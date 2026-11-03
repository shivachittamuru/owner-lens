"""Fixture-only Feature 9A identity, partial-order and reproducibility checks."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_underwriting import source as source  # noqa: PLC0414
from test_underwriting_loop import loop_snapshot
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.challenger import run_challenger
from owner_lens.cli import main
from owner_lens.opportunity_comparison import (
    ComparisonError,
    Opportunity,
    UnderwritingSelection,
    compare_pair,
    compare_underwritings,
    comparison_rows,
    load_opportunity,
)
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.records import (
    UniverseConstituentRecord,
    UniverseSnapshotRecord,
)
from owner_lens.screening import ScreeningDimension
from owner_lens.underwriting import (
    Reference,
    SemanticType,
    Statement,
    UnderwritingSnapshot,
    create_underwriting,
    parse_manual_input,
)
from owner_lens.valuation import run_valuation
from owner_lens.workbench.data import WorkbenchSource


def snapshot(*, price: float = 20, band: str = "ADEQUATE") -> UnderwritingSnapshot:
    original = loop_snapshot()
    evidence = json.loads(original.evidence_json)
    evidence["eod_price"]["value"]["close"] = price
    evidence["feature7_context"] = {
        "priority": "WORTH_UNDERWRITING",
        "setup_type": "COMPOUNDER",
        "coverage": "FULL",
        "dimensions": {item.value: band for item in ScreeningDimension},
    }
    return replace(
        original,
        evidence_json=json.dumps(evidence),
        manual=replace(
            original.manual,
            supporting_evidence=(
                Statement(SemanticType.JUDGMENT, "Fixture supporting interpretation."),
            ),
            disconfirming_evidence=(
                Statement(SemanticType.JUDGMENT, "Fixture contrary interpretation."),
            ),
        ),
    )


def persist(
    store: SqliteStore, ticker: str, data: UnderwritingSnapshot, *, valued: bool = True
) -> UnderwritingSelection:
    security = next(
        (item for item in store.list_securities() if item.symbol == ticker), None
    )
    if security is None:
        payload = json.dumps([{"symbol": ticker}]).encode()
        store.save_universe_snapshot(
            UniverseSnapshotRecord(
                "fmp",
                "2026-06-02",
                f"fixture://{ticker}",
                compute_content_hash(payload),
            ),
            (UniverseConstituentRecord(ticker, ticker, None),),
            raw_payload=payload,
            state_symbols=(),
            datasets=(),
            created_at="2026-06-02",
        )
        security = next(
            item for item in store.list_securities() if item.symbol == ticker
        )
    record = store.save_underwriting(
        security_id=security.security_id,
        ticker=ticker,
        created_at="2026-06-02T12:00:00+00:00",
        as_of_date="2026-06-02",
        snapshot_json=data.to_json(),
    )
    if valued:
        run_valuation(store, record)
    return UnderwritingSelection(ticker, record.version)


@pytest.mark.parametrize(
    "value", ["ADBE", "ADBE:latest", "ADBE:0", "ADBE:-1", "ADBE:1.0", "ADBE:1:2"]
)
def test_explicit_version_required(value: str) -> None:
    with pytest.raises(ComparisonError):
        UnderwritingSelection.parse(value)


def test_exact_versions_and_v1_v2_isolation(store: SqliteStore) -> None:
    first = persist(store, "ADBE", snapshot())
    other = persist(store, "MSFT", snapshot(price=25))
    before = compare_underwritings(store, (first, other)).to_json()
    second = persist(store, "ADBE", snapshot(price=10))
    assert second.version == 2
    assert compare_underwritings(store, (first, other)).to_json() == before
    newer = compare_underwritings(store, (second, other))
    assert newer.opportunities[0].summary.current_price == 10
    assert json.loads(before)["opportunities"][0]["summary"]["current_price"] == 20
    assert (
        newer.opportunities[0].summary.underwriting_id
        != json.loads(before)["opportunities"][0]["summary"]["underwriting_id"]
    )
    with pytest.raises(ComparisonError, match="not found"):
        compare_underwritings(store, (UnderwritingSelection("ADBE", 99), other))
    # Comparing two versions of one company is intentionally supported.
    assert len(compare_underwritings(store, (first, second)).pairs) == 1


def test_return_downside_and_scenarios(store: SqliteStore) -> None:
    a = persist(store, "ADBE", snapshot(price=20))
    b = persist(store, "MSFT", snapshot(price=30))
    report = compare_underwritings(store, (a, b))
    left, right = report.opportunities
    assert left.summary.expected_5y_cagr > right.summary.expected_5y_cagr
    assert left.bear_cagr > right.bear_cagr
    assert "HIGHER_EXPECTED_RETURN" in report.pairs[0].left_flags
    assert "BETTER_DOWNSIDE_PROTECTION" in report.pairs[0].left_flags
    assert left.summary.loss_probability == 0.25
    assert len(left.summary.scenarios) == 3
    assert left.summary.scenarios[0].terminal_return == -0.5
    rows = {row["Metric"]: row for row in comparison_rows(report)}
    assert (
        rows["Bear / Base / Bull probabilities"]["ADBE:1"] == "25.00% / 50.00% / 25.00%"
    )
    assert rows["Feature 8 classification"]["ADBE:1"] == left.summary.classification


def test_missing_evidence_is_explicit_and_needs_research(store: SqliteStore) -> None:
    original = snapshot()
    weak = replace(
        original,
        manual=replace(
            original.manual,
            supporting_evidence=(),
            disconfirming_evidence=(),
        ),
    )
    a, b = persist(store, "ADBE", weak), persist(store, "MSFT", original)
    report = compare_underwritings(store, (a, b))
    item = report.opportunities[0]
    assert "WEAKER_EVIDENCE" in item.flags
    assert not item.quality.supporting_evidence
    assert any("incomplete evidence" in reason for reason in item.research_attention)
    assert any(
        "supporting_evidence" in reason for reason in item.quality.missing_dimensions
    )
    assert (
        item.quality.biggest_uncertainty == original.manual.thesis.biggest_uncertainty
    )
    assert item.quality.major_unresolved_questions


def test_variant_documentation_not_size_or_truth(store: SqliteStore) -> None:
    original = snapshot()
    unsupported = replace(
        original, manual=replace(original.manual, variant_rationales=())
    )
    a, b = persist(store, "ADBE", original), persist(store, "MSFT", unsupported)
    report = compare_underwritings(store, (a, b))
    assert "STRONGER_VARIANT_VIEW" in report.pairs[0].left_flags
    assert report.opportunities[0].quality.documented_variant is True
    assert report.opportunities[1].quality.documented_variant is False
    evidence = json.loads(original.evidence_json)
    evidence.pop("market_expectations")
    unknown = persist(
        store, "GOOGL", replace(original, evidence_json=json.dumps(evidence))
    )
    pair = compare_underwritings(store, (a, unknown)).pairs[0]
    assert "STRONGER_VARIANT_VIEW" not in pair.left_flags
    assert "documented variant" in pair.missing_dimensions


def improved(item: Opportunity, **changes: Any) -> Opportunity:
    """Keep local sensitivity fixed while isolating the partial-order dimensions."""
    scenarios = list(item.summary.scenarios)
    bear = changes.pop("bear", item.bear_cagr)
    scenarios[0] = replace(scenarios[0], implied_cagr=bear)
    return replace(
        item,
        summary=replace(
            item.summary,
            underwriting_id="fixture-other",
            ticker="MSFT",
            scenarios=tuple(scenarios),
            **changes,
        ),
    )


def test_dominance_strict_core_and_ties(store: SqliteStore) -> None:
    item = load_opportunity(store, persist(store, "ADBE", snapshot()))
    better = improved(item, expected_5y_cagr=item.summary.expected_5y_cagr + 0.02)
    pair = compare_pair(better, item)
    assert pair.conclusion == "DOMINATED"
    assert pair.dominated == item.label
    assert "DOMINATED" in pair.right_flags
    assert compare_pair(item, better).dominated == item.label
    assert compare_pair(item, item).dominated is None


@pytest.mark.parametrize(
    "conflict",
    [
        "downside",
        "spread",
        "evidence",
        "quality",
        "sensitivity",
        "variant",
        "loss",
        "capital_efficiency",
    ],
)
def test_tradeoffs_never_false_dominance(store: SqliteStore, conflict: str) -> None:
    item = load_opportunity(store, persist(store, "ADBE", snapshot()))
    better = improved(item, expected_5y_cagr=item.summary.expected_5y_cagr + 0.02)
    if conflict == "downside":
        better = improved(better, bear=item.bear_cagr - 0.01)
    elif conflict == "spread":
        better = replace(
            better,
            summary=replace(
                better.summary, return_spread=item.summary.return_spread - 0.01
            ),
        )
    elif conflict == "evidence":
        better = replace(
            better, quality=replace(better.quality, disconfirming_evidence=())
        )
    elif conflict == "quality":
        better = replace(
            better,
            business=replace(
                better.business, dimensions=(("BUSINESS_QUALITY", "POOR"),)
            ),
        )
    elif conflict == "sensitivity":
        better = replace(
            better, quality=replace(better.quality, sensitivity_cagr_delta=0.1)
        )
    elif conflict == "variant":
        better = replace(
            better, quality=replace(better.quality, documented_variant=False)
        )
    elif conflict == "loss":
        better = replace(better, summary=replace(better.summary, loss_probability=0.9))
    else:
        better = replace(
            better,
            business=replace(
                better.business,
                dimensions=tuple(
                    (name, "POOR" if name == "CAPITAL_EFFICIENCY" else value)
                    for name, value in better.business.dimensions
                ),
            ),
        )
    pair = compare_pair(better, item)
    assert pair.conclusion == "TRADEOFF"
    assert pair.dominated is None
    assert "TRADEOFF" in pair.left_flags and "TRADEOFF" in pair.right_flags


def test_missing_quality_blocks_dominance_and_no_missing_to_neutral(
    store: SqliteStore,
) -> None:
    original = snapshot()
    evidence = json.loads(original.evidence_json)
    evidence.pop("feature7_context")
    missing = replace(original, evidence_json=json.dumps(evidence))
    a, b = persist(store, "ADBE", missing), persist(store, "MSFT", original)
    report = compare_underwritings(store, (a, b))
    assert report.pairs[0].dominated is None
    assert report.opportunities[0].business.band("BUSINESS_QUALITY") is None
    assert "business quality" in report.pairs[0].missing_dimensions
    assert (
        "MISSING"
        in next(
            row
            for row in comparison_rows(report)
            if row["Metric"] == "Business Quality"
        )["ADBE:1"]
    )


def test_missing_investor_evidence_never_qualifies_for_dominance(
    store: SqliteStore,
) -> None:
    original = snapshot()
    absent = replace(
        original,
        manual=replace(
            original.manual,
            supporting_evidence=(),
            disconfirming_evidence=(),
        ),
    )
    item = load_opportunity(store, persist(store, "ADBE", absent))
    better = improved(item, expected_5y_cagr=item.summary.expected_5y_cagr + 0.02)
    pair = compare_pair(better, item)
    assert pair.dominated is None
    assert pair.conclusion == "INCOMPLETE"
    assert "Missing investor evidence blocks dominance" in pair.key_tradeoff


def test_new_authoring_freezes_feature7_and_preserves_old_versions(
    source: WorkbenchSource,
) -> None:
    sample = (
        Path(__file__).parents[1]
        / "docs"
        / "examples"
        / "adbe_consolidated_underwriting.sample.json"
    )
    manual = parse_manual_input(json.loads(sample.read_text()))
    first = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    assert isinstance(source.store, SqliteStore)
    run_valuation(source.store, first)
    saved = UnderwritingSnapshot.from_json(first.snapshot_json)
    assert saved.schema_version == 2
    context = json.loads(saved.evidence_json)["feature7_context"]
    assert set(context["dimensions"]) == {item.value for item in ScreeningDimension}
    loaded = load_opportunity(
        source.store, UnderwritingSelection("ADBE", first.version)
    )
    assert loaded.business.priority == context["priority"]
    assert dict(loaded.business.dimensions) == context["dimensions"]
    before = loaded.summary.to_json()
    revised = replace(
        manual,
        thesis=replace(manual.thesis, biggest_uncertainty="Revised uncertainty."),
    )
    second = create_underwriting(
        source, "ADBE", revised, now=datetime(2026, 6, 2, 13, tzinfo=UTC)
    )
    run_valuation(source.store, second)
    report = compare_underwritings(
        source.store,
        (
            UnderwritingSelection("ADBE", first.version),
            UnderwritingSelection("ADBE", second.version),
        ),
    )
    assert report.opportunities[0].summary.to_json() == before
    assert (
        report.opportunities[0].quality.biggest_uncertainty
        != report.opportunities[1].quality.biggest_uncertainty
    )


def test_feature7_reused_without_recomputation(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = persist(store, "ADBE", snapshot(band="STRONG"))
    b = persist(store, "MSFT", snapshot(band="WEAK"))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Comparison must not recompute Feature 7.")

    monkeypatch.setattr("owner_lens.screening.screen_company_from_history", forbidden)
    monkeypatch.setattr(
        "owner_lens.underwriting.screen_company_from_history", forbidden
    )
    monkeypatch.setattr(store, "get_underwriting_evidence", forbidden)
    monkeypatch.setattr(store, "list_challenger_runs", forbidden)
    pair = compare_underwritings(store, (a, b)).pairs[0]
    assert "HIGHER_BUSINESS_QUALITY" in pair.left_flags
    assert pair.dominated == "MSFT:1"


@pytest.mark.parametrize(
    "field", ["reference", "evidence_date", "annual_source", "consensus", "price"]
)
def test_no_lookahead_for_legacy_and_v2(store: SqliteStore, field: str) -> None:
    original = snapshot()
    evidence = json.loads(original.evidence_json)
    future = "2026-06-03T00:00:00+00:00"
    if field == "reference":
        original = replace(
            original,
            manual=replace(
                original.manual,
                supporting_evidence=(
                    Statement(
                        SemanticType.JUDGMENT,
                        "Future",
                        (Reference(observed_at=future),),
                    ),
                ),
            ),
        )
    elif field == "evidence_date":
        original = replace(
            original,
            manual=replace(
                original.manual,
                supporting_evidence=(
                    Statement(
                        SemanticType.JUDGMENT, "Future", evidence_date="2026-06-03"
                    ),
                ),
            ),
        )
    elif field == "annual_source":
        evidence["annual_sources"] = [{"fetched_at": future}]
    elif field == "consensus":
        evidence["market_expectations"]["snapshots"][0]["source"]["fetched_at"] = future
    else:
        evidence["eod_price"]["value"]["fetched_at"] = future
    invalid = persist(
        store,
        "ADBE",
        replace(original, evidence_json=json.dumps(evidence)),
        valued=False,
    )
    with pytest.raises(ComparisonError, match="cutoff"):
        load_opportunity(store, invalid)


def test_completion_count_duplicates_and_unordered_scenarios(
    store: SqliteStore,
) -> None:
    a = persist(store, "ADBE", snapshot())
    with pytest.raises(ComparisonError, match="2 to 5"):
        compare_underwritings(store, (a,))
    with pytest.raises(ComparisonError, match="Duplicate"):
        compare_underwritings(store, (a, a))
    unvalued = persist(store, "MSFT", snapshot(), valued=False)
    with pytest.raises(ComparisonError, match="No saved"):
        compare_underwritings(store, (a, unvalued))
    incomplete = snapshot()
    incomplete = replace(
        incomplete, manual=replace(incomplete.manual, investor_policy=None)
    )
    b = persist(store, "GOOGL", incomplete)
    with pytest.raises(ComparisonError, match="required return"):
        compare_underwritings(store, (a, b))
    unordered = snapshot()
    scenarios = list(unordered.manual.scenarios)
    scenarios[0] = replace(scenarios[0], terminal_fcf_multiple=1000)
    c = persist(
        store,
        "COST",
        replace(
            unordered, manual=replace(unordered.manual, scenarios=tuple(scenarios))
        ),
    )
    with pytest.raises(ComparisonError, match="unordered"):
        compare_underwritings(store, (a, c))


def test_stable_json_cli_and_no_writes(
    store: SqliteStore, capsys: pytest.CaptureFixture[str]
) -> None:
    selections = tuple(
        persist(store, ticker, snapshot(price=price))
        for ticker, price in (
            ("ADBE", 20),
            ("MSFT", 25),
            ("GOOGL", 30),
        )
    )
    before = store._conn.total_changes
    report = compare_underwritings(store, selections)
    assert (
        report.to_json()
        == compare_underwritings(store, tuple(reversed(selections))).to_json()
    )
    assert store._conn.total_changes == before
    assert main(["compare-underwriting", "ADBE:1", "MSFT:1", "GOOGL:1", "--json"]) == 0
    assert capsys.readouterr().out.strip() == report.to_json()
    assert main(["compare-underwriting", "ADBE:1", "MSFT:1"]) == 0
    text = capsys.readouterr().out
    for label in (
        "Research attention:",
        "Capital attractiveness:",
        "Unresolved issue:",
        "not a recommendation",
    ):
        assert label in text
    assert main(["compare-underwriting", "ADBE:99", "MSFT:1"]) == 1
    assert "not found" in capsys.readouterr().err
    assert main(["compare-underwriting", "ADBE", "MSFT:1"]) == 1
    assert "TICKER:VERSION" in capsys.readouterr().err


def test_workbench_selects_exact_completed_versions(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    persist(store, "ADBE", snapshot(price=10))
    persist(store, "MSFT", snapshot(price=25))
    persist(store, "GOOGL", snapshot(), valued=False)
    for ticker in ("ADBE", "MSFT"):
        for record in store.list_underwriting(ticker):
            run_challenger(store, record)
    app_path = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120)
    app.session_state["page"] = "Opportunity Comparison"
    app.run()
    assert not app.exception and not app.error
    picker = app.multiselect(key="opportunity_companies")
    assert set(picker.options) == {"ADBE — Adobe", "MSFT — MSFT"}
    assert picker.value == []
    picker.set_value(["ADBE", "MSFT"]).run()
    assert not app.exception and not app.error
    assert app.dataframe
    frame = app.dataframe[0].value
    assert "ADBE:2" in frame.columns and "ADBE:1" not in frame.columns
    assert frame.loc["Frozen price / market date", "ADBE:2"].startswith("$10.00")
    app.selectbox(key="opportunity_version.ADBE").set_value("ADBE:1").run()
    assert not app.exception and not app.error
    assert "ADBE:1" in app.dataframe[0].value.columns
    assert not app.text_input and not app.number_input

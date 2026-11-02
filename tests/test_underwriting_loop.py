"""Offline 8E probability, expected-return and challenger contract regression tests."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_underwriting import _save_snapshot
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import _persist, record_from
from test_valuation import store as store  # noqa: PLC0414
from test_variant import variant_snapshot

from owner_lens.challenger import (
    ChallengerContext,
    ChallengerError,
    Citation,
    RuleBasedChallenger,
    build_context,
    run_challenger,
    validate_output,
)
from owner_lens.cli import main
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.persistence.records import FmpEstimateRecord
from owner_lens.underwriting import (
    Reference,
    ScenarioName,
    SemanticType,
    Statement,
    UnderwritingError,
    UnderwritingSnapshot,
    create_underwriting,
    parse_investor_policy,
    parse_manual_input,
    parse_probabilities,
)
from owner_lens.underwriting_summary import (
    SummaryError,
    classify_return,
    saved_valuation,
    summarize_underwriting,
)
from owner_lens.valuation import run_valuation, value_underwriting
from owner_lens.workbench.data import WorkbenchSource


def probability_input(
    bear: float = 0.25, base: float = 0.5, bull: float = 0.25
) -> dict[str, Any]:
    return {
        "category": "JUDGMENT",
        "rationale": "Illustrative fixture-only manual distribution.",
        "scenarios": [
            {"name": name, "probability": value, "category": "JUDGMENT"}
            for name, value in (("BEAR", bear), ("BASE", base), ("BULL", bull))
        ],
    }


def loop_snapshot() -> UnderwritingSnapshot:
    snapshot = variant_snapshot()
    return replace(
        snapshot,
        manual=replace(
            snapshot.manual,
            probability_distribution=parse_probabilities(probability_input()),
            investor_policy=parse_investor_policy(
                {"category": "JUDGMENT", "required_return": 0.12}
            ),
        ),
    )


@pytest.mark.parametrize(
    "value", [-0.01, 1.01, True, "0.25", None, float("nan"), float("inf"), 10**1000]
)
def test_invalid_probability(value: Any) -> None:
    data = probability_input()
    data["scenarios"][0]["probability"] = value
    with pytest.raises(UnderwritingError):
        parse_probabilities(data)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["scenarios"].pop(),
        lambda d: d["scenarios"].append(d["scenarios"][0]),
        lambda d: d["scenarios"][0].update(name="OTHER"),
        lambda d: d.update(category="ASSUMPTION"),
        lambda d: d["scenarios"][0].update(category="CALCULATION"),
        lambda d: d["scenarios"][0].pop("probability"),
        lambda d: d.update(unapproved=True),
    ],
)
def test_missing_duplicate_or_wrongly_typed_probabilities(mutation: Any) -> None:
    data = probability_input()
    mutation(data)
    with pytest.raises(UnderwritingError):
        parse_probabilities(data)


def test_sum_tolerance_never_normalizes_or_generates() -> None:
    with pytest.raises(UnderwritingError, match="sum"):
        parse_probabilities(probability_input(0.2, 0.5, 0.2))
    parsed = parse_probabilities(probability_input(0.25, 0.5, 0.25 + 5e-10))
    assert parsed.scenarios[2].probability == 0.25 + 5e-10
    assert math.fsum(item.probability for item in parsed.scenarios) != 1
    with pytest.raises(UnderwritingError, match="sum"):
        parse_probabilities(probability_input(0.25, 0.5, 0.25 + 2e-9))
    data = json.loads(loop_snapshot().to_json())["manual"]
    data["scenarios"] = []
    data["forward_assumptions"] = [
        {
            "name": "terminal_assumption",
            "value": "qualitative",
            "rationale": "manual",
            "category": "ASSUMPTION",
        }
    ]
    with pytest.raises(UnderwritingError, match="complete"):
        parse_manual_input(data)


@pytest.mark.parametrize(
    "value", [-1, -2, float("inf"), float("nan"), None, "0.12", True]
)
def test_invalid_investor_policy(value: Any) -> None:
    with pytest.raises(UnderwritingError):
        parse_investor_policy({"required_return": value, "category": "JUDGMENT"})


def test_semantics_round_trip_and_legacy_bytes() -> None:
    snapshot = loop_snapshot()
    payload = snapshot.to_json()
    reloaded = UnderwritingSnapshot.from_json(payload)
    assert reloaded.to_json() == payload
    assert reloaded.manual.probability_distribution.category is SemanticType.JUDGMENT
    assert all(
        item.category is SemanticType.JUDGMENT
        for item in reloaded.manual.probability_distribution.scenarios
    )
    assert reloaded.manual.scenarios[0].category is SemanticType.ASSUMPTION
    assert reloaded.manual.investor_policy.category is SemanticType.JUDGMENT
    legacy = variant_snapshot().to_json()
    assert "probability_distribution" not in legacy and "investor_policy" not in legacy
    assert UnderwritingSnapshot.from_json(legacy).to_json() == legacy


def test_expected_terminal_value_cagr_context_and_not_average_cagr() -> None:
    record = record_from(loop_snapshot())
    valuation = value_underwriting(record).to_json()
    summary = summarize_underwriting(record, valuation)
    values = [
        1000 * (1 + growth) ** 5 * margin * multiple / (100 * (1 + shares) ** 5)
        for growth, margin, shares, multiple in (
            (0, 0.1, 0, 10),
            (0.1, 0.2, -0.02, 20),
            (0.2, 0.3, -0.04, 30),
        )
    ]
    expected = 0.25 * values[0] + 0.5 * values[1] + 0.25 * values[2]
    assert summary.expected_terminal_value_per_share == pytest.approx(expected)
    assert summary.expected_5y_cagr == pytest.approx((expected / 20) ** 0.2 - 1)
    weighted_cagr = sum(
        item.probability.probability * item.implied_cagr for item in summary.scenarios
    )
    assert summary.expected_5y_cagr != pytest.approx(weighted_cagr)
    assert summary.return_spread == pytest.approx(summary.expected_5y_cagr - 0.12)
    assert summary.classification == "ATTRACTIVE"
    assert summary.loss_probability == 0.25 and summary.gain_probability == 0.75
    assert summary.weighted_downside == pytest.approx(0.25 * 0.5)
    assert summary.weighted_upside - summary.weighted_downside == pytest.approx(
        expected / 20 - 1
    )
    assert [item.name for item in summary.scenarios] == list(ScenarioName)
    assert [item.value_per_share for item in summary.scenarios] == pytest.approx(values)
    assert summary.category is SemanticType.CALCULATION
    assert summary.scenarios[0].probability.category is SemanticType.JUDGMENT
    assert summary.valuation_content_hash == compute_content_hash(valuation.encode())
    assert summarize_underwriting(record, valuation).to_json() == summary.to_json()


@pytest.mark.parametrize(
    "spread,classification",
    [
        (-0.02, "UNATTRACTIVE"),
        (-0.01001, "UNATTRACTIVE"),
        (-0.01, "WATCH"),
        (0, "WATCH"),
        (0.01, "WATCH"),
        (0.01001, "INTERESTING"),
        (0.02999, "INTERESTING"),
        (0.03, "ATTRACTIVE"),
        (0.1, "ATTRACTIVE"),
    ],
)
def test_transparent_classification_boundaries(
    spread: float, classification: str
) -> None:
    assert classify_return(spread)[0] == classification
    assert classify_return(spread, ordered=False)[0] == "INSUFFICIENT"


def test_missing_inputs_explicit_policy_override_and_saved_valuation_binding(
    store: SqliteStore,
) -> None:
    record = _persist(store, loop_snapshot())
    with pytest.raises(SummaryError, match="saved"):
        saved_valuation(store, record)
    valuation = run_valuation(store, record)
    summary = summarize_underwriting(record, valuation, required_return=0.2)
    assert summary.investor_policy.required_return == 0.2
    assert summary.policy_source == "explicit_evaluation"
    assert (
        UnderwritingSnapshot.from_json(
            record.snapshot_json
        ).manual.investor_policy.required_return
        == 0.12
    )
    missing = record_from(variant_snapshot())
    with pytest.raises(SummaryError, match="probabilities"):
        summarize_underwriting(
            missing, value_underwriting(missing).to_json(), required_return=0.12
        )
    snapshot = loop_snapshot()
    absent_policy = record_from(
        replace(snapshot, manual=replace(snapshot.manual, investor_policy=None))
    )
    with pytest.raises(SummaryError, match="required return"):
        summarize_underwriting(
            absent_policy, value_underwriting(absent_policy).to_json()
        )
    assert summarize_underwriting(
        absent_policy, value_underwriting(absent_policy).to_json(), required_return=0.12
    )
    altered = json.loads(valuation)
    altered["underwriting_content_hash"] = "wrong"
    with pytest.raises(SummaryError, match="differs"):
        summarize_underwriting(record, json.dumps(altered))
    altered = json.loads(valuation)
    altered["scenarios"][0]["year5_value_per_share"] = 99
    with pytest.raises(SummaryError):
        summarize_underwriting(record, json.dumps(altered))


def test_zero_terminal_value_and_unordered_scenarios() -> None:
    snapshot = loop_snapshot()
    zero = tuple(
        replace(item, fcf_margin_year5=0) for item in snapshot.manual.scenarios
    )
    record = record_from(
        replace(snapshot, manual=replace(snapshot.manual, scenarios=zero))
    )
    summary = summarize_underwriting(record, value_underwriting(record).to_json())
    assert (
        summary.expected_terminal_value_per_share == 0
        and summary.expected_5y_cagr == -1
    )
    assert summary.loss_probability == 1
    inverse = tuple(
        replace(item, terminal_fcf_multiple=5000)
        if item.name is ScenarioName.BEAR
        else item
        for item in snapshot.manual.scenarios
    )
    record = record_from(
        replace(snapshot, manual=replace(snapshot.manual, scenarios=inverse))
    )
    assert (
        summarize_underwriting(
            record, value_underwriting(record).to_json()
        ).classification
        == "INSUFFICIENT"
    )


def test_immutable_probability_v1_v2_and_cli(
    store: SqliteStore, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _persist(store, loop_snapshot())
    first_valuation = run_valuation(store, first)
    original = summarize_underwriting(first, first_valuation).to_json()
    snapshot = loop_snapshot()
    changed = replace(
        snapshot,
        manual=replace(
            snapshot.manual,
            probability_distribution=parse_probabilities(
                probability_input(0.5, 0.4, 0.1)
            ),
        ),
    )
    second = _persist(store, changed)
    second_valuation = run_valuation(store, second)
    revised = summarize_underwriting(second, second_valuation)
    assert (
        revised.expected_terminal_value_per_share
        < json.loads(original)["expected_terminal_value_per_share"]
    )
    assert first.version == 1 and second.version == 2
    assert saved_valuation(store, first) == first_valuation
    assert (
        summarize_underwriting(
            store.list_underwriting("ADBE")[0], first_valuation
        ).to_json()
        == original
    )
    assert (
        main(
            [
                "underwriting",
                "summary",
                "ADBE",
                "--version",
                "1",
                "--required-return",
                "0.12",
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["expected_5y_cagr"] == json.loads(original)["expected_5y_cagr"]
    assert main(["underwriting", "summary", "ADBE", "--version", "99"]) == 1
    assert "not found" in capsys.readouterr().err
    assert (
        main(
            [
                "underwriting",
                "summary",
                "ADBE",
                "--version",
                "1",
                "--required-return",
                "nan",
            ]
        )
        == 1
    )
    assert "finite" in capsys.readouterr().err


def test_challenger_read_only_semantics_citations_and_missing_evidence(
    store: SqliteStore,
) -> None:
    record = _persist(store, loop_snapshot())
    valuation = run_valuation(store, record)
    run = run_challenger(store, record)
    assert store.list_underwriting("ADBE") == (record,)
    assert saved_valuation(store, record) == valuation
    assert run.underwriting_id == record.underwriting_id
    assert run.underwriting_version == record.version
    assert run.underwriting_content_hash == record.content_hash
    assert run.input_content_hash == compute_content_hash(run.context_json.encode())
    assert run.output_content_hash == compute_content_hash(run.output_json.encode())
    assert store.list_challenger_runs(record.underwriting_id) == (run,)
    output = json.loads(run.output_json)
    assert output["category"] == "JUDGMENT"
    assert output["missing_evidence"] and output["alternative_explanations"]
    assert any(not item["evidence_available"] for item in output["missing_evidence"])
    assert output["contradictory_evidence"][0]["evidence_available"] is False
    assert "NOT_ASSESSED_AUTOMATICALLY" in output["thesis_breaker_quality"]["text"]
    assert output["overall_assessment"]["references"]
    for name, value in output.items():
        if name == "category":
            continue
        for item in value if isinstance(value, list) else [value]:
            assert item["category"] == "JUDGMENT"
            assert item["references"]
    context = ChallengerContext(run.context_json)
    assert RuleBasedChallenger().challenge(context).to_json() == run.output_json
    validate_output(RuleBasedChallenger().challenge(context), context)
    assert (
        json.loads(run.context_json)["snapshot"]["manual"]["probability_distribution"]
        == (json.loads(record.snapshot_json)["manual"]["probability_distribution"])
    )


def test_challenger_probability_evidence_and_variant_checks() -> None:
    snapshot = loop_snapshot()
    snapshot = replace(
        snapshot,
        manual=replace(
            snapshot.manual,
            probability_distribution=parse_probabilities(
                probability_input(0, 0.5, 0.5)
            ),
            supporting_evidence=(
                Statement(SemanticType.JUDGMENT, "My interpretation"),
            ),
            disconfirming_evidence=(
                Statement(SemanticType.EXPECTATION, "Recorded conflicting forecast"),
            ),
            variant_rationales=(),
        ),
    )
    record = record_from(snapshot)
    context = build_context(record, value_underwriting(record).to_json())
    output = RuleBasedChallenger().challenge(context)
    assert any("10%" in item.text for item in output.probability_challenges)
    assert any("zero weight" in item.text for item in output.probability_challenges)
    assert any("interpretation" in item.text for item in output.missing_evidence)
    assert (
        output.contradictory_evidence[0].references[0].source_category
        is SemanticType.EXPECTATION
    )
    assert "price/quality thesis" in output.variant_view_challenge.text
    assert output.alternative_explanations[0].evidence_available is False
    validate_output(output, context)


def test_challenger_cannot_mutate_context_and_bad_outputs_are_not_saved(
    store: SqliteStore,
) -> None:
    record = _persist(store, loop_snapshot())
    run_valuation(store, record)

    class FrozenBackend:
        model_version = "fixture-read-only"

        def challenge(self, context: ChallengerContext) -> Any:
            with pytest.raises(FrozenInstanceError):
                context.json_payload = "{}"
            local = json.loads(context.json_payload)
            local["snapshot"]["manual"]["probability_distribution"]["scenarios"][0][
                "probability"
            ] = 1
            return RuleBasedChallenger().challenge(context)

    run_challenger(store, record, backend=FrozenBackend())
    assert store.list_underwriting("ADBE") == (record,)

    class InvalidBackend:
        model_version = "invalid-fixture"

        def challenge(self, context: ChallengerContext) -> Any:
            return replace(
                RuleBasedChallenger().challenge(context), category=SemanticType.FACT
            )

    with pytest.raises(ChallengerError, match="JUDGMENT"):
        run_challenger(store, record, backend=InvalidBackend())
    assert len(store.list_challenger_runs(record.underwriting_id)) == 1
    context = build_context(record, value_underwriting(record).to_json())
    output = RuleBasedChallenger().challenge(context)
    citation = Citation("/future/evidence", SemanticType.FACT, "null")
    bad = replace(
        output,
        strongest_argument_against=replace(
            output.strongest_argument_against, references=(citation,)
        ),
    )
    with pytest.raises(ChallengerError, match="frozen"):
        validate_output(bad, context)


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE challenger_runs SET output_json='{}'",
        "DELETE FROM challenger_runs",
        "INSERT OR REPLACE INTO challenger_runs SELECT * FROM challenger_runs",
    ],
)
def test_append_only_challenger_runs(store: SqliteStore, operation: str) -> None:
    record = _persist(store, loop_snapshot())
    run_valuation(store, record)
    run = run_challenger(store, record)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(operation)
    store._conn.rollback()
    assert store.list_challenger_runs(record.underwriting_id) == (run,)


def test_challenger_identity_guard_and_corruption_detection(store: SqliteStore) -> None:
    record = _persist(store, loop_snapshot())
    run_valuation(store, record)
    run = run_challenger(store, record)
    with pytest.raises(StorageWriteError, match="match"):
        store.save_challenger_run(
            replace(record, content_hash="wrong"),
            challenger_version="fixture",
            model_version="fixture",
            created_at=run.created_at,
            context_json=run.context_json,
            output_json=run.output_json,
        )
    store._conn.execute("DROP TRIGGER challenger_no_update")
    store._conn.execute("UPDATE challenger_runs SET output_json='{}'")
    store._conn.commit()
    with pytest.raises(StorageReadError, match="integrity"):
        store.list_challenger_runs(record.underwriting_id)


def test_challenger_run_show_version_isolation_and_no_current_reads(
    store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _persist(store, loop_snapshot())
    run_valuation(store, first)
    monkeypatch.setattr(
        SqliteStore,
        "get_underwriting_evidence",
        lambda *a, **kw: pytest.fail("No new evidence"),
    )
    assert main(["challenger", "show", "ADBE", "--version", "1"]) == 1
    assert "Run 'challenger run'" in capsys.readouterr().err
    assert main(["challenger", "run", "ADBE", "--version", "1"]) == 0
    old = json.loads(capsys.readouterr().out)
    second = _persist(store, loop_snapshot())
    run_valuation(store, second)
    assert main(["challenger", "run", "ADBE", "--version", "2"]) == 0
    new = json.loads(capsys.readouterr().out)
    assert new["underwriting_id"] != old["underwriting_id"]
    assert (
        main(
            ["challenger", "show", "ADBE", "--version", "1", "--run-id", old["run_id"]]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == old
    assert (
        main(
            ["challenger", "show", "ADBE", "--version", "2", "--run-id", old["run_id"]]
        )
        == 1
    )
    assert "No matching" in capsys.readouterr().err
    assert len(store.list_underwriting("ADBE")) == 2


def test_real_asof_capture_and_newer_estimates_cannot_change_summary_or_challenger(
    source: WorkbenchSource,
) -> None:
    assert isinstance(source.store, SqliteStore)
    store = source.store
    manual = loop_snapshot().manual
    first = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    valuation = run_valuation(store, first)
    summary = summarize_underwriting(first, valuation).to_json()
    run = run_challenger(store, first, now=datetime(2026, 6, 2, 13, tzinfo=UTC))
    newer_id = _save_snapshot(
        store,
        "annual_analyst_estimates",
        b'[{"later":true}]',
        observed="2026-06-03T12:00:00+00:00",
        period="annual",
    )
    store.save_fmp_estimates(
        (
            FmpEstimateRecord(
                newer_id, "2028-11-30", 27e9, 30e9, 33e9, 12, 10, 12, 14, 12
            ),
        )
    )
    backdated = create_underwriting(
        source,
        "ADBE",
        replace(manual, as_of_date="2026-06-02"),
        now=datetime(2026, 6, 4, 12, tzinfo=UTC),
    )
    second = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 4, 12, tzinfo=UTC)
    )
    assert (
        summarize_underwriting(backdated, run_valuation(store, backdated))
        .variant.drivers[0]
        .consensus.snapshot_id
        != newer_id
    )
    assert (
        summarize_underwriting(second, run_valuation(store, second))
        .variant.drivers[0]
        .consensus.snapshot_id
        == newer_id
    )
    assert (
        summarize_underwriting(
            store.list_underwriting("ADBE")[0], saved_valuation(store, first)
        ).to_json()
        == summary
    )
    repeated = run_challenger(store, first, now=datetime(2026, 6, 5, 12, tzinfo=UTC))
    assert (
        repeated.input_content_hash == run.input_content_hash
        and repeated.output_json == run.output_json
    )
    assert repeated.run_id != run.run_id  # Separate append-only advisory runs.


def test_v5_migration_preserves_snapshots_valuations_and_installs_challenger(
    store: SqliteStore,
) -> None:
    record = _persist(store, loop_snapshot())
    valuation = run_valuation(store, record)
    store._conn.execute("DROP TABLE challenger_runs")
    store._conn.execute("UPDATE schema_meta SET value='5' WHERE key='schema_version'")
    store._conn.commit()
    store.initialize()
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "9"
    )
    assert (
        store.list_underwriting("ADBE") == (record,)
        and saved_valuation(store, record) == valuation
    )
    assert run_challenger(store, record)


def test_sample_input_end_to_end_and_missing_probability_challenger(
    source: WorkbenchSource,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = (
        Path(__file__).parents[1]
        / "docs"
        / "examples"
        / "adbe_probability_underwriting.sample.json"
    )
    copied = tmp_path / "ADBE-loop.json"
    copied.write_bytes(sample.read_bytes())
    assert main(["underwriting", "create", "ADBE", "--file", str(copied)]) == 0
    assert "v1" in capsys.readouterr().out
    assert main(["valuation", "run", "ADBE", "--version", "1"]) == 0
    capsys.readouterr()
    assert main(["underwriting", "summary", "ADBE", "--version", "1", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (
        summary["probability_rationale"]
        == json.loads(sample.read_text())["probability_distribution"]["rationale"]
    )
    assert summary["current_price"] == 123.45
    assert main(["challenger", "run", "ADBE", "--version", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["output"]["category"] == "JUDGMENT"
    missing = record_from(variant_snapshot())
    output = RuleBasedChallenger().challenge(
        build_context(missing, value_underwriting(missing).to_json())
    )
    assert any(
        "probabilities are unavailable" in item.text for item in output.missing_evidence
    )


def test_challenger_bounds_citation_types_and_times(store: SqliteStore) -> None:
    snapshot = loop_snapshot()
    supported = Statement(
        SemanticType.FACT,
        "Fixture cited statement",
        (Reference("Fixture source", "https://example.com"),),
    )
    snapshot = replace(
        snapshot,
        manual=replace(
            snapshot.manual,
            supporting_evidence=(supported,) * 21,
            disconfirming_evidence=(supported,) * 21,
            probability_distribution=replace(
                snapshot.manual.probability_distribution, rationale=None
            ),
        ),
    )
    record = _persist(store, snapshot)
    valuation = run_valuation(store, record)
    context = build_context(record, valuation)
    output = RuleBasedChallenger().challenge(context)
    assert len(output.contradictory_evidence) == 20
    assert any("first 20" in item.text for item in output.missing_evidence)
    assert any(
        "rationale is unavailable" in item.text
        for item in output.probability_challenges
    )
    assert any("BULL stacks" in item.text for item in output.fragile_assumptions)
    bad = replace(
        output,
        strongest_argument_against=replace(
            output.strongest_argument_against,
            references=(
                Citation("/variant/drivers/0/assumption", SemanticType.FACT, "0.1"),
            ),
        ),
    )
    with pytest.raises(ChallengerError, match="semantics"):
        validate_output(bad, context)
    bad = replace(
        output,
        strongest_argument_against=replace(
            output.strongest_argument_against,
            references=(
                replace(
                    output.strongest_argument_against.references[0], value_json="null"
                ),
            ),
        ),
    )
    with pytest.raises(ChallengerError, match="match"):
        validate_output(bad, context)
    with pytest.raises(ChallengerError, match="timezone"):
        run_challenger(store, record, now=datetime(2026, 6, 3, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ChallengerError, match="predate"):
        run_challenger(store, record, now=datetime(2026, 6, 1, tzinfo=UTC))
    assert store.list_challenger_runs(record.underwriting_id) == ()

"""Fixture-only company discovery, exact handoffs and compact 9A presentation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_opportunity_comparison import persist, snapshot
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.challenger import run_challenger
from owner_lens.opportunity_catalog import (
    ComparisonVersion,
    discover_comparison_companies,
)
from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
)
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.records import (
    UniverseConstituentRecord,
    UniverseSnapshotRecord,
)
from owner_lens.underwriting import UnderwritingSnapshot, create_underwriting
from owner_lens.valuation import run_valuation
from owner_lens.workbench.data import WorkbenchSource


def _complete(
    store: SqliteStore, ticker: str, data: UnderwritingSnapshot | None = None
) -> UnderwritingSelection:
    selection = persist(store, ticker, data or snapshot())
    record = next(
        item for item in store.list_underwriting(ticker)
        if item.version == selection.version
    )
    run_challenger(store, record)
    return selection


def _app() -> AppTest:
    app_path = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120)
    app.session_state["page"] = "Opportunity Comparison"
    return app


def _retain_current_companies(store: SqliteStore) -> None:
    payload = b'[{"symbol":"ADBE"},{"symbol":"MSFT"}]'
    store.save_universe_snapshot(
        UniverseSnapshotRecord(
            "fmp", "2026-06-02", "fixture://comparison-universe", compute_content_hash(payload)
        ),
        (
            UniverseConstituentRecord("ADBE", "Adobe", "0000796343"),
            UniverseConstituentRecord("MSFT", "Microsoft", None),
        ),
        raw_payload=payload,
        state_symbols=(),
        datasets=(),
        created_at="2026-06-02",
    )


def test_catalog_discovers_latest_fully_analyzed_and_preserves_identity(
    store: SqliteStore,
) -> None:
    _complete(store, "ADBE")
    latest = _complete(store, "ADBE", snapshot(price=25))
    persist(store, "ADBE", snapshot(price=30))  # Valued, but no saved challenger.
    persist(store, "NOW", snapshot(), valued=False)
    before = tuple(store.list_underwriting("ADBE"))

    catalog = discover_comparison_companies(store)

    assert [item.ticker for item in catalog.companies] == ["ADBE"]
    company = catalog.companies[0]
    assert company.latest.selection == latest
    assert company.latest_record_version == 3
    assert [item.selection.version for item in company.versions] == [1, 2]
    record = before[1]
    assert company.latest.underwriting_id == record.underwriting_id
    assert company.latest.content_hash == record.content_hash
    assert any("ADBE:3" in reason for reason in catalog.excluded)
    assert store.list_underwriting("ADBE") == before


def test_table_displays_frozen_dates_hurdles_missing_context_and_engine_flags(
    store: SqliteStore,
) -> None:
    first = snapshot()
    second = snapshot(price=30)
    evidence = json.loads(second.evidence_json)
    evidence.pop("feature7_context")
    evidence["eod_price"]["value"]["market_date"] = "2026-06-01"
    second = replace(
        second,
        evidence_json=json.dumps(evidence),
        manual=replace(
            second.manual,
            investor_policy=replace(second.manual.investor_policy, required_return=0.15),
            supporting_evidence=(),
        ),
    )
    a = _complete(store, "ADBE", first)
    b = _complete(store, "MSFT", second)
    expected = compare_underwritings(store, (a, b))
    before = tuple(store._conn.iterdump())
    app = _app().run()
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    assert not app.exception and not app.error
    table = app.dataframe[0].value
    assert table.loc["Frozen price / market date", "MSFT:1"] == "$30.00 / 2026-06-01"
    assert table.loc["Underwriting as of", "MSFT:1"] == "2026-06-02"
    assert table.loc["Required return", "MSFT:1"] == "15.00%"
    assert table.loc["Required return", "ADBE:1"] != "15.00%"
    assert table.loc["Business Quality", "MSFT:1"] == "MISSING (not frozen)"
    assert table.loc["Supporting evidence", "MSFT:1"] == "MISSING"
    for flag in expected.pairs[0].left_flags + expected.pairs[0].right_flags:
        assert any(flag in item.value for item in app.caption)
    assert any("Conditional capital attractiveness:" in item.value for item in app.markdown)
    assert tuple(store._conn.iterdump()) == before
    assert compare_underwritings(store, (a, b)).to_json() == expected.to_json()


def test_newer_partial_warning_and_retry_navigation(source: WorkbenchSource) -> None:
    from test_research_context import inputs

    inputs(source)
    _complete(source.store, "MSFT")
    _retain_current_companies(source.store)
    create_underwriting(
        source, "ADBE", snapshot().manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    app = _app().run()
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    assert not app.exception and not app.error
    assert any("ADBE: newer v2" in item.value for item in app.warning)
    assert "ADBE:1" in app.dataframe[0].value.columns
    app.button(key="opportunity_retry.ADBE").click().run()
    assert not app.exception and not app.error
    assert app.session_state["company_requested_underwriting"] == UnderwritingSelection("ADBE", 2)
    assert any("underwriting v2" in item.value for item in app.caption)
    assert any(item.label == "Retry analysis" for item in app.button)


def test_exact_company_handoff_and_return_to_historical_view(
    source: WorkbenchSource,
) -> None:
    from test_research_context import inputs

    _, projection = inputs(source)
    newer = create_underwriting(
        source, "ADBE", snapshot().manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    run_valuation(source.store, newer)
    run_challenger(source.store, newer)
    _complete(source.store, "MSFT")
    _retain_current_companies(source.store)
    record = projection.record
    handoff = ComparisonVersion(
        UnderwritingSelection("ADBE", record.version),
        record.underwriting_id,
        record.content_hash,
    )
    app = _app()
    app.session_state["opportunity_requested_underwriting"] = handoff
    app.run()
    assert not app.exception and not app.error
    assert app.multiselect(key="opportunity_companies").value == ["ADBE"]
    assert app.selectbox(key="opportunity_version.ADBE").value == "ADBE:1"
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    assert "ADBE:1" in app.dataframe[0].value.columns
    app.button(key="opportunity_company.ADBE:1").click().run()
    assert not app.exception and not app.error
    assert any("underwriting v1" in item.value for item in app.caption)
    next(item for item in app.button if item.label == "Compare this underwriting").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="opportunity_version.ADBE").value == "ADBE:1"


def test_latest_default_tracks_new_completion_but_history_stays_exact(
    store: SqliteStore,
) -> None:
    _complete(store, "ADBE")
    _complete(store, "MSFT")
    app = _app().run()
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    _complete(store, "ADBE", snapshot(price=25))
    app.run()
    assert not app.exception and not app.error
    assert "ADBE:2" in app.dataframe[0].value.columns
    app.selectbox(key="opportunity_version.ADBE").set_value("ADBE:1").run()
    _complete(store, "ADBE", snapshot(price=30))
    app.run()
    assert "ADBE:1" in app.dataframe[0].value.columns
    app.multiselect(key="opportunity_extra_versions").set_value(["ADBE:2"]).run()
    assert set(app.dataframe[0].value.columns) == {"ADBE:1", "ADBE:2", "MSFT:1"}


def test_ui_only_formats_service_report_without_duplicating_financial_calculation(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from owner_lens import underwriting_summary, valuation, variant
    from owner_lens.workbench.views import opportunity_comparison as view

    a = _complete(store, "ADBE")
    b = _complete(store, "MSFT")
    report = compare_underwritings(store, (a, b))
    catalog = discover_comparison_companies(store)
    calls = []

    def compare(_store: SqliteStore, selections: tuple[UnderwritingSelection, ...]):
        calls.append(selections)
        return report

    monkeypatch.setattr(view, "discover_comparison_companies", lambda _: catalog)
    monkeypatch.setattr(view, "compare_underwritings", compare)
    for module, name in (
        (valuation, "value_underwriting"),
        (underwriting_summary, "summarize_underwriting"),
        (variant, "compare_variant"),
    ):
        monkeypatch.setattr(
            module, name, lambda *_args, **_kwargs: pytest.fail("No financial math in Streamlit")
        )
    before = tuple(store._conn.iterdump())
    app = _app().run()
    assert calls == []
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    assert not app.exception and not app.error
    assert calls == [(a, b)]
    assert tuple(store._conn.iterdump()) == before


def test_ineligible_exact_handoff_is_rejected_without_latest_substitution(
    store: SqliteStore,
) -> None:
    _complete(store, "ADBE")
    _complete(store, "MSFT")
    incomplete = persist(store, "ADBE", snapshot(), valued=False)
    record = store.list_underwriting("ADBE")[-1]
    app = _app()
    app.session_state["opportunity_companies"] = ["ADBE", "MSFT"]
    app.session_state["opportunity_requested_underwriting"] = ComparisonVersion(
        incomplete, record.underwriting_id, record.content_hash
    )
    app.run()
    assert not app.exception
    assert any("requested exact underwriting" in item.value for item in app.error)
    assert not app.dataframe


def test_stale_historical_override_does_not_fall_back_to_latest(
    store: SqliteStore,
) -> None:
    _complete(store, "ADBE")
    _complete(store, "MSFT")
    app = _app()
    app.session_state["opportunity_companies"] = ["ADBE", "MSFT"]
    app.session_state["opportunity_version.ADBE"] = "ADBE:99"
    app.run()
    assert not app.exception
    assert any("ADBE:99 is no longer eligible" in item.value for item in app.error)
    assert not app.dataframe
    app.selectbox(key="opportunity_version.ADBE").set_value("Latest eligible").run()
    assert not app.exception and not app.error
    assert "ADBE:1" in app.dataframe[0].value.columns

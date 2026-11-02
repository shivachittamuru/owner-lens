"""Fixture-only forecast/outcome chronology, exact comparisons and immutable storage."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from test_changes import event_input, monitored_snapshot
from test_decisions import input_data
from test_opportunity_comparison import persist, snapshot
from test_position_sizing import policy, portfolio_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.changes import approve_event, create_event, current_change_state
from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import (
    MODEL_VERSION,
    OutcomeError,
    build_observation,
    compare_outcomes,
    create_observation,
    format_comparison,
    format_observation,
    outcome_history,
    range_comparison,
    read_observation,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import canonical_json, create_portfolio, size_position
from owner_lens.underwriting import UnderwritingError

NOW = datetime(2032, 1, 2, 12, tzinfo=UTC)
EARLY = datetime(2026, 6, 3, 12, tzinfo=UTC)
APP = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"


def fundamental(
    field: str = "revenue_cagr",
    value: float | None = 0.074,
    **changes: Any,
) -> dict[str, Any]:
    return {
        "forecast": {"kind": "SCENARIO", "id": field},
        "observable": field,
        "value": value,
        "unit": "ratio",
        "basis": "FISCAL_CAGR",
        "fiscal_year": 2030,
        "start_fiscal_year": 2025,
        "period_end": "2030-12-31",
        "cadence": None,
        "source_family": None,
        **changes,
    }


def outcome_input(**changes: Any) -> dict[str, Any]:
    return {
        "observation_date": "2031-06-02",
        "observed_at": "2031-06-03T11:00:00+00:00",
        "horizon": "5Y",
        "category": "FACT",
        "references": [
            {
                "title": "Synthetic outcome report",
                "uri": "fixture://outcome",
                "observed_at": "2031-06-03T10:00:00+00:00",
            }
        ],
        "verification_note": "Manually checked synthetic fixture, not real Adobe data.",
        "market": {
            "price": 30,
            "currency": "USD",
            "basis": "EOD_CLOSE_SAME_SHARE_BASIS",
        },
        "fundamentals": [fundamental()],
        **changes,
    }


def record(store: SqliteStore, data: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = persist(store, "ADBE", snapshot())
    return create_observation(
        store, selected, outcome_input() if data is None else data, now=NOW
    )


def test_exact_link_and_frozen_market_returns(store: SqliteStore) -> None:
    report = record(store)
    original = store.list_underwriting("ADBE")[0]
    assert report["underwriting"]["underwriting_id"] == original.underwriting_id
    assert report["underwriting"]["content_hash"] == original.content_hash
    assert report["underwriting"]["version"] == 1
    assert report["observation"]["category"] == "FACT"
    assert report["market_outcome"]["category"] == "CALCULATION"
    market = report["market_outcome"]
    assert market["family"] == "MARKET_OUTCOME"
    assert market["total_price_return"] == pytest.approx(0.5)
    days = (datetime(2031, 6, 2, tzinfo=UTC) - datetime(2026, 6, 1, tzinfo=UTC)).days
    assert market["annualized_price_return"] == pytest.approx(
        1.5 ** (365.2425 / days) - 1
    )
    assert report["elapsed"]["days_since_underwriting_as_of"] == 1826
    assert market["comparison"]["status"] != "INTERIM_OBSERVATION"
    assert report["model_version"] == MODEL_VERSION
    assert "not investor realized return" in report["disclaimer"]


def test_exact_versions_isolated_and_stable_json(store: SqliteStore) -> None:
    report = record(store)
    before = canonical_json(compare_outcomes(store, UnderwritingSelection("ADBE", 1)))
    newer = persist(store, "ADBE", snapshot(price=50))
    new = create_observation(store, newer, outcome_input(), now=NOW)
    assert new["market_outcome"]["total_price_return"] == pytest.approx(-0.4)
    assert read_observation(store, report["observation_id"]) == report
    assert (
        canonical_json(compare_outcomes(store, UnderwritingSelection("ADBE", 1)))
        == before
    )
    assert len(outcome_history(store, "ADBE")) == 2
    assert len(compare_outcomes(store, newer)["observations"]) == 1
    with pytest.raises(ValueError, match="not found"):
        compare_outcomes(store, UnderwritingSelection("ADBE", 99))


@pytest.mark.parametrize("price", [0, 10, 20, 40])
def test_market_price_returns_including_total_loss(
    store: SqliteStore, price: float
) -> None:
    data = outcome_input()
    data["market"]["price"] = price
    report = record(store, data)
    assert report["market_outcome"]["total_price_return"] == pytest.approx(
        price / 20 - 1
    )
    assert report["market_outcome"]["annualized_price_return"] is not None


@pytest.mark.parametrize(
    "observation_date,annualized,status",
    [
        ("2026-12-02", False, "INTERIM_OBSERVATION"),
        ("2027-06-01", True, "INTERIM_OBSERVATION"),
        ("2031-06-01", True, "INTERIM_OBSERVATION"),
        ("2031-06-02", True, "NEAR_BASE"),
        ("2031-06-03", True, "NOT_COMPARABLE"),
    ],
)
def test_market_horizon_no_invented_path(
    store: SqliteStore,
    observation_date: str,
    annualized: bool,
    status: str,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    forecast = compare_outcomes(store, selected)["forecast"]
    base = forecast["valuation"]["scenarios"][1]["year5_value_per_share"]
    data = outcome_input(observation_date=observation_date, fundamentals=[])
    data["market"]["price"] = base
    report = create_observation(store, selected, data, now=NOW)
    market = report["market_outcome"]
    assert (market["annualized_price_return"] is not None) is annualized
    assert market["comparison"]["status"] == status
    assert "path" not in market or market["path"] is None


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("currency", "EUR", "NOT_COMPARABLE"),
        ("currency", None, "INSUFFICIENT_DATA"),
        ("basis", "SPLIT_ADJUSTED", "NOT_COMPARABLE"),
        ("basis", None, "INSUFFICIENT_DATA"),
        ("price", None, "INSUFFICIENT_DATA"),
    ],
)
def test_market_missing_or_incompatible_basis(
    store: SqliteStore,
    field: str,
    value: Any,
    status: str,
) -> None:
    data = outcome_input()
    data["market"][field] = value
    report = record(store, data)
    assert report["market_outcome"]["comparison"]["status"] == status
    assert report["market_outcome"]["total_price_return"] is None


@pytest.mark.parametrize(
    "value,status",
    [
        (-0.1, "BELOW_BEAR"),
        (0.0, "WITHIN_BEAR_BASE"),
        (0.074, "WITHIN_BEAR_BASE"),
        (0.1, "NEAR_BASE"),
        (0.1000000005, "NEAR_BASE"),
        (0.100000002, "WITHIN_BASE_BULL"),
        (0.15, "WITHIN_BASE_BULL"),
        (0.2, "WITHIN_BASE_BULL"),
        (0.21, "ABOVE_BULL"),
    ],
)
def test_scenario_range_and_tolerance(value: float, status: str) -> None:
    comparison = range_comparison(value, {"BEAR": 0.0, "BASE": 0.1, "BULL": 0.2})
    assert comparison["status"] == status
    assert comparison["base_tolerance"] == 1e-9


def test_comparable_fundamental_and_year5_margin(store: SqliteStore) -> None:
    data = outcome_input(
        fundamentals=[
            fundamental(),
            fundamental(
                "fcf_margin_year5", 0.25, basis="ANNUAL_FISCAL", start_fiscal_year=None
            ),
            fundamental(
                "terminal_fcf_multiple",
                20,
                unit="multiple",
                basis="FISCAL_YEAR_END",
                start_fiscal_year=None,
            ),
            fundamental("share_count_cagr", -0.04),
        ]
    )
    report = record(store, data)
    growth, margin, multiple, shares = report["fundamental_outcomes"]
    assert growth["status"] == "WITHIN_BEAR_BASE"
    assert growth["nearest_scenarios"] == ["BASE"]
    assert growth["frozen_belief"]["scenario_values"] == {
        "BEAR": 0.0,
        "BASE": 0.1,
        "BULL": 0.2,
    }
    assert margin["status"] == "WITHIN_BASE_BULL"
    assert multiple["status"] == "NEAR_BASE"
    # Share counts decline toward BULL: do not silently reorder ranges.
    assert shares["status"] == "NOT_COMPARABLE"
    assert shares["nearest_scenarios"] == ["BULL"]
    assert all(
        item["category"] == "CALCULATION" for item in report["fundamental_outcomes"]
    )


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"unit": "percent"}, "NOT_COMPARABLE"),
        ({"observable": "ARR CAGR"}, "NOT_COMPARABLE"),
        ({"observable": "Revenue_cagr"}, "NOT_COMPARABLE"),
        ({"basis": "YOY"}, "NOT_COMPARABLE"),
        ({"start_fiscal_year": 2026}, "NOT_COMPARABLE"),
        ({"fiscal_year": 2027, "period_end": "2027-12-31"}, "INTERIM_OBSERVATION"),
        ({"fiscal_year": 2031, "period_end": "2031-01-01"}, "NOT_COMPARABLE"),
        ({"fiscal_year": None}, "INSUFFICIENT_DATA"),
        ({"start_fiscal_year": None}, "INSUFFICIENT_DATA"),
        ({"unit": None}, "INSUFFICIENT_DATA"),
        ({"basis": None}, "INSUFFICIENT_DATA"),
        ({"value": None}, "INSUFFICIENT_DATA"),
        ({"period_end": None}, "INSUFFICIENT_DATA"),
    ],
)
def test_fundamental_definitions_units_and_time_alignment(
    store: SqliteStore,
    changes: dict[str, Any],
    status: str,
) -> None:
    report = record(store, outcome_input(fundamentals=[fundamental(**changes)]))
    assert report["fundamental_outcomes"][0]["status"] == status
    if status != "NOT_COMPARABLE":
        assert report["fundamental_outcomes"][0]["nearest_scenarios"] == []


def test_quarterly_margin_cannot_be_compared_to_year5(store: SqliteStore) -> None:
    report = record(
        store,
        outcome_input(
            fundamentals=[
                fundamental(
                    "fcf_margin_year5", 0.2, basis="QUARTERLY", fiscal_year=2030
                ),
            ]
        ),
    )
    assert report["fundamental_outcomes"][0]["status"] == "NOT_COMPARABLE"


@pytest.mark.parametrize(
    "value,observable,status,condition_status",
    [
        (
            5.8,
            "ARR growth YoY, constant currency",
            "NO_SCENARIO_RANGE",
            "CONDITION_BREACHED",
        ),
        (
            7.4,
            "ARR growth YoY, constant currency",
            "NO_SCENARIO_RANGE",
            "CONDITION_MET",
        ),
        (7.4, "ARR growth", "NOT_COMPARABLE", "NOT_COMPARABLE"),
    ],
)
def test_thesis_variable_tracking_does_not_create_change_candidate(
    store: SqliteStore,
    value: float,
    observable: str,
    status: str,
    condition_status: str,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    metric = fundamental(
        value=value,
        forecast={"kind": "CONDITION", "id": "arr-growth"},
        observable=observable,
        unit="%",
        cadence="Quarterly",
        basis=None,
        fiscal_year=None,
        start_fiscal_year=None,
    )
    data = outcome_input(fundamentals=[metric])
    data["references"][0]["title"] = "Fixture company report"
    report = create_observation(store, selected, data, now=NOW)
    compared = report["fundamental_outcomes"][0]
    assert compared["status"] == status
    assert compared["condition_status"] == condition_status
    assert "candidate_classification" not in compared
    assert compared["frozen_belief"]["statement"]
    assert not store.list_change_events()
    assert current_change_state(store, "ADBE")["status"] == "NO_REUNDERWRITING_REQUIRED"


def test_no_observations_and_missing_values_are_explicit(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    comparison = compare_outcomes(store, selected)
    assert comparison["observations"] == []
    assert comparison["missing_observations"]["market"] is True
    data = outcome_input(
        market=None, fundamentals=[], references=[], verification_note=None
    )
    report = create_observation(store, selected, data, now=NOW)
    assert report["market_outcome"]["comparison"]["status"] == "INSUFFICIENT_DATA"
    assert report["fundamental_outcomes"] == []
    assert (
        len(
            compare_outcomes(store, selected)["missing_observations"][
                "scenario_metrics"
            ]
        )
        == 4
    )
    assert "Missing observations" in format_comparison(
        compare_outcomes(store, selected)
    )


@pytest.mark.parametrize(
    "change",
    [
        {"category": "EXPECTATION"},
        {"category": "JUDGMENT"},
        {"verification_note": None},
        {"references": []},
        {"horizon": "LATEST"},
        {"horizon": "CUSTOM"},
        {"observation_date": "2026-06-01"},
        {"observation_date": "2033-01-01"},
        {"observed_at": "2033-01-01T00:00:00+00:00"},
        {"observed_at": "2031-06-03"},
        {"observed_at": "2026-06-01T10:00:00+00:00"},
        {"references": [{"uri": "fixture://future", "observed_at": "2032-01-03"}]},
        {
            "market": {
                "price": -1,
                "currency": "USD",
                "basis": "EOD_CLOSE_SAME_SHARE_BASIS",
            }
        },
        {
            "market": {
                "price": True,
                "currency": "USD",
                "basis": "EOD_CLOSE_SAME_SHARE_BASIS",
            }
        },
        {
            "market": {
                "price": float("inf"),
                "currency": "USD",
                "basis": "EOD_CLOSE_SAME_SHARE_BASIS",
            }
        },
        {"fundamentals": [fundamental(period_end="2032-01-01")]},
        {"fundamentals": [fundamental(period_end="2026-06-01")]},
        {"fundamentals": [fundamental(fiscal_year=2040)]},
        {"fundamentals": [fundamental(start_fiscal_year=2030)]},
        {"fundamentals": [fundamental(value=float("nan"))]},
        {
            "fundamentals": [
                fundamental(forecast={"kind": "SCENARIO", "id": "arr_growth"})
            ]
        },
        {
            "fundamentals": [
                fundamental(forecast={"kind": "CONDITION", "id": "missing"})
            ]
        },
        {"fundamentals": [fundamental(), fundamental()]},
        {"unknown": "not ignored"},
    ],
)
def test_invalid_or_lookahead_observations_rejected(
    store: SqliteStore, change: dict[str, Any]
) -> None:
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises((ValueError, UnderwritingError)):
        create_observation(store, selected, outcome_input(**change), now=NOW)
    assert not store.list_outcome_observations()


@pytest.mark.parametrize("horizon", ["QUARTERLY", "1Y", "2Y", "3Y", "5Y", "CUSTOM"])
def test_horizon_labels_do_not_override_actual_alignment(
    store: SqliteStore, horizon: str
) -> None:
    report = record(
        store,
        outcome_input(
            horizon=horizon, horizon_note="Explicit manual observation window"
        ),
    )
    assert report["observation"]["horizon"] == horizon
    assert report["fundamental_outcomes"][0]["status"] == "WITHIN_BEAR_BASE"


def test_append_only_and_forged_calculation_rejected(store: SqliteStore) -> None:
    report = record(store)
    observation_id = report["observation_id"]
    for sql in (
        "UPDATE outcome_observations SET content_hash='bad' WHERE observation_id=?",
        "DELETE FROM outcome_observations WHERE observation_id=?",
        "INSERT OR REPLACE INTO outcome_observations SELECT * FROM outcome_observations WHERE observation_id=?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(sql, (observation_id,))
        store._conn.rollback()
    forged = deepcopy(report)
    forged["observation_id"] = str(uuid4())
    forged["market_outcome"]["total_price_return"] = 100
    with pytest.raises(StorageWriteError, match="differs"):
        store.save_outcome_observation(canonical_json(forged))
    assert len(store.list_outcome_observations()) == 1
    with pytest.raises(StorageWriteError):
        store.save_outcome_observation(canonical_json(report))
    assert read_observation(store, observation_id) == report


def test_historical_read_never_recomputes(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = record(store)
    frozen = canonical_json(report)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Historical read must not rerun or fetch.")

    monkeypatch.setattr("owner_lens.outcomes.frozen_forecast", forbidden)
    monkeypatch.setattr("owner_lens.outcomes._record_context", forbidden)
    monkeypatch.setattr("owner_lens.outcomes._fundamental", forbidden)
    assert canonical_json(read_observation(store, report["observation_id"])) == frozen


def test_no_mutation_and_frozen_feature9_context(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    decision = create_decision(store, selected, input_data(), now=EARLY)
    event = create_event(store, selected, event_input(), now=EARLY)
    approve_event(
        store, event["event_id"], "THESIS_UPDATE", "Explicit review", now=EARLY
    )
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    sizing = size_position(store, selected, portfolio.snapshot_id, policy(), now=EARLY)
    store.save_sizing_analysis(canonical_json(sizing), created_at=EARLY.isoformat())
    before = (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_shadow_entries(),
        store.list_change_events(),
        store.list_change_approvals(),
        store.list_portfolio_snapshots(),
        store.list_sizing_analyses(),
    )
    report = create_observation(store, selected, outcome_input(), now=NOW)
    assert (
        report["record_context"]["decisions"][0]["decision_id"] == decision.decision_id
    )
    assert (
        report["record_context"]["changes"][0]["approval"]["approved_classification"]
        == "THESIS_UPDATE"
    )
    assert before == (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_shadow_entries(),
        store.list_change_events(),
        store.list_change_approvals(),
        store.list_portfolio_snapshots(),
        store.list_sizing_analyses(),
    )
    frozen = canonical_json(report)
    later = create_event(store, selected, event_input(), now=NOW + timedelta(days=1))
    approve_event(
        store,
        later["event_id"],
        "NOISE",
        "Later information",
        now=NOW + timedelta(days=1),
    )
    assert canonical_json(read_observation(store, report["observation_id"])) == frozen
    older = build_observation(
        store,
        selected,
        outcome_input(),
        observation_id=str(uuid4()),
        recorded_at=NOW.isoformat(),
    )
    assert len(older["record_context"]["changes"]) == 1


def test_v9_additive_migration_and_content_integrity(store: SqliteStore) -> None:
    report = record(store)
    original = store.list_underwriting("ADBE")
    store._conn.executescript(
        "DROP TABLE outcome_observations; UPDATE schema_meta SET value='9' WHERE key='schema_version';"
    )
    store.initialize()
    assert store.list_underwriting("ADBE") == original
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "10"
    )
    store.save_outcome_observation(canonical_json(report))
    store._conn.executescript(
        "DROP TRIGGER outcome_no_update; UPDATE outcome_observations SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        read_observation(store, report["observation_id"])


def test_later_approval_cannot_rewrite_frozen_outcome_context(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    report = create_observation(store, selected, outcome_input(), now=NOW)
    assert report["record_context"]["changes"][0]["approval"] is None
    before = canonical_json(report)
    approve_event(
        store,
        event["event_id"],
        "THESIS_BREAK",
        "Later explicit approval",
        now=NOW + timedelta(days=1),
    )
    assert canonical_json(read_observation(store, report["observation_id"])) == before
    historical = build_observation(
        store,
        selected,
        outcome_input(),
        observation_id=str(uuid4()),
        recorded_at=NOW.isoformat(),
    )
    assert historical["record_context"]["changes"][0]["approval"] is None


def test_missing_metric_value_remains_in_missing_inventory(store: SqliteStore) -> None:
    record(store, outcome_input(fundamentals=[fundamental(value=None)]))
    comparison = compare_outcomes(store, UnderwritingSelection("ADBE", 1))
    assert "revenue_cagr" in comparison["missing_observations"]["scenario_metrics"]


def test_incomplete_underwriting_has_no_latest_fallback(store: SqliteStore) -> None:
    original = snapshot()
    incomplete = replace(
        original, manual=replace(original.manual, probability_distribution=None)
    )
    persist(store, "ADBE", incomplete)
    persist(store, "ADBE", original)
    with pytest.raises(ValueError, match="probabilit"):
        create_observation(
            store, UnderwritingSelection("ADBE", 1), outcome_input(), now=NOW
        )
    assert not store.list_outcome_observations()


def test_structured_condition_exact_metadata_without_change_record(
    store: SqliteStore,
) -> None:
    from test_changes import predicate_snapshot

    selected = persist(store, "ADBE", predicate_snapshot())
    metric = fundamental(
        forecast={"kind": "CONDITION", "id": "total_adobe_arr_growth"},
        observable="Total Adobe ARR growth",
        value=5.8,
        unit="percent_yoy",
        cadence="quarterly",
        source_family="adobe_earnings",
    )
    report = create_observation(
        store, selected, outcome_input(fundamentals=[metric]), now=NOW
    )
    assert report["fundamental_outcomes"][0]["condition_status"] == "CONDITION_BREACHED"
    metric["source_family"] = "different"
    report = create_observation(
        store, selected, outcome_input(fundamentals=[metric]), now=NOW
    )
    assert report["fundamental_outcomes"][0]["status"] == "NOT_COMPARABLE"
    assert not store.list_change_events()


def test_cli_roundtrip_and_reproducibility(
    store: SqliteStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persist(store, "ADBE", snapshot())
    data = outcome_input(
        observation_date="2026-06-03",
        observed_at=EARLY.isoformat(),
        horizon="CUSTOM",
        horizon_note="First manual observation",
        fundamentals=[],
        references=[{"title": "Synthetic outcome report", "observed_at": "2026-06-03"}],
    )
    path = tmp_path / "outcome.json"
    path.write_text(canonical_json(data), encoding="utf-8")
    assert (
        main(
            [
                "outcome",
                "create",
                "ADBE",
                "--version",
                "1",
                "--file",
                str(path),
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert main(["outcome", "show", report["observation_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert main(["outcome", "history", "ADBE", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [report]
    assert main(["outcome", "compare", "ADBE", "--version", "1", "--json"]) == 0
    before = capsys.readouterr().out
    assert main(["outcome", "compare", "ADBE", "--version", "1", "--json"]) == 0
    assert capsys.readouterr().out == before
    assert main(["outcome", "compare", "ADBE", "--version", "1"]) == 0
    assert "MARKET_OUTCOME" in capsys.readouterr().out
    assert main(["outcome", "show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert (
        main(["outcome", "create", "ADBE", "--version", "99", "--file", str(path)]) == 1
    )
    assert "not found" in capsys.readouterr().err
    assert len(store.list_outcome_observations()) == 1


def test_workbench_readonly_and_explicit_entry(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Outcomes"
    app.session_state["outcomes_version"] = "ADBE:1"
    app.run()
    assert not app.exception and not app.error
    assert not store.list_outcome_observations()
    data = outcome_input(
        observation_date="2026-06-03",
        observed_at=EARLY.isoformat(),
        horizon="CUSTOM",
        horizon_note="Synthetic interim fixture",
        fundamentals=[],
        references=[{"uri": "fixture://outcome", "observed_at": "2026-06-03"}],
    )
    app.text_area(key="outcomes_input").set_value(canonical_json(data))
    next(
        item
        for item in app.button
        if item.label == "Record immutable outcome observation"
    ).click().run()
    assert not app.exception and not app.error
    assert len(store.list_outcome_observations()) == 1
    assert app.dataframe[0].value.iloc[0]["Status"] == "INTERIM_OBSERVATION"
    app.run()
    assert len(store.list_outcome_observations()) == 1
    assert not store.list_change_events() and not store.list_decisions()
    assert "MARKET_OUTCOME" in format_observation(
        json.loads(store.list_outcome_observations()[0].snapshot_json)
    )


def test_manual_template_is_custom_interim_without_invented_evidence(
    store: SqliteStore,
) -> None:
    examples = Path(__file__).parents[1] / "docs" / "examples"
    data = json.loads((examples / "adbe_outcome.sample.json").read_text())
    selected = persist(store, "ADBE", snapshot())
    clock = datetime(2026, 11, 3, 12, tzinfo=UTC)
    report = create_observation(store, selected, data, now=clock)
    assert data["horizon"] == "CUSTOM"
    assert report["market_outcome"]["comparison"]["status"] == "INSUFFICIENT_DATA"
    assert report["fundamental_outcomes"][0]["status"] == "INSUFFICIENT_DATA"
    data["references"] = [
        {"uri": "fixture://verified-interim", "observed_at": data["observed_at"]}
    ]
    data["verification_note"] = "Synthetic test evidence only, not an Adobe assertion."
    data["market"]["price"] = 25
    data["fundamentals"][0].update(value=0.25, period_end="2026-10-31")
    report = create_observation(store, selected, data, now=clock)
    assert report["market_outcome"]["comparison"]["status"] == "INTERIM_OBSERVATION"
    assert report["fundamental_outcomes"][0]["status"] == "INTERIM_OBSERVATION"


def test_future_synthetic_template_still_rejected_in_2026(store: SqliteStore) -> None:
    examples = Path(__file__).parents[1] / "docs" / "examples"
    data = json.loads((examples / "adbe_outcome_5y.synthetic.json").read_text())
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(OutcomeError, match="cannot look ahead"):
        create_observation(store, selected, data, now=datetime(2026, 11, 3, tzinfo=UTC))
    assert not store.list_outcome_observations()

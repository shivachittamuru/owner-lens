"""Fixture-only calibration eligibility, proper score math and immutable histories."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_decisions import input_data
from test_opportunity_comparison import persist, snapshot
from test_outcomes import fundamental, outcome_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.calibration import (
    CalibrationError,
    _continuous_summary,
    _probability_summary,
    brier_score,
    build_report,
    format_report,
    read_report,
    realized_region,
    run_calibration,
    sample_status,
)
from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import create_observation
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import canonical_json

NOW = datetime(2032, 1, 2, 12, tzinfo=UTC)
AS_OF = "2032-12-31"
APP = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"


def completed(
    store: SqliteStore,
    *,
    region: str = "BASE",
    metric_value: float = 0.074,
    ticker: str = "ADBE",
    now: datetime = NOW,
) -> tuple[UnderwritingSelection, dict[str, Any]]:
    selected = persist(store, ticker, snapshot())
    from owner_lens.outcomes import frozen_forecast

    forecast = frozen_forecast(store, selected)
    prices = {
        item["assumptions"]["name"]: item["year5_value_per_share"]
        for item in forecast["valuation"]["scenarios"]
    }
    price = (
        (prices["BASE"] + prices["BULL"]) / 2
        if region == "AMBIGUOUS"
        else prices[region]
    )
    data = outcome_input(fundamentals=[fundamental(value=metric_value)])
    data["market"]["price"] = price
    return selected, create_observation(store, selected, data, now=now)


@pytest.mark.parametrize(
    "count,status",
    [
        (0, "INSUFFICIENT_HISTORY_FOR_CALIBRATION"),
        (4, "INSUFFICIENT_HISTORY_FOR_CALIBRATION"),
        (5, "EARLY_SIGNAL_ONLY"),
        (19, "EARLY_SIGNAL_ONLY"),
        (20, "CALIBRATION_AVAILABLE"),
        (100, "CALIBRATION_AVAILABLE"),
    ],
)
def test_sample_guardrails(count: int, status: str) -> None:
    assert sample_status(count) == status


@pytest.mark.parametrize(
    "value,region",
    [
        (1, "BEAR"),
        (10, "BEAR"),
        (10.00000001, "BEAR"),
        (15, None),
        (20, "BASE"),
        (20.00000001, "BASE"),
        (25, None),
        (30, "BULL"),
        (40, "BULL"),
    ],
)
def test_disjoint_regions_never_nearest_scenario_winner(
    value: float, region: str | None
) -> None:
    assert (
        realized_region(value, {"BEAR": 10, "BASE": 20, "BULL": 30})["realized_region"]
        == region
    )


@pytest.mark.parametrize(
    "values",
    [
        {"BEAR": 20, "BASE": 20, "BULL": 30},
        {"BEAR": 30, "BASE": 20, "BULL": 10},
        {"BEAR": 10, "BASE": 20, "BULL": 20.00000001},
    ],
)
def test_ambiguous_or_unordered_anchors_no_discrete_class(
    values: dict[str, float],
) -> None:
    assert realized_region(20, values)["realized_region"] is None


def test_brier_exact_unnormalized_math() -> None:
    assert brier_score(
        {"BEAR": 0.2, "BASE": 0.5, "BULL": 0.3}, "BEAR"
    ) == pytest.approx(0.98)
    assert brier_score({"BEAR": 0, "BASE": 1, "BULL": 0}, "BASE") == 0
    assert brier_score({"BEAR": 1, "BASE": 0, "BULL": 0}, "BULL") == 2


@pytest.mark.parametrize(
    "probabilities,region",
    [
        ({"BEAR": 0.2, "BASE": 0.5}, "BASE"),
        ({"BEAR": 0.2, "BASE": 0.5, "BULL": 0.2}, "BASE"),
        ({"BEAR": -0.1, "BASE": 0.8, "BULL": 0.3}, "BASE"),
        ({"BEAR": True, "BASE": 0, "BULL": 0}, "BASE"),
        ({"BEAR": float("nan"), "BASE": 0.7, "BULL": 0.3}, "BASE"),
        ({"BEAR": 0.2, "BASE": 0.5, "BULL": 0.3}, "AMBIGUOUS"),
    ],
)
def test_brier_invalid_or_ambiguous_never_normalized(
    probabilities: dict[str, float], region: str
) -> None:
    with pytest.raises(CalibrationError):
        brier_score(probabilities, region)


def summary_rows(count: int, *, error: float = -0.018) -> list[dict[str, Any]]:
    return [
        {
            "underwriting": {"underwriting_id": f"fixture-{index}"},
            "observation_id": f"outcome-{index}",
            "observation_date": "2031-06-02",
            "metric": "market_price",
            "probabilities": {"BEAR": 0.2, "BASE": 0.5, "BULL": 0.3},
            "realized_region": "BEAR" if index % 2 == 0 else "BULL",
            "region_reason": "",
            "brier": brier_score(
                {"BEAR": 0.2, "BASE": 0.5, "BULL": 0.3},
                "BEAR" if index % 2 == 0 else "BULL",
            ),
            "forecast_error": error,
            "base_forecast": 0.1,
            "observed": 0.1 + error,
        }
        for index in range(count)
    ]


@pytest.mark.parametrize("count", [0, 4, 5, 19, 20])
def test_probability_counts_frequencies_and_guarded_means(count: int) -> None:
    summary = _probability_summary(summary_rows(count))
    assert summary["status"] == sample_status(count)
    assert summary["eligible_sample_count"] == count
    assert len(summary["raw_scores"]) == count
    if count < 5:
        assert summary["scenario_frequency"] == [] and summary["mean_brier"] is None
    else:
        assert summary["scenario_frequency"][0][
            "assigned_probability_average"
        ] == pytest.approx(0.2)
        assert (
            summary["scenario_frequency"][0]["observed_region_frequency"]
            == (count + 1) // 2 / count
        )
        assert summary["mean_brier"] == pytest.approx(
            sum(item["brier"] for item in summary_rows(count)) / count
        )


def test_sparse_probability_buckets_and_boundary_membership() -> None:
    rows = summary_rows(20)
    for index, row in enumerate(rows):
        row["probabilities"] = (
            {"BEAR": 0.2, "BASE": 0.4, "BULL": 0.4}
            if index < 4
            else {"BEAR": 1.0, "BASE": 0.0, "BULL": 0.0}
        )
    summary = _probability_summary(rows)
    assert summary["suppressed_bucket_count"] == 3
    assert len(summary["buckets"]) == 3
    bear = next(item for item in summary["buckets"] if item["scenario"] == "BEAR")
    assert bear["lower"] == 0.8 and bear["upper_inclusive"] is True
    assert bear["sample_count"] == 16 and bear["average_predicted_probability"] == 1
    rows = summary_rows(5)
    bucket = next(
        item
        for item in _probability_summary(rows)["buckets"]
        if item["scenario"] == "BEAR"
    )
    assert bucket["lower"] == 0.2 and bucket["upper"] == 0.4


@pytest.mark.parametrize("count", [1, 4, 5, 19, 20])
@pytest.mark.parametrize(
    "error,direction,word",
    [
        (-0.018, "BASE_ABOVE_OBSERVED", "optimistic"),
        (0.018, "BASE_BELOW_OBSERVED", "pessimistic"),
        (0.0, "NO_DIRECTIONAL_BIAS_DETECTED", "No directional"),
    ],
)
def test_continuous_errors_sample_guards_and_direction(
    count: int, error: float, direction: str, word: str
) -> None:
    rows = summary_rows(count, error=error)
    for row in rows:
        row["metric"] = "revenue_cagr"
    summary = _continuous_summary(rows)[0]
    assert summary["status"] == sample_status(count)
    assert len(summary["raw_errors"]) == count
    if count < 5:
        assert summary["mean_error"] is None and summary["directional_bias"] is None
    else:
        assert summary["mean_error"] == pytest.approx(error)
        assert summary["median_error"] == pytest.approx(error)
        assert summary["mean_absolute_error"] == pytest.approx(abs(error))
        assert summary["mean_error_pp"] == pytest.approx(error * 100)
        assert summary["directional_bias"] == direction
    assert (summary["interpretation"] is None) is (count < 20)
    if count >= 20:
        assert word in summary["interpretation"]


def test_mean_median_mae_differ_and_share_direction_not_value_judgment() -> None:
    rows = summary_rows(20)
    for index, row in enumerate(rows):
        row.update(
            metric="share_count_cagr", forecast_error=-0.1 if index < 19 else 0.5
        )
    summary = _continuous_summary(rows)[0]
    assert summary["mean_error"] == pytest.approx(-0.07)
    assert summary["median_error"] == -0.1
    assert summary["mean_absolute_error"] == pytest.approx(0.12)
    assert "desirability" in summary["interpretation"]


def test_empty_and_no_outcome_valid_report(store: SqliteStore) -> None:
    report = run_calibration(store, as_of="2026-11-02")
    assert report["status"] == "INSUFFICIENT_HISTORY_FOR_CALIBRATION"
    assert report["eligible_sample_count"] == report["excluded_sample_count"] == 0
    assert read_report(store, report["report_id"]) == report
    persist(store, "ADBE", snapshot())
    report = build_report(store, as_of="2026-11-02")
    assert report["excluded_sample_count"] == 1
    assert report["exclusions"][0]["status"] == "INSUFFICIENT_DATA"
    assert "NO_OUTCOME" in report["exclusions"][0]["reason"]
    assert report["date_range"] == {"start": None, "end": None}


def test_completed_exact_link_raw_scores_and_bias(store: SqliteStore) -> None:
    selected, observation = completed(store)
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 1
    assert report["eligible_pair_count"] == 2
    assert report["candidate_pair_count"] == 2
    assert report["excluded_sample_count"] == 0
    assert report["status"] == "INSUFFICIENT_HISTORY_FOR_CALIBRATION"
    assert report["probability_calibration"]["mean_brier"] is None
    raw = report["probability_calibration"]["raw_scores"][0]
    assert raw["realized_region"] == "BASE"
    assert raw["observation_id"] == observation["observation_id"]
    assert raw["underwriting"]["version"] == selected.version
    assert (
        raw["underwriting"]["content_hash"]
        == observation["underwriting"]["content_hash"]
    )
    growth = report["continuous_forecast_errors"][0]
    assert growth["raw_errors"][0]["forecast_error"] == pytest.approx(-0.026)
    assert growth["mean_error"] is None
    assert report["cohorts"] and all(item["suppressed"] for item in report["cohorts"])


def test_between_scenarios_not_scored_but_fundamental_still_eligible(
    store: SqliteStore,
) -> None:
    _, observation = completed(store, region="AMBIGUOUS")
    report = build_report(store, as_of=AS_OF)
    probability = report["probability_calibration"]
    assert report["eligible_sample_count"] == 1
    assert probability["eligible_sample_count"] == 0
    assert probability["ambiguous_count"] == 1
    assert probability["raw_scores"] == [] and probability["mean_brier"] is None
    assert (
        probability["excluded_from_scoring"][0]["observation_id"]
        == observation["observation_id"]
    )
    assert report["continuous_forecast_errors"][0]["raw_errors"]


@pytest.mark.parametrize(
    "kind,status",
    [
        ("interim", "INTERIM_ONLY"),
        ("unit", "NOT_COMPARABLE"),
        ("missing", "INSUFFICIENT_DATA"),
    ],
)
def test_interim_incompatible_and_missing_exclusions(
    store: SqliteStore, kind: str, status: str
) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input()
    if kind == "interim":
        data["observation_date"] = "2027-06-02"
        data["fundamentals"] = [fundamental(fiscal_year=2026, period_end="2026-12-31")]
    elif kind == "unit":
        data["market"]["currency"] = "EUR"
        data["fundamentals"][0]["unit"] = "%"
    else:
        data["market"] = None
        data["fundamentals"][0]["value"] = None
    create_observation(store, selected, data, now=NOW)
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 0
    assert report["excluded_sample_count"] == 2
    assert all(item["status"] == status for item in report["exclusions"])


def test_earliest_eligible_pair_no_repeated_observation_inflation(
    store: SqliteStore,
) -> None:
    selected, first = completed(store)
    data = outcome_input()
    data["market"]["price"] = 100000
    second = create_observation(store, selected, data, now=NOW + timedelta(days=1))
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 1 and report["eligible_pair_count"] == 2
    assert {item["observation_id"] for item in report["included_pairs"]} == {
        first["observation_id"]
    }
    assert {item["observation_id"] for item in report["exclusions"]} == {
        second["observation_id"]
    }
    assert all("DUPLICATE" in item["reason"] for item in report["exclusions"])


def test_interim_does_not_block_completed_pair(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input(observation_date="2027-06-02", fundamentals=[])
    create_observation(store, selected, data, now=NOW - timedelta(days=1))
    create_observation(store, selected, outcome_input(), now=NOW)
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 1
    assert report["exclusion_counts"] == {"INTERIM_ONLY": 1}


def test_no_lookahead_and_old_asof_reproducible_after_new_outcome(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    before = canonical_json(build_report(store, as_of="2031-12-31"))
    create_observation(store, selected, outcome_input(), now=NOW)
    assert canonical_json(build_report(store, as_of="2031-12-31")) == before
    assert build_report(store, as_of="2032-01-02")["eligible_sample_count"] == 1
    assert build_report(store, as_of="2026-06-01")["input_underwritings"] == []


def test_missing_probabilities_never_use_newer_version(store: SqliteStore) -> None:
    original = snapshot()
    persist(
        store,
        "ADBE",
        replace(
            original, manual=replace(original.manual, probability_distribution=None)
        ),
    )
    selected, _ = completed(store)
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 1
    assert report["exclusions"][0]["status"] == "NOT_ELIGIBLE"
    assert report["exclusions"][0]["underwriting"]["version"] == 1
    assert (
        report["included_pairs"][0]["underwriting"]["version"] == selected.version == 2
    )


def test_unordered_share_scenarios_still_have_comparable_continuous_base_error(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input(
        market=None, fundamentals=[fundamental("share_count_cagr", -0.03)]
    )
    create_observation(store, selected, data, now=NOW)
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 1
    assert report["continuous_forecast_errors"][0]["raw_errors"][0][
        "forecast_error"
    ] == pytest.approx(-0.01)
    assert report["probability_calibration"]["eligible_sample_count"] == 0


def test_cohorts_frozen_metadata_and_sparse_suppression(store: SqliteStore) -> None:
    for _ in range(5):
        original = snapshot()
        evidence = json.loads(original.evidence_json)
        evidence["feature7_context"].update(sector="Technology", industry="Software")
        selected = persist(
            store, "ADBE", replace(original, evidence_json=json.dumps(evidence))
        )
        create_decision(
            store, selected, input_data(), now=datetime(2026, 6, 3, 12, tzinfo=UTC)
        )
        create_observation(store, selected, outcome_input(), now=NOW)
    report = build_report(store, as_of=AS_OF)
    assert report["status"] == "EARLY_SIGNAL_ONLY"
    cohorts = {(item["dimension"], item["value"]): item for item in report["cohorts"]}
    assert cohorts[("sector", "Technology")]["eligible_sample_count"] == 5
    assert cohorts[("industry", "Software")]["suppressed"] is False
    assert cohorts[("setup_type", "COMPOUNDER")]["status"] == "EARLY_SIGNAL_ONLY"
    assert cohorts[("decision_type", "WATCH")]["eligible_sample_count"] == 5
    assert report["continuous_forecast_errors"][0]["mean_error"] == pytest.approx(
        -0.026
    )
    # All market prices are between anchors: do not inherit the global eligible count.
    assert (
        report["probability_calibration"]["status"]
        == "INSUFFICIENT_HISTORY_FOR_CALIBRATION"
    )
    company = build_report(store, as_of=AS_OF, company="adbe")
    assert company["company"] == "ADBE" and company["eligible_sample_count"] == 5


def test_report_persistence_integrity_idempotence_and_no_input_mutation(
    store: SqliteStore,
) -> None:
    completed(store)
    before = (
        store.list_underwriting("ADBE"),
        store.list_outcome_observations(),
        store.list_decisions(),
        store.list_change_events(),
        store.list_sizing_analyses(),
    )
    report = run_calibration(store, as_of=AS_OF)
    assert run_calibration(store, as_of=AS_OF) == report
    assert read_report(store, report["report_id"]) == report
    assert before == (
        store.list_underwriting("ADBE"),
        store.list_outcome_observations(),
        store.list_decisions(),
        store.list_change_events(),
        store.list_sizing_analyses(),
    )
    for sql in (
        "UPDATE calibration_reports SET content_hash='bad' WHERE report_id=?",
        "DELETE FROM calibration_reports WHERE report_id=?",
        "INSERT OR REPLACE INTO calibration_reports SELECT * FROM calibration_reports WHERE report_id=?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._conn.execute(sql, (report["report_id"],))
        store._conn.rollback()
    forged = deepcopy(report)
    forged["eligible_sample_count"] = 100
    with pytest.raises(StorageWriteError, match="differs"):
        store.save_calibration_report(canonical_json(forged))
    completed(store, ticker="MSFT")
    assert read_report(store, report["report_id"]) == report
    assert run_calibration(store, as_of=AS_OF)["report_id"] != report["report_id"]
    store._conn.executescript(
        "DROP TRIGGER calibration_no_update; UPDATE calibration_reports SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        read_report(store, report["report_id"])


def test_read_saved_report_never_recomputes(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = run_calibration(store, as_of=AS_OF)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Historical calibration read cannot recompute.")

    monkeypatch.setattr("owner_lens.calibration.build_report", forbidden)
    assert read_report(store, report["report_id"]) == report


def test_schema10_additive_migration_preserves_sources(store: SqliteStore) -> None:
    completed(store)
    before = store.list_outcome_observations()
    store._conn.executescript(
        "DROP TABLE calibration_reports; UPDATE schema_meta SET value='10' WHERE key='schema_version';"
    )
    store.initialize()
    assert store.list_outcome_observations() == before
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "12"
    )
    assert run_calibration(store, as_of=AS_OF)["eligible_sample_count"] == 1


def test_cli_valid_insufficient_history_and_show(
    store: SqliteStore, capsys: pytest.CaptureFixture[str]
) -> None:
    persist(store, "ADBE", snapshot())
    assert main(["calibration", "run", "--as-of", "2026-11-02", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "INSUFFICIENT_HISTORY_FOR_CALIBRATION"
    assert main(["calibration", "show", report["report_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert main(["calibration", "company", "ADBE", "--as-of", "2026-11-02"]) == 0
    assert "INSUFFICIENT_HISTORY_FOR_CALIBRATION" in capsys.readouterr().out
    assert main(["calibration", "show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert main(["calibration", "run", "--as-of", "invalid"]) == 1
    assert "Error" in capsys.readouterr().err
    assert "No scenario winner" not in format_report(report)  # No invented realization.


def test_workbench_insufficient_history_readonly_until_save(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Calibration"
    app.run()
    assert not app.exception and not app.error
    assert any(
        "INSUFFICIENT_HISTORY_FOR_CALIBRATION" in item.value for item in app.warning
    )
    assert (
        store._conn.execute("SELECT COUNT(*) FROM calibration_reports").fetchone()[0]
        == 0
    )
    app.button(key="calibration_save").click().run()
    assert not app.exception and not app.error
    assert (
        store._conn.execute("SELECT COUNT(*) FROM calibration_reports").fetchone()[0]
        == 1
    )
    assert not store.list_outcome_observations()


def test_twenty_completed_forecasts_support_independent_summary_guards(
    store: SqliteStore,
) -> None:
    for index in range(20):
        completed(
            store,
            region="BEAR" if index < 6 else "BULL" if index < 8 else "BASE",
            metric_value=0.082,
        )
    report = build_report(store, as_of=AS_OF)
    assert report["status"] == "CALIBRATION_AVAILABLE"
    assert report["eligible_sample_count"] == 20
    assert report["eligible_pair_count"] == 40
    probability = report["probability_calibration"]
    assert probability["status"] == "CALIBRATION_AVAILABLE"
    assert probability["eligible_sample_count"] == 20
    assert [
        item["observed_region_frequency"] for item in probability["scenario_frequency"]
    ] == [0.3, 0.6, 0.1]
    growth = report["continuous_forecast_errors"][0]
    assert growth["mean_error_pp"] == pytest.approx(-1.8)
    assert "optimistic" in growth["interpretation"]
    assert report["missing_cohort_metadata"]["sector"] == 20
    assert report["forecast_date_range"] == {"start": "2026-06-02", "end": "2026-06-02"}


def test_ambiguous_first_terminal_observation_cannot_be_cherry_picked_away(
    store: SqliteStore,
) -> None:
    selected, first = completed(store, region="AMBIGUOUS")
    data = outcome_input()
    data["market"]["price"] = 100000
    create_observation(store, selected, data, now=NOW + timedelta(days=1))
    report = build_report(store, as_of=AS_OF)
    assert report["probability_calibration"]["ambiguous_count"] == 1
    assert report["probability_calibration"]["eligible_sample_count"] == 0
    assert report["included_pairs"][0]["observation_id"] == first["observation_id"]


def test_condition_named_market_price_cannot_become_a_market_sample(
    store: SqliteStore,
) -> None:
    from test_changes import predicate_snapshot

    original = predicate_snapshot(condition_id="market_price")
    selected = persist(store, "ADBE", original)
    metric = fundamental(
        forecast={"kind": "CONDITION", "id": "market_price"},
        observable="Total Adobe ARR growth",
        value=5.8,
        unit="percent_yoy",
        cadence="quarterly",
        source_family="adobe_earnings",
    )
    create_observation(
        store, selected, outcome_input(market=None, fundamentals=[metric]), now=NOW
    )
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 0
    assert any("condition-only" in item["reason"] for item in report["exclusions"])


def test_unknown_outcome_model_excluded_explicitly(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, observation = completed(store)
    records = store.list_outcome_observations()
    data = deepcopy(observation)
    data["model_version"] = "future-unknown-model"
    payload = canonical_json(data)
    from owner_lens.persistence import compute_content_hash

    altered = replace(
        records[0],
        snapshot_json=payload,
        content_hash=compute_content_hash(payload.encode()),
    )
    monkeypatch.setattr(store, "list_outcome_observations", lambda: (altered,))
    report = build_report(store, as_of=AS_OF)
    assert report["eligible_sample_count"] == 0
    assert report["exclusions"][0]["status"] == "NOT_COMPARABLE"
    assert "version" in report["exclusions"][0]["reason"]


def test_decision_after_measurement_cannot_supply_a_hindsight_cohort(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_decision(
        store, selected, input_data(), now=datetime(2031, 6, 3, 10, tzinfo=UTC)
    )
    create_observation(store, selected, outcome_input(), now=NOW)
    report = build_report(store, as_of=AS_OF)
    assert all(
        item["cohorts"]["decision_type"] is None for item in report["included_pairs"]
    )
    assert not any(item["dimension"] == "decision_type" for item in report["cohorts"])


def test_workbench_populated_calibration_and_company_filter(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    completed(store)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Calibration"
    app.session_state["calibration_as_of"] = NOW.date()
    app.session_state["calibration_company"] = "ADBE"
    app.run()
    assert not app.exception and not app.error
    assert any("Eligible forecasts: 1" in item.value for item in app.markdown)
    assert app.dataframe
    assert (
        store._conn.execute("SELECT COUNT(*) FROM calibration_reports").fetchone()[0]
        == 0
    )

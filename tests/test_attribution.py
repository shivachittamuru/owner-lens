"""Fixture-only layered attribution, investor authority and exact immutable linkage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_calibration import completed
from test_changes import event_input, monitored_snapshot
from test_decisions import comparison_input, four_companies, input_data
from test_mistakes import label
from test_mistakes import review_input as mistake_input
from test_opportunity_comparison import persist, snapshot
from test_outcomes import fundamental, outcome_input
from test_position_sizing import policy, portfolio_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.attribution import (
    AUDIT_CODES,
    AttributionError,
    build_review,
    create_review,
    read_review,
    review_history,
    review_summary,
)
from owner_lens.calibration import run_calibration
from owner_lens.changes import approve_event, create_event
from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.mistakes import create_review as create_mistake_review
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import create_observation
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import canonical_json, create_portfolio, size_position
from owner_lens.workbench.data import WorkbenchSource

NOW = datetime(2032, 1, 4, 12, tzinfo=UTC)
EARLY = datetime(2026, 6, 3, 12, tzinfo=UTC)
ROOT = Path(__file__).parents[1]
APP = ROOT / "src" / "owner_lens" / "workbench" / "app.py"


def reviewed(**changes: Any) -> dict[str, Any]:
    return {
        "rationale": "Explicit synthetic investor review, not an Adobe assertion.",
        "evidence_references": [{"title": "Synthetic exact frozen records"}],
        "investor_reviewed": True,
        **changes,
    }


def review_input(**changes: Any) -> dict[str, Any]:
    return {
        "as_of_date": NOW.date().isoformat(),
        "category": "JUDGMENT",
        "links": {},
        "reviewer": "Investor",
        "confidence": "LOW",
        "interpretation": "Evidence is incomplete; no skill, luck or causal conclusion.",
        "investor_reviewed": True,
        "evidence_references": [{"title": "Exact selected underwriting"}],
        "process_reviews": [],
        "decision_framework_review": None,
        "actual_position": None,
        "relative_outcomes": [],
        "external_review": reviewed(status="UNRESOLVED", contributors=[]),
        "unresolved_questions": ["What remains missing in the decision-time evidence?"],
        **changes,
    }


def fixed_review(
    store: SqliteStore, selected: UnderwritingSelection, data: Any
) -> dict[str, Any]:
    return build_review(
        store,
        selected,
        data,
        review_id="10000000-0000-0000-0000-000000000001",
        recorded_at=NOW.isoformat(),
    )


def audit(code: str, **changes: Any) -> dict[str, Any]:
    return {
        **reviewed(code=code, status="SATISFIED", performed_at=EARLY.isoformat()),
        **changes,
    }


def actual_position(oid: str, **changes: Any) -> dict[str, Any]:
    return {
        **reviewed(
            category="FACT",
            units=10,
            entry_price=20,
            entry_at=(EARLY + timedelta(hours=1)).isoformat(),
            currency="USD",
            starting_portfolio_value=1000,
            end_observation_id=oid,
            constant_units_no_flows=True,
            basis="EOD_CLOSE_SAME_SHARE_BASIS",
        ),
        **changes,
    }


def case_with_shadows(
    store: SqliteStore,
) -> tuple[UnderwritingSelection, dict[str, Any], dict[str, Any]]:
    selections = four_companies(store)
    decision = create_decision(
        store, selections[0], comparison_input(store, selections), now=EARLY
    )
    outcome = create_observation(store, selections[0], outcome_input(), now=NOW)
    return selections[0], json.loads(decision.to_json()), outcome


def relative_input(
    decision: dict[str, Any], oid: str, role: str = "BENCHMARK", **changes: Any
) -> dict[str, Any]:
    shadow = next(item for item in decision["shadows"] if item["role"] == role)
    price = shadow["frozen_price"] or 100
    return {
        **reviewed(
            shadow_id=shadow["shadow_id"],
            observation_id=oid,
            start_date="2026-06-01",
            end_date="2031-06-02",
            start_price=price,
            end_price=price * 1.1,
            currency="USD",
            basis="EOD_CLOSE_SAME_SHARE_BASIS",
            return_basis="UNDERWRITING_MARKET",
        ),
        **changes,
    }


def test_review_with_unresolved_layers_is_valid_and_not_forced(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    report = create_review(store, selected, review_input(), now=NOW)
    assert report["process"]["status"] == "PROCESS_UNRESOLVED"
    assert report["decision"]["status"] == "DECISION_CONTEXT_INCOMPLETE"
    assert report["portfolio"]["status"] == "INSUFFICIENT_DATA"
    assert report["external"]["status"] == "UNRESOLVED"
    assert report["outcome"] == "UNRESOLVED"
    assert all(
        item["status"] == "INSUFFICIENT_DATA"
        for item in report["forecast"]["forecasts"]
    )
    assert report["semantic_role"] == "ATTRIBUTION" and report["category"] == "JUDGMENT"


def test_immutable_history_exact_v1_and_stable_saved_json(store: SqliteStore) -> None:
    selected, outcome = completed(store)
    data = review_input(links={"observation_ids": [outcome["observation_id"]]})
    first = create_review(store, selected, data, now=NOW)
    before = canonical_json(first)
    persist(store, "ADBE", snapshot(price=50))
    second = create_review(store, selected, data, now=NOW + timedelta(days=1))
    assert first["review_id"] != second["review_id"]
    assert first["underwriting"] == second["underwriting"]
    assert len(review_history(store, "ADBE")) == 2
    assert canonical_json(read_review(store, first["review_id"])) == before
    assert canonical_json(fixed_review(store, selected, data)) == canonical_json(
        fixed_review(store, selected, data)
    )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE attribution_reviews SET recorded_at='2099-01-01'",
        "DELETE FROM attribution_reviews",
        "INSERT OR REPLACE INTO attribution_reviews SELECT * FROM attribution_reviews",
    ],
)
def test_append_only_database_guards(store: SqliteStore, sql: str) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_review(store, selected, review_input(), now=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(sql)
    store._conn.rollback()


def test_explicit_process_review_can_resolve_unknowns_without_causal_claim(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = review_input(process_reviews=[audit(code) for code in AUDIT_CODES])
    report = create_review(store, selected, data, now=NOW)
    assert report["process"]["status"] == "PROCESS_COMPLIANT"
    assert all(
        item["investor_review"]["investor_reviewed"]
        for item in report["process"]["checks"]
    )
    assert report["outcome"] == "UNRESOLVED"
    assert "no causal" in report["process"]["note"].lower()


@pytest.mark.parametrize("override", ["SATISFIED", "NOT_APPLICABLE", "UNRESOLVED"])
def test_approved_thesis_change_creates_process_exception_not_auto_attribution_cause(
    store: SqliteStore,
    override: str,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    links = {"change_event_ids": [event["event_id"]]}
    pending = create_review(store, selected, review_input(links=links), now=NOW)
    assert pending["process"]["status"] != "PROCESS_EXCEPTIONS"
    approve_event(
        store, event["event_id"], "THESIS_UPDATE", "Needs a new review.", now=EARLY
    )
    report = create_review(store, selected, review_input(links=links), now=NOW)
    assert report["process"]["status"] == "PROCESS_EXCEPTIONS"
    with pytest.raises(AttributionError, match="erase"):
        create_review(
            store,
            selected,
            review_input(
                links=links,
                process_reviews=[audit("REUNDERWRITING_PERFORMED", status=override)],
            ),
            now=NOW,
        )
    assert (
        read_review(store, pending["review_id"])["process"]["status"]
        != "PROCESS_EXCEPTIONS"
    )


@pytest.mark.parametrize(
    "action,price,status",
    [
        ("BUY", 20, "CONSISTENT_WITH_RECORDED_FRAMEWORK"),
        ("ADD", 20, "CONSISTENT_WITH_RECORDED_FRAMEWORK"),
        ("BUY", 1000, "INCONSISTENT_WITH_RECORDED_FRAMEWORK"),
        ("ADD", 1000, "INCONSISTENT_WITH_RECORDED_FRAMEWORK"),
        ("TRIM", 20, "DECISION_CONTEXT_INCOMPLETE"),
        ("EXIT", 20, "DECISION_CONTEXT_INCOMPLETE"),
        ("WATCH", 20, "DECISION_CONTEXT_INCOMPLETE"),
    ],
)
def test_decision_consistency_uses_original_frozen_hurdle(
    store: SqliteStore, action: str, price: float, status: str
) -> None:
    selected = persist(store, "ADBE", snapshot(price=price))
    decision = create_decision(
        store, selected, {**input_data(), "action": action}, now=EARLY
    )
    report = create_review(
        store,
        selected,
        review_input(links={"decision_id": decision.decision_id}),
        now=NOW,
    )
    assert report["decision"]["status"] == status
    assert report["outcome"] == "UNRESOLVED"


@pytest.mark.parametrize(
    "action,basis", [("WATCH", "EVIDENCE_INSUFFICIENT"), ("PASS", "UNRESOLVED_RISK")]
)
def test_watch_pass_explicit_recorded_basis_no_execution(
    store: SqliteStore, action: str, basis: str
) -> None:
    selected, outcome = completed(store, region="BULL")
    decision = create_decision(
        store, selected, {**input_data(), "action": action}, now=EARLY
    )
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision.decision_id,
                "observation_ids": [outcome["observation_id"]],
            },
            decision_framework_review=reviewed(basis=basis),
        ),
        now=NOW,
    )
    assert report["decision"]["status"] == "CONSISTENT_WITH_RECORDED_FRAMEWORK"
    assert report["portfolio"]["actual_capital_outcome"] == "NOT_DEPLOYED"
    assert report["portfolio"]["position_contribution"] is None
    assert report["portfolio"]["portfolio_contribution"] is None
    assert not report["portfolio"]["market_outcomes"][0]["execution_established"]


@pytest.mark.parametrize(
    "value,status",
    [
        (0.05, "MISSED_LOW"),
        (0.15, "MISSED_HIGH"),
        (0.1, "SUPPORTED"),
        (0.09, "SUPPORTED"),
    ],
)
def test_mature_forecast_direction_and_threshold(
    store: SqliteStore, value: float, status: str
) -> None:
    selected, outcome = completed(store, metric_value=value)
    report = create_review(
        store,
        selected,
        review_input(links={"observation_ids": [outcome["observation_id"]]}),
        now=NOW,
    )
    growth = next(
        item
        for item in report["forecast"]["forecasts"]
        if item["metric"] == "revenue_cagr"
    )
    assert growth["status"] == status
    assert growth["forecast_error"] == pytest.approx(value - 0.1)
    assert (
        report["context"]["outcomes"][0]["report"]["observation"]["category"] == "FACT"
    )


def test_immature_and_incompatible_forecasts_not_scored_early(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input(
        observation_date="2027-06-02",
        observed_at="2027-06-03T11:00:00+00:00",
        horizon="1Y",
        references=[{"title": "Synthetic interim report", "observed_at": "2027-06-03"}],
        fundamentals=[
            fundamental(value=0.01, fiscal_year=2026, period_end="2026-12-31")
        ],
    )
    outcome = create_observation(store, selected, data, now=NOW)
    report = create_review(
        store,
        selected,
        review_input(links={"observation_ids": [outcome["observation_id"]]}),
        now=NOW,
    )
    for metric in ("market_price", "revenue_cagr"):
        assert (
            next(
                item
                for item in report["forecast"]["forecasts"]
                if item["metric"] == metric
            )["status"]
            == "NOT_MATURE"
        )
    incompatible = create_observation(
        store,
        selected,
        outcome_input(
            fundamentals=[fundamental(observable="Revenue CAGR", unit="percent")],
        ),
        now=NOW,
    )
    report = create_review(
        store,
        selected,
        review_input(links={"observation_ids": [incompatible["observation_id"]]}),
        now=NOW,
    )
    assert report["forecast"]["forecasts"][0]["status"] == "NOT_COMPARABLE"


def test_mistake_review_is_judgment_not_auto_conversion(store: SqliteStore) -> None:
    selected, outcome = completed(store, metric_value=0.05)
    mistake = create_mistake_review(
        store,
        selected,
        mistake_input(
            links={"observation_ids": [outcome["observation_id"]]},
            approved_labels=[label("GROWTH_TOO_HIGH")],
        ),
        now=NOW,
    )
    no_outcomes = create_review(
        store,
        selected,
        review_input(links={"mistake_review_id": mistake["review_id"]}),
        now=NOW,
    )
    assert no_outcomes["context"]["mistake_review"]["semantic_role"] == "MISTAKE_REVIEW"
    assert all(
        item["status"] == "INSUFFICIENT_DATA"
        for item in no_outcomes["forecast"]["forecasts"]
    )
    linked = create_review(
        store,
        selected,
        review_input(
            links={
                "mistake_review_id": mistake["review_id"],
                "observation_ids": [outcome["observation_id"]],
            }
        ),
        now=NOW,
    )
    assert linked["forecast"]["forecasts"][0]["status"] == "MISSED_LOW"


def test_hypothetical_sizing_weighted_arithmetic_never_actual_holdings(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store)
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    sized = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(),
        proposed_increment=0.01,
        now=EARLY,
    )
    saved = store.save_sizing_analysis(
        canonical_json(sized), created_at=EARLY.isoformat()
    )
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "sizing_analysis_id": saved.analysis_id,
                "observation_ids": [outcome["observation_id"]],
            }
        ),
        now=NOW,
    )
    layer = report["portfolio"]
    assert layer["status"] == "HYPOTHETICAL_ONLY"
    assert layer["position_contribution"] is None
    assert layer["portfolio_contribution"] is None
    expected = (
        sized["proposed_target_weight"]
        * outcome["market_outcome"]["total_price_return"]
    )
    assert layer["hypothetical_contributions"][0]["contribution"] == pytest.approx(
        expected
    )


def test_actual_position_evidence_supports_only_transparent_mark_to_market(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(
        store, selected, {**input_data(), "action": "BUY"}, now=EARLY
    )
    outcome = create_observation(store, selected, outcome_input(), now=NOW)
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision.decision_id,
                "observation_ids": [outcome["observation_id"]],
            },
            actual_position=actual_position(outcome["observation_id"]),
        ),
        now=NOW,
    )
    layer = report["portfolio"]
    assert layer["status"] == "ACTUAL_POSITION_MARK_TO_MARKET"
    assert layer["position_contribution"] == 100
    assert layer["portfolio_contribution"] == pytest.approx(0.1)
    assert layer["position_price_return"] == pytest.approx(0.5)
    assert layer["start_weight"] == pytest.approx(0.2)
    assert "not realized" in layer["capital_basis"]


@pytest.mark.parametrize(
    "change",
    [
        {"category": "JUDGMENT"},
        {"constant_units_no_flows": False},
        {"units": -1},
        {"entry_price": 0},
        {"starting_portfolio_value": 1},
        {"currency": "EUR"},
        {"basis": "UNADJUSTED"},
        {"investor_reviewed": False},
        {"entry_at": "2025-01-01T00:00:00+00:00"},
        {"entry_at": "2099-01-01T00:00:00+00:00"},
        {"end_observation_id": "missing"},
    ],
)
def test_invalid_actual_evidence_rejected(
    store: SqliteStore, change: dict[str, Any]
) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(store, selected, input_data(), now=EARLY)
    outcome = create_observation(store, selected, outcome_input(), now=NOW)
    evidence = {**actual_position(outcome["observation_id"]), **change}
    with pytest.raises(ValueError):
        create_review(
            store,
            selected,
            review_input(
                links={
                    "decision_id": decision.decision_id,
                    "observation_ids": [outcome["observation_id"]],
                },
                actual_position=evidence,
            ),
            now=NOW,
        )


def test_benchmark_and_recorded_best_alternative_relative_arithmetic(
    store: SqliteStore,
) -> None:
    selected, decision, outcome = case_with_shadows(store)
    links = {
        "decision_id": decision["decision_id"],
        "observation_ids": [outcome["observation_id"]],
    }
    comparisons = [
        relative_input(decision, outcome["observation_id"], role)
        for role in ("BENCHMARK", "BEST_ALTERNATIVE")
    ]
    report = create_review(
        store,
        selected,
        review_input(links=links, relative_outcomes=comparisons),
        now=NOW,
    )
    assert [row["kind"] for row in report["relative_outcomes"]] == [
        "BENCHMARK_OUTCOME",
        "SHADOW_ALTERNATIVE_OUTCOME",
    ]
    for row in report["relative_outcomes"]:
        assert row["price_return"] == pytest.approx(0.1)
        assert row["difference"] == pytest.approx(0.4)
        assert row["semantic_role"] == "RELATIVE_OUTCOME"
    assert report["portfolio"]["status"] == "HYPOTHETICAL_ONLY"
    assert report["portfolio"]["actual_capital_outcome"] == "NOT_DEPLOYED"
    assert review_summary(store)["average_relative_market_outcome"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"start_date": "2026-06-02"},
        {"end_date": "2031-06-03"},
        {"currency": "EUR"},
        {"start_price": 0},
        {"basis": "TOTAL_RETURN"},
        {"shadow_id": "missing"},
        {"investor_reviewed": False},
        {"return_basis": "ACTUAL_POSITION"},
    ],
)
def test_relative_outcome_guardrails(
    store: SqliteStore, change: dict[str, Any]
) -> None:
    selected, decision, outcome = case_with_shadows(store)
    comparison = {**relative_input(decision, outcome["observation_id"]), **change}
    with pytest.raises(ValueError):
        create_review(
            store,
            selected,
            review_input(
                links={
                    "decision_id": decision["decision_id"],
                    "observation_ids": [outcome["observation_id"]],
                },
                relative_outcomes=[comparison],
            ),
            now=NOW,
        )


def test_frozen_alternative_start_never_substituted(store: SqliteStore) -> None:
    selected, decision, outcome = case_with_shadows(store)
    comparison = relative_input(decision, outcome["observation_id"], "BEST_ALTERNATIVE")
    comparison["start_price"] += 1
    with pytest.raises(AttributionError, match="recorded shadow"):
        create_review(
            store,
            selected,
            review_input(
                links={
                    "decision_id": decision["decision_id"],
                    "observation_ids": [outcome["observation_id"]],
                },
                relative_outcomes=[comparison],
            ),
            now=NOW,
        )


def test_actual_relative_outcome_uses_execution_interval_not_frozen_interval(
    store: SqliteStore,
) -> None:
    selected, decision, outcome = case_with_shadows(store)
    comparison = relative_input(decision, outcome["observation_id"])
    comparison.update(return_basis="ACTUAL_POSITION", start_date="2026-06-03")
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision["decision_id"],
                "observation_ids": [outcome["observation_id"]],
            },
            actual_position=actual_position(outcome["observation_id"], entry_price=25),
            relative_outcomes=[comparison],
        ),
        now=NOW,
    )
    assert report["relative_outcomes"][0]["difference"] == pytest.approx(0.1)
    assert report["relative_outcomes"][0]["return_basis"] == "ACTUAL_POSITION"
    assert report["portfolio"]["actual_capital_outcome"] == "DEPLOYED"


def test_actual_adverse_return_does_not_inherit_favorable_frozen_price_return(
    store: SqliteStore,
) -> None:
    selected, decision, outcome = case_with_shadows(store)
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision["decision_id"],
                "observation_ids": [outcome["observation_id"]],
            },
            actual_position=actual_position(outcome["observation_id"], entry_price=40),
        ),
        now=NOW,
    )
    assert report["market_outcome"] == "FAVORABLE"
    assert report["outcome"] == "ADVERSE"
    assert report["outcome_basis"] == "ACTUAL_POSITION_PRICE_ONLY"


def test_external_contributors_only_explicit_reviewed_judgment(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    external = reviewed(
        status="EXTERNAL_CONTRIBUTOR_RECORDED",
        contributors=[
            reviewed(
                kind="REGULATORY_EVENT",
                statement="Synthetic investor explanation, not machine causality.",
            )
        ],
    )
    report = create_review(
        store, selected, review_input(external_review=external), now=NOW
    )
    assert report["external"]["category"] == "JUDGMENT"
    assert report["external"]["contributors"][0]["investor_reviewed"]
    assert report["outcome"] == "UNRESOLVED"
    external["contributors"][0]["investor_reviewed"] = False
    with pytest.raises(AttributionError, match="investor_reviewed"):
        create_review(store, selected, review_input(external_review=external), now=NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"as_of_date": "2099-01-01"},
        {"investor_reviewed": False},
        {"category": "FACT"},
        {"evidence_references": []},
        {
            "evidence_references": [
                {"title": "Future source", "observed_at": "2099-01-01"}
            ]
        },
        {
            "external_review": reviewed(
                status="EXTERNAL_CONTRIBUTOR_RECORDED", contributors=[]
            )
        },
    ],
)
def test_invalid_review_authority_and_temporal_fields(
    store: SqliteStore, change: dict[str, Any]
) -> None:
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(ValueError):
        create_review(store, selected, review_input(**change), now=NOW)
    assert not store.list_attribution_reviews()


def test_no_lookahead_across_exact_inputs(store: SqliteStore) -> None:
    selected, outcome = completed(store)
    with pytest.raises(ValueError, match="unavailable"):
        create_review(
            store,
            selected,
            review_input(
                as_of_date="2026-06-03",
                links={"observation_ids": [outcome["observation_id"]]},
            ),
            now=NOW,
        )
    calibration = run_calibration(store, as_of="2032-01-03")
    other = persist(store, "ADBE", snapshot())
    for links in (
        {"observation_ids": [outcome["observation_id"]]},
        {"calibration_report_id": calibration["report_id"]},
    ):
        with pytest.raises(ValueError, match="exact"):
            create_review(store, other, review_input(links=links), now=NOW)


def test_missing_requested_version_never_uses_available_latest(
    store: SqliteStore,
) -> None:
    persist(store, "ADBE", snapshot())
    with pytest.raises(ValueError):
        create_review(
            store, UnderwritingSelection("ADBE", 999), review_input(), now=NOW
        )
    assert not store.list_attribution_reviews()


@pytest.mark.parametrize("kind", ["decision", "mistake", "calibration"])
def test_same_day_later_recorded_sources_cannot_enter_review(
    store: SqliteStore,
    kind: str,
) -> None:
    selected, _ = completed(store, now=NOW + timedelta(hours=1))
    if kind == "decision":
        decision = create_decision(
            store, selected, input_data(), now=NOW + timedelta(hours=1)
        )
        links = {"decision_id": decision.decision_id}
    elif kind == "mistake":
        mistake = create_mistake_review(
            store, selected, mistake_input(), now=NOW + timedelta(hours=1)
        )
        links = {"mistake_review_id": mistake["review_id"]}
    else:
        calibration = run_calibration(store, as_of=NOW.date().isoformat())
        links = {"calibration_report_id": calibration["report_id"]}
    with pytest.raises(ValueError, match="unavailable|cutoff"):
        create_review(store, selected, review_input(links=links), now=NOW)


def test_saved_reads_do_not_recompute_and_detect_corrupt_payload(
    store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    report = create_review(store, selected, review_input(), now=NOW)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Historical reads must not rebuild.")

    monkeypatch.setattr("owner_lens.attribution.build_review", forbidden)
    assert canonical_json(read_review(store, report["review_id"])) == canonical_json(
        report
    )
    store._conn.executescript(
        "DROP TRIGGER attribution_no_update; UPDATE attribution_reviews SET content_hash='corrupted';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        read_review(store, report["review_id"])


def test_later_process_work_cannot_establish_decision_time_compliance(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(store, selected, input_data(), now=EARLY)
    with pytest.raises(AttributionError, match="later work"):
        create_review(
            store,
            selected,
            review_input(
                links={"decision_id": decision.decision_id},
                process_reviews=[
                    audit("SUPPORTING_EVIDENCE_VERIFIED", performed_at=NOW.isoformat())
                ],
            ),
            now=NOW,
        )


def test_cross_case_sampling_warnings_and_duplicate_review_not_new_case(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store)
    data = review_input(links={"observation_ids": [outcome["observation_id"]]})
    for _ in range(5):
        create_review(store, selected, data, now=NOW)
    summary = review_summary(store)
    assert summary["review_count"] == 5 and summary["case_count"] == 1
    assert summary["sample_warning"] == "INSUFFICIENT_ATTRIBUTION_HISTORY"
    assert summary["process_compliance_rate"] is None
    assert summary["average_relative_market_outcome"] is None
    for _ in range(4):
        selected, outcome = completed(store)
        create_review(
            store,
            selected,
            review_input(
                links={"observation_ids": [outcome["observation_id"]]},
            ),
            now=NOW,
        )
    summary = review_summary(store)
    assert summary["case_count"] == 5
    assert summary["sample_warning"] == "DESCRIPTIVE_ONLY"
    assert summary["forecast_misses"]["revenue_cagr:MISSED_LOW"] == 5
    assert summary["cohorts"]


def test_earliest_mature_review_supersedes_early_unresolved_case_for_summary_only(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store)
    first = create_review(store, selected, review_input(), now=NOW)
    later = create_review(
        store,
        selected,
        review_input(
            links={"observation_ids": [outcome["observation_id"]]},
        ),
        now=NOW + timedelta(days=1),
    )
    assert review_summary(store)["review_ids"] == [later["review_id"]]
    assert read_review(store, first["review_id"])["outcome"] == "UNRESOLVED"


def test_summary_resolved_denominators_and_terminal_benchmark_math(
    store: SqliteStore,
) -> None:
    selections = four_companies(store)
    for index in range(5):
        selected = persist(store, "ADBE", snapshot()) if index else selections[0]
        decision_record = create_decision(
            store,
            selected,
            comparison_input(store, [selected, *selections[1:]]),
            now=EARLY,
        )
        decision = json.loads(decision_record.to_json())
        outcome = create_observation(store, selected, outcome_input(), now=NOW)
        revised_data = outcome_input()
        revised_data["market"]["price"] = 40
        revised = create_observation(
            store, selected, revised_data, now=NOW + timedelta(hours=1)
        )
        data = review_input(
            links={
                "decision_id": decision["decision_id"],
                "observation_ids": [
                    outcome["observation_id"],
                    revised["observation_id"],
                ],
            },
            process_reviews=[audit(code) for code in AUDIT_CODES],
            relative_outcomes=[
                relative_input(decision, revised["observation_id"]),
                relative_input(decision, outcome["observation_id"]),
            ],
        )
        create_review(store, selected, data, now=NOW + timedelta(hours=2))
        if index == 0:
            create_review(store, selected, data, now=NOW + timedelta(days=1))
    result = review_summary(store)
    assert result["review_count"] == 6 and result["case_count"] == 5
    assert result["process_resolved_count"] == 5
    assert result["process_compliance_rate"] == 1
    assert result["benchmark_comparison_count"] == 5
    assert result["average_relative_market_outcome"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    "units,delayed,status",
    [
        (1, False, "WITHIN_POLICY"),
        (10, False, "POLICY_EXCEPTIONS"),
        (10, True, "POLICY_UNRESOLVED"),
    ],
)
def test_actual_policy_is_separate_from_hypothetical_proposal(
    store: SqliteStore,
    units: int,
    delayed: bool,
    status: str,
) -> None:
    selected, outcome = completed(store)
    decision = create_decision(store, selected, input_data(), now=EARLY)
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    timestamp = EARLY + timedelta(hours=2) if delayed else EARLY
    sized = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(),
        decision_id=decision.decision_id,
        proposed_increment=0.01,
        now=timestamp,
    )
    saved = store.save_sizing_analysis(
        canonical_json(sized), created_at=timestamp.isoformat()
    )
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision.decision_id,
                "sizing_analysis_id": saved.analysis_id,
                "observation_ids": [outcome["observation_id"]],
            },
            actual_position=actual_position(outcome["observation_id"], units=units),
        ),
        now=NOW,
    )
    assert report["portfolio"]["policy_status"] == "WITHIN_POLICY"
    assert report["portfolio"]["actual_policy_status"] == status


def test_process_evidence_must_exist_when_work_was_performed(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(ValueError, match="look ahead"):
        create_review(
            store,
            selected,
            review_input(
                process_reviews=[
                    audit(
                        "SUPPORTING_EVIDENCE_VERIFIED",
                        evidence_references=[
                            {
                                "title": "Later review cannot verify earlier work",
                                "observed_at": "2031-06-03",
                            }
                        ],
                    )
                ]
            ),
            now=NOW,
        )


@pytest.mark.parametrize(
    "price_multiplier,status",
    [(0.5, "MISSED_LOW"), (1, "SUPPORTED"), (2, "MISSED_HIGH")],
)
def test_terminal_scenario_attribution_boundaries(
    store: SqliteStore, price_multiplier: float, status: str
) -> None:
    selected, original = completed(store, region="BASE")
    data = outcome_input()
    data["market"]["price"] = (
        original["observation"]["market"]["price"] * price_multiplier
    )
    if price_multiplier == 0.5:
        # Below every frozen scenario anchor, not merely below Base.
        data["market"]["price"] = 0
    if price_multiplier == 2:
        data["market"]["price"] = 1_000_000
    observed = create_observation(store, selected, data, now=NOW)
    result = create_review(
        store,
        selected,
        review_input(links={"observation_ids": [observed["observation_id"]]}),
        now=NOW,
    )
    terminal = next(
        item
        for item in result["forecast"]["forecasts"]
        if item["metric"] == "market_price"
    )
    assert terminal["status"] == status


def test_between_anchor_price_is_ambiguous_not_a_forecast_winner(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    from owner_lens.outcomes import frozen_forecast

    frozen = frozen_forecast(store, selected)
    anchors = frozen["valuation"]["scenarios"]
    prices = {
        item["assumptions"]["name"]: item["year5_value_per_share"] for item in anchors
    }
    data = outcome_input()
    data["market"]["price"] = (prices["BEAR"] + prices["BASE"]) / 2
    observed = create_observation(store, selected, data, now=NOW)
    result = create_review(
        store,
        selected,
        review_input(links={"observation_ids": [observed["observation_id"]]}),
        now=NOW,
    )
    terminal = next(
        item
        for item in result["forecast"]["forecasts"]
        if item["metric"] == "market_price"
    )
    assert (
        terminal["status"] == "NOT_COMPARABLE" and terminal["realized_region"] is None
    )


def test_documented_template_remains_unresolved_without_outcomes(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    template = json.loads(
        (ROOT / "docs" / "examples" / "adbe_attribution.sample.json").read_text()
    )
    template["as_of_date"] = EARLY.date().isoformat()
    result = create_review(store, selected, template, now=EARLY)
    assert result["outcome"] == "UNRESOLVED"
    assert result["portfolio"]["portfolio_contribution"] is None
    assert result["external"]["status"] == "UNRESOLVED"


def test_no_source_mutation_and_storage_tamper_checks(store: SqliteStore) -> None:
    selected, outcome = completed(store)
    decision = create_decision(store, selected, input_data(), now=EARLY)
    before = (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_outcome_observations(),
        store.list_change_events(),
        store.list_change_approvals(),
        store.list_sizing_analyses(),
        store.list_mistake_reviews(),
    )
    data = review_input(
        links={
            "decision_id": decision.decision_id,
            "observation_ids": [outcome["observation_id"]],
        }
    )
    review = fixed_review(store, selected, data)
    tampered = deepcopy(review)
    tampered["decision"]["status"] = "SKILLED"
    with pytest.raises(StorageWriteError, match="differs"):
        store.save_attribution_review(canonical_json(tampered))
    store.save_attribution_review(canonical_json(review))
    assert before == (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_outcome_observations(),
        store.list_change_events(),
        store.list_change_approvals(),
        store.list_sizing_analyses(),
        store.list_mistake_reviews(),
    )
    with pytest.raises(StorageReadError):
        read_review(store, "missing")


def test_schema12_additive_migration_preserves_sources(store: SqliteStore) -> None:
    selected, _ = completed(store)
    mistake = create_mistake_review(store, selected, mistake_input(), now=NOW)
    before = (
        store.list_underwriting("ADBE"),
        store.list_outcome_observations(),
        store.list_mistake_reviews(),
    )
    store._conn.executescript(
        "DROP TABLE attribution_reviews; UPDATE schema_meta SET value='12' WHERE key='schema_version';"
    )
    store.initialize()
    assert before == (
        store.list_underwriting("ADBE"),
        store.list_outcome_observations(),
        store.list_mistake_reviews(),
    )
    assert create_review(
        store,
        selected,
        review_input(links={"mistake_review_id": mistake["review_id"]}),
        now=NOW,
    )


def test_cli_create_show_history_summary_and_failure(
    store: SqliteStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def source():
        yield WorkbenchSource(store, None, "", "")

    monkeypatch.setattr("owner_lens.workbench.data.open_source", source)
    persist(store, "ADBE", snapshot())
    path = tmp_path / "attribution.json"
    path.write_text(
        canonical_json(review_input(as_of_date="2026-06-03")), encoding="utf-8"
    )
    assert (
        main(
            [
                "attribution",
                "review",
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
    for action, arg in (("show", report["review_id"]), ("history", "ADBE")):
        assert main(["attribution", "review", action, arg, "--json"]) == 0
        json.loads(capsys.readouterr().out)
    assert main(["attribution", "summary", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["case_count"] == 1
    assert main(["attribution", "review", "show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err


def test_workbench_explicit_review_gate_and_layer_history(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Attribution"
    app.session_state["attribution_version"] = "ADBE:1"
    app.run()
    assert not app.exception and not store.list_attribution_reviews()
    app.text_area(key="attribution_input").set_value(
        canonical_json(review_input(as_of_date="2026-06-03"))
    )
    button = "FormSubmitter:attribution_create-Append immutable attribution review"
    app.button(key=button).click().run()
    assert app.error and not store.list_attribution_reviews()
    app.checkbox(key="attribution_approve").check()
    app.button(key=button).click().run()
    assert not app.exception and not app.error
    assert len(store.list_attribution_reviews()) == 1
    assert any("Recorded attribution" in item.value for item in app.success)

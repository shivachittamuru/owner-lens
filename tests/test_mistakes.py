"""Fixture-only mistake taxonomy authority, evidence thresholds and immutable histories."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_calibration import completed
from test_changes import event_input, monitored_snapshot
from test_decisions import input_data
from test_opportunity_comparison import persist, snapshot
from test_outcomes import fundamental, outcome_input
from test_position_sizing import policy, portfolio_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.calibration import run_calibration
from owner_lens.changes import approve_event, create_event
from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.mistakes import (
    TAXONOMY,
    TAXONOMY_GROUPS,
    MistakeError,
    build_review,
    create_review,
    read_review,
    review_history,
    review_summary,
    suggest_review,
)
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import create_observation
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import canonical_json, create_portfolio, size_position

NOW = datetime(2032, 1, 3, 12, tzinfo=UTC)
EARLY = datetime(2026, 6, 3, 12, tzinfo=UTC)
ROOT = Path(__file__).parents[1]
APP = ROOT / "src" / "owner_lens" / "workbench" / "app.py"


def label(code: str, **changes: Any) -> dict[str, Any]:
    return {
        "code": code,
        "confidence": "MEDIUM",
        "rationale": "Explicit synthetic investor assessment, not an Adobe assertion.",
        "evidence_references": [{"title": "Synthetic frozen underwriting evidence"}],
        "investor_approved": True,
        **changes,
    }


def review_input(**changes: Any) -> dict[str, Any]:
    return {
        "review_date": NOW.date().isoformat(),
        "category": "JUDGMENT",
        "reviewer": "Investor",
        "rationale": "Synthetic post-mortem; missing evidence remains unresolved.",
        "confidence": "LOW",
        "evidence_references": [],
        "links": {},
        "approved_labels": [],
        "primary_mistake": None,
        "unresolved_questions": [
            "Was the recorded evidence adequate at the decision date?"
        ],
        **changes,
    }


def candidates(suggestion: dict[str, Any]) -> set[str]:
    return {item["code"] for item in suggestion["candidate_labels"]}


def test_taxonomy_small_fixed_eight_groups() -> None:
    assert len(TAXONOMY_GROUPS) == 8
    assert len(TAXONOMY) == sum(map(len, TAXONOMY_GROUPS.values()))
    assert TAXONOMY["FOMO"] == "BEHAVIORAL"
    assert TAXONOMY["NO_IDENTIFIED_MISTAKE"] == "NO_MISTAKE_EXTERNAL"


def test_immutable_multiple_reviews_and_exact_version_isolation(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store)
    original_underwritings = store.list_underwriting("ADBE")
    original_outcomes = store.list_outcome_observations()
    links = {"observation_ids": [outcome["observation_id"]]}
    first = create_review(store, selected, review_input(links=links), now=NOW)
    new = persist(store, "ADBE", snapshot(price=50))
    second = create_review(
        store, selected, review_input(links=links), now=NOW + timedelta(days=1)
    )
    assert first["review_id"] != second["review_id"]
    assert first["underwriting"] == second["underwriting"]
    assert first["underwriting"]["version"] != new.version
    assert read_review(store, first["review_id"]) == first
    assert len(review_history(store, "ADBE")) == 2
    assert store.list_underwriting("ADBE")[:1] == original_underwritings
    assert store.list_outcome_observations() == original_outcomes


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE mistake_reviews SET recorded_at='2099-01-01'",
        "DELETE FROM mistake_reviews",
        "INSERT OR REPLACE INTO mistake_reviews SELECT * FROM mistake_reviews",
    ],
)
def test_database_immutable_guards(store: SqliteStore, operation: str) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_review(store, selected, review_input(), now=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(operation)
    store._conn.rollback()


def test_candidates_never_approved_implicitly(store: SqliteStore) -> None:
    selected, outcome = completed(store, metric_value=0.05)
    suggestion = suggest_review(store, selected, now=NOW)
    assert "GROWTH_TOO_HIGH" in candidates(suggestion)
    assert all(not item["investor_approved"] for item in suggestion["candidate_labels"])
    assert store.list_mistake_reviews() == ()
    report = create_review(
        store,
        selected,
        review_input(
            links={"observation_ids": [outcome["observation_id"]]},
        ),
        now=NOW,
    )
    assert report["candidate_labels"]
    assert not report["approved_labels"]
    assert review_summary(store)["approved_review_count"] == 0


def test_multiple_explicit_labels_optional_primary_and_provenance(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store, metric_value=0.05)
    data = review_input(
        links={"observation_ids": [outcome["observation_id"]]},
        approved_labels=[label("GROWTH_TOO_HIGH"), label("CONFIRMATION_BIAS")],
    )
    report = create_review(store, selected, data, now=NOW)
    assert report["primary_mistake"] is None
    assert set(report["secondary_mistakes"]) == {"GROWTH_TOO_HIGH", "CONFIRMATION_BIAS"}
    labels = {item["code"]: item for item in report["approved_labels"]}
    assert labels["GROWTH_TOO_HIGH"]["machine_suggested"]
    assert not labels["CONFIRMATION_BIAS"]["machine_suggested"]
    assert all(item["investor_approved"] for item in labels.values())
    data["primary_mistake"] = "GROWTH_TOO_HIGH"
    second = create_review(store, selected, data, now=NOW)
    assert second["secondary_mistakes"] == ["CONFIRMATION_BIAS"]
    assert second["quality"]["decision_quality"] == "NOT_ASSESSED_HERE"
    assert (
        second["context"]["outcomes"][0]["report"]["observation"]["category"] == "FACT"
    )
    assert (
        second["context"]["outcomes"][0]["report"]["market_outcome"]["category"]
        == "CALCULATION"
    )


@pytest.mark.parametrize("code", TAXONOMY_GROUPS["BEHAVIORAL"])
def test_behavioral_labels_only_explicit_investor_authority(
    store: SqliteStore, code: str
) -> None:
    selected, _ = completed(store)
    assert not set(TAXONOMY_GROUPS["BEHAVIORAL"]) & candidates(
        suggest_review(store, selected, now=NOW)
    )
    with pytest.raises(MistakeError, match="explicit"):
        create_review(
            store,
            selected,
            review_input(
                approved_labels=[label(code, investor_approved=False)],
            ),
            now=NOW,
        )
    report = create_review(
        store, selected, review_input(approved_labels=[label(code)]), now=NOW
    )
    assert not report["approved_labels"][0]["machine_suggested"]


def test_adverse_outcome_never_forces_a_mistake(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input(
        market={"price": 5, "currency": "USD", "basis": "EOD_CLOSE_SAME_SHARE_BASIS"},
        fundamentals=[],
    )
    outcome = create_observation(store, selected, data, now=NOW)
    report = create_review(
        store,
        selected,
        review_input(
            links={"observation_ids": [outcome["observation_id"]]},
            approved_labels=[label("NO_IDENTIFIED_MISTAKE")],
        ),
        now=NOW,
    )
    assert report["quality"]["outcome_quality"] == "ADVERSE"
    assert report["quality"]["forecast_quality"] == "UNRESOLVED"
    assert report["approved_labels"][0]["code"] == "NO_IDENTIFIED_MISTAKE"
    assert not report["candidate_labels"]


def test_favorable_outcome_with_weak_process_remains_separate(
    store: SqliteStore,
) -> None:
    original = snapshot()
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(original.manual, disconfirming_evidence=()),
        ),
    )
    outcome = create_observation(store, selected, outcome_input(), now=NOW)
    report = create_review(
        store,
        selected,
        review_input(
            links={"observation_ids": [outcome["observation_id"]]},
            approved_labels=[label("FAVORABLE_OUTCOME_WITH_WEAK_PROCESS")],
        ),
        now=NOW,
    )
    assert report["quality"]["outcome_quality"] == "FAVORABLE"
    assert report["quality"]["process_quality"] == "EXCEPTIONS"
    assert report["quality"]["decision_quality"] == "NOT_ASSESSED_HERE"


@pytest.mark.parametrize(
    "code",
    [
        "GROWTH_TOO_HIGH",
        "MARGIN_TOO_HIGH",
        "TERMINAL_MULTIPLE_TOO_HIGH",
        "SCENARIO_RANGE_TOO_NARROW",
        "PROBABILITY_TOO_OPTIMISTIC",
    ],
)
def test_interim_cannot_support_forecast_labels(store: SqliteStore, code: str) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = outcome_input(
        observation_date="2026-09-02",
        observed_at="2026-09-03T11:00:00+00:00",
        horizon="CUSTOM",
        horizon_note="Interim synthetic observation.",
        fundamentals=[],
    )
    data["references"] = [
        {"title": "Synthetic interim source", "observed_at": "2026-09-03"}
    ]
    outcome = create_observation(
        store, selected, data, now=datetime(2026, 9, 3, 12, tzinfo=UTC)
    )
    links = {"observation_ids": [outcome["observation_id"]]}
    suggestion = suggest_review(store, selected, links=links, now=NOW)
    assert suggestion["evidence_state"] == "INTERIM_ONLY"
    assert not suggestion["candidate_labels"]
    with pytest.raises(MistakeError, match="comparable"):
        create_review(
            store,
            selected,
            review_input(links=links, approved_labels=[label(code)]),
            now=NOW,
        )


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.05, "GROWTH_TOO_HIGH"),
        (0.15, "GROWTH_TOO_LOW"),
        (0.1, None),
        (0.095, None),
        (0.09, None),
        (0.11, None),
    ],
)
def test_forecast_error_materiality_and_direction(
    store: SqliteStore, value: float, expected: str | None
) -> None:
    selected, _ = completed(store, metric_value=value)
    suggestion = suggest_review(store, selected, now=NOW)
    assert candidates(suggestion) == ({expected} if expected else set())
    assert suggestion["quality"]["forecast_quality"] == (
        "MISSED" if expected else "SUPPORTED"
    )


@pytest.mark.parametrize(
    "metric,value,code",
    [
        ("fcf_margin_year5", 0.15, "MARGIN_TOO_HIGH"),
        ("fcf_margin_year5", 0.25, "MARGIN_TOO_LOW"),
        ("share_count_cagr", 0, "SHARE_COUNT_ASSUMPTION_WRONG"),
        ("terminal_fcf_multiple", 10, "TERMINAL_MULTIPLE_TOO_HIGH"),
        ("terminal_fcf_multiple", 40, "TERMINAL_MULTIPLE_TOO_LOW"),
    ],
)
def test_other_comparable_metric_candidates(
    store: SqliteStore, metric: str, value: float, code: str
) -> None:
    selected = persist(store, "ADBE", snapshot())
    from owner_lens.outcomes import SCENARIO_METRICS

    unit, basis = SCENARIO_METRICS[metric]
    outcome = outcome_input(
        fundamentals=[
            fundamental(
                forecast={"kind": "SCENARIO", "id": metric},
                observable=metric,
                value=value,
                unit=unit,
                basis=basis,
            )
        ]
    )
    create_observation(store, selected, outcome, now=NOW)
    assert code in candidates(suggest_review(store, selected, now=NOW))


def test_incompatible_definitions_no_fuzzy_matching(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    observation = create_observation(
        store,
        selected,
        outcome_input(
            market=None,
            fundamentals=[fundamental(observable="Revenue CAGR", unit="percent")],
        ),
        now=NOW,
    )
    suggestion = suggest_review(store, selected, now=NOW)
    assert suggestion["evidence_state"] == "NOT_COMPARABLE"
    assert not suggestion["candidate_labels"]
    with pytest.raises(MistakeError, match="comparable"):
        create_review(
            store,
            selected,
            review_input(
                links={"observation_ids": [observation["observation_id"]]},
                approved_labels=[label("GROWTH_TOO_HIGH")],
            ),
            now=NOW,
        )


def test_approved_changes_not_pending_require_reunderwriting(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    assert "FAILED_TO_REUNDERWRITE" not in candidates(
        suggest_review(store, selected, now=NOW)
    )
    approve_event(
        store,
        event["event_id"],
        "THESIS_UPDATE",
        "Synthetic explicit approval.",
        now=EARLY,
    )
    assert "FAILED_TO_REUNDERWRITE" in candidates(
        suggest_review(store, selected, now=NOW)
    )
    later_noise = create_event(
        store, selected, event_input(), now=EARLY + timedelta(days=1)
    )
    approve_event(
        store,
        later_noise["event_id"],
        "NOISE",
        "Independent noise.",
        now=EARLY + timedelta(days=1),
    )
    assert "FAILED_TO_REUNDERWRITE" in candidates(
        suggest_review(store, selected, now=NOW)
    )
    persist(store, "ADBE", snapshot())  # Earlier than approval: not a response.
    assert "FAILED_TO_REUNDERWRITE" in candidates(
        suggest_review(store, selected, now=NOW)
    )


def test_later_completed_underwriting_satisfies_change_check(
    store: SqliteStore,
) -> None:
    from owner_lens.valuation import run_valuation

    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    approve_event(
        store, event["event_id"], "THESIS_BREAK", "Review required.", now=EARLY
    )
    original = store.list_underwriting("ADBE")[0]
    newer = store.save_underwriting(
        security_id=original.security_id,
        ticker="ADBE",
        snapshot_json=monitored_snapshot().to_json(),
        as_of_date="2026-06-02",
        created_at=(EARLY + timedelta(days=1)).isoformat(),
    )
    run_valuation(store, newer)
    suggestion = suggest_review(store, selected, now=NOW)
    assert "FAILED_TO_REUNDERWRITE" not in candidates(suggestion)
    assert (
        next(
            item
            for item in suggestion["process_checks"]
            if item["code"] == "REUNDERWRITING_PERFORMED"
        )["status"]
        == "SATISFIED"
    )


def test_sizing_candidates_use_proposal_and_explicit_policy_only(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    sizing = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(),
        proposed_increment=0.5,
        now=EARLY,
    )
    stored = store.save_sizing_analysis(
        canonical_json(sizing), created_at=EARLY.isoformat()
    )
    suggestion = suggest_review(
        store, selected, links={"sizing_analysis_id": stored.analysis_id}, now=NOW
    )
    assert {
        "POSITION_TOO_LARGE",
        "DOWNSIDE_BUDGET_IGNORED",
        "CASH_OPTIONALITY_IGNORED",
    } <= candidates(suggestion)
    assert "POSITION_TOO_SMALL" not in candidates(suggestion)
    report = create_review(
        store,
        selected,
        review_input(
            links={"sizing_analysis_id": stored.analysis_id},
            approved_labels=[label("POSITION_TOO_LARGE")],
        ),
        now=NOW,
    )
    assert report["context"]["sizing"]["analysis_id"] == stored.analysis_id
    assert (
        "not executed"
        in next(
            item
            for item in report["process_checks"]
            if item["code"] == "SIZING_WITHIN_POLICY"
        )["detail"]
    )


@pytest.mark.parametrize("code", TAXONOMY_GROUPS["PORTFOLIO_SIZING"])
def test_sizing_label_without_9c_context_rejected(
    store: SqliteStore, code: str
) -> None:
    selected, _ = completed(store)
    with pytest.raises(MistakeError, match="Feature 9C"):
        create_review(
            store, selected, review_input(approved_labels=[label(code)]), now=NOW
        )


def test_exact_decision_linkage_and_records_unchanged(store: SqliteStore) -> None:
    selected, outcome = completed(store)
    decision = create_decision(store, selected, input_data(), now=EARLY)
    before = (
        store.list_decisions(),
        store.list_outcome_observations(),
        store.list_change_events(),
    )
    report = create_review(
        store,
        selected,
        review_input(
            links={
                "decision_id": decision.decision_id,
                "observation_ids": [outcome["observation_id"]],
            },
        ),
        now=NOW,
    )
    assert report["context"]["decision"]["decision_id"] == decision.decision_id
    assert before == (
        store.list_decisions(),
        store.list_outcome_observations(),
        store.list_change_events(),
    )
    other = persist(store, "ADBE", snapshot())
    with pytest.raises(MistakeError, match="exact"):
        create_review(
            store,
            other,
            review_input(links={"decision_id": decision.decision_id}),
            now=NOW,
        )
    with pytest.raises(MistakeError, match="exact"):
        create_review(
            store,
            other,
            review_input(links={"observation_ids": [outcome["observation_id"]]}),
            now=NOW,
        )


def test_calibration_linkage_and_small_sample_blocks_probability_conclusions(
    store: SqliteStore,
) -> None:
    selected, _ = completed(store)
    calibration = run_calibration(store, as_of=NOW.date().isoformat())
    links = {"calibration_report_id": calibration["report_id"]}
    report = create_review(store, selected, review_input(links=links), now=NOW)
    assert report["context"]["calibration"] == calibration
    with pytest.raises(MistakeError, match="calibration"):
        create_review(
            store,
            selected,
            review_input(
                links=links, approved_labels=[label("PROBABILITY_TOO_OPTIMISTIC")]
            ),
            now=NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"category": "FACT"},
        {"review_date": "2099-01-01"},
        {"primary_mistake": "FOMO"},
        {"primary_mistake": ["FOMO"]},
        {"approved_labels": [label("FOMO", investor_approved=1)]},
        {"approved_labels": [label("UNKNOWN")]},
        {"approved_labels": [label("FOMO", evidence_references=[])]},
        {"approved_labels": [label("FOMO"), label("FOMO")]},
        {"approved_labels": [label("FOMO"), label("NO_IDENTIFIED_MISTAKE")]},
        {
            "evidence_references": [
                {"title": "Future evidence", "observed_at": "2099-01-01"}
            ]
        },
    ],
)
def test_invalid_authority_and_lookahead_rejected(
    store: SqliteStore, mutation: dict[str, Any]
) -> None:
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(ValueError):
        create_review(store, selected, review_input(**mutation), now=NOW)
    assert store.list_mistake_reviews() == ()


def test_old_review_not_changed_by_new_evidence_or_approvals(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    clock = EARLY + timedelta(days=1)
    report = create_review(
        store,
        selected,
        review_input(
            review_date=clock.date().isoformat(),
            links={"change_event_ids": [event["event_id"]]},
        ),
        now=clock,
    )
    payload = store.get_mistake_review(report["review_id"])
    approve_event(
        store,
        event["event_id"],
        "THESIS_UPDATE",
        "Later approval.",
        now=clock + timedelta(days=1),
    )
    assert store.get_mistake_review(report["review_id"]) == payload
    assert not read_review(store, report["review_id"])["candidate_labels"]
    historical = suggest_review(
        store, selected, review_date=clock.date().isoformat(), now=NOW
    )
    assert historical["context"]["changes"][0]["approval"] is None


def test_deterministic_preview_json_and_tamper_rejected(store: SqliteStore) -> None:
    selected, _ = completed(store)
    assert canonical_json(suggest_review(store, selected, now=NOW)) == canonical_json(
        suggest_review(store, selected, now=NOW)
    )
    data = review_input()
    report = build_review(
        store,
        selected,
        data,
        review_id="10000000-0000-0000-0000-000000000001",
        recorded_at=NOW.isoformat(),
    )
    changed = deepcopy(report)
    changed["candidate_labels"] = [label("FOMO")]
    with pytest.raises(StorageWriteError, match="differs"):
        store.save_mistake_review(canonical_json(changed))
    store.save_mistake_review(canonical_json(report))
    assert canonical_json(read_review(store, report["review_id"])) == canonical_json(
        report
    )
    with pytest.raises(StorageWriteError, match="immutable"):
        store.save_mistake_review(canonical_json(report))
    with pytest.raises(StorageReadError):
        read_review(store, "missing")


def test_summary_approved_only_multiple_labels_and_sample_warning(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_review(store, selected, review_input(), now=NOW)
    for _ in range(5):
        create_review(
            store,
            selected,
            review_input(
                approved_labels=[label("FOMO"), label("ANCHORING")],
            ),
            now=NOW,
        )
    summary = review_summary(store)
    assert summary["review_count"] == 6 and summary["approved_review_count"] == 5
    assert summary["categories"] == {"BEHAVIORAL": 5}
    assert summary["approved_labels"] == {"ANCHORING": 5, "FOMO": 5}
    assert summary["sample_warning"] == "DESCRIPTIVE_ONLY"
    assert "not independent" in summary["disclaimer"]


def test_missing_outcomes_explicit_insufficient_state_and_no_mistake(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    report = create_review(store, selected, review_input(), now=NOW)
    assert report["evidence_state"] == "INSUFFICIENT_EVIDENCE"
    assert report["quality"]["outcome_quality"] == "UNRESOLVED"
    assert report["quality"]["forecast_quality"] == "UNRESOLVED"
    assert not report["approved_labels"] and not report["candidate_labels"]
    assert review_summary(store)["sample_warning"] == "INSUFFICIENT_REVIEW_HISTORY"


def test_future_records_unavailable_even_when_linked_explicitly(
    store: SqliteStore,
) -> None:
    selected, outcome = completed(store)
    with pytest.raises(MistakeError, match="unavailable"):
        suggest_review(
            store,
            selected,
            links={"observation_ids": [outcome["observation_id"]]},
            review_date="2026-06-03",
            now=NOW,
        )
    suggestion = suggest_review(store, selected, review_date="2026-06-03", now=NOW)
    assert not suggestion["context"]["outcomes"]
    with pytest.raises(MistakeError, match="unavailable"):
        suggest_review(store, selected, review_date="2025-01-01", now=NOW)


def test_no_latest_substitution_missing_version_fails(store: SqliteStore) -> None:
    persist(store, "ADBE", snapshot())
    with pytest.raises(ValueError, match="not found"):
        suggest_review(store, UnderwritingSelection("ADBE", 99), now=NOW)


def test_same_day_approved_change_is_question_not_failed_action_candidate(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    approve_event(store, event["event_id"], "THESIS_UPDATE", "Needs work.", now=EARLY)
    report = suggest_review(store, selected, now=EARLY)
    assert "FAILED_TO_REUNDERWRITE" not in candidates(report)
    assert (
        next(
            item
            for item in report["process_checks"]
            if item["code"] == "REUNDERWRITING_PERFORMED"
        )["status"]
        == "EXCEPTION"
    )


def test_range_candidate_only_outside_completed_fundamental_span(
    store: SqliteStore,
) -> None:
    selected, _ = completed(store, metric_value=0.25)
    report = suggest_review(store, selected, now=NOW)
    assert {"GROWTH_TOO_LOW", "SCENARIO_RANGE_TOO_NARROW"} <= candidates(report)
    selected2, _ = completed(store, metric_value=0.21)
    assert "SCENARIO_RANGE_TOO_NARROW" not in candidates(
        suggest_review(store, selected2, now=NOW)
    )


def test_naive_recording_clock_rejected(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(MistakeError, match="timezone"):
        create_review(store, selected, review_input(), now=NOW.replace(tzinfo=None))


def test_missing_selected_records_fail_explicitly(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    for key in ("decision_id", "sizing_analysis_id", "calibration_report_id"):
        with pytest.raises((ValueError, StorageReadError)):
            suggest_review(store, selected, links={key: "missing"}, now=NOW)


def test_sizing_must_match_selected_decision(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(store, selected, input_data(), now=EARLY)
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    report = size_position(store, selected, portfolio.snapshot_id, policy(), now=EARLY)
    sizing = store.save_sizing_analysis(
        canonical_json(report), created_at=EARLY.isoformat()
    )
    with pytest.raises(MistakeError, match="selected decision"):
        suggest_review(
            store,
            selected,
            links={
                "decision_id": decision.decision_id,
                "sizing_analysis_id": sizing.analysis_id,
            },
            now=NOW,
        )


def test_valid_sizing_context_does_not_create_false_mistake_candidates(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    report = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(),
        proposed_increment=0.01,
        now=EARLY,
    )
    sizing = store.save_sizing_analysis(
        canonical_json(report), created_at=EARLY.isoformat()
    )
    suggestion = suggest_review(
        store, selected, links={"sizing_analysis_id": sizing.analysis_id}, now=NOW
    )
    assert not candidates(suggestion)


def test_hurdle_check_uses_frozen_judgment_not_outcome(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot(price=1000))
    decision = create_decision(
        store, selected, {**input_data(), "action": "BUY"}, now=EARLY
    )
    report = suggest_review(
        store, selected, links={"decision_id": decision.decision_id}, now=NOW
    )
    check = next(
        item
        for item in report["process_checks"]
        if item["code"] == "HURDLE_CONSISTENCY"
    )
    assert check["status"] == "EXCEPTION"
    assert report["quality"]["outcome_quality"] == "UNRESOLVED"
    assert report["quality"]["decision_quality"] == "NOT_ASSESSED_HERE"


def test_probability_label_requires_twenty_unambiguous_linked_samples(
    store: SqliteStore,
) -> None:
    selected = None
    for _ in range(20):
        selected, _ = completed(store)
    assert selected is not None
    calibration = run_calibration(store, as_of=NOW.date().isoformat())
    report = create_review(
        store,
        selected,
        review_input(
            links={"calibration_report_id": calibration["report_id"]},
            approved_labels=[label("PROBABILITY_TOO_OPTIMISTIC")],
        ),
        now=NOW,
    )
    assert report["approved_labels"][0]["investor_approved"]
    assert not report["approved_labels"][0]["machine_suggested"]


def test_history_reads_never_recompute(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = persist(store, "ADBE", snapshot())
    review = create_review(store, selected, review_input(), now=NOW)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Historical reviews must not rerun suggestions.")

    monkeypatch.setattr("owner_lens.mistakes.suggest_review", forbidden)
    assert read_review(store, review["review_id"]) == review
    assert review_history(store, "ADBE") == [review]


def test_schema11_additive_migration_keeps_immutable_sources(
    store: SqliteStore,
) -> None:
    selected, _ = completed(store)
    calibration = run_calibration(store, as_of=NOW.date().isoformat())
    before = (store.list_underwriting("ADBE"), store.list_outcome_observations())
    store._conn.executescript(
        "DROP TABLE mistake_reviews; UPDATE schema_meta SET value='11' WHERE key='schema_version';"
    )
    store.initialize()
    assert before == (
        store.list_underwriting("ADBE"),
        store.list_outcome_observations(),
    )
    assert (
        json.loads(store.get_calibration_report(calibration["report_id"]))
        == calibration
    )
    assert (
        create_review(store, selected, review_input(), now=NOW)["approved_labels"] == []
    )


def test_sizing_change_and_calibration_linkage_reject_different_versions(
    store: SqliteStore,
) -> None:
    original = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, original, event_input(), now=EARLY)
    portfolio = create_portfolio(store, portfolio_input(), now=EARLY)
    analysis = store.save_sizing_analysis(
        canonical_json(
            size_position(
                store,
                original,
                portfolio.snapshot_id,
                policy(),
                now=EARLY,
            )
        ),
        created_at=EARLY.isoformat(),
    )
    calibration = run_calibration(store, as_of=NOW.date().isoformat())
    other = persist(store, "ADBE", snapshot())
    for links in (
        {"change_event_ids": [event["event_id"]]},
        {"sizing_analysis_id": analysis.analysis_id},
        {"calibration_report_id": calibration["report_id"]},
    ):
        with pytest.raises(MistakeError, match="exact"):
            suggest_review(store, other, links=links, now=NOW)


def test_transaction_rejects_reentrant_save(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    review = build_review(
        store,
        selected,
        review_input(),
        review_id="10000000-0000-0000-0000-000000000001",
        recorded_at=NOW.isoformat(),
    )
    with store.transaction(), pytest.raises(StorageWriteError, match="own transaction"):
        store.save_mistake_review(canonical_json(review))


def test_incomplete_followup_not_substituted_for_completed_reunderwriting(
    store: SqliteStore,
) -> None:
    from owner_lens.valuation import run_valuation

    selected = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, selected, event_input(), now=EARLY)
    approve_event(store, event["event_id"], "THESIS_UPDATE", "Needs work.", now=EARLY)
    original = monitored_snapshot()
    incomplete = replace(
        original, manual=replace(original.manual, probability_distribution=None)
    )
    newer = store.save_underwriting(
        security_id=store.list_underwriting("ADBE")[0].security_id,
        ticker="ADBE",
        snapshot_json=incomplete.to_json(),
        as_of_date="2026-06-02",
        created_at=(EARLY + timedelta(days=1)).isoformat(),
    )
    run_valuation(store, newer)
    report = suggest_review(store, selected, now=NOW)
    assert "FAILED_TO_REUNDERWRITE" in candidates(report)
    assert report["context"]["excluded_followup_underwritings"][0]["reason"]


def test_manual_template_records_unresolved_without_invented_outcomes(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = json.loads(
        (ROOT / "docs" / "examples" / "adbe_mistake_review.sample.json").read_text()
    )
    review = create_review(store, selected, data, now=NOW)
    assert review["approved_labels"][0]["code"] == "UNRESOLVED"
    assert review["evidence_state"] == "INSUFFICIENT_EVIDENCE"
    assert not review["context"]["outcomes"] and not review["candidate_labels"]


def test_missing_market_observation_does_not_turn_neutral_or_favorable(
    store: SqliteStore,
) -> None:
    selected, first = completed(store)
    second = create_observation(store, selected, outcome_input(market=None), now=NOW)
    report = suggest_review(
        store,
        selected,
        links={
            "observation_ids": [first["observation_id"], second["observation_id"]],
        },
        now=NOW,
    )
    assert report["quality"]["outcome_quality"] == "UNRESOLVED"


def test_same_day_calibration_cannot_smuggle_later_recorded_evidence(
    store: SqliteStore,
) -> None:
    selected, _ = completed(store, now=NOW + timedelta(hours=1))
    calibration = run_calibration(store, as_of=NOW.date().isoformat())
    with pytest.raises(MistakeError, match="cutoff"):
        suggest_review(
            store,
            selected,
            links={"calibration_report_id": calibration["report_id"]},
            now=NOW,
        )


def test_workbench_labels_require_selection_and_explicit_matching_approval(
    store: SqliteStore,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Mistake Review"
    app.session_state["mistakes_version"] = "ADBE:1"
    app.run()
    assert app.multiselect(key="mistakes_codes").value == []
    app.multiselect(key="mistakes_codes").set_value(["FOMO"])
    app.text_input(key="mistakes_reviewer").set_value("Fixture investor")
    app.text_area(key="mistakes_rationale").set_value(
        "Explicit reflection, no automatic diagnosis."
    )
    app.checkbox(key="mistakes_approve").check()
    button = "FormSubmitter:mistakes_create-Append investor-approved review"
    app.text_area(key="mistakes_label_json").set_value('[{"code": []}]')
    app.button(key=button).click().run()
    assert not app.exception
    assert app.error and not store.list_mistake_reviews()
    app.text_area(key="mistakes_label_json").set_value(canonical_json([label("FOMO")]))
    app.button(key=button).click().run()
    assert not app.exception and not app.error
    review = json.loads(store.list_mistake_reviews()[0])
    assert review["approved_labels"][0]["code"] == "FOMO"
    assert review["approved_labels"][0]["investor_approved"]
    assert not review["approved_labels"][0]["machine_suggested"]


def test_cli_create_suggest_show_history_summary_and_failure(
    store: SqliteStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from owner_lens.workbench.data import WorkbenchSource

    @contextmanager
    def source():
        yield WorkbenchSource(store, None, "", "")

    monkeypatch.setattr("owner_lens.workbench.data.open_source", source)
    persist(store, "ADBE", snapshot())
    path = tmp_path / "review.json"
    path.write_text(
        canonical_json(review_input(review_date="2026-06-03")), encoding="utf-8"
    )
    assert (
        main(["mistakes", "review", "suggest", "ADBE", "--version", "1", "--json"]) == 0
    )
    assert "candidate_labels" in json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "mistakes",
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
    for action, arg in [("show", report["review_id"]), ("history", "ADBE")]:
        assert main(["mistakes", "review", action, arg, "--json"]) == 0
        json.loads(capsys.readouterr().out)
    assert main(["mistakes", "summary", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["review_count"] == 1
    assert main(["mistakes", "review", "show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err


def test_workbench_readonly_and_explicit_review_approval(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Mistake Review"
    app.session_state["mistakes_version"] = "ADBE:1"
    app.run()
    assert not app.exception and not app.error
    assert not store.list_mistake_reviews()
    app.text_input(key="mistakes_reviewer").set_value("Fixture investor")
    app.text_area(key="mistakes_rationale").set_value("Review evidence limitations.")
    app.button(
        key="FormSubmitter:mistakes_create-Append investor-approved review"
    ).click().run()
    assert not store.list_mistake_reviews()
    assert any("Explicit investor approval" in item.value for item in app.error)
    app.checkbox(key="mistakes_approve").check()
    app.button(
        key="FormSubmitter:mistakes_create-Append investor-approved review"
    ).click().run()
    assert not app.exception and not app.error
    assert len(store.list_mistake_reviews()) == 1
    assert not json.loads(store.list_mistake_reviews()[0])["approved_labels"]

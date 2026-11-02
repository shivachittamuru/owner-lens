"""Fixture-only change matching, explicit approval, chronology and immutable histories."""

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
from test_position_sizing import policy, portfolio_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.changes import (
    ChangeError,
    approve_event,
    assess_event,
    change_history,
    create_event,
    current_change_state,
    format_assessment,
    format_current_state,
    trigger,
)
from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import canonical_json, create_portfolio, size_position
from owner_lens.underwriting import (
    Reference,
    ThesisCondition,
    UnderwritingError,
    UnderwritingSnapshot,
    _conditions,
)
from owner_lens.underwriting_authoring import authoring_from_manual
from owner_lens.valuation import run_valuation

NOW = datetime(2026, 6, 3, 12, tzinfo=UTC)
ROOT = Path(__file__).parents[1]
APP = ROOT / "src" / "owner_lens" / "workbench" / "app.py"


def monitored_snapshot() -> UnderwritingSnapshot:
    original = snapshot()
    dependency = ThesisCondition(
        "arr-growth",
        "ARR growth remains at least 7%.",
        "ARR growth YoY, constant currency",
        ">= 7%",
        (Reference(title="Fixture company report"),),
        "Quarterly",
    )
    breaker = ThesisCondition(
        "arr-collapse",
        "Sustained monetization thesis fails at negative ARR growth.",
        "ARR growth YoY, constant currency",
        "< 0%",
        (Reference(title="Fixture company report"),),
        "Quarterly",
    )
    return replace(
        original,
        manual=replace(
            original.manual,
            thesis=replace(
                original.manual.thesis,
                dependencies=(dependency.statement,),
                breakers=(breaker.statement,),
                monitoring_dependencies=(dependency,),
                monitoring_breakers=(breaker,),
            ),
        ),
    )


def event_input(value: float = 5.8, **changes: Any) -> dict[str, Any]:
    return {
        "event_date": "2026-06-03",
        "observed_at": "2026-06-03T11:00:00+00:00",
        "observation": {
            "category": "FACT",
            "statement": f"Synthetic reported ARR growth is {value}%.",
            "references": [
                {
                    "title": "Fixture company report",
                    "uri": "fixture://arr",
                    "observed_at": "2026-06-03T10:00:00+00:00",
                }
            ],
            "verification_note": "Investor checked the synthetic fixture; no real-company assertion.",
            "metric": {
                "observable": "ARR growth YoY, constant currency",
                "value": value,
                "unit": "%",
                "cadence": "Quarterly",
            },
        },
        "interpretation": {
            "category": "JUDGMENT",
            "text": "Revisit growth persistence, not an instruction to trade.",
        },
        "condition_id": "arr-growth",
        "affected_beliefs": [
            "/manual/scenarios/1/revenue_cagr",
            "/manual/probability_distribution/scenarios/1/probability",
            "/manual/thesis/monitoring_dependencies/0",
        ],
        **changes,
    }


def record_event(
    store: SqliteStore, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    selected = persist(store, "ADBE", monitored_snapshot())
    return create_event(
        store, selected, event_input() if data is None else data, now=NOW
    )


@pytest.mark.parametrize(
    "value,status,candidate",
    [
        (7, "CONDITION_MET", "EVIDENCE"),
        (8.2, "CONDITION_MET", "EVIDENCE"),
        (5.8, "CONDITION_BREACHED", "THESIS_UPDATE"),
    ],
)
def test_dependency_condition_and_candidate(
    store: SqliteStore, value: float, status: str, candidate: str
) -> None:
    event = record_event(store, event_input(value))
    assert event["assessment"]["result"] == status
    assert event["assessment"]["candidate_classification"] == candidate
    assert event["assessment"]["condition"]["condition_id"] == "arr-growth"
    assert event["event"]["observation"]["category"] == "FACT"
    assert event["event"]["interpretation"]["category"] == "JUDGMENT"
    assessment = assess_event(store, event["event_id"])
    assert assessment["approved_classification"] is None
    assert assessment["reunderwriting_trigger"] is None
    assert assessment["history_status"] == "PENDING_APPROVAL"
    assert len(store.list_underwriting("ADBE")) == 1


@pytest.mark.parametrize(
    "value,status,candidate",
    [
        (-1, "CONDITION_BREACHED", "THESIS_BREAK"),
        (0, "CONDITION_MET", "EVIDENCE"),
        (5.8, "CONDITION_MET", "EVIDENCE"),
    ],
)
def test_breaker_predicate_true_is_thesis_breach(
    store: SqliteStore, value: float, status: str, candidate: str
) -> None:
    event = record_event(store, event_input(value, condition_id="arr-collapse"))
    assert event["assessment"]["condition_kind"] == "BREAKER"
    assert event["assessment"]["result"] == status
    assert event["assessment"]["candidate_classification"] == candidate


@pytest.mark.parametrize(
    "field,value",
    [
        ("observable", "Revenue CAGR"),
        ("observable", "arr growth YoY, constant currency"),
        ("unit", "ratio"),
        ("unit", "percent"),
        ("cadence", "Annual"),
    ],
)
def test_incompatible_definitions_units_cadence_not_comparable(
    store: SqliteStore, field: str, value: str
) -> None:
    data = event_input()
    data["observation"]["metric"][field] = value
    event = record_event(store, data)
    assert event["assessment"]["result"] == "NOT_COMPARABLE"
    assert event["assessment"]["candidate_classification"] is None


@pytest.mark.parametrize("field", ["observable", "value", "unit", "cadence"])
def test_incomplete_metric_is_not_neutral(store: SqliteStore, field: str) -> None:
    data = event_input()
    data["observation"]["metric"][field] = None
    event = record_event(store, data)
    assert event["assessment"]["result"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize(
    "threshold",
    [
        "Two consecutive annual declines",
        ">= 7",
        "generally >= 7%",
        ">= 7% and retention stable",
    ],
)
def test_qualitative_or_ambiguous_threshold_not_parsed(
    store: SqliteStore, threshold: str
) -> None:
    original = monitored_snapshot()
    dependency = replace(
        original.manual.thesis.monitoring_dependencies[0], threshold=threshold
    )
    modified = replace(
        original,
        manual=replace(
            original.manual,
            thesis=replace(
                original.manual.thesis,
                monitoring_dependencies=(dependency,),
            ),
        ),
    )
    selected = persist(store, "ADBE", modified)
    event = create_event(store, selected, event_input(), now=NOW)
    assert event["assessment"]["result"] == "NOT_COMPARABLE"


def test_source_mismatch_and_unverified_observation(store: SqliteStore) -> None:
    data = event_input()
    data["observation"]["references"][0]["title"] = "Different source"
    event = record_event(store, data)
    assert event["assessment"]["result"] == "NOT_COMPARABLE"
    data["observation"]["category"] = "EXPECTATION"
    selected = UnderwritingSelection("ADBE", 1)
    event2 = create_event(store, selected, data, now=NOW)
    assert event2["assessment"]["result"] == "INSUFFICIENT_DATA"
    assert event2["event"]["observation"]["category"] == "EXPECTATION"


def test_no_metric_no_link_and_legacy_missing_structure_explicit(
    store: SqliteStore,
) -> None:
    data = event_input(condition_id=None)
    data["observation"]["metric"] = None
    event = record_event(store, data)
    assert event["assessment"]["result"] == "INSUFFICIENT_DATA"
    assert event["assessment"]["condition"] is None
    selected = persist(store, "ADBE", snapshot())
    with pytest.raises(ChangeError, match="Condition ID"):
        create_event(store, selected, event_input(), now=NOW)
    data["affected_beliefs"] = []
    legacy = create_event(store, selected, data, now=NOW)
    assert legacy["affected_beliefs"] == []
    assert "NONE LINKED" in format_assessment(assess_event(store, legacy["event_id"]))


def test_monitoring_date_and_optional_source_cadence_missingness(
    store: SqliteStore,
) -> None:
    original = monitored_snapshot()
    dependency = replace(
        original.manual.thesis.monitoring_dependencies[0], monitoring_date="2026-07-01"
    )
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(
                original.manual,
                thesis=replace(
                    original.manual.thesis,
                    monitoring_dependencies=(dependency,),
                ),
            ),
        ),
    )
    event = create_event(store, selected, event_input(), now=NOW)
    assert event["assessment"]["result"] == "INSUFFICIENT_DATA"
    assert "not reached" in event["assessment"]["reason"]


@pytest.mark.parametrize(
    "classification,expected",
    [
        ("NOISE", "NO_REUNDERWRITING_REQUIRED"),
        ("EVIDENCE", "REVIEW_RECOMMENDED"),
        ("THESIS_UPDATE", "NEW_UNDERWRITING_REQUIRED"),
        ("THESIS_BREAK", "NEW_UNDERWRITING_REQUIRED"),
    ],
)
def test_explicit_approval_authority_and_trigger(
    store: SqliteStore, classification: str, expected: str
) -> None:
    event = record_event(store)
    before = store.get_change_event(event["event_id"])
    approval = approve_event(
        store,
        event["event_id"],
        classification,
        "Investor reviewed the complete context.",
        now=NOW,
    )
    assert trigger(classification) == expected
    assert approval["approved_classification"] == classification
    assert approval["category"] == "JUDGMENT"
    report = assess_event(store, event["event_id"])
    assert report["reunderwriting_trigger"] == expected
    assert report["assessment"]["candidate_classification"] == "THESIS_UPDATE"
    assert report["approved_classification"] == classification
    assert store.get_change_event(event["event_id"]) == before
    assert len(store.list_underwriting("ADBE")) == 1
    with pytest.raises(StorageWriteError, match="immutable"):
        approve_event(
            store,
            event["event_id"],
            "NOISE",
            "Second approval is not an edit.",
            now=NOW,
        )


def test_affected_belief_values_preserve_semantics(store: SqliteStore) -> None:
    event = record_event(store)
    beliefs = event["affected_beliefs"]
    assert [item["kind"] for item in beliefs] == ["assumption", "probability", "thesis"]
    assert [item["category"] for item in beliefs] == [
        "ASSUMPTION",
        "JUDGMENT",
        "JUDGMENT",
    ]
    assert isinstance(beliefs[0]["previous_belief"], float)
    assert beliefs[1]["previous_belief"] == 0.5
    assert beliefs[2]["previous_belief"]["condition_id"] == "arr-growth"


@pytest.mark.parametrize(
    "pointer",
    [
        "/evidence/eod_price",
        "/manual/scenarios/-1/revenue_cagr",
        "/manual/scenarios/999/revenue_cagr",
        "/manual/scenarios/1/not_real",
        "/manual/probability_distribution/unknown",
    ],
)
def test_bad_belief_links_rejected_not_silently_ignored(
    store: SqliteStore, pointer: str
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    with pytest.raises(ChangeError, match="belief"):
        create_event(store, selected, event_input(affected_beliefs=[pointer]), now=NOW)
    assert not store.list_change_events()


def test_exact_v1_v2_isolation_and_no_latest_substitution(store: SqliteStore) -> None:
    first = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, first, event_input(), now=NOW)
    before = canonical_json(assess_event(store, event["event_id"]))
    persist(store, "ADBE", snapshot(price=40))
    assert canonical_json(assess_event(store, event["event_id"])) == before
    assert event["underwriting"]["version"] == 1
    assert (
        event["underwriting"]["underwriting_id"]
        == store.list_underwriting("ADBE")[0].underwriting_id
    )
    with pytest.raises(ChangeError, match="not found"):
        create_event(store, UnderwritingSelection("ADBE", 99), event_input(), now=NOW)
    with pytest.raises(StorageReadError, match="not found"):
        assess_event(store, "missing")


def test_decision_sizing_context_frozen_and_no_automatic_mutation(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    earlier = NOW - timedelta(minutes=10)
    decision = create_decision(store, selected, input_data(), now=earlier)
    portfolio = create_portfolio(store, portfolio_input(), now=earlier)
    sizing = size_position(
        store, selected, portfolio.snapshot_id, policy(), now=earlier
    )
    analysis = store.save_sizing_analysis(
        canonical_json(sizing), created_at=earlier.isoformat()
    )
    before = (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_sizing_analyses(),
        store.list_portfolio_snapshots(),
        store.list_shadow_entries(),
    )
    data = event_input(affected_binding_constraints=["evidence_quality"])
    event = create_event(store, selected, data, now=NOW)
    assert event["decision_context"]["decision_id"] == decision.decision_id
    assert event["sizing_context"]["analysis_id"] == analysis.analysis_id
    assert event["sizing_context"]["report"]["target_range"] == [0, 0.06]
    assert event["sizing_binding_effect"]["status"] == "INVESTOR_IDENTIFIED"
    approve_event(
        store, event["event_id"], "THESIS_UPDATE", "Revisit growth beliefs.", now=NOW
    )
    report = assess_event(store, event["event_id"])
    assert "WATCH decision should be revisited" in report["decision_implication"]
    assert (
        store.list_underwriting("ADBE"),
        store.list_decisions(),
        store.list_sizing_analyses(),
        store.list_portfolio_snapshots(),
        store.list_shadow_entries(),
    ) == before
    create_decision(
        store, selected, {**input_data(), "action": "PASS"}, now=NOW + timedelta(days=1)
    )
    assert (
        assess_event(store, event["event_id"])["decision_context"]["judgment"]["action"]
        == "WATCH"
    )
    assert "PASS" not in canonical_json(report["decision_context"]["judgment"])


def test_missing_context_and_unmapped_binding_effect_explicit(
    store: SqliteStore,
) -> None:
    event = record_event(store)
    assert event["decision_context"] is None and event["sizing_context"] is None
    assert event["sizing_binding_effect"]["status"] == "NOT_DETERMINED"
    with pytest.raises(ChangeError, match="binding"):
        create_event(
            store,
            UnderwritingSelection("ADBE", 1),
            event_input(affected_binding_constraints=["sector"]),
            now=NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "future_observed",
        "future_event",
        "future_source",
        "before_underwriting",
        "naive",
        "missing_fact_source",
        "missing_verification",
        "fact_interpretation",
        "nan",
        "bool",
        "extra",
        "duplicate_pointer",
    ],
)
def test_invalid_semantics_and_lookahead_leave_no_partial_event(
    store: SqliteStore, mutation: str
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    data = event_input()
    if mutation == "future_observed":
        data["observed_at"] = "2026-06-04T11:00:00+00:00"
    elif mutation == "future_event":
        data["event_date"] = "2026-06-04"
    elif mutation == "future_source":
        data["observation"]["references"][0]["observed_at"] = (
            "2026-06-04T11:00:00+00:00"
        )
    elif mutation == "before_underwriting":
        data["observed_at"] = "2026-06-01T11:00:00+00:00"
        data["event_date"] = "2026-06-01"
        data["observation"]["references"] = [{"title": "Fixture company report"}]
    elif mutation == "naive":
        data["observed_at"] = "2026-06-03T11:00:00"
    elif mutation == "missing_fact_source":
        data["observation"]["references"] = []
    elif mutation == "missing_verification":
        data["observation"].pop("verification_note")
    elif mutation == "fact_interpretation":
        data["interpretation"]["category"] = "FACT"
    elif mutation == "nan":
        data["observation"]["metric"]["value"] = float("nan")
    elif mutation == "bool":
        data["observation"]["metric"]["value"] = True
    elif mutation == "extra":
        data["approved_classification"] = "THESIS_BREAK"
    else:
        data["affected_beliefs"] *= 2
    with pytest.raises(ValueError):
        create_event(store, selected, data, now=NOW)
    assert not store.list_change_events()


def test_future_decision_and_sizing_not_imported_into_event(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    future = NOW + timedelta(days=1)
    create_decision(store, selected, input_data(), now=future)
    portfolio = create_portfolio(store, portfolio_input(), now=future)
    report = size_position(store, selected, portfolio.snapshot_id, policy(), now=future)
    store.save_sizing_analysis(canonical_json(report), created_at=future.isoformat())
    event = create_event(store, selected, event_input(), now=NOW)
    assert event["decision_context"] is None and event["sizing_context"] is None
    with pytest.raises(ChangeError, match="precede"):
        approve_event(
            store,
            event["event_id"],
            "NOISE",
            "Too early",
            now=NOW - timedelta(seconds=1),
        )


def test_summary_accumulates_all_approved_events_not_just_latest(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    for classification in ("THESIS_UPDATE", "EVIDENCE", "EVIDENCE", "NOISE", "NOISE"):
        event = create_event(store, selected, event_input(), now=NOW)
        approve_event(
            store, event["event_id"], classification, "Manual assessment", now=NOW
        )
    create_event(store, selected, event_input(), now=NOW)
    state = current_change_state(store, "ADBE")
    assert state["since_underwriting"] == {
        "NOISE": 2,
        "EVIDENCE": 2,
        "THESIS_UPDATE": 1,
        "THESIS_BREAK": 0,
    }
    assert state["status"] == "REUNDERWRITING_REQUIRED"
    assert state["pending_approval"] == 1
    assert len(state["included_event_ids"]) == 6
    assert len(change_history(store, "ADBE")) == 6
    assert canonical_json(state) == canonical_json(current_change_state(store, "ADBE"))


def test_immutable_database_history_and_forged_assessment_rejected(
    store: SqliteStore,
) -> None:
    event = record_event(store)
    approval = approve_event(
        store, event["event_id"], "THESIS_UPDATE", "Review required", now=NOW
    )
    for table, field, key in (
        ("change_events", "event_id", event["event_id"]),
        ("change_approvals", "approval_id", approval["approval_id"]),
    ):
        for operation in (
            f"UPDATE {table} SET content_hash='bad' WHERE {field}=?",
            f"DELETE FROM {table} WHERE {field}=?",
            f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} WHERE {field}=?",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store._conn.execute(operation, (key,))
            store._conn.rollback()
    forged = deepcopy(event)
    forged["assessment"]["candidate_classification"] = "NOISE"
    with pytest.raises(StorageWriteError, match="differs"):
        store.save_change_event(canonical_json(forged))
    assert (
        len(store.list_change_events()) == 1 and len(store.list_change_approvals()) == 1
    )


def test_historical_read_does_not_reassess_or_fetch_latest(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = record_event(store)
    before = canonical_json(assess_event(store, event["event_id"]))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Historical read cannot recompute/fetch")

    monkeypatch.setattr("owner_lens.changes.load_opportunity", forbidden)
    monkeypatch.setattr("owner_lens.changes.condition_assessment", forbidden)
    monkeypatch.setattr("owner_lens.changes._contexts", forbidden)
    monkeypatch.setattr("owner_lens.changes.trigger", forbidden)
    assert canonical_json(assess_event(store, event["event_id"])) == before
    assert canonical_json(json.loads(before)) == before


def test_integrity_errors_and_additive_v8_migration(store: SqliteStore) -> None:
    event = record_event(store)
    original = store.list_underwriting("ADBE")
    store._conn.executescript(
        "DROP TABLE change_approvals; DROP TABLE change_events; "
        "UPDATE schema_meta SET value='8' WHERE key='schema_version';"
    )
    store.initialize()
    assert store.list_underwriting("ADBE") == original
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "13"
    )
    store.save_change_event(canonical_json(event))
    approve_event(store, event["event_id"], "NOISE", "Manual", now=NOW)
    store._conn.executescript(
        "DROP TRIGGER change_approval_no_update; UPDATE change_approvals SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        store.list_change_approvals()
    store._conn.executescript(
        "DROP TRIGGER change_event_no_update; UPDATE change_events SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        assess_event(store, event["event_id"])


def test_cli_create_assess_approve_show_history_summary(
    store: SqliteStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    persist(store, "ADBE", monitored_snapshot())
    path = tmp_path / "event.json"
    path.write_text(canonical_json(event_input()), encoding="utf-8")
    assert (
        main(
            [
                "change",
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
    event_id = report["event_id"]
    assert report["history_status"] == "PENDING_APPROVAL"
    for action in ("show", "assess"):
        assert main(["change", action, event_id, "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == report
    assert (
        main(
            [
                "change",
                "approve",
                event_id,
                "--classification",
                "THESIS_UPDATE",
                "--rationale",
                "Revisit the growth trajectory.",
                "--json",
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["reunderwriting_trigger"] == "NEW_UNDERWRITING_REQUIRED"
    assert main(["change", "history", "ADBE", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [approved]
    assert main(["change", "summary", "ADBE", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "REUNDERWRITING_REQUIRED"
    assert main(["change", "show", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert len(store.list_underwriting("ADBE")) == 1


def test_workbench_explicit_approval_and_readonly_history(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", monitored_snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "What Changed?"
    app.run()
    assert not app.exception and not app.error
    app.selectbox(key="changes_version").set_value("ADBE:1").run()
    app.selectbox(key="changes_condition").set_value("arr-growth").run()
    app.text_area(key="changes_input").set_value(canonical_json(event_input()))
    next(
        item for item in app.button if item.label == "Record pending change event"
    ).click().run()
    assert not app.exception and not app.error
    assert len(store.list_change_events()) == 1 and not store.list_change_approvals()
    event_id = store.list_change_events()[0].event_id
    app.selectbox(key="changes_classification." + event_id).set_value("THESIS_UPDATE")
    app.text_area(key="changes_rationale." + event_id).set_value(
        "Revisit revenue growth assumptions."
    )
    next(
        item for item in app.button if item.label == "Explicitly approve classification"
    ).click().run()
    assert not app.exception and not app.error
    assert len(store.list_change_approvals()) == 1

    assert any(item.label == "Start from latest underwriting" for item in app.button)
    app.run()
    assert len(store.list_change_events()) == 1
    assert len(store.list_underwriting("ADBE")) == 1
    assert len(store.list_change_approvals()) == 1


def test_documented_synthetic_adbe_example(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    data = json.loads(
        (ROOT / "docs" / "examples" / "adbe_change.sample.json").read_text()
    )
    event = create_event(store, selected, data, now=NOW)
    assert event["assessment"]["result"] == "CONDITION_BREACHED"
    assert event["assessment"]["candidate_classification"] == "THESIS_UPDATE"
    assert event["event"]["observation"]["metric"]["value"] == 5.8
    assert len(event["affected_beliefs"]) == 3


@pytest.mark.parametrize(
    "threshold,value,met",
    [
        ("> 7%", 7, False),
        (">= 7%", 7, True),
        ("<= 7%", 7, True),
        ("< 7%", 7, False),
        ("== 7%", 7, True),
        ("== 7%", 7.000001, False),
    ],
)
def test_operator_boundaries_no_hidden_tolerance(
    store: SqliteStore,
    threshold: str,
    value: float,
    met: bool,
) -> None:
    original = monitored_snapshot()
    dependency = replace(
        original.manual.thesis.monitoring_dependencies[0], threshold=threshold
    )
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(
                original.manual,
                thesis=replace(
                    original.manual.thesis, monitoring_dependencies=(dependency,)
                ),
            ),
        ),
    )
    event = create_event(store, selected, event_input(value), now=NOW)
    assert event["assessment"]["predicate_satisfied"] is met
    assert event["assessment"]["result"] == (
        "CONDITION_MET" if met else "CONDITION_BREACHED"
    )


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("fixture://arr", "CONDITION_BREACHED"),
        ("fixture://different", "NOT_COMPARABLE"),
    ],
)
def test_source_uri_precedes_title_matching(
    store: SqliteStore, uri: str, expected: str
) -> None:
    original = monitored_snapshot()
    dependency = replace(
        original.manual.thesis.monitoring_dependencies[0],
        sources=(Reference(title="Another title", uri="fixture://arr"),),
    )
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(
                original.manual,
                thesis=replace(
                    original.manual.thesis, monitoring_dependencies=(dependency,)
                ),
            ),
        ),
    )
    data = event_input()
    data["observation"]["references"][0]["uri"] = uri
    event = create_event(store, selected, data, now=NOW)
    assert event["assessment"]["result"] == expected


@pytest.mark.parametrize("field", ["observable", "threshold"])
def test_missing_condition_metadata_does_not_create_candidate(
    store: SqliteStore, field: str
) -> None:
    original = monitored_snapshot()
    dependency = replace(
        original.manual.thesis.monitoring_dependencies[0], **{field: None}
    )
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(
                original.manual,
                thesis=replace(
                    original.manual.thesis, monitoring_dependencies=(dependency,)
                ),
            ),
        ),
    )
    event = create_event(store, selected, event_input(), now=NOW)
    assert event["assessment"]["result"] == "INSUFFICIENT_DATA"
    assert event["assessment"]["candidate_classification"] is None


def test_pending_candidate_does_not_require_new_underwriting(
    store: SqliteStore,
) -> None:
    event = record_event(store, event_input(-1, condition_id="arr-collapse"))
    assert event["assessment"]["candidate_classification"] == "THESIS_BREAK"
    summary = current_change_state(store, "ADBE")
    assert summary["since_underwriting"]["THESIS_BREAK"] == 0
    assert summary["status"] == "REVIEW_PENDING"
    assert "Pending approval: 1" in format_current_state(summary)
    assert "Latest decision: MISSING" in format_current_state(summary)


def test_events_linked_to_old_version_since_new_version_still_count(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    old_event = create_event(store, selected, event_input(), now=NOW)
    approve_event(
        store, old_event["event_id"], "THESIS_UPDATE", "Old version issue", now=NOW
    )
    original = store.list_underwriting("ADBE")[0]
    new = store.save_underwriting(
        security_id=original.security_id,
        ticker="ADBE",
        created_at=(NOW + timedelta(days=1)).isoformat(),
        as_of_date="2026-06-02",
        snapshot_json=monitored_snapshot().to_json(),
    )
    run_valuation(store, new)
    summary = current_change_state(store, "ADBE")
    assert summary["latest_underwriting"]["version"] == 2
    assert summary["since_underwriting"]["THESIS_UPDATE"] == 0
    data = event_input()
    data["observed_at"] = (NOW + timedelta(days=2)).isoformat()
    data["event_date"] = "2026-06-05"
    event = create_event(store, selected, data, now=NOW + timedelta(days=2))
    approve_event(
        store,
        event["event_id"],
        "THESIS_UPDATE",
        "New evidence on old version",
        now=NOW + timedelta(days=2),
    )
    state = current_change_state(store, "ADBE")
    assert state["since_underwriting"]["THESIS_UPDATE"] == 1
    assert state["included_event_ids"] == [event["event_id"]]
    assert len(change_history(store, "ADBE")) == 2
    assert event["underwriting"]["version"] == 1


def test_company_histories_and_decision_linkages_do_not_cross_securities(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    other = persist(store, "MSFT", monitored_snapshot())
    create_decision(store, other, input_data(), now=NOW - timedelta(minutes=5))
    event = create_event(store, selected, event_input(), now=NOW)
    assert event["decision_context"] is None
    assert change_history(store, "MSFT") == []
    assert (
        current_change_state(store, "MSFT")["latest_decision"]["chosen"][
            "underwriting"
        ]["ticker"]
        == "MSFT"
    )
    assert len(change_history(store, "ADBE")) == 1


def test_uncompleted_underwriting_and_lookahead_source_are_rejected(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot(), valued=False)
    with pytest.raises(ChangeError, match="valuation"):
        create_event(store, selected, event_input(), now=NOW)
    original = monitored_snapshot()
    evidence = json.loads(original.evidence_json)
    evidence["lookahead"] = {"fetched_at": "2027-01-01T00:00:00+00:00"}
    selected = persist(
        store, "ADBE", replace(original, evidence_json=json.dumps(evidence))
    )
    with pytest.raises(ChangeError, match="cutoff|after"):
        create_event(store, selected, event_input(), now=NOW)
    assert not store.list_change_events()


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "CALCULATION"),
        ("reunderwriting_trigger", "SELL"),
        ("model_version", "fake"),
        ("approved_at", "2020-01-01T00:00:00+00:00"),
        ("approved_classification", "SELL"),
        ("rationale", ""),
    ],
)
def test_forged_approval_rejected_atomically(
    store: SqliteStore, field: str, value: str
) -> None:
    event = record_event(store)
    approval = {
        "approval_id": "test-approval",
        "event_id": event["event_id"],
        "approved_at": NOW.isoformat(),
        "approved_classification": "THESIS_UPDATE",
        "category": "JUDGMENT",
        "rationale": "Explicit investor approval",
        "reunderwriting_trigger": "NEW_UNDERWRITING_REQUIRED",
        "model_version": "manual-change-assessment-v1",
        field: value,
    }
    with pytest.raises(StorageWriteError):
        store.save_change_approval(canonical_json(approval))
    assert not store.list_change_approvals()
    assert len(store.list_change_events()) == 1


def test_workbench_start_latest_is_draft_only(
    store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    first = persist(store, "ADBE", monitored_snapshot())
    event = create_event(store, first, event_input(), now=NOW)
    approve_event(store, event["event_id"], "THESIS_UPDATE", "Re-underwrite", now=NOW)
    latest = monitored_snapshot()
    latest = replace(
        latest,
        manual=replace(
            latest.manual,
            thesis=replace(
                latest.manual.thesis,
                biggest_uncertainty="Distinct latest-version belief",
            ),
        ),
    )
    persist(store, "ADBE", latest)
    captured: list[dict[str, Any]] = []

    def draft_renderer(ticker: str, projection: Any, source_factory: Any) -> None:
        captured.append(st.session_state["authoring." + ticker]["seed"])
        assert projection.record.version == 2

    monkeypatch.setattr(
        "owner_lens.workbench.views.underwriting_authoring.render", draft_renderer
    )
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "What Changed?"
    app.session_state["changes_version"] = "ADBE:1"
    app.session_state["changes_event"] = event["event_id"]
    app.run()
    assert not app.exception and not app.error
    next(
        item for item in app.button if item.label == "Start from latest underwriting"
    ).click().run()
    assert not app.exception and not app.error
    assert captured[-1] == authoring_from_manual(latest.manual)
    assert len(store.list_underwriting("ADBE")) == 2
    assert assess_event(store, event["event_id"])["underwriting"]["version"] == 1
    assert not store.list_decisions() and not store.list_sizing_analyses()
    assert any(item.label == "Start from latest underwriting" for item in app.button)
    app.run()
    assert len(store.list_change_events()) == 1
    assert len(store.list_underwriting("ADBE")) == 2
    assert len(store.list_change_approvals()) == 1


def test_workbench_approval_is_not_carried_between_events(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    selected = persist(store, "ADBE", monitored_snapshot())
    first = create_event(store, selected, event_input(), now=NOW)
    second = create_event(store, selected, event_input(8), now=NOW)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "What Changed?"
    app.session_state["changes_version"] = "ADBE:1"
    app.session_state["changes_event"] = first["event_id"]
    app.run()
    app.selectbox(key="changes_classification." + first["event_id"]).set_value(
        "THESIS_BREAK"
    )
    app.text_area(key="changes_rationale." + first["event_id"]).set_value(
        "Unsubmitted first judgment"
    )
    app.selectbox(key="changes_event").set_value(second["event_id"]).run()
    assert not app.exception and not app.error
    assert (
        app.selectbox(key="changes_classification." + second["event_id"]).value is None
    )
    assert app.text_area(key="changes_rationale." + second["event_id"]).value == ""
    next(
        item for item in app.button if item.label == "Explicitly approve classification"
    ).click().run()
    assert app.error and not app.exception
    assert not store.list_change_approvals()


@pytest.mark.parametrize("classification", [None, "NOISE", "EVIDENCE", "THESIS_UPDATE", "THESIS_BREAK"])
def test_summary_approval_authority_and_separate_noncomparable_pending(
    store: SqliteStore, classification: str | None,
) -> None:
    selected = persist(store, "ADBE", monitored_snapshot())
    data = event_input()
    data["observation"]["metric"]["unit"] = "incompatible"
    pending = create_event(store, selected, data, now=NOW)
    assert pending["assessment"]["result"] == "NOT_COMPARABLE"
    assert pending["assessment"]["candidate_classification"] is None
    if classification:
        event = create_event(store, selected, event_input(), now=NOW)
        approve_event(store, event["event_id"], classification, "Explicit approval", now=NOW)
    state = current_change_state(store, "ADBE")
    assert state["since_underwriting"] == {
        name: int(name == classification) for name in ("NOISE", "EVIDENCE", "THESIS_UPDATE", "THESIS_BREAK")
    }
    assert state["pending_approval"] == 1
    assert state["pending_non_comparable"] == 1
    assert state["status"] == (
        "REUNDERWRITING_REQUIRED" if classification in ("THESIS_UPDATE", "THESIS_BREAK") else "REVIEW_PENDING"
    )
    assert "Pending non-comparable assessment: 1" in format_current_state(state)


def predicate_condition(**changes: Any) -> dict[str, Any]:
    return {
        "condition_id": "total_adobe_arr_growth",
        "statement": "Total Adobe ARR growth must remain at least 6%.",
        "category": "JUDGMENT",
        "observable": "Total Adobe ARR growth",
        "operator": "GTE", "threshold": 6.0, "unit": "percent_yoy",
        "cadence": "quarterly", "source_family": "adobe_earnings",
        **changes,
    }


def predicate_snapshot(*, breaker: bool = False, **changes: Any) -> UnderwritingSnapshot:
    original = monitored_snapshot()
    condition = _conditions([predicate_condition(**changes)])[0]
    return replace(original, manual=replace(original.manual, thesis=replace(
        original.manual.thesis,
        monitoring_breakers=(condition,) if breaker else original.manual.thesis.monitoring_breakers,
        monitoring_dependencies=original.manual.thesis.monitoring_dependencies if breaker else (condition,),
        breakers=(condition.statement,) if breaker else original.manual.thesis.breakers,
        dependencies=original.manual.thesis.dependencies if breaker else (condition.statement,),
    )))


def predicate_event(value: float = 5.8) -> dict[str, Any]:
    data = event_input(value, condition_id="total_adobe_arr_growth", affected_beliefs=[])
    data["observation"]["metric"] = {
        "observable": "Total Adobe ARR growth", "value": value,
        "unit": "percent_yoy", "cadence": "quarterly", "source_family": "adobe_earnings",
    }
    return data


@pytest.mark.parametrize("op,value,met", [
    ("GTE", 6.0, True), ("GTE", 5.8, False), ("GT", 6.0, False),
    ("GT", 6.1, True), ("LTE", 6.0, True), ("LTE", 6.1, False),
    ("LT", 6.0, False), ("LT", 5.8, True), ("EQ", 6.0, True), ("EQ", 6.000001, False),
])
def test_structured_predicate_exact_numeric_operators(
    store: SqliteStore, op: str, value: float, met: bool,
) -> None:
    selected = persist(store, "ADBE", predicate_snapshot(operator=op))
    event = create_event(store, selected, predicate_event(value), now=NOW)
    assessment = event["assessment"]
    assert assessment["predicate_satisfied"] is met
    assert assessment["result"] == ("CONDITION_MET" if met else "CONDITION_BREACHED")
    assert assessment["candidate_classification"] == ("EVIDENCE" if met else "THESIS_UPDATE")
    assert assessment["condition"]["operator"] == op
    assert assessment["condition"]["threshold"] == 6.0
    assert assessment["condition"]["statement"] == predicate_condition()["statement"]
    assert event["model_version"] == "manual-change-assessment-v1.1"
    assert current_change_state(store, "ADBE")["status"] == "REVIEW_PENDING"
    assert sum(current_change_state(store, "ADBE")["since_underwriting"].values()) == 0


def test_structured_breaker_uses_invalidating_predicate(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", predicate_snapshot(breaker=True, operator="LT"))
    event = create_event(store, selected, predicate_event(), now=NOW)
    assert event["assessment"]["result"] == "CONDITION_BREACHED"
    assert event["assessment"]["candidate_classification"] == "THESIS_BREAK"
    assert current_change_state(store, "ADBE")["status"] == "REVIEW_PENDING"
    approve_event(store, event["event_id"], "THESIS_BREAK", "Explicit review", now=NOW)
    assert current_change_state(store, "ADBE")["status"] == "REUNDERWRITING_REQUIRED"


@pytest.mark.parametrize("field,value", [
    ("observable", "Total adobe ARR growth"), ("observable", " Total Adobe ARR growth "),
    ("observable", "Total Adobe ARR Growth"), ("observable", "Adobe ARR growth"),
    ("unit", "percent"), ("unit", "%"), ("unit", "ratio"),
    ("cadence", "Quarterly"), ("source_family", "Adobe_Earnings"),
    ("source_family", "adobe_earnings_release"),
])
def test_structured_predicate_metadata_never_fuzzy_matches(
    store: SqliteStore, field: str, value: str,
) -> None:
    selected = persist(store, "ADBE", predicate_snapshot())
    data = predicate_event()
    data["observation"]["metric"][field] = value
    event = create_event(store, selected, data, now=NOW)
    assert event["assessment"]["result"] == "NOT_COMPARABLE"
    assert event["assessment"]["candidate_classification"] is None
    state = current_change_state(store, "ADBE")
    assert state["pending_non_comparable"] == 1
    assert state["status"] == "REVIEW_PENDING"


@pytest.mark.parametrize("field", ["observable", "value", "unit", "cadence", "source_family"])
def test_structured_predicate_missing_event_metadata_is_insufficient(
    store: SqliteStore, field: str,
) -> None:
    selected = persist(store, "ADBE", predicate_snapshot())
    data = predicate_event()
    data["observation"]["metric"][field] = None
    event = create_event(store, selected, data, now=NOW)
    assert event["assessment"]["result"] == "INSUFFICIENT_DATA"
    state = current_change_state(store, "ADBE")
    assert state["pending_approval"] == 1 and state["pending_non_comparable"] == 0
    assert state["status"] == "REVIEW_PENDING"


@pytest.mark.parametrize("changes", [
    {"operator": "GTE_APPROX"}, {"operator": "gte"}, {"operator": None},
    {"threshold": "6.0"}, {"threshold": True}, {"threshold": float("inf")},
    {"threshold": float("nan")}, {"threshold": None},
    {"observable": None}, {"unit": None}, {"cadence": None}, {"source_family": None},
    {"monitoring_cadence": "Quarterly"},
])
def test_invalid_partial_or_conflicting_structured_predicate_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(UnderwritingError):
        _conditions([predicate_condition(**changes)])


def test_legacy_bytes_and_frozen_records_survive_structured_predicates(store: SqliteStore) -> None:
    legacy = monitored_snapshot()
    payload = legacy.to_json()
    data = json.loads(payload)
    for field in ("monitoring_dependencies", "monitoring_breakers"):
        assert all(not set(item) & {"operator", "unit", "cadence", "source_family"}
                   for item in data["manual"]["thesis"][field])
    assert UnderwritingSnapshot.from_json(payload).to_json() == payload
    original = persist(store, "ADBE", legacy)
    event = create_event(store, original, event_input(), now=NOW)
    approve_event(store, event["event_id"], "THESIS_UPDATE", "Approved before new predicate", now=NOW)
    before = (
        store.list_change_events(), store.list_change_approvals(),
        store.list_underwriting("ADBE"), canonical_json(assess_event(store, event["event_id"])),
    )
    structured = persist(store, "ADBE", predicate_snapshot())
    new = create_event(store, structured, predicate_event(), now=NOW)
    approve_event(store, new["event_id"], "NOISE", "Does not invalidate the earlier approval", now=NOW)
    assert store.list_change_events()[0] == before[0][0]
    assert store.list_change_approvals()[0] == before[1][0]
    assert store.list_underwriting("ADBE")[0] == before[2][0]
    assert canonical_json(assess_event(store, event["event_id"])) == before[3]
    assert current_change_state(store, "ADBE")["status"] == "REUNDERWRITING_REQUIRED"
    assert current_change_state(store, "ADBE")["since_underwriting"]["THESIS_UPDATE"] == 1
    assert not set(event["assessment"]["condition"]) & {"operator", "unit", "cadence", "source_family"}


def test_structured_predicate_roundtrip_cloning_and_zero_threshold() -> None:
    from owner_lens.underwriting_contract import parse_authoring_input

    original = predicate_snapshot(threshold=0)
    payload = original.to_json()
    restored = UnderwritingSnapshot.from_json(payload)
    assert restored.manual == original.manual
    assert restored.to_json() == payload
    condition = json.loads(payload)["manual"]["thesis"]["monitoring_dependencies"][0]
    assert condition["threshold"] == 0
    assert condition["operator"] == "GTE"
    draft = authoring_from_manual(restored.manual)
    cloned = parse_authoring_input(draft)
    assert cloned.thesis.monitoring_dependencies[0] == restored.manual.thesis.monitoring_dependencies[0]
    assert json.loads(restored.to_json()) == json.loads(payload)


def test_summary_uses_real_approval_not_flattened_candidate(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = record_event(store)
    pending = assess_event(store, event["event_id"])
    pending["approved_classification"] = "THESIS_UPDATE"
    pending["reunderwriting_trigger"] = "NEW_UNDERWRITING_REQUIRED"
    assert pending["approval"] is None
    monkeypatch.setattr("owner_lens.changes.change_history", lambda *args: [pending])
    state = current_change_state(store, "ADBE")
    assert state["status"] == "REVIEW_PENDING"
    assert sum(state["since_underwriting"].values()) == 0


def test_approval_moves_noncomparable_event_out_of_pending_counters(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", predicate_snapshot())
    data = predicate_event()
    data["observation"]["metric"]["source_family"] = "different"
    event = create_event(store, selected, data, now=NOW)
    approve_event(store, event["event_id"], "THESIS_UPDATE", "Explicit causal judgment despite incompatible metric", now=NOW)
    state = current_change_state(store, "ADBE")
    assert state["pending_approval"] == state["pending_non_comparable"] == 0
    assert state["since_underwriting"]["THESIS_UPDATE"] == 1
    assert state["status"] == "REUNDERWRITING_REQUIRED"


def test_authoring_widgets_preserve_and_edit_structured_predicate() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from owner_lens.workbench.views.underwriting_authoring import _conditions\n"
        "st.session_state['edited_conditions'] = _conditions("
        "st.session_state['seed_conditions'], 'dependencies', 'predicate_test')\n"
    )
    app.session_state["seed_conditions"] = [predicate_condition()]
    app.run()
    assert not app.exception
    result = app.session_state["edited_conditions"][0]
    for field in ("operator", "threshold", "observable", "unit", "cadence", "source_family"):
        assert result[field] == predicate_condition()[field]
    app.number_input(key="predicate_test.0.numeric_threshold").set_value(7.5).run()
    assert not app.exception
    result = app.session_state["edited_conditions"][0]
    assert result["threshold"] == 7.5
    assert _conditions([result])[0].source_family == "adobe_earnings"


def test_structured_zero_threshold_not_flagged_missing_in_projection(store: SqliteStore) -> None:
    from owner_lens.underwriting_contract import project_underwriting

    persist(store, "ADBE", predicate_snapshot(threshold=0))
    projection = project_underwriting(store, "ADBE", version=1)
    assert not any(item.section == "total_adobe_arr_growth" for item in projection.missing_evidence)


def test_workbench_displays_independent_pending_noncomparable_counter(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    selected = persist(store, "ADBE", predicate_snapshot())
    data = predicate_event()
    data["observation"]["metric"]["source_family"] = "different"
    create_event(store, selected, data, now=NOW)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "What Changed?"
    app.session_state["changes_version"] = "ADBE:1"
    app.run()
    assert not app.exception and not app.error
    assert any("Pending non-comparable assessment: 1" in item.value for item in app.caption)
    assert any("Status: REVIEW_PENDING" in item.value for item in app.markdown)
    assert sum(app.dataframe[0].value["Count"]) == 0

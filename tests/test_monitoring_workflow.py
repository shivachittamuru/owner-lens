"""Fixture-only Company Monitor previews, explicit approvals and retry recovery."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from test_changes import NOW, event_input, predicate_event, predicate_snapshot
from test_opportunity_catalog import _complete
from test_opportunity_comparison import persist
from test_research_context import inputs
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.changes import ChangeError, create_event, current_change_state
from owner_lens.monitoring_workflow import (
    approve_pending,
    monitored_projection,
    monitoring_state,
    prepare_review,
    preview_evidence,
    record_review,
    reunderwriting_context,
)
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageWriteError
from owner_lens.underwriting import create_underwriting
from owner_lens.workbench.data import WorkbenchSource


def _record(store: SqliteStore) -> Any:
    _complete(store, "ADBE", predicate_snapshot())
    return store.list_underwriting("ADBE")[-1]


def _preview(store: SqliteStore, record: Any, **kwargs: Any) -> dict[str, Any]:
    return preview_evidence(store, record, json.dumps(predicate_event()), now=NOW, **kwargs)


def test_latest_completed_and_pinned_identity_with_newer_incomplete(store: SqliteStore) -> None:
    record = _record(store)
    persist(store, "ADBE", predicate_snapshot(), valued=False)
    assert monitored_projection(store, "ADBE").record == record
    before = tuple(store._conn.iterdump())
    assert monitored_projection(store, "ADBE", record).record == record
    assert monitoring_state(store, record)["latest_underwriting"]["version"] == 1
    assert tuple(store._conn.iterdump()) == before
    _complete(store, "ADBE", predicate_snapshot())
    assert monitored_projection(store, "ADBE").record.version == 3
    assert monitored_projection(store, "ADBE", record).record == record
    with pytest.raises(ChangeError, match="identity mismatch"):
        monitored_projection(store, "ADBE", replace(record, content_hash="wrong"))


def test_json_preview_is_readonly_candidate_not_approval(store: SqliteStore) -> None:
    record = _record(store)
    before = tuple(store._conn.iterdump())
    preview = _preview(store, record)
    assert preview["underwriting"]["underwriting_id"] == record.underwriting_id
    assert preview["underwriting"]["content_hash"] == record.content_hash
    assert preview["assessment"]["result"] == "CONDITION_BREACHED"
    assert preview["assessment"]["candidate_classification"] == "THESIS_UPDATE"
    assert monitoring_state(store, record)["status"] == "NO_REUNDERWRITING_REQUIRED"
    assert tuple(store._conn.iterdump()) == before
    assert not store.list_change_events() and not store.list_change_approvals()


@pytest.mark.parametrize("data", ["{", "[]", '{"ticker":"MSFT"}', '{"security_id":99}'])
def test_invalid_or_company_override_json_rejected(store: SqliteStore, data: str) -> None:
    record = _record(store)
    with pytest.raises(ValueError):
        preview_evidence(store, record, data, now=NOW)
    assert not store.list_change_events()


def test_company_security_and_condition_mismatch_rejected(store: SqliteStore) -> None:
    record = _record(store)
    for changed in (
        replace(record, ticker="MSFT"), replace(record, security_id=99),
    ):
        with pytest.raises(ValueError):
            preview_evidence(store, changed, json.dumps(predicate_event()), now=NOW)
    with pytest.raises(ChangeError, match="conflicts"):
        _preview(store, record, condition_id="other")
    assert not store.list_change_events()


@pytest.mark.parametrize("field,value,status", [
    ("observable", "different", "NOT_COMPARABLE"),
    ("unit", "%", "NOT_COMPARABLE"),
    ("cadence", "annual", "NOT_COMPARABLE"),
    ("source_family", "other", "NOT_COMPARABLE"),
    ("source_family", None, "INSUFFICIENT_DATA"),
])
def test_preview_preserves_exact_predicate_matching(
    store: SqliteStore, field: str, value: str | None, status: str
) -> None:
    record = _record(store)
    data = predicate_event()
    data["observation"]["metric"][field] = value
    preview = preview_evidence(store, record, json.dumps(data), now=NOW)
    assert preview["assessment"]["result"] == status
    assert preview["assessment"]["candidate_classification"] is None


def test_legacy_qualitative_condition_is_not_reinterpreted(store: SqliteStore) -> None:
    original = predicate_snapshot()
    condition = replace(
        original.manual.thesis.monitoring_breakers[0], threshold="sustained deterioration"
    )
    _complete(store, "ADBE", replace(
        original, manual=replace(original.manual, thesis=replace(
            original.manual.thesis, monitoring_breakers=(condition,)
        ))
    ))
    record = store.list_underwriting("ADBE")[0]
    preview = preview_evidence(
        store, record, json.dumps(event_input(condition_id=condition.condition_id)), now=NOW
    )
    assert preview["assessment"]["result"] == "NOT_COMPARABLE"


def test_approval_requires_investor_judgment_and_separate_records(store: SqliteStore) -> None:
    record = _record(store)
    preview = _preview(store, record)
    with pytest.raises(ValueError):
        prepare_review(store, preview, "", "Rationale", now=NOW)
    with pytest.raises(ChangeError, match="rationale"):
        prepare_review(store, preview, "THESIS_UPDATE", "  ", now=NOW)
    assert not store.list_change_events()
    submission = prepare_review(store, preview, "EVIDENCE", "Investor override, not a model approval.", now=NOW)
    before = store.list_underwriting("ADBE")
    report = record_review(store, submission)
    assert report["assessment"]["candidate_classification"] == "THESIS_UPDATE"
    assert report["approved_classification"] == "EVIDENCE"
    assert report["approval"]["rationale"] == submission["rationale"]
    assert len(store.list_change_events()) == len(store.list_change_approvals()) == 1
    assert store.list_underwriting("ADBE") == before
    assert not store.list_decisions() and not store.list_sizing_analyses()
    assert record_review(store, submission) == report
    assert len(store.list_change_events()) == len(store.list_change_approvals()) == 1


@pytest.mark.parametrize("failure_point", ["event_before", "event_after", "approval_before", "approval_after"])
def test_partial_failure_retry_never_duplicates(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    record = _record(store)
    submission = prepare_review(store, _preview(store, record), "THESIS_UPDATE", "Revisit thesis.", now=NOW)
    method = "save_change_event" if failure_point.startswith("event") else "save_change_approval"
    original = getattr(store, method)

    def fail(payload: str) -> Any:
        if failure_point.endswith("after"):
            original(payload)
        raise StorageWriteError("Fixture interrupted save")

    monkeypatch.setattr(store, method, fail)
    with pytest.raises(StorageWriteError, match="interrupted"):
        record_review(store, submission)
    expected_events = 0 if failure_point == "event_before" else 1
    assert len(store.list_change_events()) == expected_events
    if expected_events and failure_point != "approval_after":
        assert monitoring_state(store, record)["status"] == "REVIEW_PENDING"
    monkeypatch.setattr(store, method, original)
    result = record_review(store, submission)
    assert result["event_id"] == submission["event"]["event_id"]
    assert len(store.list_change_events()) == len(store.list_change_approvals()) == 1
    assert monitoring_state(store, record)["status"] == "REUNDERWRITING_REQUIRED"
    changed = deepcopy(submission)
    changed["rationale"] = "Different approval"
    with pytest.raises(ChangeError, match="Retry differs"):
        record_review(store, changed)


def test_summary_precedence_and_no_incomplete_baseline_supersession(store: SqliteStore) -> None:
    record = _record(store)
    statuses = [
        ("EVIDENCE", "REVIEW_RECOMMENDED"),
        ("NOISE", "REVIEW_RECOMMENDED"),
        ("THESIS_UPDATE", "REUNDERWRITING_REQUIRED"),
        ("NOISE", "REUNDERWRITING_REQUIRED"),
    ]
    for classification, expected in statuses:
        preview = _preview(store, record)
        submission = prepare_review(store, preview, classification, "Explicit review.", now=NOW)
        record_review(store, submission)
        assert monitoring_state(store, record)["status"] == expected
    data = predicate_event()
    data["observation"]["metric"]["unit"] = "ratio"
    create_event(store, UnderwritingSelection("ADBE", 1), data, now=NOW)
    state = monitoring_state(store, record)
    assert state["pending_approval"] == state["pending_non_comparable"] == 1
    assert state["status"] == "REUNDERWRITING_REQUIRED"
    persist(store, "ADBE", predicate_snapshot(), valued=False)
    assert monitoring_state(store, record)["since_underwriting"]["THESIS_UPDATE"] == 1
    assert current_change_state(store, "ADBE")["latest_underwriting"]["version"] == 2


def _company_app() -> AppTest:
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"),
        default_timeout=120,
    )
    app.session_state["provider"] = "fmp"
    app.session_state["page"] = "Company"
    app.session_state["selected_ticker"] = "ADBE"
    return app


def _ui_json() -> str:
    return json.dumps(event_input(condition_id=None, affected_beliefs=[]))


def _approval_key(app: AppTest) -> str:
    return "monitor.ADBE.approve." + app.session_state["monitor.ADBE"]["preview"]["event_id"]


def test_company_monitor_load_preview_and_ordinary_approval(source: WorkbenchSource) -> None:
    inputs(source)
    before = tuple(source.store._conn.iterdump())
    app = _company_app().run()
    assert not app.exception and not app.error
    assert any(item.value == "Monitor ADBE v1" for item in app.subheader)
    assert tuple(source.store._conn.iterdump()) == before
    app.button(key="monitor.ADBE.new").click().run()
    app.text_area(key="monitor.ADBE.raw").set_value(_ui_json())
    app.button(key="monitor.ADBE.validate").click().run()
    assert not app.exception and not app.error
    assert tuple(source.store._conn.iterdump()) == before
    approval_key = _approval_key(app)
    assert app.selectbox(key=approval_key + ".classification").value is None
    approve = next(item for item in app.button if item.label == "Record & Approve Change")
    approve.click().run()
    assert app.error and not source.store.list_change_events()
    app.selectbox(key=approval_key + ".classification").set_value("EVIDENCE")
    app.text_area(key=approval_key + ".rationale").set_value("Continue monitoring.")
    next(item for item in app.button if item.label == "Record & Approve Change").click().run()
    assert not app.exception and not app.error
    assert any("Authoritative thesis status: REVIEW_RECOMMENDED" in item.value for item in app.markdown)
    assert not any(item.label == "Prepare Re-underwriting" for item in app.button)
    assert len(source.store.list_change_events()) == len(source.store.list_change_approvals()) == 1
    assert not source.store.list_decisions() and not source.store.list_sizing_analyses()
    app.run()
    assert len(source.store.list_change_events()) == len(source.store.list_change_approvals()) == 1
    app.button(key="monitor.ADBE.new").click().run()
    app.text_area(key="monitor.ADBE.raw").set_value(_ui_json())
    app.button(key="monitor.ADBE.validate").click().run()
    next_key = _approval_key(app)
    assert next_key != approval_key
    assert app.selectbox(key=next_key + ".classification").value is None
    assert app.text_area(key=next_key + ".rationale").value == ""


def test_company_thesis_change_export_and_cleanup_one_handoff(source: WorkbenchSource) -> None:
    detail, projection = inputs(source)
    record = projection.record
    preview = preview_evidence(source.store, record, _ui_json(), now=NOW)
    submission = prepare_review(source.store, preview, "THESIS_UPDATE", "Synthetic isolated test.", now=NOW)
    record_review(source.store, submission)
    before = tuple(source.store._conn.iterdump())
    exported = reunderwriting_context(source.store, record, detail)
    assert "Authoring v2" in exported and "THESIS_UPDATE" in exported
    assert record.underwriting_id in exported and record.content_hash in exported
    assert "Synthetic isolated test." in exported
    assert "prior_bear_base_bull" in exported and '"BEAR"' in exported
    assert tuple(source.store._conn.iterdump()) == before
    app = _company_app().run()
    app.button(key="monitor.ADBE.prepare").click().run()
    app.button(key="monitor.ADBE.copy").click().run()
    assert not app.exception and not app.error
    assert any("OwnerLens Re-underwriting Context" in item.value for item in app.code)
    assert any(item.label == "Paste OwnerLens Underwriting JSON" for item in app.text_area)
    assert any(item.label == "Validate + Preview" for item in app.button)
    assert len(source.store.list_underwriting("ADBE")) == 1
    assert tuple(source.store._conn.iterdump()) == before


def test_company_review_stays_pinned_and_discloses_newer_incomplete(source: WorkbenchSource) -> None:
    _, projection = inputs(source)
    app = _company_app().run()
    create_underwriting(
        source, "ADBE", projection.snapshot.manual, now=NOW + timedelta(days=1)
    )
    app.run()
    assert not app.exception and not app.error
    assert any("Newer underwriting v2 exists but is incomplete" in item.value for item in app.warning)
    assert app.session_state["monitor.ADBE"]["record"] == projection.record


def test_existing_pending_event_is_approved_without_another_event(store: SqliteStore) -> None:
    record = _record(store)
    event = create_event(store, UnderwritingSelection("ADBE", record.version), predicate_event(), now=NOW)
    assert monitoring_state(store, record)["status"] == "REVIEW_PENDING"
    result = approve_pending(store, event["event_id"], "NOISE", "Insufficient significance.")
    assert result == approve_pending(store, event["event_id"], "NOISE", "Insufficient significance.")
    assert monitoring_state(store, record)["status"] == "NO_REUNDERWRITING_REQUIRED"
    assert len(store.list_change_events()) == len(store.list_change_approvals()) == 1


def test_company_partial_approval_failure_shows_pending_and_retries_same_event(
    source: WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs(source)
    app = _company_app().run()
    app.button(key="monitor.ADBE.new").click().run()
    app.text_area(key="monitor.ADBE.raw").set_value(_ui_json())
    app.button(key="monitor.ADBE.validate").click().run()
    approval_key = _approval_key(app)
    app.selectbox(key=approval_key + ".classification").set_value("THESIS_UPDATE")
    app.text_area(key=approval_key + ".rationale").set_value("Synthetic fixture review.")
    original = SqliteStore.save_change_approval

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise StorageWriteError("Fixture approval failure")

    monkeypatch.setattr(SqliteStore, "save_change_approval", fail)
    next(item for item in app.button if item.label == "Record & Approve Change").click().run()
    assert not app.exception and app.error
    assert len(source.store.list_change_events()) == 1
    assert not source.store.list_change_approvals()
    pending_id = source.store.list_change_events()[0].event_id
    app.run()
    assert not app.exception
    assert any("Authoritative thesis status: REVIEW_PENDING" in item.value for item in app.markdown)
    assert any("recorded pending approval" in item.value.lower() for item in app.markdown)
    monkeypatch.setattr(SqliteStore, "save_change_approval", original)
    app.button(key="monitor.ADBE.retry").click().run()
    assert not app.exception and not app.error
    assert source.store.list_change_events()[0].event_id == pending_id
    assert len(source.store.list_change_events()) == len(source.store.list_change_approvals()) == 1
    assert any("Authoritative thesis status: REUNDERWRITING_REQUIRED" in item.value for item in app.markdown)


def test_changed_json_invalidates_preview_without_writes(source: WorkbenchSource) -> None:
    inputs(source)
    app = _company_app().run()
    app.button(key="monitor.ADBE.new").click().run()
    app.text_area(key="monitor.ADBE.raw").set_value(_ui_json())
    app.button(key="monitor.ADBE.validate").click().run()
    assert any(item.label == "Record & Approve Change" for item in app.button)
    app.text_area(key="monitor.ADBE.raw").set_value("{}").run()
    assert not app.exception
    assert not any(item.label == "Record & Approve Change" for item in app.button)
    assert not source.store.list_change_events()
    assert not source.store.list_change_approvals()


def test_event_dates_and_source_verification_are_never_manufactured(store: SqliteStore) -> None:
    record = _record(store)
    for field in ("observed_at", "event_date"):
        data = predicate_event()
        del data[field]
        with pytest.raises(ValueError):
            preview_evidence(store, record, json.dumps(data), now=NOW)
    data = predicate_event()
    data["observed_at"] = (NOW + timedelta(days=1)).isoformat()
    with pytest.raises(ChangeError, match="look ahead"):
        preview_evidence(store, record, json.dumps(data), now=NOW)
    data = predicate_event()
    del data["observation"]["verification_note"]
    with pytest.raises(ChangeError, match="verification"):
        preview_evidence(store, record, json.dumps(data), now=NOW)
    assert not store.list_change_events()

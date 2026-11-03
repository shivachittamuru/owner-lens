"""Offline contextual sizing, explicit approval and recoverable immutable linkage."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from test_decisions import input_data
from test_opportunity_catalog import _app, _complete
from test_opportunity_comparison import persist, snapshot
from test_position_sizing import NOW, policy, portfolio_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.allocation_workflow import (
    discover_allocation_context,
    record_allocation_decision,
    validate_comparison_context,
)
from owner_lens.decisions import DecisionError, create_decision
from owner_lens.opportunity_catalog import ComparisonVersion
from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageWriteError
from owner_lens.position_sizing import canonical_json, create_portfolio, size_position


def _inputs(store: SqliteStore) -> tuple[UnderwritingSelection, str, dict[str, Any]]:
    a = _complete(store, "ADBE", snapshot(price=20))
    b = _complete(store, "MSFT", snapshot(price=30))
    comparison = compare_underwritings(store, (a, b)).to_json()
    judgment = {
        **input_data(),
        "alternatives": [
            {"underwriting": "MSFT:1", "disposition": "DEFERRED", "reason": "Verify thesis first."}
        ],
    }
    return a, comparison, judgment


def _sizing(store: SqliteStore, selected: UnderwritingSelection, **changes: Any) -> dict[str, Any]:
    portfolio = create_portfolio(store, portfolio_input(**changes), now=NOW)
    return size_position(store, selected, portfolio.snapshot_id, policy(), now=NOW)


def test_discovery_uses_existing_snapshots_and_unique_saved_policies_read_only(store: SqliteStore) -> None:
    selected, _, _ = _inputs(store)
    assert discover_allocation_context(store).portfolios == ()
    assert discover_allocation_context(store).policies == ()
    report = _sizing(store, selected, notes="Synthetic fixture, not actual holdings.")
    first = store.save_sizing_analysis(canonical_json(report), created_at=NOW.isoformat())
    later = store.save_sizing_analysis(
        canonical_json(report), created_at=(NOW + timedelta(seconds=1)).isoformat()
    )
    older = create_portfolio(
        store, portfolio_input(as_of_date="2026-06-01"), now=NOW + timedelta(seconds=2)
    )
    before = tuple(store._conn.iterdump())
    context = discover_allocation_context(store)
    assert [item.as_of_date for item in context.portfolios] == ["2026-06-03", "2026-06-01"]
    assert context.portfolios[1].snapshot_id == older.snapshot_id
    assert len(context.policies) == 1
    assert context.policies[0].source_analysis_id == later.analysis_id != first.analysis_id
    assert json.loads(context.policies[0].policy_json) == policy()
    assert tuple(store._conn.iterdump()) == before


def test_exact_handoff_and_preview_keep_frozen_economics_and_constraints(store: SqliteStore) -> None:
    selected, comparison, _ = _inputs(store)
    old = store.list_underwriting("ADBE")[0]
    persist(store, "ADBE", snapshot(price=5))
    before = tuple(store._conn.iterdump())
    validated = validate_comparison_context(store, comparison, selected)
    assert validated["opportunities"][0]["summary"]["underwriting_id"] == old.underwriting_id
    assert tuple(store._conn.iterdump()) == before
    report = _sizing(store, selected)
    assert report["underwriting"]["content_hash"] == old.content_hash
    assert report["opportunity"]["summary"]["current_price"] == 20
    assert report["opportunity"]["summary"]["market_date"] == "2026-06-01"
    assert report["current_weight"] == 0.02 and report["cash_weight"] == 0.4
    assert report["sector_weights"]["Technology"] == pytest.approx(0.2)
    assert report["thesis_weights"]["AI_CAPEX"] == pytest.approx(0.2)
    assert report["target_range"] == pytest.approx([0, 0.06])
    assert report["incremental_room"] == pytest.approx([0, 0.04])
    assert set(report["binding_constraints"]) == {"bear_loss_budget", "evidence_quality"}
    assert report["quality_cap_reasons"]


@pytest.mark.parametrize("action", ["WATCH", "PASS"])
def test_research_decisions_without_portfolio_or_policy_and_idempotent_retry(
    store: SqliteStore, action: str
) -> None:
    selected, comparison, judgment = _inputs(store)
    judgment["action"] = action
    request_id = str(uuid4())
    before = store.list_underwriting("ADBE")
    first, analysis = record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=None,
    )
    again, _ = record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=None,
    )
    assert first == again and analysis is None
    assert len(store.list_decisions()) == 1
    assert first.judgment.action == action
    assert first.alternatives[0].opportunity.label == "MSFT:1"
    assert store.list_underwriting("ADBE") == before
    assert not store.list_shadow_entries()
    assert not store.list_portfolio_snapshots()
    assert not store.list_sizing_analyses()


def test_decision_and_intended_allocation_linkage_retry_and_no_execution(store: SqliteStore) -> None:
    selected, comparison, judgment = _inputs(store)
    report = _sizing(store, selected)
    report = size_position(
        store, selected, report["portfolio"]["snapshot_id"], policy(),
        proposed_increment=0.02, now=NOW,
    )
    original = store.list_underwriting("ADBE")
    portfolios = store.list_portfolio_snapshots()
    request_id = str(uuid4())
    result = record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=report,
    )
    assert result == record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=report,
    )
    decision, saved = result
    assert saved is not None
    assert saved.decision_id == decision.decision_id == request_id
    frozen = json.loads(saved.report_json)
    assert frozen["decision_context"] == json.loads(decision.to_json())
    assert frozen["proposed_increment"] == 0.02
    assert frozen["proposed_target_weight"] == 0.04
    assert decision.chosen.underwriting == original[0]
    assert store.list_underwriting("ADBE") == original
    assert store.list_portfolio_snapshots() == portfolios
    assert not store.list_shadow_entries()
    assert len(store.list_sizing_analyses()) == len(store.list_decisions()) == 1


def test_partial_persistence_failure_resumes_existing_decision(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected, comparison, judgment = _inputs(store)
    report = _sizing(store, selected)
    request_id = str(uuid4())
    save = store.save_sizing_analysis

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise StorageWriteError("Fixture failure after decision commit")

    monkeypatch.setattr(store, "save_sizing_analysis", fail)
    with pytest.raises(StorageWriteError, match="after decision"):
        record_allocation_decision(
            store, selected, comparison, judgment, request_id=request_id,
            approved_at=NOW, sizing_report=report,
        )
    assert len(store.list_decisions()) == 1
    assert not store.list_sizing_analyses()
    monkeypatch.setattr(store, "save_sizing_analysis", save)
    decision, saved = record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=report,
    )
    assert decision.decision_id == request_id and saved is not None
    assert len(store.list_decisions()) == len(store.list_sizing_analyses()) == 1


def test_changed_retry_and_forged_comparison_rejected(store: SqliteStore) -> None:
    selected, comparison, judgment = _inputs(store)
    request_id = str(uuid4())
    record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=None,
    )
    with pytest.raises(DecisionError, match="Retry differs"):
        record_allocation_decision(
            store, selected, comparison, {**judgment, "action": "BUY"},
            request_id=request_id, approved_at=NOW, sizing_report=None,
        )
    tampered = json.loads(comparison)
    tampered["opportunities"][0]["summary"]["underwriting_content_hash"] = "wrong"
    with pytest.raises(DecisionError, match="immutable sources"):
        validate_comparison_context(store, json.dumps(tampered), selected)
    assert len(store.list_decisions()) == 1


def test_shadow_choices_never_enter_portfolio_discovery(store: SqliteStore) -> None:
    selected, _, _ = _inputs(store)
    create_decision(store, selected, {
        **input_data(), "shadow": {"alternatives": [], "include_benchmark": False}
    }, now=NOW)
    assert store.list_shadow_entries()
    assert discover_allocation_context(store).portfolios == ()


def _open_allocation(store: SqliteStore) -> Any:
    _inputs(store)
    app = _app().run()
    app.multiselect(key="opportunity_companies").set_value(["ADBE", "MSFT"]).run()
    app.selectbox(key="comparison_allocation_selected").set_value("ADBE:1").run()
    next(item for item in app.button if item.label == "Evaluate Allocation").click().run()
    return app


def test_ui_handoff_missing_context_and_explicit_research_approval(store: SqliteStore) -> None:
    app = _open_allocation(store)
    assert not app.exception and not app.error
    state = app.session_state["allocation_workflow"]
    assert state["selected"] == "ADBE:1"
    assert any("Frozen price $20.00 on 2026-06-01" in item.value for item in app.caption)
    assert not store.list_decisions()
    assert any("No portfolio snapshot exists" in item.value for item in app.info)
    assert next(item for item in app.selectbox if item.label == "Action [JUDGMENT]").value is None
    before = tuple(store._conn.iterdump())
    app.run()
    assert tuple(store._conn.iterdump()) == before
    next(item for item in app.button if item.label == "Record Decision").click().run()
    assert not app.exception
    assert app.error and not store.list_decisions()
    assert "approved" not in app.session_state["allocation_workflow"]
    next(item for item in app.selectbox if item.label == "Action [JUDGMENT]").set_value("WATCH")
    next(item for item in app.selectbox if item.label == "Confidence [JUDGMENT]").set_value("MEDIUM")
    next(item for item in app.text_area if item.label == "Rationale [JUDGMENT]").set_value("Need more evidence.")
    next(item for item in app.text_input if item.label == "Primary reason [JUDGMENT]").set_value("Verify thesis.")
    next(item for item in app.text_area if item.label == "Key risk [JUDGMENT]").set_value("Competitive erosion.")
    next(item for item in app.text_area if item.label == "Change condition [JUDGMENT]").set_value("Verify margins.")
    next(item for item in app.selectbox if item.label == "MSFT:1: disposition").set_value("DEFERRED")
    next(item for item in app.text_area if item.label.startswith("MSFT:1: why")).set_value("Compare evidence.")
    next(item for item in app.button if item.label == "Record Decision").click().run()
    assert not app.exception and not app.error
    assert len(store.list_decisions()) == 1
    assert any("No trade, actual holding or shadow entry" in item.value for item in app.success)
    app.run()
    assert len(store.list_decisions()) == 1
    next(item for item in app.button if item.label == "Back to comparison").click().run()
    assert not app.exception and not app.error
    assert app.multiselect(key="opportunity_companies").value == ["ADBE", "MSFT"]


@pytest.mark.parametrize("missing_cash", [False, True])
def test_ui_snapshot_freshness_confirmation_policy_and_missing_cash(
    store: SqliteStore, missing_cash: bool
) -> None:
    selected, _, _ = _inputs(store)
    report = _sizing(store, selected, notes="Synthetic example only.", cash=None if missing_cash else 0.4)
    store.save_sizing_analysis(canonical_json(report), created_at=NOW.isoformat())
    app = _app()
    comparison = compare_underwritings(store, (selected, UnderwritingSelection("MSFT", 1)))
    app.session_state["allocation_workflow"] = {
        "selected": "ADBE:1", "comparison_json": comparison.to_json()
    }
    before = tuple(store._conn.iterdump())
    app.run()
    assert not app.exception and not app.error
    assert any("Latest is not necessarily current" in item.value for item in app.warning)
    assert any("Synthetic example only." in item.value for item in app.markdown)
    assert not app.metric
    confirm = next(item for item in app.checkbox if item.label.startswith("I confirm"))
    confirm.check().run()
    assert not app.exception and not app.error
    assert len(app.metric) == 4
    assert app.metric[2].label == "Policy ceiling"
    if missing_cash:
        assert app.metric[1].value == "MISSING"
        assert any("Cash was not supplied" in item.value for item in app.warning)
        assert app.metric[3].value == "0.00%"
    assert tuple(store._conn.iterdump()) == before


def test_ui_missing_policy_is_explicit_and_never_fabricates_capacity(store: SqliteStore) -> None:
    _, comparison, _ = _inputs(store)
    create_portfolio(store, portfolio_input(), now=NOW)
    app = _app()
    app.session_state["allocation_workflow"] = {"selected": "ADBE:1", "comparison_json": comparison}
    app.run()
    assert not app.exception and not app.error
    assert any("No saved sizing policy exists" in item.value for item in app.info)
    assert not app.metric
    assert not store.list_decisions() and not store.list_sizing_analyses()


def test_company_handoff_opens_comparison_instead_of_previous_allocation(store: SqliteStore) -> None:
    app = _open_allocation(store)
    record = store.list_underwriting("MSFT")[0]
    app.session_state["opportunity_requested_underwriting"] = ComparisonVersion(
        UnderwritingSelection("MSFT", 1), record.underwriting_id, record.content_hash
    )
    app.run()
    assert not app.exception and not app.error
    assert app.multiselect(key="opportunity_companies").value == ["MSFT"]
    assert app.selectbox(key="opportunity_version.MSFT").value == "MSFT:1"
    assert "allocation_workflow" not in app.session_state


def test_ui_approved_allocation_retry_preserves_locked_payload(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected, comparison, judgment = _inputs(store)
    report = _sizing(store, selected)
    report = size_position(
        store, selected, report["portfolio"]["snapshot_id"], policy(),
        proposed_increment=0.01, now=NOW,
    )
    request_id = str(uuid4())
    state = {
        "selected": "ADBE:1",
        "comparison_json": comparison,
        "approved": {
            "request_id": request_id, "approved_at": NOW.isoformat(),
            "judgment": judgment, "report": report,
        },
    }
    app = _app()
    app.session_state["allocation_workflow"] = state
    app.run()
    assert not app.exception and not store.list_decisions()
    assert not any(item.label == "Action [JUDGMENT]" for item in app.selectbox)
    save = SqliteStore.save_sizing_analysis

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise StorageWriteError("Fixture failure")

    monkeypatch.setattr(SqliteStore, "save_sizing_analysis", fail)
    next(item for item in app.button if item.label == "Retry Record Decision").click().run()
    assert not app.exception and app.error
    assert len(store.list_decisions()) == 1
    assert any("decision may already be committed" in item.value for item in app.error)
    monkeypatch.setattr(SqliteStore, "save_sizing_analysis", save)
    next(item for item in app.button if item.label == "Retry Record Decision").click().run()
    assert not app.exception and not app.error
    assert len(store.list_decisions()) == len(store.list_sizing_analyses()) == 1
    assert any("Investor intended increment: 1.00%" in item.value for item in app.markdown)
    assert app.session_state["allocation_workflow"]["decision_id"] == request_id
    app.run()
    assert len(store.list_decisions()) == len(store.list_sizing_analyses()) == 1


def test_retry_recovers_decision_commit_before_ui_receipt(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected, comparison, judgment = _inputs(store)
    request_id = str(uuid4())
    save = store.save_decision

    def fail_after_commit(payload: str) -> Any:
        save(payload)
        raise StorageWriteError("Fixture interrupted receipt")

    monkeypatch.setattr(store, "save_decision", fail_after_commit)
    with pytest.raises(StorageWriteError, match="interrupted receipt"):
        record_allocation_decision(
            store, selected, comparison, judgment, request_id=request_id,
            approved_at=NOW, sizing_report=None,
        )
    monkeypatch.setattr(store, "save_decision", save)
    decision, _ = record_allocation_decision(
        store, selected, comparison, judgment, request_id=request_id,
        approved_at=NOW, sizing_report=None,
    )
    assert decision.decision_id == request_id
    assert len(store.list_decisions()) == 1


def test_different_selected_company_and_wrong_sizing_identity(store: SqliteStore) -> None:
    selected, comparison, _ = _inputs(store)
    other = UnderwritingSelection("MSFT", 1)
    judgment = {
        **input_data(), "alternatives": [{
            "underwriting": "ADBE:1", "disposition": "PREFERRED", "reason": "Stronger return, needs evidence."
        }]
    }
    report = _sizing(store, selected)
    with pytest.raises(DecisionError, match="exact compared underwriting"):
        record_allocation_decision(
            store, other, comparison, judgment, request_id=str(uuid4()),
            approved_at=NOW, sizing_report=report,
        )
    assert not store.list_decisions()
    decision, _ = record_allocation_decision(
        store, other, comparison, judgment, request_id=str(uuid4()),
        approved_at=NOW, sizing_report=None,
    )
    assert decision.chosen.label == "MSFT:1"
    assert decision.alternatives[0].opportunity.label == "ADBE:1"


def test_ui_has_no_financial_calculation_implementation() -> None:
    import inspect

    from owner_lens.workbench.views import allocation

    source = inspect.getsource(allocation)
    assert "size_position(" in source and "record_allocation_decision(" in source
    assert "max_single_position_weight /" not in source
    assert "terminal_return /" not in source
    assert "create_decision(" not in source

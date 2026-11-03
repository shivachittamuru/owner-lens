"""Inline Compare -> Evaluate Allocation -> Record Decision experience."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import streamlit as st

from owner_lens.allocation_workflow import (
    discover_allocation_context,
    record_allocation_decision,
    validate_comparison_context,
)
from owner_lens.decisions import (
    AlternativeDisposition,
    Confidence,
    DecisionAction,
    DecisionJudgment,
    load_decision_json,
    read_decision,
)
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json, size_position, sizing_rows
from owner_lens.workbench.views._common import frame

ERRORS = (ValueError, PersistenceError)


def _assessment(report: dict[str, Any]) -> None:
    columns = st.columns(4)
    columns[0].metric("Current portfolio weight", f"{report['current_weight']:.2%}")
    columns[1].metric(
        "Cash available", f"{report['cash_weight']:.2%}"
        if report["cash_weight"] is not None else "MISSING"
    )
    columns[2].metric("Policy ceiling", f"{report['target_range'][1]:.2%}")
    columns[3].metric("Incremental capacity", f"{report['incremental_room'][1]:.2%}")
    st.write("Binding constraints: " + ", ".join(report["binding_constraints"]))
    st.caption(
        "Policy ceiling, not a target weight. Zero is a valid choice. A non-loss "
        "modeled Bear scenario is not a guarantee of limited real-world downside."
    )
    for warning in report["warnings"]:
        st.warning(warning)
    for missing in report["missing_dimensions"]:
        st.warning(missing)
    st.write("Evidence-quality limitations: " + (
        ", ".join(report["quality_cap_reasons"]) or "None established"
    ))
    st.write(
        f"Modeled Bear contribution at current weight: "
        f"{report['current_bear_loss_contribution']:.2%}"
    )
    if report["proposed_increment"] is not None:
        st.write(
            f"Investor intended increment: {report['proposed_increment']:.2%}; "
            f"proposed total weight: {report['proposed_target_weight']:.2%}; "
            f"modeled Bear contribution: {report['proposed_bear_loss_contribution']:.2%}"
        )
    with st.expander("Exposures, policy ceilings and assessment details"):
        st.write("Existing sector exposures", report["sector_weights"])
        st.write("Existing thesis exposures", report["thesis_weights"])
        st.dataframe(frame(sizing_rows(report), index="Metric"), width="stretch")
        st.json(canonical_json(report))


def _recorded(store: SqliteStore, state: dict[str, Any]) -> None:
    record = next(
        item for item in store.list_decisions() if item.decision_id == state["decision_id"]
    )
    decision = read_decision(record)
    summary = decision.chosen.summary
    st.success("Decision recorded. No trade, actual holding or shadow entry was created.")
    st.subheader(f"{decision.chosen.label}: {decision.judgment.action}")
    st.write("Rationale: " + decision.judgment.rationale)
    st.caption(
        f"Frozen expected CAGR {summary['expected_5y_cagr']:.2%}; "
        f"hurdle {summary['investor_policy']['required_return']:.2%}. "
        f"Price ${summary['current_price']:.2f} on {summary['market_date']}. "
        f"Recorded {decision.recorded_at} | {decision.decision_id}"
    )
    st.write("Confidence [JUDGMENT]: " + decision.judgment.confidence)
    st.write("Primary reason: " + decision.judgment.primary_reason)
    st.write("Risk: " + decision.judgment.biggest_risk)
    st.write("Change condition: " + decision.judgment.what_would_change_decision)
    for alternative in decision.alternatives:
        st.write(
            f"{alternative.opportunity.label}: {alternative.disposition}: {alternative.reason}"
        )
    if state.get("analysis_id"):
        analysis = store.get_sizing_analysis(state["analysis_id"])
        _assessment(json.loads(analysis.report_json))
        st.caption(f"Linked immutable sizing analysis: {analysis.analysis_id}")
    else:
        st.info("Allocation assessment unavailable/not used; no capacity was fabricated.")
    with st.expander("Decision JSON, provenance and exact immutable identities"):
        st.json(decision.to_json())
    if st.button("Open this underwriting in Company Investment View"):
        from owner_lens.workbench.views.opportunity_comparison import _open_company

        _open_company(UnderwritingSelection.parse(decision.chosen.label))


def _save(store: SqliteStore, state: dict[str, Any]) -> None:
    pending = state["approved"]
    try:
        decision, analysis = record_allocation_decision(
            store,
            UnderwritingSelection.parse(state["selected"]),
            state["comparison_json"],
            pending["judgment"],
            request_id=pending["request_id"],
            approved_at=datetime.fromisoformat(pending["approved_at"]),
            sizing_report=pending["report"],
        )
    except ERRORS as exc:
        st.error(
            f"Recording did not finish: {exc}. A decision may already be committed; "
            "retry resumes this exact approval without creating another decision."
        )
    else:
        state["decision_id"] = decision.decision_id
        state["analysis_id"] = analysis.analysis_id if analysis else None
        st.rerun()


def render(store: SqliteStore, state: dict[str, Any]) -> None:
    if st.button("Back to comparison"):
        if state.get("approved") and not state.get("decision_id"):
            st.error("Finish retrying the pending approval before leaving this workflow.")
        else:
            for key, value in state.get("comparison_selections", {}).items():
                st.session_state[key] = value
            del st.session_state["allocation_workflow"]
            st.rerun()
    if state.get("decision_id"):
        _recorded(store, state)
        return
    if state.get("approved"):
        st.info("This approval is locked while persistence is retried.")
        if st.button("Retry Record Decision"):
            _save(store, state)
        return
    selected = UnderwritingSelection.parse(state["selected"])
    comparison = validate_comparison_context(store, state["comparison_json"], selected)
    chosen = next(
        item for item in comparison["opportunities"]
        if item["summary"]["ticker"] == selected.ticker
        and item["summary"]["underwriting_version"] == selected.version
    )
    summary = chosen["summary"]
    st.subheader(f"Evaluate Allocation: {state['selected']}")
    st.caption(
        f"Frozen price ${summary['current_price']:.2f} on {summary['market_date']} | "
        f"expected 5Y CAGR {summary['expected_5y_cagr']:.2%} | "
        f"required return {summary['investor_policy']['required_return']:.2%}. "
        "Historical economics are not a current quote or execution instruction."
    )
    with st.expander("Exact comparison and alternative identities"):
        st.json(comparison)
    context = discover_allocation_context(store)
    portfolios = {item.snapshot_id: item for item in context.portfolios}
    policies = {item.content_hash: item for item in context.policies}
    st.caption(
        "Latest is only a default candidate. Portfolio provenance is not classified "
        "as actual, synthetic or test by the existing schema; confirm its intended use."
    )
    portfolio_id = st.selectbox(
        "Portfolio snapshot",
        list(portfolios),
        format_func=lambda key: f"{portfolios[key].as_of_date} | {key}",
        index=0 if portfolios else None,
        key="allocation_portfolio",
    )
    policy_id = st.selectbox(
        "Saved sizing policy",
        list(policies),
        format_func=lambda key: (
            f"{policies[key].created_at} | analysis {policies[key].source_analysis_id}"
        ),
        index=0 if policies else None,
        key="allocation_policy",
    )
    policy_data = None
    if policy_id:
        policy = policies[policy_id]
        policy_data = json.loads(policy.policy_json)
        st.caption(
            f"Policy source analysis {policy.source_analysis_id}; saved "
            f"{policy.created_at}. Policy content hash: {policy.content_hash}"
        )
    else:
        st.info(
            "No saved sizing policy exists. Supply an explicit existing 9C policy "
            "below, or use standalone Portfolio Context / Position Sizing setup."
        )
        raw_policy = st.text_area("Explicit sizing policy JSON (optional)", key="allocation_policy_json")
        if raw_policy.strip():
            try:
                policy_data = load_decision_json(raw_policy)
            except ValueError as exc:
                st.error(f"Invalid policy JSON: {exc}")
    if not portfolio_id:
        st.info(
            "No portfolio snapshot exists. Allocation is unavailable. WATCH/PASS "
            "decisions remain available below; use the existing setup when needed."
        )
    if not portfolios or not policies:
        with st.expander("Existing portfolio and policy setup"):
            from owner_lens.workbench.views import position_sizing

            position_sizing.render(store)
    confirmed = False
    if portfolio_id:
        portfolio = portfolios[portfolio_id]
        age = (datetime.now(UTC).date() - date.fromisoformat(portfolio.as_of_date)).days
        st.warning(
            f"Portfolio as of {portfolio.as_of_date} ({age} calendar days old), "
            f"created {portfolio.created_at}. Latest is not necessarily current. "
            "No live holdings or executions have been verified."
        )
        st.write("Portfolio notes: " + (portfolio.notes or "No provenance notes supplied"))
        with st.expander("Selected portfolio holdings and provenance"):
            st.json(portfolio.to_json())
        confirmed = st.checkbox(
            "I confirm this snapshot's provenance and date are appropriate for this "
            "assessment (not inferred actual holdings).",
            key=f"allocation_confirm.{portfolio_id}",
        )
    report = None
    intended = st.text_input(
        "Intended incremental portfolio weight (optional decimal ratio, e.g. 0.01)",
        key="allocation_intended",
    )
    with st.expander("Optional explicit opportunity exposure context"):
        st.caption(
            "For an unheld company, sector/industry/thesis context is not inferred. "
            "Use the existing 9C JSON shape (sector, industry, exposure_tags); "
            "blank preserves unknowns. For a held company it must match the snapshot."
        )
        raw_context = st.text_area(
            "Opportunity exposure context JSON (optional)", key="allocation_exposure_context"
        )
    if portfolio_id and policy_data is not None and confirmed:
        try:
            report = size_position(
                store, selected, portfolio_id, policy_data,
                proposed_increment=float(intended) if intended.strip() else None,
                context_data=load_decision_json(raw_context) if raw_context.strip() else None,
            )
        except ERRORS as exc:
            st.error(f"Allocation assessment unavailable: {exc}")
        else:
            _assessment(report)
    else:
        st.info("No usable confirmed allocation assessment. No allocation capacity is assumed.")
    st.subheader("Investor decision")
    st.caption(
        "Only references and calculated context are prefilled. You choose the action "
        "and allocation. Recording a decision is not evidence of an executed trade."
    )
    alternatives = [
        f"{item['summary']['ticker']}:{item['summary']['underwriting_version']}"
        for item in comparison["opportunities"]
        if item is not chosen
    ]
    with st.form("allocation_decision." + state["selected"]):
        action = st.selectbox("Action [JUDGMENT]", [item.value for item in DecisionAction], index=None)
        confidence = st.selectbox("Confidence [JUDGMENT]", [item.value for item in Confidence], index=None)
        rationale = st.text_area("Rationale [JUDGMENT]")
        primary = st.text_input("Primary reason [JUDGMENT]")
        risk = st.text_area("Key risk [JUDGMENT]")
        change = st.text_area("Change condition [JUDGMENT]")
        alternative_inputs: list[dict[str, Any]] = []
        for label in alternatives:
            disposition = st.selectbox(
                f"{label}: disposition", [item.value for item in AlternativeDisposition], index=None
            )
            reason = st.text_area(f"{label}: why preferred, deferred or passed over")
            alternative_inputs.append(
                {"underwriting": label, "disposition": disposition, "reason": reason}
            )
        approved = st.form_submit_button("Record Decision")
    if approved:
        if intended.strip() and report is None:
            st.error("Intended allocation requires a usable sizing assessment; clear it for a research decision.")
            return
        judgment = {
            "category": "JUDGMENT", "action": action, "confidence": confidence,
            "rationale": rationale, "primary_reason": primary, "biggest_risk": risk,
            "what_would_change_decision": change, "alternatives": alternative_inputs,
        }
        # Validate judgment before locking the retryable approval.
        try:
            DecisionJudgment.from_data({
                key: value for key, value in judgment.items() if key != "alternatives"
            })
            for alternative in alternative_inputs:
                AlternativeDisposition(alternative["disposition"])
                if not alternative["reason"].strip():
                    raise ValueError("Every alternative requires a reason.")
        except ValueError as exc:
            st.error(f"Decision was not approved: {exc}")
            return
        state["approved"] = {
            "request_id": str(uuid4()), "approved_at": datetime.now(UTC).isoformat(),
            "judgment": judgment, "report": report,
        }
        _save(store, state)

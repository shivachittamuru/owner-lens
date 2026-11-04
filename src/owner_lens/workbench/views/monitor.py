"""Company monitoring: evidence preview, explicit approval and JSON-first handoff."""

from __future__ import annotations

from typing import Any

import streamlit as st

from owner_lens.changes import (
    ChangeClassification,
    ChangeError,
    assess_event,
    change_history,
)
from owner_lens.monitoring_workflow import (
    approve_pending,
    condition_label,
    monitored_projection,
    monitoring_state,
    prepare_review,
    preview_evidence,
    record_review,
    reunderwriting_context,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.underwriting import condition_data
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.underwriting_investment_view import (
    is_analysis_complete,
    select_investment_projection,
)
from owner_lens.workbench.data import CompanyDetail
from owner_lens.workbench.views.underwriting_json import SourceFactory

ERRORS = (ValueError, PersistenceError, OSError)


def _assessment(report: dict[str, Any]) -> None:
    observation = report["event"]["observation"]
    st.markdown("**Observed evidence**")
    st.write(observation["statement"])
    metric = observation["metric"]
    if metric:
        st.write(
            f"{metric['observable'] or 'Observable unavailable'}: "
            f"{metric['value'] if metric['value'] is not None else 'MISSING'} "
            f"{metric['unit'] or 'Unit unavailable'} | cadence: "
            f"{metric['cadence'] or 'MISSING'} | source family: "
            f"{metric.get('source_family') or 'MISSING'}"
        )
    else:
        st.info("No numeric observation supplied.")
    st.caption(
        f"Event/period date: {report['event']['event_date']} | "
        f"observed: {report['event']['observed_at']} | {observation['category']}"
    )
    for reference in observation["references"]:
        st.write(
            "Source: " + " | ".join(
                str(reference[key]) for key in ("title", "uri", "observed_at") if reference.get(key)
            )
        )
    st.caption(
        "Manual verification note: " + (observation["verification_note"] or "Not supplied")
        + ". Pasted metadata is not automatic source verification."
    )
    assessment = report["assessment"]
    condition = assessment["condition"]
    st.markdown("**Frozen thesis condition**")
    if condition:
        st.write(f"{assessment['condition_kind']}: {condition_label(condition)}")
    else:
        st.info("No frozen condition linked; no threshold inferred.")
    st.markdown("**Deterministic assessment (not approval)**")
    st.write("Comparability: " + {
        "CONDITION_MET": "Comparable",
        "CONDITION_BREACHED": "Comparable",
        "NOT_COMPARABLE": "Not comparable",
        "INSUFFICIENT_DATA": "Insufficient data",
    }[assessment["result"]])
    st.write(f"{assessment['result']}: {assessment['reason']}")
    st.write("Candidate classification: " + (assessment["candidate_classification"] or "NOT DETERMINED"))
    st.write("Investor interpretation: " + report["event"]["interpretation"]["text"])
    for belief in report["affected_beliefs"]:
        st.write(f"Affected {belief['kind']}: {belief['pointer']}")
        st.write("Frozen belief:", belief["previous_belief"])
    if not report["affected_beliefs"]:
        st.caption("No affected belief explicitly identified; not assumed unaffected.")
    with st.expander("Full assessment, exact identity and provenance"):
        st.json(report)


def _approval_fields(key: str, button: str) -> tuple[str | None, str, bool]:
    with st.form(key):
        classification = st.selectbox(
            "Investor classification [JUDGMENT]",
            [item.value for item in ChangeClassification],
            index=None, key=key + ".classification",
        )
        rationale = st.text_area("Investor approval rationale [JUDGMENT]", key=key + ".rationale")
        submitted = st.form_submit_button(button, type="primary")
    return classification, rationale, submitted


def _save(store: SqliteStore, state: dict[str, Any]) -> None:
    try:
        report = record_review(store, state["submission"])
    except ERRORS as exc:
        st.error(
            f"Recording/approval did not finish: {exc}. The event may already be "
            "recorded pending approval. Retry uses the same event, never a new one."
        )
    else:
        state["receipt"] = report["event_id"]
        state.pop("submission", None)
        state.pop("preview", None)
        state["entering"] = False
        st.rerun()


def _new_evidence(store: SqliteStore, state: dict[str, Any], key: str, conditions: dict[str, Any]) -> None:
    if state.get("submission"):
        submission = state["submission"]
        st.warning(
            "Approval is locked for retry. Event identity: " + submission["event"]["event_id"]
        )
        existing = next(
            (item for item in store.list_change_events()
             if item.event_id == submission["event"]["event_id"]), None
        )
        if existing is None:
            st.write("Event not yet recorded.")
        elif assess_event(store, existing.event_id)["approval"] is None:
            st.write("Event recorded pending approval.")
        else:
            st.write("Approval already recorded; retry restores its receipt without new records.")
        if st.button("Retry Record & Approve Change", key=key + ".retry"):
            _save(store, state)
        return
    if st.button("Record New Evidence", key=key + ".new", type="primary"):
        state["entering"] = True
        state.pop("receipt", None)
    if not state.get("entering"):
        return
    st.caption(
        "Paste an existing 9D event JSON object. Company and exact underwriting are "
        "already selected. Supply event_date, observed_at, observation, interpretation "
        "and affected_beliefs. FACT requires source metadata and your verification_note. "
        "Do not omit dates, metric definitions, units or sources expecting them to be inferred."
    )
    condition_id = st.selectbox(
        "Frozen dependency / breaker (optional)",
        list(conditions), index=None, key=key + ".condition",
        format_func=lambda value: conditions[value]["statement"],
    )
    raw_key = key + ".raw"
    with st.expander("Secondary: import existing change-event JSON file"):
        upload = st.file_uploader("Change-event JSON file", type=["json"], key=key + ".upload")
        if st.button("Load event file", key=key + ".load", disabled=upload is None) and upload is not None:
            try:
                st.session_state[raw_key] = upload.getvalue().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                st.error(f"Cannot decode event file: {exc}")
            else:
                state.pop("preview", None)
                st.rerun()
    raw = st.text_area("Paste 9D event JSON", key=raw_key, height=260)
    if state.get("preview_input") != (raw, condition_id):
        state.pop("preview", None)
    if st.button("Validate + Preview", key=key + ".validate"):
        try:
            preview = preview_evidence(store, state["record"], raw, condition_id=condition_id)
        except ERRORS as exc:
            state.pop("preview", None)
            st.error(f"Evidence was not validated: {exc}")
        else:
            state["preview"] = preview
            state["preview_input"] = (raw, condition_id)
    if not state.get("preview"):
        return
    _assessment(state["preview"])
    classification, rationale, approved = _approval_fields(
        key + ".approve." + state["preview"]["event_id"], "Record & Approve Change"
    )
    if approved:
        try:
            if classification is None:
                raise ChangeError("Choose an investor classification; candidate is not approval.")
            state["submission"] = prepare_review(store, state["preview"], classification, rationale)
        except ERRORS as exc:
            st.error(f"Change was not approved: {exc}")
        else:
            _save(store, state)


def _render(store: SqliteStore, detail: CompanyDetail, state: dict[str, Any], key: str) -> None:
    ticker = detail.company.ticker
    projection = monitored_projection(store, ticker, state.get("record"))
    record, snapshot = projection.record, projection.snapshot
    assert record is not None and snapshot is not None
    state["record"] = record
    st.subheader(f"Monitor {ticker} v{record.version}")
    st.caption(f"Exact monitored underwriting as of {record.as_of_date}. No automatic version switching.")
    records = store.list_underwriting(ticker)
    latest = records[-1]
    if latest.version > record.version:
        newest = monitored_projection(store, ticker)
        completed_version = newest.record.version if newest.record else record.version
        st.warning(
            f"Newer underwriting v{latest.version} exists"
            + (" but is incomplete; it is not the monitored completed thesis."
               if completed_version < latest.version else
               "; this review remains pinned until you explicitly start a new review.")
        )
        if (
            not state.get("submission") and not state.get("entering")
            and st.button("Start a new review on latest completed underwriting", key=key + ".latest")
        ):
            state.clear()
            state["record"] = newest.record
            st.rerun()
    conditions = {}
    st.markdown("**Current thesis dependencies and breakers**")
    for kind, values, legacy in (
        ("Dependency", snapshot.manual.thesis.monitoring_dependencies, snapshot.manual.thesis.dependencies),
        ("Breaker", snapshot.manual.thesis.monitoring_breakers, snapshot.manual.thesis.breakers),
    ):
        for condition_value in values:
            data = condition_data(condition_value)
            conditions[condition_value.condition_id] = data
            st.write(f"{kind}: {condition_label(data)}")
        if not values:
            for statement in legacy:
                st.write(f"{kind}: {statement} (legacy qualitative condition)")
            if not legacy:
                st.caption(f"No {kind.lower()} conditions recorded.")
    summary = monitoring_state(store, record)
    st.write("Authoritative thesis status: " + summary["status"])
    st.caption(summary["scope"])
    st.caption(
        f"Pending review: {summary['pending_approval']} | "
        f"Pending non-comparable: {summary['pending_non_comparable']} | "
        f"Non-comparable in scope: {summary['non_comparable']}"
    )
    st.write("Re-underwriting required: " + ("YES" if summary["status"] == "REUNDERWRITING_REQUIRED" else "NO"))
    history = change_history(store, ticker)
    recent = [item for item in history if item["event_id"] in summary["included_event_ids"] and item["approval"]]
    if recent:
        st.write("Most recent approved change: " + recent[-1]["approved_classification"])
        for item in recent[-3:]:
            st.write(
                f"{item['event']['event_date']} | {item['approved_classification']}: "
                f"{item['event']['observation']['statement']} | {item['approval']['rationale']}"
            )
    else:
        st.caption("No approved changes in this summary scope.")
    with st.expander("Advanced: monitored identity, predicates and summary"):
        st.json({
            "underwriting_id": record.underwriting_id, "version": record.version,
            "content_hash": record.content_hash, "conditions": conditions, "summary": summary,
        })
    if state.get("receipt"):
        st.success("Change approved. Status above includes the recorded approval; no beliefs or investment records changed.")
        receipt = next(item for item in history if item["event_id"] == state["receipt"])
        st.write(
            f"{receipt['approved_classification']}: {receipt['approval']['rationale']} | "
            f"{receipt['reunderwriting_trigger']}"
        )
    _new_evidence(store, state, key, conditions)
    if summary["status"] == "REUNDERWRITING_REQUIRED":
        if st.button("Prepare Re-underwriting", key=key + ".prepare"):
            state["preparing"] = True
            authoring_key = "underwriting_json." + ticker
            authoring_state = st.session_state.setdefault(authoring_key, {})
            authoring_state.pop("preview", None)
            authoring_state.pop("preview_json", None)
            authoring_state["editing"] = True
            st.rerun()
        if state.get("preparing"):
            st.info(
                "Discuss the approved changes, prepare revised Authoring v2 JSON, then use "
                "the Underwriting tab: Paste JSON -> Validate + Preview -> Commit & Analyze. "
                "No assumptions or probabilities have been revised for you."
            )
            if st.button("Copy Re-underwriting Context", key=key + ".copy"):
                state["export"] = reunderwriting_context(store, record, detail)
            if state.get("export"):
                st.code(state["export"], language="markdown")
    st.subheader("Monitoring timeline")
    if not history:
        st.caption("No change events recorded.")
    for item in reversed(history):
        event, assessment, approval = item["event"], item["assessment"], item["approval"]
        classification = item["approved_classification"] or "PENDING"
        label = f"{event['event_date']} | {classification} | v{item['underwriting']['version']}: {event['observation']['statement']}"
        with st.expander(label):
            st.caption(
                f"Exact underwriting: {item['ticker']} v{item['underwriting']['version']} | "
                f"{assessment['result']} | candidate: {assessment['candidate_classification'] or 'NOT DETERMINED'}"
            )
            _assessment(item)
            st.write("Approval: " + classification)
            st.write("Approval rationale: " + (approval["rationale"] if approval else "PENDING"))
            if approval is None and not state.get("submission"):
                approved_class, reason, submitted = _approval_fields(
                    key + ".pending." + item["event_id"], "Approve Recorded Change"
                )
                if submitted:
                    try:
                        if approved_class is None:
                            raise ChangeError("Select an explicit investor classification.")
                        approve_pending(store, item["event_id"], approved_class, reason)
                    except ERRORS as exc:
                        st.error(f"Approval did not finish: {exc}. The event remains available for retry.")
                    else:
                        state["receipt"] = item["event_id"]
                        st.rerun()


def render(
    detail: CompanyDetail, source_factory: SourceFactory,
    *, underwriting: UnderwritingProjection | None = None,
) -> None:
    key = "monitor." + detail.company.ticker
    state = st.session_state.setdefault(key, {})
    try:
        with source_factory() as source:
            if not isinstance(source.store, SqliteStore):
                raise ChangeError("Monitor requires the existing SQLite evidence store.")
            if not state.get("record"):
                candidate = (
                    underwriting if underwriting is not None and is_analysis_complete(underwriting)
                    else select_investment_projection(source.store, detail.company.ticker)[0]
                )
                if not is_analysis_complete(candidate):
                    st.info("Monitor requires a completed underwriting. Complete or retry analysis in Underwriting.")
                    return
                state["record"] = candidate.record
            _render(source.store, detail, state, key)
    except ERRORS as exc:
        st.error(f"Monitor unavailable: {exc}")

"""Manual What Changed entry, frozen delta review and explicit classification approval."""

from __future__ import annotations

import json
from dataclasses import asdict

import streamlit as st

from owner_lens.changes import (
    ChangeClassification,
    ChangeError,
    approve_event,
    assess_event,
    change_history,
    create_event,
    current_change_state,
    format_assessment,
)
from owner_lens.decisions import load_decision_json
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json
from owner_lens.underwriting import UnderwritingSnapshot
from owner_lens.underwriting_authoring import authoring_from_manual
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.workbench.views import underwriting_authoring
from owner_lens.workbench.views._common import frame


def render(
    store: SqliteStore, source_factory: underwriting_authoring.SourceFactory
) -> None:
    st.title("What Changed?")
    st.caption(
        "Manual evidence and explicit investor approval. Threshold candidates are not "
        "approved thesis changes. No retrieval, automatic assumption/probability changes or trades."
    )
    selections = {}
    for security in store.list_securities():
        for record in store.list_underwriting(security.symbol):
            selections[f"{record.ticker}:{record.version}"] = record
    selected = st.selectbox(
        "Exact underwriting version",
        list(selections),
        index=None,
        key="changes_version",
    )
    if not selected:
        st.info("Select an exact completed underwriting version to record evidence.")
        return
    record = selections[selected]
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    conditions = {
        item.condition_id: item
        for item in (
            *snapshot.manual.thesis.monitoring_dependencies,
            *snapshot.manual.thesis.monitoring_breakers,
        )
    }
    condition_id = st.selectbox(
        "Link dependency / breaker (optional)",
        list(conditions),
        index=None,
        key="changes_condition",
    )
    if condition_id:
        st.json(json.loads(canonical_json(asdict(conditions[condition_id]))))
    st.caption(
        "Import event JSON by pasting its complete contents. Required: event_date, observed_at, "
        "observation (category, statement, references; optional metric/verification_note), "
        "interpretation (JUDGMENT), affected_beliefs (exact snapshot JSON pointers). "
        "FACT requires manual verification and source metadata. Existing qualitative thresholds "
        "remain NOT_COMPARABLE; no units or definitions are guessed."
    )
    with st.form("changes_create"):
        event_input = st.text_area("Change event JSON", key="changes_input")
        submitted = st.form_submit_button("Record pending change event")
    if submitted:
        try:
            data = load_decision_json(event_input)
            if not isinstance(data, dict):
                raise ChangeError("Change event JSON must be an object.")
            if condition_id is not None:
                if data.get("condition_id") not in (None, condition_id):
                    raise ChangeError(
                        "Imported condition_id conflicts with selected dependency/breaker."
                    )
                data["condition_id"] = condition_id
            event = create_event(
                store, UnderwritingSelection(record.ticker, record.version), data
            )
            st.session_state["changes_event"] = event["event_id"]
            st.success(
                f"Recorded pending event {event['event_id']}; investor approval still required."
            )
        except (ValueError, PersistenceError, OSError) as exc:
            st.error(f"Event was not recorded: {exc}")
    st.subheader("Company current-state summary")
    summary = current_change_state(store, record.ticker)
    st.write(
        f"Latest underwriting: {record.ticker} v{summary['latest_underwriting']['version']}"
    )
    st.write("Status: " + summary["status"])
    st.dataframe(
        frame(
            [
                {"Classification": key, "Count": value}
                for key, value in summary["since_underwriting"].items()
            ]
        ),
        width="stretch",
    )
    st.caption(
        f"Pending approval: {summary['pending_approval']}. "
        f"Pending non-comparable assessment: {summary['pending_non_comparable']}. {summary['scope']}"
    )
    with st.expander("Latest decision and historical sizing context"):
        st.json(summary)
    history = change_history(store, record.ticker)
    event_id = st.selectbox(
        "Recorded event",
        [item["event_id"] for item in history],
        index=None,
        key="changes_event",
    )
    if not event_id:
        return
    report = assess_event(store, event_id)
    st.text(format_assessment(report))
    with st.expander(
        "Frozen delta: affected assumptions, probabilities, thesis and context"
    ):
        st.json(json.loads(canonical_json(report)))
    st.download_button(
        "Download change assessment JSON",
        canonical_json(report),
        file_name=f"change-{event_id}.json",
        mime="application/json",
    )
    if report["approval"] is None:
        with st.form("changes_approve." + event_id):
            classification = st.selectbox(
                "Approved classification [JUDGMENT]",
                [item.value for item in ChangeClassification],
                index=None,
                key="changes_classification." + event_id,
            )
            rationale = st.text_area(
                "Approval / override rationale [JUDGMENT]",
                key="changes_rationale." + event_id,
            )
            approve = st.form_submit_button("Explicitly approve classification")
        if approve:
            try:
                if classification is None:
                    raise ChangeError(
                        "Select an explicit classification; candidate is not approval."
                    )
                approve_event(store, event_id, classification, rationale)
            except (ValueError, PersistenceError) as exc:
                st.error(f"Approval was not saved: {exc}")
            else:
                st.rerun()
    else:
        st.success(
            f"Approved {report['approved_classification']} / {report['reunderwriting_trigger']}"
        )
    if report["reunderwriting_trigger"] == "NEW_UNDERWRITING_REQUIRED":
        latest = project_underwriting(store, record.ticker)
        if latest.snapshot is not None and st.button(
            "Start from latest underwriting", key="changes_start_latest"
        ):
            key = "authoring." + record.ticker
            generation = 1 + int(st.session_state.get(key + ".generation", 0))
            st.session_state[key] = {
                "seed": authoring_from_manual(latest.snapshot.manual),
                "id": generation,
            }
            st.session_state[key + ".generation"] = generation
            st.session_state["changes_draft_ticker"] = record.ticker
            st.info(
                f"Draft initialized from {record.ticker} v{latest.record.version if latest.record else '?'}; nothing saved."
            )
    if st.session_state.get("changes_draft_ticker") == record.ticker:
        st.subheader("Re-underwriting draft [Explicit save only]")
        underwriting_authoring.render(
            record.ticker, project_underwriting(store, record.ticker), source_factory
        )

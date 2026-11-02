"""Explicit investor decision creation and separate immutable history/shadow tables."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from owner_lens.decisions import (
    DISCLAIMER,
    AlternativeDisposition,
    Confidence,
    DecisionAction,
    DecisionError,
    ShadowEntry,
    ShadowRole,
    create_decision,
    format_decision,
    read_decision,
)
from owner_lens.opportunity_comparison import (
    ComparisonError,
    UnderwritingSelection,
    load_opportunity,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.workbench.views._common import frame


def render(store: SqliteStore) -> None:
    st.title("Decisions")
    st.caption(DISCLAIMER)
    comparison_json = st.session_state.get("decision_comparison_json")
    comparison = json.loads(comparison_json) if comparison_json else None
    options: dict[str, UnderwritingSelection] = {}
    if comparison:
        for item in comparison["opportunities"]:
            summary = item["summary"]
            selection = UnderwritingSelection(
                summary["ticker"], summary["underwriting_version"]
            )
            options[f"{selection.ticker}:{selection.version}"] = selection
        st.info(
            "This decision will freeze the exact Opportunity Comparison. Record reasons for every other compared version."
        )
        if st.button("Discard comparison context"):
            del st.session_state["decision_comparison_json"]
            st.session_state.pop("decision_selected_underwriting", None)
            st.rerun()
    else:
        for security in store.list_securities():
            for record in store.list_underwriting(security.symbol):
                options[f"{record.ticker}:{record.version}"] = UnderwritingSelection(
                    record.ticker, record.version
                )
    requested = st.session_state.pop("decision_requested_underwriting", None)
    if requested in options:
        st.session_state["decision_selected_underwriting"] = requested
    selected = st.selectbox(
        "Exact underwriting version",
        list(options),
        index=None,
        key="decision_selected_underwriting",
    )
    if selected:
        try:
            opportunity = load_opportunity(store, options[selected])
        except ComparisonError as exc:
            st.error(f"This version is not completed/eligible: {exc}")
        else:
            summary = opportunity.summary
            st.caption(
                f"DECISION_STATE source: {selected} | frozen price FACT "
                f"${summary.current_price:.2f} on {summary.market_date} | "
                f"saved hurdle JUDGMENT {summary.investor_policy.required_return:.2%}. "
                "Not a current quote or execution price."
            )
            candidates = [label for label in options if label != selected]
            alternatives = (
                candidates
                if comparison
                else st.multiselect(
                    "Alternatives considered (exact versions)",
                    candidates,
                    key=f"decision_alternatives.{selected}",
                )
            )
            _create_form(store, options[selected], alternatives, comparison)
    else:
        st.info(
            "Select an exact completed underwriting version. Nothing defaults to latest."
        )
    st.divider()
    _history(store, options[selected].ticker if selected else None)


def _create_form(
    store: SqliteStore,
    selected: UnderwritingSelection,
    alternatives: list[str],
    comparison: dict[str, Any] | None,
) -> None:
    label = f"{selected.ticker}:{selected.version}"
    prefix = "decision_form." + label + "." + ",".join(alternatives)
    with st.form(prefix):
        action = st.selectbox(
            "Action [JUDGMENT]", [item.value for item in DecisionAction], index=None
        )
        confidence = st.selectbox(
            "Confidence [JUDGMENT]", [item.value for item in Confidence], index=None
        )
        rationale = st.text_area("Rationale [JUDGMENT]")
        primary = st.text_input("Primary reason [JUDGMENT]")
        risk = st.text_area("Biggest risk [JUDGMENT]")
        change = st.text_area("What would change the decision [JUDGMENT]")
        decision_at = st.text_input(
            "Decision timestamp (optional ISO with timezone; blank = save time)"
        )
        as_of = st.text_input(
            "As-of date (optional YYYY-MM-DD; blank = decision UTC date)"
        )
        alternative_inputs = []
        shadow_inputs = []
        for alternative in alternatives:
            st.subheader(alternative)
            disposition = st.selectbox(
                f"{alternative}: disposition",
                [item.value for item in AlternativeDisposition],
                index=None,
            )
            reason = st.text_area(
                f"{alternative}: why preferred, deferred or passed over"
            )
            role = st.selectbox(
                f"{alternative}: optional shadow role",
                [
                    "NOT_TRACKED",
                    ShadowRole.BEST_ALTERNATIVE.value,
                    ShadowRole.PASS_CANDIDATE.value,
                ],
            )
            alternative_inputs.append(
                {
                    "underwriting": alternative,
                    "disposition": disposition,
                    "reason": reason,
                }
            )
            if role != "NOT_TRACKED":
                shadow_inputs.append({"underwriting": alternative, "role": role})
        shadow_requested = st.checkbox(
            "Create independent hypothetical $100 shadow entries", value=False
        )
        benchmark = st.checkbox(
            "Include S&P 500 benchmark placeholder (no price)", value=True
        )
        st.caption(
            "Shadow ACTUAL_CHOICE means the opportunity associated with your recorded "
            "decision, including WATCH/PASS; it does not assert a trade. No outcomes are observed."
        )
        save = st.form_submit_button("Save new immutable decision")
    if save:
        try:
            if shadow_inputs and not shadow_requested:
                raise DecisionError(
                    "Enable shadow creation or set alternative shadow roles to NOT_TRACKED."
                )
            data: dict[str, Any] = {
                "category": "JUDGMENT",
                "action": action,
                "confidence": confidence,
                "rationale": rationale,
                "primary_reason": primary,
                "biggest_risk": risk,
                "what_would_change_decision": change,
                "alternatives": alternative_inputs,
                "comparison": comparison,
                "shadow": {
                    "alternatives": shadow_inputs,
                    "include_benchmark": benchmark,
                }
                if shadow_requested
                else None,
            }
            if decision_at.strip():
                data["decision_at"] = decision_at
            if as_of.strip():
                data["as_of_date"] = as_of
            snapshot = create_decision(store, selected, data)
        except (DecisionError, ComparisonError, PersistenceError) as exc:
            st.error(f"Decision was not saved: {exc}")
        else:
            st.success(
                f"Created immutable decision {snapshot.decision_id}. Underwriting was not changed."
            )


def _history(store: SqliteStore, ticker: str | None) -> None:
    st.subheader("Decision history [Read-only]")
    records = store.list_decisions(ticker)
    if not records:
        st.info("No decisions recorded.")
        return
    snapshots = [read_decision(record) for record in records]
    st.dataframe(
        frame(
            [
                {
                    "Decision date": item.decision_at,
                    "Ticker": item.chosen.underwriting.ticker,
                    "Underwriting version": item.chosen.underwriting.version,
                    "Action": item.judgment.action.value,
                    "Decision ID": item.decision_id,
                    "Recorded at": item.recorded_at,
                }
                for item in snapshots
            ]
        ),
        width="stretch",
    )
    for snapshot in snapshots:
        with st.expander(
            f"{snapshot.decision_at} {snapshot.judgment.action} {snapshot.chosen.label}"
        ):
            st.text(format_decision(snapshot))
            st.download_button(
                "Download frozen decision JSON",
                snapshot.to_json(),
                file_name=f"decision-{snapshot.decision_id}.json",
                mime="application/json",
                key="decision_download." + snapshot.decision_id,
            )


def render_shadow(store: SqliteStore) -> None:
    st.title("Shadow Portfolio")
    st.caption(DISCLAIMER)
    entries = [
        ShadowEntry.from_data(json.loads(record.snapshot_json))
        for record in store.list_shadow_entries()
    ]
    if not entries:
        st.info(
            "No shadow entries recorded. Explicitly enable shadow creation when saving a decision."
        )
        return
    st.dataframe(
        frame(
            [
                {
                    "Decision date": entry.decision_at,
                    "Ticker": entry.ticker,
                    "Role": entry.role.value,
                    "Frozen price": f"${entry.frozen_price:.2f}"
                    if entry.frozen_price is not None
                    else "MISSING (benchmark placeholder)",
                    "Market date": entry.market_date or "MISSING",
                    "Underwriting version": str(entry.underwriting_version)
                    if entry.underwriting_version
                    else "N/A (benchmark)",
                    "Decision/action": f"{entry.decision_id} / {entry.action}",
                    "Basis": entry.basis,
                    "Observation state": entry.state + " / " + entry.outcome_state,
                }
                for entry in entries
            ]
        ),
        width="stretch",
    )
    st.download_button(
        "Download shadow starts JSON",
        "[" + ",".join(entry.to_json() for entry in entries) + "]",
        file_name="shadow-starts.json",
        mime="application/json",
    )

"""Explicit investor approval of immutable, evidence-gated post-mortems."""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from owner_lens.decisions import load_decision_json
from owner_lens.mistakes import (
    DISCLAIMER,
    TAXONOMY,
    create_review,
    review_history,
    review_summary,
    suggest_review,
)
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json
from owner_lens.workbench.views._common import frame


def render(store: SqliteStore) -> None:
    st.title("Mistake Review")
    st.caption(DISCLAIMER)
    with st.expander("Descriptive approved-review summary"):
        st.json(review_summary(store))
    selections = {
        f"{record.ticker}:{record.version}": UnderwritingSelection(
            record.ticker, record.version
        )
        for security in store.list_securities()
        for record in store.list_underwriting(security.symbol)
    }
    selected = st.selectbox(
        "Exact underwriting version",
        list(selections),
        index=None,
        key="mistakes_version",
    )
    if not selected:
        st.info(
            "Select an exact completed version. No review or label is written automatically."
        )
        return
    selection = selections[selected]
    day = st.date_input(
        "Review date (UTC)", value=datetime.now(UTC).date(), key="mistakes_date"
    )
    try:
        base = suggest_review(store, selection, review_date=day.isoformat())
        uid = base["context"]["forecast"]["underwriting_id"]
        decision_ids = [
            item.decision_id
            for item in store.list_decisions()
            if item.underwriting_id == uid
        ]
        sizing_ids = [
            item.analysis_id
            for item in store.list_sizing_analyses()
            if item.underwriting_id == uid
        ]
        decision_id = st.selectbox(
            "Exact decision (optional)",
            decision_ids,
            index=None,
            key="mistakes_decision",
        )
        sizing_id = st.selectbox(
            "Exact sizing analysis (optional)",
            sizing_ids,
            index=None,
            key="mistakes_sizing",
        )
        observation_ids = st.multiselect(
            "Linked outcome observations",
            base["links"]["observation_ids"],
            key="mistakes_outcomes",
        )
        event_ids = st.multiselect(
            "Linked change events",
            base["links"]["change_event_ids"],
            key="mistakes_events",
        )
        calibration_id = st.text_input(
            "Exact calibration report ID (optional)", key="mistakes_calibration"
        )
        links = {
            "decision_id": decision_id,
            "sizing_analysis_id": sizing_id,
            "observation_ids": observation_ids,
            "change_event_ids": event_ids,
            "calibration_report_id": calibration_id.strip() or None,
        }
        suggestion = suggest_review(
            store, selection, links=links, review_date=day.isoformat()
        )
        st.write("Evidence state: " + suggestion["evidence_state"])
        st.json(suggestion["quality"])
        st.subheader("Process questions, not mistake conclusions")
        st.dataframe(
            frame(suggestion["process_checks"]), width="stretch", hide_index=True
        )
        st.subheader("Machine candidates (not approved)")
        st.json(suggestion["candidate_labels"])
        with st.expander("Exact linked records and copied evidence"):
            st.json(suggestion["context"])
        st.caption(
            "Select labels yourself, provide a rationale and evidence for each, then explicitly approve. "
            "Behavioral labels are investor judgments only. An empty label list is valid."
        )
        with st.form("mistakes_create"):
            codes = st.multiselect(
                "Labels to approve (no defaults)", list(TAXONOMY), key="mistakes_codes"
            )
            reviewer = st.text_input("Reviewer", key="mistakes_reviewer")
            rationale = st.text_area("Review rationale", key="mistakes_rationale")
            confidence = st.selectbox(
                "Review confidence",
                ("LOW", "MEDIUM", "HIGH"),
                key="mistakes_confidence",
            )
            unresolved = st.text_area(
                "Unresolved questions (one per line)", key="mistakes_unresolved"
            )
            primary = st.text_input(
                "Optional primary mistake code", key="mistakes_primary"
            )
            label_json = st.text_area(
                "Per-label approval JSON array (code, confidence, rationale, evidence_references, investor_approved)",
                value="[]",
                key="mistakes_label_json",
            )
            evidence_json = st.text_area(
                "Review evidence references JSON array", value="[]", key="mistakes_refs"
            )
            approval = st.checkbox(
                "I explicitly approve these labels and this immutable review.",
                key="mistakes_approve",
            )
            submitted = st.form_submit_button("Append investor-approved review")
        if submitted:
            try:
                if not approval:
                    raise ValueError(
                        "Explicit investor approval is required; no review saved."
                    )
                labels = load_decision_json(label_json)
                if (
                    not isinstance(labels, list)
                    or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get("code"), str)
                        for item in labels
                    )
                    or set(codes) != {item["code"] for item in labels}
                ):
                    raise ValueError(
                        "Selected labels must exactly match the per-label approval JSON."
                    )
                data = {
                    "review_date": day.isoformat(),
                    "category": "JUDGMENT",
                    "reviewer": reviewer,
                    "rationale": rationale,
                    "confidence": confidence,
                    "links": links,
                    "approved_labels": labels,
                    "primary_mistake": primary.strip() or None,
                    "evidence_references": load_decision_json(evidence_json),
                    "unresolved_questions": [
                        line.strip() for line in unresolved.splitlines() if line.strip()
                    ],
                }
                review = create_review(store, selection, data)
                st.success("Recorded immutable review " + review["review_id"])
            except (ValueError, PersistenceError, OverflowError) as exc:
                st.error(f"Review was not recorded: {exc}")
        st.subheader("Immutable review history")
        for review in review_history(store, selection.ticker):
            if review["underwriting"]["underwriting_id"] == uid:
                with st.expander(f"{review['review_date']} | {review['review_id']}"):
                    st.json(review)
                    st.download_button(
                        "Download review JSON",
                        canonical_json(review),
                        file_name=f"mistake-review-{review['review_id']}.json",
                        key=review["review_id"],
                    )
    except (ValueError, PersistenceError, OverflowError) as exc:
        st.error(f"Mistake review could not be loaded: {exc}")

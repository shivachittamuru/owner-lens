"""Offline explicit investor-reviewed attribution, with no automatic writes."""

from __future__ import annotations

import streamlit as st

from owner_lens.attribution import (
    DISCLAIMER,
    create_review,
    review_history,
    review_summary,
)
from owner_lens.decisions import load_decision_json
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json


def render(store: SqliteStore) -> None:
    st.title("Attribution")
    st.caption(DISCLAIMER)
    with st.expander("Descriptive cross-case summary"):
        st.json(review_summary(store))
    selections = {
        f"{item.ticker}:{item.version}": UnderwritingSelection(
            item.ticker, item.version
        )
        for security in store.list_securities()
        for item in store.list_underwriting(security.symbol)
    }
    selected = st.selectbox(
        "Exact underwriting version",
        list(selections),
        index=None,
        key="attribution_version",
    )
    if not selected:
        st.info(
            "Select an exact completed version. Unresolved layers do not prevent an explicit review."
        )
        return
    st.caption(
        "Paste review JSON or import a file. Links are exact; market outcomes and shadow records never imply execution."
    )
    with st.form("attribution_create"):
        text = st.text_area("Attribution review JSON", key="attribution_input")
        uploaded = st.file_uploader(
            "Import attribution JSON", type=["json"], key="attribution_upload"
        )
        approved = st.checkbox(
            "I reviewed the interpretation, external contributors and evidence.",
            key="attribution_approve",
        )
        submitted = st.form_submit_button("Append immutable attribution review")
    if submitted:
        try:
            if not approved:
                raise ValueError(
                    "Explicit investor review is required; nothing was saved."
                )
            if uploaded is not None and text.strip():
                raise ValueError("Use either pasted JSON or file import, not both.")
            payload = uploaded.getvalue().decode("utf-8-sig") if uploaded else text
            review = create_review(
                store, selections[selected], load_decision_json(payload)
            )
            st.success("Recorded attribution " + review["review_id"])
        except (ValueError, PersistenceError, UnicodeError, OverflowError) as exc:
            st.error(f"Attribution was not recorded: {exc}")
    try:
        selection = selections[selected]
        records = store.list_underwriting(selection.ticker)
        uid = next(
            item.underwriting_id
            for item in records
            if item.version == selection.version
        )
        st.subheader("Exact-version attribution history")
        for review in review_history(store, selection.ticker):
            if review["underwriting"]["underwriting_id"] != uid:
                continue
            with st.expander(f"{review['as_of_date']} | {review['review_id']}"):
                st.json(review["summary"])
                for title, key in (
                    (
                        "Linked underwriting, decision, sizing, outcomes and mistake review",
                        "context",
                    ),
                    ("Process attribution", "process"),
                    ("Forecast attribution", "forecast"),
                    ("Decision consistency", "decision"),
                    ("Portfolio and sizing contribution", "portfolio"),
                    ("External contributors (investor judgment)", "external"),
                    (
                        "Benchmark and recorded shadow relative outcomes",
                        "relative_outcomes",
                    ),
                    ("Interpretation and unresolved areas", "judgment"),
                ):
                    st.subheader(title)
                    st.json(review[key])
                st.download_button(
                    "Download attribution JSON",
                    canonical_json(review),
                    file_name=f"attribution-{review['review_id']}.json",
                    key=review["review_id"],
                )
    except (ValueError, PersistenceError) as exc:
        st.error(f"Attribution history could not be loaded: {exc}")

"""Read-only comparison of explicitly selected completed immutable versions."""

from __future__ import annotations

import streamlit as st

from owner_lens.opportunity_comparison import (
    ComparisonError,
    UnderwritingSelection,
    compare_underwritings,
    comparison_rows,
    load_opportunity,
)
from owner_lens.persistence import SqliteStore
from owner_lens.workbench.views._common import frame


def render(store: SqliteStore) -> None:
    st.title("Opportunity Comparison")
    st.caption(
        "Select 2-5 completed immutable underwriting versions, including multiple "
        "versions of the same company. No current prices, latest-version substitution, "
        "editable beliefs or aggregate score."
    )
    options: dict[str, UnderwritingSelection] = {}
    excluded = []
    seen = set()
    for security in store.list_securities():
        for record in store.list_underwriting(security.symbol):
            if record.underwriting_id in seen:
                continue
            seen.add(record.underwriting_id)
            selection = UnderwritingSelection(record.ticker, record.version)
            label = f"{selection.ticker}:{selection.version}"
            try:
                load_opportunity(store, selection)
            except ComparisonError as exc:
                excluded.append(f"{label}: {exc}")
            else:
                options[label] = selection
    if excluded:
        with st.expander("Excluded incomplete or invalid versions"):
            for reason in excluded:
                st.warning(reason)
    selected = st.multiselect(
        "Completed underwriting versions (2-5)",
        options=list(options),
        max_selections=5,
        key="opportunity_versions",
    )
    if len(selected) < 2:
        st.info("Select at least 2 completed underwriting versions to compare.")
        return
    report = compare_underwritings(store, tuple(options[label] for label in selected))
    rows = comparison_rows(report)
    long_metrics = {
        "Unresolved challenger questions",
        "Missing dimensions",
        "Immutable identity",
    }
    st.dataframe(
        frame(
            [row for row in rows if row["Metric"] not in long_metrics], index="Metric"
        ),
        width="stretch",
    )
    st.caption(report.disclaimer)
    for pair in report.pairs:
        st.subheader(f"{pair.left} vs {pair.right}: {pair.conclusion}")
        st.write(pair.key_tradeoff)
        st.write("Capital attractiveness: " + pair.capital_attractiveness)
    for opportunity in report.opportunities:
        with st.expander(
            f"{opportunity.label}: research attention and unresolved issues"
        ):
            for reason in opportunity.research_attention:
                st.write(reason)
            st.write("Biggest uncertainty: " + opportunity.unresolved_issue)
            for question in opportunity.quality.major_unresolved_questions:
                st.write(question)
            for missing in opportunity.quality.missing_dimensions:
                st.write("MISSING: " + missing)
            st.write(
                f"Immutable identity: {opportunity.summary.underwriting_id} / "
                f"{opportunity.summary.underwriting_content_hash}"
            )
    st.download_button(
        "Download reproducible comparison JSON",
        data=report.to_json(),
        file_name="opportunity-comparison.json",
        mime="application/json",
    )

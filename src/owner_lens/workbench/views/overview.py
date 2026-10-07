"""Overview view: the current opportunity funnel and research queue (Feature 7D)."""

from __future__ import annotations

import streamlit as st

from owner_lens.screening import BUCKET_ORDER, CoverageClass, ScreeningResult, SetupType
from owner_lens.workbench.data import (
    NOT_AVAILABLE,
    OverviewCounts,
    PersistedCompany,
    main_limiting_reason,
    research_queue,
    strongest_reason,
)
from owner_lens.workbench.views._common import (
    BUCKET_LABEL,
    COVERAGE_LABEL,
    SETUP_LABEL,
    frame,
    metric_row,
)

__all__ = ["render"]


def render(
    companies: tuple[PersistedCompany, ...],
    results: tuple[ScreeningResult, ...],
    counts: OverviewCounts,
) -> None:
    """Render the landing page from counts the data layer derived dynamically."""
    st.title("Overview")
    st.caption(
        "Research priority derived from persisted filings. Nothing here is "
        "investment advice, and no price or valuation input is involved."
    )

    _universe(counts)
    st.divider()
    _funnel(counts)
    st.divider()
    _queue(results)

    missing = [company for company in companies if not company.available]
    if missing:
        st.divider()
        st.subheader("Tracked but not screenable")
        st.caption(
            "These companies are in the store without a readable raw snapshot, so "
            "nothing can be derived for them. They are listed rather than dropped."
        )
        st.dataframe(
            frame(
                [
                    {"Ticker": c.ticker, "Company": c.company_name, "CIK": c.cik}
                    for c in missing
                ],
                index="Ticker",
            ),
            width="stretch",
        )


def _universe(counts: OverviewCounts) -> None:
    st.subheader("Universe")
    metric_row(
        [
            ("Companies tracked", counts.tracked, "Every company in the active store."),
            (
                "FULL coverage",
                counts.by_coverage.get(CoverageClass.FULL, 0),
                "Every analytical layer available.",
            ),
            (
                "PARTIAL coverage",
                counts.by_coverage.get(CoverageClass.PARTIAL, 0),
                "Owner economics available, at least one other layer blocked.",
            ),
            (
                "FAILED coverage",
                counts.by_coverage.get(CoverageClass.FAILED, 0),
                "Owner economics itself is unusable; the company cannot be screened.",
            ),
        ]
    )
    metric_row(
        [
            (BUCKET_LABEL[bucket], counts.by_bucket.get(bucket, 0), None)
            for bucket in BUCKET_ORDER
        ]
    )
    compounders = counts.by_setup.get(SetupType.COMPOUNDER, 0)
    asymmetric = counts.by_setup.get(SetupType.POTENTIAL_ASYMMETRIC_SETUP, 0)
    st.caption(
        f"Setup types: {compounders} {SETUP_LABEL[SetupType.COMPOUNDER]}, "
        f"{asymmetric} {SETUP_LABEL[SetupType.POTENTIAL_ASYMMETRIC_SETUP]}, "
        f"{counts.by_setup.get(SetupType.NEITHER, 0)} {SETUP_LABEL[SetupType.NEITHER]}."
    )


def _funnel(counts: OverviewCounts) -> None:
    st.subheader("Opportunity funnel")
    stages = counts.funnel
    widest = max((count for _, count in stages), default=0)
    for index, (label, count) in enumerate(stages):
        share = count / widest if widest else 0.0
        st.markdown(f"**{label}** — {count}")
        st.progress(share)
        if index < len(stages) - 1:
            st.caption("↓")
    st.caption(
        "Screenable excludes companies whose coverage cannot support any verdict. "
        "Counts are derived from the active store on every load."
    )


def _queue(results: tuple[ScreeningResult, ...]) -> None:
    st.subheader("Research queue")
    queue = research_queue(results)
    if not queue:
        st.info(
            "No company currently reaches HIGH_PRIORITY or WORTH_UNDERWRITING in "
            "this store."
        )
        return

    st.dataframe(
        frame(
            [
                {
                    "Ticker": result.ticker,
                    "Priority": BUCKET_LABEL[result.bucket],
                    "Setup": SETUP_LABEL[result.setup_type],
                    "Score": result.screening_score,
                    "Coverage": COVERAGE_LABEL[result.coverage_class],
                    "Strongest reason": strongest_reason(result) or NOT_AVAILABLE,
                    "Main limitation": main_limiting_reason(result) or NOT_AVAILABLE,
                }
                for result in queue
            ],
            index="Ticker",
        ),
        width="stretch",
    )

    selected = st.selectbox(
        "Open a company",
        options=[result.ticker for result in queue],
        key="overview_open_ticker",
    )
    if st.button("Go to Company view", key="overview_open_button"):
        st.session_state["selected_ticker"] = selected
        st.session_state["requested_page"] = "Company"
        st.rerun()

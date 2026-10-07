"""Screener view: the interactive table over the Feature 7 universe (Feature 7D)."""

from __future__ import annotations

import streamlit as st

from owner_lens.screening import (
    BUCKET_ORDER,
    DIMENSION_ORDER,
    CoverageClass,
    DimensionBand,
    LimitingFactor,
    ScreeningResult,
    SetupType,
)
from owner_lens.workbench.data import (
    BAND_LABEL,
    DIMENSION_LABEL,
    limiting_factor_label,
)
from owner_lens.workbench.views._common import (
    BUCKET_LABEL,
    COVERAGE_LABEL,
    SETUP_LABEL,
    frame,
    reason_lists,
)

__all__ = ["render"]

_SORTS = {
    "Ranking (bucket, coverage, score)": None,
    "Screening score": lambda r: (-r.screening_score, r.ticker),
    "Ticker": lambda r: r.ticker,
}


def render(results: tuple[ScreeningResult, ...]) -> None:
    """Render the filterable screener. Bands and order come from Feature 7."""
    st.title("Screener")
    st.caption(
        "Every band, bucket, and reason is read from the deterministic engine. "
        "The default order is the Feature 7 ranking: bucket, then coverage "
        "class, then score, then ticker."
    )
    if not results:
        st.warning("No company in the active store can be screened.")
        return

    filtered = _filters(results)
    st.caption(f"{len(filtered)} of {len(results)} companies match.")
    if not filtered:
        st.info("No company matches the current filters.")
        return

    st.dataframe(_table(filtered), width="stretch")
    _detail(filtered)


def _filters(results: tuple[ScreeningResult, ...]) -> list[ScreeningResult]:
    with st.expander("Filters", expanded=True):
        top, bottom = st.columns(2), st.columns(2)
        buckets = top[0].multiselect(
            "Priority bucket",
            options=[BUCKET_LABEL[b] for b in BUCKET_ORDER],
            default=[],
            key="screener_buckets",
        )
        setups = top[1].multiselect(
            "Setup type",
            options=[SETUP_LABEL[s] for s in SetupType],
            default=[],
            key="screener_setups",
        )
        coverages = bottom[0].multiselect(
            "Coverage class",
            options=[COVERAGE_LABEL[c] for c in CoverageClass],
            default=[],
            key="screener_coverage",
        )
        factors = bottom[1].multiselect(
            "Limiting factor",
            options=[limiting_factor_label(f) for f in LimitingFactor],
            default=[],
            key="screener_limiting",
        )

        dimension_columns = st.columns(2)
        dimension = dimension_columns[0].selectbox(
            "Dimension",
            options=[DIMENSION_LABEL[d] for d in DIMENSION_ORDER],
            key="screener_dimension",
        )
        bands = dimension_columns[1].multiselect(
            "Band for that dimension",
            options=[BAND_LABEL[b] for b in DimensionBand],
            default=[],
            key="screener_bands",
        )
        sort_label = st.selectbox(
            "Sort by", options=list(_SORTS), key="screener_sort"
        )

    selected_dimension = next(
        d for d in DIMENSION_ORDER if DIMENSION_LABEL[d] == dimension
    )
    matches = [
        result
        for result in results
        if (not buckets or BUCKET_LABEL[result.bucket] in buckets)
        and (not setups or SETUP_LABEL[result.setup_type] in setups)
        and (not coverages or COVERAGE_LABEL[result.coverage_class] in coverages)
        and (
            not factors
            or limiting_factor_label(result.limiting_factor) in factors
        )
        and (not bands or BAND_LABEL[result.band(selected_dimension)] in bands)
    ]

    key = _SORTS[sort_label]
    if key is None:
        return sorted(matches, key=lambda r: r.rank_key)
    return sorted(matches, key=key)


def _table(results: list[ScreeningResult]):  # type: ignore[no-untyped-def]
    rows = []
    for result in results:
        row = {
            "Ticker": result.ticker,
            "Priority": BUCKET_LABEL[result.bucket],
            "Setup": SETUP_LABEL[result.setup_type],
            "Coverage": COVERAGE_LABEL[result.coverage_class],
            "Score": result.screening_score,
        }
        for dimension in DIMENSION_ORDER:
            row[DIMENSION_LABEL[dimension]] = BAND_LABEL[result.band(dimension)]
        row["Limiting factor"] = limiting_factor_label(result.limiting_factor)
        rows.append(row)
    return frame(rows, index="Ticker")


def _detail(results: list[ScreeningResult]) -> None:
    st.subheader("Why a company ranks where it does")
    ticker = st.selectbox(
        "Company", options=[r.ticker for r in results], key="screener_detail_ticker"
    )
    result = next(r for r in results if r.ticker == ticker)

    header = st.columns(4)
    header[0].metric("Priority", BUCKET_LABEL[result.bucket])
    header[1].metric("Setup", SETUP_LABEL[result.setup_type])
    header[2].metric("Coverage", COVERAGE_LABEL[result.coverage_class])
    header[3].metric(
        "Score",
        result.screening_score,
        help="Orders companies within a bucket; it never sets the bucket.",
    )
    reason_lists(result)

    with st.expander("Dimension evidence"):
        st.dataframe(
            frame(
                [
                    {
                        "Dimension": DIMENSION_LABEL[dimension],
                        "Band": BAND_LABEL[result.band(dimension)],
                        "Evidence": " · ".join(result.dimensions[dimension].evidence)
                        or "—",
                    }
                    for dimension in DIMENSION_ORDER
                ],
                index="Dimension",
            ),
            width="stretch",
        )

    if st.button("Open in Company view", key="screener_open_button"):
        st.session_state["selected_ticker"] = ticker
        st.session_state["requested_page"] = "Company"
        st.rerun()

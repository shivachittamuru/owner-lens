"""Screener view: the interactive table over the Feature 7 universe (Feature 7D)."""

from __future__ import annotations

import streamlit as st

from owner_lens.compounding import cagr
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
    ImprovingEconomicsReviewCandidate,
    format_count,
    format_money,
    format_per_share,
    format_ratio,
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


def render_improving_economics_review(
    candidates: tuple[ImprovingEconomicsReviewCandidate, ...],
) -> None:
    """Render the additive review lane without changing the standard screener."""
    st.title("Improving Economics — Review Only; Not a Valuation Signal")
    st.caption(
        "These WATCH and LOW_PRIORITY companies meet the recent FCF and "
        "FCF/share trend filter. Existing priorities, coverage, gates, and "
        "limiting reasons remain unchanged."
    )
    if not candidates:
        st.info("No company matches the Improving Economics review filter.")
        return
    st.caption(f"{len(candidates)} companies match.")
    st.dataframe(
        _improving_economics_table(candidates),
        column_config={
            "Ticker / company": st.column_config.TextColumn(
                "Ticker / company", width="medium"
            ),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Coverage": st.column_config.TextColumn("Coverage", width="small"),
            "FCF/share": st.column_config.TextColumn("FCF/share", width="medium"),
            "Latest FCF (USD M)": st.column_config.NumberColumn(
                "Latest FCF (USD M)", format="$%.1f", width="small"
            ),
            "Diluted-share CAGR": st.column_config.TextColumn(
                "Diluted-share CAGR", width="medium"
            ),
            "Survival gate": st.column_config.TextColumn(
                "Survival gate", width="medium"
            ),
        },
        hide_index=True,
        width="stretch",
    )
    company_labels = {
        candidate.company.ticker: (
            f"{candidate.company.ticker} — {candidate.company.company_name}"
        )
        for candidate in candidates
    }
    ticker = st.selectbox(
        "Company details",
        options=[candidate.company.ticker for candidate in candidates],
        format_func=company_labels.__getitem__,
        key="improving_economics_detail_ticker",
    )
    selected = next(
        candidate for candidate in candidates if candidate.company.ticker == ticker
    )
    _improving_economics_detail(selected)


def _improving_economics_table(
    candidates: tuple[ImprovingEconomicsReviewCandidate, ...],
):  # type: ignore[no-untyped-def]
    rows = []
    for candidate in candidates:
        result = candidate.screening
        economics = candidate.owner_economics
        first, third_most_recent, latest = economics[0], economics[-3], economics[-1]
        first_shares = (
            first.diluted_shares.value if first.diluted_shares is not None else None
        )
        latest_shares = (
            latest.diluted_shares.value if latest.diluted_shares is not None else None
        )
        share_cagr = cagr(
            first_shares,
            latest_shares,
            latest.fiscal_year - first.fiscal_year,
        )
        rows.append(
            {
                "Ticker / company": (
                    f"{candidate.company.ticker} — {candidate.company.company_name}"
                ),
                "Priority": result.bucket.value,
                "Coverage": result.coverage_class.value,
                "FCF/share": (
                    f"FY{third_most_recent.fiscal_year} "
                    f"{_format_dollar_per_share(third_most_recent.fcf_per_share)} "
                    f"→ FY{latest.fiscal_year} "
                    f"{_format_dollar_per_share(latest.fcf_per_share)}"
                ),
                "Latest FCF (USD M)": (
                    latest.free_cash_flow / 1_000_000
                    if latest.free_cash_flow is not None
                    else None
                ),
                "Diluted-share CAGR": (
                    f"FY{first.fiscal_year}–FY{latest.fiscal_year} "
                    f"{format_ratio(share_cagr, signed=True)}"
                ),
                "Survival gate": result.gate.value if result.gate else "None",
            }
        )
    return frame(rows)


def _format_dollar_per_share(value: float | None) -> str:
    return "NOT AVAILABLE" if value is None else f"${format_per_share(value)}"


def _improving_economics_detail(
    candidate: ImprovingEconomicsReviewCandidate,
) -> None:
    result = candidate.screening
    st.markdown(f"**Survival gate:** {result.gate.value if result.gate else 'None'}")
    if result.limiting_reasons:
        st.markdown("**Limiting reasons**")
        for reason in result.limiting_reasons:
            st.markdown(f"- {reason.value}")
    else:
        st.caption("No additional limiting reasons.")
    if result.coverage_reasons:
        st.markdown("**Coverage limitations**")
        for reason in result.coverage_reasons:
            st.markdown(f"- {reason.value}")

    with st.expander("Five-year financial history", expanded=False):
        st.dataframe(
            frame(
                [
                    {
                        "FY": row.fiscal_year,
                        "FCF (USD)": (
                            format_money(row.free_cash_flow)
                            if row.free_cash_flow is not None
                            else "NOT AVAILABLE"
                        ),
                        "FCF/share (USD)": _format_dollar_per_share(
                            row.fcf_per_share
                        ),
                        "Diluted shares": (
                            f"{format_count(row.diluted_shares.value)} shares"
                            if row.diluted_shares is not None
                            else "NOT AVAILABLE"
                        ),
                    }
                    for row in candidate.owner_economics
                ],
                index="FY",
            ),
            width="stretch",
        )


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

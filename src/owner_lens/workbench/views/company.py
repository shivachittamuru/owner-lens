"""Company view: one company's full research picture (Feature 7D).

Every table is built from existing Feature 1 and Feature 2 outputs. Where a
layer is unavailable, the Feature 6 coverage reason is shown in place of an
empty chart, so the reader always learns why something is missing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# pandas ships no type stubs and is an indirect dependency of Streamlit; it is
# used here only to shape chart data, never to compute a financial value.
import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from owner_lens.capital_allocation import CapitalAllocationRow
from owner_lens.capital_efficiency import CapitalEfficiencyRow
from owner_lens.compounding import EconomicCompoundingView
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.workbench.data import (
    NOT_AVAILABLE,
    CompanyDetail,
    format_count,
    format_money,
    format_per_share,
    format_ratio,
)
from owner_lens.workbench.views._common import (
    BUCKET_LABEL,
    COVERAGE_LABEL,
    SETUP_LABEL,
    dimension_frame,
    frame,
    reason_lists,
    unavailable,
)

__all__ = ["render"]


def render(detail: CompanyDetail) -> None:
    """Render one company's research page."""
    _header(detail)
    st.divider()
    reason_lists(detail.screening)
    st.divider()

    fundamentals, screening, future = st.tabs(
        ["Fundamentals", "Screening", "Future: Valuation · Edge"]
    )
    with fundamentals:
        _owner_economics(detail.owner_economics)
        st.divider()
        _capital_efficiency(detail)
        st.divider()
        _capital_allocation(detail)
        st.divider()
        _economic_value(detail)
    with screening:
        st.subheader("Screening dimensions")
        st.dataframe(dimension_frame(detail), width="stretch")
        st.caption(
            "Bands are coarse by design. The score orders companies within a "
            "bucket and never sets one."
        )
    with future:
        st.info(
            "Valuation, expected return, edge, and position sizing are not part "
            "of this layer. They need a price, which is the first input OwnerLens "
            "does not derive from a filing. When those features land, they attach "
            "here without changing anything above."
        )


def _header(detail: CompanyDetail) -> None:
    company, result = detail.company, detail.screening
    st.title(f"{company.ticker} — {company.company_name}")
    year = (
        f"FY{result.latest_fiscal_year}"
        if result.latest_fiscal_year is not None
        else NOT_AVAILABLE
    )
    columns = st.columns(5)
    columns[0].metric("Coverage", COVERAGE_LABEL[result.coverage_class])
    columns[1].metric("Research priority", BUCKET_LABEL[result.bucket])
    columns[2].metric("Setup", SETUP_LABEL[result.setup_type])
    columns[3].metric("Latest fiscal year", year)
    columns[4].metric(
        "Dimensions evaluable",
        f"{result.evaluable_dimensions} of 6",
        help="A dimension OwnerLens could not evaluate is excluded, never zeroed.",
    )
    st.caption(
        f"CIK {company.cik} · snapshot "
        f"{(company.content_hash or '')[:12] or NOT_AVAILABLE} · fetched "
        f"{company.fetched_at or NOT_AVAILABLE}"
    )


def _owner_economics(rows: Sequence[OwnerEconomicsRow]) -> None:
    st.subheader("Owner economics")
    if not rows:
        unavailable(None, subject="Owner economics")
        return

    table = frame(
        [
            {
                "FY": row.fiscal_year,
                "Revenue": _fact_money(row.revenue),
                "Operating income": _fact_money(row.operating_income),
                "Operating margin": format_ratio(row.operating_margin),
                "Net income": _fact_money(row.net_income),
                "Operating cash flow": _fact_money(row.operating_cash_flow),
                "CapEx": _fact_money(row.capital_expenditures),
                "FCF": format_money(row.free_cash_flow),
                "FCF margin": format_ratio(row.fcf_margin),
                "Diluted shares": _fact_count(row.diluted_shares),
                "FCF/share": format_per_share(row.fcf_per_share),
            }
            for row in rows
        ],
        index="FY",
    )
    st.dataframe(table, width="stretch")
    _chart(
        rows,
        {
            "FCF/share": lambda r: r.fcf_per_share,
            "FCF margin %": lambda r: None if r.fcf_margin is None else r.fcf_margin * 100,
            "Operating margin %": lambda r: (
                None if r.operating_margin is None else r.operating_margin * 100
            ),
        },
        caption="Years with no derivable value are omitted from the line, never zeroed.",
    )


def _capital_efficiency(detail: CompanyDetail) -> None:
    st.subheader("Capital efficiency")
    rows: Sequence[CapitalEfficiencyRow] = detail.capital_efficiency
    if not rows:
        unavailable(
            detail.capital_efficiency_unavailable_reason, subject="Capital efficiency"
        )
        return

    st.dataframe(
        frame(
            [
                {
                    "FY": row.fiscal_year,
                    "ROIC": format_ratio(row.roic),
                    "ROA": format_ratio(row.roa),
                    "ROE": format_ratio(row.roe),
                    "Invested capital": format_money(row.invested_capital),
                    "Total debt": format_money(row.total_debt),
                    "Net cash / debt": format_money(row.net_cash),
                }
                for row in rows
            ],
            index="FY",
        ),
        width="stretch",
    )
    _chart(
        rows,
        {
            "ROIC %": lambda r: None if r.roic is None else r.roic * 100,
            "ROE %": lambda r: None if r.roe is None else r.roe * 100,
        },
    )


def _capital_allocation(detail: CompanyDetail) -> None:
    st.subheader("Capital allocation")
    rows: Sequence[CapitalAllocationRow] = detail.capital_allocation
    if not rows:
        unavailable(
            detail.capital_allocation_unavailable_reason, subject="Capital allocation"
        )
        return

    st.dataframe(
        frame(
            [
                {
                    "FY": row.fiscal_year,
                    "Repurchases": format_money(row.repurchases),
                    "SBC": format_money(row.sbc),
                    "Dividends": format_money(row.dividends),
                    "Repurchases / FCF": format_ratio(row.repurchases_over_fcf),
                    "SBC / FCF": format_ratio(row.sbc_over_fcf),
                    "Returned / FCF": format_ratio(row.capital_returned_over_fcf),
                    "Retained FCF": format_money(row.retained_fcf),
                    "Share-count change": format_ratio(
                        row.diluted_share_growth, signed=True
                    ),
                    "Buybacks": row.buyback_effectiveness.value,
                    "Classification": row.classification.value,
                }
                for row in rows
            ],
            index="FY",
        ),
        width="stretch",
    )


def _economic_value(detail: CompanyDetail) -> None:
    st.subheader("Economic Value Lens")
    if detail.snapshots:
        st.markdown("**Annual classifications**")
        st.dataframe(
            frame(
                [
                    {
                        "FY": snapshot.fiscal_year,
                        "Classification": snapshot.classification.value,
                        "FCF/share growth": format_ratio(
                            snapshot.fcf_per_share_growth, signed=True
                        ),
                        "ROIC change": format_ratio(snapshot.roic_change, signed=True),
                        "Drivers": ", ".join(d.value for d in snapshot.drivers) or "—",
                    }
                    for snapshot in detail.snapshots
                ],
                index="FY",
            ),
            width="stretch",
        )
    else:
        unavailable(detail.economic_value_unavailable_reason, subject="Economic value")

    _compounding(detail.recent_compounding, detail.long_term_compounding)

    summary = detail.summary
    if summary is None:
        unavailable(detail.summary_unavailable_reason, subject="Company summary")
        return

    st.markdown("**Company summary**")
    st.metric(
        "Overall economic value", summary.overall_economic_value_classification.value
    )
    left, middle, right = st.columns(3)
    with left:
        st.markdown("**Positive**")
        _driver_list(summary.key_positive_drivers)
    with middle:
        st.markdown("**Watch**")
        _driver_list(summary.key_watch_drivers)
    with right:
        st.markdown("**Negative**")
        _driver_list(summary.key_negative_drivers)


def _compounding(
    recent: EconomicCompoundingView | None, long_term: EconomicCompoundingView | None
) -> None:
    views = [("Recent", recent), ("Long term", long_term)]
    if not any(view for _, view in views):
        return
    st.markdown("**Compounding**")
    st.dataframe(
        frame(
            [
                {
                    "Window": f"{label} (FY{view.start_fiscal_year}–FY{view.end_fiscal_year})",
                    "Classification": view.classification.value,
                    "Revenue CAGR": format_ratio(view.revenue_cagr, signed=True),
                    "FCF CAGR": format_ratio(view.fcf_cagr, signed=True),
                    "FCF/share CAGR": format_ratio(view.fcf_per_share_cagr, signed=True),
                    "Share CAGR": format_ratio(view.diluted_share_cagr, signed=True),
                    "ROIC change": format_ratio(view.roic_change, signed=True),
                }
                for label, view in views
                if view is not None
            ],
            index="Window",
        ),
        width="stretch",
    )


def _driver_list(drivers: Sequence[Any]) -> None:
    if not drivers:
        st.caption("None.")
        return
    for driver in drivers:
        st.markdown(f"- {driver.value}")


def _chart(
    rows: Sequence[Any],
    series: dict[str, Any],
    *,
    caption: str | None = None,
) -> None:
    """A small line chart over derivable values only.

    A year with no derivable value is left out of the line rather than plotted
    as zero, and a series with nothing to plot is dropped entirely instead of
    rendering an empty axis.
    """
    numeric = pd.DataFrame(
        [
            {
                # A fiscal year is a label, not a quantity: as a string the axis
                # reads "2021" rather than "2,021".
                "FY": str(row.fiscal_year),
                **{name: fn(row) for name, fn in series.items()},
            }
            for row in rows
        ]
    )
    if numeric.empty:
        return
    numeric = numeric.set_index("FY").dropna(axis=1, how="all")
    if numeric.empty or not len(numeric.columns):
        return
    st.line_chart(numeric, height=220)
    if caption:
        st.caption(caption)


def _fact_money(fact: Any) -> str | None:
    return format_money(fact.value) if fact is not None else None


def _fact_count(fact: Any) -> str | None:
    return format_count(fact.value) if fact is not None else None

"""Compare view: a side-by-side table over two to five companies (Feature 7D)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import streamlit as st

from owner_lens.workbench.data import (
    ComparisonTable,
    format_comparison_value,
)
from owner_lens.workbench.discovery import price_summary, valuation_attention
from owner_lens.workbench.views._common import frame

__all__ = ["MAX_COMPANIES", "MIN_COMPANIES", "render", "render_table"]

MIN_COMPANIES = 2
MAX_COMPANIES = 5


def render(table: ComparisonTable | None) -> None:
    """Render the comparison, or explain what is needed to build one."""
    st.title("Compare")
    st.caption(
        f"Select {MIN_COMPANIES} to {MAX_COMPANIES} companies in the sidebar. "
        "Unavailable metrics show as N/A; they are never normalized to zero."
    )
    if table is None or len(table.columns) < MIN_COMPANIES:
        st.info(f"Select at least {MIN_COMPANIES} companies to compare.")
        return
    render_table(table)


def render_table(table: ComparisonTable) -> None:
    """Render one group of comparison rows per section, preserving N/A."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for label, group in table.rows:
        groups.setdefault(group, []).append((label, group))

    for group, rows in groups.items():
        st.subheader(group)
        st.dataframe(
            frame(
                [
                    {
                        "Metric": label,
                        **{
                            ticker: format_comparison_value(
                                label, table.value(label, ticker)
                            )
                            for ticker in table.tickers
                        },
                    }
                    for label, _ in rows
                ],
                index="Metric",
            ),
            width="stretch",
        )


def render_discovery_evidence(evidence: dict[str, Any], selected: list[str]) -> None:
    """Display captured discovery evidence without recalculating comparisons."""
    items = evidence["items"]
    if set(selected) != {item.company.ticker for item in items} or len(selected) != len(items):
        return
    st.subheader("Discovery evidence at selection")
    st.caption(st.session_state.get("discovery_comparison_message", ""))
    st.caption(
        "Current discovery evidence is separate from any frozen underwriting. "
        "Dates and fiscal periods may differ. Conditional ratios are NOT_VERIFIED; "
        "they are not comparable for banks or REITs and are not valuation conclusions."
    )
    columns: dict[str, dict[str, Any]] = {}
    for item in items:
        ticker = item.company.ticker
        review = evidence["reviews"][ticker]
        card = evidence["cards"][ticker]
        attention = valuation_attention(item, card, review, evidence["market_date"])
        columns[ticker] = {
            "Security ID": str(item.company.security_id),
            "Existing gate": item.screening.gate.value if item.screening.gate else "None (not safety)",
            "Financial evidence": review.financial_state,
            "Financial warnings": "; ".join(
                f"{entry.code}: {entry.explanation}" for entry in review.financial
            ) or "No financial warning from current checks (not safety)",
            "Evidence limitations": "; ".join(
                f"{entry.code}: {entry.explanation}" for entry in review.limitations
            ) or "No limitation flagged by current checks (not complete evidence)",
            "Saved price and conditional valuation": price_summary({
                **card,
                "latest_price_to_fcf": attention.latest_multiple,
                "median_price_to_fcf": attention.median_multiple,
            }),
            "Median FCF yield": (
                f"{attention.median_yield:.2%}"
                if attention.median_yield is not None else "N/A"
            ),
            "FCF/share latest/median": (
                f"{attention.denominator_ratio:.2f}x"
                if attention.denominator_ratio is not None else "N/A"
            ),
            "Valuation ordering status": attention.reason,
        }
    labels = next(iter(columns.values())).keys()
    st.dataframe(
        frame([
            {"Evidence": label, **{ticker: values[label] for ticker, values in columns.items()}}
            for label in labels
        ], index="Evidence"),
        width="stretch",
    )
    with st.expander("Discovery sources, dates and complete evidence"):
        for item in items:
            ticker = item.company.ticker
            st.markdown(f"**{ticker} (security ID {item.company.security_id})**")
            st.json({
                "review": asdict(evidence["reviews"][ticker]),
                "price_and_financial_sources": evidence["cards"][ticker],
            })

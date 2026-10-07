"""Compare view: a side-by-side table over two to five companies (Feature 7D)."""

from __future__ import annotations

import streamlit as st

from owner_lens.workbench.data import (
    ComparisonTable,
    format_comparison_value,
)
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

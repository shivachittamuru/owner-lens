"""Shared rendering helpers for the workbench views (Feature 7D).

Presentation only. Nothing here decides a band, a bucket, a classification, or a
number; it formats what the data layer already resolved. The one rule every
helper enforces is that an unavailable value renders as an explicit "N/A" or
"Not evaluable", never as a blank cell and never as a zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# pandas ships no type stubs and is an indirect dependency of Streamlit; it is
# used here only to shape display frames, never to compute a financial value.
import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from owner_lens.screening import (
    DIMENSION_ORDER,
    CoverageClass,
    ScreeningBucket,
    ScreeningResult,
    SetupType,
)
from owner_lens.workbench.data import (
    BAND_LABEL,
    DIMENSION_LABEL,
    NOT_AVAILABLE,
    CompanyDetail,
    limiting_factor_label,
    main_limiting_reason,
    strongest_reason,
)

__all__ = [
    "BUCKET_LABEL",
    "COVERAGE_LABEL",
    "SETUP_LABEL",
    "dimension_frame",
    "frame",
    "metric_row",
    "reason_lists",
    "screening_row",
    "unavailable",
]

BUCKET_LABEL: dict[ScreeningBucket, str] = {
    bucket: bucket.value for bucket in ScreeningBucket
}
SETUP_LABEL: dict[SetupType, str] = {setup: setup.value for setup in SetupType}
COVERAGE_LABEL: dict[CoverageClass, str] = {
    coverage: coverage.value for coverage in CoverageClass
}


def unavailable(reason: str | None, *, subject: str) -> None:
    """State that something cannot be shown, and why. Never render an empty chart."""
    detail = f" {reason}" if reason else ""
    st.info(f"**{subject}: not evaluable.**{detail}")


def frame(rows: Sequence[dict[str, Any]], *, index: str | None = None) -> pd.DataFrame:
    """Build a display frame, keeping missing values as an explicit "N/A" string."""
    table = pd.DataFrame(list(rows))
    if table.empty:
        return table
    table = table.astype(object).where(pd.notna(table), NOT_AVAILABLE)
    if index is not None and index in table.columns:
        table = table.set_index(index)
    return table


def metric_row(entries: Sequence[tuple[str, Any, str | None]]) -> None:
    """Render a row of compact metric cards: (label, value, help)."""
    columns = st.columns(len(entries))
    for column, (label, value, help_text) in zip(columns, entries, strict=True):
        column.metric(label, value, help=help_text)


def screening_row(result: ScreeningResult) -> dict[str, Any]:
    """One screener/queue row. Bands come straight from Feature 7."""
    row: dict[str, Any] = {
        "Ticker": result.ticker,
        "Priority": BUCKET_LABEL[result.bucket],
        "Setup": SETUP_LABEL[result.setup_type],
        "Coverage": COVERAGE_LABEL[result.coverage_class],
        "Score": result.screening_score,
    }
    for dimension in DIMENSION_ORDER:
        row[DIMENSION_LABEL[dimension]] = BAND_LABEL[result.band(dimension)]
    row["Limiting factor"] = limiting_factor_label(result.limiting_factor)
    row["Strongest reason"] = strongest_reason(result) or NOT_AVAILABLE
    row["Main limitation"] = main_limiting_reason(result) or NOT_AVAILABLE
    return row


def dimension_frame(detail: CompanyDetail) -> pd.DataFrame:
    """The six dimensions with text labels, never colour alone."""
    return frame(
        [
            {
                "Dimension": DIMENSION_LABEL[dimension],
                "Band": BAND_LABEL[detail.dimension(dimension).band],
                "Evidence": " · ".join(detail.dimension(dimension).evidence)
                or NOT_AVAILABLE,
            }
            for dimension in DIMENSION_ORDER
        ],
        index="Dimension",
    )


def reason_lists(result: ScreeningResult) -> None:
    """Render the three Feature 7 reason categories, unchanged."""
    left, middle, right = st.columns(3)
    with left:
        st.markdown("**Why it surfaced**")
        if result.supporting_reasons:
            for reason in result.supporting_reasons:
                st.markdown(f"- {reason.value}")
        else:
            st.caption("No supporting reasons.")
    with middle:
        st.markdown("**What holds it back**")
        if result.gate is not None:
            st.markdown(f"- **{result.gate.value}** (gate)")
        if result.limiting_reasons:
            for reason in result.limiting_reasons:
                st.markdown(f"- {reason.value}")
        elif result.gate is None:
            st.caption("No limiting reasons.")
    with right:
        st.markdown("**What we cannot see**")
        shown = False
        for reason in result.coverage_reasons:
            st.markdown(f"- {reason.value}")
            shown = True
        if result.unavailable_dimensions:
            missing = ", ".join(
                DIMENSION_LABEL[dimension] for dimension in result.unavailable_dimensions
            )
            st.markdown(f"- Unavailable dimensions: {missing}")
            shown = True
        if result.unavailable_metrics:
            st.markdown(
                f"- Blocking canonical metrics: {', '.join(result.unavailable_metrics)}"
            )
            shown = True
        if not shown:
            st.caption("Everything was measurable.")

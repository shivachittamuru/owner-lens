"""Data Quality view: OwnerLens's trust model made visible (Feature 7D).

Shows, per company, exactly which canonical metrics are available, unsupported,
invalid, or structurally absent, which ones block a layer, and the Feature 6
diagnosis behind each. Technical provenance stays behind expanders, and raw
XBRL payloads are never rendered.
"""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from owner_lens.canonical import MetricStatus
from owner_lens.workbench.data import (
    LAYER_LABEL,
    NOT_AVAILABLE,
    CoverageStanding,
    DataQualityReport,
)
from owner_lens.workbench.views._common import frame

__all__ = ["render"]

_STATUS_MARK = {
    MetricStatus.AVAILABLE: "✓",
    MetricStatus.STRUCTURALLY_ABSENT: "·",
    MetricStatus.UNSUPPORTED: "✗",
    MetricStatus.INVALID: "✗",
}
_STATUS_NOTE = {
    MetricStatus.AVAILABLE: "derived from a reported concept",
    MetricStatus.STRUCTURALLY_ABSENT: "proven absent by the company's own totals",
    MetricStatus.UNSUPPORTED: "no trusted concept; never approximated",
    MetricStatus.INVALID: "reported data is ambiguous or malformed; refused",
}


def render(
    standings: Sequence[CoverageStanding], report: DataQualityReport | None
) -> None:
    """Render the universe grid and, when one is selected, a company diagnosis."""
    st.title("Data Quality")
    st.caption(
        "OwnerLens refuses rather than approximates. A metric it cannot trust is "
        "marked unsupported or invalid and never substituted, and a company it "
        "cannot use stays listed with its reason."
    )

    _standings(standings)
    if report is None:
        st.info("Select a company in the sidebar to see its full diagnosis.")
        return
    st.divider()
    _company(report)


def _standings(standings: Sequence[CoverageStanding]) -> None:
    st.subheader("Coverage across the store")
    if not standings:
        st.warning("No company is persisted in the active store.")
        return
    st.dataframe(
        frame(
            [
                {
                    "Ticker": standing.company.ticker,
                    "Coverage": standing.overall,
                    "Unusable metrics": ", ".join(standing.unusable_metrics) or "—",
                    "Primary blocker": standing.primary_blocker or "—",
                }
                for standing in standings
            ],
            index="Ticker",
        ),
        width="stretch",
    )
    counts: dict[str, int] = {}
    for standing in standings:
        counts[standing.overall] = counts.get(standing.overall, 0) + 1
    st.caption(
        " · ".join(f"{state}: {count}" for state, count in sorted(counts.items()))
    )


def _company(report: DataQualityReport) -> None:
    company = report.company
    st.subheader(f"{company.ticker} — {company.company_name}")
    columns = st.columns(4)
    columns[0].metric("Coverage", report.overall)
    columns[1].metric("Available", len(report.available))
    columns[2].metric(
        "Unsupported / invalid", len(report.unsupported) + len(report.invalid)
    )
    columns[3].metric("Structurally absent", len(report.structurally_absent))
    blocking = report.blocking
    st.caption(
        "Blocking metrics: "
        + (", ".join(metric.metric for metric in blocking) if blocking else "none")
    )

    st.markdown("**Canonical metrics**")
    st.dataframe(
        frame(
            [
                {
                    "": _STATUS_MARK[metric.status],
                    "Metric": metric.metric.replace("_", " ").capitalize(),
                    "Status": metric.status.value,
                    "Why": metric.reason or _STATUS_NOTE[metric.status],
                    "Blocks a layer": "yes" if metric.blocking else "",
                }
                for metric in report.metrics
            ],
            index="Metric",
        ),
        width="stretch",
    )

    st.markdown("**Analytical layers**")
    st.dataframe(
        frame(
            [
                {
                    "Layer": LAYER_LABEL.get(layer, layer),
                    "State": state,
                    "Reason": reason or "—",
                }
                for layer, (state, reason) in report.layers.items()
            ],
            index="Layer",
        ),
        width="stretch",
    )

    with st.expander("Technical provenance"):
        st.caption(
            "Which SEC concept was selected for each metric, what else was tried, "
            "and any conflict the normalizer resolved. Raw XBRL payloads are not "
            "rendered here."
        )
        st.dataframe(
            frame(
                [
                    {
                        "Metric": metric.metric,
                        "Concept used": metric.concept_used or NOT_AVAILABLE,
                        "Concepts tried": ", ".join(metric.concepts_tried) or "—",
                        "Catalog candidates": ", ".join(metric.candidates) or "—",
                        "Diagnosis": metric.diagnosis,
                        "Latest FY": metric.latest_fiscal_year,
                        "Resolved conflicts": ", ".join(metric.resolved_conflicts) or "—",
                    }
                    for metric in report.metrics
                ],
                index="Metric",
            ),
            width="stretch",
        )
        survey = report.survey
        st.caption(
            f"Snapshot {(company.content_hash or '')[:12] or NOT_AVAILABLE} · "
            f"processing {company.processing_status or NOT_AVAILABLE} · "
            f"primary diagnosis {survey.primary_category.value}"
        )
        stale = survey.silently_stale()
        if stale:
            st.warning(f"Silently stale concepts detected: {', '.join(stale)}")

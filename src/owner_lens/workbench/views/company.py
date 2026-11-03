"""Company view: one company's full research picture (Feature 7D).

Every table is built from existing Feature 1 and Feature 2 outputs. Where a
layer is unavailable, the Feature 6 coverage reason is shown in place of an
empty chart, so the reader always learns why something is missing.
"""

from __future__ import annotations

import json
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
from owner_lens.research_context import build_research_context
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.underwriting_investment_view import (
    build_investment_view,
    is_analysis_complete,
)
from owner_lens.workbench.data import (
    NOT_AVAILABLE,
    CompanyDetail,
    format_count,
    format_money,
    format_per_share,
    format_ratio,
)
from owner_lens.workbench.views import underwriting_json
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


def render(
    detail: CompanyDetail,
    underwriting: UnderwritingProjection | None = None,
    authoring_source: underwriting_json.SourceFactory | None = None,
    *,
    authoring_underwriting: UnderwritingProjection | None = None,
    pending_underwriting: UnderwritingProjection | None = None,
) -> None:
    """Render one company's research page."""
    _header(detail)
    st.divider()
    reason_lists(detail.screening)
    st.divider()

    fundamentals, screening, beliefs = st.tabs(
        ["Fundamentals", "Screening", "Underwriting"]
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
    with beliefs:
        authoring_projection = authoring_underwriting or underwriting
        if authoring_projection is not None and authoring_source is not None:
            underwriting_json.render(
                detail.company.ticker, authoring_projection, authoring_source
            )
        _underwriting(underwriting, pending_underwriting)
        if (
            underwriting is not None and underwriting.record is not None
            and underwriting.snapshot is not None
        ):
            actions = st.columns(2)
            if actions[0].button(
                f"Record decision on v{underwriting.record.version}"
            ):
                record = underwriting.record
                st.session_state["decision_requested_underwriting"] = (
                    f"{record.ticker}:{record.version}"
                )
                st.session_state.pop("decision_comparison_json", None)
                st.session_state["requested_page"] = "Decisions"
                st.rerun()
            if actions[1].button("Compare underwriting versions"):
                st.session_state["requested_page"] = "Opportunity Comparison"
                st.rerun()
    context = build_research_context(detail, underwriting)
    if st.button("Copy Research Context"):
        st.session_state["research_context_open"] = True
    if st.session_state.get("research_context_open"):
        with st.expander("Research Context", expanded=True):
            st.caption("Select and copy the text below, or download it. No data is sent automatically. Review before sharing.")
            st.code(context.markdown, language="markdown")
            st.download_button("Download Markdown", context.markdown,
                               file_name=f"{detail.company.ticker}-research.md", mime="text/markdown")
            st.download_button("Download JSON", context.json_export,
                               file_name=f"{detail.company.ticker}-research.json", mime="application/json")
    if detail.company.provider == "fmp":
        _fmp_evidence(detail)


def _underwriting(
    projection: UnderwritingProjection | None,
    pending: UnderwritingProjection | None = None,
) -> None:
    st.subheader("Investment View")
    if projection is None:
        st.info("Underwriting unavailable for this store.")
        return
    if projection.record is None or projection.snapshot is None:
        st.info("No immutable underwriting record. No values or assumptions are generated.")
        return
    investment = build_investment_view(projection)
    complete = is_analysis_complete(projection)
    status = "Analysis complete" if complete else "Analysis incomplete"
    st.caption(
        f"{investment.ticker} | underwriting v{investment.version} | "
        f"as of {investment.as_of_date} | {status}"
    )
    if pending is not None and pending.record is not None:
        st.info(
            f"Newer v{pending.record.version} has incomplete analysis. "
            f"This view stays on completed v{investment.version}; use its Retry "
            "analysis action above to resume the newer version."
        )

    identity = st.columns(5)
    identity[0].metric("Frozen price", format_per_share(investment.current_price))
    identity[1].metric("Market date", investment.market_date or NOT_AVAILABLE)
    identity[2].metric("Frozen priority", investment.frozen_priority or NOT_AVAILABLE)
    identity[3].metric("Frozen setup", investment.frozen_setup or NOT_AVAILABLE)
    identity[4].metric("Frozen coverage", investment.frozen_coverage or NOT_AVAILABLE)

    returns = st.columns(5)
    returns[0].metric("Expected return", format_ratio(investment.expected_cagr))
    returns[1].metric("Required return", format_ratio(investment.required_return))
    returns[2].metric("Spread vs hurdle", format_ratio(investment.return_spread))
    returns[3].metric("Assessment", investment.classification or NOT_AVAILABLE)
    returns[4].metric(
        "Expected value/share",
        format_per_share(
            projection.summary.expected_terminal_value_per_share
            if projection.summary
            else None
        ),
    )
    st.info(investment.key_takeaway)
    st.caption(
        "Frozen market evidence and saved calculations; expected outcomes depend on "
        "manual assumptions and probabilities. Not a buy/sell recommendation."
    )

    st.subheader("Scenario setup and outcomes")
    if investment.scenarios:
        st.dataframe(
            frame([
                {
                    "Scenario": row.name,
                    "Probability [JUDGMENT]": format_ratio(row.probability),
                    "Revenue CAGR [ASSUMPTION]": format_ratio(row.revenue_cagr),
                    "Year-5 FCF margin [ASSUMPTION]": format_ratio(row.fcf_margin_year5),
                    "Share-count CAGR [ASSUMPTION]": format_ratio(row.share_count_cagr),
                    "Terminal FCF multiple [ASSUMPTION]": f"{row.terminal_fcf_multiple:.1f}x",
                    "Value/share [CALCULATION]": format_per_share(row.value_per_share),
                    "Implied CAGR [CALCULATION]": format_ratio(row.implied_cagr),
                }
                for row in investment.scenarios
            ]),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("Scenario assumptions are unavailable for this version.")
    if investment.probability_rationale:
        st.caption("Probability rationale [JUDGMENT]: " + investment.probability_rationale)

    st.subheader("Why it may work")
    st.write(f"Key uncertainty: {investment.biggest_uncertainty}")
    st.write(f"Most important variable: {investment.most_important_variable}")
    for evidence_item in investment.business_drivers[:2]:
        st.write(f"Driver: {evidence_item.text}")
    for evidence_item in investment.supporting_evidence[:2]:
        st.write(f"Supporting evidence: {evidence_item.text}")
    if not investment.business_drivers and not investment.supporting_evidence:
        st.caption("No supporting case recorded; missing information is not inferred.")

    st.subheader("What could break it")
    st.markdown("**Dependencies — what must be true**")
    for dependency in investment.dependencies[:3]:
        st.write(dependency)
    if not investment.dependencies:
        st.caption("No dependencies recorded.")
    st.markdown("**Thesis breakers**")
    for breaker in investment.breakers[:3]:
        st.write(breaker)
    if not investment.breakers:
        st.caption("No thesis breakers recorded.")

    st.subheader("Market variant and key sensitivity")
    if investment.variant_conclusion:
        st.write(investment.variant_conclusion.replace("_", " ").capitalize())
    else:
        st.caption("No saved variant comparison is available.")
    if investment.most_sensitive_driver:
        driver = investment.most_sensitive_driver
        st.write(
            f"Most sensitive variable: {driver.name} "
            f"({driver.sensitivity_band}; "
            f"{format_ratio(driver.cagr_delta)} CAGR effect for the saved "
            f"{_format_driver_perturbation(driver.name, driver.perturbation)})."
        )
    else:
        st.caption("No saved sensitivity result is available.")

    st.subheader("Open challenger questions")
    if investment.challenger is None:
        st.caption("No saved challenger run; this view does not run one.")
    else:
        if investment.challenger.strongest_argument_against:
            st.write(investment.challenger.strongest_argument_against)
        for question in investment.challenger.unresolved_questions[:3]:
            st.write(f"- {question}")
        if not investment.challenger.unresolved_questions:
            st.caption("No unresolved challenger questions were saved.")

    with st.expander("Variant drivers and sensitivity"):
        if investment.variant_drivers:
            st.dataframe(
                frame([
                    {
                        "Driver": item.name,
                        "Direction vs expectations": item.direction,
                        "Underwriting assumption": (
                            _format_driver_value(item.name, item.assumption)
                        ),
                        "Consensus": (
                            _format_driver_value(item.name, item.consensus)
                            if item.consensus is not None
                            else NOT_AVAILABLE
                        ),
                        "Sensitivity": item.sensitivity_band,
                        "Perturbation": _format_driver_perturbation(
                            item.name, item.perturbation
                        ),
                        "CAGR effect": format_ratio(item.cagr_delta),
                        "Rationale [JUDGMENT]": item.rationale or NOT_AVAILABLE,
                    }
                    for item in sorted(
                        investment.variant_drivers,
                        key=lambda item: abs(item.cagr_delta),
                        reverse=True,
                    )
                ]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No saved variant or sensitivity outputs.")

    with st.expander("Supporting and disconfirming evidence"):
        for label, items in (
            ("Business drivers", investment.business_drivers),
            ("Supporting evidence", investment.supporting_evidence),
            ("Disconfirming evidence", investment.disconfirming_evidence),
        ):
            st.markdown(f"**{label}**")
            if not items:
                st.caption("None recorded.")
            for item in items:
                st.write(f"[{item.category}] {item.text}")
                if item.evidence_date:
                    st.caption(f"Evidence date: {item.evidence_date}")
                for reference in item.references:
                    st.caption("Source: " + reference)
        st.markdown("**Historical economic context [FACT]**")
        if investment.historical_metrics:
            st.dataframe(
                frame([
                    {
                        "Metric": item.name,
                        "Latest fiscal year": item.fiscal_year or NOT_AVAILABLE,
                        "Historical value": format_ratio(item.value)
                        if item.unit == "ratio"
                        else item.value,
                    }
                    for item in investment.historical_metrics
                ]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No frozen historical base rates are available.")

    with st.expander("Full challenger output"):
        if not projection.challenger_runs:
            st.info("No saved challenger run.")
        else:
            run = projection.challenger_runs[-1]
            st.caption(
                f"Saved advisory run: {run.created_at} | "
                f"underwriting v{run.underwriting_version}"
            )
            output = json.loads(run.output_json)
            for field, value in output.items():
                st.markdown(f"**{field.replace('_', ' ').capitalize()}**")
                values = value if isinstance(value, list) else [value]
                if not values:
                    st.caption("None recorded.")
                for finding in values:
                    if not isinstance(finding, dict):
                        st.write(finding)
                        continue
                    st.write(finding.get("text", NOT_AVAILABLE))
                    if not finding.get("evidence_available", False):
                        st.caption("Evidence unavailable.")
                    references = finding.get("references", [])
                    if references:
                        st.caption(
                            "References: "
                            + ", ".join(item.get("path", NOT_AVAILABLE) for item in references)
                        )

    with st.expander("Analysis gaps and provenance"):
        if not investment.missing:
            st.caption("No explicit gaps reported; this is not an evidence-quality certification.")
        for section, reason in investment.missing:
            st.write(f"{section}: {reason}")
        st.caption(f"Provider: {investment.provider or NOT_AVAILABLE}")
        st.caption(f"Record ID: {investment.record_id}")
        st.caption(f"Content hash: {investment.content_hash}")
        if projection.snapshot:
            evidence = json.loads(projection.snapshot.evidence_json)
            st.json(evidence)
    with st.expander("View Full JSON"):
        st.code(investment.snapshot_json, language="json")


def _format_driver_value(name: str, value: float) -> str:
    return f"{value:.1f}x" if name == "terminal_fcf_multiple" else format_ratio(value)


def _format_driver_perturbation(name: str, value: float) -> str:
    if name == "terminal_fcf_multiple":
        return f"{value:+g}x"
    points = value * 100
    return f"{points:+g} percentage point{'s' if abs(points) != 1 else ''}"


def _fmp_evidence(detail: CompanyDetail) -> None:
    st.divider()
    for error in detail.evidence_errors:
        st.warning(error)
    st.subheader("Quarterly evidence")
    st.caption(
        "Reported FACT evidence only. Not used in annual economics or screening."
    )
    if detail.quarterly_evidence:
        st.dataframe(frame(list(detail.quarterly_evidence)), width="stretch")
    else:
        st.info("No persisted quarterly statement rows.")
    st.subheader("Latest EOD price")
    st.caption(
        "Market evidence, not a valuation or screening input. Currency is not inferred."
    )
    if detail.eod_prices:
        st.dataframe(frame(list(detail.eod_prices)), width="stretch")
    else:
        st.info("No reliable persisted EOD close.")
    st.subheader("Market Expectations")
    st.caption(
        "EXPECTATION: analyst consensus, not reported facts or OwnerLens assumptions."
    )
    if detail.market_expectations:
        st.dataframe(frame(list(detail.market_expectations)), width="stretch")
    else:
        st.info("No persisted analyst estimates; check entitlement and dataset status.")
    with st.expander("Provider provenance and dataset status"):
        st.caption(
            f"Annual canonical history {detail.company.history_id}: fact-linked source snapshots below. "
            "Latest attempts can differ from the retained annual inputs."
        )
        st.dataframe(frame(list(detail.annual_provenance)), width="stretch")
        st.caption("Latest dataset snapshots")
        st.dataframe(frame(list(detail.evidence_snapshots)), width="stretch")
        st.dataframe(
            frame(
                [
                    {
                        "Dataset": state.dataset,
                        "Status": state.status,
                        "Last attempt": state.last_attempt_at,
                        "Reason": state.last_error,
                    }
                    for state in detail.dataset_states
                ]
            ),
            width="stretch",
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
        f"Provider {company.provider.upper()} · CIK {company.cik or NOT_AVAILABLE} · "
        f"{'evidence fingerprint' if company.provider == 'fmp' else 'snapshot'} "
        f"{(company.content_hash or '')[:12] or NOT_AVAILABLE} · fetched "
        f"{company.fetched_at or NOT_AVAILABLE}"
    )
    if company.provider == "fmp":
        st.caption(
            f"Annual canonical input hash: {company.history_input_hash or NOT_AVAILABLE}"
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

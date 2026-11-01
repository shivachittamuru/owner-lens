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
from owner_lens.research_context import build_research_context, scenario_rows
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.workbench.data import (
    NOT_AVAILABLE,
    CompanyDetail,
    format_count,
    format_money,
    format_per_share,
    format_ratio,
)
from owner_lens.workbench.views import underwriting_authoring
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
    authoring_source: underwriting_authoring.SourceFactory | None = None,
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
        if underwriting is not None and authoring_source is not None:
            underwriting_authoring.render(detail.company.ticker, underwriting, authoring_source)
        if st.session_state.get("authoring." + detail.company.ticker):
            with st.expander("Existing underwriting [Read-only]"):
                _underwriting(underwriting)
        else:
            _underwriting(underwriting)
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


def _underwriting(projection: UnderwritingProjection | None) -> None:
    st.subheader("Underwriting")
    if projection is None:
        st.info("Underwriting unavailable for this store.")
        return
    if projection.record is None or projection.snapshot is None:
        st.info("No immutable underwriting record. No values or assumptions are generated.")
        return
    record, snapshot, summary = projection.record, projection.snapshot, projection.summary
    st.caption(f"Underwriting v{record.version} | as of {record.as_of_date} | {projection.status} | read-only")
    evidence = json.loads(snapshot.evidence_json)
    st.caption("Underwriting evidence provider: " + str(evidence.get("provider", NOT_AVAILABLE)))
    price = evidence.get("eod_price", {}).get("value")
    st.caption(f"Frozen market price FACT: {format_per_share(price['close'] if price else None)} | "
               f"market date: {price['market_date'] if price else NOT_AVAILABLE}")
    policy = snapshot.manual.investor_policy
    columns = st.columns(4)
    columns[0].metric("Classification", summary.classification if summary else NOT_AVAILABLE)
    columns[1].metric("Expected 5Y CAGR", format_ratio(summary.expected_5y_cagr if summary else None))
    columns[2].metric("Required return", format_ratio(
        summary.investor_policy.required_return if summary else policy.required_return if policy else None))
    columns[3].metric("Spread vs hurdle", format_ratio(summary.return_spread if summary else None))
    st.caption("CALCULATION outcomes; JUDGMENT hurdle/probabilities. Conditional assessment, not a buy/sell recommendation.")
    st.caption("Variant view: " + (projection.variant.conclusion if projection.variant else NOT_AVAILABLE))
    if projection.status == "CAPTURED":
        st.info("Derived outputs are N/A for this exact version. The page does not generate them.")
        with st.expander("Offline commands to generate missing artifacts"):
            st.code(
                f"uv run owner-lens valuation run {record.ticker} --version {record.version}\n"
                f"uv run owner-lens variant show {record.ticker} --version {record.version}\n"
                f"uv run owner-lens underwriting summary {record.ticker} --version {record.version}\n"
                f"uv run owner-lens challenger run {record.ticker} --version {record.version}",
                language="powershell",
            )
    st.caption("Probability rationale [JUDGMENT]: " + (
        snapshot.manual.probability_distribution.rationale
        if snapshot.manual.probability_distribution and snapshot.manual.probability_distribution.rationale
        else NOT_AVAILABLE))
    st.subheader("Bear / Base / Bull")
    rows = scenario_rows(projection)
    for row in rows:
        row["Probability [JUDGMENT]"] = format_ratio(row["Probability [JUDGMENT]"])
        row["Value/share [CALCULATION]"] = format_per_share(row["Value/share [CALCULATION]"])
        row["Implied CAGR [CALCULATION]"] = format_ratio(row["Implied CAGR [CALCULATION]"])
    if rows:
        st.dataframe(frame(rows), width="stretch")
    else:
        st.info("No approved scenario assumptions.")
    st.subheader("What drives the result")
    st.write("Biggest uncertainty [JUDGMENT]: " + snapshot.manual.thesis.biggest_uncertainty)
    st.write("Most important variable [JUDGMENT]: " + snapshot.manual.thesis.most_important_variable)
    if projection.variant:
        st.dataframe(frame([{
            "Driver": driver.driver, "Sensitivity": driver.sensitivity.band,
            "Perturbation": driver.sensitivity.perturbation,
            "CAGR effect": format_ratio(driver.sensitivity.cagr_delta),
            "Consensus": format_ratio(driver.consensus.value),
            "Delta": format_ratio(driver.absolute_delta),
            "Rationale [JUDGMENT]": driver.rationale.text if driver.rationale else NOT_AVAILABLE,
        } for driver in sorted(projection.variant.drivers, key=lambda item: abs(item.sensitivity.cagr_delta), reverse=True)]),
            width="stretch")
    else:
        st.info("No projected variant or sensitivity outputs. No valuation is run by this page.")
    with st.expander("Thesis and evidence"):
        manual = snapshot.manual
        for label, statements in (("Key business/value drivers", manual.business_drivers),
                                  ("Supporting evidence", manual.supporting_evidence),
                                  ("Disconfirming evidence", manual.disconfirming_evidence)):
            st.markdown(f"**{label}**")
            if not statements:
                st.info("None recorded; evidence is missing, not assumed.")
            for statement in statements:
                st.write(f"[{statement.category}] {statement.text}")
                if statement.evidence_date:
                    st.caption("Evidence date: " + statement.evidence_date)
                for reference in statement.references:
                    st.caption(f"Source: {reference.title or NOT_AVAILABLE} | {reference.observed_at or NOT_AVAILABLE}")
        for label, texts, conditions in (
            ("Dependencies / what must be true", manual.thesis.dependencies, manual.thesis.monitoring_dependencies),
            ("Thesis breakers", manual.thesis.breakers, manual.thesis.monitoring_breakers),
        ):
            st.markdown(f"**{label} [JUDGMENT]**")
            if conditions:
                for condition in conditions:
                    st.write(condition.statement)
                    st.caption(f"Observable: {condition.observable or NOT_AVAILABLE} | "
                               f"Condition: {condition.threshold or NOT_AVAILABLE} | "
                               f"Monitor: {condition.monitoring_cadence or condition.monitoring_date or NOT_AVAILABLE}")
                    st.caption("Sources: " + (", ".join(reference.title or NOT_AVAILABLE for reference in condition.sources) or NOT_AVAILABLE))
            else:
                for text in texts:
                    st.write(text)
        st.markdown("**Next evidence to collect [JUDGMENT]**")
        for text in manual.thesis.next_evidence_to_collect:
            st.write(text)
    with st.expander("Challenger [JUDGMENT]"):
        if not projection.challenger_runs:
            st.info("No saved challenger run. The UI never runs the challenger.")
        else:
            run = projection.challenger_runs[-1]
            st.caption(f"Saved advisory run: {run.created_at} | underwriting v{run.underwriting_version}")
            output = json.loads(run.output_json)
            for field in ("overall_assessment", "strongest_argument_against", "fragile_assumptions",
                          "probability_challenges", "missing_evidence", "variant_view_challenge", "questions_to_resolve"):
                st.markdown(f"**{field.replace('_', ' ').capitalize()}**")
                values = output[field] if isinstance(output[field], list) else [output[field]]
                if not values:
                    st.caption("None recorded.")
                for finding in values:
                    st.write(finding["text"])
                    if not finding["evidence_available"]:
                        st.caption("Evidence unavailable.")
                    st.caption("References: " + ", ".join(item["path"] for item in finding["references"]))
    with st.expander("Missing evidence and outputs"):
        if not projection.missing_evidence:
            st.caption("No explicit gaps reported; this is not an evidence-quality certification.")
        for missing in projection.missing_evidence:
            st.write(f"{missing.section}: {missing.reason}")


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

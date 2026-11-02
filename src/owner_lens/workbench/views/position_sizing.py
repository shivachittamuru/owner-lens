"""Explicit snapshot/policy entry and read-only bounded sizing review."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import streamlit as st

from owner_lens.decisions import DecisionError, load_decision_json
from owner_lens.opportunity_comparison import ComparisonError, UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import (
    DISCLAIMER,
    PortfolioSnapshot,
    canonical_json,
    create_portfolio,
    format_sizing,
    size_position,
    sizing_rows,
)
from owner_lens.workbench.views._common import frame

ERRORS = (ValueError, DecisionError, ComparisonError, PersistenceError)


def render(store: SqliteStore) -> None:
    st.title("Portfolio Context / Position Sizing")
    st.caption(DISCLAIMER)
    with st.expander("Create immutable portfolio snapshot"):
        st.caption(
            "Enter JSON with as_of_date, basis (WEIGHT or MARKET_VALUE), holdings "
            "(ticker, asset_type, weight or market_value), and optional cash. "
            "Sector, industry and exposure_tags are manual; null means unknown, [] means no tags. "
            "MARKET_VALUE also requires an explicit three-letter currency; no currency conversion. "
            "WEIGHT inputs are decimal ratios. All supplied amounts are normalized by their sum."
        )
        with st.form("portfolio_create"):
            portfolio_input = st.text_area(
                "Portfolio input JSON", key="sizing_portfolio_input"
            )
            save_portfolio = st.form_submit_button("Save new portfolio snapshot")
        if save_portfolio:
            try:
                snapshot = create_portfolio(store, load_decision_json(portfolio_input))
            except ERRORS as exc:
                st.error(f"Portfolio was not saved: {exc}")
            else:
                st.success(f"Created portfolio snapshot {snapshot.snapshot_id}")
    portfolios = store.list_portfolio_snapshots()
    portfolio_id = st.selectbox(
        "Exact portfolio snapshot",
        [item.snapshot_id for item in portfolios],
        index=None,
        key="sizing_portfolio_id",
    )
    if portfolio_id:
        portfolio = PortfolioSnapshot.from_json(
            store.get_portfolio_snapshot(portfolio_id)
        )
        st.caption(
            f"As of {portfolio.as_of_date}; normalization total {portfolio.normalization_total:g}; "
            f"cash {'MISSING' if portfolio.cash_weight is None else format(portfolio.cash_weight, '.2%')}."
        )
        st.dataframe(
            frame(
                [
                    {
                        "Ticker": item.ticker,
                        "Asset type": item.asset_type.value,
                        "Current weight": f"{item.weight:.2%}",
                        "Sector": item.context.sector or "MISSING",
                        "Industry": item.context.industry or "MISSING",
                        "Tags": ", ".join(item.context.exposure_tags)
                        if item.context.exposure_tags is not None
                        else "MISSING",
                    }
                    for item in portfolio.holdings
                ]
            ),
            width="stretch",
        )
    selections = {}
    for security in store.list_securities():
        for record in store.list_underwriting(security.symbol):
            selections[f"{record.ticker}:{record.version}"] = UnderwritingSelection(
                record.ticker, record.version
            )
    label = st.selectbox(
        "Exact underwriting version",
        list(selections),
        index=None,
        key="sizing_underwriting",
    )
    decision_id = st.selectbox(
        "Optional exact decision context (never treated as holdings)",
        [item.decision_id for item in store.list_decisions()],
        index=None,
        key="sizing_decision_id",
    )
    with st.form("sizing_review"):
        st.caption(
            "All eight numeric policy fields plus category=JUDGMENT are required: "
            "max_single_position_weight, max_initial_position_weight, "
            "max_portfolio_bear_loss_contribution, max_sector_weight, min_cash_reserve, "
            "starter_position_weight, max_thesis_weight, severe_bear_loss_threshold. "
            "No limits are prefilled or assumed."
        )
        policy_input = st.text_area(
            "Explicit sizing policy JSON", key="sizing_policy_input"
        )
        context_input = st.text_area(
            "Optional opportunity exposure context JSON (sector, industry, exposure_tags)",
            key="sizing_context_input",
        )
        increment_input = st.text_input(
            "Optional proposed incremental weight (decimal ratio)",
            key="sizing_increment_input",
        )
        persist = st.checkbox("Save this sizing analysis immutably", value=False)
        submitted = st.form_submit_button("Review position-size range")
    if submitted:
        if not label or not portfolio_id:
            st.error("Select an exact underwriting version and portfolio snapshot.")
        else:
            try:
                report = size_position(
                    store,
                    selections[label],
                    portfolio_id,
                    load_decision_json(policy_input),
                    context_data=load_decision_json(context_input)
                    if context_input.strip()
                    else None,
                    proposed_increment=float(increment_input)
                    if increment_input.strip()
                    else None,
                    decision_id=decision_id,
                )
                if persist:
                    saved = store.save_sizing_analysis(
                        canonical_json(report), created_at=datetime.now(UTC).isoformat()
                    )
                    st.success(
                        f"Saved immutable sizing analysis {saved.analysis_id}; no decision or trade was created."
                    )
            except ERRORS as exc:
                st.error(f"Sizing analysis was not created: {exc}")
            else:
                st.dataframe(
                    frame(sizing_rows(report), index="Metric"), width="stretch"
                )
                with st.expander(
                    "Frozen economics, context, largest positions and concentration details"
                ):
                    st.json(json.loads(canonical_json(report)))
                st.download_button(
                    "Download sizing JSON",
                    canonical_json(report),
                    file_name="position-sizing.json",
                    mime="application/json",
                )
    st.subheader("Saved sizing analyses [Read-only]")
    analyses = store.list_sizing_analyses()
    if not analyses:
        st.info("No sizing analyses saved.")
    for analysis in analyses:
        with st.expander(f"{analysis.created_at} / {analysis.analysis_id}"):
            st.text(format_sizing(json.loads(analysis.report_json)))
            st.download_button(
                "Download saved analysis JSON",
                analysis.report_json,
                file_name=f"sizing-{analysis.analysis_id}.json",
                mime="application/json",
                key="sizing_download." + analysis.analysis_id,
            )

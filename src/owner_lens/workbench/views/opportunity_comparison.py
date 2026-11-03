"""Company-first, read-only presentation of the existing Feature 9A service."""

from __future__ import annotations

import streamlit as st

from owner_lens.opportunity_catalog import discover_comparison_companies
from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
    comparison_rows,
)
from owner_lens.persistence import SqliteStore
from owner_lens.workbench.views._common import frame

_MAIN_METRICS = (
    "Underwriting as of",
    "Frozen price / market date",
    "Expected 5Y CAGR",
    "Required return",
    "Spread over hurdle",
    "Feature 8 classification",
    "Bear CAGR / terminal return",
    "Base CAGR",
    "Bull CAGR / terminal return",
    "Probability of terminal loss",
    "Business Quality",
    "Variant view",
    "Supporting evidence",
    "Disconfirming evidence",
    "Challenger status",
)


def _open_company(selection: UnderwritingSelection) -> None:
    st.session_state["requested_company_provider"] = "fmp"
    st.session_state["company_requested_underwriting"] = selection
    st.session_state["comparison_requested_company"] = selection.ticker
    st.session_state["requested_page"] = "Company"
    st.rerun()


def render(store: SqliteStore) -> None:
    st.title("Opportunity Comparison")
    workflow = st.session_state.get("allocation_workflow")
    if (
        workflow is not None
        and "opportunity_requested_underwriting" in st.session_state
        and (not workflow.get("approved") or workflow.get("decision_id"))
    ):
        del st.session_state["allocation_workflow"]
    if "allocation_workflow" in st.session_state:
        from owner_lens.workbench.views import allocation

        allocation.render(store, st.session_state["allocation_workflow"])
        return
    st.caption(
        "Choose 2-5 companies. Each uses its latest fully analyzed, eligible "
        "underwriting, with frozen prices and saved investor hurdles. "
        "No refresh, revaluation, new score or investment recommendation."
    )
    catalog = discover_comparison_companies(store)
    companies = {item.ticker: item for item in catalog.companies}
    versions = {
        version.label: version
        for company in catalog.companies
        for version in company.versions
    }
    handoff = st.session_state.pop("opportunity_requested_underwriting", None)
    if handoff is not None:
        if handoff not in versions.values():
            st.error("The requested exact underwriting is not fully analyzed or eligible.")
            return
        else:
            st.session_state["opportunity_companies"] = [handoff.selection.ticker]
            st.session_state[f"opportunity_version.{handoff.selection.ticker}"] = handoff.label
            st.session_state["opportunity_extra_versions"] = []
    if not companies:
        st.info("No fully analyzed, comparison-eligible underwritings are available.")
    if "opportunity_companies" in st.session_state:
        st.session_state["opportunity_companies"] = [
            ticker for ticker in st.session_state["opportunity_companies"]
            if ticker in companies
        ]
    selected = st.multiselect(
        "Companies (2-5)",
        options=list(companies),
        format_func=lambda ticker: f"{ticker} — {companies[ticker].name}",
        max_selections=5,
        key="opportunity_companies",
    )
    overrides: dict[str, str] = {}
    with st.expander("Advanced: historical underwriting versions"):
        st.caption("Optional exact-version overrides; multiple versions of one company are supported.")
        for ticker in selected:
            company = companies[ticker]
            labels = ["Latest eligible"] + [
                version.label for version in reversed(company.versions)
            ]
            key = f"opportunity_version.{ticker}"
            previous = st.session_state.get(key)
            if previous is not None and previous not in labels:
                labels.append(previous)
            if previous is None:
                st.session_state[key] = "Latest eligible"
            chosen_label = st.selectbox(
                f"{ticker} version",
                labels,
                key=key,
            )
            if chosen_label != "Latest eligible" and chosen_label not in versions:
                st.error(
                    f"{chosen_label} is no longer eligible. Select Latest eligible "
                    "or another historical version explicitly; nothing was substituted."
                )
                return
            overrides[ticker] = (
                company.latest.label if chosen_label == "Latest eligible" else chosen_label
            )
        if "opportunity_extra_versions" in st.session_state:
            st.session_state["opportunity_extra_versions"] = [
                label for label in st.session_state["opportunity_extra_versions"]
                if label in versions
            ]
        extra = st.multiselect(
            "Additional historical versions",
            list(versions),
            max_selections=4,
            key="opportunity_extra_versions",
        )
    resolved = {
        overrides.get(ticker, companies[ticker].latest.label): None
        for ticker in selected
    }
    resolved.update(dict.fromkeys(extra))
    for ticker in selected:
        company = companies[ticker]
        chosen = versions[overrides.get(ticker, company.latest.label)]
        st.caption(f"{ticker}: comparing underwriting v{chosen.selection.version}")
        if company.latest_record_version > company.latest.selection.version:
            st.warning(
                f"{ticker}: newer v{company.latest_record_version} is incomplete or "
                f"ineligible. Using eligible v{chosen.selection.version}, not current prices."
            )
            if st.button(
                f"Open {ticker} v{company.latest_record_version} for exact-version retry",
                key=f"opportunity_retry.{ticker}",
            ):
                _open_company(UnderwritingSelection(ticker, company.latest_record_version))
    if catalog.excluded:
        with st.expander("Excluded incomplete or invalid versions"):
            for reason in catalog.excluded:
                st.write(reason)
    if not 2 <= len(resolved) <= 5:
        st.info("Select 2-5 distinct underwritings to compare; remove extra historical versions if needed.")
        return
    report = compare_underwritings(
        store, tuple(versions[label].selection for label in resolved)
    )
    rows = comparison_rows(report)
    by_metric = {row["Metric"]: row for row in rows}
    st.caption(
        "Compare the frozen price dates and required returns explicitly: they may "
        "differ. Bear outcomes are modeled scenarios, not maximum losses."
    )
    st.dataframe(
        frame([by_metric[name] for name in _MAIN_METRICS], index="Metric"),
        width="stretch",
    )
    st.caption(report.disclaimer)
    st.caption(
        "Challenger limitations use 9A's bounded offline rule review, not a new "
        "model run or evidence verification. Expand a company for questions and gaps."
    )
    st.subheader("Grounded tradeoffs")
    for pair in report.pairs:
        st.markdown(f"**{pair.left} vs {pair.right}: {pair.conclusion}**")
        st.write(pair.key_tradeoff)
        st.caption(
            f"{pair.left}: {', '.join(pair.left_flags) or 'No flags'} | "
            f"{pair.right}: {', '.join(pair.right_flags) or 'No flags'}"
        )
        st.write("Conditional capital attractiveness: " + pair.capital_attractiveness)
        with st.expander(f"{pair.left} vs {pair.right}: research attention"):
            st.write(pair.research_attention)
    for opportunity in report.opportunities:
        with st.expander(f"{opportunity.label}: evidence, model inputs and provenance"):
            st.markdown("**Research attention**")
            for reason in opportunity.research_attention:
                st.write(reason)
            st.write("Biggest uncertainty: " + opportunity.unresolved_issue)
            for question in opportunity.quality.major_unresolved_questions:
                st.write(question)
            for missing in opportunity.quality.missing_dimensions:
                st.write("MISSING: " + missing)
            st.dataframe(
                frame([
                    {"Metric": row["Metric"], opportunity.label: row[opportunity.label]}
                    for row in rows if row["Metric"] not in _MAIN_METRICS
                ], index="Metric"),
                width="stretch",
            )
            st.json(opportunity.summary.to_json())
            record = next(
                item for item in store.list_underwriting(opportunity.summary.ticker)
                if item.underwriting_id == opportunity.summary.underwriting_id
            )
            st.markdown("**Frozen snapshot and evidence provenance**")
            st.json(record.snapshot_json)
            if st.button(
                f"Open {opportunity.label} Company Investment View",
                key=f"opportunity_company.{opportunity.label}",
            ):
                _open_company(versions[opportunity.label].selection)
    with st.expander("Full comparison and reproducible export"):
        st.json(report.to_json())
        st.download_button(
            "Download reproducible comparison JSON",
            data=report.to_json(),
            file_name="opportunity-comparison.json",
            mime="application/json",
        )
    allocation_selected = st.selectbox(
        "Opportunity to evaluate in portfolio context",
        [item.label for item in report.opportunities],
        index=None,
        key="comparison_allocation_selected",
    )
    if st.button("Evaluate Allocation", disabled=allocation_selected is None):
        comparison_selections = {
            key: value for key, value in st.session_state.items()
            if isinstance(key, str) and (
                key in ("opportunity_companies", "opportunity_extra_versions")
                or key.startswith("opportunity_version.")
            )
        }
        for state_key in list(st.session_state):
            if isinstance(state_key, str) and state_key.startswith("allocation_"):
                del st.session_state[state_key]
        st.session_state["allocation_workflow"] = {
            "selected": allocation_selected,
            "comparison_json": report.to_json(),
            "comparison_selections": comparison_selections,
        }
        st.rerun()
    if st.button("Record a decision from this comparison"):
        st.session_state["decision_comparison_json"] = report.to_json()
        st.session_state.pop("decision_selected_underwriting", None)
        st.session_state["requested_page"] = "Decisions"
        st.rerun()

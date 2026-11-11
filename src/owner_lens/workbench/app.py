"""Streamlit entry point for the OwnerLens workbench (Feature 7D).

Orchestration only: this module resolves which companies the active store can
serve, hands the already-resolved data to one view, and owns navigation. No
financial decision is made here, and no SEC or FMP request is issued by opening
or navigating the application.

Launch it with ``uv run owner-lens workbench``.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from owner_lens.canonical import CanonicalDataError
from owner_lens.decisions import DecisionError
from owner_lens.opportunity_catalog import discover_comparison_companies
from owner_lens.opportunity_comparison import ComparisonError
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.screening import ScreeningBucket
from owner_lens.underwriting import UnderwritingError
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.underwriting_investment_view import (
    is_analysis_complete,
    select_investment_projection,
)
from owner_lens.underwriting_summary import SummaryError
from owner_lens.variant import VariantError
from owner_lens.workbench.cache import (
    cached_company_detail,
    cached_comparison,
    cached_coverage_standings,
    cached_data_quality,
    cached_improving_economics_owner_economics,
    cached_screening,
    clear_caches,
    fingerprint,
    open_run_source,
)
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    improving_economics_review_candidates,
    load_persisted_companies,
    overview_counts,
)
from owner_lens.workbench.views import (
    attribution,
    calibration,
    changes,
    company,
    compare,
    data_quality,
    decisions,
    mistakes,
    opportunity_comparison,
    outcomes,
    overview,
    position_sizing,
    screener,
)

__all__ = ["main"]

PAGES = ("Overview", "Screener", "Company", "Compare", "Opportunity Comparison", "Decisions", "Shadow Portfolio", "Portfolio Context / Position Sizing", "What Changed?", "Outcomes", "Calibration", "Mistake Review", "Attribution", "Data Quality")


def main() -> None:
    """Render the workbench."""
    st.set_page_config(page_title="OwnerLens Workbench", page_icon="🔎", layout="wide")
    requested_provider = st.session_state.pop("requested_company_provider", None)
    if requested_provider is not None:
        st.session_state["provider"] = requested_provider
    elif "provider" not in st.session_state:
        st.session_state["provider"] = (
            "fmp" if os.environ.get("OWNER_LENS_WORKBENCH_PROVIDER") == "fmp" else "sec"
        )
    provider = st.sidebar.selectbox(
        "Evidence provider",
        options=("sec", "fmp"),
        index=None,
        format_func=lambda value: (
            "SEC (default)" if value == "sec" else "FMP · S&P 500"
        ),
        key="provider",
    )
    if provider is None:
        st.error("Select an evidence provider to continue.")
        return

    # The company list is read fresh every run rather than cached, so a
    # re-ingested company's new content hash takes effect immediately and
    # invalidates the derived results that depended on the old payload. One
    # short-lived source per run: a SQLite connection is thread-bound and
    # Streamlit reruns on whichever thread is free.
    try:
        with open_run_source() as source:
            db_path, raw_data_path = source.db_path, source.raw_data_path
            companies = load_persisted_companies(source, provider)
    except (PersistenceError, OSError) as exc:
        st.title("OwnerLens Workbench")
        st.error(
            f"The configured store could not be opened: {exc}\n\n"
            "Check `OWNER_LENS_DB_PATH`, or pass another store with "
            "`uv run owner-lens workbench --db data/ownerlens.db`."
        )
        return

    usable = tuple(c for c in companies if c.available or provider == "fmp")
    prints = fingerprint(companies)
    pending = st.session_state.pop("discovery_comparison_pending", None)
    if pending is not None:
        try:
            with open_run_source() as source:
                _route_discovery_comparison(pending, usable, provider, db_path, source.store)
        except (ComparisonError, PersistenceError, OSError, WorkbenchError) as exc:
            st.error(f"Cannot compare the selected securities: {exc}")
    comparison_ticker = st.session_state.pop("comparison_requested_company", None)
    if comparison_ticker is not None:
        st.session_state["selected_ticker"] = comparison_ticker

    page = _sidebar(db_path, raw_data_path, companies, usable)
    if comparison_ticker is not None and _find(usable, comparison_ticker) is None:
        st.error(
            f"{comparison_ticker}'s frozen underwriting remains available in "
            "Opportunity Comparison, but its Company page has no persisted "
            "company data in this provider's universe. No other company was substituted."
        )
        return

    if page in ("Opportunity Comparison", "Decisions", "Shadow Portfolio", "Portfolio Context / Position Sizing", "What Changed?", "Outcomes", "Calibration", "Mistake Review", "Attribution"):
        try:
            with open_run_source() as source:
                if not isinstance(source.store, SqliteStore):
                    st.error("Opportunity comparison, decisions and shadow entries require SQLite.")
                    return
                if page == "Opportunity Comparison":
                    opportunity_comparison.render(
                        source.store, discovery_context=(db_path, provider)
                    )
                elif page == "Decisions":
                    decisions.render(source.store)
                elif page == "Portfolio Context / Position Sizing":
                    position_sizing.render(source.store)
                elif page == "What Changed?":
                    changes.render(source.store, open_run_source)
                elif page == "Outcomes":
                    outcomes.render(source.store)
                elif page == "Calibration":
                    calibration.render(source.store)
                elif page == "Mistake Review":
                    mistakes.render(source.store)
                elif page == "Attribution":
                    attribution.render(source.store)
                else:
                    decisions.render_shadow(source.store)
        except (ComparisonError, DecisionError, PersistenceError, OSError) as exc:
            st.error(f"{page} could not be loaded: {exc}")
        return

    if not companies:
        st.title("OwnerLens Workbench")
        st.warning(
            f"No company is persisted for provider {provider.upper()} in `{db_path}`. Use "
            "`uv run owner-lens refresh-sp500` for FMP or "
            "`uv run owner-lens ingest ADBE` for SEC."
        )
        return

    st.caption(
        f"Provider: {provider.upper()} · Annual screening only · "
        f"As of: {max((c.fetched_at or '' for c in companies), default='') or 'unavailable'}"
    )
    if provider == "fmp":
        st.caption(
            f"Current persisted S&P 500: {len(companies)} securities · Membership observed "
            f"{companies[0].universe_observed_at}"
        )
    results = _guarded(
        lambda: cached_screening(prints, provider=provider, db_path=db_path)
    )
    if results is None:
        return

    if page == "Overview":
        overview.render(companies, results, overview_counts(companies, results))
    elif page == "Screener":
        screener_modes = (
            ("Standard Screener", "Improving Economics - Review Only")
            if provider == "fmp"
            else ("Standard Screener",)
        )
        if st.session_state.get("screener_view_mode") not in screener_modes:
            st.session_state["screener_view_mode"] = screener_modes[0]
        screener_mode = st.radio(
            "Screener view",
            options=screener_modes,
            horizontal=True,
            key="screener_view_mode",
        )
        if screener_mode == "Improving Economics - Review Only":
            eligible = tuple(
                result
                for result in results
                if result.bucket
                in (ScreeningBucket.WATCH, ScreeningBucket.LOW_PRIORITY)
            )
            owner_economics = _guarded(
                lambda: cached_improving_economics_owner_economics(
                    prints,
                    tuple(result.ticker for result in eligible),
                    db_path=db_path,
                    provider=provider,
                )
            )
            if owner_economics is not None:
                candidates = improving_economics_review_candidates(
                    companies, eligible, dict(owner_economics)
                )
                screener.render_improving_economics_review(candidates)
        else:
            screener.render(results)
        show_review = st.checkbox(
            "Show Uncertainty & Fragility review",
            value=False,
            key="show_uncertainty_fragility",
            help="Offline historical research prompts, existing financial warnings, and evidence limitations. No risk score.",
        )
        from owner_lens.workbench.cache import (
            discovery_canonical_reviews,
            discovery_overview,
            uncertainty_fragility_reviews,
        )

        overview_data = _guarded(lambda: discovery_overview(companies, results, db_path))
        if overview_data is not None:
            lanes, cards = overview_data
            reviews = _guarded(
                lambda: uncertainty_fragility_reviews(companies, results, db_path)
                if show_review
                else discovery_canonical_reviews(lanes, companies, db_path)
            )
            if reviews is not None:
                screener.render_discovery(
                    lanes, cards, reviews, results,
                    selection_context=(db_path, provider),
                    show_review=show_review,
                )
    elif page == "Company":
        _company_page(usable, provider, db_path)
    elif page == "Compare":
        _compare_page(usable, provider, db_path)
    else:
        _data_quality_page(usable, prints, db_path, provider)


def _sidebar(
    db_path: str,
    raw_data_path: str,
    companies: tuple[PersistedCompany, ...],
    usable: tuple[PersistedCompany, ...],
) -> str:
    with st.sidebar:
        st.header("OwnerLens")
        requested = st.session_state.pop("requested_page", None)
        if requested in PAGES:
            st.session_state["page"] = requested
        page = st.radio("View", options=PAGES, key="page")

        if page == "Company":
            _ticker_picker(usable, "selected_ticker", "Company")
        elif page == "Compare":
            _multi_picker(usable)
        elif page == "Data Quality":
            _ticker_picker(usable, "quality_ticker", "Company", allow_none=True)

        st.divider()
        st.subheader("Data")
        st.caption(f"Store `{db_path}`")
        st.caption(f"Raw snapshots `{raw_data_path}`")
        st.caption(
            f"{sum(c.available for c in companies)} of {len(companies)} companies "
            "have usable persisted annual evidence."
        )
        st.caption(
            "The workbench reads persisted data only. Use "
            "`uv run owner-lens ingest TICKER` for SEC or "
            "`uv run owner-lens refresh-sp500` for FMP, then reload below."
        )
        if st.button("Reload persisted data", width="stretch"):
            clear_caches()
            st.rerun()
    return str(page)


def _ticker_picker(
    companies: tuple[PersistedCompany, ...],
    key: str,
    label: str,
    *,
    allow_none: bool = False,
) -> None:
    tickers = [c.ticker for c in companies]
    options = ([""] + tickers) if allow_none else tickers
    if not tickers:
        return
    current = st.session_state.get(key)
    index = options.index(current) if current in options else 0
    if current not in options:
        st.session_state[key] = options[index]
    st.selectbox(label, options=options, index=index, key=key)


def _multi_picker(companies: tuple[PersistedCompany, ...]) -> None:
    tickers = [c.ticker for c in companies]
    selected = st.session_state.get("compare_tickers", tickers[: compare.MIN_COMPANIES])
    if "compare_tickers" not in st.session_state:
        st.session_state["compare_tickers"] = selected
    unavailable = [ticker for ticker in selected if ticker not in tickers]
    if unavailable:
        st.warning(
            "Unavailable selections remain selected until removed: "
            + ", ".join(unavailable)
        )
    st.multiselect(
        f"Companies ({compare.MIN_COMPANIES}–{compare.MAX_COMPANIES})",
        options=[*tickers, *unavailable],
        max_selections=compare.MAX_COMPANIES,
        key="compare_tickers",
    )


def _route_discovery_comparison(
    pending: dict[str, Any],
    companies: tuple[PersistedCompany, ...],
    provider: str,
    db_path: str,
    store: object,
) -> None:
    if pending["context"] != (db_path, provider):
        raise WorkbenchError("The selection belongs to a different store or provider.")
    if not isinstance(store, SqliteStore):
        raise WorkbenchError("Discovery comparison requires a SQLite store.")
    items = pending["items"]
    if not 2 <= len(items) <= 5:
        raise WorkbenchError("Select 2-5 securities.")
    selected = [item.company for item in items]
    identities = [company.security_id for company in selected]
    tickers = [company.ticker for company in selected]
    if None in identities or len(set(identities)) != len(identities):
        raise WorkbenchError("Selected security identities are missing or duplicated.")
    if len(set(tickers)) != len(tickers):
        raise WorkbenchError("Selected ticker symbols are ambiguous; no company was substituted.")
    for selected_company in selected:
        matches = [company for company in companies if company.ticker == selected_company.ticker]
        if len(matches) != 1 or matches[0] != selected_company:
            raise WorkbenchError(
                f"{selected_company.ticker} changed or has an ambiguous ticker. Reload and reselect."
            )
    catalog = discover_comparison_companies(store)
    eligible: set[str] = set()
    for selected_company in selected:
        catalog_matches = [
            entry for entry in catalog.companies
            if entry.ticker == selected_company.ticker
        ]
        if len(catalog_matches) != 1:
            continue
        eligible_id = catalog_matches[0].latest.underwriting_id
        records = store.list_underwriting(selected_company.ticker)
        if any(
            record.underwriting_id == eligible_id
            and record.security_id == selected_company.security_id
            for record in records
        ):
            eligible.add(selected_company.ticker)
    missing = [ticker for ticker in tickers if ticker not in eligible]
    st.session_state["discovery_comparison_evidence"] = pending
    if missing:
        st.session_state["compare_tickers"] = tickers
        st.session_state["discovery_comparison_message"] = (
            "Using Compare because these securities lack an identity-matched completed "
            "underwriting: " + ", ".join(missing) + ". All selections were retained."
        )
        st.session_state["requested_page"] = "Compare"
    else:
        st.session_state["opportunity_companies"] = tickers
        st.session_state["opportunity_extra_versions"] = []
        for ticker in tickers:
            st.session_state[f"opportunity_version.{ticker}"] = "Latest eligible"
        st.session_state.pop("allocation_workflow", None)
        st.session_state.pop("opportunity_requested_underwriting", None)
        st.session_state["discovery_comparison_message"] = (
            "Using Opportunity Comparison with each selected security's latest eligible frozen underwriting."
        )
        st.session_state["requested_page"] = "Opportunity Comparison"


def _find(
    companies: tuple[PersistedCompany, ...], ticker: str
) -> PersistedCompany | None:
    return next((c for c in companies if c.ticker == ticker), None)


def _company_page(
    usable: tuple[PersistedCompany, ...], provider: str = "sec", db_path: str = ""
) -> None:
    ticker = st.session_state.get("selected_ticker")
    selected = _find(usable, str(ticker)) if ticker else None
    if selected is None:
        st.title("Company")
        st.info("Select a company in the sidebar.")
        return
    detail = _guarded(
        lambda: cached_company_detail(
            selected.ticker,
            selected.content_hash or "",
            provider=provider,
            db_path=db_path,
        )
    )
    if detail is not None:
        try:
            with open_run_source() as source:
                if isinstance(source.store, SqliteStore):
                    projection, latest_projection = select_investment_projection(
                        source.store, selected.ticker
                    )
                    requested = st.session_state.get("company_requested_underwriting")
                    if requested is not None and requested.ticker == selected.ticker:
                        projection = project_underwriting(
                            source.store, selected.ticker, version=requested.version
                        )
                        latest_projection = project_underwriting(source.store, selected.ticker)
                    elif requested is not None:
                        del st.session_state["company_requested_underwriting"]
                else:
                    projection, latest_projection = None, None
        except (UnderwritingError, SummaryError, VariantError, PersistenceError, OSError) as exc:
            st.error(f"Underwriting could not be loaded: {exc}")
            return
        company.render(
            detail,
            projection,
            authoring_source=open_run_source,
            authoring_underwriting=latest_projection,
            pending_underwriting=latest_projection
            if latest_projection is not None
            and projection is not None
            and latest_projection.record != projection.record
            and not is_analysis_complete(latest_projection)
            else None,
        )
    else:
        st.title(f"Company: {selected.ticker}")


def _compare_page(
    usable: tuple[PersistedCompany, ...], provider: str = "sec", db_path: str = ""
) -> None:
    requested = st.session_state.get("compare_tickers", [])
    missing = [ticker for ticker in requested if sum(c.ticker == ticker for c in usable) != 1]
    if missing:
        st.title("Compare")
        st.error(
            "Cannot compare unavailable or ambiguous selections: "
            + ", ".join(missing)
            + ". Remove them or restore their evidence; no substitute was chosen."
        )
        return
    selected = [
        c
        for c in usable
        if c.ticker in set(st.session_state.get("compare_tickers", []))
    ]
    if len(selected) < compare.MIN_COMPANIES:
        compare.render(None)
        return
    table = _guarded(
        lambda: cached_comparison(
            fingerprint(tuple(selected)), provider=provider, db_path=db_path
        )
    )
    compare.render(table)
    evidence = st.session_state.get("discovery_comparison_evidence")
    if evidence is not None and evidence["context"] == (db_path, provider):
        compare.render_discovery_evidence(
            evidence, st.session_state.get("compare_tickers", [])
        )


def _data_quality_page(
    usable: tuple[PersistedCompany, ...],
    prints: tuple[tuple[str, str], ...],
    db_path: str,
    provider: str = "sec",
) -> None:
    standings = cached_coverage_standings(prints, db_path, provider=provider)
    ticker = st.session_state.get("quality_ticker")
    selected = _find(usable, str(ticker)) if ticker else None
    report = (
        _guarded(
            lambda: cached_data_quality(
                selected.ticker,
                selected.content_hash or "",
                provider=provider,
                db_path=db_path,
            )
        )
        if selected is not None
        else None
    )
    data_quality.render(standings, report)


def _guarded(build):  # type: ignore[no-untyped-def]
    """Run a loader, turning an expected data failure into a visible message."""
    try:
        return build()
    except WorkbenchError as exc:
        st.error(str(exc))
    except CanonicalDataError as exc:
        st.error(
            f"OwnerLens refused to derive this company's history rather than "
            f"approximate it: {exc}"
        )
    return None


main()

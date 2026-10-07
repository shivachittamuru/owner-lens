"""Streamlit entry point for the OwnerLens workbench (Feature 7D).

Orchestration only: this module resolves which companies the active store can
serve, hands the already-resolved data to one view, and owns navigation. No
financial decision is made here, and no SEC or FMP request is issued by opening
or navigating the application.

Launch it with ``uv run owner-lens workbench``.
"""

from __future__ import annotations

import streamlit as st

from owner_lens.canonical import CanonicalDataError
from owner_lens.persistence.errors import PersistenceError
from owner_lens.workbench.cache import (
    cached_company_detail,
    cached_comparison,
    cached_coverage_standings,
    cached_data_quality,
    cached_screening,
    clear_caches,
    fingerprint,
    open_run_source,
)
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    load_persisted_companies,
    overview_counts,
)
from owner_lens.workbench.views import (
    company,
    compare,
    data_quality,
    overview,
    screener,
)

__all__ = ["main"]

PAGES = ("Overview", "Screener", "Company", "Compare", "Data Quality")


def main() -> None:
    """Render the workbench."""
    st.set_page_config(page_title="OwnerLens Workbench", page_icon="🔎", layout="wide")

    # The company list is read fresh every run rather than cached, so a
    # re-ingested company's new content hash takes effect immediately and
    # invalidates the derived results that depended on the old payload. One
    # short-lived source per run: a SQLite connection is thread-bound and
    # Streamlit reruns on whichever thread is free.
    try:
        with open_run_source() as source:
            db_path, raw_data_path = source.db_path, source.raw_data_path
            companies = load_persisted_companies(source)
    except (PersistenceError, OSError) as exc:
        st.title("OwnerLens Workbench")
        st.error(
            f"The configured store could not be opened: {exc}\n\n"
            "Check `OWNER_LENS_DB_PATH`, or pass another store with "
            "`uv run owner-lens workbench --db data/ownerlens.db`."
        )
        return

    usable = tuple(c for c in companies if c.available)
    prints = fingerprint(companies)

    page = _sidebar(db_path, raw_data_path, companies, usable)

    if not companies:
        st.title("OwnerLens Workbench")
        st.warning(
            f"No company is persisted in `{db_path}`. Ingest one with "
            "`uv run owner-lens ingest ADBE`, or point the workbench at another "
            "store with `uv run owner-lens workbench --db data/universe_6a.db`."
        )
        return

    results = _guarded(lambda: cached_screening(prints))
    if results is None:
        return

    if page == "Overview":
        overview.render(companies, results, overview_counts(companies, results))
    elif page == "Screener":
        screener.render(results)
    elif page == "Company":
        _company_page(usable)
    elif page == "Compare":
        _compare_page(usable)
    else:
        _data_quality_page(usable, prints, db_path)


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
            f"{len(usable)} of {len(companies)} companies have a readable snapshot."
        )
        st.caption(
            "The workbench reads persisted data only. Fetch fresh SEC data with "
            "`uv run owner-lens ingest TICKER`, then reload below."
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
    st.selectbox(label, options=options, index=index, key=key)


def _multi_picker(companies: tuple[PersistedCompany, ...]) -> None:
    tickers = [c.ticker for c in companies]
    st.multiselect(
        f"Companies ({compare.MIN_COMPANIES}–{compare.MAX_COMPANIES})",
        options=tickers,
        default=st.session_state.get("compare_tickers", tickers[: compare.MIN_COMPANIES]),
        max_selections=compare.MAX_COMPANIES,
        key="compare_tickers",
    )


def _find(companies: tuple[PersistedCompany, ...], ticker: str) -> PersistedCompany | None:
    return next((c for c in companies if c.ticker == ticker), None)


def _company_page(usable: tuple[PersistedCompany, ...]) -> None:
    ticker = st.session_state.get("selected_ticker")
    selected = _find(usable, str(ticker)) if ticker else None
    if selected is None:
        st.title("Company")
        st.info("Select a company in the sidebar.")
        return
    detail = _guarded(
        lambda: cached_company_detail(selected.ticker, selected.content_hash or "")
    )
    if detail is not None:
        company.render(detail)


def _compare_page(usable: tuple[PersistedCompany, ...]) -> None:
    selected = [
        c for c in usable if c.ticker in set(st.session_state.get("compare_tickers", []))
    ]
    if len(selected) < compare.MIN_COMPANIES:
        compare.render(None)
        return
    table = _guarded(lambda: cached_comparison(fingerprint(tuple(selected))))
    compare.render(table)


def _data_quality_page(
    usable: tuple[PersistedCompany, ...],
    prints: tuple[tuple[str, str], ...],
    db_path: str,
) -> None:
    standings = cached_coverage_standings(prints, db_path)
    ticker = st.session_state.get("quality_ticker")
    selected = _find(usable, str(ticker)) if ticker else None
    report = (
        _guarded(lambda: cached_data_quality(selected.ticker, selected.content_hash or ""))
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

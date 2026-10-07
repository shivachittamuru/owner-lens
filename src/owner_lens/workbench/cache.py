"""Streamlit caching for the workbench (Feature 7D).

Everything expensive is cached; the company list is not. That split is what
makes invalidation honest: the company list is re-read from the store on every
run, so a re-ingested company's new content hash appears immediately, changes
the fingerprint every other cache key is built from, and invalidates the derived
entries that depended on the old payload. Caching the list instead would have
reduced the guarantee to "until the user remembers to press Reload".

Cached functions take hashable scalars only and return plain data; no live
handle is ever captured in a cache key or retained as hidden global state. That
is not stylistic. A ``WorkbenchSource`` owns a SQLite connection, SQLite
connections are bound to their creating thread, and Streamlit reruns a script on
whichever thread is free. Each cached function therefore opens its own
short-lived source and closes it, which is affordable precisely because the
expensive results are what gets cached.

The data layer itself stays cache-free and Streamlit-free: this module is the
only place caching is applied.
"""

from __future__ import annotations

import streamlit as st

from owner_lens.screening import ScreeningResult
from owner_lens.workbench.data import (
    DEFAULT_MAX_YEARS,
    CompanyDetail,
    ComparisonTable,
    CoverageStanding,
    DataQualityReport,
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    build_comparison,
    company_detail,
    coverage_standings,
    data_quality_report,
    load_persisted_companies,
    open_source,
    screen_persisted_universe,
)

__all__ = [
    "cached_company_detail",
    "cached_comparison",
    "cached_coverage_standings",
    "cached_data_quality",
    "cached_screening",
    "clear_caches",
    "fingerprint",
    "open_run_source",
]


def open_run_source() -> WorkbenchSource:
    """Open a source for one unit of work. The caller must close it."""
    return open_source()


def fingerprint(
    companies: tuple[PersistedCompany, ...],
) -> tuple[tuple[str, str], ...]:
    """The (ticker, content hash) pairs every derived result depends on.

    This is the cache key for anything built from raw payloads. Re-ingesting a
    company changes its content hash, which changes the fingerprint, which
    invalidates the derived entry instead of serving a stale one.
    """
    return tuple(
        (company.ticker, company.content_hash or "")
        for company in companies
        if company.available
    )


def _select(
    source: WorkbenchSource, wanted: tuple[tuple[str, str], ...]
) -> list[PersistedCompany]:
    """Resolve a fingerprint back to company records, in fingerprint order."""
    by_ticker = {c.ticker: c for c in load_persisted_companies(source)}
    return [
        _verify(by_ticker[ticker], content_hash)
        for ticker, content_hash in wanted
        if ticker in by_ticker
    ]


def _one(
    source: WorkbenchSource, ticker: str, content_hash: str
) -> PersistedCompany:
    company = next(
        (c for c in load_persisted_companies(source) if c.ticker == ticker), None
    )
    if company is None:
        raise WorkbenchError(f"{ticker} is no longer present in {source.db_path}.")
    return _verify(company, content_hash)


def _verify(company: PersistedCompany, content_hash: str) -> PersistedCompany:
    """Refuse to compute against a payload other than the one the key names.

    The cache key names a snapshot. If the store now holds a different one, the
    cached value would be attributed to a payload it was not derived from, so
    this raises instead.
    """
    if company.content_hash != content_hash:
        raise WorkbenchError(
            f"{company.ticker} changed on disk while the workbench was open. "
            "Press 'Reload persisted data' to pick up the new snapshot."
        )
    return company


@st.cache_data(show_spinner="Screening the persisted universe…")
def cached_screening(
    companies: tuple[tuple[str, str], ...], max_years: int = DEFAULT_MAX_YEARS
) -> tuple[ScreeningResult, ...]:
    """Screen every company in the fingerprint."""
    with open_run_source() as source:
        return screen_persisted_universe(
            source, _select(source, companies), max_years=max_years
        )


@st.cache_data(show_spinner="Building company detail…")
def cached_company_detail(
    ticker: str, content_hash: str, max_years: int = DEFAULT_MAX_YEARS
) -> CompanyDetail:
    """One company's full research view, keyed on its exact stored payload."""
    with open_run_source() as source:
        return company_detail(
            source, _one(source, ticker, content_hash), max_years=max_years
        )


@st.cache_data(show_spinner="Comparing companies…")
def cached_comparison(
    companies: tuple[tuple[str, str], ...], max_years: int = DEFAULT_MAX_YEARS
) -> ComparisonTable:
    """The side-by-side table for the companies in the fingerprint."""
    return build_comparison(
        cached_company_detail(ticker, content_hash, max_years)
        for ticker, content_hash in companies
    )


@st.cache_data(show_spinner="Diagnosing coverage…")
def cached_data_quality(
    ticker: str, content_hash: str, max_years: int = DEFAULT_MAX_YEARS
) -> DataQualityReport:
    """One company's coverage diagnosis, keyed on its exact stored payload."""
    with open_run_source() as source:
        return data_quality_report(
            source, _one(source, ticker, content_hash), max_years=max_years
        )


@st.cache_data(show_spinner="Diagnosing coverage across the universe…")
def cached_coverage_standings(
    companies: tuple[tuple[str, str], ...],
    db_path: str,
    max_years: int = DEFAULT_MAX_YEARS,
) -> tuple[CoverageStanding, ...]:
    """Coverage standings for every persisted company, failures included.

    ``db_path`` participates in the key because a company with no readable
    snapshot is absent from the fingerprint yet must still appear in the grid.
    """
    with open_run_source() as source:
        return coverage_standings(
            source, load_persisted_companies(source), max_years=max_years
        )


def clear_caches() -> None:
    """Drop every cached derived result, for example after a re-ingestion."""
    cached_screening.clear()
    cached_company_detail.clear()
    cached_comparison.clear()
    cached_data_quality.clear()
    cached_coverage_standings.clear()


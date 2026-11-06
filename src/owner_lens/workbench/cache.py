"""Streamlit caching for the workbench (Feature 7D).

Everything expensive is cached; the company list is not. That split is what
makes invalidation honest: the company list is re-read from the store on every
run, so a re-ingested company's new content hash appears immediately, changes
the fingerprint every other cache key is built from, and invalidates the derived
entries that depended on the old payload. Caching the list instead would have
reduced the guarantee to "until the user remembers to press Reload".

Cached functions use hashable data keys and return plain data; no live
handle is ever captured in a cache key or retained as hidden global state. That
is not stylistic. A ``WorkbenchSource`` owns a SQLite connection, SQLite
connections are bound to their creating thread, and Streamlit reruns a script on
whichever thread is free. Each cached function therefore opens its own
short-lived source and closes it. The FMP screening loop passes that source as
an excluded, transient argument to per-security cache misses, so it does not
open hundreds of SQLite connections. No source is returned or retained.

The data layer itself stays cache-free and Streamlit-free: this module is the
only place caching is applied.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from owner_lens.candidate_review import CandidateSelection
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.persistence import SqliteStore
from owner_lens.screening import (
    ScreeningBucket,
    ScreeningResult,
    assemble_screening_evidence,
    screen_company,
)
from owner_lens.uncertainty_fragility import (
    UncertaintyFragilityReview,
    load_uncertainty_fragility,
)
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
    load_canonical_history,
    load_persisted_companies,
    open_source,
    screen_persisted_universe,
)
from owner_lens.workbench.discovery import (
    DISPLAY_LIMIT,
    DiscoveryLanes,
    discovery_lanes,
    discovery_price_card,
)

__all__ = [
    "cached_company_detail",
    "cached_comparison",
    "cached_coverage_standings",
    "cached_data_quality",
    "cached_improving_economics_owner_economics",
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
        if company.available or company.provider == "fmp"
    )


def _select(
    source: WorkbenchSource, wanted: tuple[tuple[str, str], ...], provider: str = "sec"
) -> list[PersistedCompany]:
    """Resolve a fingerprint back to company records, in fingerprint order."""
    by_ticker = {c.ticker: c for c in load_persisted_companies(source, provider)}
    return [
        _verify(by_ticker[ticker], content_hash)
        for ticker, content_hash in wanted
        if ticker in by_ticker
    ]


def _one(
    source: WorkbenchSource, ticker: str, content_hash: str, provider: str = "sec"
) -> PersistedCompany:
    company = next(
        (c for c in load_persisted_companies(source, provider) if c.ticker == ticker),
        None,
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
    companies: tuple[tuple[str, str], ...],
    max_years: int = DEFAULT_MAX_YEARS,
    provider: str = "sec",
    db_path: str = "",
) -> tuple[ScreeningResult, ...]:
    """Screen every company in the fingerprint."""
    if provider == "fmp":
        with open_run_source() as source:
            selected = _select(source, companies, provider)
            return tuple(
                sorted(
                    (
                        cached_screening_result(
                            company, max_years, db_path, _source=source
                        )
                        for company in selected
                    ),
                    key=lambda result: result.rank_key,
                )
            )
    with open_run_source() as source:
        return screen_persisted_universe(
            source, _select(source, companies, provider), max_years=max_years
        )


@st.cache_data(show_spinner="Checking recent owner economics…")
def cached_improving_economics_owner_economics(
    companies: tuple[tuple[str, str], ...],
    candidate_tickers: tuple[str, ...],
    db_path: str,
    provider: str = "fmp",
) -> tuple[tuple[str, tuple[OwnerEconomicsRow, ...]], ...]:
    """Load candidate owner economics from the persisted FMP histories only."""
    if provider != "fmp":
        return ()
    with open_run_source() as source:
        selected = _select(source, companies, provider)
        by_ticker = {company.ticker: company for company in selected}
        results: list[tuple[str, tuple[OwnerEconomicsRow, ...]]] = []
        for ticker in candidate_tickers:
            company = by_ticker.get(ticker)
            if company is None:
                continue
            history = load_canonical_history(source, company)
            evidence = assemble_screening_evidence(history)
            results.append((ticker, evidence.owner_economics))
        return tuple(results)


@st.cache_data(show_spinner=False)
def cached_screening_result(
    company: PersistedCompany,
    max_years: int = DEFAULT_MAX_YEARS,
    db_path: str = "",
    *,
    _source: WorkbenchSource,
) -> ScreeningResult:
    history = load_canonical_history(_source, company, max_years=max_years)
    return screen_company(assemble_screening_evidence(history))


@st.cache_data(show_spinner="Reviewing uncertainty and fragility evidence…")
def cached_uncertainty_fragility(
    company: PersistedCompany,
    result: ScreeningResult,
    db_path: str,
    *,
    _source: WorkbenchSource,
) -> UncertaintyFragilityReview:
    """Cache plain independent review evidence; retain no live source."""
    return load_uncertainty_fragility(_source, company, result)


def uncertainty_fragility_reviews(
    companies: tuple[PersistedCompany, ...],
    results: tuple[ScreeningResult, ...],
    db_path: str,
) -> tuple[UncertaintyFragilityReview, ...]:
    """Open one short-lived source for independent per-company cache misses."""
    if not companies:
        return ()
    with open_run_source() as source:
        by_ticker = {
            company.ticker: company
            for company in load_persisted_companies(source, companies[0].provider)
        }
        for company in companies:
            current = by_ticker.get(company.ticker)
            if current is None or current != company:
                raise WorkbenchError(
                    f"{company.ticker} changed; reload persisted data."
                )
        return tuple(
            cached_uncertainty_fragility(
                by_ticker[result.ticker], result, db_path, _source=source
            )
            for result in sorted(results, key=lambda item: item.rank_key)
        )


@st.cache_data(show_spinner="Loading saved discovery price evidence…")
def cached_discovery_price(
    selection: CandidateSelection,
    db_path: str,
    *,
    _source: WorkbenchSource,
) -> dict[str, Any]:
    return discovery_price_card(_source, selection)


def discovery_overview(
    companies: tuple[PersistedCompany, ...],
    results: tuple[ScreeningResult, ...],
    db_path: str,
) -> tuple[DiscoveryLanes, dict[str, dict[str, Any]]]:
    eligible = tuple(
        r.ticker
        for r in results
        if r.bucket in (ScreeningBucket.WATCH, ScreeningBucket.LOW_PRIORITY)
    )
    owners = (
        cached_improving_economics_owner_economics(
            fingerprint(companies),
            eligible,
            db_path,
            companies[0].provider,
        )
        if companies
        else ()
    )
    lanes = discovery_lanes(companies, results, dict(owners))
    with open_run_source() as source:
        current = (
            {
                c.ticker: c
                for c in load_persisted_companies(source, companies[0].provider)
            }
            if companies
            else {}
        )
        if any(current.get(c.ticker) != c for c in companies):
            raise WorkbenchError("Discovery evidence changed; reload persisted data.")
        cards = {
            item.company.ticker: cached_discovery_price(item, db_path, _source=source)
            for item in (
                *lanes.compounders[:DISPLAY_LIMIT],
                *lanes.improving[:DISPLAY_LIMIT],
            )
        }
    return lanes, cards


@st.cache_data(show_spinner="Building company detail…")
def cached_company_detail(
    ticker: str,
    content_hash: str,
    max_years: int = DEFAULT_MAX_YEARS,
    provider: str = "sec",
    db_path: str = "",
) -> CompanyDetail:
    """One company's full research view, keyed on its exact stored payload."""
    with open_run_source() as source:
        return company_detail(
            source, _one(source, ticker, content_hash, provider), max_years=max_years
        )


@st.cache_data(show_spinner="Comparing companies…")
def cached_comparison(
    companies: tuple[tuple[str, str], ...],
    max_years: int = DEFAULT_MAX_YEARS,
    provider: str = "sec",
    db_path: str = "",
) -> ComparisonTable:
    """The side-by-side table for the companies in the fingerprint."""
    return build_comparison(
        cached_company_detail(ticker, content_hash, max_years, provider, db_path)
        for ticker, content_hash in companies
    )


@st.cache_data(show_spinner="Diagnosing coverage…")
def cached_data_quality(
    ticker: str,
    content_hash: str,
    max_years: int = DEFAULT_MAX_YEARS,
    provider: str = "sec",
    db_path: str = "",
) -> DataQualityReport:
    """One company's coverage diagnosis, keyed on its exact stored payload."""
    with open_run_source() as source:
        return data_quality_report(
            source, _one(source, ticker, content_hash, provider), max_years=max_years
        )


@st.cache_data(show_spinner="Diagnosing coverage across the universe…")
def cached_coverage_standings(
    companies: tuple[tuple[str, str], ...],
    db_path: str,
    max_years: int = DEFAULT_MAX_YEARS,
    provider: str = "sec",
) -> tuple[CoverageStanding, ...]:
    """Coverage standings for every persisted company, failures included.

    ``db_path`` participates in the key because a company with no readable
    snapshot is absent from the fingerprint yet must still appear in the grid.
    """
    with open_run_source() as source:
        if provider == "fmp":
            if not isinstance(source.store, SqliteStore):
                raise WorkbenchError("FMP coverage requires the SQLite store.")
            states = source.store.list_security_refresh_state()
            results = {
                result.ticker: result
                for result in cached_screening(companies, max_years, provider, db_path)
            }
            return tuple(
                CoverageStanding(
                    company,
                    results[company.ticker].coverage_class.value,
                    (),
                    "; ".join(
                        reason.value
                        for reason in results[company.ticker].coverage_reasons
                    )
                    or None,
                    tuple(
                        state
                        for state in states
                        if state.security_id == company.security_id
                    ),
                )
                for company in load_persisted_companies(source, provider)
            )
        return coverage_standings(
            source, load_persisted_companies(source, provider), max_years=max_years
        )


def clear_caches() -> None:
    """Drop every cached derived result, for example after a re-ingestion."""
    cached_screening.clear()
    cached_screening_result.clear()
    cached_company_detail.clear()
    cached_comparison.clear()
    cached_data_quality.clear()
    cached_coverage_standings.clear()
    cached_improving_economics_owner_economics.clear()
    cached_uncertainty_fragility.clear()
    cached_discovery_price.clear()

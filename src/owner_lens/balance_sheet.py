"""Adobe fiscal-year-end balance-sheet normalization from raw SEC Company Facts.

This module supports OwnerLens Slice 1E. Balance-sheet facts are instant
observations at a fiscal-year-end date, not duration facts. They are selected
through the shared ``_annual`` instant path, which stays explicitly distinct
from duration selection. This module supplies the balance-sheet concept
preference orders and thin public normalizers. It is deterministic and offline.
"""

from __future__ import annotations

from typing import Any, Final

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    SUPPORTED_TICKER,
    AmbiguousValueError,
    ConceptNotFoundError,
    MalformedFactsError,
    UnsupportedTickerError,
    ensure_supported_ticker,
    select_instant_series,
    us_gaap_concepts,
)
from owner_lens.reported import AnnualSeries, MetricSpec

CASH: Final = MetricSpec("cash", ("CashAndCashEquivalentsAtCarryingValue",))
SHORT_TERM_INVESTMENTS: Final = MetricSpec(
    "short_term_investments", ("ShortTermInvestments",)
)
CURRENT_DEBT: Final = MetricSpec("current_debt", ("DebtCurrent",))
LONG_TERM_DEBT: Final = MetricSpec("long_term_debt", ("LongTermDebt",))
TOTAL_ASSETS: Final = MetricSpec("total_assets", ("Assets",))
TOTAL_EQUITY: Final = MetricSpec("total_equity", ("StockholdersEquity",))

__all__ = [
    "CASH",
    "CURRENT_DEBT",
    "LONG_TERM_DEBT",
    "SHORT_TERM_INVESTMENTS",
    "TOTAL_ASSETS",
    "TOTAL_EQUITY",
    "AmbiguousValueError",
    "ConceptNotFoundError",
    "MalformedFactsError",
    "UnsupportedTickerError",
    "normalize_annual_instant",
    "normalize_cash",
    "normalize_current_debt",
    "normalize_long_term_debt",
    "normalize_short_term_investments",
    "normalize_total_assets",
    "normalize_total_equity",
]


def normalize_annual_instant(
    raw_facts: dict[str, Any],
    spec: MetricSpec,
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive a canonical fiscal-year-end instant series for one metric."""
    normalized_ticker = ensure_supported_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_instant_series(
        us_gaap,
        spec.concept_preference,
        max_years=max_years,
        concept_error=ConceptNotFoundError,
        ambiguity_error=AmbiguousValueError,
        unit=spec.unit,
    )
    return AnnualSeries(
        metric=spec.metric,
        ticker=normalized_ticker,
        concept=concept,
        unit=spec.unit,
        observations=observations,
    )


def normalize_cash(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end cash series."""
    return normalize_annual_instant(raw_facts, CASH, ticker=ticker, max_years=max_years)


def normalize_short_term_investments(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end short-term investments series."""
    return normalize_annual_instant(
        raw_facts, SHORT_TERM_INVESTMENTS, ticker=ticker, max_years=max_years
    )


def normalize_current_debt(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end current debt series."""
    return normalize_annual_instant(
        raw_facts, CURRENT_DEBT, ticker=ticker, max_years=max_years
    )


def normalize_long_term_debt(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end long-term debt series."""
    return normalize_annual_instant(
        raw_facts, LONG_TERM_DEBT, ticker=ticker, max_years=max_years
    )


def normalize_total_assets(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end total assets series."""
    return normalize_annual_instant(
        raw_facts, TOTAL_ASSETS, ticker=ticker, max_years=max_years
    )


def normalize_total_equity(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical fiscal-year-end total stockholders' equity series."""
    return normalize_annual_instant(
        raw_facts, TOTAL_EQUITY, ticker=ticker, max_years=max_years
    )

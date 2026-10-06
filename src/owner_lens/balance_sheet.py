"""Adobe fiscal-year-end balance-sheet normalization from raw SEC Company Facts.

This module supports OwnerLens Slice 1E. Balance-sheet facts are instant
observations at a fiscal-year-end date, not duration facts. They are selected
through the shared ``_annual`` instant path, which stays explicitly distinct
from duration selection. This module supplies the balance-sheet concept
preference orders and thin public normalizers. It is deterministic and offline.
"""

from __future__ import annotations

from typing import Any

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    DEFAULT_TICKER,
    AmbiguousValueError,
    ConceptNotFoundError,
    MalformedFactsError,
    canonicalize_ticker,
    has_annual_history,
    select_instant_series,
    us_gaap_concepts,
)
from owner_lens.metrics import (
    CASH,
    CURRENT_DEBT,
    LONG_TERM_DEBT,
    SHORT_TERM_INVESTMENTS,
    TOTAL_ASSETS,
    TOTAL_EQUITY,
    CanonicalMetricDefinition,
    resolve_concepts,
)
from owner_lens.reported import AnnualSeries

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
    definition: CanonicalMetricDefinition,
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive a canonical fiscal-year-end instant series for one metric and company."""
    normalized_ticker = canonicalize_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_instant_series(
        us_gaap,
        resolve_concepts(definition, normalized_ticker),
        max_years=max_years,
        concept_error=ConceptNotFoundError,
        ambiguity_error=AmbiguousValueError,
        unit=definition.unit,
    )
    return AnnualSeries(
        metric=definition.name,
        ticker=normalized_ticker,
        concept=concept,
        unit=definition.unit,
        observations=observations,
    )


def normalize_cash(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical fiscal-year-end cash series."""
    return normalize_annual_instant(raw_facts, CASH, ticker=ticker, max_years=max_years)


def normalize_short_term_investments(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical short-term investments series, tolerant of absence.

    A company that reports no short-term-investments concept (for example, Visa,
    whose investment securities are deliberately not treated as corporate excess
    cash) returns an empty series, so cash-plus-short-term-investments equals
    cash and an absent concept stays distinct from a reported zero. A concept
    reported only in stale years is not treated as absent: the stale-only
    ``ConceptNotFoundError`` propagates (unsupported).
    """
    normalized_ticker = canonicalize_ticker(ticker)
    try:
        return normalize_annual_instant(
            raw_facts, SHORT_TERM_INVESTMENTS, ticker=ticker, max_years=max_years
        )
    except ConceptNotFoundError:
        if has_annual_history(
            us_gaap_concepts(raw_facts),
            resolve_concepts(SHORT_TERM_INVESTMENTS, normalized_ticker),
            instant=True,
            unit=SHORT_TERM_INVESTMENTS.unit,
        ):
            raise
        return AnnualSeries(
            metric=SHORT_TERM_INVESTMENTS.name,
            ticker=normalized_ticker,
            concept="",
            unit=SHORT_TERM_INVESTMENTS.unit,
            observations=(),
        )


def normalize_current_debt(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical fiscal-year-end current debt series."""
    return normalize_annual_instant(
        raw_facts, CURRENT_DEBT, ticker=ticker, max_years=max_years
    )


def normalize_long_term_debt(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical fiscal-year-end long-term debt series."""
    return normalize_annual_instant(
        raw_facts, LONG_TERM_DEBT, ticker=ticker, max_years=max_years
    )


def normalize_total_assets(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical fiscal-year-end total assets series."""
    return normalize_annual_instant(
        raw_facts, TOTAL_ASSETS, ticker=ticker, max_years=max_years
    )


def normalize_total_equity(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical fiscal-year-end total stockholders' equity series."""
    return normalize_annual_instant(
        raw_facts, TOTAL_EQUITY, ticker=ticker, max_years=max_years
    )

"""Generic annual reported-metric normalization for OwnerLens.

This module supports OwnerLens Slice 1D. Slices 1B and 1C each wrote a
metric-specific wrapper; with several more duration-based facts, that pattern is
the duplication that no longer scales. This module replaces it with one
spec-driven normalizer over the shared ``_annual`` primitive, plus documented
metric specifications for net income, operating cash flow, capital expenditures,
and diluted weighted-average shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    DEFAULT_TICKER,
    AmbiguousValueError,
    AnnualObservation,
    ConceptNotFoundError,
    MalformedFactsError,
    canonicalize_ticker,
    select_annual_series,
    us_gaap_concepts,
)
from owner_lens.metrics import (
    CAPITAL_EXPENDITURES,
    DILUTED_SHARES,
    DIVIDENDS_PAID,
    INCOME_TAX_EXPENSE,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    PRETAX_INCOME,
    REPURCHASES,
    STOCK_BASED_COMPENSATION,
    CanonicalMetricDefinition,
    resolve_concepts,
)

__all__ = [
    "CAPITAL_EXPENDITURES",
    "DILUTED_SHARES",
    "DIVIDENDS_PAID",
    "INCOME_TAX_EXPENSE",
    "NET_INCOME",
    "OPERATING_CASH_FLOW",
    "PRETAX_INCOME",
    "REPURCHASES",
    "STOCK_BASED_COMPENSATION",
    "AmbiguousValueError",
    "AnnualSeries",
    "ConceptNotFoundError",
    "MalformedFactsError",
    "normalize_annual_metric",
    "normalize_capital_expenditures",
    "normalize_diluted_shares",
    "normalize_dividends_paid",
    "normalize_income_tax_expense",
    "normalize_net_income",
    "normalize_operating_cash_flow",
    "normalize_pretax_income",
    "normalize_repurchases",
    "normalize_stock_based_compensation",
]


@dataclass(frozen=True)
class AnnualSeries:
    """The ordered canonical annual series for one reported metric."""

    metric: str
    ticker: str
    concept: str
    unit: str
    observations: tuple[AnnualObservation, ...]



def normalize_annual_metric(
    raw_facts: dict[str, Any],
    definition: CanonicalMetricDefinition,
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive a canonical annual series for one reported metric and company."""
    normalized_ticker = canonicalize_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_annual_series(
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


def normalize_net_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual net income series."""
    return normalize_annual_metric(raw_facts, NET_INCOME, ticker=ticker, max_years=max_years)


def normalize_operating_cash_flow(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual operating cash flow series."""
    return normalize_annual_metric(
        raw_facts, OPERATING_CASH_FLOW, ticker=ticker, max_years=max_years
    )


def normalize_capital_expenditures(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual capital expenditures series.

    The reported value is preserved as supplied by the SEC; the positive
    magnitude used for free cash flow is applied in the derivation step.
    """
    return normalize_annual_metric(
        raw_facts, CAPITAL_EXPENDITURES, ticker=ticker, max_years=max_years
    )


def normalize_diluted_shares(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual diluted weighted-average shares series."""
    return normalize_annual_metric(
        raw_facts, DILUTED_SHARES, ticker=ticker, max_years=max_years
    )


def normalize_income_tax_expense(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual income tax expense series."""
    return normalize_annual_metric(
        raw_facts, INCOME_TAX_EXPENSE, ticker=ticker, max_years=max_years
    )


def normalize_pretax_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual pretax income series."""
    return normalize_annual_metric(
        raw_facts, PRETAX_INCOME, ticker=ticker, max_years=max_years
    )


def normalize_repurchases(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual common-stock repurchase cash outflow.

    The value is the reported positive cash-outflow magnitude; it is never
    inferred from share-count or treasury-stock changes.
    """
    return normalize_annual_metric(
        raw_facts, REPURCHASES, ticker=ticker, max_years=max_years
    )


def normalize_stock_based_compensation(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual stock-based compensation expense."""
    return normalize_annual_metric(
        raw_facts, STOCK_BASED_COMPENSATION, ticker=ticker, max_years=max_years
    )


def normalize_dividends_paid(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive the canonical annual common dividends paid, tolerant of absence.

    A company with no dividend concept (for example, Adobe) returns an empty
    series (the fact is structurally absent) rather than raising, preserving the
    distinction between a company with no dividend program and unavailable data.
    """
    normalized_ticker = canonicalize_ticker(ticker)
    try:
        return normalize_annual_metric(
            raw_facts, DIVIDENDS_PAID, ticker=ticker, max_years=max_years
        )
    except ConceptNotFoundError:
        return AnnualSeries(
            metric=DIVIDENDS_PAID.name,
            ticker=normalized_ticker,
            concept="",
            unit=DIVIDENDS_PAID.unit,
            observations=(),
        )

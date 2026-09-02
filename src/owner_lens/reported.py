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
from typing import Any, Final

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    SUPPORTED_TICKER,
    TARGET_UNIT,
    AmbiguousValueError,
    AnnualObservation,
    ConceptNotFoundError,
    MalformedFactsError,
    UnsupportedTickerError,
    ensure_supported_ticker,
    select_annual_series,
    us_gaap_concepts,
)

SHARES_UNIT: Final = "shares"

__all__ = [
    "CAPITAL_EXPENDITURES",
    "DILUTED_SHARES",
    "INCOME_TAX_EXPENSE",
    "NET_INCOME",
    "OPERATING_CASH_FLOW",
    "PRETAX_INCOME",
    "AmbiguousValueError",
    "AnnualSeries",
    "ConceptNotFoundError",
    "MalformedFactsError",
    "MetricSpec",
    "UnsupportedTickerError",
    "normalize_annual_metric",
    "normalize_capital_expenditures",
    "normalize_diluted_shares",
    "normalize_income_tax_expense",
    "normalize_net_income",
    "normalize_operating_cash_flow",
    "normalize_pretax_income",
]


@dataclass(frozen=True)
class MetricSpec:
    """How a reported metric is selected from Company Facts."""

    metric: str
    concept_preference: tuple[str, ...]
    unit: str = TARGET_UNIT


@dataclass(frozen=True)
class AnnualSeries:
    """The ordered canonical annual series for one reported metric."""

    metric: str
    ticker: str
    concept: str
    unit: str
    observations: tuple[AnnualObservation, ...]


# Concept preference orders verified against Adobe's live Company Facts.
NET_INCOME: Final = MetricSpec("net_income", ("NetIncomeLoss",))
OPERATING_CASH_FLOW: Final = MetricSpec(
    "operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",)
)
CAPITAL_EXPENDITURES: Final = MetricSpec(
    "capital_expenditures",
    ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
)
DILUTED_SHARES: Final = MetricSpec(
    "diluted_shares",
    ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    unit=SHARES_UNIT,
)
INCOME_TAX_EXPENSE: Final = MetricSpec(
    "income_tax_expense", ("IncomeTaxExpenseBenefit",)
)
PRETAX_INCOME: Final = MetricSpec(
    "pretax_income",
    (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
)


def normalize_annual_metric(
    raw_facts: dict[str, Any],
    spec: MetricSpec,
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive a canonical annual series for one reported metric."""
    normalized_ticker = ensure_supported_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_annual_series(
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


def normalize_net_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual net income series."""
    return normalize_annual_metric(raw_facts, NET_INCOME, ticker=ticker, max_years=max_years)


def normalize_operating_cash_flow(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual operating cash flow series."""
    return normalize_annual_metric(
        raw_facts, OPERATING_CASH_FLOW, ticker=ticker, max_years=max_years
    )


def normalize_capital_expenditures(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual capital expenditures series.

    The reported value is preserved as supplied by the SEC; the positive
    magnitude used for free cash flow is applied in the derivation step.
    """
    return normalize_annual_metric(
        raw_facts, CAPITAL_EXPENDITURES, ticker=ticker, max_years=max_years
    )


def normalize_diluted_shares(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual diluted weighted-average shares series."""
    return normalize_annual_metric(
        raw_facts, DILUTED_SHARES, ticker=ticker, max_years=max_years
    )


def normalize_income_tax_expense(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual income tax expense series."""
    return normalize_annual_metric(
        raw_facts, INCOME_TAX_EXPENSE, ticker=ticker, max_years=max_years
    )


def normalize_pretax_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualSeries:
    """Derive Adobe's canonical annual pretax income series."""
    return normalize_annual_metric(
        raw_facts, PRETAX_INCOME, ticker=ticker, max_years=max_years
    )

"""Adobe annual revenue normalization from raw SEC Company Facts.

This module supports OwnerLens Slice 1B: turning the raw SEC Company Facts
payload for ADBE into a canonical annual revenue series. It is deterministic and
offline. Selection behavior is shared with other annual metrics through the
internal ``_annual`` primitive; this module supplies the revenue concept
preference order and revenue-specific failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    DEFAULT_TICKER,
    AnnualObservation,
    MalformedFactsError,
    canonicalize_ticker,
    select_annual_series,
    us_gaap_concepts,
)
from owner_lens.canonical import MetricInvalidError, MetricUnsupportedError
from owner_lens.metrics import REVENUE, resolve_concepts

REVENUE_CONCEPT_PREFERENCE: Final = REVENUE.default_concepts

# Re-exported so callers keep referring to the shared reported-fact type.
AnnualRevenueObservation = AnnualObservation

__all__ = [
    "REVENUE_CONCEPT_PREFERENCE",
    "AmbiguousRevenueError",
    "AnnualRevenueObservation",
    "AnnualRevenueSeries",
    "MalformedFactsError",
    "RevenueConceptNotFoundError",
    "RevenueNormalizationError",
    "normalize_annual_revenue",
]


class RevenueNormalizationError(Exception):
    """Base class for revenue-specific normalization failures."""


class RevenueConceptNotFoundError(RevenueNormalizationError, MetricUnsupportedError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousRevenueError(RevenueNormalizationError, MetricInvalidError):
    """Raised when a fiscal year has conflicting distinct full-year values."""


@dataclass(frozen=True)
class AnnualRevenueSeries:
    """The ordered canonical annual revenue series for one company."""

    ticker: str
    concept: str
    observations: tuple[AnnualObservation, ...]


def normalize_annual_revenue(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualRevenueSeries:
    """Derive a canonical annual revenue series from raw Company Facts."""
    normalized_ticker = canonicalize_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_annual_series(
        us_gaap,
        resolve_concepts(REVENUE, normalized_ticker),
        max_years=max_years,
        concept_error=RevenueConceptNotFoundError,
        ambiguity_error=AmbiguousRevenueError,
    )
    return AnnualRevenueSeries(
        ticker=normalized_ticker,
        concept=concept,
        observations=observations,
    )

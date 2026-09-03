"""Adobe annual operating income normalization from raw SEC Company Facts.

This module supports OwnerLens Slice 1C: turning the raw SEC Company Facts
payload for ADBE into a canonical annual operating income series. It reuses the
shared ``_annual`` selection primitive and supplies the operating-income concept
preference order and operating-income-specific failures. It is deterministic and
offline.
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
from owner_lens.metrics import OPERATING_INCOME, resolve_concepts

OPERATING_INCOME_CONCEPT_PREFERENCE: Final = OPERATING_INCOME.default_concepts

# Re-exported so callers keep referring to the shared reported-fact type.
AnnualOperatingIncomeObservation = AnnualObservation

__all__ = [
    "OPERATING_INCOME_CONCEPT_PREFERENCE",
    "AmbiguousOperatingIncomeError",
    "AnnualOperatingIncomeObservation",
    "AnnualOperatingIncomeSeries",
    "MalformedFactsError",
    "OperatingIncomeConceptNotFoundError",
    "OperatingIncomeNormalizationError",
    "normalize_annual_operating_income",
]


class OperatingIncomeNormalizationError(Exception):
    """Base class for operating-income-specific normalization failures."""


class OperatingIncomeConceptNotFoundError(OperatingIncomeNormalizationError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousOperatingIncomeError(OperatingIncomeNormalizationError):
    """Raised when a fiscal year has conflicting distinct full-year values."""


@dataclass(frozen=True)
class AnnualOperatingIncomeSeries:
    """The ordered canonical annual operating income series for one company."""

    ticker: str
    concept: str
    observations: tuple[AnnualObservation, ...]


def normalize_annual_operating_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualOperatingIncomeSeries:
    """Derive a canonical annual operating income series from Company Facts."""
    normalized_ticker = canonicalize_ticker(ticker)
    us_gaap = us_gaap_concepts(raw_facts)
    concept, observations = select_annual_series(
        us_gaap,
        resolve_concepts(OPERATING_INCOME, normalized_ticker),
        max_years=max_years,
        concept_error=OperatingIncomeConceptNotFoundError,
        ambiguity_error=AmbiguousOperatingIncomeError,
    )
    return AnnualOperatingIncomeSeries(
        ticker=normalized_ticker,
        concept=concept,
        observations=observations,
    )

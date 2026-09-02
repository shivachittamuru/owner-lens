"""Adobe annual revenue normalization from raw SEC Company Facts.

This module supports OwnerLens Slice 1B: turning the raw SEC Company Facts
payload for ADBE into a canonical annual revenue series. It is deterministic
and offline. It performs no network access and invents no values: each
observation is a preserved source fact with full provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

SUPPORTED_TICKER: Final = "ADBE"
TARGET_UNIT: Final = "USD"
ANNUAL_FISCAL_PERIOD: Final = "FY"
REVENUE_CONCEPT_PREFERENCE: Final = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
DEFAULT_MAX_YEARS: Final = 5
# Adobe uses a 52-to-53 week fiscal calendar, so full years span ~363-371 days.
_MIN_FULL_YEAR_DAYS: Final = 350
_MAX_FULL_YEAR_DAYS: Final = 380
_REQUIRED_FACT_FIELDS: Final = ("start", "end", "val", "fp", "form", "filed", "accn")


class RevenueNormalizationError(Exception):
    """Base class for every annual revenue normalization failure."""


class UnsupportedTickerError(RevenueNormalizationError):
    """Raised when the requested ticker is not supported by this slice."""


class MalformedFactsError(RevenueNormalizationError):
    """Raised when the payload lacks a usable us-gaap fact structure."""


class RevenueConceptNotFoundError(RevenueNormalizationError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousRevenueError(RevenueNormalizationError):
    """Raised when a fiscal year has conflicting distinct full-year values."""


@dataclass(frozen=True)
class AnnualRevenueObservation:
    """One canonical full fiscal-year revenue value with SEC provenance."""

    concept: str
    unit: str
    fiscal_year: int
    fiscal_period: str
    period_start: date
    period_end: date
    form: str
    filed: date
    accession: str
    value: int


@dataclass(frozen=True)
class AnnualRevenueSeries:
    """The ordered canonical annual revenue series for one company."""

    ticker: str
    concept: str
    observations: tuple[AnnualRevenueObservation, ...]


@dataclass(frozen=True)
class _Candidate:
    """An internal qualifying full-year fact before per-year resolution."""

    fiscal_year: int
    period_start: date
    period_end: date
    fiscal_period: str
    form: str
    filed: date
    accession: str
    value: int


def normalize_annual_revenue(
    raw_facts: dict[str, Any],
    *,
    ticker: str = SUPPORTED_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> AnnualRevenueSeries:
    """Derive a canonical annual revenue series from raw Company Facts."""
    normalized_ticker = ticker.strip().upper()
    if normalized_ticker != SUPPORTED_TICKER:
        raise UnsupportedTickerError(
            f"Unsupported ticker {ticker!r}; only {SUPPORTED_TICKER} is "
            "supported by this feature."
        )

    us_gaap = _us_gaap_concepts(raw_facts)
    concept, candidates = _select_concept(us_gaap)
    by_year = _group_by_fiscal_year(candidates)

    selected_years = sorted(by_year, reverse=True)[:max_years]
    observations = tuple(
        _resolve_year(concept, year, by_year[year])
        for year in selected_years
    )
    return AnnualRevenueSeries(
        ticker=normalized_ticker,
        concept=concept,
        observations=observations,
    )


def _us_gaap_concepts(raw_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_facts, dict):
        raise MalformedFactsError("Company Facts payload is not an object.")
    facts = raw_facts.get("facts")
    if not isinstance(facts, dict):
        raise MalformedFactsError("Company Facts payload has no facts object.")
    us_gaap = facts.get("us-gaap")
    if not isinstance(us_gaap, dict):
        raise MalformedFactsError("Company Facts payload has no us-gaap taxonomy.")
    return us_gaap


def _select_concept(
    us_gaap: dict[str, Any],
) -> tuple[str, list[_Candidate]]:
    for concept in REVENUE_CONCEPT_PREFERENCE:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        candidates = _qualifying_candidates(concept, entry)
        if candidates:
            return concept, candidates
    raise RevenueConceptNotFoundError(
        "No supported US-GAAP revenue concept with a full fiscal-year "
        f"observation was found. Tried: {', '.join(REVENUE_CONCEPT_PREFERENCE)}."
    )


def _qualifying_candidates(
    concept: str,
    entry: dict[str, Any],
) -> list[_Candidate]:
    units = entry.get("units")
    if not isinstance(units, dict):
        return []
    facts = units.get(TARGET_UNIT)
    if not isinstance(facts, list):
        return []

    candidates: list[_Candidate] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("fp") != ANNUAL_FISCAL_PERIOD:
            continue
        candidates.append(_candidate_from_fact(concept, fact))
    return candidates


def _candidate_from_fact(concept: str, fact: dict[str, Any]) -> _Candidate:
    missing = [field for field in _REQUIRED_FACT_FIELDS if field not in fact]
    if missing:
        raise MalformedFactsError(
            f"Annual {concept} fact is missing required field(s): "
            f"{', '.join(missing)}."
        )
    try:
        period_start = date.fromisoformat(fact["start"])
        period_end = date.fromisoformat(fact["end"])
        filed = date.fromisoformat(fact["filed"])
    except (TypeError, ValueError) as exc:
        raise MalformedFactsError(
            f"Annual {concept} fact has an invalid date: {exc}"
        ) from exc

    value = fact["val"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedFactsError(
            f"Annual {concept} fact has a non-integer value: {value!r}"
        )

    duration_days = (period_end - period_start).days
    if not _MIN_FULL_YEAR_DAYS <= duration_days <= _MAX_FULL_YEAR_DAYS:
        # A FY-tagged period outside the full-year window is a partial period.
        return _NON_FULL_YEAR

    return _Candidate(
        fiscal_year=period_end.year,
        period_start=period_start,
        period_end=period_end,
        fiscal_period=ANNUAL_FISCAL_PERIOD,
        form=str(fact["form"]),
        filed=filed,
        accession=str(fact["accn"]),
        value=value,
    )


# Sentinel marking a FY-tagged fact whose duration is not a full fiscal year.
_NON_FULL_YEAR: Final = _Candidate(
    fiscal_year=0,
    period_start=date.min,
    period_end=date.min,
    fiscal_period="",
    form="",
    filed=date.min,
    accession="",
    value=0,
)


def _group_by_fiscal_year(
    candidates: list[_Candidate],
) -> dict[int, list[_Candidate]]:
    by_year: dict[int, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate is _NON_FULL_YEAR:
            continue
        by_year.setdefault(candidate.fiscal_year, []).append(candidate)
    return by_year


def _resolve_year(
    concept: str,
    fiscal_year: int,
    candidates: list[_Candidate],
) -> AnnualRevenueObservation:
    distinct_values = {candidate.value for candidate in candidates}
    if len(distinct_values) > 1:
        raise AmbiguousRevenueError(
            f"Fiscal year {fiscal_year} has conflicting {concept} values: "
            f"{sorted(distinct_values)}."
        )
    # Identical comparative repeats collapse to the earliest original filing.
    retained = min(candidates, key=lambda c: (c.filed, c.accession))
    return AnnualRevenueObservation(
        concept=concept,
        unit=TARGET_UNIT,
        fiscal_year=fiscal_year,
        fiscal_period=retained.fiscal_period,
        period_start=retained.period_start,
        period_end=retained.period_end,
        form=retained.form,
        filed=retained.filed,
        accession=retained.accession,
        value=retained.value,
    )

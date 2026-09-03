"""Shared annual-series selection primitive for OwnerLens metrics.

Internal module. Revenue and operating-income normalization concretely
duplicated this logic, so it is extracted here: full fiscal-year filtering,
fiscal-year derivation from the period end date, comparative deduplication with
earliest-filed provenance, and preference-ordered concept selection. Each metric
module supplies its own concept preference list and typed error classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

DEFAULT_TICKER: Final = "ADBE"
TARGET_UNIT: Final = "USD"
ANNUAL_FISCAL_PERIOD: Final = "FY"
DEFAULT_MAX_YEARS: Final = 5
# Adobe uses a 52-to-53 week fiscal calendar, so full years span ~363-371 days.
_MIN_FULL_YEAR_DAYS: Final = 350
_MAX_FULL_YEAR_DAYS: Final = 380
_REQUIRED_FACT_FIELDS: Final = ("start", "end", "val", "fp", "form", "filed", "accn")
_INSTANT_REQUIRED_FACT_FIELDS: Final = ("end", "val", "fp", "form", "filed", "accn")


class AnnualNormalizationError(Exception):
    """Base class for shared annual-normalization failures."""


class MalformedFactsError(AnnualNormalizationError):
    """Raised when the payload lacks a usable us-gaap fact structure."""


class ConceptNotFoundError(AnnualNormalizationError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousValueError(AnnualNormalizationError):
    """Raised when a fiscal year has conflicting distinct full-year values."""


@dataclass(frozen=True)
class AnnualObservation:
    """One canonical full fiscal-year reported value with SEC provenance."""

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


def canonicalize_ticker(ticker: str) -> str:
    """Return the canonical uppercase ticker; no company allow-list is applied.

    A company is "unsupported" for a metric only when no trustworthy concept
    resolves, which surfaces as a typed ConceptNotFoundError, not as a ticker
    rejection.
    """
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("A non-empty ticker is required for normalization.")
    return normalized


def us_gaap_concepts(raw_facts: dict[str, Any]) -> dict[str, Any]:
    """Return the us-gaap taxonomy object or raise if the payload is malformed."""
    if not isinstance(raw_facts, dict):
        raise MalformedFactsError("Company Facts payload is not an object.")
    facts = raw_facts.get("facts")
    if not isinstance(facts, dict):
        raise MalformedFactsError("Company Facts payload has no facts object.")
    us_gaap = facts.get("us-gaap")
    if not isinstance(us_gaap, dict):
        raise MalformedFactsError("Company Facts payload has no us-gaap taxonomy.")
    return us_gaap


def select_annual_series(
    us_gaap: dict[str, Any],
    concept_preference: tuple[str, ...],
    *,
    max_years: int,
    concept_error: type[Exception],
    ambiguity_error: type[Exception],
    unit: str = TARGET_UNIT,
) -> tuple[str, tuple[AnnualObservation, ...]]:
    """Select one concept and resolve its canonical duration annual series."""
    for concept in concept_preference:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        observations = _qualifying_observations(concept, entry, unit)
        if not observations:
            continue
        return concept, _resolve_series(
            concept, observations, max_years, ambiguity_error
        )
    raise concept_error(
        "No supported US-GAAP concept with a full fiscal-year observation was "
        f"found. Tried: {', '.join(concept_preference)}."
    )


def select_instant_series(
    us_gaap: dict[str, Any],
    concept_preference: tuple[str, ...],
    *,
    max_years: int,
    concept_error: type[Exception],
    ambiguity_error: type[Exception],
    unit: str = TARGET_UNIT,
) -> tuple[str, tuple[AnnualObservation, ...]]:
    """Select one concept and resolve its canonical fiscal-year-end instant series.

    Balance-sheet facts are instant (no start date), so they are selected by
    fiscal-period-end semantics rather than a duration window. This keeps the
    instant path explicitly distinct from the duration path above.
    """
    for concept in concept_preference:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        observations = _qualifying_instant_observations(concept, entry, unit)
        if not observations:
            continue
        return concept, _resolve_series(
            concept, observations, max_years, ambiguity_error
        )
    raise concept_error(
        "No supported US-GAAP concept with a fiscal-year-end instant observation "
        f"was found. Tried: {', '.join(concept_preference)}."
    )


def _resolve_series(
    concept: str,
    observations: list[AnnualObservation],
    max_years: int,
    ambiguity_error: type[Exception],
) -> tuple[AnnualObservation, ...]:
    by_year: dict[int, list[AnnualObservation]] = {}
    for observation in observations:
        by_year.setdefault(observation.fiscal_year, []).append(observation)
    years = sorted(by_year, reverse=True)[:max_years]
    return tuple(
        _resolve_year(concept, year, by_year[year], ambiguity_error)
        for year in years
    )


def _qualifying_observations(
    concept: str,
    entry: dict[str, Any],
    unit: str,
) -> list[AnnualObservation]:
    units = entry.get("units")
    if not isinstance(units, dict):
        return []
    facts = units.get(unit)
    if not isinstance(facts, list):
        return []

    observations: list[AnnualObservation] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        # Duration facts have a start date; skip instant facts.
        if "start" not in fact:
            continue
        if fact.get("fp") != ANNUAL_FISCAL_PERIOD:
            continue
        observation = _observation_from_fact(concept, fact, unit)
        if observation is not None:
            observations.append(observation)
    return observations


def _qualifying_instant_observations(
    concept: str,
    entry: dict[str, Any],
    unit: str,
) -> list[AnnualObservation]:
    units = entry.get("units")
    if not isinstance(units, dict):
        return []
    facts = units.get(unit)
    if not isinstance(facts, list):
        return []

    observations: list[AnnualObservation] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        # Instant facts have no start date; require annual 10-K fiscal-year-end.
        if "start" in fact:
            continue
        if fact.get("fp") != ANNUAL_FISCAL_PERIOD:
            continue
        form = fact.get("form")
        if not isinstance(form, str) or not form.startswith("10-K"):
            continue
        observation = _instant_observation_from_fact(concept, fact, unit)
        observations.append(observation)
    return observations


def _observation_from_fact(
    concept: str,
    fact: dict[str, Any],
    unit: str,
) -> AnnualObservation | None:
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
        return None

    return AnnualObservation(
        concept=concept,
        unit=unit,
        fiscal_year=period_end.year,
        fiscal_period=ANNUAL_FISCAL_PERIOD,
        period_start=period_start,
        period_end=period_end,
        form=str(fact["form"]),
        filed=filed,
        accession=str(fact["accn"]),
        value=value,
    )


def _instant_observation_from_fact(
    concept: str,
    fact: dict[str, Any],
    unit: str,
) -> AnnualObservation:
    missing = [field for field in _INSTANT_REQUIRED_FACT_FIELDS if field not in fact]
    if missing:
        raise MalformedFactsError(
            f"Instant {concept} fact is missing required field(s): "
            f"{', '.join(missing)}."
        )
    try:
        period_end = date.fromisoformat(fact["end"])
        filed = date.fromisoformat(fact["filed"])
    except (TypeError, ValueError) as exc:
        raise MalformedFactsError(
            f"Instant {concept} fact has an invalid date: {exc}"
        ) from exc

    value = fact["val"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedFactsError(
            f"Instant {concept} fact has a non-integer value: {value!r}"
        )

    # Instant facts have a single point in time; start equals end.
    return AnnualObservation(
        concept=concept,
        unit=unit,
        fiscal_year=period_end.year,
        fiscal_period=ANNUAL_FISCAL_PERIOD,
        period_start=period_end,
        period_end=period_end,
        form=str(fact["form"]),
        filed=filed,
        accession=str(fact["accn"]),
        value=value,
    )


def _resolve_year(
    concept: str,
    fiscal_year: int,
    observations: list[AnnualObservation],
    ambiguity_error: type[Exception],
) -> AnnualObservation:
    distinct_values = {observation.value for observation in observations}
    if len(distinct_values) > 1:
        raise ambiguity_error(
            f"Fiscal year {fiscal_year} has conflicting {concept} values: "
            f"{sorted(distinct_values)}."
        )
    # Identical comparative repeats collapse to the earliest original filing.
    return min(observations, key=lambda o: (o.filed, o.accession))

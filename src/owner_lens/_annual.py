"""Shared annual-series selection primitive for OwnerLens metrics.

Internal module. Revenue and operating-income normalization concretely
duplicated this logic, so it is extracted here: full fiscal-year filtering,
fiscal-year derivation from the period end date, comparative deduplication with
earliest-filed provenance, and preference-ordered concept selection. Each metric
module supplies its own concept preference list and typed error classes.

Recency-aware selection (Slice 6B): a concept is eligible only if it covers the
company's latest fiscal year. The reference is the newest full-year ``FY``
duration period end in any 10-K-family filing in the payload (see
``latest_annual_period_end``); a concept is current when its newest qualifying
observation ends within ``RECENCY_TOLERANCE_DAYS`` of that reference. The first
current concept in preference order wins; stale concepts are skipped, and if no
concept is current the metric's ``concept_error`` is raised instead of returning
stale history. Per-company overrides replace the preference tuple before this
rule runs, so they stay authoritative.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from owner_lens.canonical import MetricInvalidError, MetricUnsupportedError

DEFAULT_TICKER: Final = "ADBE"
TARGET_UNIT: Final = "USD"
ANNUAL_FISCAL_PERIOD: Final = "FY"
DEFAULT_MAX_YEARS: Final = 5
# Adobe uses a 52-to-53 week fiscal calendar, so full years span ~363-371 days.
_MIN_FULL_YEAR_DAYS: Final = 350
_MAX_FULL_YEAR_DAYS: Final = 380
_REQUIRED_FACT_FIELDS: Final = ("start", "end", "val", "fp", "form", "filed", "accn")
_INSTANT_REQUIRED_FACT_FIELDS: Final = ("end", "val", "fp", "form", "filed", "accn")
# A concept is current only if its newest observation ends within this many
# days of the company's latest fiscal-year end (absorbs 52/53-week drift).
RECENCY_TOLERANCE_DAYS: Final = 31


class AnnualNormalizationError(Exception):
    """Base class for shared annual-normalization failures."""


class MalformedFactsError(AnnualNormalizationError, MetricInvalidError):
    """Raised when the payload lacks a usable us-gaap fact structure."""


class ConceptNotFoundError(AnnualNormalizationError, MetricUnsupportedError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousValueError(AnnualNormalizationError, MetricInvalidError):
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


def latest_annual_period_end(us_gaap: dict[str, Any]) -> date | None:
    """Return the company's latest fiscal-year end evidenced by its 10-K filings.

    The reference is the newest period end of any full-year (350-380 day) ``FY``
    duration fact filed on a 10-K-family form, across the whole us-gaap
    taxonomy. It is derived only from the company's own reported periods, never
    from today's date. Returns ``None`` when the payload has no such fact (for
    example a registrant with only 10-Q filings), in which case no recency
    filtering is applied.
    """
    cached = _REFERENCE_CACHE.get(id(us_gaap))
    if cached is not None and cached[0] is us_gaap:
        return cached[1]
    latest: date | None = None
    for entry in us_gaap.values():
        units = entry.get("units") if isinstance(entry, dict) else None
        if not isinstance(units, dict):
            continue
        for facts in units.values():
            if not isinstance(facts, list):
                continue
            for fact in facts:
                end = _full_year_10k_end(fact)
                if end is not None and (latest is None or end > latest):
                    latest = end
    _REFERENCE_CACHE.clear()
    _REFERENCE_CACHE[id(us_gaap)] = (us_gaap, latest)
    return latest


# Single-entry memo: the SEC adapter selects all metrics from one payload in a
# row, so the reference scan (~90 ms on a 6 MB payload) runs once per payload
# rather than once per metric. Parsed Company Facts payloads are treated as
# immutable; the stored object reference guards against id() reuse.
_REFERENCE_CACHE: dict[int, tuple[dict[str, Any], date | None]] = {}


def _full_year_10k_end(fact: Any) -> date | None:
    if not isinstance(fact, dict) or fact.get("fp") != ANNUAL_FISCAL_PERIOD:
        return None
    form = fact.get("form")
    if not isinstance(form, str) or not form.startswith("10-K"):
        return None
    start, end = fact.get("start"), fact.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        period_start, period_end = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return None
    if not _MIN_FULL_YEAR_DAYS <= (period_end - period_start).days <= _MAX_FULL_YEAR_DAYS:
        return None
    return period_end


def is_current(
    observations: list[AnnualObservation], reference_end: date | None
) -> bool:
    """Return True when a concept covers the company's latest fiscal year.

    A concept is current when its newest qualifying observation ends within
    ``RECENCY_TOLERANCE_DAYS`` of the company reference fiscal-year end. The
    tolerance absorbs 52/53-week calendar drift but is far shorter than one
    fiscal year, so a concept whose last value is a prior fiscal year is stale.
    Older-year gaps are not penalized: only the newest year must be covered.
    """
    if reference_end is None or not observations:
        return bool(observations)
    newest = max(observation.period_end for observation in observations)
    return (reference_end - newest).days <= RECENCY_TOLERANCE_DAYS


def _select_current(
    us_gaap: dict[str, Any],
    concept_preference: tuple[str, ...],
    qualify: Callable[[str, dict[str, Any], str], list[AnnualObservation]],
    unit: str,
) -> tuple[str, list[AnnualObservation]] | list[str]:
    """Return the first current concept, or the stale-concept descriptions."""
    reference_end = latest_annual_period_end(us_gaap)
    stale: list[str] = []
    for concept in concept_preference:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        observations = qualify(concept, entry, unit)
        if not observations:
            continue
        if is_current(observations, reference_end):
            return concept, observations
        newest = max(observation.period_end for observation in observations)
        stale.append(f"{concept} (last period end {newest.isoformat()})")
    if stale and reference_end is not None:
        stale.append(f"company latest fiscal-year end {reference_end.isoformat()}")
    return stale


def _stale_suffix(stale: list[str]) -> str:
    if not stale:
        return ""
    return " Stale (no value for the latest fiscal year): " + "; ".join(stale) + "."


def has_annual_history(
    us_gaap: dict[str, Any],
    concept_preference: tuple[str, ...],
    *,
    instant: bool,
    unit: str = TARGET_UNIT,
) -> bool:
    """Return True when any preferred concept has qualifying annual history.

    Tolerant-of-absence metrics use this to tell a concept the company never
    reported (structurally absent) from one it reported only in stale years
    (unsupported: the item may have been retagged, so absence cannot be assumed).
    """
    qualify = _qualifying_instant_observations if instant else _qualifying_observations
    return any(
        isinstance(us_gaap.get(concept), dict)
        and bool(qualify(concept, us_gaap[concept], unit))
        for concept in concept_preference
    )


def select_annual_series(
    us_gaap: dict[str, Any],
    concept_preference: tuple[str, ...],
    *,
    max_years: int,
    concept_error: type[Exception],
    ambiguity_error: type[Exception],
    unit: str = TARGET_UNIT,
) -> tuple[str, tuple[AnnualObservation, ...]]:
    """Select the highest-priority current concept and resolve its duration series.

    Concepts are tried in preference order; a concept with qualifying history
    that does not cover the company's latest fiscal year is skipped as stale
    (see ``is_current``). If no concept is current, ``concept_error`` is raised
    rather than returning stale history.
    """
    selected = _select_current(
        us_gaap, concept_preference, _qualifying_observations, unit
    )
    if isinstance(selected, tuple):
        concept, observations = selected
        return concept, _resolve_series(
            concept, observations, max_years, ambiguity_error
        )
    raise concept_error(
        "No supported US-GAAP concept with a full fiscal-year observation was "
        f"found. Tried: {', '.join(concept_preference)}.{_stale_suffix(selected)}"
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
    """Select the highest-priority current concept and resolve its instant series.

    Balance-sheet facts are instant (no start date), so they are selected by
    fiscal-period-end semantics rather than a duration window. This keeps the
    instant path explicitly distinct from the duration path above. The same
    recency rule applies: a concept whose newest year-end balance precedes the
    company's latest fiscal year is stale and is skipped.
    """
    selected = _select_current(
        us_gaap, concept_preference, _qualifying_instant_observations, unit
    )
    if isinstance(selected, tuple):
        concept, observations = selected
        return concept, _resolve_series(
            concept, observations, max_years, ambiguity_error
        )
    raise concept_error(
        "No supported US-GAAP concept with a fiscal-year-end instant observation "
        f"was found. Tried: {', '.join(concept_preference)}.{_stale_suffix(selected)}"
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

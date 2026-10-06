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

Conflict resolution (Slice 6C): when one fiscal year has several distinct
reported values for the selected concept, the year is resolved only if the
conflict is mechanical:

* Precision re-rounding: exactly one value has the fewest trailing zeros (the
  most precise), and every other value equals it rounded half-away-from-zero
  to 10^3..10^6, within the precision its own trailing zeros express. The most
  precise value is kept, from its earliest filing.
* Stock split (share units only): a conflict whose values form a pre-split and
  a post-split group with an integer ratio 2..``MAX_SPLIT_RATIO``, where the
  pre-split value is the post-split value divided by the ratio (exactly or
  re-rounded as above) and every pre-split report was filed before every
  post-split report. Each such conflict evidences a split between those filing
  dates; observations filed on or before the split's last pre-split report are
  scaled by its ratio (cumulatively across splits) to the latest basis, and an
  observation filed between the two reports has an unknown basis and fails.

Anything else, including genuine revisions, reverse or fractional splits, and
contradictory split evidence, raises the metric's ambiguity error unchanged.
Every resolved value carries a ``ConflictResolution`` recording the as-filed
value, the split factor applied, and every superseded value.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
from typing import Any, Final

from owner_lens.canonical import (
    ConflictResolution,
    ConflictResolutionKind,
    FactComponent,
    MetricInvalidError,
    MetricUnsupportedError,
    SupersededValue,
)

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
# Slice 6C: conflicting values are reconciled only by re-rounding to thousands
# through millions (never a percentage band), and stock splits are recognized
# only for share counts with an integer forward ratio in this range.
PRECISION_ROUNDING_DIGITS: Final = (3, 4, 5, 6)
SPLIT_ELIGIBLE_UNIT: Final = "shares"
MAX_SPLIT_RATIO: Final = 100


class AnnualNormalizationError(Exception):
    """Base class for shared annual-normalization failures."""


class MalformedFactsError(AnnualNormalizationError, MetricInvalidError):
    """Raised when the payload lacks a usable us-gaap fact structure."""


class ConceptNotFoundError(AnnualNormalizationError, MetricUnsupportedError):
    """Raised when no preference-order concept has a qualifying observation."""


class AmbiguousValueError(AnnualNormalizationError, MetricInvalidError):
    """Raised when a fiscal year has conflicting distinct full-year values."""


class StructurallyAbsentError(AnnualNormalizationError):
    """Raised when the payload proves a metric has no value to report.

    Not a data failure: the company's own reported totals show the metric is
    zero, so the series is empty rather than unsupported. Callers translate it
    into ``STRUCTURALLY_ABSENT``.
    """


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
    resolution: ConflictResolution | None = None
    components: tuple[FactComponent, ...] = ()


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


def compose_instant_series(
    us_gaap: dict[str, Any],
    components: tuple[str, ...],
    *,
    max_years: int,
    concept_error: type[Exception],
    ambiguity_error: type[Exception],
    unit: str = TARGET_UNIT,
    unsafe: tuple[str, ...] = (),
    totals_tried: tuple[str, ...] = (),
) -> tuple[str, tuple[AnnualObservation, ...]]:
    """Add the component concepts reported at each fiscal-year end (Slice 6D).

    Each component is resolved on its own with the usual per-year conflict rules,
    then the components present at a year end are summed. The composite must
    cover the company's latest fiscal year, exactly like single-concept
    selection; otherwise it is stale and ``concept_error`` is raised. A year
    where an ``unsafe`` concept holds a non-zero value cannot be decomposed, so
    the whole metric is refused rather than silently understated.

    A year with only one contributing component yields that component's
    observation unchanged, so composition never alters single-source provenance.
    Components reported as zero are not contributors.
    """
    reference_end = latest_annual_period_end(us_gaap)
    tried = ", ".join((*totals_tried, *components))
    present: dict[str, dict[int, list[AnnualObservation]]] = {}
    for concept in components:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        by_year: dict[int, list[AnnualObservation]] = {}
        for observation in _qualifying_instant_observations(concept, entry, unit):
            by_year.setdefault(observation.fiscal_year, []).append(observation)
        if by_year:
            present[concept] = by_year
    if not present:
        raise concept_error(
            "No supported US-GAAP concept with a fiscal-year-end instant observation "
            f"was found. Tried: {tried}."
        )

    years = sorted({year for by_year in present.values() for year in by_year}, reverse=True)
    composed = [
        _compose_year(
            year,
            [
                _resolve_year(concept, year, present[concept][year], ambiguity_error)
                for concept in components
                if year in present.get(concept, {})
            ],
            ambiguity_error,
        )
        for year in years[:max_years]
    ]
    _refuse_unsafe(us_gaap, composed, unit, concept_error, unsafe)
    if not is_current(composed, reference_end):
        newest = max(observation.period_end for observation in composed)
        raise concept_error(
            "No supported US-GAAP concept with a fiscal-year-end instant observation "
            f"was found. Tried: {tried}. Stale (no value for the latest fiscal "
            f"year): {', '.join(present)} (last period end {newest.isoformat()})"
            + (
                f"; company latest fiscal-year end {reference_end.isoformat()}."
                if reference_end is not None
                else "."
            )
        )
    return " + ".join(present), tuple(composed)


def _compose_year(
    fiscal_year: int,
    parts: list[AnnualObservation],
    ambiguity_error: type[Exception],
) -> AnnualObservation:
    # A component reported as zero adds nothing to the sum, so it is not a
    # contributor: dropping it keeps a year with one real component identical to
    # a plain single-concept selection. A year where every component is zero
    # keeps the first, so a reported zero stays distinct from an absent value.
    contributors = [part for part in parts if part.value != 0] or parts[:1]
    if len(contributors) == 1:
        return contributors[0]
    ends = {part.period_end for part in contributors}
    if len(ends) > 1:
        raise ambiguity_error(
            f"Fiscal year {fiscal_year} components end on different dates: "
            f"{sorted(end.isoformat() for end in ends)}."
        )
    primary = contributors[0]
    return replace(
        primary,
        concept=" + ".join(part.concept for part in contributors),
        value=sum(part.value for part in contributors),
        resolution=None,
        components=tuple(
            FactComponent(
                provider_field=part.concept,
                value=part.value,
                form=part.form,
                filed=part.filed,
                accession=part.accession,
            )
            for part in contributors
        ),
    )


def _refuse_unsafe(
    us_gaap: dict[str, Any],
    composed: list[AnnualObservation],
    unit: str,
    concept_error: type[Exception],
    unsafe: tuple[str, ...],
) -> None:
    ends = {observation.period_end for observation in composed}
    for concept in unsafe:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            continue
        blocking = sorted(
            {
                observation.period_end.isoformat()
                for observation in _qualifying_instant_observations(concept, entry, unit)
                if observation.value != 0 and observation.period_end in ends
            }
        )
        if blocking:
            raise concept_error(
                f"{concept} is non-zero at {', '.join(blocking)} and bundles "
                "economics this metric excludes, so the reported components "
                "cannot be composed without understating or widening the metric."
            )


def proves_absence(
    us_gaap: dict[str, Any],
    absence_proof: tuple[str, str],
    *,
    unit: str = TARGET_UNIT,
) -> bool:
    """True when the company's own totals prove the metric is zero (Slice 6D).

    ``absence_proof`` is a ``(total, remainder)`` concept pair where the metric
    equals ``total - remainder``. At the company's latest fiscal-year end, a
    reported total that equals the remainder (or is itself zero) proves there is
    nothing to report. A missing tag proves nothing and returns False.
    """
    reference_end = latest_annual_period_end(us_gaap)
    if reference_end is None:
        return False
    total_concept, remainder_concept = absence_proof

    def at_reference(concept: str) -> int | None:
        entry = us_gaap.get(concept)
        if not isinstance(entry, dict):
            return None
        values = {
            observation.value
            for observation in _qualifying_instant_observations(concept, entry, unit)
            if observation.period_end == reference_end
        }
        return values.pop() if len(values) == 1 else None

    total = at_reference(total_concept)
    if total is None:
        return False
    if total == 0:
        return True
    return total == at_reference(remainder_concept)


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
    events = (
        _split_events(by_year)
        if observations and observations[0].unit == SPLIT_ELIGIBLE_UNIT
        else ()
    )
    return tuple(
        _resolve_year(concept, year, by_year[year], ambiguity_error, events)
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
    events: tuple[_SplitEvent, ...] = (),
) -> AnnualObservation:
    """Resolve one fiscal year's observations to a single canonical value.

    Identical values collapse to the earliest original filing, exactly as
    before. Distinct values are resolved only when they are provably the same
    economic value (see the module docstring); anything else raises
    ``ambiguity_error``.
    """
    distinct_values = {observation.value for observation in observations}

    def conflict() -> Exception:
        return ambiguity_error(
            f"Fiscal year {fiscal_year} has conflicting {concept} values: "
            f"{sorted(distinct_values)}."
        )

    factored: list[tuple[AnnualObservation, int]] = []
    for observation in observations:
        factor = _split_factor(observation, events)
        if factor is None:
            raise ambiguity_error(
                f"Fiscal year {fiscal_year} {concept} was filed "
                f"{observation.filed.isoformat()}, between a stock split's last "
                "pre-split and first post-split reports, so its share basis is "
                "uncertain."
            )
        factored.append((observation, factor))

    basis = min(factor for _, factor in factored)
    on_basis = [observation for observation, factor in factored if factor == basis]
    value = _agreed_value({observation.value for observation in on_basis})
    if value is None:
        raise conflict()
    for observation, factor in factored:
        if factor != basis and not _same_value(
            observation.value, Fraction(value * basis, factor)
        ):
            raise conflict()

    # Identical comparative repeats collapse to the earliest original filing.
    chosen = min(
        (observation for observation in on_basis if observation.value == value),
        key=lambda o: (o.filed, o.accession),
    )
    if len(distinct_values) == 1 and basis == 1:
        return chosen
    kind = (
        ConflictResolutionKind.STOCK_SPLIT
        if basis != 1 or any(factor != basis for _, factor in factored)
        else ConflictResolutionKind.PRECISION
    )
    superseded = tuple(
        SupersededValue(
            value=observation.value,
            form=observation.form,
            filed=observation.filed,
            accession=observation.accession,
            split_factor=factor,
        )
        for observation, factor in sorted(
            factored, key=lambda pair: (pair[0].filed, pair[0].accession)
        )
        if (observation.value, factor) != (value, basis)
    )
    return replace(
        chosen,
        value=value * basis,
        resolution=ConflictResolution(
            kind=kind, reported_value=value, split_factor=basis, superseded=superseded
        ),
    )


# --- Conflict classification (Slice 6C) --------------------------------------


@dataclass(frozen=True)
class _SplitEvent:
    """A forward stock split evidenced by restated comparatives in the payload."""

    ratio: int
    last_pre_filed: date
    first_post_filed: date


def _trailing_zeros(value: int) -> int:
    if value == 0:
        return 0
    remaining, zeros = abs(value), 0
    while remaining % 10 == 0:
        remaining //= 10
        zeros += 1
    return zeros


def _round_to(value: Fraction, digits: int) -> int:
    """Round half away from zero to a multiple of ``10 ** digits``."""
    step = 10**digits
    quotient = value / step
    magnitude = math.floor(abs(quotient) + Fraction(1, 2))
    return (magnitude if quotient >= 0 else -magnitude) * step


def _same_value(coarse: int, exact: Fraction) -> bool:
    """True when ``coarse`` equals ``exact`` or is ``exact`` re-rounded.

    Re-rounding is accepted only to thousands through millions, and only to a
    precision the coarse value's own trailing zeros can express, so the largest
    difference ever absorbed is half a million units.
    """
    if coarse == exact:
        return True
    if coarse == 0:
        return False
    zeros = _trailing_zeros(coarse)
    return any(
        _round_to(exact, digits) == coarse
        for digits in PRECISION_ROUNDING_DIGITS
        if digits <= zeros
    )


def _agreed_value(values: set[int]) -> int | None:
    """Return the one most precise value every other value re-rounds, else None."""
    if len(values) == 1:
        return next(iter(values))
    if 0 in values:
        return None
    fewest = min(_trailing_zeros(value) for value in values)
    precise = [value for value in values if _trailing_zeros(value) == fewest]
    if len(precise) != 1:
        return None
    candidate = precise[0]
    if all(_same_value(value, Fraction(candidate)) for value in values):
        return candidate
    return None


def _split_ratio(values: set[int]) -> int | None:
    """The integer forward-split ratio that explains distinct values, if any."""
    if len(values) < 2 or min(values) <= 0:
        return None
    high = max(values)
    ratio = round(Fraction(high, min(values)))
    if not 2 <= ratio <= MAX_SPLIT_RATIO:
        return None
    pre = {value for value in values if round(Fraction(high, value)) == ratio}
    post = {value for value in values if round(Fraction(high, value)) == 1}
    if len(pre) + len(post) != len(values):
        return None
    pre_value, post_value = _agreed_value(pre), _agreed_value(post)
    if pre_value is None or post_value is None:
        return None
    if not _same_value(pre_value, Fraction(post_value, ratio)):
        return None
    return ratio


def classify_conflict_values(
    values: set[int], *, shares: bool
) -> ConflictResolutionKind | None:
    """Classify distinct same-year values by value alone; None means genuine.

    This is the value test the normalizer applies; resolution additionally
    requires the filing-order evidence for splits.
    """
    if len(values) < 2:
        return None
    if _agreed_value(values) is not None:
        return ConflictResolutionKind.PRECISION
    if shares and _split_ratio(values) is not None:
        return ConflictResolutionKind.STOCK_SPLIT
    return None


def _split_evidence(observations: list[AnnualObservation]) -> _SplitEvent | None:
    """Return the forward split that explains one year's conflict, if any."""
    values = {observation.value for observation in observations}
    ratio = _split_ratio(values)
    if ratio is None:
        return None
    high = max(values)
    pre = [o for o in observations if round(Fraction(high, o.value)) == ratio]
    post = [o for o in observations if round(Fraction(high, o.value)) == 1]
    last_pre = max(o.filed for o in pre)
    first_post = min(o.filed for o in post)
    if last_pre >= first_post:
        return None
    return _SplitEvent(ratio, last_pre, first_post)


def _split_events(
    by_year: dict[int, list[AnnualObservation]],
) -> tuple[_SplitEvent, ...]:
    """Collect split events from every year's restatement evidence.

    Evidence from different years for the same split is merged into the
    narrowest filing interval. If evidence contradicts itself (overlapping
    intervals with different ratios, or an empty merged interval), no split is
    recognized at all, so every conflict stays a loud failure.
    """
    found = sorted(
        (e for e in map(_split_evidence, by_year.values()) if e is not None),
        key=lambda e: (e.last_pre_filed, e.first_post_filed),
    )
    merged: list[_SplitEvent] = []
    for event in found:
        if merged and event.last_pre_filed < merged[-1].first_post_filed:
            previous = merged[-1]
            if previous.ratio != event.ratio:
                return ()
            last_pre = max(previous.last_pre_filed, event.last_pre_filed)
            first_post = min(previous.first_post_filed, event.first_post_filed)
            if last_pre >= first_post:
                return ()
            merged[-1] = _SplitEvent(event.ratio, last_pre, first_post)
        else:
            merged.append(event)
    return tuple(merged)


def _split_factor(
    observation: AnnualObservation, events: tuple[_SplitEvent, ...]
) -> int | None:
    """Cumulative split factor to the latest basis; None if the basis is unknown."""
    factor = 1
    for event in events:
        if observation.filed <= event.last_pre_filed:
            factor *= event.ratio
        elif observation.filed < event.first_post_filed:
            return None
    return factor

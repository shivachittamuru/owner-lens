"""Universe coverage survey for OwnerLens (Slice 6A).

Runs the existing SEC-first canonical pipeline across a declared universe of
conventional operating companies and measures, deterministically, which companies
reach full coverage, which are partial or failed, which canonical metrics block
them, and why. The purpose is coverage *discovery*: nothing here changes SEC
normalization, overrides, economics, or coverage semantics.

This module is SEC-side (above the canonical boundary): diagnosis inspects raw
Company Facts read-only through a small candidate-concept catalog to classify a
gap as a missing, stale, alternative, or composite concept. The catalog is
evidence only; it is never used to select a value.

``company_coverage_from_history`` re-raises an INVALID metric by design, so a
company with one ambiguous restatement yields no coverage picture at all. The
survey therefore probes each analytical layer directly and records UNAVAILABLE
(unsupported input), BLOCKED (invalid input), or ERROR (unexpected exception,
a likely OwnerLens bug) per layer without changing coverage itself.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum
from typing import Any, Final

import owner_lens.metrics as _metric_registry
from owner_lens._annual import (
    SPLIT_ELIGIBLE_UNIT,
    AmbiguousValueError,
    MalformedFactsError,
    classify_conflict_values,
)
from owner_lens.canonical import (
    CANONICAL_METRICS,
    CanonicalFinancialHistory,
    ConflictResolutionKind,
    MetricInvalidError,
    MetricKind,
    MetricStatus,
    MetricUnsupportedError,
)
from owner_lens.capital_allocation import (
    CapitalAllocationClassification,
    capital_allocation_from_history,
)
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.compounding import (
    CompoundingClassification,
    compounding_views_from_history,
)
from owner_lens.economic_summary import (
    OverallEconomicValueClassification,
    economic_value_summary_from_history,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    economic_value_from_history,
)
from owner_lens.ingestion import ingest_company
from owner_lens.metrics import CanonicalMetricDefinition, resolve_concepts
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.persistence.raw import RawSnapshotStore
from owner_lens.persistence.store import OwnerLensStore
from owner_lens.sec import SecClient
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "CANDIDATE_CATALOG",
    "LAYERS",
    "SURVEY_NOTES",
    "UNIVERSE_6A",
    "CompanySurvey",
    "DiagnosisCategory",
    "LayerProbe",
    "LayerState",
    "MetricFinding",
    "Overall",
    "RestatementKind",
    "UniverseMember",
    "UniverseReport",
    "failed_survey",
    "format_company_view",
    "format_metric_view",
    "format_pattern_view",
    "survey_company",
    "survey_from_snapshot",
    "survey_with_ingestion",
]


# --- Universe -----------------------------------------------------------------


@dataclass(frozen=True)
class UniverseMember:
    """One surveyed company with its industry and any stress-test note."""

    ticker: str
    industry: str
    note: str | None = None


UNIVERSE_6A: Final[tuple[UniverseMember, ...]] = (
    UniverseMember("ADBE", "Software"),
    UniverseMember("V", "Payments"),
    UniverseMember("COST", "Consumer retail"),
    UniverseMember("MSFT", "Software"),
    UniverseMember("CRM", "Software"),
    UniverseMember("NOW", "Software"),
    UniverseMember("META", "Internet"),
    UniverseMember("AMZN", "Internet"),
    UniverseMember("NVDA", "Semiconductors"),
    UniverseMember("ORCL", "Software"),
    UniverseMember("INTU", "Software"),
    UniverseMember("NKE", "Consumer apparel"),
    UniverseMember("LULU", "Consumer apparel"),
    UniverseMember("CMG", "Restaurants"),
    UniverseMember("PG", "Consumer staples"),
    UniverseMember("KO", "Consumer staples"),
    UniverseMember("HD", "Home improvement retail"),
    UniverseMember("LOW", "Home improvement retail"),
    UniverseMember("CAT", "Industrials", "stress test: captive finance arm (Cat Financial)"),
    UniverseMember("DE", "Industrials", "stress test: captive finance arm (John Deere Financial)"),
    UniverseMember("UNH", "Managed care", "stress test: insurance-like balance sheet"),
    UniverseMember("PFE", "Pharmaceuticals"),
    UniverseMember("XOM", "Energy"),
    UniverseMember("CVX", "Energy"),
)
_INDUSTRY: Final = {m.ticker: m for m in UNIVERSE_6A}

# Human annotations for findings the rules leave UNCLASSIFIED: (ticker, metric) -> note.
SURVEY_NOTES: Final[dict[tuple[str, str], str]] = {}


# --- Types --------------------------------------------------------------------


class LayerState(Enum):
    """Survey outcome of one analytical layer."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class Overall(Enum):
    """Company-level survey outcome."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DiagnosisCategory(Enum):
    """Why a canonical metric is not cleanly available."""

    NONE = "NONE"
    POLICY_ABSENT = "POLICY_ABSENT"
    AMBIGUOUS_DUPLICATE = "AMBIGUOUS_DUPLICATE"
    MALFORMED = "MALFORMED"
    STALE_CONCEPT = "STALE_CONCEPT"
    # A composition the registry declares cannot be performed for this company,
    # because a concept bundles economics the canonical metric excludes.
    COMPOSITION_BLOCKED = "COMPOSITION_BLOCKED"
    COMPOSITE_CANDIDATE = "COMPOSITE_CANDIDATE"
    ALTERNATIVE_CONCEPT = "ALTERNATIVE_CONCEPT"
    MISSING_CONCEPT = "MISSING_CONCEPT"
    PERIOD_ISSUE = "PERIOD_ISSUE"
    BUSINESS_STRUCTURE = "BUSINESS_STRUCTURE"
    LIKELY_BUG = "LIKELY_BUG"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class LayerProbe:
    """One layer's outcome with its reason and the canonical metric that blocked it."""

    state: LayerState
    reason: str | None = None
    blocking_metric: str | None = None


@dataclass(frozen=True)
class MetricFinding:
    """One canonical metric's status for a company, with its diagnosis and evidence."""

    metric: str
    status: MetricStatus
    diagnosis: DiagnosisCategory
    concept_used: str | None
    concepts_tried: tuple[str, ...]
    candidates: tuple[str, ...]
    latest_fiscal_year: int | None
    reason: str | None = None
    value_level: bool = False
    note: str | None = None
    restatement: RestatementKind | None = None
    # Slice 6C: conflicts the normalizer resolved, e.g. "FY2024 STOCK_SPLIT x10".
    resolved_conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanySurvey:
    """The complete survey picture for one company."""

    ticker: str
    company_name: str | None
    industry: str
    cik: str | None
    content_hash: str | None
    ingestion_status: str | None
    processing_status: str | None
    overall: Overall
    layers: dict[str, LayerProbe]
    metrics: dict[str, MetricFinding]
    primary_blocker: str | None
    primary_category: DiagnosisCategory
    failure: str | None = None
    note: str | None = None

    def metrics_with(self, status: MetricStatus) -> tuple[str, ...]:
        return tuple(m for m, f in self.metrics.items() if f.status is status)

    def silently_stale(self) -> tuple[str, ...]:
        """AVAILABLE metrics whose selected SEC concept has no recent annual value."""
        return tuple(
            m for m, f in self.metrics.items()
            if f.status is MetricStatus.AVAILABLE and f.diagnosis is DiagnosisCategory.STALE_CONCEPT
        )

    def unusable_inputs(self) -> tuple[MetricFinding, ...]:
        """Required inputs that are unsupported or invalid (unsupported diluted shares
        only degrade owner economics, so they are not counted as blocking)."""
        return tuple(
            f for m, f in self.metrics.items()
            if f.status in _UNUSABLE
            and not (m == "diluted_shares" and f.status is MetricStatus.UNSUPPORTED)
        )

    def blocking_metrics(self) -> tuple[str, ...]:
        seen: list[str] = []
        for probe in self.layers.values():
            if probe.blocking_metric and probe.blocking_metric not in seen:
                seen.append(probe.blocking_metric)
        return tuple(seen)


# --- Candidate-concept catalog (read-only diagnosis evidence) -------------------

# For each canonical metric: SEC concepts that may carry the same economics when the
# preferred concepts are missing or stale. "Component" concepts may need to be
# summed (composite metric) rather than substituted.
CANDIDATE_CATALOG: Final[dict[str, tuple[str, ...]]] = {
    "revenue": (
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "HealthCareOrganizationRevenue",
    ),
    "operating_income": (),
    "net_income": ("ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",),
    "capital_expenditures": (
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ),
    "diluted_shares": ("WeightedAverageNumberOfShareOutstandingBasicAndDiluted",),
    "income_tax_expense": (),
    "pretax_income": (),
    "repurchases": ("PaymentsForRepurchaseOfEquity",),
    "stock_based_compensation": ("ShareBasedCompensationArrangementByShareBasedPaymentAwardCompensationCost",),
    "dividends_paid": ("PaymentsOfOrdinaryDividends",),
    "cash": ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"),
    "short_term_investments": (
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ),
    "current_debt": ("LongTermDebtAndCapitalLeaseObligationsCurrent",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    "total_assets": (),
    "total_equity": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
}
# Concepts that are additive parts of a canonical metric (composite candidates).
# Slice 6D implemented current-debt composition in the metric registry, so the
# only pattern the survey had measured is now resolved before diagnosis; an
# entry here means a metric still needs a sum OwnerLens cannot yet perform.
_COMPONENTS: Final[dict[str, frozenset[str]]] = {}
# When the selected concept excludes these, a non-zero value means the metric is
# likely understated (value-level composite). Current debt no longer appears
# here: its components are composed, so it can no longer be silently understated.
_VALUE_LEVEL_ADDENDS: Final[dict[tuple[str, str], frozenset[str]]] = {}
# Concepts suggesting a business structure the canonical model does not target.
_STRUCTURE_MARKERS: Final = (
    "PremiumsEarnedNet",
    "PolicyholderBenefitsAndClaimsIncurredNet",
    "InterestAndDividendIncomeOperating",
    "HealthCareOrganizationPremiumRevenue",
)
_STRUCTURAL_METRICS: Final = frozenset({"revenue", "operating_income"})
_RECENT_DAYS: Final = 400
_MIN_FULL_YEAR_DAYS: Final = 350
_MAX_FULL_YEAR_DAYS: Final = 380
_AMBIGUOUS_YEAR = re.compile(r"Fiscal year (\d{4})")
_AMBIGUOUS_VALUES = re.compile(r"values: \[([-\d, ]+)\]")


class RestatementKind(Enum):
    """What kind of revision produced conflicting full-year values."""

    STOCK_SPLIT = "STOCK_SPLIT"
    PRECISION = "PRECISION"
    VALUE_CHANGE = "VALUE_CHANGE"


def _restatement_kind(reason: str | None, *, shares: bool = True) -> RestatementKind | None:
    """Classify conflicting values with the normalizer's exact rule (Slice 6C).

    Since 6C the normalizer resolves precision re-roundings and evidenced splits,
    so an unresolved conflict is normally a genuine ``VALUE_CHANGE``; a
    ``PRECISION`` or ``STOCK_SPLIT`` label here means the values fit the pattern
    but the filing-order evidence did not.
    """
    match = _AMBIGUOUS_VALUES.search(reason or "")
    if not match:
        return None
    values = {int(v) for v in match.group(1).split(",") if v.strip()}
    if len(values) < 2:
        return None
    kind = classify_conflict_values(values, shares=shares)
    if kind is ConflictResolutionKind.STOCK_SPLIT:
        return RestatementKind.STOCK_SPLIT
    if kind is ConflictResolutionKind.PRECISION:
        return RestatementKind.PRECISION
    return RestatementKind.VALUE_CHANGE


# --- Layer probing ------------------------------------------------------------

LAYERS: Final = (
    "owner_economics",
    "capital_efficiency",
    "economic_value",
    "compounding",
    "capital_allocation",
    "economic_summary",
)
_OWNER_INPUTS: Final = (
    "diluted_shares",
    "revenue", "operating_income", "net_income", "operating_cash_flow", "capital_expenditures",
)
_CAPITAL_INPUTS: Final = (
    "operating_income", "net_income", "income_tax_expense", "pretax_income", "cash",
    "short_term_investments", "current_debt", "long_term_debt", "total_assets", "total_equity",
)
_ALLOCATION_INPUTS: Final = ("repurchases", "stock_based_compensation", "dividends_paid")
_LAYER_INPUTS: Final[dict[str, tuple[str, ...]]] = {
    "owner_economics": _OWNER_INPUTS,
    "capital_efficiency": _CAPITAL_INPUTS,
    "economic_value": _OWNER_INPUTS + _CAPITAL_INPUTS,
    "compounding": _OWNER_INPUTS + _CAPITAL_INPUTS,
    "capital_allocation": _OWNER_INPUTS + _CAPITAL_INPUTS + _ALLOCATION_INPUTS,
    "economic_summary": _OWNER_INPUTS + _CAPITAL_INPUTS + _ALLOCATION_INPUTS,
}
_UNUSABLE: Final = (MetricStatus.UNSUPPORTED, MetricStatus.INVALID)


def _blocking(history: CanonicalFinancialHistory, layer: str) -> str | None:
    """The first unusable required input, in the order the layer requires them.

    Unsupported diluted shares degrade owner economics to PARTIAL rather than
    blocking it, so only an INVALID diluted-share series blocks a layer.
    """
    statuses = history.statuses()
    for metric in _LAYER_INPUTS[layer]:
        status = statuses[metric]
        if metric == "diluted_shares" and status is MetricStatus.UNSUPPORTED:
            continue
        if status in _UNUSABLE:
            return metric
    return None


def _evaluate(layer: str, history: CanonicalFinancialHistory) -> tuple[LayerState, str | None]:
    """Run one layer and apply the coverage layer-state rules to its result."""
    shares_unsupported = history.statuses()["diluted_shares"] is MetricStatus.UNSUPPORTED
    insufficient = LayerState.INSUFFICIENT_DATA
    if layer == "owner_economics":
        owner_economics_from_history(history)
        return (LayerState.PARTIAL, "diluted shares unsupported") if shares_unsupported else (
            LayerState.AVAILABLE, None)
    if layer == "capital_efficiency":
        capital_efficiency_from_history(history)
        return LayerState.AVAILABLE, None
    if layer == "economic_value":
        snapshots = economic_value_from_history(history)
        if snapshots and all(
            s.classification is EconomicValueClassification.INSUFFICIENT_DATA for s in snapshots
        ):
            return insufficient, "every annual snapshot is INSUFFICIENT_DATA"
        return LayerState.AVAILABLE, None
    if layer == "compounding":
        recent, long_term = compounding_views_from_history(history)
        if (
            recent.classification is CompoundingClassification.INSUFFICIENT_DATA
            and long_term.classification is CompoundingClassification.INSUFFICIENT_DATA
        ):
            return insufficient, "both compounding views are INSUFFICIENT_DATA"
        return LayerState.AVAILABLE, None
    if layer == "capital_allocation":
        rows = capital_allocation_from_history(history)
        if rows and all(
            r.classification is CapitalAllocationClassification.INSUFFICIENT_DATA for r in rows
        ):
            return LayerState.PARTIAL, "every capital-allocation year is INSUFFICIENT_DATA"
        return LayerState.AVAILABLE, None
    summary = economic_value_summary_from_history(history)
    if (
        summary.overall_economic_value_classification
        is OverallEconomicValueClassification.INSUFFICIENT_DATA
    ):
        return insufficient, "overall classification is INSUFFICIENT_DATA"
    return LayerState.AVAILABLE, None


def _probe_layers(history: CanonicalFinancialHistory) -> dict[str, LayerProbe]:
    probes: dict[str, LayerProbe] = {}
    shares_unsupported = history.statuses()["diluted_shares"] is MetricStatus.UNSUPPORTED
    for layer in LAYERS:
        try:
            state, reason = _evaluate(layer, history)
        except MetricUnsupportedError as exc:
            probes[layer] = LayerProbe(LayerState.UNAVAILABLE, str(exc), _blocking(history, layer))
            continue
        except MetricInvalidError as exc:
            probes[layer] = LayerProbe(LayerState.BLOCKED, str(exc), _blocking(history, layer))
            continue
        except Exception as exc:  # noqa: BLE001 - an unexpected failure is the finding
            probes[layer] = LayerProbe(LayerState.ERROR, f"{type(exc).__name__}: {exc}")
            continue
        blocker = "diluted_shares" if shares_unsupported and state is not LayerState.AVAILABLE else None
        probes[layer] = LayerProbe(state, reason, blocker)
    return probes


# --- Raw-fact evidence (read-only) ----------------------------------------------

_DEFINITIONS: Final[dict[str, CanonicalMetricDefinition]] = {
    value.name: value
    for value in vars(_metric_registry).values()
    if isinstance(value, CanonicalMetricDefinition)
}


def _fy_values(us_gaap: Mapping[str, Any], concept: str, unit: str, kind: MetricKind) -> dict[date, int]:
    """Annual 10-K values for a concept keyed by period end (latest filing wins)."""
    entry = us_gaap.get(concept)
    if not isinstance(entry, dict) or not isinstance(entry.get("units"), dict):
        return {}
    facts = entry["units"].get(unit)
    if not isinstance(facts, list):
        return {}
    chosen: dict[date, tuple[str, int]] = {}
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("fp") != "FY":
            continue
        if not str(fact.get("form", "")).startswith("10-K"):
            continue
        value = fact.get("val")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            end = date.fromisoformat(str(fact["end"]))
            if kind is MetricKind.DURATION:
                if "start" not in fact:
                    continue
                days = (end - date.fromisoformat(str(fact["start"]))).days
                if not _MIN_FULL_YEAR_DAYS <= days <= _MAX_FULL_YEAR_DAYS:
                    continue
            elif "start" in fact:
                continue
        except (KeyError, ValueError):
            continue
        filed = str(fact.get("filed", ""))
        if end not in chosen or filed > chosen[end][0]:
            chosen[end] = (filed, int(value))
    return {end: val for end, (_, val) in chosen.items()}


def _reference_date(history: CanonicalFinancialHistory, us_gaap: Mapping[str, Any]) -> date | None:
    ends = [f.period_end for s in history.series for f in s.observations]
    if ends:
        return max(ends)
    latest: date | None = None
    for concept in ("Assets", "Revenues", "NetIncomeLoss"):
        kind = MetricKind.INSTANT if concept == "Assets" else MetricKind.DURATION
        values = _fy_values(us_gaap, concept, "USD", kind)
        if values:
            candidate = max(values)
            latest = candidate if latest is None or candidate > latest else latest
    return latest


def _us_gaap(raw_facts: Mapping[str, Any]) -> Mapping[str, Any]:
    facts = raw_facts.get("facts") if isinstance(raw_facts, Mapping) else None
    us_gaap = facts.get("us-gaap") if isinstance(facts, Mapping) else None
    return us_gaap if isinstance(us_gaap, Mapping) else {}


# --- Per-metric diagnosis -------------------------------------------------------


def _unsafe_present(
    definition: CanonicalMetricDefinition,
    us_gaap: Mapping[str, Any],
    kind: MetricKind,
    recent: Callable[[str], dict[date, int]],
) -> bool:
    """True when a registry 'unsafe' concept holds a recent non-zero value."""
    composition = definition.composition
    if composition is None:
        return False
    return any(
        any(value != 0 for value in recent(concept).values())
        for concept in composition.unsafe
    )


def _diagnose(
    metric: str,
    history: CanonicalFinancialHistory,
    us_gaap: Mapping[str, Any],
    reference: date | None,
    ticker: str,
) -> MetricFinding:
    series = history.series_for(metric)
    definition = _DEFINITIONS[metric]
    spec_kind = definition.kind
    tried = resolve_concepts(definition, ticker)
    if definition.composition is not None:
        tried = (*tried, *definition.composition.components)
    recent_cutoff = reference - timedelta(days=_RECENT_DAYS) if reference else None

    def recent(concept: str) -> dict[date, int]:
        values = _fy_values(us_gaap, concept, definition.unit, spec_kind)
        if recent_cutoff is None:
            return values
        return {end: v for end, v in values.items() if end >= recent_cutoff}

    def current_candidates() -> tuple[str, ...]:
        return tuple(c for c in CANDIDATE_CATALOG.get(metric, ()) if c not in tried and recent(c))

    years = [f.fiscal_year for f in series.observations]
    latest_year = max(years) if years else None
    used = series.observations[0].provider_field if series.observations else None

    resolved = tuple(
        f"FY{f.fiscal_year} {f.resolution.kind.value}"
        + (f" x{f.resolution.split_factor}" if f.resolution.split_factor != 1 else "")
        for f in series.observations
        if f.resolution is not None
    )

    def make(
        diagnosis: DiagnosisCategory,
        candidates: tuple[str, ...],
        reason: str | None = None,
        value_level: bool = False,
    ) -> MetricFinding:
        return MetricFinding(
            metric, series.status, diagnosis, used, tried, candidates, latest_year,
            reason, value_level, resolved_conflicts=resolved,
        )

    if series.status is MetricStatus.STRUCTURALLY_ABSENT:
        return make(diagnosis=DiagnosisCategory.POLICY_ABSENT, candidates=(),
                             reason="structurally absent by canonical policy")

    if series.status is MetricStatus.INVALID:
        error = series.error
        if isinstance(error, AmbiguousValueError) or "conflicting" in (series.reason or ""):
            match = _AMBIGUOUS_YEAR.search(series.reason or "")
            year = int(match.group(1)) if match else None
            window = history.max_years + (1 if spec_kind is MetricKind.INSTANT else 0)
            oldest = reference.year - window + 1 if reference else None
            where = (
                "oldest window year (restated baseline)"
                if year is not None and oldest is not None and year <= oldest
                else "inside the analysis window"
            )
            kind = _restatement_kind(series.reason, shares=definition.unit == SPLIT_ELIGIBLE_UNIT)
            label = f"; {kind.value.lower().replace('_', ' ')} restatement" if kind else ""
            # Since Slice 6B the selector skips stale concepts before resolving
            # years, so a conflict is always in the current selected concept.
            return replace(
                make(diagnosis=DiagnosisCategory.AMBIGUOUS_DUPLICATE, candidates=(),
                     reason=f"{series.reason} [{where}{label}]"),
                restatement=kind,
            )
        category = (
            DiagnosisCategory.MALFORMED if isinstance(error, MalformedFactsError)
            else DiagnosisCategory.UNCLASSIFIED
        )
        return make(diagnosis=category, candidates=(), reason=series.reason)

    if series.status is MetricStatus.UNSUPPORTED:
        candidates = tuple(
            c for c in CANDIDATE_CATALOG.get(metric, ()) if c not in tried and recent(c)
        )
        stale = [c for c in tried if _fy_values(us_gaap, c, definition.unit, spec_kind) and not recent(c)]
        components = _COMPONENTS.get(metric, frozenset())
        nonzero_components = [
            c for c in candidates if c in components and any(v != 0 for v in recent(c).values())
        ]
        present_no_annual = [
            c for c in tried
            if c in us_gaap and not _fy_values(us_gaap, c, definition.unit, spec_kind)
        ]
        if _unsafe_present(definition, us_gaap, spec_kind, recent):
            category, reason = DiagnosisCategory.COMPOSITION_BLOCKED, (
                series.reason or "components cannot be composed safely"
            )
        elif present_no_annual and not candidates and not stale:
            category, reason = DiagnosisCategory.PERIOD_ISSUE, (
                f"{', '.join(present_no_annual)} present but with no annual 10-K "
                "observation (for example a new registrant with only 10-Q filings)"
            )
        elif stale:
            last = max(max(_fy_values(us_gaap, c, definition.unit, spec_kind)) for c in stale)
            category, reason = DiagnosisCategory.STALE_CONCEPT, (
                f"preferred {', '.join(stale)} last reported {last}; "
                f"current candidates: {', '.join(candidates) or 'none'}"
            )
        elif len(nonzero_components) >= 2:
            category, reason = DiagnosisCategory.COMPOSITE_CANDIDATE, (
                f"needs a sum of {' + '.join(nonzero_components)}"
            )
        elif candidates:
            category, reason = DiagnosisCategory.ALTERNATIVE_CONCEPT, (
                f"override candidate: {', '.join(candidates)}"
            )
        elif metric in _STRUCTURAL_METRICS and any(m in us_gaap for m in _STRUCTURE_MARKERS):
            category, reason = DiagnosisCategory.BUSINESS_STRUCTURE, (
                "industry-specific concepts present: "
                + ", ".join(m for m in _STRUCTURE_MARKERS if m in us_gaap)
            )
        else:
            category, reason = DiagnosisCategory.MISSING_CONCEPT, (
                f"no recent annual value for {', '.join(tried)} or any catalog candidate"
            )
        return make(diagnosis=category, candidates=candidates, reason=reason)

    # AVAILABLE: guard against silent staleness. Since Slice 6B the selector
    # rejects stale concepts, so a hit here would indicate a selection regression.
    if recent_cutoff is not None and series.observations:
        newest = max(f.period_end for f in series.observations)
        if newest < recent_cutoff:
            return make(
                diagnosis=DiagnosisCategory.STALE_CONCEPT,
                candidates=current_candidates(),
                value_level=True,
                reason=(
                    f"selected {used} was last reported FY{latest_year} "
                    f"({sorted(years)}); current candidates: "
                    f"{', '.join(current_candidates()) or 'none'}"
                ),
            )
    # Then value-level composites and period gaps.
    addends = _VALUE_LEVEL_ADDENDS.get((metric, used or ""), frozenset())
    understated = []
    for fact in series.observations:
        for concept in sorted(addends):
            value = _fy_values(us_gaap, concept, definition.unit, spec_kind).get(fact.period_end)
            if value:
                understated.append(f"FY{fact.fiscal_year} {concept} {value:,}")
    if understated:
        return make(diagnosis=DiagnosisCategory.COMPOSITE_CANDIDATE,
                             candidates=tuple(sorted(addends)), value_level=True,
                             reason=f"{used} excludes non-zero " + "; ".join(understated))
    expected = min(3, history.max_years)
    contiguous = sorted(years) == list(range(min(years), max(years) + 1))
    if len(years) < expected or not contiguous:
        return make(diagnosis=DiagnosisCategory.PERIOD_ISSUE, candidates=(),
                             reason=f"fiscal years present: {sorted(years)}")
    return make(diagnosis=DiagnosisCategory.NONE, candidates=())


# --- Company survey -------------------------------------------------------------


def _overall(layers: Mapping[str, LayerProbe], metrics: Mapping[str, MetricFinding]) -> Overall:
    silently_stale = any(
        f.status is MetricStatus.AVAILABLE and f.diagnosis is DiagnosisCategory.STALE_CONCEPT
        for f in metrics.values()
    )
    if all(p.state is LayerState.AVAILABLE for p in layers.values()) and not silently_stale:
        return Overall.FULL
    if layers["owner_economics"].state not in (LayerState.AVAILABLE, LayerState.PARTIAL):
        return Overall.FAILED
    return Overall.PARTIAL


def _primary(
    layers: Mapping[str, LayerProbe], metrics: Mapping[str, MetricFinding]
) -> tuple[str | None, DiagnosisCategory]:
    for layer in LAYERS:
        probe = layers[layer]
        if probe.state is LayerState.AVAILABLE:
            continue
        if probe.state is LayerState.ERROR:
            return f"{layer}: {probe.reason}", DiagnosisCategory.LIKELY_BUG
        if probe.blocking_metric:
            return probe.blocking_metric, metrics[probe.blocking_metric].diagnosis
        return f"{layer}: {probe.reason}", DiagnosisCategory.PERIOD_ISSUE
    return None, DiagnosisCategory.NONE


def survey_company(
    raw_facts: Mapping[str, Any],
    *,
    ticker: str,
    company_name: str | None = None,
    cik: str | None = None,
    content_hash: str | None = None,
    ingestion_status: str | None = None,
    processing_status: str | None = None,
    max_years: int = 5,
    notes: Mapping[tuple[str, str], str] = SURVEY_NOTES,
) -> CompanySurvey:
    """Survey one company's raw Company Facts deterministically and offline."""
    history = canonical_history_from_sec(dict(raw_facts), ticker=ticker, max_years=max_years)
    us_gaap = _us_gaap(raw_facts)
    reference = _reference_date(history, us_gaap)
    metrics: dict[str, MetricFinding] = {}
    for spec in CANONICAL_METRICS:
        finding = _diagnose(spec.name, history, us_gaap, reference, history.ticker)
        note = notes.get((history.ticker, spec.name))
        if note is not None:
            finding = replace(finding, note=note)
        metrics[spec.name] = finding
    layers = _probe_layers(history)
    primary, category = _primary(layers, metrics)
    member = _INDUSTRY.get(history.ticker)
    return CompanySurvey(
        ticker=history.ticker,
        company_name=company_name,
        industry=member.industry if member else "Unspecified",
        cik=cik,
        content_hash=content_hash,
        ingestion_status=ingestion_status,
        processing_status=processing_status,
        overall=_overall(layers, metrics),
        layers=layers,
        metrics=metrics,
        primary_blocker=primary,
        primary_category=category,
        note=member.note if member else None,
    )


def failed_survey(
    ticker: str,
    reason: str,
    *,
    ingestion_status: str | None = "FAILED",
    company_name: str | None = None,
    category: DiagnosisCategory = DiagnosisCategory.UNCLASSIFIED,
) -> CompanySurvey:
    """A company the pipeline could not reach (retrieval or persistence failure)."""
    normalized = ticker.strip().upper()
    member = _INDUSTRY.get(normalized)
    return CompanySurvey(
        ticker=normalized,
        company_name=company_name,
        industry=member.industry if member else "Unspecified",
        cik=None,
        content_hash=None,
        ingestion_status=ingestion_status,
        processing_status=None,
        overall=Overall.FAILED,
        layers={},
        metrics={},
        primary_blocker=f"ingestion: {reason}",
        primary_category=category,
        failure=reason,
        note=member.note if member else None,
    )


def survey_with_ingestion(
    ticker: str,
    *,
    sec_client: SecClient,
    store: OwnerLensStore,
    raw_store: RawSnapshotStore,
    max_years: int = 5,
) -> CompanySurvey:
    """Ingest one company with the existing workflow, then survey its stored snapshot.

    Retrieval and persistence go through ``ingest_company`` unchanged; the raw
    payload is reloaded from the raw store by content hash, so there is no second
    SEC request. An unexpected exception from ingestion is recorded as a likely
    OwnerLens bug rather than aborting the universe run.
    """
    try:
        result = ingest_company(ticker, sec_client=sec_client, store=store, max_years=max_years)
    except Exception as exc:  # noqa: BLE001 - an unexpected failure is the finding
        return failed_survey(
            ticker,
            f"ingest_company raised {type(exc).__name__}: {exc}",
            ingestion_status="ERROR",
            category=DiagnosisCategory.LIKELY_BUG,
        )
    name = result.company.company_name if result.company else None
    if result.failure is not None or result.source_snapshot is None:
        reason = result.failure.message if result.failure else "no source snapshot"
        return failed_survey(
            ticker, reason, ingestion_status=result.status.value, company_name=name
        )
    snapshot = result.source_snapshot
    raw_facts = json.loads(raw_store.get(snapshot.content_hash))
    return survey_company(
        raw_facts,
        ticker=result.company.ticker if result.company else ticker,
        company_name=name,
        cik=snapshot.cik,
        content_hash=snapshot.content_hash,
        ingestion_status=result.status.value,
        processing_status=result.processing_status.value,
        max_years=max_years,
    )


def survey_from_snapshot(
    entry: Mapping[str, Any], raw_store: RawSnapshotStore, *, max_years: int = 5
) -> CompanySurvey:
    """Re-survey a company offline from a prior report entry's stored snapshot."""
    ticker = str(entry["ticker"])
    content_hash = entry.get("content_hash")
    if not content_hash:
        return failed_survey(
            ticker,
            str(entry.get("failure") or "no stored snapshot"),
            ingestion_status=entry.get("ingestion_status"),
            company_name=entry.get("company_name"),
        )
    return survey_company(
        json.loads(raw_store.get(str(content_hash))),
        ticker=ticker,
        company_name=entry.get("company_name"),
        cik=entry.get("cik"),
        content_hash=str(content_hash),
        ingestion_status=entry.get("ingestion_status"),
        processing_status=entry.get("processing_status"),
        max_years=max_years,
    )


# --- Universe aggregation -------------------------------------------------------

RECURRING_THRESHOLD: Final = 3


@dataclass(frozen=True)
class MetricAggregate:
    """One canonical metric across the surveyed universe."""

    metric: str
    counts: dict[str, int]
    affected: dict[str, tuple[str, ...]]
    blocking_companies: tuple[str, ...]
    dominant_diagnosis: str | None


@dataclass(frozen=True)
class UniverseReport:
    """Deterministic aggregation of company surveys, in input order."""

    companies: tuple[CompanySurvey, ...]

    @property
    def surveyed(self) -> tuple[CompanySurvey, ...]:
        return tuple(c for c in self.companies if c.metrics)

    def distribution(self) -> dict[str, int]:
        counts = Counter(c.overall.value for c in self.companies)
        return {o.value: counts.get(o.value, 0) for o in Overall}

    def layer_counts(self) -> dict[str, dict[str, int]]:
        return {
            layer: dict(sorted(Counter(
                c.layers[layer].state.value for c in self.surveyed
            ).items()))
            for layer in LAYERS
        }

    def metric_view(self) -> tuple[MetricAggregate, ...]:
        rows = []
        for spec in CANONICAL_METRICS:
            findings = [(c.ticker, c.metrics[spec.name]) for c in self.surveyed]
            counts = {s.value: sum(1 for _, f in findings if f.status is s) for s in MetricStatus}
            affected = {
                s.value: tuple(t for t, f in findings if f.status is s)
                for s in MetricStatus
                if s is not MetricStatus.AVAILABLE
            }
            diagnoses = Counter(
                f.diagnosis.value for _, f in findings
                if f.diagnosis not in (DiagnosisCategory.NONE, DiagnosisCategory.POLICY_ABSENT)
            )
            blocking = tuple(c.ticker for c in self.surveyed if spec.name in c.blocking_metrics())
            dominant = diagnoses.most_common(1)[0][0] if diagnoses else None
            rows.append(MetricAggregate(spec.name, counts, affected, blocking, dominant))
        return tuple(rows)

    def top_blockers(self, limit: int = 5) -> tuple[tuple[str, int], ...]:
        ranked = [(m.metric, len(m.blocking_companies)) for m in self.metric_view()]
        ranked = [r for r in ranked if r[1] > 0]
        ranked.sort(key=lambda r: (-r[1], r[0]))
        return tuple(ranked[:limit])

    def findings(self) -> tuple[tuple[str, MetricFinding], ...]:
        """Every non-clean metric finding as (ticker, finding)."""
        return tuple(
            (c.ticker, f)
            for c in self.surveyed
            for f in c.metrics.values()
            if f.diagnosis not in (DiagnosisCategory.NONE, DiagnosisCategory.POLICY_ABSENT)
        )

    def diagnosis_counts(self) -> dict[str, int]:
        counts = Counter(f.diagnosis.value for _, f in self.findings())
        for company in self.surveyed:
            counts[DiagnosisCategory.LIKELY_BUG.value] += sum(
                1 for p in company.layers.values() if p.state is LayerState.ERROR
            )
        return {k: v for k, v in sorted(counts.items()) if v}

    def restatements(self) -> dict[str, tuple[str, ...]]:
        """Ambiguous duplicates grouped by restatement kind: kind -> ticker:metric."""
        grouped: dict[str, list[str]] = {}
        for ticker, finding in self.findings():
            if finding.diagnosis is DiagnosisCategory.AMBIGUOUS_DUPLICATE:
                kind = finding.restatement.value if finding.restatement else "UNKNOWN"
                grouped.setdefault(kind, []).append(f"{ticker}:{finding.metric}")
        return {k: tuple(v) for k, v in sorted(grouped.items())}

    def resolved_conflicts(self) -> tuple[tuple[str, str, str], ...]:
        """Conflicts the normalizer resolved: (ticker, metric, "FY<year> <kind>[ x<n>]")."""
        return tuple(
            (c.ticker, finding.metric, entry)
            for c in self.surveyed
            for finding in c.metrics.values()
            for entry in finding.resolved_conflicts
        )

    def unblocked_by(
        self, resolves: Callable[[str, MetricFinding], bool]
    ) -> tuple[str, ...]:
        """Companies with blocking inputs that would have none if ``resolves`` held.

        A what-if over diagnoses (no recomputation): it counts companies whose every
        unsupported or invalid required input is resolved by the improvement.
        """
        return tuple(
            c.ticker
            for c in self.surveyed
            if c.unusable_inputs()
            and all(resolves(c.ticker, f) for f in c.unusable_inputs())
        )

    def composites(self) -> tuple[tuple[str, str, bool, str | None], ...]:
        return tuple(
            (t, f.metric, f.value_level, f.reason)
            for t, f in self.findings()
            if f.diagnosis is DiagnosisCategory.COMPOSITE_CANDIDATE
        )

    def recurring_candidates(self) -> tuple[tuple[str, str, tuple[str, ...], bool], ...]:
        """(metric, candidate concept, tickers, recurring) for override-style findings."""
        seen: dict[tuple[str, str], list[str]] = {}
        for ticker, finding in self.findings():
            if finding.value_level:
                continue
            for concept in finding.candidates:
                seen.setdefault((finding.metric, concept), []).append(ticker)
        return tuple(
            (metric, concept, tuple(tickers), len(tickers) >= RECURRING_THRESHOLD)
            for (metric, concept), tickers in sorted(seen.items(), key=lambda i: (-len(i[1]), i[0]))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution": self.distribution(),
            "layer_counts": self.layer_counts(),
            "top_blockers": [list(b) for b in self.top_blockers(len(CANONICAL_METRICS))],
            "diagnosis_counts": self.diagnosis_counts(),
            "composites": [list(c) for c in self.composites()],
            "silently_stale": {c.ticker: list(c.silently_stale()) for c in self.surveyed
                               if c.silently_stale()},
            "restatements": {k: list(v) for k, v in self.restatements().items()},
            "resolved_conflicts": [list(r) for r in self.resolved_conflicts()],
            "recurring_candidates": [
                [m, c, list(t), r] for m, c, t, r in self.recurring_candidates()
            ],
            "metric_view": [_plain(m) for m in self.metric_view()],
            "companies": [_plain(c) for c in self.companies],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return {name: _plain(getattr(obj, name)) for name in obj.__dataclass_fields__}
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


# --- Formatting -----------------------------------------------------------------

_SHORT: Final = {
    "AVAILABLE": "OK", "PARTIAL": "PART", "INSUFFICIENT_DATA": "INSUF",
    "UNAVAILABLE": "UNAV", "BLOCKED": "BLOCK", "ERROR": "ERR",
}


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "n/a"


def format_company_view(report: UniverseReport) -> str:
    """One row per company: overall, six layer states, unsupported/invalid, primary blocker."""
    head = (
        f"{'Ticker':<6} {'Overall':<8} {'Owner':<6}{'CapEf':<6}{'EcVal':<6}"
        f"{'Comp':<6}{'CapAl':<6}{'Summ':<6} {'Unsupported':<34} {'Invalid':<24} "
        f"{'Stale (silent)':<28} Primary blocker"
    )
    lines = [head]
    for c in report.companies:
        states = "".join(
            f"{_SHORT[c.layers[layer].state.value]:<6}" if layer in c.layers else f"{'-':<6}"
            for layer in LAYERS
        )
        unsupported = ",".join(c.metrics_with(MetricStatus.UNSUPPORTED)) or "-"
        invalid = ",".join(c.metrics_with(MetricStatus.INVALID)) or "-"
        blocker = (
            f"{c.primary_blocker} [{c.primary_category.value}]" if c.primary_blocker else "-"
        )
        stale = ",".join(c.silently_stale()) or "-"
        lines.append(
            f"{c.ticker:<6} {c.overall.value:<8} {states} {unsupported[:34]:<34} "
            f"{invalid[:24]:<24} {stale[:28]:<28} {blocker[:110]}"
        )
    dist = report.distribution()
    total = len(report.companies)
    lines.append("")
    lines.append(
        "  ".join(f"{k}={v} ({_pct(v, total)})" for k, v in dist.items()) + f"  of {total}"
    )
    return "\n".join(lines)


def format_metric_view(report: UniverseReport) -> str:
    """One row per canonical metric across the universe."""
    lines = [
        (
            f"{'Metric':<25} {'Avail':>5} {'Unsup':>5} {'Inval':>5} {'Absent':>6} {'Blocks':>6}  "
            f"{'Dominant diagnosis':<20} Companies affected"
        )
    ]
    for m in report.metric_view():
        affected = "; ".join(
            f"{status.lower()}: {','.join(tickers)}" for status, tickers in m.affected.items() if tickers
        )
        lines.append(
            f"{m.metric:<25} {m.counts['AVAILABLE']:>5} {m.counts['UNSUPPORTED']:>5} "
            f"{m.counts['INVALID']:>5} {m.counts['STRUCTURALLY_ABSENT']:>6} "
            f"{len(m.blocking_companies):>6}  {m.dominant_diagnosis or '-':<20} {affected or '-'}"
        )
    return "\n".join(lines)


def format_pattern_view(report: UniverseReport) -> str:
    """Top blockers, diagnosis mix, composites, and recurring-versus-quirk candidates."""
    lines = ["Top blocking metrics (companies blocked):"]
    lines.extend(f"  {metric:<25} {count}" for metric, count in report.top_blockers())
    lines.append("Diagnosis categories (company-metric findings):")
    lines.extend(f"  {cat:<22} {n}" for cat, n in report.diagnosis_counts().items())
    stale = [(c.ticker, c.silently_stale()) for c in report.surveyed if c.silently_stale()]
    lines.append(
        f"Silently stale AVAILABLE metrics (selected concept has no recent value): "
        f"{sum(len(m) for _, m in stale)} in {len(stale)} companies"
    )
    lines.extend(f"  {t:<6} {', '.join(m)}" for t, m in stale)
    lines.append("Ambiguous duplicates by restatement kind:")
    lines.extend(
        f"  {kind:<14} {len(items):>2}  {', '.join(items)}"
        for kind, items in report.restatements().items()
    )
    resolved = report.resolved_conflicts()
    lines.append(f"Conflicts resolved by the normalizer (precision / stock split): {len(resolved)}")
    lines.extend(f"  {t:<6} {m:<22} {entry}" for t, m, entry in resolved)
    lines.append("Composite-metric candidates:")
    lines.extend(
        f"  {t:<6} {m:<16} {'value-level' if v else 'unsupported'}: {r}"
        for t, m, v, r in report.composites()
    )
    if not report.composites():
        lines.append("  none")
    lines.append(f"Alternative concepts (recurring = {RECURRING_THRESHOLD}+ companies):")
    for metric, concept, tickers, recurring in report.recurring_candidates():
        kind = "RECURRING" if recurring else "quirk"
        lines.append(f"  {kind:<9} {metric:<22} {concept:<50} {','.join(tickers)}")
    errors = [
        (c.ticker, layer, p.reason)
        for c in report.surveyed
        for layer, p in c.layers.items()
        if p.state is LayerState.ERROR
    ]
    if errors:
        lines.append("Likely OwnerLens bugs (unexpected layer exceptions):")
        lines.extend(f"  {t} {layer}: {reason}" for t, layer, reason in errors)
    return "\n".join(lines)

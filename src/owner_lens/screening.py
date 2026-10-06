"""Deterministic opportunity screening for OwnerLens.

This module supports OwnerLens Feature 7, the first investing-decision layer above
normalization. It composes the existing Feature 1 owner-economics rows and
Feature 2A-2D outputs, together with the Feature 6 coverage contract, into a
research-priority verdict for one company: which businesses look strong enough,
improving enough, and resilient enough to deserve expensive underwriting.

It answers "who deserves deeper work and why", never "is this cheap". No price,
multiple, intrinsic value, expected return, scenario, probability, or position
size appears here, and no LLM is involved: every band, gate, bucket, and reason
is a documented deterministic rule over facts OwnerLens already derived.

Three properties are deliberate and load bearing:

* **Margin levels are never scored across companies.** Only margin *trend* and
  *sign* are used, so a structurally low-margin, high-turnover business is not
  penalized for its business model. The one absolute cross-company level
  threshold in the design is ROIC, which is already capital-turnover adjusted.
* **ROIC level and ROIC trend are separated.** Level sets the capital-efficiency
  band; trend belongs to economic momentum. A company whose invested capital
  grew as its cash pile shrank can show a large ROIC fall while still earning an
  exceptional return, and must not screen as a broken business.
* **Missing data is never a zero or a neutral score.** An unavailable dimension
  is ``NOT_EVALUABLE``: excluded from the score, excluded from the evaluable
  count, and capped by an explicit coverage ceiling so absent negative evidence
  can never become an advantage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from typing import Any, Protocol

from owner_lens._trajectory import net_cash_trajectory
from owner_lens.canonical import (
    CanonicalDataError,
    CanonicalFinancialHistory,
    MetricStatus,
)
from owner_lens.capital_allocation import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationRow,
    build_capital_allocation_rows,
)
from owner_lens.capital_efficiency import (
    CapitalEfficiencyRow,
    capital_efficiency_from_history,
)
from owner_lens.compounding import (
    CompoundingClassification,
    EconomicCompoundingView,
    build_compounding_view,
    cagr,
)
from owner_lens.economic_summary import (
    EconomicValueSummary,
    OverallEconomicValueClassification,
    synthesize_economic_value_summary,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    EconomicValueSnapshot,
    build_economic_value_snapshots,
)
from owner_lens.owner_economics import OwnerEconomicsRow, owner_economics_from_history
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "BUCKET_ORDER",
    "DEFAULT_SCREENING_THRESHOLDS",
    "DIMENSION_ORDER",
    "CoverageClass",
    "DimensionBand",
    "DimensionScore",
    "LimitingFactor",
    "MomentumBasis",
    "ReasonCategory",
    "ScreeningBucket",
    "ScreeningDimension",
    "ScreeningEvidence",
    "ScreeningReason",
    "ScreeningResult",
    "ScreeningThresholds",
    "SetupType",
    "UniverseScreening",
    "assemble_screening_evidence",
    "format_screening_detail",
    "format_screening_result",
    "format_screening_table",
    "reason_category",
    "score_balance_sheet_strength",
    "score_business_quality",
    "score_capital_allocation",
    "score_capital_efficiency",
    "score_dimensions",
    "score_economic_momentum",
    "score_per_share_compounding",
    "screen_company",
    "screen_company_from_facts",
    "screen_company_from_history",
    "screen_universe",
    "screening_evidence_from_facts",
]


class ScreeningDimension(Enum):
    """One interpretable screening dimension."""

    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    CAPITAL_EFFICIENCY = "CAPITAL_EFFICIENCY"
    PER_SHARE_COMPOUNDING = "PER_SHARE_COMPOUNDING"
    BALANCE_SHEET_STRENGTH = "BALANCE_SHEET_STRENGTH"
    CAPITAL_ALLOCATION = "CAPITAL_ALLOCATION"
    ECONOMIC_MOMENTUM = "ECONOMIC_MOMENTUM"


# The fixed reporting order of the scored dimensions.
DIMENSION_ORDER: tuple[ScreeningDimension, ...] = (
    ScreeningDimension.BUSINESS_QUALITY,
    ScreeningDimension.CAPITAL_EFFICIENCY,
    ScreeningDimension.PER_SHARE_COMPOUNDING,
    ScreeningDimension.BALANCE_SHEET_STRENGTH,
    ScreeningDimension.CAPITAL_ALLOCATION,
    ScreeningDimension.ECONOMIC_MOMENTUM,
)


class DimensionBand(Enum):
    """Coarse ordinal band for one dimension. Deliberately not a continuous score.

    ``NOT_EVALUABLE`` means the inputs are unavailable, never that the dimension
    is neutral. It is excluded from the screening score and from the evaluable
    dimension count.
    """

    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    WEAK = "WEAK"
    POOR = "POOR"
    NOT_EVALUABLE = "NOT_EVALUABLE"

    @property
    def ordinal(self) -> int | None:
        """3, 2, 1, 0, or None when the dimension cannot be evaluated."""
        return _BAND_ORDINAL[self]

    def __ge__(self, other: DimensionBand) -> bool:
        return _compare(self, other) >= 0

    def __gt__(self, other: DimensionBand) -> bool:
        return _compare(self, other) > 0

    def __le__(self, other: DimensionBand) -> bool:
        return _compare(self, other) <= 0

    def __lt__(self, other: DimensionBand) -> bool:
        return _compare(self, other) < 0


_BAND_ORDINAL: dict[DimensionBand, int | None] = {
    DimensionBand.STRONG: 3,
    DimensionBand.ADEQUATE: 2,
    DimensionBand.WEAK: 1,
    DimensionBand.POOR: 0,
    DimensionBand.NOT_EVALUABLE: None,
}
# Ordered weakest to strongest; NOT_EVALUABLE sorts below POOR only for ordering,
# never for interpretation.
_BAND_BY_ORDINAL: dict[int, DimensionBand] = {
    3: DimensionBand.STRONG,
    2: DimensionBand.ADEQUATE,
    1: DimensionBand.WEAK,
    0: DimensionBand.POOR,
}


def _compare(left: DimensionBand, right: DimensionBand) -> int:
    """Compare two bands; NOT_EVALUABLE ranks below POOR for ordering purposes."""
    lhs = -1 if left.ordinal is None else left.ordinal
    rhs = -1 if right.ordinal is None else right.ordinal
    return (lhs > rhs) - (lhs < rhs)


def _shift(band: DimensionBand, notches: int) -> DimensionBand:
    """Move a band by whole notches, clamped to POOR..STRONG. Never shifts NOT_EVALUABLE."""
    if band is DimensionBand.NOT_EVALUABLE:
        return band
    current = band.ordinal
    assert current is not None
    return _BAND_BY_ORDINAL[max(0, min(3, current + notches))]


class MomentumBasis(Enum):
    """Which momentum path produced the band, so the reader knows what was seen."""

    ECONOMIC_VALUE_SUMMARY = "ECONOMIC_VALUE_SUMMARY"
    ANNUAL_SNAPSHOTS = "ANNUAL_SNAPSHOTS"
    OWNER_ECONOMICS_ONLY = "OWNER_ECONOMICS_ONLY"
    NONE = "NONE"


class CoverageClass(Enum):
    """The Feature 6 coverage taxonomy applied to the layers screening consumes.

    ``FULL`` means every layer screening needs produced usable output;
    ``PARTIAL`` means owner economics is usable but at least one other layer is
    not; ``FAILED`` means owner economics itself is unusable, so the company
    cannot be screened at all.
    """

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ScreeningReason(Enum):
    """Named, deterministic reason code explaining part of a screening result.

    Reasons restate evidence OwnerLens already derived. They introduce no new
    judgement, and each is categorized supporting, limiting, coverage, or gate.
    """

    # Supporting.
    DURABLE_CASH_GENERATION = "DURABLE_CASH_GENERATION"
    MARGINS_EXPANDING = "MARGINS_EXPANDING"
    EXCEPTIONAL_RETURNS_ON_CAPITAL = "EXCEPTIONAL_RETURNS_ON_CAPITAL"
    ROIC_IMPROVING = "ROIC_IMPROVING"
    STRONG_PER_SHARE_COMPOUNDING = "STRONG_PER_SHARE_COMPOUNDING"
    PER_SHARE_COMPOUNDING_ACCELERATING = "PER_SHARE_COMPOUNDING_ACCELERATING"
    SHARE_COUNT_SHRINKING = "SHARE_COUNT_SHRINKING"
    NET_CASH_POSITION = "NET_CASH_POSITION"
    DEBT_COMFORTABLY_COVERED_BY_CASH_FLOW = "DEBT_COMFORTABLY_COVERED_BY_CASH_FLOW"
    OWNER_FRIENDLY_CAPITAL_ALLOCATION = "OWNER_FRIENDLY_CAPITAL_ALLOCATION"
    EFFECTIVE_BUYBACKS = "EFFECTIVE_BUYBACKS"
    ECONOMICS_IMPROVING = "ECONOMICS_IMPROVING"

    # Limiting.
    CASH_GENERATION_INTERRUPTED = "CASH_GENERATION_INTERRUPTED"
    LATEST_YEAR_CASH_BURN = "LATEST_YEAR_CASH_BURN"
    MARGINS_CONTRACTING = "MARGINS_CONTRACTING"
    RETURNS_BELOW_QUALITY_THRESHOLD = "RETURNS_BELOW_QUALITY_THRESHOLD"
    ROIC_COLLAPSED_FROM_LOW_BASE = "ROIC_COLLAPSED_FROM_LOW_BASE"
    ROIC_FELL_BUT_LEVEL_REMAINS_HIGH = "ROIC_FELL_BUT_LEVEL_REMAINS_HIGH"
    PER_SHARE_COMPOUNDING_FLAT = "PER_SHARE_COMPOUNDING_FLAT"
    PER_SHARE_VALUE_DECLINING = "PER_SHARE_VALUE_DECLINING"
    PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY = "PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY"
    MATERIAL_DILUTION = "MATERIAL_DILUTION"
    NET_DEBT_POSITION = "NET_DEBT_POSITION"
    NET_CASH_CUSHION_SHRINKING = "NET_CASH_CUSHION_SHRINKING"
    LEVERAGE_RISING = "LEVERAGE_RISING"
    HEAVY_STOCK_BASED_COMPENSATION = "HEAVY_STOCK_BASED_COMPENSATION"
    CAPITAL_RETURNS_PERSISTENTLY_EXCEED_FCF = "CAPITAL_RETURNS_PERSISTENTLY_EXCEED_FCF"
    QUESTIONABLE_CAPITAL_ALLOCATION = "QUESTIONABLE_CAPITAL_ALLOCATION"
    ECONOMICS_DETERIORATING = "ECONOMICS_DETERIORATING"

    # Coverage.
    COVERAGE_LIMITED = "COVERAGE_LIMITED"
    MOMENTUM_FROM_OWNER_ECONOMICS_ONLY = "MOMENTUM_FROM_OWNER_ECONOMICS_ONLY"
    MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY = "MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY"
    PER_SHARE_METRICS_UNAVAILABLE = "PER_SHARE_METRICS_UNAVAILABLE"

    # Gate.
    COVERAGE_FAILED = "COVERAGE_FAILED"
    TOO_FEW_EVALUABLE_DIMENSIONS = "TOO_FEW_EVALUABLE_DIMENSIONS"
    PERSISTENT_CASH_BURN = "PERSISTENT_CASH_BURN"
    LEVERAGE_UNSUPPORTED_BY_CASH_FLOW = "LEVERAGE_UNSUPPORTED_BY_CASH_FLOW"
    NET_DEBT_WITHOUT_CASH_FLOW = "NET_DEBT_WITHOUT_CASH_FLOW"
    RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL = "RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL"
    PERSISTENT_MATERIAL_DILUTION = "PERSISTENT_MATERIAL_DILUTION"


class ReasonCategory(Enum):
    """How a reason should be presented to the reader."""

    SUPPORTING = "SUPPORTING"
    LIMITING = "LIMITING"
    COVERAGE = "COVERAGE"
    GATE = "GATE"


_REASON_CATEGORY: dict[ScreeningReason, ReasonCategory] = {
    ScreeningReason.DURABLE_CASH_GENERATION: ReasonCategory.SUPPORTING,
    ScreeningReason.MARGINS_EXPANDING: ReasonCategory.SUPPORTING,
    ScreeningReason.EXCEPTIONAL_RETURNS_ON_CAPITAL: ReasonCategory.SUPPORTING,
    ScreeningReason.ROIC_IMPROVING: ReasonCategory.SUPPORTING,
    ScreeningReason.STRONG_PER_SHARE_COMPOUNDING: ReasonCategory.SUPPORTING,
    ScreeningReason.PER_SHARE_COMPOUNDING_ACCELERATING: ReasonCategory.SUPPORTING,
    ScreeningReason.SHARE_COUNT_SHRINKING: ReasonCategory.SUPPORTING,
    ScreeningReason.NET_CASH_POSITION: ReasonCategory.SUPPORTING,
    ScreeningReason.DEBT_COMFORTABLY_COVERED_BY_CASH_FLOW: ReasonCategory.SUPPORTING,
    ScreeningReason.OWNER_FRIENDLY_CAPITAL_ALLOCATION: ReasonCategory.SUPPORTING,
    ScreeningReason.EFFECTIVE_BUYBACKS: ReasonCategory.SUPPORTING,
    ScreeningReason.ECONOMICS_IMPROVING: ReasonCategory.SUPPORTING,
    ScreeningReason.CASH_GENERATION_INTERRUPTED: ReasonCategory.LIMITING,
    ScreeningReason.LATEST_YEAR_CASH_BURN: ReasonCategory.LIMITING,
    ScreeningReason.MARGINS_CONTRACTING: ReasonCategory.LIMITING,
    ScreeningReason.RETURNS_BELOW_QUALITY_THRESHOLD: ReasonCategory.LIMITING,
    ScreeningReason.ROIC_COLLAPSED_FROM_LOW_BASE: ReasonCategory.LIMITING,
    ScreeningReason.ROIC_FELL_BUT_LEVEL_REMAINS_HIGH: ReasonCategory.LIMITING,
    ScreeningReason.PER_SHARE_COMPOUNDING_FLAT: ReasonCategory.LIMITING,
    ScreeningReason.PER_SHARE_VALUE_DECLINING: ReasonCategory.LIMITING,
    ScreeningReason.PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY: ReasonCategory.LIMITING,
    ScreeningReason.MATERIAL_DILUTION: ReasonCategory.LIMITING,
    ScreeningReason.NET_DEBT_POSITION: ReasonCategory.LIMITING,
    ScreeningReason.NET_CASH_CUSHION_SHRINKING: ReasonCategory.LIMITING,
    ScreeningReason.LEVERAGE_RISING: ReasonCategory.LIMITING,
    ScreeningReason.HEAVY_STOCK_BASED_COMPENSATION: ReasonCategory.LIMITING,
    ScreeningReason.CAPITAL_RETURNS_PERSISTENTLY_EXCEED_FCF: ReasonCategory.LIMITING,
    ScreeningReason.QUESTIONABLE_CAPITAL_ALLOCATION: ReasonCategory.LIMITING,
    ScreeningReason.ECONOMICS_DETERIORATING: ReasonCategory.LIMITING,
    ScreeningReason.COVERAGE_LIMITED: ReasonCategory.COVERAGE,
    ScreeningReason.MOMENTUM_FROM_OWNER_ECONOMICS_ONLY: ReasonCategory.COVERAGE,
    ScreeningReason.MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY: ReasonCategory.COVERAGE,
    ScreeningReason.PER_SHARE_METRICS_UNAVAILABLE: ReasonCategory.COVERAGE,
    ScreeningReason.COVERAGE_FAILED: ReasonCategory.GATE,
    ScreeningReason.TOO_FEW_EVALUABLE_DIMENSIONS: ReasonCategory.GATE,
    ScreeningReason.PERSISTENT_CASH_BURN: ReasonCategory.GATE,
    ScreeningReason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW: ReasonCategory.GATE,
    ScreeningReason.NET_DEBT_WITHOUT_CASH_FLOW: ReasonCategory.GATE,
    ScreeningReason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL: ReasonCategory.GATE,
    ScreeningReason.PERSISTENT_MATERIAL_DILUTION: ReasonCategory.GATE,
}


def reason_category(reason: ScreeningReason) -> ReasonCategory:
    """How a reason should be presented. Every reason has exactly one category."""
    return _REASON_CATEGORY[reason]


@dataclass(frozen=True)
class ScreeningThresholds:
    """Centralized, named cutoffs. Not configurable weights.

    These are inspectable boundaries a reader can change in one place; every
    band and gate is a documented rule, never a weighted sum. Growth and CAGR
    thresholds are fractions (0.15 == 15%); ROIC and margin thresholds are
    absolute values or differences in the ratio (0.03 == 3 percentage points);
    coverage ratios are multiples of free cash flow.

    Defaults reuse the existing OwnerLens cutoffs wherever one already exists,
    so screening cannot drift away from the Feature 2 interpretation.
    """

    # Capital efficiency (ROIC levels). ``strong_roic`` matches the
    # ``high_roic_level`` already used by Features 2A, 2B, 2C, and 2D.
    strong_roic: float = 0.20
    adequate_roic: float = 0.10
    weak_roic: float = 0.05
    # ROIC movement. ``material_roic_improvement`` matches Feature 2B's
    # ``material_roic_change``; ``severe_roic_collapse`` matches Feature 2D's.
    material_roic_improvement: float = 0.03
    severe_roic_collapse: float = 0.10

    # Per-share compounding. Both match Feature 2B's CAGR bands.
    strong_fcf_per_share_cagr: float = 0.15
    adequate_fcf_per_share_cagr: float = 0.07
    declining_fcf_per_share_cagr: float = -0.02
    # Share-count movement; matches Feature 2B's ``material_share_cagr``.
    material_share_cagr: float = 0.01

    # Business quality. Margin levels are never thresholded, only margin change.
    material_margin_change: float = 0.03
    durable_fcf_year_share: float = 0.80
    weak_fcf_year_share: float = 0.50

    # Balance-sheet strength, as multiples of latest free cash flow.
    net_debt_to_fcf_adequate: float = 2.0
    net_debt_to_fcf_weak: float = 4.0
    # Matches Feature 2C's ``net_cash_material_change``.
    material_net_cash_change: float = 0.05

    # Capital allocation.
    heavy_sbc_to_fcf: float = 0.25
    capital_returned_over_fcf: float = 1.00

    # Gates.
    gate_net_debt_to_fcf: float = 6.0
    gate_persistent_dilution_cagr: float = 0.05
    min_evaluable_dimensions: int = 2
    coverage_ceiling_dimensions: int = 3


DEFAULT_SCREENING_THRESHOLDS = ScreeningThresholds()


@dataclass(frozen=True)
class DimensionScore:
    """One dimension's band, its reasons, and the evidence behind it."""

    dimension: ScreeningDimension
    band: DimensionBand
    reasons: tuple[ScreeningReason, ...]
    evidence: tuple[str, ...]

    @property
    def evaluable(self) -> bool:
        return self.band is not DimensionBand.NOT_EVALUABLE


@dataclass(frozen=True)
class ScreeningEvidence:
    """Every Feature 1 and Feature 2 output screening could obtain for one company.

    Each component is ``None`` when the coverage contract blocks the layer that
    produces it. Nothing here is substituted, defaulted, or inferred: an absent
    component means the inputs were genuinely unavailable.
    """

    ticker: str
    coverage_class: CoverageClass
    owner_economics: tuple[OwnerEconomicsRow, ...]
    capital_efficiency: tuple[CapitalEfficiencyRow, ...]
    snapshots: tuple[EconomicValueSnapshot, ...]
    recent_compounding: EconomicCompoundingView | None
    long_term_compounding: EconomicCompoundingView | None
    capital_allocation: tuple[CapitalAllocationRow, ...]
    summary: EconomicValueSummary | None
    unavailable_metrics: tuple[str, ...]
    blocked_layers: tuple[str, ...]

    @property
    def latest_fiscal_year(self) -> int | None:
        return self.owner_economics[-1].fiscal_year if self.owner_economics else None

    @property
    def latest_owner_economics(self) -> OwnerEconomicsRow | None:
        return self.owner_economics[-1] if self.owner_economics else None

    @property
    def latest_capital_efficiency(self) -> CapitalEfficiencyRow | None:
        return self.capital_efficiency[-1] if self.capital_efficiency else None

    @property
    def latest_capital_allocation(self) -> CapitalAllocationRow | None:
        return self.capital_allocation[-1] if self.capital_allocation else None


# --- Evidence assembly ---------------------------------------------------------

# Layers screening consumes, in pipeline order. These mirror the Feature 6
# coverage layers, minus the economic summary, which is derived from the rest.
_SCREENING_LAYERS: tuple[str, ...] = (
    "owner_economics",
    "capital_efficiency",
    "economic_value",
    "compounding",
    "capital_allocation",
)


class _AnnualRow(Protocol):
    @property
    def fiscal_year(self) -> int: ...


def _ascending[RowT: _AnnualRow](rows: Sequence[RowT]) -> tuple[RowT, ...]:
    return tuple(sorted(rows, key=lambda row: row.fiscal_year))


def assemble_screening_evidence(
    history: CanonicalFinancialHistory,
) -> ScreeningEvidence:
    """Run each analytical layer at most once and record what was obtainable.

    Layers are composed from the two base layers (owner economics and capital
    efficiency) rather than re-derived from the history, so screening a company
    costs the same as one Feature 2 pass regardless of how many dimensions it
    can evaluate. A layer that cannot run is recorded as blocked with the
    canonical metrics that blocked it; it is never replaced by a default.
    """
    ticker = history.ticker
    statuses = history.statuses()
    unavailable = tuple(
        metric
        for metric, status in statuses.items()
        if status is not MetricStatus.AVAILABLE
        and status is not MetricStatus.STRUCTURALLY_ABSENT
    )
    blocked: list[str] = []

    try:
        owner = _ascending(owner_economics_from_history(history))
    except CanonicalDataError:
        return ScreeningEvidence(
            ticker=ticker,
            coverage_class=CoverageClass.FAILED,
            owner_economics=(),
            capital_efficiency=(),
            snapshots=(),
            recent_compounding=None,
            long_term_compounding=None,
            capital_allocation=(),
            summary=None,
            unavailable_metrics=unavailable,
            blocked_layers=_SCREENING_LAYERS,
        )

    try:
        capital = _ascending(capital_efficiency_from_history(history))
    except CanonicalDataError:
        capital = ()
        blocked.append("capital_efficiency")

    snapshots: tuple[EconomicValueSnapshot, ...] = ()
    recent: EconomicCompoundingView | None = None
    long_term: EconomicCompoundingView | None = None
    allocation: tuple[CapitalAllocationRow, ...] = ()
    summary: EconomicValueSummary | None = None

    if capital:
        snapshots = _ascending(build_economic_value_snapshots(owner, capital))
        if all(
            snap.classification is EconomicValueClassification.INSUFFICIENT_DATA
            for snap in snapshots
        ):
            snapshots = ()
            blocked.append("economic_value")
        recent, long_term = _compounding_views(owner, capital, snapshots)
        if (
            recent.classification is CompoundingClassification.INSUFFICIENT_DATA
            and long_term.classification is CompoundingClassification.INSUFFICIENT_DATA
        ):
            recent = long_term = None
            blocked.append("compounding")
        allocation = _capital_allocation(history, owner, capital, snapshots)
        if not allocation:
            blocked.append("capital_allocation")
        if long_term is not None and allocation:
            summary = synthesize_economic_value_summary(
                ticker, snapshots, recent, long_term, allocation
            )
            if (
                summary.overall_economic_value_classification
                is OverallEconomicValueClassification.INSUFFICIENT_DATA
            ):
                summary = None
    else:
        blocked.extend(("economic_value", "compounding", "capital_allocation"))

    coverage_class = (
        CoverageClass.FULL
        if not blocked and summary is not None
        else CoverageClass.PARTIAL
    )
    return ScreeningEvidence(
        ticker=ticker,
        coverage_class=coverage_class,
        owner_economics=owner,
        capital_efficiency=capital,
        snapshots=snapshots,
        recent_compounding=recent,
        long_term_compounding=long_term,
        capital_allocation=allocation,
        summary=summary,
        unavailable_metrics=unavailable,
        blocked_layers=tuple(blocked),
    )


def _compounding_views(
    owner: Sequence[OwnerEconomicsRow],
    capital: Sequence[CapitalEfficiencyRow],
    snapshots: Sequence[EconomicValueSnapshot],
) -> tuple[EconomicCompoundingView, EconomicCompoundingView]:
    """Build the recent 3-year and longest-available views from already-derived rows."""
    common = {row.fiscal_year for row in owner} & {row.fiscal_year for row in capital}
    intervals = max(len(common) - 1, 0)
    recent = build_compounding_view(owner, capital, snapshots, period_years=3)
    long_term = build_compounding_view(
        owner, capital, snapshots, period_years=min(5, intervals)
    )
    return recent, long_term


def _capital_allocation(
    history: CanonicalFinancialHistory,
    owner: Sequence[OwnerEconomicsRow],
    capital: Sequence[CapitalEfficiencyRow],
    snapshots: Sequence[EconomicValueSnapshot],
) -> tuple[CapitalAllocationRow, ...]:
    """Build capital-allocation rows, or return empty when an input is unusable."""
    try:
        repurchases = history.require("repurchases")
        sbc = history.require("stock_based_compensation")
        dividends = history.require("dividends_paid")
    except CanonicalDataError:
        return ()
    rows = _ascending(
        build_capital_allocation_rows(owner, capital, snapshots, repurchases, sbc, dividends)
    )
    if all(
        row.classification is CapitalAllocationClassification.INSUFFICIENT_DATA
        for row in rows
    ):
        return ()
    return rows


def screening_evidence_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> ScreeningEvidence:
    """Compatibility wrapper: map raw SEC Company Facts, then assemble evidence."""
    return assemble_screening_evidence(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
    )


# --- Dimension scoring ---------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _billions(value: int | None) -> str:
    return "n/a" if value is None else f"{value / 1e9:+,.1f}B"


def _not_evaluable(
    dimension: ScreeningDimension, *reasons: ScreeningReason
) -> DimensionScore:
    return DimensionScore(dimension, DimensionBand.NOT_EVALUABLE, reasons, ())


def score_business_quality(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band how reliably the business converts activity into cash, and the trend.

    The base band comes from cash-generation durability: how many years produced
    positive free cash flow, and whether the latest year matches or exceeds the
    earliest. A bounded one-notch modifier applies the margin *trend*. Margin
    levels are never used, so a 3% margin, high-turnover retailer and a 40%
    margin software business are banded on the same evidence.
    """
    dimension = ScreeningDimension.BUSINESS_QUALITY
    rows = evidence.owner_economics
    fcf = [row.free_cash_flow for row in rows if row.free_cash_flow is not None]
    if len(fcf) < 2:
        return _not_evaluable(dimension)

    positive = sum(1 for value in fcf if value > 0)
    share = positive / len(fcf)
    latest, earliest = fcf[-1], fcf[0]
    reasons: list[ScreeningReason] = []

    if latest <= 0:
        band = DimensionBand.POOR
        reasons.append(ScreeningReason.LATEST_YEAR_CASH_BURN)
    elif positive == len(fcf) and latest >= earliest:
        band = DimensionBand.STRONG
        reasons.append(ScreeningReason.DURABLE_CASH_GENERATION)
    elif share >= thresholds.durable_fcf_year_share:
        band = DimensionBand.ADEQUATE
        if positive < len(fcf):
            reasons.append(ScreeningReason.CASH_GENERATION_INTERRUPTED)
    elif share >= thresholds.weak_fcf_year_share:
        band = DimensionBand.WEAK
        reasons.append(ScreeningReason.CASH_GENERATION_INTERRUPTED)
    else:
        band = DimensionBand.POOR
        reasons.append(ScreeningReason.CASH_GENERATION_INTERRUPTED)

    operating_change = _margin_change(rows, "operating_margin")
    fcf_margin_change = _margin_change(rows, "fcf_margin")
    if operating_change is not None and fcf_margin_change is not None:
        if (
            operating_change <= -thresholds.material_margin_change
            and fcf_margin_change < 0
        ):
            band = _shift(band, -1)
            reasons.append(ScreeningReason.MARGINS_CONTRACTING)
        elif (
            operating_change >= thresholds.material_margin_change
            and fcf_margin_change >= 0
        ):
            band = _shift(band, 1)
            reasons.append(ScreeningReason.MARGINS_EXPANDING)

    evidence_lines = (
        f"FCF positive in {positive} of {len(fcf)} years",
        f"operating margin change {_pct(operating_change)}",
        f"FCF margin change {_pct(fcf_margin_change)}",
    )
    return DimensionScore(dimension, band, tuple(reasons), evidence_lines)


def _margin_change(rows: Sequence[OwnerEconomicsRow], attribute: str) -> float | None:
    """Start-to-end change in a margin, or None when either endpoint is missing."""
    values = [
        getattr(row, attribute) for row in rows if getattr(row, attribute) is not None
    ]
    return values[-1] - values[0] if len(values) >= 2 else None


def score_capital_efficiency(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band the return the business earns on the capital it employs, by level.

    The band is set by the ROIC *level* alone. A ROIC fall demotes the band only
    when the resulting level is already below the strong threshold, because a
    large fall from an extraordinary base can still leave an exceptional return:
    invested capital grows mechanically as a net-cash pile is spent, and that is
    a balance-sheet fact rather than a deterioration in earning power. The
    direction of ROIC is reported here as a reason and scored under economic
    momentum.
    """
    dimension = ScreeningDimension.CAPITAL_EFFICIENCY
    rows = evidence.capital_efficiency
    roic_values = [row.roic for row in rows if row.roic is not None]
    if not roic_values:
        return _not_evaluable(dimension)

    latest = roic_values[-1]
    change = roic_values[-1] - roic_values[0] if len(roic_values) >= 2 else None
    reasons: list[ScreeningReason] = []

    if latest >= thresholds.strong_roic:
        band = DimensionBand.STRONG
        reasons.append(ScreeningReason.EXCEPTIONAL_RETURNS_ON_CAPITAL)
    elif latest >= thresholds.adequate_roic:
        band = DimensionBand.ADEQUATE
    elif latest >= thresholds.weak_roic:
        band = DimensionBand.WEAK
        reasons.append(ScreeningReason.RETURNS_BELOW_QUALITY_THRESHOLD)
    else:
        band = DimensionBand.POOR
        reasons.append(ScreeningReason.RETURNS_BELOW_QUALITY_THRESHOLD)

    if change is not None:
        if change <= -thresholds.severe_roic_collapse:
            if latest >= thresholds.strong_roic:
                reasons.append(ScreeningReason.ROIC_FELL_BUT_LEVEL_REMAINS_HIGH)
            else:
                band = _shift(band, -1)
                reasons.append(ScreeningReason.ROIC_COLLAPSED_FROM_LOW_BASE)
        elif change >= thresholds.material_roic_improvement:
            reasons.append(ScreeningReason.ROIC_IMPROVING)

    evidence_lines = (
        f"ROIC {_ratio(latest)}",
        f"ROIC change over window {_pct(change)}",
    )
    return DimensionScore(dimension, band, tuple(reasons), evidence_lines)


def score_per_share_compounding(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band the growth of economic value per ownership unit.

    The base band is the long-term FCF/share CAGR. A bounded one-notch modifier
    applies the share-count direction, and the upward modifier additionally
    requires aggregate free cash flow not to have declined: shrinking the
    denominator while the numerator erodes is not compounding, and is reported
    as such.
    """
    dimension = ScreeningDimension.PER_SHARE_COMPOUNDING
    rows = evidence.owner_economics
    per_share = [
        (row.fiscal_year, row.fcf_per_share)
        for row in rows
        if row.fcf_per_share is not None
    ]
    if len(per_share) < 2:
        return _not_evaluable(dimension, ScreeningReason.PER_SHARE_METRICS_UNAVAILABLE)

    years = per_share[-1][0] - per_share[0][0]
    start, end = per_share[0][1], per_share[-1][1]
    per_share_cagr = cagr(start, end, years)
    reasons: list[ScreeningReason] = []

    if per_share_cagr is None:
        # A sign change makes the CAGR undefined; the direction is still knowable.
        if end <= 0 or end < start:
            band = DimensionBand.POOR
            reasons.append(ScreeningReason.PER_SHARE_VALUE_DECLINING)
        else:
            band = DimensionBand.WEAK
            reasons.append(ScreeningReason.PER_SHARE_COMPOUNDING_FLAT)
    elif per_share_cagr >= thresholds.strong_fcf_per_share_cagr:
        band = DimensionBand.STRONG
        reasons.append(ScreeningReason.STRONG_PER_SHARE_COMPOUNDING)
    elif per_share_cagr >= thresholds.adequate_fcf_per_share_cagr:
        band = DimensionBand.ADEQUATE
    elif per_share_cagr > thresholds.declining_fcf_per_share_cagr:
        band = DimensionBand.WEAK
        reasons.append(ScreeningReason.PER_SHARE_COMPOUNDING_FLAT)
    else:
        band = DimensionBand.POOR
        reasons.append(ScreeningReason.PER_SHARE_VALUE_DECLINING)

    share_cagr = _share_cagr(rows)
    fcf_cagr = _aggregate_fcf_cagr(rows)
    if share_cagr is not None:
        if share_cagr >= thresholds.material_share_cagr:
            band = _shift(band, -1)
            reasons.append(ScreeningReason.MATERIAL_DILUTION)
        elif share_cagr <= -thresholds.material_share_cagr:
            if fcf_cagr is not None and fcf_cagr >= 0:
                band = _shift(band, 1)
                reasons.append(ScreeningReason.SHARE_COUNT_SHRINKING)
            elif fcf_cagr is not None:
                reasons.append(ScreeningReason.PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY)

    if _accelerating(evidence):
        reasons.append(ScreeningReason.PER_SHARE_COMPOUNDING_ACCELERATING)

    evidence_lines = (
        f"FCF/share CAGR {_pct(per_share_cagr)} over {years} years",
        f"diluted-share CAGR {_pct(share_cagr)}",
        f"aggregate FCF CAGR {_pct(fcf_cagr)}",
    )
    return DimensionScore(dimension, band, tuple(reasons), evidence_lines)


def _share_cagr(rows: Sequence[OwnerEconomicsRow]) -> float | None:
    shares = [
        (row.fiscal_year, row.diluted_shares.value)
        for row in rows
        if row.diluted_shares is not None
    ]
    if len(shares) < 2:
        return None
    return cagr(shares[0][1], shares[-1][1], shares[-1][0] - shares[0][0])


def _aggregate_fcf_cagr(rows: Sequence[OwnerEconomicsRow]) -> float | None:
    values = [
        (row.fiscal_year, row.free_cash_flow)
        for row in rows
        if row.free_cash_flow is not None
    ]
    if len(values) < 2:
        return None
    return cagr(values[0][1], values[-1][1], values[-1][0] - values[0][0])


def _accelerating(evidence: ScreeningEvidence) -> bool:
    """Whether the recent per-share CAGR materially exceeds the long-term one."""
    recent, long_term = evidence.recent_compounding, evidence.long_term_compounding
    if recent is None or long_term is None:
        return False
    recent_cagr = recent.fcf_per_share_cagr
    long_cagr = long_term.fcf_per_share_cagr
    return (
        recent_cagr is not None and long_cagr is not None and recent_cagr > long_cagr + 0.01
    )


def _latest_free_cash_flow(rows: Sequence[OwnerEconomicsRow]) -> int | None:
    """The most recent derivable free cash flow, or None when none is derivable.

    Every caller must resolve the latest cash flow the same way, so a year whose
    free cash flow could not be derived cannot make one rule see a different
    "latest year" than another.
    """
    for row in reversed(rows):
        if row.free_cash_flow is not None:
            return row.free_cash_flow
    return None


def score_balance_sheet_strength(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band whether the company can survive a bad outcome without a forced decision.

    A net-cash company is strong regardless of size. A net-debt company is
    banded by how many years of latest free cash flow the debt represents, so a
    net-debt position with no derivable free cash flow cannot be banded at all
    and reports ``NOT_EVALUABLE`` rather than the worst band. A shrinking
    net-cash cushion is reported but does not demote a company that remains in
    net cash; only a materially deteriorating *net-debt* position demotes, using
    the same materiality rule Feature 2C applies to net cash.
    """
    dimension = ScreeningDimension.BALANCE_SHEET_STRENGTH
    rows = evidence.capital_efficiency
    positions = [row.net_cash for row in rows if row.net_cash is not None]
    fcf = _latest_free_cash_flow(evidence.owner_economics)
    if not positions:
        return _not_evaluable(dimension)

    latest = positions[-1]
    change = latest - positions[0] if len(positions) >= 2 else None
    trajectory = (
        net_cash_trajectory(
            positions[0], positions[-1], material=thresholds.material_net_cash_change
        )
        if len(positions) >= 2
        else None
    )
    deteriorated = trajectory is not None and trajectory.direction < 0
    reasons: list[ScreeningReason] = []

    if latest >= 0:
        band = DimensionBand.STRONG
        reasons.append(ScreeningReason.NET_CASH_POSITION)
        if deteriorated:
            reasons.append(ScreeningReason.NET_CASH_CUSHION_SHRINKING)
        coverage = None
    else:
        if fcf is None:
            # Net debt with no derivable cash flow cannot be sized against
            # anything; refusing is the honest answer, not banding it worst.
            return _not_evaluable(dimension)
        reasons.append(ScreeningReason.NET_DEBT_POSITION)
        net_debt = -latest
        if fcf <= 0:
            band = DimensionBand.POOR
            coverage = None
        else:
            coverage = net_debt / fcf
            if coverage <= thresholds.net_debt_to_fcf_adequate:
                band = DimensionBand.ADEQUATE
                reasons.append(ScreeningReason.DEBT_COMFORTABLY_COVERED_BY_CASH_FLOW)
            elif coverage <= thresholds.net_debt_to_fcf_weak:
                band = DimensionBand.WEAK
            else:
                band = DimensionBand.POOR
        if deteriorated:
            band = _shift(band, -1)
            reasons.append(ScreeningReason.LEVERAGE_RISING)

    evidence_lines = (
        f"net cash/debt {_billions(latest)}",
        f"change over window {_billions(change)}",
        "net debt / FCF n/a" if coverage is None else f"net debt / FCF {coverage:.1f}x",
    )
    return DimensionScore(dimension, band, tuple(reasons), evidence_lines)


def score_capital_allocation(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band whether management converts cash into owner value.

    The base band is the existing Feature 2C classification, so screening
    introduces no second opinion on capital allocation. A bounded one-notch
    modifier applies heavy stock-based compensation or capital returns that
    persistently exceed free cash flow; persistence is required so a single
    year's buyback surge does not demote a sound allocator.
    """
    dimension = ScreeningDimension.CAPITAL_ALLOCATION
    rows = evidence.capital_allocation
    latest = evidence.latest_capital_allocation
    if latest is None or latest.classification is CapitalAllocationClassification.INSUFFICIENT_DATA:
        return _not_evaluable(dimension)

    band = _ALLOCATION_BAND[latest.classification]
    reasons: list[ScreeningReason] = []
    if latest.classification is CapitalAllocationClassification.OWNER_FRIENDLY:
        reasons.append(ScreeningReason.OWNER_FRIENDLY_CAPITAL_ALLOCATION)
    elif latest.classification in (
        CapitalAllocationClassification.QUESTIONABLE,
        CapitalAllocationClassification.OWNER_UNFRIENDLY,
    ):
        reasons.append(ScreeningReason.QUESTIONABLE_CAPITAL_ALLOCATION)
    if latest.buyback_effectiveness is BuybackEffectiveness.EFFECTIVE_BUYBACKS:
        reasons.append(ScreeningReason.EFFECTIVE_BUYBACKS)

    heavy_sbc = (
        latest.sbc_over_fcf is not None
        and latest.sbc_over_fcf >= thresholds.heavy_sbc_to_fcf
    )
    overdistributing = _persistently_over_distributing(rows, thresholds)
    if heavy_sbc or overdistributing:
        band = _shift(band, -1)
        if heavy_sbc:
            reasons.append(ScreeningReason.HEAVY_STOCK_BASED_COMPENSATION)
        if overdistributing:
            reasons.append(ScreeningReason.CAPITAL_RETURNS_PERSISTENTLY_EXCEED_FCF)

    evidence_lines = (
        f"capital allocation {latest.classification.value}",
        f"SBC / FCF {_ratio(latest.sbc_over_fcf)}",
        f"capital returned / FCF {_ratio(latest.capital_returned_over_fcf)}",
    )
    return DimensionScore(dimension, band, tuple(reasons), evidence_lines)


_ALLOCATION_BAND: dict[CapitalAllocationClassification, DimensionBand] = {
    CapitalAllocationClassification.OWNER_FRIENDLY: DimensionBand.STRONG,
    CapitalAllocationClassification.BALANCED: DimensionBand.ADEQUATE,
    CapitalAllocationClassification.QUESTIONABLE: DimensionBand.WEAK,
    CapitalAllocationClassification.OWNER_UNFRIENDLY: DimensionBand.POOR,
}


def _persistently_over_distributing(
    rows: Sequence[CapitalAllocationRow], thresholds: ScreeningThresholds
) -> bool:
    """Whether capital returned exceeded FCF in a majority of measurable years."""
    ratios = [
        row.capital_returned_over_fcf
        for row in rows
        if row.capital_returned_over_fcf is not None
    ]
    if not ratios:
        return False
    over = sum(1 for ratio in ratios if ratio > thresholds.capital_returned_over_fcf)
    return over * 2 > len(ratios)


def score_economic_momentum(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> DimensionScore:
    """Band whether economics are improving, stable, or deteriorating.

    Three paths, each labelled so the reader knows what was actually seen. The
    full path uses the Feature 2D company-level verdict. The annual path uses
    the Feature 2A snapshots when compounding or capital allocation is blocked.
    The owner-economics path reads the direction of the FCF/share *level* series
    rather than growth percentages, because a sign change makes a growth
    percentage meaningless, and it is capped at ``ADEQUATE`` because it sees far
    less than the other two.
    """
    dimension = ScreeningDimension.ECONOMIC_MOMENTUM
    summary = evidence.summary
    if summary is not None:
        band = _MOMENTUM_BAND[summary.overall_economic_value_classification]
        return DimensionScore(
            dimension,
            band,
            _momentum_reasons(band, MomentumBasis.ECONOMIC_VALUE_SUMMARY),
            (
                f"overall economic value {summary.overall_economic_value_classification.value}",
                f"basis {MomentumBasis.ECONOMIC_VALUE_SUMMARY.value}",
            ),
        )

    if evidence.snapshots:
        return _momentum_from_snapshots(dimension, evidence.snapshots)
    return _momentum_from_owner_economics(dimension, evidence.owner_economics)


_MOMENTUM_BAND: dict[OverallEconomicValueClassification, DimensionBand] = {
    OverallEconomicValueClassification.STRONGLY_IMPROVING: DimensionBand.STRONG,
    OverallEconomicValueClassification.IMPROVING: DimensionBand.STRONG,
    OverallEconomicValueClassification.STABLE: DimensionBand.ADEQUATE,
    OverallEconomicValueClassification.DETERIORATING: DimensionBand.WEAK,
    OverallEconomicValueClassification.STRONGLY_DETERIORATING: DimensionBand.POOR,
    OverallEconomicValueClassification.INSUFFICIENT_DATA: DimensionBand.NOT_EVALUABLE,
}

_BASIS_REASON: dict[MomentumBasis, ScreeningReason | None] = {
    MomentumBasis.ECONOMIC_VALUE_SUMMARY: None,
    MomentumBasis.ANNUAL_SNAPSHOTS: ScreeningReason.MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY,
    MomentumBasis.OWNER_ECONOMICS_ONLY: ScreeningReason.MOMENTUM_FROM_OWNER_ECONOMICS_ONLY,
    MomentumBasis.NONE: None,
}


def _momentum_reasons(
    band: DimensionBand, basis: MomentumBasis
) -> tuple[ScreeningReason, ...]:
    reasons: list[ScreeningReason] = []
    if band >= DimensionBand.STRONG:
        reasons.append(ScreeningReason.ECONOMICS_IMPROVING)
    elif band <= DimensionBand.WEAK and band is not DimensionBand.NOT_EVALUABLE:
        reasons.append(ScreeningReason.ECONOMICS_DETERIORATING)
    basis_reason = _BASIS_REASON[basis]
    if basis_reason is not None:
        reasons.append(basis_reason)
    return tuple(reasons)


def _momentum_from_snapshots(
    dimension: ScreeningDimension, snapshots: Sequence[EconomicValueSnapshot]
) -> DimensionScore:
    """Band momentum from the annual verdicts when the company-level one is blocked."""
    verdicts = [
        snap.classification
        for snap in snapshots
        if snap.classification is not EconomicValueClassification.INSUFFICIENT_DATA
    ]
    if not verdicts:
        return _not_evaluable(dimension)

    improving = sum(1 for v in verdicts if v is EconomicValueClassification.IMPROVING)
    deteriorating = sum(
        1 for v in verdicts if v is EconomicValueClassification.DETERIORATING
    )
    latest = verdicts[-1]
    if latest is EconomicValueClassification.IMPROVING and improving >= deteriorating:
        band = DimensionBand.STRONG
    elif latest is EconomicValueClassification.DETERIORATING and deteriorating > improving:
        band = DimensionBand.POOR
    elif latest is EconomicValueClassification.DETERIORATING:
        band = DimensionBand.WEAK
    else:
        band = DimensionBand.ADEQUATE

    return DimensionScore(
        dimension,
        band,
        _momentum_reasons(band, MomentumBasis.ANNUAL_SNAPSHOTS),
        (
            f"latest annual economic value {latest.value}",
            f"{improving} improving / {deteriorating} deteriorating years",
            f"basis {MomentumBasis.ANNUAL_SNAPSHOTS.value}",
        ),
    )


def _momentum_from_owner_economics(
    dimension: ScreeningDimension, rows: Sequence[OwnerEconomicsRow]
) -> DimensionScore:
    """Band momentum from the FCF/share level direction, capped at ADEQUATE.

    Levels, not growth percentages: a series crossing zero produces a growth
    percentage with no economic meaning, while its direction remains readable.
    """
    levels = [row.fcf_per_share for row in rows if row.fcf_per_share is not None]
    if len(levels) < 3:
        return _not_evaluable(dimension, ScreeningReason.MOMENTUM_FROM_OWNER_ECONOMICS_ONLY)

    latest, previous, earliest = levels[-1], levels[-2], levels[0]
    rising_steps = sum(1 for prior, current in pairwise(levels) if current > prior)
    majority_rising = rising_steps * 2 > len(levels) - 1

    if latest <= 0:
        band = DimensionBand.POOR
    elif latest > previous and latest > earliest and majority_rising:
        band = DimensionBand.ADEQUATE
    elif latest < earliest and latest < previous:
        band = DimensionBand.POOR
    elif latest < earliest or latest < previous:
        band = DimensionBand.WEAK
    else:
        band = DimensionBand.ADEQUATE

    return DimensionScore(
        dimension,
        band,
        _momentum_reasons(band, MomentumBasis.OWNER_ECONOMICS_ONLY),
        (
            f"FCF/share {earliest:.2f} → {latest:.2f}",
            f"{rising_steps} of {len(levels) - 1} years rising",
            f"basis {MomentumBasis.OWNER_ECONOMICS_ONLY.value}",
        ),
    )


_SCORERS = {
    ScreeningDimension.BUSINESS_QUALITY: score_business_quality,
    ScreeningDimension.CAPITAL_EFFICIENCY: score_capital_efficiency,
    ScreeningDimension.PER_SHARE_COMPOUNDING: score_per_share_compounding,
    ScreeningDimension.BALANCE_SHEET_STRENGTH: score_balance_sheet_strength,
    ScreeningDimension.CAPITAL_ALLOCATION: score_capital_allocation,
    ScreeningDimension.ECONOMIC_MOMENTUM: score_economic_momentum,
}


def score_dimensions(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> dict[ScreeningDimension, DimensionScore]:
    """Score every dimension in the fixed reporting order."""
    return {
        dimension: _SCORERS[dimension](evidence, thresholds=thresholds)
        for dimension in DIMENSION_ORDER
    }


# --- Buckets, gates, and the screening result ----------------------------------


class ScreeningBucket(Enum):
    """Research priority, never investment advice.

    A bucket answers "how soon should a human spend expensive underwriting time
    on this company". It is not a buy, sell, hold, or valuation statement.
    """

    HIGH_PRIORITY = "HIGH_PRIORITY"
    WORTH_UNDERWRITING = "WORTH_UNDERWRITING"
    WATCH = "WATCH"
    LOW_PRIORITY = "LOW_PRIORITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Ordered strongest to weakest, so a ceiling is a maximum index lookup.
BUCKET_ORDER: tuple[ScreeningBucket, ...] = (
    ScreeningBucket.HIGH_PRIORITY,
    ScreeningBucket.WORTH_UNDERWRITING,
    ScreeningBucket.WATCH,
    ScreeningBucket.LOW_PRIORITY,
    ScreeningBucket.INSUFFICIENT_DATA,
)


class SetupType(Enum):
    """Why a company is interesting, orthogonal to how urgently to look at it.

    ``COMPOUNDER`` is an already-excellent business still compounding.
    ``POTENTIAL_ASYMMETRIC_SETUP`` is a business whose returns on capital and
    balance sheet remain intact while its recent economics look weak, which is
    the shape a temporarily depressed quality business takes. Neither label is a
    recommendation, and neither considers price.
    """

    COMPOUNDER = "COMPOUNDER"
    POTENTIAL_ASYMMETRIC_SETUP = "POTENTIAL_ASYMMETRIC_SETUP"
    NEITHER = "NEITHER"


class LimitingFactor(Enum):
    """Whether a company ranks low because it is weak or because it is unseeable."""

    NONE = "NONE"
    FUNDAMENTALS = "FUNDAMENTALS"
    COVERAGE = "COVERAGE"
    BOTH = "BOTH"


@dataclass(frozen=True)
class ScreeningResult:
    """One company's deterministic screening verdict with its full justification."""

    ticker: str
    latest_fiscal_year: int | None
    coverage_class: CoverageClass
    bucket: ScreeningBucket
    setup_type: SetupType
    limiting_factor: LimitingFactor
    dimensions: dict[ScreeningDimension, DimensionScore]
    screening_score: int
    evaluable_dimensions: int
    coverage_ceiling: ScreeningBucket | None
    gate: ScreeningReason | None
    supporting_reasons: tuple[ScreeningReason, ...]
    limiting_reasons: tuple[ScreeningReason, ...]
    coverage_reasons: tuple[ScreeningReason, ...]
    unavailable_dimensions: tuple[ScreeningDimension, ...]
    unavailable_metrics: tuple[str, ...]

    def band(self, dimension: ScreeningDimension) -> DimensionBand:
        return self.dimensions[dimension].band

    @property
    def rank_key(self) -> tuple[int, int, int, str]:
        """Deterministic ordering: bucket, then coverage class, then score, then ticker.

        The score orders companies *within* a bucket only. It is never a cutoff,
        and it is not comparable across coverage classes, which is why the
        coverage class sorts ahead of it.
        """
        return (
            BUCKET_ORDER.index(self.bucket),
            _COVERAGE_RANK[self.coverage_class],
            -self.screening_score,
            self.ticker,
        )


_COVERAGE_RANK: dict[CoverageClass, int] = {
    CoverageClass.FULL: 0,
    CoverageClass.PARTIAL: 1,
    CoverageClass.FAILED: 2,
}


def _gate(
    evidence: ScreeningEvidence,
    scores: dict[ScreeningDimension, DimensionScore],
    thresholds: ScreeningThresholds,
) -> tuple[ScreeningBucket, ScreeningReason] | None:
    """Apply the survival and usability gates in their documented order.

    Gates are deliberately **not** quality preferences. They remove companies
    that cannot be screened at all (G0a, G0b), that do not generate cash (G1),
    that carry leverage their cash flow cannot service (G2), that earn no
    plausible return on capital (G3), or that dilute owners faster than any
    operating result can offset (G4). Cash generation is checked before
    leverage, because a business that does not produce cash is disqualified on
    its own terms rather than on its balance sheet. A gate whose inputs are
    unavailable is skipped, never assumed.
    """
    evaluable = [score for score in scores.values() if score.evaluable]

    # G0a — the company cannot be screened at all.
    if evidence.coverage_class is CoverageClass.FAILED:
        return ScreeningBucket.INSUFFICIENT_DATA, ScreeningReason.COVERAGE_FAILED
    # G0b — too little is visible for any verdict to mean anything.
    if (
        len(evaluable) < thresholds.min_evaluable_dimensions
        or not scores[ScreeningDimension.BUSINESS_QUALITY].evaluable
    ):
        return (
            ScreeningBucket.INSUFFICIENT_DATA,
            ScreeningReason.TOO_FEW_EVALUABLE_DIMENSIONS,
        )

    # G1 — persistent cash burn. One bad year is a band, two in a row is a gate.
    fcf = [
        row.free_cash_flow
        for row in evidence.owner_economics
        if row.free_cash_flow is not None
    ]
    if len(fcf) >= 2 and fcf[-1] <= 0 and fcf[-2] <= 0:
        return ScreeningBucket.LOW_PRIORITY, ScreeningReason.PERSISTENT_CASH_BURN

    # G2 — solvency. Skipped entirely when the balance sheet is not visible.
    latest_capital = evidence.latest_capital_efficiency
    net_cash = latest_capital.net_cash if latest_capital is not None else None
    if net_cash is not None and net_cash < 0:
        latest_fcf = _latest_free_cash_flow(evidence.owner_economics)
        if latest_fcf is None or latest_fcf <= 0:
            return (
                ScreeningBucket.LOW_PRIORITY,
                ScreeningReason.NET_DEBT_WITHOUT_CASH_FLOW,
            )
        if -net_cash / latest_fcf > thresholds.gate_net_debt_to_fcf:
            return (
                ScreeningBucket.LOW_PRIORITY,
                ScreeningReason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW,
            )

    # G3 — returns floor. Skipped when ROIC is not visible.
    roic = [row.roic for row in evidence.capital_efficiency if row.roic is not None]
    if roic and all(value < thresholds.weak_roic for value in roic):
        improving = (
            len(roic) >= 2
            and roic[-1] - roic[0] >= thresholds.material_roic_improvement
        )
        if not improving:
            return (
                ScreeningBucket.LOW_PRIORITY,
                ScreeningReason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL,
            )

    # G4 — dilution outrunning any operating result.
    share_cagr = _share_cagr(evidence.owner_economics)
    if share_cagr is not None and share_cagr >= thresholds.gate_persistent_dilution_cagr:
        return ScreeningBucket.LOW_PRIORITY, ScreeningReason.PERSISTENT_MATERIAL_DILUTION

    return None


def _bucket(
    scores: dict[ScreeningDimension, DimensionScore],
    coverage_class: CoverageClass,
) -> ScreeningBucket:
    """Apply the bucket rule table; the first matching rule wins.

    The rules are stated over named dimensions rather than over the score, so a
    company's bucket can always be explained by pointing at the dimensions that
    satisfied or failed a rule. The score never decides a bucket.
    """
    quality = scores[ScreeningDimension.BUSINESS_QUALITY].band
    efficiency = scores[ScreeningDimension.CAPITAL_EFFICIENCY].band
    compounding = scores[ScreeningDimension.PER_SHARE_COMPOUNDING].band
    balance_sheet = scores[ScreeningDimension.BALANCE_SHEET_STRENGTH].band
    momentum = scores[ScreeningDimension.ECONOMIC_MOMENTUM].band
    evaluable = [score.band for score in scores.values() if score.evaluable]
    strong = sum(1 for band in evaluable if band is DimensionBand.STRONG)
    weak = sum(1 for band in evaluable if band is DimensionBand.WEAK)
    poor = sum(1 for band in evaluable if band is DimensionBand.POOR)
    adequate_or_better = all(band >= DimensionBand.ADEQUATE for band in evaluable)

    # HIGH_PRIORITY — an excellent business, growing owner value, with no weak
    # spot anywhere, seen in full. Every dimension must actually have been
    # measured: a Feature 6 layer can produce output while the dimension it
    # feeds is still unevaluable, and an unmeasured dimension must never pass
    # for an absent weakness. The "four of six strong" requirement keeps a
    # single threshold boundary from deciding the top bucket on its own.
    if (
        coverage_class is CoverageClass.FULL
        and len(evaluable) == len(DIMENSION_ORDER)
        and quality is DimensionBand.STRONG
        and compounding >= DimensionBand.ADEQUATE
        and momentum >= DimensionBand.ADEQUATE
        and adequate_or_better
        and strong >= 4
    ):
        return ScreeningBucket.HIGH_PRIORITY

    # WORTH_UNDERWRITING (a) — strong with one real caveat.
    if (
        quality >= DimensionBand.ADEQUATE
        and efficiency >= DimensionBand.ADEQUATE
        and compounding >= DimensionBand.ADEQUATE
        and balance_sheet >= DimensionBand.ADEQUATE
        and poor == 0
        and weak <= 1
        and strong >= 2
    ):
        return ScreeningBucket.WORTH_UNDERWRITING

    # WORTH_UNDERWRITING (b) — the asymmetric shape: an intact foundation whose
    # recent economics are depressed. Quality, returns, and the balance sheet
    # must all still hold; only compounding or momentum may be weak.
    if (
        quality is DimensionBand.STRONG
        and efficiency is DimensionBand.STRONG
        and balance_sheet >= DimensionBand.ADEQUATE
        and (compounding <= DimensionBand.WEAK or momentum <= DimensionBand.WEAK)
        and compounding is not DimensionBand.NOT_EVALUABLE
        and momentum is not DimensionBand.NOT_EVALUABLE
    ):
        return ScreeningBucket.WORTH_UNDERWRITING

    # WORTH_UNDERWRITING (c) — everything visible is good, but not everything is
    # visible. The coverage ceiling applied afterwards is what keeps this honest.
    if (
        len(evaluable) < len(DIMENSION_ORDER)
        and len(evaluable) >= 3
        and adequate_or_better
        and strong >= 2
    ):
        return ScreeningBucket.WORTH_UNDERWRITING

    # WATCH — intact in parts, not yet worth expensive work.
    if sum(1 for band in evaluable if band >= DimensionBand.ADEQUATE) >= 2 and poor <= 1:
        return ScreeningBucket.WATCH

    return ScreeningBucket.LOW_PRIORITY


def _coverage_ceiling(
    coverage_class: CoverageClass,
    evaluable: int,
    thresholds: ScreeningThresholds,
) -> ScreeningBucket | None:
    """The highest bucket a coverage-limited company may reach.

    A company that was not measured on every dimension is missing evidence in
    both directions, so its unseen dimensions could be strengths or weaknesses.
    Capping it keeps absent negative evidence from outranking a company that was
    measured on everything.

    The cap is keyed on the **evaluable dimension count**, not only on the
    Feature 6 coverage class: a layer can produce output while the dimension it
    feeds remains unevaluable, and that company is just as unmeasured.
    """
    fully_measured = (
        coverage_class is CoverageClass.FULL and evaluable == len(DIMENSION_ORDER)
    )
    if fully_measured or coverage_class is CoverageClass.FAILED:
        return None
    if evaluable >= thresholds.coverage_ceiling_dimensions:
        return ScreeningBucket.WORTH_UNDERWRITING
    return ScreeningBucket.WATCH


def _apply_ceiling(
    bucket: ScreeningBucket, ceiling: ScreeningBucket | None
) -> ScreeningBucket:
    """Lower a bucket to the ceiling. A ceiling never raises a bucket."""
    if ceiling is None:
        return bucket
    return max(bucket, ceiling, key=BUCKET_ORDER.index)


def _setup_type(scores: dict[ScreeningDimension, DimensionScore]) -> SetupType:
    """Classify why a company is interesting, independently of its priority."""
    quality = scores[ScreeningDimension.BUSINESS_QUALITY].band
    efficiency = scores[ScreeningDimension.CAPITAL_EFFICIENCY].band
    compounding = scores[ScreeningDimension.PER_SHARE_COMPOUNDING].band
    balance_sheet = scores[ScreeningDimension.BALANCE_SHEET_STRENGTH].band
    momentum = scores[ScreeningDimension.ECONOMIC_MOMENTUM].band

    # Neither label is granted without seeing returns on capital: a business
    # cannot be called a compounder, or a depressed-quality setup, on cash-flow
    # evidence alone.
    if efficiency is DimensionBand.NOT_EVALUABLE:
        return SetupType.NEITHER
    if (
        quality is DimensionBand.STRONG
        and efficiency >= DimensionBand.ADEQUATE
        and compounding >= DimensionBand.ADEQUATE
        and momentum >= DimensionBand.ADEQUATE
    ):
        return SetupType.COMPOUNDER
    if (
        quality is DimensionBand.STRONG
        and efficiency is DimensionBand.STRONG
        and balance_sheet >= DimensionBand.ADEQUATE
        and (compounding <= DimensionBand.WEAK or momentum <= DimensionBand.WEAK)
        and compounding is not DimensionBand.NOT_EVALUABLE
        and momentum is not DimensionBand.NOT_EVALUABLE
    ):
        return SetupType.POTENTIAL_ASYMMETRIC_SETUP
    return SetupType.NEITHER


def _limiting_factor(
    bucket: ScreeningBucket,
    scores: dict[ScreeningDimension, DimensionScore],
    coverage_class: CoverageClass,
    ceiling_applied: bool,
    gate: ScreeningReason | None,
) -> LimitingFactor:
    """Separate "ranks low because it is weak" from "ranks low because it is unseen"."""
    if bucket is ScreeningBucket.HIGH_PRIORITY:
        return LimitingFactor.NONE
    if bucket is ScreeningBucket.INSUFFICIENT_DATA:
        return LimitingFactor.COVERAGE
    # A survival gate is measured evidence, even when it demoted no band: a
    # gated company must never report that nothing limits it.
    gated_on_evidence = gate is not None
    weak_evidence = gated_on_evidence or any(
        score.band <= DimensionBand.WEAK and score.evaluable for score in scores.values()
    )
    coverage_limited = coverage_class is not CoverageClass.FULL or any(
        not score.evaluable for score in scores.values()
    )
    if weak_evidence and (coverage_limited or ceiling_applied):
        return LimitingFactor.BOTH
    if weak_evidence:
        return LimitingFactor.FUNDAMENTALS
    if coverage_limited:
        return LimitingFactor.COVERAGE
    return LimitingFactor.NONE


def _collect_reasons(
    scores: dict[ScreeningDimension, DimensionScore],
    evidence: ScreeningEvidence,
    ceiling: ScreeningBucket | None,
) -> tuple[
    tuple[ScreeningReason, ...], tuple[ScreeningReason, ...], tuple[ScreeningReason, ...]
]:
    """Gather deduplicated reasons in dimension order, split by category."""
    supporting: list[ScreeningReason] = []
    limiting: list[ScreeningReason] = []
    coverage: list[ScreeningReason] = []
    buckets = {
        ReasonCategory.SUPPORTING: supporting,
        ReasonCategory.LIMITING: limiting,
        ReasonCategory.COVERAGE: coverage,
        ReasonCategory.GATE: [],
    }
    for dimension in DIMENSION_ORDER:
        for reason in scores[dimension].reasons:
            target = buckets[reason_category(reason)]
            if reason not in target:
                target.append(reason)
    incomplete = (
        ceiling is not None
        or evidence.coverage_class is not CoverageClass.FULL
        or any(not score.evaluable for score in scores.values())
    )
    if incomplete and ScreeningReason.COVERAGE_LIMITED not in coverage:
        coverage.insert(0, ScreeningReason.COVERAGE_LIMITED)
    return tuple(supporting), tuple(limiting), tuple(coverage)


def screen_company(
    evidence: ScreeningEvidence,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> ScreeningResult:
    """Score, gate, bucket, and explain one company from assembled evidence.

    The gates decide the bucket when they fire, but never suppress the
    dimensions or the reasons: a gated company still reports everything that was
    measurable, so the reader always sees why it was set aside.
    """
    scores = score_dimensions(evidence, thresholds=thresholds)
    evaluable = [score for score in scores.values() if score.evaluable]
    score_total = sum(score.band.ordinal or 0 for score in evaluable)
    ceiling = _coverage_ceiling(evidence.coverage_class, len(evaluable), thresholds)

    gated = _gate(evidence, scores, thresholds)
    ceiling_applied = False
    if gated is not None:
        bucket, gate_reason = gated
    else:
        gate_reason = None
        unbounded = _bucket(scores, evidence.coverage_class)
        bucket = _apply_ceiling(unbounded, ceiling)
        ceiling_applied = bucket is not unbounded

    supporting, limiting, coverage = _collect_reasons(scores, evidence, ceiling)
    setup = (
        SetupType.NEITHER
        if bucket is ScreeningBucket.INSUFFICIENT_DATA
        else _setup_type(scores)
    )
    return ScreeningResult(
        ticker=evidence.ticker,
        latest_fiscal_year=evidence.latest_fiscal_year,
        coverage_class=evidence.coverage_class,
        bucket=bucket,
        setup_type=setup,
        limiting_factor=_limiting_factor(
            bucket, scores, evidence.coverage_class, ceiling_applied, gate_reason
        ),
        dimensions=scores,
        screening_score=score_total,
        evaluable_dimensions=len(evaluable),
        coverage_ceiling=ceiling,
        gate=gate_reason,
        supporting_reasons=supporting,
        limiting_reasons=limiting,
        coverage_reasons=coverage,
        unavailable_dimensions=tuple(
            dimension
            for dimension in DIMENSION_ORDER
            if not scores[dimension].evaluable
        ),
        unavailable_metrics=evidence.unavailable_metrics,
    )


def screen_company_from_history(
    history: CanonicalFinancialHistory,
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> ScreeningResult:
    """Assemble evidence from a canonical history, then screen the company."""
    return screen_company(assemble_screening_evidence(history), thresholds=thresholds)


def screen_company_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> ScreeningResult:
    """Compatibility wrapper: map raw SEC Company Facts, then screen the company."""
    return screen_company_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years),
        thresholds=thresholds,
    )


# --- Rendering -----------------------------------------------------------------

_BAND_LABEL: dict[DimensionBand, str] = {
    DimensionBand.STRONG: "Strong",
    DimensionBand.ADEQUATE: "Adequate",
    DimensionBand.WEAK: "Weak",
    DimensionBand.POOR: "Poor",
    DimensionBand.NOT_EVALUABLE: "Not evaluable",
}

_DIMENSION_LABEL: dict[ScreeningDimension, str] = {
    ScreeningDimension.BUSINESS_QUALITY: "Business quality",
    ScreeningDimension.CAPITAL_EFFICIENCY: "Capital efficiency",
    ScreeningDimension.PER_SHARE_COMPOUNDING: "Per-share compounding",
    ScreeningDimension.BALANCE_SHEET_STRENGTH: "Balance sheet",
    ScreeningDimension.CAPITAL_ALLOCATION: "Capital allocation",
    ScreeningDimension.ECONOMIC_MOMENTUM: "Economic momentum",
}


def format_screening_result(result: ScreeningResult) -> str:
    """Render the owner-readable screening verdict with its reasons and evidence."""
    year = f"FY{result.latest_fiscal_year}" if result.latest_fiscal_year else "n/a"
    lines = [
        f"{result.ticker} — Opportunity Screening ({year})",
        "",
    ]
    for dimension in DIMENSION_ORDER:
        score = result.dimensions[dimension]
        lines.append(
            f"  {_DIMENSION_LABEL[dimension] + ':':<23}{_BAND_LABEL[score.band]}"
        )
    lines.extend(
        [
            "",
            f"Priority:   {result.bucket.value}",
            f"Setup:      {result.setup_type.value}",
            (
                f"Coverage:   {result.coverage_class.value} "
                f"({result.evaluable_dimensions} of {len(DIMENSION_ORDER)}"
                " dimensions evaluable)"
            ),
        ]
    )
    if result.limiting_factor is not LimitingFactor.NONE:
        lines.append(f"Limited by: {result.limiting_factor.value}")
    if result.gate is not None:
        lines.append(f"Gate:       {result.gate.value}")

    if result.supporting_reasons:
        lines.extend(["", "Why it ranks where it does:"])
        lines.extend(f"  + {reason.value}" for reason in result.supporting_reasons)
    if result.limiting_reasons:
        lines.extend(["", "What holds it back:"])
        lines.extend(f"  - {reason.value}" for reason in result.limiting_reasons)
    if result.coverage_reasons or result.unavailable_dimensions or result.unavailable_metrics:
        lines.extend(["", "What we cannot see:"])
        lines.extend(f"  ? {reason.value}" for reason in result.coverage_reasons)
        if result.unavailable_dimensions:
            missing = ", ".join(
                _DIMENSION_LABEL[d].lower() for d in result.unavailable_dimensions
            )
            lines.append(f"  ? unavailable dimensions: {missing}")
        if result.unavailable_metrics:
            lines.append(
                f"  ? blocking canonical metrics: {', '.join(result.unavailable_metrics)}"
            )

    lines.extend(["", "Evidence:"])
    for dimension in DIMENSION_ORDER:
        score = result.dimensions[dimension]
        if score.evidence:
            lines.append(f"  {_DIMENSION_LABEL[dimension]}:")
            lines.extend(f"    {item}" for item in score.evidence)
    lines.extend(
        [
            "",
            (
                f"Screening score: {result.screening_score}"
                " (orders companies within a bucket; never sets the bucket)"
            ),
        ]
    )
    return "\n".join(lines)


# --- Universe screening --------------------------------------------------------


@dataclass(frozen=True)
class UniverseScreening:
    """Every company's screening result, ranked, with its bucket distribution."""

    results: tuple[ScreeningResult, ...]

    @property
    def ranked(self) -> tuple[ScreeningResult, ...]:
        """Results in the documented ranking order."""
        return tuple(sorted(self.results, key=lambda result: result.rank_key))

    def in_bucket(self, bucket: ScreeningBucket) -> tuple[ScreeningResult, ...]:
        return tuple(result for result in self.ranked if result.bucket is bucket)

    def distribution(self) -> dict[ScreeningBucket, int]:
        """Company count per bucket, in bucket order, including empty buckets."""
        return {
            bucket: sum(1 for result in self.results if result.bucket is bucket)
            for bucket in BUCKET_ORDER
        }

    def worth_underwriting(self) -> tuple[ScreeningResult, ...]:
        """The companies a human should look at next, highest priority first."""
        return tuple(
            result
            for result in self.ranked
            if result.bucket
            in (ScreeningBucket.HIGH_PRIORITY, ScreeningBucket.WORTH_UNDERWRITING)
        )


def screen_universe(
    histories: Sequence[CanonicalFinancialHistory],
    *,
    thresholds: ScreeningThresholds = DEFAULT_SCREENING_THRESHOLDS,
) -> UniverseScreening:
    """Screen every supplied company and rank them.

    Each company costs one evidence assembly, so the cost is linear in the
    universe size with no cross-company work and no network access.
    """
    return UniverseScreening(
        tuple(
            screen_company_from_history(history, thresholds=thresholds)
            for history in histories
        )
    )


_BUCKET_ABBREVIATION: dict[ScreeningBucket, str] = {
    ScreeningBucket.HIGH_PRIORITY: "HIGH",
    ScreeningBucket.WORTH_UNDERWRITING: "WORTH",
    ScreeningBucket.WATCH: "WATCH",
    ScreeningBucket.LOW_PRIORITY: "LOW",
    ScreeningBucket.INSUFFICIENT_DATA: "NO DATA",
}

_BAND_ABBREVIATION: dict[DimensionBand, str] = {
    DimensionBand.STRONG: "STR",
    DimensionBand.ADEQUATE: "ADQ",
    DimensionBand.WEAK: "WEK",
    DimensionBand.POOR: "POR",
    DimensionBand.NOT_EVALUABLE: "---",
}

_SETUP_ABBREVIATION: dict[SetupType, str] = {
    SetupType.COMPOUNDER: "compounder",
    SetupType.POTENTIAL_ASYMMETRIC_SETUP: "asymmetric",
    SetupType.NEITHER: "",
}


def format_screening_table(screening: UniverseScreening) -> str:
    """Render the ranked universe as a deterministic one-line-per-company grid."""
    header = (
        f"{'Company':<8}{'Priority':<9}{'Setup':<12}{'Coverage':<10}"
        + "".join(f"{dimension.value[:4]:<5}" for dimension in DIMENSION_ORDER)
        + f"{'Score':>6}  Limited by"
    )
    lines = [header, "-" * len(header)]
    for result in screening.ranked:
        bands = "".join(
            f"{_BAND_ABBREVIATION[result.band(dimension)]:<5}"
            for dimension in DIMENSION_ORDER
        )
        limited = (
            "" if result.limiting_factor is LimitingFactor.NONE
            else result.limiting_factor.value.lower()
        )
        lines.append(
            f"{result.ticker:<8}{_BUCKET_ABBREVIATION[result.bucket]:<9}"
            f"{_SETUP_ABBREVIATION[result.setup_type]:<12}"
            f"{result.coverage_class.value:<10}{bands}"
            f"{result.screening_score:>6}  {limited}"
        )

    lines.append("")
    lines.append("Distribution:")
    for bucket, count in screening.distribution().items():
        tickers = ", ".join(r.ticker for r in screening.in_bucket(bucket))
        lines.append(f"  {bucket.value + ':':<21}{count:>3}  {tickers}")
    lines.append("")
    lines.append(
        "Priority is research order, not investment advice. The score orders "
        "companies within a bucket and never sets one."
    )
    return "\n".join(lines)


def format_screening_detail(screening: UniverseScreening) -> str:
    """Render the full per-company justification for every company, in rank order."""
    return "\n\n".join(
        format_screening_result(result) for result in screening.ranked
    )

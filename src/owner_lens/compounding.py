"""Deterministic multi-year economic-compounding interpretation for OwnerLens.

This module supports OwnerLens Slice 2B. It is the multi-year interpretation
layer: it consumes the Feature 1 owner-economics and capital-efficiency metrics
and the Feature 2A annual economic-value snapshots, and for a requested period it
produces an ``EconomicCompoundingView`` reporting the compounding rates (revenue,
aggregate free cash flow, free cash flow per share, and diluted shares), the
start-to-end quality and balance-sheet changes (operating margin, FCF margin,
ROIC, net cash or net debt), and the counts of the annual classifications in the
period. It then classifies the period as STRONGLY_COMPOUNDING, COMPOUNDING,
STABLE, DETERIORATING, or INSUFFICIENT_DATA using explicit documented rules that
treat FCF-per-share CAGR as the primary per-share compounding measure and surface
share-count-driven results, material dilution, and ROIC deterioration.

The layer performs no SEC retrieval or re-normalization and duplicates no
Feature 1 calculation. CAGR uses the fiscal-year interval count (observations
minus one) as the exponent denominator and fails explicitly on invalid inputs.
Thresholds are centralized and named; there are no configurable weights, no
numeric composite score, and the multi-year verdict is never an average of the
annual verdicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from owner_lens._trajectory import net_cash_trajectory
from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.capital_efficiency import (
    CapitalEfficiencyRow,
    capital_efficiency_from_history,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    EconomicValueSnapshot,
    build_economic_value_snapshots,
)
from owner_lens.owner_economics import OwnerEconomicsRow, owner_economics_from_history
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "DEFAULT_COMPOUNDING_THRESHOLDS",
    "CompoundingClassification",
    "CompoundingDriver",
    "CompoundingThresholds",
    "EconomicCompoundingView",
    "build_compounding_view",
    "cagr",
    "classify_compounding",
    "compounding_view_from_facts",
    "compounding_view_from_history",
    "compounding_views_from_facts",
    "compounding_views_from_history",
    "format_compounding_view",
]


class CompoundingClassification(Enum):
    """Deterministic multi-year verdict on owner-oriented compounding."""

    STRONGLY_COMPOUNDING = "STRONGLY_COMPOUNDING"
    COMPOUNDING = "COMPOUNDING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CompoundingDriver(Enum):
    """Named reason code explaining part of a compounding classification."""

    STRONG_FCF_PER_SHARE_COMPOUNDING = "STRONG_FCF_PER_SHARE_COMPOUNDING"
    MODERATE_FCF_PER_SHARE_COMPOUNDING = "MODERATE_FCF_PER_SHARE_COMPOUNDING"
    WEAK_FCF_PER_SHARE_COMPOUNDING = "WEAK_FCF_PER_SHARE_COMPOUNDING"
    FCF_PER_SHARE_DECLINED = "FCF_PER_SHARE_DECLINED"
    AGGREGATE_FCF_GREW = "AGGREGATE_FCF_GREW"
    AGGREGATE_FCF_DECLINED = "AGGREGATE_FCF_DECLINED"
    ROIC_HIGH_AND_SUSTAINED = "ROIC_HIGH_AND_SUSTAINED"
    ROIC_IMPROVED = "ROIC_IMPROVED"
    ROIC_DETERIORATED = "ROIC_DETERIORATED"
    OPERATING_MARGIN_EXPANDED = "OPERATING_MARGIN_EXPANDED"
    OPERATING_MARGIN_CONTRACTED = "OPERATING_MARGIN_CONTRACTED"
    FCF_MARGIN_EXPANDED = "FCF_MARGIN_EXPANDED"
    FCF_MARGIN_CONTRACTED = "FCF_MARGIN_CONTRACTED"
    SHARE_COUNT_SHRANK = "SHARE_COUNT_SHRANK"
    MATERIAL_DILUTION = "MATERIAL_DILUTION"
    BALANCE_SHEET_IMPROVED = "BALANCE_SHEET_IMPROVED"
    BALANCE_SHEET_DETERIORATED = "BALANCE_SHEET_DETERIORATED"
    CONSISTENT_ANNUAL_IMPROVEMENT = "CONSISTENT_ANNUAL_IMPROVEMENT"
    MIXED_ANNUAL_ECONOMICS = "MIXED_ANNUAL_ECONOMICS"
    INSUFFICIENT_MULTI_YEAR_HISTORY = "INSUFFICIENT_MULTI_YEAR_HISTORY"


@dataclass(frozen=True)
class CompoundingThresholds:
    """Centralized, named materiality boundaries. Not configurable weights.

    These are inspectable cutoffs a reader can change in one place; the
    classification is a documented rule, never a weighted sum. CAGR thresholds
    are fractions (0.15 == 15%); margin and ROIC change thresholds are absolute
    differences in the ratio (0.02 == 2 percentage points).
    """

    strong_fcf_per_share_cagr: float = 0.15
    healthy_fcf_per_share_cagr: float = 0.07
    flat_cagr_band: float = 0.02
    material_fcf_cagr: float = 0.05
    material_margin_change: float = 0.02
    material_roic_change: float = 0.03
    material_share_cagr: float = 0.01
    high_roic_level: float = 0.20


DEFAULT_COMPOUNDING_THRESHOLDS = CompoundingThresholds()


@dataclass(frozen=True)
class EconomicCompoundingView:
    """One multi-year period of compounding rates, changes, counts, and verdict."""

    start_fiscal_year: int
    end_fiscal_year: int
    years: int
    # Compounding rates (period CAGR); None when the CAGR is invalid.
    revenue_cagr: float | None
    fcf_cagr: float | None
    fcf_per_share_cagr: float | None
    diluted_share_cagr: float | None
    # Start-to-end quality changes.
    operating_margin_start: float | None
    operating_margin_end: float | None
    operating_margin_change: float | None
    fcf_margin_start: float | None
    fcf_margin_end: float | None
    fcf_margin_change: float | None
    roic_start: float | None
    roic_end: float | None
    roic_change: float | None
    # Balance-sheet trajectory.
    net_cash_or_debt_start: int | None
    net_cash_or_debt_end: int | None
    net_cash_or_debt_change: int | None
    # Annual consistency context.
    improving_count: int
    stable_count: int
    deteriorating_count: int
    insufficient_count: int
    # Interpretation.
    classification: CompoundingClassification
    drivers: tuple[CompoundingDriver, ...]


def cagr(begin: float | None, end: float | None, years: int) -> float | None:
    """Standard CAGR over ``years`` fiscal-year intervals, or None if invalid.

    ``years`` is the interval count (observations minus one), never the
    observation count. Returns None for a missing endpoint, a non-positive
    interval count, a non-positive beginning, or a non-positive ending (a sign
    change that makes the ratio undefined or economically meaningless).
    """
    if begin is None or end is None or years <= 0 or begin <= 0 or end <= 0:
        return None
    return (end / begin) ** (1 / years) - 1


def _obs_value(observation: Any) -> float | None:
    return float(observation.value) if observation is not None else None


def _row(row: Any, name: str) -> Any:
    return getattr(row, name) if row is not None else None


def _delta(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return end - start


def _int_delta(start: int | None, end: int | None) -> int | None:
    if start is None or end is None:
        return None
    return end - start


def _direction(value: float | None, threshold: float) -> int | None:
    if value is None:
        return None
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _net_cash_direction(
    start: int | None, end: int | None, thresholds: CompoundingThresholds
) -> int | None:
    """+1 improved, -1 deteriorated, 0 immaterial, None when an endpoint is absent."""
    trajectory = net_cash_trajectory(start, end, material=thresholds.material_fcf_cagr)
    return trajectory.direction if trajectory is not None else None


def count_annual_classifications(
    snapshots: Sequence[EconomicValueSnapshot], start_fiscal_year: int, end_fiscal_year: int
) -> tuple[int, int, int, int]:
    """Tally in-period annual classifications as (improving, stable, deteriorating, insufficient)."""
    improving = stable = deteriorating = insufficient = 0
    for snap in snapshots:
        if not start_fiscal_year <= snap.fiscal_year <= end_fiscal_year:
            continue
        match snap.classification:
            case EconomicValueClassification.IMPROVING:
                improving += 1
            case EconomicValueClassification.STABLE:
                stable += 1
            case EconomicValueClassification.DETERIORATING:
                deteriorating += 1
            case EconomicValueClassification.INSUFFICIENT_DATA:
                insufficient += 1
    return improving, stable, deteriorating, insufficient


def _common_fiscal_years(
    owner: dict[int, OwnerEconomicsRow], capital: dict[int, CapitalEfficiencyRow]
) -> list[int]:
    return sorted(set(owner) & set(capital))


# Ordered from strongest to weakest, so a downgrade increases the index.
_ORDER: tuple[CompoundingClassification, ...] = (
    CompoundingClassification.STRONGLY_COMPOUNDING,
    CompoundingClassification.COMPOUNDING,
    CompoundingClassification.STABLE,
    CompoundingClassification.DETERIORATING,
)
_STABLE_INDEX = _ORDER.index(CompoundingClassification.STABLE)


def _emit_drivers(
    *,
    pps_band: int,
    fcf_dir: int | None,
    roic_dir: int | None,
    roic_high: bool,
    opm_dir: int | None,
    fcfm_dir: int | None,
    share_dir: int | None,
    net_cash_dir: int | None,
    consistency: CompoundingDriver | None,
) -> list[CompoundingDriver]:
    """Build drivers in the fixed priority order used for every classification."""
    drivers: list[CompoundingDriver] = []
    match pps_band:
        case 3:
            drivers.append(CompoundingDriver.STRONG_FCF_PER_SHARE_COMPOUNDING)
        case 2:
            drivers.append(CompoundingDriver.MODERATE_FCF_PER_SHARE_COMPOUNDING)
        case 1:
            drivers.append(CompoundingDriver.WEAK_FCF_PER_SHARE_COMPOUNDING)
        case -1:
            drivers.append(CompoundingDriver.FCF_PER_SHARE_DECLINED)
    if fcf_dir == 1:
        drivers.append(CompoundingDriver.AGGREGATE_FCF_GREW)
    elif fcf_dir == -1:
        drivers.append(CompoundingDriver.AGGREGATE_FCF_DECLINED)
    if roic_high:
        drivers.append(CompoundingDriver.ROIC_HIGH_AND_SUSTAINED)
    if roic_dir == 1:
        drivers.append(CompoundingDriver.ROIC_IMPROVED)
    elif roic_dir == -1:
        drivers.append(CompoundingDriver.ROIC_DETERIORATED)
    if opm_dir == 1:
        drivers.append(CompoundingDriver.OPERATING_MARGIN_EXPANDED)
    elif opm_dir == -1:
        drivers.append(CompoundingDriver.OPERATING_MARGIN_CONTRACTED)
    if fcfm_dir == 1:
        drivers.append(CompoundingDriver.FCF_MARGIN_EXPANDED)
    elif fcfm_dir == -1:
        drivers.append(CompoundingDriver.FCF_MARGIN_CONTRACTED)
    if share_dir == 1:
        drivers.append(CompoundingDriver.SHARE_COUNT_SHRANK)
    elif share_dir == -1:
        drivers.append(CompoundingDriver.MATERIAL_DILUTION)
    if net_cash_dir == 1:
        drivers.append(CompoundingDriver.BALANCE_SHEET_IMPROVED)
    elif net_cash_dir == -1:
        drivers.append(CompoundingDriver.BALANCE_SHEET_DETERIORATED)
    if consistency is not None:
        drivers.append(consistency)
    return drivers


def _per_share_band(pps: float, thresholds: CompoundingThresholds) -> int:
    """3 strong, 2 healthy, 1 weak-positive, 0 flat, -1 declined."""
    if pps >= thresholds.strong_fcf_per_share_cagr:
        return 3
    if pps >= thresholds.healthy_fcf_per_share_cagr:
        return 2
    if pps <= -thresholds.flat_cagr_band:
        return -1
    if abs(pps) < thresholds.flat_cagr_band:
        return 0
    return 1


def classify_compounding(
    view: EconomicCompoundingView,
    *,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> tuple[CompoundingClassification, tuple[CompoundingDriver, ...]]:
    """Apply the documented deterministic rule to a period's compounding signals."""
    pps = view.fcf_per_share_cagr
    if pps is None:
        return (
            CompoundingClassification.INSUFFICIENT_DATA,
            (CompoundingDriver.INSUFFICIENT_MULTI_YEAR_HISTORY,),
        )

    band = _per_share_band(pps, thresholds)
    fcf_dir = _direction(view.fcf_cagr, thresholds.material_fcf_cagr)
    share_dir = _share_direction(view.diluted_share_cagr, thresholds.material_share_cagr)
    roic_dir = _direction(view.roic_change, thresholds.material_roic_change)
    roic_high = view.roic_end is not None and view.roic_end >= thresholds.high_roic_level
    opm_dir = _direction(view.operating_margin_change, thresholds.material_margin_change)
    fcfm_dir = _direction(view.fcf_margin_change, thresholds.material_margin_change)
    net_cash_dir = _net_cash_direction(
        view.net_cash_or_debt_start, view.net_cash_or_debt_end, thresholds
    )
    consistency = _consistency_driver(view)

    drivers = _emit_drivers(
        pps_band=band,
        fcf_dir=fcf_dir,
        roic_dir=roic_dir,
        roic_high=roic_high,
        opm_dir=opm_dir,
        fcfm_dir=fcfm_dir,
        share_dir=share_dir,
        net_cash_dir=net_cash_dir,
        consistency=consistency,
    )

    # Base verdict from the primary per-share compounding band.
    if band == 3:
        base_index = _ORDER.index(CompoundingClassification.STRONGLY_COMPOUNDING)
    elif band in (2, 1):
        base_index = _ORDER.index(CompoundingClassification.COMPOUNDING)
    elif band == 0:
        base_index = _STABLE_INDEX
    else:
        base_index = _ORDER.index(CompoundingClassification.DETERIORATING)

    illusion = (
        view.fcf_cagr is not None
        and view.fcf_cagr <= -thresholds.material_fcf_cagr
        and share_dir == 1
    )
    dilution = share_dir == -1
    roic_bad = roic_dir == -1

    if base_index <= _ORDER.index(CompoundingClassification.COMPOUNDING):
        downgrades = sum((illusion, dilution, roic_bad))
        # Tempering alone never pushes a compounding base below STABLE.
        index = min(base_index + downgrades, _STABLE_INDEX)
        classification = _ORDER[index]
    elif base_index == _ORDER.index(CompoundingClassification.DETERIORATING):
        classification = _temper_deteriorating(
            pps=pps,
            thresholds=thresholds,
            roic_dir=roic_dir,
            opm_dir=opm_dir,
            fcfm_dir=fcfm_dir,
        )
    else:
        classification = _resolve_stable(
            view=view,
            roic_dir=roic_dir,
            opm_dir=opm_dir,
            fcfm_dir=fcfm_dir,
            share_dir=share_dir,
            net_cash_dir=net_cash_dir,
            tempering=illusion or dilution or roic_bad,
        )

    return classification, tuple(drivers)


def _share_direction(share_cagr: float | None, threshold: float) -> int | None:
    """A share-count decline is positive for owners; dilution is negative."""
    if share_cagr is None:
        return None
    if share_cagr <= -threshold:
        return 1
    if share_cagr >= threshold:
        return -1
    return 0


def _temper_deteriorating(
    *,
    pps: float,
    thresholds: CompoundingThresholds,
    roic_dir: int | None,
    opm_dir: int | None,
    fcfm_dir: int | None,
) -> CompoundingClassification:
    marginal = abs(pps) < 2 * thresholds.flat_cagr_band
    if marginal and roic_dir == 1 and opm_dir == 1 and fcfm_dir == 1:
        return CompoundingClassification.STABLE
    return CompoundingClassification.DETERIORATING


def _resolve_stable(
    *,
    view: EconomicCompoundingView,
    roic_dir: int | None,
    opm_dir: int | None,
    fcfm_dir: int | None,
    share_dir: int | None,
    net_cash_dir: int | None,
    tempering: bool,
) -> CompoundingClassification:
    votes = [d for d in (roic_dir, opm_dir, fcfm_dir, share_dir, net_cash_dir) if d is not None]
    positive = sum(1 for d in votes if d == 1)
    negative = sum(1 for d in votes if d == -1)
    annual_negative = view.deteriorating_count > view.improving_count
    if positive >= 2 and positive > negative and not tempering:
        return CompoundingClassification.COMPOUNDING
    if (negative >= 2 or annual_negative) and negative >= positive:
        return CompoundingClassification.DETERIORATING
    return CompoundingClassification.STABLE


def _consistency_driver(view: EconomicCompoundingView) -> CompoundingDriver | None:
    total = (
        view.improving_count
        + view.stable_count
        + view.deteriorating_count
        + view.insufficient_count
    )
    if total == 0:
        return None
    if view.deteriorating_count == 0 and view.stable_count == 0 and view.improving_count > 0:
        return CompoundingDriver.CONSISTENT_ANNUAL_IMPROVEMENT
    return CompoundingDriver.MIXED_ANNUAL_ECONOMICS


def build_compounding_view(
    owner_economics: Sequence[OwnerEconomicsRow],
    capital_efficiency: Sequence[CapitalEfficiencyRow],
    snapshots: Sequence[EconomicValueSnapshot],
    *,
    period_years: int,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> EconomicCompoundingView:
    """Select a period deterministically and build a classified compounding view.

    ``period_years`` is the number of fiscal-year intervals (years of
    compounding), so a 3-year CAGR spans ``FY(end - 3)`` through ``FY(end)`` and
    requires four observations. The CAGR exponent denominator equals
    ``period_years``.
    """
    owner = {row.fiscal_year: row for row in owner_economics}
    capital = {row.fiscal_year: row for row in capital_efficiency}
    common = _common_fiscal_years(owner, capital)

    end_fy = common[-1] if common else 0
    start_fy = end_fy - period_years
    years = end_fy - start_fy
    counts = count_annual_classifications(snapshots, start_fy, end_fy)

    if not common or start_fy not in owner or start_fy not in capital or years < 1:
        return _insufficient_view(start_fy, end_fy, max(years, 0), counts)

    o_start, o_end = owner[start_fy], owner[end_fy]
    c_start, c_end = capital[start_fy], capital[end_fy]

    view = EconomicCompoundingView(
        start_fiscal_year=start_fy,
        end_fiscal_year=end_fy,
        years=years,
        revenue_cagr=cagr(_obs_value(o_start.revenue), _obs_value(o_end.revenue), years),
        fcf_cagr=cagr(_as_float(o_start.free_cash_flow), _as_float(o_end.free_cash_flow), years),
        fcf_per_share_cagr=cagr(o_start.fcf_per_share, o_end.fcf_per_share, years),
        diluted_share_cagr=cagr(
            _obs_value(o_start.diluted_shares), _obs_value(o_end.diluted_shares), years
        ),
        operating_margin_start=o_start.operating_margin,
        operating_margin_end=o_end.operating_margin,
        operating_margin_change=_delta(o_start.operating_margin, o_end.operating_margin),
        fcf_margin_start=o_start.fcf_margin,
        fcf_margin_end=o_end.fcf_margin,
        fcf_margin_change=_delta(o_start.fcf_margin, o_end.fcf_margin),
        roic_start=c_start.roic,
        roic_end=c_end.roic,
        roic_change=_delta(c_start.roic, c_end.roic),
        net_cash_or_debt_start=c_start.net_cash,
        net_cash_or_debt_end=c_end.net_cash,
        net_cash_or_debt_change=_int_delta(c_start.net_cash, c_end.net_cash),
        improving_count=counts[0],
        stable_count=counts[1],
        deteriorating_count=counts[2],
        insufficient_count=counts[3],
        classification=CompoundingClassification.INSUFFICIENT_DATA,
        drivers=(),
    )
    classification, drivers = classify_compounding(view, thresholds=thresholds)
    return replace(view, classification=classification, drivers=drivers)


def _as_float(value: int | None) -> float | None:
    return float(value) if value is not None else None


def _insufficient_view(
    start_fy: int, end_fy: int, years: int, counts: tuple[int, int, int, int]
) -> EconomicCompoundingView:
    return EconomicCompoundingView(
        start_fiscal_year=start_fy,
        end_fiscal_year=end_fy,
        years=years,
        revenue_cagr=None,
        fcf_cagr=None,
        fcf_per_share_cagr=None,
        diluted_share_cagr=None,
        operating_margin_start=None,
        operating_margin_end=None,
        operating_margin_change=None,
        fcf_margin_start=None,
        fcf_margin_end=None,
        fcf_margin_change=None,
        roic_start=None,
        roic_end=None,
        roic_change=None,
        net_cash_or_debt_start=None,
        net_cash_or_debt_end=None,
        net_cash_or_debt_change=None,
        improving_count=counts[0],
        stable_count=counts[1],
        deteriorating_count=counts[2],
        insufficient_count=counts[3],
        classification=CompoundingClassification.INSUFFICIENT_DATA,
        drivers=(CompoundingDriver.INSUFFICIENT_MULTI_YEAR_HISTORY,),
    )


def _feature_inputs(
    history: CanonicalFinancialHistory,
) -> tuple[
    tuple[OwnerEconomicsRow, ...],
    tuple[CapitalEfficiencyRow, ...],
    tuple[EconomicValueSnapshot, ...],
]:
    owner = owner_economics_from_history(history)
    capital = capital_efficiency_from_history(history)
    return owner, capital, build_economic_value_snapshots(owner, capital)


def compounding_view_from_history(
    history: CanonicalFinancialHistory,
    *,
    period_years: int,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> EconomicCompoundingView:
    """Derive Feature 1 and Feature 2A outputs from a canonical history, then build a view.

    ``period_years`` is the number of fiscal-year intervals (years of
    compounding).
    """
    owner, capital, snapshots = _feature_inputs(history)
    return build_compounding_view(
        owner, capital, snapshots, period_years=period_years, thresholds=thresholds
    )


def compounding_views_from_history(
    history: CanonicalFinancialHistory,
    *,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> tuple[EconomicCompoundingView, EconomicCompoundingView]:
    """Return the recent 3-year CAGR view and the longest available view.

    ``period_years`` counts fiscal-year intervals, so the recent view is a true
    3-year CAGR (FY(end - 3) through FY(end)). The long view uses the longest
    span the history supports, capped at a 5-year CAGR; with five observations
    that is a 4-year CAGR, and it becomes a 5-year CAGR once a sixth year exists.
    """
    owner, capital, snapshots = _feature_inputs(history)
    owner_by = {row.fiscal_year: row for row in owner}
    capital_by = {row.fiscal_year: row for row in capital}
    available_intervals = max(len(_common_fiscal_years(owner_by, capital_by)) - 1, 0)
    recent = build_compounding_view(
        owner, capital, snapshots, period_years=3, thresholds=thresholds
    )
    long_term = build_compounding_view(
        owner,
        capital,
        snapshots,
        period_years=min(5, available_intervals),
        thresholds=thresholds,
    )
    return recent, long_term


def compounding_view_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    period_years: int,
    max_years: int = 5,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> EconomicCompoundingView:
    """Compatibility wrapper: map raw SEC Company Facts, then build a view."""
    return compounding_view_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years),
        period_years=period_years,
        thresholds=thresholds,
    )


def compounding_views_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> tuple[EconomicCompoundingView, EconomicCompoundingView]:
    """Compatibility wrapper: map raw SEC Company Facts, then build both views."""
    return compounding_views_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years),
        thresholds=thresholds,
    )


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/a"


def _fmt_ratio(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _fmt_cash(value: int | None) -> str:
    return f"{value:+,}" if value is not None else "n/a"


def format_compounding_view(view: EconomicCompoundingView) -> str:
    """Render the compact multi-year compounding view with its drivers."""
    lines = [
        (
            f"ADBE Economic Compounding — FY{view.start_fiscal_year} "
            f"→ FY{view.end_fiscal_year}  ({view.years}-year CAGR)"
        ),
        "",
        f"  Revenue CAGR:       {_fmt_pct(view.revenue_cagr)}",
        f"  FCF CAGR:           {_fmt_pct(view.fcf_cagr)}",
        f"  FCF/share CAGR:     {_fmt_pct(view.fcf_per_share_cagr)}",
        f"  Diluted-share CAGR: {_fmt_pct(view.diluted_share_cagr)}",
        "",
        (
            f"  Operating margin:   {_fmt_ratio(view.operating_margin_start)} "
            f"→ {_fmt_ratio(view.operating_margin_end)}"
        ),
        (
            f"  FCF margin:         {_fmt_ratio(view.fcf_margin_start)} "
            f"→ {_fmt_ratio(view.fcf_margin_end)}"
        ),
        (
            f"  ROIC:               {_fmt_ratio(view.roic_start)} "
            f"→ {_fmt_ratio(view.roic_end)}"
        ),
        (
            f"  Net cash/debt:      {_fmt_cash(view.net_cash_or_debt_start)} "
            f"→ {_fmt_cash(view.net_cash_or_debt_end)}"
        ),
        "",
        (
            f"  Annual snapshots:   IMPROVING {view.improving_count}  "
            f"STABLE {view.stable_count}  DETERIORATING {view.deteriorating_count}  "
            f"INSUFFICIENT {view.insufficient_count}"
        ),
        "",
        f"  Classification:     {view.classification.value}",
        "  Drivers:",
    ]
    for driver in view.drivers:
        lines.append(f"    - {driver.value}")
    return "\n".join(lines)

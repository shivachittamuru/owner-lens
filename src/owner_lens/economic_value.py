"""Deterministic annual economic-value interpretation for OwnerLens.

This module supports OwnerLens Slice 2A. It is the first interpretation layer:
it consumes the Feature 1 owner-economics and capital-efficiency outputs and
produces, per completed fiscal year, an ``EconomicValueSnapshot`` that separates
LEVEL signals (operating margin, FCF margin, ROIC, net cash or net debt) from
CHANGE signals (revenue growth, margin changes, FCF growth, FCF-per-share
growth, share-count growth, ROIC change), then classifies the year as
IMPROVING, STABLE, DETERIORATING, or INSUFFICIENT_DATA using explicit documented
rules that weight per-share economics above aggregate growth. Every
classification carries ordered, named drivers so the verdict is transparent.

The layer performs no SEC retrieval or re-normalization: it reads already-derived
Feature 1 rows and computes only the few adjacent-year changes those rows do not
already expose. Thresholds are centralized and named; there are no configurable
weights and no numeric composite score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from owner_lens._trajectory import NetCashTrajectory, net_cash_trajectory
from owner_lens.capital_efficiency import (
    CapitalEfficiencyRow,
    capital_efficiency_from_facts,
)
from owner_lens.owner_economics import OwnerEconomicsRow, owner_economics_from_facts

__all__ = [
    "DEFAULT_THRESHOLDS",
    "EconomicValueClassification",
    "EconomicValueDriver",
    "EconomicValueSnapshot",
    "EconomicValueThresholds",
    "build_economic_value_snapshots",
    "classify_economic_value",
    "economic_value_from_facts",
    "format_economic_value_view",
]


class EconomicValueClassification(Enum):
    """Deterministic annual verdict on owner-oriented economics."""

    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class EconomicValueDriver(Enum):
    """Named reason code explaining part of a classification."""

    FCF_PER_SHARE_STRONG_GROWTH = "FCF_PER_SHARE_STRONG_GROWTH"
    FCF_PER_SHARE_DECLINE = "FCF_PER_SHARE_DECLINE"
    ROIC_EXPANDED = "ROIC_EXPANDED"
    ROIC_CONTRACTED = "ROIC_CONTRACTED"
    ROIC_SUSTAINED_HIGH = "ROIC_SUSTAINED_HIGH"
    OPERATING_MARGIN_EXPANDED = "OPERATING_MARGIN_EXPANDED"
    OPERATING_MARGIN_CONTRACTED = "OPERATING_MARGIN_CONTRACTED"
    FCF_MARGIN_EXPANDED = "FCF_MARGIN_EXPANDED"
    FCF_MARGIN_CONTRACTED = "FCF_MARGIN_CONTRACTED"
    SHARE_COUNT_DECLINED = "SHARE_COUNT_DECLINED"
    SHARE_COUNT_INCREASED = "SHARE_COUNT_INCREASED"
    NET_CASH_IMPROVED = "NET_CASH_IMPROVED"
    NET_CASH_DETERIORATED = "NET_CASH_DETERIORATED"
    TURNED_TO_NET_CASH = "TURNED_TO_NET_CASH"
    TURNED_TO_NET_DEBT = "TURNED_TO_NET_DEBT"
    REVENUE_MATERIAL_GROWTH = "REVENUE_MATERIAL_GROWTH"
    REVENUE_DECLINE = "REVENUE_DECLINE"
    FCF_MATERIAL_GROWTH = "FCF_MATERIAL_GROWTH"
    FCF_DECLINE = "FCF_DECLINE"
    PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION = (
        "PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION"
    )
    PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION = (
        "PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION"
    )
    PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY = (
        "PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY"
    )
    INSUFFICIENT_PRIOR_YEAR_DATA = "INSUFFICIENT_PRIOR_YEAR_DATA"


@dataclass(frozen=True)
class EconomicValueThresholds:
    """Centralized, named materiality boundaries. Not configurable weights.

    These are inspectable cutoffs a reader can change in one place; the
    classification is a documented rule, never a weighted sum. Growth-type
    thresholds are fractions (0.05 == 5%); margin and ROIC change thresholds are
    absolute differences in the ratio (0.01 == 1 percentage point).
    """

    material_growth: float = 0.05
    material_margin_change: float = 0.01
    material_roic_change: float = 0.02
    severe_roic_change: float = 0.05
    material_share_change: float = 0.01
    high_roic_level: float = 0.20


DEFAULT_THRESHOLDS = EconomicValueThresholds()


@dataclass(frozen=True)
class EconomicValueSnapshot:
    """One fiscal year of owner-oriented signals, its verdict, and its drivers."""

    fiscal_year: int
    # CHANGE signals (year over year); None when the prior year is unavailable.
    revenue_growth: float | None
    operating_margin_change: float | None
    fcf_growth: float | None
    fcf_margin_change: float | None
    diluted_share_growth: float | None
    fcf_per_share_growth: float | None
    roic_change: float | None
    # LEVEL signals (point in time).
    operating_margin: float | None
    fcf_margin: float | None
    fcf_per_share: float | None
    roic: float | None
    net_cash_or_debt: int | None
    # Interpretation.
    classification: EconomicValueClassification
    drivers: tuple[EconomicValueDriver, ...]


_NetCashSignal = NetCashTrajectory


def _direction(value: float | None, threshold: float) -> int | None:
    """Return +1 above +threshold, -1 below -threshold, 0 within, None if absent."""
    if value is None:
        return None
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _share_direction(share_growth: float | None, threshold: float) -> int | None:
    """A share-count decline is positive for owners; dilution is negative."""
    if share_growth is None:
        return None
    if share_growth <= -threshold:
        return 1
    if share_growth >= threshold:
        return -1
    return 0


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / prior


def _delta(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None:
        return None
    return current - prior


def _net_cash_signal(
    current: int | None, prior: int | None, thresholds: EconomicValueThresholds
) -> _NetCashSignal | None:
    return net_cash_trajectory(prior, current, material=thresholds.material_growth)


def _emit_directional_drivers(
    *,
    pps_dir: int | None,
    roic_dir: int | None,
    roic_high: bool,
    opm_dir: int | None,
    fcfm_dir: int | None,
    share_dir: int | None,
    net_cash: _NetCashSignal | None,
    rev_dir: int | None,
    fcf_dir: int | None,
) -> list[EconomicValueDriver]:
    """Build drivers in the fixed priority order used for every classification."""
    drivers: list[EconomicValueDriver] = []
    if pps_dir == 1:
        drivers.append(EconomicValueDriver.FCF_PER_SHARE_STRONG_GROWTH)
    elif pps_dir == -1:
        drivers.append(EconomicValueDriver.FCF_PER_SHARE_DECLINE)
    if roic_dir == 1:
        drivers.append(EconomicValueDriver.ROIC_EXPANDED)
    elif roic_dir == -1:
        drivers.append(EconomicValueDriver.ROIC_CONTRACTED)
    if roic_high:
        drivers.append(EconomicValueDriver.ROIC_SUSTAINED_HIGH)
    if opm_dir == 1:
        drivers.append(EconomicValueDriver.OPERATING_MARGIN_EXPANDED)
    elif opm_dir == -1:
        drivers.append(EconomicValueDriver.OPERATING_MARGIN_CONTRACTED)
    if fcfm_dir == 1:
        drivers.append(EconomicValueDriver.FCF_MARGIN_EXPANDED)
    elif fcfm_dir == -1:
        drivers.append(EconomicValueDriver.FCF_MARGIN_CONTRACTED)
    if share_dir == 1:
        drivers.append(EconomicValueDriver.SHARE_COUNT_DECLINED)
    elif share_dir == -1:
        drivers.append(EconomicValueDriver.SHARE_COUNT_INCREASED)
    if net_cash is not None and net_cash.direction != 0:
        if net_cash.direction == 1:
            drivers.append(
                EconomicValueDriver.TURNED_TO_NET_CASH
                if net_cash.flipped
                else EconomicValueDriver.NET_CASH_IMPROVED
            )
        else:
            drivers.append(
                EconomicValueDriver.TURNED_TO_NET_DEBT
                if net_cash.flipped
                else EconomicValueDriver.NET_CASH_DETERIORATED
            )
    if rev_dir == 1:
        drivers.append(EconomicValueDriver.REVENUE_MATERIAL_GROWTH)
    elif rev_dir == -1:
        drivers.append(EconomicValueDriver.REVENUE_DECLINE)
    if fcf_dir == 1:
        drivers.append(EconomicValueDriver.FCF_MATERIAL_GROWTH)
    elif fcf_dir == -1:
        drivers.append(EconomicValueDriver.FCF_DECLINE)
    return drivers


def _classify(
    snapshot: EconomicValueSnapshot,
    thresholds: EconomicValueThresholds,
    net_cash: _NetCashSignal | None,
) -> tuple[EconomicValueClassification, tuple[EconomicValueDriver, ...]]:
    """Apply the documented deterministic rule to a snapshot's signals."""
    # Insufficiency gate: per-share growth is the required minimum comparison.
    if snapshot.fcf_per_share_growth is None:
        return (
            EconomicValueClassification.INSUFFICIENT_DATA,
            (EconomicValueDriver.INSUFFICIENT_PRIOR_YEAR_DATA,),
        )

    pps_dir = _direction(snapshot.fcf_per_share_growth, thresholds.material_growth)
    roic_dir = _direction(snapshot.roic_change, thresholds.material_roic_change)
    roic_severe = (
        snapshot.roic_change is not None
        and snapshot.roic_change <= -thresholds.severe_roic_change
    )
    roic_high = snapshot.roic is not None and snapshot.roic >= thresholds.high_roic_level
    opm_dir = _direction(
        snapshot.operating_margin_change, thresholds.material_margin_change
    )
    fcfm_dir = _direction(snapshot.fcf_margin_change, thresholds.material_margin_change)
    share_dir = _share_direction(
        snapshot.diluted_share_growth, thresholds.material_share_change
    )
    rev_dir = _direction(snapshot.revenue_growth, thresholds.material_growth)
    fcf_dir = _direction(snapshot.fcf_growth, thresholds.material_growth)

    drivers = _emit_directional_drivers(
        pps_dir=pps_dir,
        roic_dir=roic_dir,
        roic_high=roic_high,
        opm_dir=opm_dir,
        fcfm_dir=fcfm_dir,
        share_dir=share_dir,
        net_cash=net_cash,
        rev_dir=rev_dir,
        fcf_dir=fcf_dir,
    )

    # Genuine leverage deterioration: a turn to net debt or a deepening net-debt
    # position. Drawing down surplus cash while remaining net-cash positive is
    # reported as a driver but is not a leverage guardrail.
    leverage_deteriorated = (
        net_cash is not None and net_cash.direction == -1 and net_cash.net_debt
    )

    if pps_dir == 1:
        classification, offsets = _resolve_improving_base(
            roic_material=(roic_dir == -1),
            roic_severe=roic_severe,
            leverage_deteriorated=leverage_deteriorated,
        )
        drivers.extend(offsets)
    elif pps_dir == -1:
        classification, offsets = _resolve_deteriorating_base(
            snapshot=snapshot,
            thresholds=thresholds,
            roic_dir=roic_dir,
            opm_dir=opm_dir,
            fcfm_dir=fcfm_dir,
        )
        drivers.extend(offsets)
    else:
        classification = _resolve_stable_base(
            roic_dir=roic_dir,
            opm_dir=opm_dir,
            fcfm_dir=fcfm_dir,
            share_dir=share_dir,
            net_cash=net_cash,
            material_guard=leverage_deteriorated or roic_severe,
        )

    return classification, tuple(drivers)


def _resolve_improving_base(
    *, roic_material: bool, roic_severe: bool, leverage_deteriorated: bool
) -> tuple[EconomicValueClassification, list[EconomicValueDriver]]:
    """Strong per-share growth cannot alone declare improvement amid deterioration."""
    offsets: list[EconomicValueDriver] = []
    roic_bad = roic_material or roic_severe
    if not roic_bad and not leverage_deteriorated:
        return EconomicValueClassification.IMPROVING, offsets
    if roic_bad:
        offsets.append(
            EconomicValueDriver.PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION
        )
    if leverage_deteriorated:
        offsets.append(
            EconomicValueDriver.PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION
        )
    # Both guardrails firing, or severe ROIC deterioration alone, is deteriorating.
    if roic_severe or (roic_bad and leverage_deteriorated):
        return EconomicValueClassification.DETERIORATING, offsets
    return EconomicValueClassification.STABLE, offsets


def _resolve_deteriorating_base(
    *,
    snapshot: EconomicValueSnapshot,
    thresholds: EconomicValueThresholds,
    roic_dir: int | None,
    opm_dir: int | None,
    fcfm_dir: int | None,
) -> tuple[EconomicValueClassification, list[EconomicValueDriver]]:
    """A marginal per-share decline offset by strong quality tempers to stable."""
    pps_growth = snapshot.fcf_per_share_growth
    marginal = pps_growth is not None and abs(pps_growth) < 2 * thresholds.material_growth
    if marginal and roic_dir == 1 and opm_dir == 1 and fcfm_dir == 1:
        return (
            EconomicValueClassification.STABLE,
            [EconomicValueDriver.PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY],
        )
    return EconomicValueClassification.DETERIORATING, []


def _resolve_stable_base(
    *,
    roic_dir: int | None,
    opm_dir: int | None,
    fcfm_dir: int | None,
    share_dir: int | None,
    net_cash: _NetCashSignal | None,
    material_guard: bool,
) -> EconomicValueClassification:
    """Resolve a flat per-share year by counting corroborating secondary signals."""
    net_cash_dir = net_cash.direction if net_cash is not None else None
    votes = [
        d
        for d in (roic_dir, opm_dir, fcfm_dir, share_dir, net_cash_dir)
        if d is not None
    ]
    positive = sum(1 for d in votes if d == 1)
    negative = sum(1 for d in votes if d == -1)
    if positive >= 2 and positive > negative and not material_guard:
        return EconomicValueClassification.IMPROVING
    if negative >= 2 and negative > positive:
        return EconomicValueClassification.DETERIORATING
    return EconomicValueClassification.STABLE


def classify_economic_value(
    snapshot: EconomicValueSnapshot,
    *,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueClassification, tuple[EconomicValueDriver, ...]]:
    """Classify a snapshot from its own fields alone.

    A single snapshot has no prior-year net-cash value, so the net-cash change
    guardrail is applied by ``build_economic_value_snapshots``, which sees the
    adjacent years; standalone classification uses the remaining signals.
    """
    return _classify(snapshot, thresholds, None)


def _owner_by_year(
    rows: Sequence[OwnerEconomicsRow],
) -> dict[int, OwnerEconomicsRow]:
    return {row.fiscal_year: row for row in rows}


def _capital_by_year(
    rows: Sequence[CapitalEfficiencyRow],
) -> dict[int, CapitalEfficiencyRow]:
    return {row.fiscal_year: row for row in rows}


def build_economic_value_snapshots(
    owner_economics: Sequence[OwnerEconomicsRow],
    capital_efficiency: Sequence[CapitalEfficiencyRow],
    *,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueSnapshot, ...]:
    """Align Feature 1 rows by fiscal year and build classified snapshots."""
    owner = _owner_by_year(owner_economics)
    capital = _capital_by_year(capital_efficiency)
    years = sorted(set(owner) | set(capital), reverse=True)

    snapshots: list[EconomicValueSnapshot] = []
    for year in years:
        owner_row = owner.get(year)
        capital_row = capital.get(year)
        prior_owner = owner.get(year - 1)
        prior_capital = capital.get(year - 1)

        revenue_growth = _growth(
            _observation_value(owner_row),
            _observation_value(prior_owner),
        )
        operating_margin_change = _delta(
            _attr(owner_row, "operating_margin"),
            _attr(prior_owner, "operating_margin"),
        )
        fcf_margin_change = _delta(
            _attr(owner_row, "fcf_margin"),
            _attr(prior_owner, "fcf_margin"),
        )
        roic_change = _delta(
            _attr(capital_row, "roic"),
            _attr(prior_capital, "roic"),
        )
        net_cash = _net_cash_signal(
            _attr(capital_row, "net_cash"),
            _attr(prior_capital, "net_cash"),
            thresholds,
        )

        snapshot = EconomicValueSnapshot(
            fiscal_year=year,
            revenue_growth=revenue_growth,
            operating_margin_change=operating_margin_change,
            fcf_growth=_attr(owner_row, "fcf_growth"),
            fcf_margin_change=fcf_margin_change,
            diluted_share_growth=_attr(owner_row, "diluted_share_growth"),
            fcf_per_share_growth=_attr(owner_row, "fcf_per_share_growth"),
            roic_change=roic_change,
            operating_margin=_attr(owner_row, "operating_margin"),
            fcf_margin=_attr(owner_row, "fcf_margin"),
            fcf_per_share=_attr(owner_row, "fcf_per_share"),
            roic=_attr(capital_row, "roic"),
            net_cash_or_debt=_attr(capital_row, "net_cash"),
            classification=EconomicValueClassification.INSUFFICIENT_DATA,
            drivers=(),
        )
        classification, drivers = _classify(snapshot, thresholds, net_cash)
        snapshots.append(
            replace(snapshot, classification=classification, drivers=drivers)
        )
    return tuple(snapshots)


def _observation_value(row: OwnerEconomicsRow | None) -> int | None:
    if row is None or row.revenue is None:
        return None
    return row.revenue.value


def _attr(row: Any, name: str) -> Any:
    if row is None:
        return None
    return getattr(row, name)


def economic_value_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueSnapshot, ...]:
    """Normalize Feature 1 outputs from a payload, then build snapshots.

    All SEC retrieval and normalization happen inside the Feature 1 entry points;
    this interpretation layer performs no network access.
    """
    owner_economics = owner_economics_from_facts(
        raw_facts, ticker=ticker, max_years=max_years
    )
    capital_efficiency = capital_efficiency_from_facts(
        raw_facts, ticker=ticker, max_years=max_years
    )
    return build_economic_value_snapshots(
        owner_economics, capital_efficiency, thresholds=thresholds
    )


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/a"


def _fmt_ratio(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _fmt_cash(value: int | None) -> str:
    return f"{value:+,}" if value is not None else "n/a"


def format_economic_value_view(
    snapshots: Sequence[EconomicValueSnapshot],
) -> str:
    """Render the compact owner-oriented view with per-year drivers."""
    header = (
        f"{'FY':>4}  {'RevGr':>7}  {'OpMgΔ':>7}  {'FCFGr':>7}  "
        f"{'FCF/shGr':>8}  {'ShGr':>7}  {'ROIC':>6}  {'ROICΔ':>7}  "
        f"{'NetCash':>14}  {'Class':<16}"
    )
    lines = [header, "-" * len(header)]
    for snap in snapshots:
        lines.append(
            f"{snap.fiscal_year:>4}  "
            f"{_fmt_pct(snap.revenue_growth):>7}  "
            f"{_fmt_pct(snap.operating_margin_change):>7}  "
            f"{_fmt_pct(snap.fcf_growth):>7}  "
            f"{_fmt_pct(snap.fcf_per_share_growth):>8}  "
            f"{_fmt_pct(snap.diluted_share_growth):>7}  "
            f"{_fmt_ratio(snap.roic):>6}  "
            f"{_fmt_pct(snap.roic_change):>7}  "
            f"{_fmt_cash(snap.net_cash_or_debt):>14}  "
            f"{snap.classification.value:<16}"
        )
        driver_names = ", ".join(d.value for d in snap.drivers) or "none"
        lines.append(f"      drivers: {driver_names}")
    return "\n".join(lines)

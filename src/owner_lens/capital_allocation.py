"""Deterministic capital-allocation interpretation for OwnerLens.

This module supports OwnerLens Slice 2C. It consumes the existing Feature 1 free
cash flow, diluted-share growth, net cash or net debt, and ROIC, the Feature 2A
annual snapshots, and the new reported repurchase, stock-based-compensation, and
dividend facts, and for each fiscal year derives the capital-allocation ratios,
capital returned, and retained free cash flow, interprets buyback effectiveness
from the actual diluted-share-count change, and classifies the year as
owner-friendly, balanced, questionable, owner-unfriendly, or insufficient-data
with ordered named drivers.

The layer performs no SEC retrieval. It never subtracts SBC from free cash flow,
never infers repurchases from share-count changes, preserves a negative retained
free cash flow, treats a structurally-absent dividend concept as no dividend
program, reuses the shared net-cash trajectory helper for the balance-sheet
guardrail, and surfaces ROIC as context only. Thresholds are centralized and
named; there are no configurable weights and no numeric score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from owner_lens._trajectory import NetCashTrajectory, net_cash_trajectory
from owner_lens.capital_efficiency import (
    CapitalEfficiencyRow,
    capital_efficiency_from_facts,
)
from owner_lens.economic_value import EconomicValueSnapshot, economic_value_from_facts
from owner_lens.owner_economics import OwnerEconomicsRow, owner_economics_from_facts
from owner_lens.reported import (
    AnnualSeries,
    normalize_dividends_paid,
    normalize_repurchases,
    normalize_stock_based_compensation,
)

__all__ = [
    "DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS",
    "BuybackEffectiveness",
    "CapitalAllocationClassification",
    "CapitalAllocationDriver",
    "CapitalAllocationRow",
    "CapitalAllocationThresholds",
    "build_capital_allocation_rows",
    "capital_allocation_from_facts",
    "capital_allocation_summary",
    "classify_buyback_effectiveness",
    "format_capital_allocation_view",
]


class BuybackEffectiveness(Enum):
    """How repurchase spending translated into actual share-count reduction."""

    EFFECTIVE_BUYBACKS = "EFFECTIVE_BUYBACKS"
    PARTIALLY_OFFSET_BY_DILUTION = "PARTIALLY_OFFSET_BY_DILUTION"
    INEFFECTIVE_BUYBACKS = "INEFFECTIVE_BUYBACKS"
    NET_DILUTION = "NET_DILUTION"
    NO_MEANINGFUL_BUYBACK_ACTIVITY = "NO_MEANINGFUL_BUYBACK_ACTIVITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CapitalAllocationClassification(Enum):
    """Deterministic per-year verdict on observable capital-allocation outcomes."""

    OWNER_FRIENDLY = "OWNER_FRIENDLY"
    BALANCED = "BALANCED"
    QUESTIONABLE = "QUESTIONABLE"
    OWNER_UNFRIENDLY = "OWNER_UNFRIENDLY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CapitalAllocationDriver(Enum):
    """Named reason code explaining part of a capital-allocation interpretation."""

    SHARE_COUNT_SHRANK = "SHARE_COUNT_SHRANK"
    MATERIAL_DILUTION = "MATERIAL_DILUTION"
    SHARE_COUNT_FLAT = "SHARE_COUNT_FLAT"
    EFFECTIVE_BUYBACKS = "EFFECTIVE_BUYBACKS"
    BUYBACKS_OFFSET_BY_DILUTION = "BUYBACKS_OFFSET_BY_DILUTION"
    INEFFECTIVE_BUYBACKS = "INEFFECTIVE_BUYBACKS"
    NO_MEANINGFUL_BUYBACKS = "NO_MEANINGFUL_BUYBACKS"
    MEANINGFUL_REPURCHASES = "MEANINGFUL_REPURCHASES"
    HIGH_SBC_BURDEN = "HIGH_SBC_BURDEN"
    CAPITAL_RETURNED_EXCEEDS_FCF = "CAPITAL_RETURNED_EXCEEDS_FCF"
    BALANCE_SHEET_IMPROVED = "BALANCE_SHEET_IMPROVED"
    BALANCE_SHEET_DETERIORATED = "BALANCE_SHEET_DETERIORATED"
    HIGH_ROIC_CONTEXT = "HIGH_ROIC_CONTEXT"
    LOW_ROIC_CONTEXT = "LOW_ROIC_CONTEXT"
    ROIC_IMPROVING = "ROIC_IMPROVING"
    ROIC_DETERIORATING = "ROIC_DETERIORATING"
    RETAINED_FCF_NEGATIVE = "RETAINED_FCF_NEGATIVE"
    NO_DIVIDEND_PROGRAM = "NO_DIVIDEND_PROGRAM"
    INSUFFICIENT_CAPITAL_DATA = "INSUFFICIENT_CAPITAL_DATA"


@dataclass(frozen=True)
class CapitalAllocationThresholds:
    """Centralized, named materiality boundaries. Not configurable weights."""

    material_share_change: float = 0.01
    high_sbc_to_fcf: float = 0.15
    meaningful_repurchase_to_fcf: float = 0.25
    capital_returned_over_fcf_material: float = 1.00
    high_roic_level: float = 0.20
    material_roic_change: float = 0.03
    net_cash_material_change: float = 0.05


DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS = CapitalAllocationThresholds()


@dataclass(frozen=True)
class CapitalAllocationRow:
    """One fiscal year of capital-allocation facts, metrics, and interpretation."""

    fiscal_year: int
    # Reported and reused facts.
    free_cash_flow: int | None
    repurchases: int | None
    dividends: int | None
    sbc: int | None
    diluted_share_growth: float | None
    net_cash_or_debt: int | None
    roic: float | None
    # Derived metrics.
    repurchases_over_fcf: float | None
    dividends_over_fcf: float | None
    sbc_over_fcf: float | None
    capital_returned: int | None
    capital_returned_over_fcf: float | None
    retained_fcf: int | None
    # Interpretation.
    buyback_effectiveness: BuybackEffectiveness
    classification: CapitalAllocationClassification
    drivers: tuple[CapitalAllocationDriver, ...]


def _ratio(numerator: int | None, free_cash_flow: int | None) -> float | None:
    if numerator is None or free_cash_flow is None or free_cash_flow <= 0:
        return None
    return numerator / free_cash_flow


def classify_buyback_effectiveness(
    *,
    repurchases: int | None,
    repurchases_over_fcf: float | None,
    diluted_share_growth: float | None,
    thresholds: CapitalAllocationThresholds = DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> BuybackEffectiveness:
    """Compare repurchase spending against the actual diluted-share-count change."""
    if repurchases is None or diluted_share_growth is None:
        return BuybackEffectiveness.INSUFFICIENT_DATA
    if repurchases_over_fcf is not None:
        meaningful = repurchases_over_fcf >= thresholds.meaningful_repurchase_to_fcf
    else:
        meaningful = repurchases > 0
    shrank = diluted_share_growth <= -thresholds.material_share_change
    rose = diluted_share_growth >= thresholds.material_share_change
    if meaningful:
        if shrank:
            return BuybackEffectiveness.EFFECTIVE_BUYBACKS
        if rose:
            return BuybackEffectiveness.INEFFECTIVE_BUYBACKS
        return BuybackEffectiveness.PARTIALLY_OFFSET_BY_DILUTION
    if rose:
        return BuybackEffectiveness.NET_DILUTION
    return BuybackEffectiveness.NO_MEANINGFUL_BUYBACK_ACTIVITY


_EFFECTIVENESS_DRIVER = {
    BuybackEffectiveness.EFFECTIVE_BUYBACKS: CapitalAllocationDriver.EFFECTIVE_BUYBACKS,
    BuybackEffectiveness.PARTIALLY_OFFSET_BY_DILUTION: (
        CapitalAllocationDriver.BUYBACKS_OFFSET_BY_DILUTION
    ),
    BuybackEffectiveness.INEFFECTIVE_BUYBACKS: CapitalAllocationDriver.INEFFECTIVE_BUYBACKS,
    BuybackEffectiveness.NO_MEANINGFUL_BUYBACK_ACTIVITY: (
        CapitalAllocationDriver.NO_MEANINGFUL_BUYBACKS
    ),
}


@dataclass(frozen=True)
class _CapitalSignals:
    diluted_share_growth: float | None
    buyback_effectiveness: BuybackEffectiveness
    repurchases_over_fcf: float | None
    sbc_over_fcf: float | None
    capital_returned_over_fcf: float | None
    retained_fcf: int | None
    roic: float | None
    roic_change: float | None
    trajectory: NetCashTrajectory | None
    no_dividend_program: bool


def _emit_drivers(
    signals: _CapitalSignals, thresholds: CapitalAllocationThresholds
) -> list[CapitalAllocationDriver]:
    """Build drivers in the fixed priority order used for every classification."""
    drivers: list[CapitalAllocationDriver] = []
    dsg = signals.diluted_share_growth
    if dsg is not None:
        if dsg <= -thresholds.material_share_change:
            drivers.append(CapitalAllocationDriver.SHARE_COUNT_SHRANK)
        elif dsg >= thresholds.material_share_change:
            drivers.append(CapitalAllocationDriver.MATERIAL_DILUTION)
        else:
            drivers.append(CapitalAllocationDriver.SHARE_COUNT_FLAT)
    effectiveness_driver = _EFFECTIVENESS_DRIVER.get(signals.buyback_effectiveness)
    if effectiveness_driver is not None:
        drivers.append(effectiveness_driver)
    if (
        signals.repurchases_over_fcf is not None
        and signals.repurchases_over_fcf >= thresholds.meaningful_repurchase_to_fcf
    ):
        drivers.append(CapitalAllocationDriver.MEANINGFUL_REPURCHASES)
    if (
        signals.sbc_over_fcf is not None
        and signals.sbc_over_fcf >= thresholds.high_sbc_to_fcf
    ):
        drivers.append(CapitalAllocationDriver.HIGH_SBC_BURDEN)
    if (
        signals.capital_returned_over_fcf is not None
        and signals.capital_returned_over_fcf >= thresholds.capital_returned_over_fcf_material
    ):
        drivers.append(CapitalAllocationDriver.CAPITAL_RETURNED_EXCEEDS_FCF)
    if signals.trajectory is not None:
        if signals.trajectory.direction == 1:
            drivers.append(CapitalAllocationDriver.BALANCE_SHEET_IMPROVED)
        elif signals.trajectory.direction == -1 and signals.trajectory.net_debt:
            drivers.append(CapitalAllocationDriver.BALANCE_SHEET_DETERIORATED)
    if signals.roic is not None:
        drivers.append(
            CapitalAllocationDriver.HIGH_ROIC_CONTEXT
            if signals.roic >= thresholds.high_roic_level
            else CapitalAllocationDriver.LOW_ROIC_CONTEXT
        )
    if signals.roic_change is not None:
        if signals.roic_change >= thresholds.material_roic_change:
            drivers.append(CapitalAllocationDriver.ROIC_IMPROVING)
        elif signals.roic_change <= -thresholds.material_roic_change:
            drivers.append(CapitalAllocationDriver.ROIC_DETERIORATING)
    if signals.retained_fcf is not None and signals.retained_fcf < 0:
        drivers.append(CapitalAllocationDriver.RETAINED_FCF_NEGATIVE)
    if signals.no_dividend_program:
        drivers.append(CapitalAllocationDriver.NO_DIVIDEND_PROGRAM)
    return drivers


def _classify(
    signals: _CapitalSignals, thresholds: CapitalAllocationThresholds
) -> tuple[CapitalAllocationClassification, tuple[CapitalAllocationDriver, ...]]:
    """Apply the documented priority rule to a year's capital-allocation signals."""
    dsg = signals.diluted_share_growth
    if dsg is None or signals.buyback_effectiveness is BuybackEffectiveness.INSUFFICIENT_DATA:
        return (
            CapitalAllocationClassification.INSUFFICIENT_DATA,
            (CapitalAllocationDriver.INSUFFICIENT_CAPITAL_DATA,),
        )

    drivers = _emit_drivers(signals, thresholds)
    high_sbc = (
        signals.sbc_over_fcf is not None
        and signals.sbc_over_fcf >= thresholds.high_sbc_to_fcf
    )
    returns_exceed = (
        signals.capital_returned_over_fcf is not None
        and signals.capital_returned_over_fcf >= thresholds.capital_returned_over_fcf_material
    )
    # Genuine leverage deterioration only (a turn to net debt or deepening net debt).
    deteriorated = (
        signals.trajectory is not None
        and signals.trajectory.direction == -1
        and signals.trajectory.net_debt
    )
    shrank = dsg <= -thresholds.material_share_change
    rose = dsg >= thresholds.material_share_change
    effectiveness = signals.buyback_effectiveness

    if rose:
        classification = (
            CapitalAllocationClassification.OWNER_UNFRIENDLY
            if high_sbc or deteriorated
            else CapitalAllocationClassification.QUESTIONABLE
        )
    elif shrank and effectiveness is BuybackEffectiveness.EFFECTIVE_BUYBACKS:
        classification = (
            CapitalAllocationClassification.QUESTIONABLE
            if deteriorated
            else CapitalAllocationClassification.OWNER_FRIENDLY
        )
    else:
        offset = effectiveness in (
            BuybackEffectiveness.PARTIALLY_OFFSET_BY_DILUTION,
            BuybackEffectiveness.INEFFECTIVE_BUYBACKS,
        )
        if offset and (high_sbc or deteriorated or returns_exceed) or deteriorated:
            classification = CapitalAllocationClassification.QUESTIONABLE
        else:
            classification = CapitalAllocationClassification.BALANCED

    return classification, tuple(drivers)


def _by_year_value(series: AnnualSeries) -> dict[int, int]:
    return {obs.fiscal_year: obs.value for obs in series.observations}


def build_capital_allocation_rows(
    owner_economics: Sequence[OwnerEconomicsRow],
    capital_efficiency: Sequence[CapitalEfficiencyRow],
    snapshots: Sequence[EconomicValueSnapshot],
    repurchases: AnnualSeries,
    stock_based_compensation: AnnualSeries,
    dividends_paid: AnnualSeries,
    *,
    thresholds: CapitalAllocationThresholds = DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> tuple[CapitalAllocationRow, ...]:
    """Align inputs by fiscal year and build classified capital-allocation rows."""
    owner = {row.fiscal_year: row for row in owner_economics}
    capital = {row.fiscal_year: row for row in capital_efficiency}
    snapshot = {snap.fiscal_year: snap for snap in snapshots}
    repo_by = _by_year_value(repurchases)
    sbc_by = _by_year_value(stock_based_compensation)
    div_by = _by_year_value(dividends_paid)
    no_dividend_program = dividends_paid.concept == "" and not dividends_paid.observations

    years = sorted(set(owner) | set(capital) | set(repo_by) | set(sbc_by), reverse=True)
    rows: list[CapitalAllocationRow] = []
    for year in years:
        owner_row = owner.get(year)
        capital_row = capital.get(year)
        fcf = _attr(owner_row, "free_cash_flow")
        repo = repo_by.get(year)
        sbc = sbc_by.get(year)
        dividends = div_by.get(year)
        dividends_effective = dividends if dividends is not None else (0 if no_dividend_program else None)
        dsg = _attr(owner_row, "diluted_share_growth")
        net_cash = _attr(capital_row, "net_cash")
        roic = _attr(capital_row, "roic")
        roic_change = _attr(snapshot.get(year), "roic_change")

        repurchases_over_fcf = _ratio(repo, fcf)
        capital_returned = (
            repo + dividends_effective
            if repo is not None and dividends_effective is not None
            else None
        )
        retained_fcf = (
            fcf - repo - dividends_effective
            if fcf is not None and repo is not None and dividends_effective is not None
            else None
        )
        prior_capital = capital.get(year - 1)
        trajectory = net_cash_trajectory(
            _attr(prior_capital, "net_cash"),
            net_cash,
            material=thresholds.net_cash_material_change,
        )

        effectiveness = classify_buyback_effectiveness(
            repurchases=repo,
            repurchases_over_fcf=repurchases_over_fcf,
            diluted_share_growth=dsg,
            thresholds=thresholds,
        )
        capital_returned_over_fcf = _ratio(capital_returned, fcf)
        signals = _CapitalSignals(
            diluted_share_growth=dsg,
            buyback_effectiveness=effectiveness,
            repurchases_over_fcf=repurchases_over_fcf,
            sbc_over_fcf=_ratio(sbc, fcf),
            capital_returned_over_fcf=capital_returned_over_fcf,
            retained_fcf=retained_fcf,
            roic=roic,
            roic_change=roic_change,
            trajectory=trajectory,
            no_dividend_program=no_dividend_program,
        )
        classification, drivers = _classify(signals, thresholds)

        rows.append(
            CapitalAllocationRow(
                fiscal_year=year,
                free_cash_flow=fcf,
                repurchases=repo,
                dividends=dividends,
                sbc=sbc,
                diluted_share_growth=dsg,
                net_cash_or_debt=net_cash,
                roic=roic,
                repurchases_over_fcf=repurchases_over_fcf,
                dividends_over_fcf=_ratio(dividends, fcf),
                sbc_over_fcf=_ratio(sbc, fcf),
                capital_returned=capital_returned,
                capital_returned_over_fcf=capital_returned_over_fcf,
                retained_fcf=retained_fcf,
                buyback_effectiveness=effectiveness,
                classification=classification,
                drivers=drivers,
            )
        )
    return tuple(rows)


def _attr(row: Any, name: str) -> Any:
    return getattr(row, name) if row is not None else None


def capital_allocation_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: CapitalAllocationThresholds = DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> tuple[CapitalAllocationRow, ...]:
    """Normalize the reported and reused inputs from a payload, then build rows.

    All SEC retrieval and normalization happen inside the reported and Feature 1
    and Feature 2A entry points; this interpretation layer performs no network access.
    """
    owner = owner_economics_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    capital = capital_efficiency_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    snapshots = economic_value_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    repurchases = normalize_repurchases(raw_facts, ticker=ticker, max_years=max_years)
    sbc = normalize_stock_based_compensation(raw_facts, ticker=ticker, max_years=max_years)
    dividends = normalize_dividends_paid(raw_facts, ticker=ticker, max_years=max_years)
    return build_capital_allocation_rows(
        owner, capital, snapshots, repurchases, sbc, dividends, thresholds=thresholds
    )


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/a"


def _fmt_ratio(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else "n/a"


def _fmt_millions(value: int | None) -> str:
    return f"{value / 1e6:,.0f}" if value is not None else "n/a"


def format_capital_allocation_view(
    rows: Sequence[CapitalAllocationRow],
) -> str:
    """Render the compact per-year capital-allocation view with drivers ($ millions)."""
    header = (
        f"{'FY':>4}  {'FCF':>8}  {'Repo':>8}  {'Repo/FCF':>8}  {'Div':>6}  "
        f"{'SBC':>7}  {'SBC/FCF':>7}  {'CapRet':>8}  {'CR/FCF':>7}  "
        f"{'Retained':>9}  {'ShGr':>6}  {'Buyback':<26}  {'NetCash':>10}  "
        f"{'ROIC':>6}  {'Class':<16}"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.fiscal_year:>4}  "
            f"{_fmt_millions(r.free_cash_flow):>8}  "
            f"{_fmt_millions(r.repurchases):>8}  "
            f"{_fmt_ratio(r.repurchases_over_fcf):>8}  "
            f"{_fmt_millions(r.dividends):>6}  "
            f"{_fmt_millions(r.sbc):>7}  "
            f"{_fmt_ratio(r.sbc_over_fcf):>7}  "
            f"{_fmt_millions(r.capital_returned):>8}  "
            f"{_fmt_ratio(r.capital_returned_over_fcf):>7}  "
            f"{_fmt_millions(r.retained_fcf):>9}  "
            f"{_fmt_pct(r.diluted_share_growth):>6}  "
            f"{r.buyback_effectiveness.value:<26}  "
            f"{_fmt_millions(r.net_cash_or_debt):>10}  "
            f"{_fmt_ratio(r.roic):>6}  "
            f"{r.classification.value:<16}"
        )
        driver_names = ", ".join(d.value for d in r.drivers) or "none"
        lines.append(f"      drivers: {driver_names}")
    return "\n".join(lines)


def capital_allocation_summary(rows: Sequence[CapitalAllocationRow]) -> str:
    """Render the multi-year owner-question summary ($ millions)."""
    if not rows:
        return "No capital-allocation data."
    total_fcf = sum(r.free_cash_flow for r in rows if r.free_cash_flow is not None)
    total_repo = sum(r.repurchases for r in rows if r.repurchases is not None)
    total_div = sum(r.dividends for r in rows if r.dividends is not None)
    total_sbc = sum(r.sbc for r in rows if r.sbc is not None)
    sbc_over_fcf = total_sbc / total_fcf if total_fcf else None
    shrank_years = sum(
        1
        for r in rows
        if r.diluted_share_growth is not None and r.diluted_share_growth < 0
    )
    effective_years = sum(
        1 for r in rows if r.buyback_effectiveness is BuybackEffectiveness.EFFECTIVE_BUYBACKS
    )
    deteriorated = any(
        CapitalAllocationDriver.BALANCE_SHEET_DETERIORATED in r.drivers for r in rows
    )
    latest = rows[0]
    span = f"FY{rows[-1].fiscal_year}-FY{rows[0].fiscal_year}"
    no_dividends = all(r.dividends is None for r in rows)
    return "\n".join(
        [
            f"ADBE Capital Allocation Summary — {span} ($ millions)",
            "",
            f"  Free cash flow generated:   {_fmt_millions(total_fcf)}",
            (
                f"  Spent on repurchases:       {_fmt_millions(total_repo)} "
                f"({_fmt_ratio(total_repo / total_fcf if total_fcf else None)} of FCF)"
            ),
            (
                "  Returned as dividends:      "
                + (
                    "none (no dividend program)"
                    if no_dividends
                    else _fmt_millions(total_div)
                )
            ),
            f"  SBC relative to FCF:        {_fmt_ratio(sbc_over_fcf)}",
            f"  Years diluted shares fell:  {shrank_years} of {len(rows)}",
            f"  Years buybacks effective:   {effective_years} of {len(rows)}",
            f"  Balance sheet deteriorated: {'yes' if deteriorated else 'no'}",
            f"  Latest ROIC:                {_fmt_ratio(latest.roic)}",
        ]
    )

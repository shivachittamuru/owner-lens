"""Company-level economic-value synthesis for OwnerLens.

This module supports OwnerLens Slice 2D, the Feature 2 capstone. It composes the
existing Feature 2A annual economic-value snapshots, the Feature 2B recent and
long-term compounding views, and the Feature 2C capital-allocation rows into one
deterministic company-level ``EconomicValueSummary`` with an overall
classification, ordered deduplicated drivers, and a compact evidence set.

The overall classification follows a documented priority hierarchy on a small
ordinal scale: an insufficiency gate, a long-term compounding base that anchors
the positive ceiling, a bounded latest-year adjustment that reconciles
recent-versus-long-term tension, a capital-allocation modifier, and severe
quality and balance-sheet guardrails. It is never a mapping, average, weighted
score, or 0-to-100 score. The layer makes no SEC calls, performs no
normalization, and reimplements no component logic; it composes existing objects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.capital_allocation import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationRow,
    capital_allocation_from_history,
)
from owner_lens.compounding import (
    CompoundingClassification,
    EconomicCompoundingView,
    compounding_views_from_history,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    EconomicValueSnapshot,
    economic_value_from_history,
)
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS",
    "EconomicSummaryThresholds",
    "EconomicValueSummary",
    "OverallEconomicValueClassification",
    "SummaryDriver",
    "economic_value_summary_from_facts",
    "economic_value_summary_from_history",
    "format_economic_value_summary",
    "synthesize_economic_value_summary",
]


class OverallEconomicValueClassification(Enum):
    """Deterministic company-level verdict on economic-value development."""

    STRONGLY_IMPROVING = "STRONGLY_IMPROVING"
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    STRONGLY_DETERIORATING = "STRONGLY_DETERIORATING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SummaryDriver(Enum):
    """Named reason code, categorized positive, watch, or negative."""

    # Positive.
    PER_SHARE_CASH_FLOW_COMPOUNDING = "PER_SHARE_CASH_FLOW_COMPOUNDING"
    FCF_PER_SHARE_ACCELERATING = "FCF_PER_SHARE_ACCELERATING"
    HIGH_ROIC = "HIGH_ROIC"
    ROIC_IMPROVING = "ROIC_IMPROVING"
    SHARE_COUNT_SHRINKING = "SHARE_COUNT_SHRINKING"
    EFFECTIVE_BUYBACKS = "EFFECTIVE_BUYBACKS"
    OWNER_FRIENDLY_CAPITAL_ALLOCATION = "OWNER_FRIENDLY_CAPITAL_ALLOCATION"
    HEALTHY_BALANCE_SHEET = "HEALTHY_BALANCE_SHEET"
    MARGINS_EXPANDING = "MARGINS_EXPANDING"
    # Watch.
    HIGH_SBC_BURDEN = "HIGH_SBC_BURDEN"
    CAPITAL_RETURNS_EXCEED_FCF = "CAPITAL_RETURNS_EXCEED_FCF"
    DECLINING_NET_CASH_CUSHION = "DECLINING_NET_CASH_CUSHION"
    BUYBACKS_PARTLY_OFFSET_BY_DILUTION = "BUYBACKS_PARTLY_OFFSET_BY_DILUTION"
    MIXED_RECENT_ECONOMICS = "MIXED_RECENT_ECONOMICS"
    RECENT_SLOWDOWN = "RECENT_SLOWDOWN"
    EARLY_IMPROVEMENT_NOT_YET_PROVEN = "EARLY_IMPROVEMENT_NOT_YET_PROVEN"
    # Negative.
    FCF_PER_SHARE_DECLINING = "FCF_PER_SHARE_DECLINING"
    MATERIAL_DILUTION = "MATERIAL_DILUTION"
    ROIC_DETERIORATING = "ROIC_DETERIORATING"
    OWNER_UNFRIENDLY_CAPITAL_ALLOCATION = "OWNER_UNFRIENDLY_CAPITAL_ALLOCATION"
    WORSENING_NET_DEBT = "WORSENING_NET_DEBT"
    MARGINS_CONTRACTING = "MARGINS_CONTRACTING"
    AGGREGATE_FCF_DECLINING = "AGGREGATE_FCF_DECLINING"


@dataclass(frozen=True)
class EconomicSummaryThresholds:
    """Centralized, named cutoffs. Most severity reuses component drivers."""

    severe_roic_collapse: float = 0.10
    high_roic_level: float = 0.20


DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS = EconomicSummaryThresholds()


@dataclass(frozen=True)
class EconomicValueSummary:
    """One company-level synthesis of the Feature 2A, 2B, and 2C outputs."""

    ticker: str
    latest_fiscal_year: int | None
    # Component classifications.
    latest_annual_classification: EconomicValueClassification
    recent_compounding_classification: CompoundingClassification | None
    long_term_compounding_classification: CompoundingClassification
    latest_capital_allocation_classification: CapitalAllocationClassification
    # Synthesis.
    overall_economic_value_classification: OverallEconomicValueClassification
    key_positive_drivers: tuple[SummaryDriver, ...]
    key_watch_drivers: tuple[SummaryDriver, ...]
    key_negative_drivers: tuple[SummaryDriver, ...]
    # Compact evidence.
    latest_fcf_per_share_growth: float | None
    long_term_fcf_per_share_cagr: float | None
    recent_fcf_per_share_cagr: float | None
    diluted_share_cagr: float | None
    latest_roic: float | None
    long_term_roic_change: float | None
    latest_net_cash_or_debt: int | None
    latest_sbc_to_fcf: float | None
    latest_capital_returned_to_fcf: float | None
    buyback_effectiveness: BuybackEffectiveness | None


_SCORE_TO_OVERALL = {
    2: OverallEconomicValueClassification.STRONGLY_IMPROVING,
    1: OverallEconomicValueClassification.IMPROVING,
    0: OverallEconomicValueClassification.STABLE,
    -1: OverallEconomicValueClassification.DETERIORATING,
    -2: OverallEconomicValueClassification.STRONGLY_DETERIORATING,
}

_LONG_TERM_BASE = {
    CompoundingClassification.STRONGLY_COMPOUNDING: 2,
    CompoundingClassification.COMPOUNDING: 1,
    CompoundingClassification.STABLE: 0,
    CompoundingClassification.DETERIORATING: -1,
}

_ANNUAL_BASE = {
    EconomicValueClassification.IMPROVING: 1,
    EconomicValueClassification.STABLE: 0,
    EconomicValueClassification.DETERIORATING: -1,
}


def _latest(rows: Sequence[Any]) -> Any:
    return max(rows, key=lambda r: r.fiscal_year) if rows else None


@dataclass(frozen=True)
class _Signals:
    latest_annual: EconomicValueClassification
    long_term: CompoundingClassification
    recent: CompoundingClassification | None
    capital: CapitalAllocationClassification
    long_term_roic_change: float | None
    latest_net_cash_or_debt: int | None
    driver_values: frozenset[str]
    buyback_effectiveness: BuybackEffectiveness | None
    recent_cagr: float | None
    long_term_cagr: float | None
    diluted_share_cagr: float | None
    latest_roic: float | None
    net_cash_declined_but_positive: bool
    long_term_driver_values: frozenset[str]


def _classify_overall(
    signals: _Signals, thresholds: EconomicSummaryThresholds
) -> tuple[OverallEconomicValueClassification, list[SummaryDriver]]:
    """Apply the documented priority hierarchy to the component signals."""
    lt_base = _LONG_TERM_BASE.get(signals.long_term)
    annual_base = _ANNUAL_BASE.get(signals.latest_annual)
    if lt_base is None and annual_base is None:
        return OverallEconomicValueClassification.INSUFFICIENT_DATA, []

    established = lt_base is not None
    base = lt_base if lt_base is not None else annual_base
    assert base is not None
    score = base
    tension: list[SummaryDriver] = []

    # Latest-year adjustment: bounded one notch, never flips a strong base.
    if annual_base is not None:
        if base >= 1 and annual_base <= -1:
            score = base - 1
            tension.append(SummaryDriver.RECENT_SLOWDOWN)
        elif base <= -1 and annual_base >= 1:
            score = base + 1
            tension.append(SummaryDriver.EARLY_IMPROVEMENT_NOT_YET_PROVEN)

    # Without a long-term base, a positive latest year is not yet proven.
    if not established and score >= 1:
        score = 0
        tension.append(SummaryDriver.EARLY_IMPROVEMENT_NOT_YET_PROVEN)

    # Capital-allocation modifier: bounded, never lifts above the base.
    if signals.capital is CapitalAllocationClassification.OWNER_UNFRIENDLY or (
        signals.capital is CapitalAllocationClassification.QUESTIONABLE and score > 0
    ):
        score -= 1

    # Severe guardrails, applied last, force the score down.
    severe_roic = (
        signals.long_term_roic_change is not None
        and signals.long_term_roic_change <= -thresholds.severe_roic_collapse
    )
    net_debt_guardrail = (
        signals.latest_net_cash_or_debt is not None
        and signals.latest_net_cash_or_debt < 0
        and "BALANCE_SHEET_DETERIORATED" in signals.driver_values
    )
    if severe_roic:
        score = -2 if score <= -1 else -1
    if net_debt_guardrail:
        score = min(score, -1)

    score = max(-2, min(2, score))
    return _SCORE_TO_OVERALL[score], tension


def _dedup(drivers: list[SummaryDriver]) -> tuple[SummaryDriver, ...]:
    seen: set[SummaryDriver] = set()
    ordered: list[SummaryDriver] = []
    for driver in drivers:
        if driver not in seen:
            seen.add(driver)
            ordered.append(driver)
    return tuple(ordered)


def _collect_drivers(
    signals: _Signals,
    tension: list[SummaryDriver],
    thresholds: EconomicSummaryThresholds,
) -> tuple[tuple[SummaryDriver, ...], tuple[SummaryDriver, ...], tuple[SummaryDriver, ...]]:
    """Map component classifications and drivers into ordered, deduplicated categories."""
    dv = signals.driver_values
    positive: list[SummaryDriver] = []
    watch: list[SummaryDriver] = []
    negative: list[SummaryDriver] = []

    # Positive, in fixed priority order.
    if signals.long_term in (
        CompoundingClassification.STRONGLY_COMPOUNDING,
        CompoundingClassification.COMPOUNDING,
    ) or {"STRONG_FCF_PER_SHARE_COMPOUNDING", "MODERATE_FCF_PER_SHARE_COMPOUNDING"} & dv:
        positive.append(SummaryDriver.PER_SHARE_CASH_FLOW_COMPOUNDING)
    if (
        signals.recent_cagr is not None
        and signals.long_term_cagr is not None
        and signals.recent_cagr > signals.long_term_cagr + 0.01
    ):
        positive.append(SummaryDriver.FCF_PER_SHARE_ACCELERATING)
    if (
        signals.latest_roic is not None and signals.latest_roic >= thresholds.high_roic_level
    ) or {"HIGH_ROIC_CONTEXT", "ROIC_HIGH_AND_SUSTAINED"} & dv:
        positive.append(SummaryDriver.HIGH_ROIC)
    if {"ROIC_IMPROVING", "ROIC_IMPROVED"} & dv:
        positive.append(SummaryDriver.ROIC_IMPROVING)
    if "SHARE_COUNT_SHRANK" in dv or (
        signals.diluted_share_cagr is not None and signals.diluted_share_cagr < -0.01
    ):
        positive.append(SummaryDriver.SHARE_COUNT_SHRINKING)
    if signals.buyback_effectiveness is BuybackEffectiveness.EFFECTIVE_BUYBACKS:
        positive.append(SummaryDriver.EFFECTIVE_BUYBACKS)
    if signals.capital is CapitalAllocationClassification.OWNER_FRIENDLY:
        positive.append(SummaryDriver.OWNER_FRIENDLY_CAPITAL_ALLOCATION)
    # Margin trend uses the durable long-term window and never claims both directions.
    lt_dv = signals.long_term_driver_values
    lt_expanded = bool({"OPERATING_MARGIN_EXPANDED", "FCF_MARGIN_EXPANDED"} & lt_dv)
    lt_contracted = bool({"OPERATING_MARGIN_CONTRACTED", "FCF_MARGIN_CONTRACTED"} & lt_dv)
    if lt_expanded and not lt_contracted:
        positive.append(SummaryDriver.MARGINS_EXPANDING)

    # Watch, in fixed priority order.
    if "HIGH_SBC_BURDEN" in dv:
        watch.append(SummaryDriver.HIGH_SBC_BURDEN)
    if "CAPITAL_RETURNED_EXCEEDS_FCF" in dv:
        watch.append(SummaryDriver.CAPITAL_RETURNS_EXCEED_FCF)
    if signals.net_cash_declined_but_positive:
        watch.append(SummaryDriver.DECLINING_NET_CASH_CUSHION)
    if signals.buyback_effectiveness is BuybackEffectiveness.PARTIALLY_OFFSET_BY_DILUTION:
        watch.append(SummaryDriver.BUYBACKS_PARTLY_OFFSET_BY_DILUTION)
    if "MIXED_ANNUAL_ECONOMICS" in dv or (
        signals.recent is not None and signals.recent is not signals.long_term
    ):
        watch.append(SummaryDriver.MIXED_RECENT_ECONOMICS)
    watch.extend(tension)

    # Negative, in fixed priority order.
    if "FCF_PER_SHARE_DECLINED" in dv:
        negative.append(SummaryDriver.FCF_PER_SHARE_DECLINING)
    if "MATERIAL_DILUTION" in dv:
        negative.append(SummaryDriver.MATERIAL_DILUTION)
    severe_roic = (
        signals.long_term_roic_change is not None
        and signals.long_term_roic_change <= -thresholds.severe_roic_collapse
    )
    if "ROIC_DETERIORATED" in dv or "ROIC_DETERIORATING" in dv or severe_roic:
        negative.append(SummaryDriver.ROIC_DETERIORATING)
    if signals.capital is CapitalAllocationClassification.OWNER_UNFRIENDLY:
        negative.append(SummaryDriver.OWNER_UNFRIENDLY_CAPITAL_ALLOCATION)
    if (
        signals.latest_net_cash_or_debt is not None
        and signals.latest_net_cash_or_debt < 0
        and "BALANCE_SHEET_DETERIORATED" in dv
    ):
        negative.append(SummaryDriver.WORSENING_NET_DEBT)
    if lt_contracted and not lt_expanded:
        negative.append(SummaryDriver.MARGINS_CONTRACTING)
    if "AGGREGATE_FCF_DECLINED" in dv:
        negative.append(SummaryDriver.AGGREGATE_FCF_DECLINING)

    return _dedup(positive), _dedup(watch), _dedup(negative)


def _driver_values(*components: Any) -> frozenset[str]:
    values: set[str] = set()
    for component in components:
        if component is not None:
            values.update(d.value for d in component.drivers)
    return frozenset(values)


def synthesize_economic_value_summary(
    ticker: str,
    snapshots: Sequence[EconomicValueSnapshot],
    recent_view: EconomicCompoundingView | None,
    long_term_view: EconomicCompoundingView,
    capital_rows: Sequence[CapitalAllocationRow],
    *,
    thresholds: EconomicSummaryThresholds = DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
) -> EconomicValueSummary:
    """Compose the Feature 2A, 2B, and 2C outputs into a company-level summary."""
    latest_snapshot = _latest(snapshots)
    latest_capital = _latest(capital_rows)

    latest_annual = (
        latest_snapshot.classification
        if latest_snapshot is not None
        else EconomicValueClassification.INSUFFICIENT_DATA
    )
    long_term = long_term_view.classification
    recent = recent_view.classification if recent_view is not None else None
    capital = (
        latest_capital.classification
        if latest_capital is not None
        else CapitalAllocationClassification.INSUFFICIENT_DATA
    )

    latest_roic = (
        latest_snapshot.roic
        if latest_snapshot is not None and latest_snapshot.roic is not None
        else long_term_view.roic_end
    )
    net_cash = latest_capital.net_cash_or_debt if latest_capital is not None else None
    net_cash_declined_but_positive = (
        long_term_view.net_cash_or_debt_start is not None
        and long_term_view.net_cash_or_debt_end is not None
        and long_term_view.net_cash_or_debt_end < long_term_view.net_cash_or_debt_start
        and long_term_view.net_cash_or_debt_end >= 0
    )

    signals = _Signals(
        latest_annual=latest_annual,
        long_term=long_term,
        recent=recent,
        capital=capital,
        long_term_roic_change=long_term_view.roic_change,
        latest_net_cash_or_debt=net_cash,
        driver_values=_driver_values(
            latest_snapshot, recent_view, long_term_view, latest_capital
        ),
        buyback_effectiveness=(
            latest_capital.buyback_effectiveness if latest_capital is not None else None
        ),
        recent_cagr=recent_view.fcf_per_share_cagr if recent_view is not None else None,
        long_term_cagr=long_term_view.fcf_per_share_cagr,
        diluted_share_cagr=long_term_view.diluted_share_cagr,
        latest_roic=latest_roic,
        net_cash_declined_but_positive=net_cash_declined_but_positive,
        long_term_driver_values=frozenset(d.value for d in long_term_view.drivers),
    )

    overall, tension = _classify_overall(signals, thresholds)
    positive, watch, negative = _collect_drivers(signals, tension, thresholds)

    latest_fiscal_year = (
        latest_snapshot.fiscal_year
        if latest_snapshot is not None
        else latest_capital.fiscal_year
        if latest_capital is not None
        else long_term_view.end_fiscal_year
    )

    return EconomicValueSummary(
        ticker=ticker,
        latest_fiscal_year=latest_fiscal_year,
        latest_annual_classification=latest_annual,
        recent_compounding_classification=recent,
        long_term_compounding_classification=long_term,
        latest_capital_allocation_classification=capital,
        overall_economic_value_classification=overall,
        key_positive_drivers=positive,
        key_watch_drivers=watch,
        key_negative_drivers=negative,
        latest_fcf_per_share_growth=(
            latest_snapshot.fcf_per_share_growth if latest_snapshot is not None else None
        ),
        long_term_fcf_per_share_cagr=long_term_view.fcf_per_share_cagr,
        recent_fcf_per_share_cagr=(
            recent_view.fcf_per_share_cagr if recent_view is not None else None
        ),
        diluted_share_cagr=long_term_view.diluted_share_cagr,
        latest_roic=latest_roic,
        long_term_roic_change=long_term_view.roic_change,
        latest_net_cash_or_debt=net_cash,
        latest_sbc_to_fcf=latest_capital.sbc_over_fcf if latest_capital is not None else None,
        latest_capital_returned_to_fcf=(
            latest_capital.capital_returned_over_fcf if latest_capital is not None else None
        ),
        buyback_effectiveness=(
            latest_capital.buyback_effectiveness if latest_capital is not None else None
        ),
    )


def _summarize(
    ticker: str,
    history: CanonicalFinancialHistory,
    thresholds: EconomicSummaryThresholds,
) -> EconomicValueSummary:
    snapshots = economic_value_from_history(history)
    recent_view, long_term_view = compounding_views_from_history(history)
    capital_rows = capital_allocation_from_history(history)
    return synthesize_economic_value_summary(
        ticker,
        snapshots,
        recent_view,
        long_term_view,
        capital_rows,
        thresholds=thresholds,
    )


def economic_value_summary_from_history(
    history: CanonicalFinancialHistory,
    *,
    thresholds: EconomicSummaryThresholds = DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
) -> EconomicValueSummary:
    """Build every component from a canonical history, then synthesize the summary."""
    return _summarize(history.ticker, history, thresholds)


def economic_value_summary_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: EconomicSummaryThresholds = DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
) -> EconomicValueSummary:
    """Compatibility wrapper: map raw SEC Company Facts, then synthesize the summary.

    The caller's ``ticker`` is echoed into the summary exactly as supplied.
    """
    history = canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
    return _summarize(ticker, history, thresholds)


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/a"


def _fmt_ratio(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _fmt_billions(value: int | None) -> str:
    return f"{value / 1e9:+,.1f}B" if value is not None else "n/a"


def _cls(value: Any) -> str:
    return value.value if value is not None else "n/a"


def format_economic_value_summary(summary: EconomicValueSummary) -> str:
    """Render the compact owner-readable company-level Economic Value Lens."""
    lines = [
        f"{summary.ticker} — Economic Value Lens",
        "",
        f"  Latest annual:       {summary.latest_annual_classification.value}",
        f"  Recent compounding:  {_cls(summary.recent_compounding_classification)}",
        f"  Long-term:           {summary.long_term_compounding_classification.value}",
        f"  Capital allocation:  {summary.latest_capital_allocation_classification.value}",
        "",
        "Overall:",
        f"  {summary.overall_economic_value_classification.value}",
        "",
        "Core evidence:",
        f"  FCF/share CAGR:      {_fmt_pct(summary.long_term_fcf_per_share_cagr)}",
        f"  Share-count CAGR:    {_fmt_pct(summary.diluted_share_cagr)}",
        f"  ROIC:                {_fmt_ratio(summary.latest_roic)}",
        f"  Net cash/debt:       {_fmt_billions(summary.latest_net_cash_or_debt)}",
    ]
    if summary.key_positive_drivers:
        lines.append("")
        lines.append("Positive:")
        lines.extend(f"  + {d.value}" for d in summary.key_positive_drivers)
    if summary.key_watch_drivers:
        lines.append("")
        lines.append("Watch:")
        lines.extend(f"  - {d.value}" for d in summary.key_watch_drivers)
    if summary.key_negative_drivers:
        lines.append("")
        lines.append("Negative:")
        lines.extend(f"  ! {d.value}" for d in summary.key_negative_drivers)
    return "\n".join(lines)

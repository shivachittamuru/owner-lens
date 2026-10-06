"""Synthetic Feature 2 component builders for the Feature 7 screening tests.

Screening composes Feature 1 and Feature 2 outputs, so its unit tests construct
those outputs directly rather than going through SEC payloads. Every builder
produces the smallest object that carries the signal under test and leaves every
other field ``None``, so a test can never pass because of an incidental value.
"""

from __future__ import annotations

from datetime import date

from owner_lens.canonical import CanonicalFact
from owner_lens.capital_allocation import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationRow,
)
from owner_lens.capital_efficiency import CapitalEfficiencyRow
from owner_lens.compounding import CompoundingClassification, EconomicCompoundingView
from owner_lens.economic_summary import (
    EconomicValueSummary,
    OverallEconomicValueClassification,
)
from owner_lens.economic_value import EconomicValueClassification, EconomicValueSnapshot
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.screening import CoverageClass, ScreeningEvidence

BASE_YEAR = 2021
TICKER = "TEST"


def fact(metric: str, value: int, year: int) -> CanonicalFact:
    """A minimal canonical fact with the provenance the model requires."""
    return CanonicalFact(
        metric=metric,
        value=value,
        unit="shares" if metric == "diluted_shares" else "USD",
        fiscal_year=year,
        fiscal_period="FY",
        period_end=date(year, 12, 31),
        period_start=date(year - 1, 12, 31) if metric != "diluted_shares" else None,
        provider="test",
        provider_field=metric,
        form="10-K",
        filed=date(year + 1, 2, 1),
        accession=f"{metric}-{year}",
    )


def owner_row(
    year: int,
    *,
    free_cash_flow: int | None = None,
    fcf_per_share: float | None = None,
    diluted_shares: int | None = None,
    operating_margin: float | None = None,
    fcf_margin: float | None = None,
) -> OwnerEconomicsRow:
    """One owner-economics year carrying only the fields screening reads."""
    return OwnerEconomicsRow(
        fiscal_year=year,
        revenue=None,
        operating_income=None,
        net_income=None,
        operating_cash_flow=None,
        capital_expenditures=None,
        diluted_shares=(
            fact("diluted_shares", diluted_shares, year)
            if diluted_shares is not None
            else None
        ),
        operating_margin=operating_margin,
        net_margin=None,
        free_cash_flow=free_cash_flow,
        fcf_margin=fcf_margin,
        fcf_per_share=fcf_per_share,
        fcf_growth=None,
        fcf_per_share_growth=None,
        diluted_share_growth=None,
    )


def owner_series(
    free_cash_flow: list[int | None] | None = None,
    *,
    fcf_per_share: list[float | None] | None = None,
    diluted_shares: list[int | None] | None = None,
    operating_margin: list[float | None] | None = None,
    fcf_margin: list[float | None] | None = None,
    start_year: int = BASE_YEAR,
) -> tuple[OwnerEconomicsRow, ...]:
    """Owner-economics rows in ascending fiscal-year order from parallel series."""
    length = max(
        len(series)
        for series in (
            free_cash_flow,
            fcf_per_share,
            diluted_shares,
            operating_margin,
            fcf_margin,
        )
        if series is not None
    )

    def at(series: list | None, index: int):  # type: ignore[type-arg]
        return series[index] if series is not None and index < len(series) else None

    return tuple(
        owner_row(
            start_year + index,
            free_cash_flow=at(free_cash_flow, index),
            fcf_per_share=at(fcf_per_share, index),
            diluted_shares=at(diluted_shares, index),
            operating_margin=at(operating_margin, index),
            fcf_margin=at(fcf_margin, index),
        )
        for index in range(length)
    )


def capital_row(
    year: int, *, roic: float | None = None, net_cash: int | None = None
) -> CapitalEfficiencyRow:
    """One capital-efficiency year carrying only the fields screening reads."""
    return CapitalEfficiencyRow(
        fiscal_year=year,
        cash=None,
        short_term_investments=None,
        current_debt=None,
        long_term_debt=None,
        total_assets=None,
        total_equity=None,
        cash_plus_sti=None,
        total_debt=None,
        net_cash=net_cash,
        effective_tax_rate=None,
        nopat=None,
        invested_capital=None,
        roa=None,
        roe=None,
        roic=roic,
    )


def capital_series(
    roic: list[float | None] | None = None,
    *,
    net_cash: list[int | None] | None = None,
    start_year: int = BASE_YEAR,
) -> tuple[CapitalEfficiencyRow, ...]:
    """Capital-efficiency rows in ascending fiscal-year order from parallel series."""
    length = max(len(s) for s in (roic, net_cash) if s is not None)

    def at(series: list | None, index: int):  # type: ignore[type-arg]
        return series[index] if series is not None and index < len(series) else None

    return tuple(
        capital_row(
            start_year + index, roic=at(roic, index), net_cash=at(net_cash, index)
        )
        for index in range(length)
    )


def allocation_row(
    year: int,
    classification: CapitalAllocationClassification,
    *,
    sbc_over_fcf: float | None = None,
    capital_returned_over_fcf: float | None = None,
    buyback_effectiveness: BuybackEffectiveness = (
        BuybackEffectiveness.NO_MEANINGFUL_BUYBACK_ACTIVITY
    ),
) -> CapitalAllocationRow:
    """One capital-allocation year carrying only the fields screening reads."""
    return CapitalAllocationRow(
        fiscal_year=year,
        free_cash_flow=None,
        repurchases=None,
        dividends=None,
        sbc=None,
        diluted_share_growth=None,
        net_cash_or_debt=None,
        roic=None,
        repurchases_over_fcf=None,
        dividends_over_fcf=None,
        sbc_over_fcf=sbc_over_fcf,
        capital_returned=None,
        capital_returned_over_fcf=capital_returned_over_fcf,
        retained_fcf=None,
        buyback_effectiveness=buyback_effectiveness,
        classification=classification,
        drivers=(),
    )


def snapshot(
    year: int, classification: EconomicValueClassification
) -> EconomicValueSnapshot:
    """One annual economic-value verdict with no other signal attached."""
    return EconomicValueSnapshot(
        fiscal_year=year,
        revenue_growth=None,
        operating_margin_change=None,
        fcf_growth=None,
        fcf_margin_change=None,
        diluted_share_growth=None,
        fcf_per_share_growth=None,
        roic_change=None,
        operating_margin=None,
        fcf_margin=None,
        fcf_per_share=None,
        roic=None,
        net_cash_or_debt=None,
        classification=classification,
        drivers=(),
    )


def compounding_view(
    *,
    fcf_per_share_cagr: float | None = None,
    start: int = BASE_YEAR,
    end: int = BASE_YEAR + 4,
) -> EconomicCompoundingView:
    """One compounding view carrying only the per-share CAGR screening reads."""
    return EconomicCompoundingView(
        start_fiscal_year=start,
        end_fiscal_year=end,
        years=end - start,
        revenue_cagr=None,
        fcf_cagr=None,
        fcf_per_share_cagr=fcf_per_share_cagr,
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
        improving_count=0,
        stable_count=0,
        deteriorating_count=0,
        insufficient_count=0,
        classification=CompoundingClassification.STABLE,
        drivers=(),
    )


def summary(
    classification: OverallEconomicValueClassification, *, ticker: str = TICKER
) -> EconomicValueSummary:
    """One company-level verdict with no other signal attached."""
    return EconomicValueSummary(
        ticker=ticker,
        latest_fiscal_year=BASE_YEAR + 4,
        latest_annual_classification=EconomicValueClassification.STABLE,
        recent_compounding_classification=None,
        long_term_compounding_classification=CompoundingClassification.STABLE,
        latest_capital_allocation_classification=(
            CapitalAllocationClassification.BALANCED
        ),
        overall_economic_value_classification=classification,
        key_positive_drivers=(),
        key_watch_drivers=(),
        key_negative_drivers=(),
        latest_fcf_per_share_growth=None,
        long_term_fcf_per_share_cagr=None,
        recent_fcf_per_share_cagr=None,
        diluted_share_cagr=None,
        latest_roic=None,
        long_term_roic_change=None,
        latest_net_cash_or_debt=None,
        latest_sbc_to_fcf=None,
        latest_capital_returned_to_fcf=None,
        buyback_effectiveness=None,
    )


def evidence(
    *,
    ticker: str = TICKER,
    coverage_class: CoverageClass = CoverageClass.FULL,
    owner_economics: tuple[OwnerEconomicsRow, ...] = (),
    capital_efficiency: tuple[CapitalEfficiencyRow, ...] = (),
    snapshots: tuple[EconomicValueSnapshot, ...] = (),
    recent_compounding: EconomicCompoundingView | None = None,
    long_term_compounding: EconomicCompoundingView | None = None,
    capital_allocation: tuple[CapitalAllocationRow, ...] = (),
    economic_summary: EconomicValueSummary | None = None,
    unavailable_metrics: tuple[str, ...] = (),
    blocked_layers: tuple[str, ...] = (),
) -> ScreeningEvidence:
    """Assemble screening evidence from explicit components."""
    return ScreeningEvidence(
        ticker=ticker,
        coverage_class=coverage_class,
        owner_economics=owner_economics,
        capital_efficiency=capital_efficiency,
        snapshots=snapshots,
        recent_compounding=recent_compounding,
        long_term_compounding=long_term_compounding,
        capital_allocation=capital_allocation,
        summary=economic_summary,
        unavailable_metrics=unavailable_metrics,
        blocked_layers=blocked_layers,
    )

"""Tests for the OwnerLens Slice 2C capital-allocation interpretation layer.

Fixtures construct Feature 1 rows, Feature 2A snapshots, and reported series
directly; no SEC payloads or network access.
"""

from __future__ import annotations

from datetime import date

from owner_lens import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationDriver,
    CapitalAllocationThresholds,
    CapitalEfficiencyRow,
    EconomicValueClassification,
    EconomicValueSnapshot,
    OwnerEconomicsRow,
    build_capital_allocation_rows,
    classify_buyback_effectiveness,
)
from owner_lens.canonical import (
    CanonicalFact,
    CanonicalSeries,
    MetricStatus,
    metric_spec,
)

Eff = BuybackEffectiveness
Cls = CapitalAllocationClassification
Drv = CapitalAllocationDriver


def _obs(metric: str, value: int, year: int) -> CanonicalFact:
    return CanonicalFact(
        metric=metric,
        unit=metric_spec(metric).unit,
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year - 1, 12, 1),
        period_end=date(year, 11, 30),
        provider="test",
        provider_field="X",
        form="10-K",
        filed=date(year + 1, 1, 15),
        accession=f"acc-{year}",
        value=value,
    )


def _series(metric: str, values: dict[int, int]) -> CanonicalSeries:
    observations = tuple(_obs(metric, v, y) for y, v in sorted(values.items(), reverse=True))
    status = MetricStatus.AVAILABLE if observations else MetricStatus.STRUCTURALLY_ABSENT
    return CanonicalSeries(
        metric=metric, unit="USD", status=status, observations=observations
    )


def _empty_dividends() -> CanonicalSeries:
    return CanonicalSeries(
        metric="dividends_paid", unit="USD", status=MetricStatus.STRUCTURALLY_ABSENT
    )


def _owner(year: int, *, free_cash_flow: int | None, diluted_share_growth: float | None) -> OwnerEconomicsRow:
    return OwnerEconomicsRow(
        fiscal_year=year,
        revenue=None,
        operating_income=None,
        net_income=None,
        operating_cash_flow=None,
        capital_expenditures=None,
        diluted_shares=None,
        operating_margin=None,
        net_margin=None,
        free_cash_flow=free_cash_flow,
        fcf_margin=None,
        fcf_per_share=None,
        fcf_growth=None,
        fcf_per_share_growth=None,
        diluted_share_growth=diluted_share_growth,
    )


def _capital(year: int, *, net_cash: int | None, roic: float | None) -> CapitalEfficiencyRow:
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


def _snap(year: int, *, roic_change: float | None = None) -> EconomicValueSnapshot:
    return EconomicValueSnapshot(
        fiscal_year=year,
        revenue_growth=None,
        operating_margin_change=None,
        fcf_growth=None,
        fcf_margin_change=None,
        diluted_share_growth=None,
        fcf_per_share_growth=None,
        roic_change=roic_change,
        operating_margin=None,
        fcf_margin=None,
        fcf_per_share=None,
        roic=None,
        net_cash_or_debt=None,
        classification=EconomicValueClassification.IMPROVING,
        drivers=(),
    )


# --- User Story 4: buyback effectiveness ------------------------------------


def test_effective_buybacks() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=9_000, repurchases_over_fcf=0.9, diluted_share_growth=-0.05
        )
        is Eff.EFFECTIVE_BUYBACKS
    )


def test_partially_offset_by_dilution() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=9_000, repurchases_over_fcf=0.9, diluted_share_growth=0.0
        )
        is Eff.PARTIALLY_OFFSET_BY_DILUTION
    )


def test_ineffective_buybacks() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=9_000, repurchases_over_fcf=0.9, diluted_share_growth=0.03
        )
        is Eff.INEFFECTIVE_BUYBACKS
    )


def test_net_dilution() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=100, repurchases_over_fcf=0.02, diluted_share_growth=0.03
        )
        is Eff.NET_DILUTION
    )


def test_no_meaningful_buyback_activity() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=100, repurchases_over_fcf=0.02, diluted_share_growth=0.0
        )
        is Eff.NO_MEANINGFUL_BUYBACK_ACTIVITY
    )


def test_buyback_effectiveness_insufficient_data() -> None:
    assert (
        classify_buyback_effectiveness(
            repurchases=None, repurchases_over_fcf=None, diluted_share_growth=-0.05
        )
        is Eff.INSUFFICIENT_DATA
    )


# --- Row-building helpers ---------------------------------------------------


def _build_one_year(
    *,
    fcf: int | None,
    repo: int | None,
    sbc: int | None,
    dsg: float | None,
    net_cash: int,
    prior_net_cash: int,
    roic: float,
    roic_change: float | None = None,
    dividends: CanonicalSeries | None = None,
    thresholds: CapitalAllocationThresholds | None = None,
):
    year = 2025
    owner = [_owner(year, free_cash_flow=fcf, diluted_share_growth=dsg)]
    capital = [
        _capital(year, net_cash=net_cash, roic=roic),
        _capital(year - 1, net_cash=prior_net_cash, roic=roic),
    ]
    snaps = [_snap(year, roic_change=roic_change)]
    repurchases = _series("repurchases", {year: repo} if repo is not None else {})
    sbc_series = _series("stock_based_compensation", {year: sbc} if sbc is not None else {})
    dividends_series = dividends if dividends is not None else _empty_dividends()
    kwargs = {"thresholds": thresholds} if thresholds is not None else {}
    return build_capital_allocation_rows(
        owner, capital, snaps, repurchases, sbc_series, dividends_series, **kwargs
    )[0]


# --- User Story 3: derived metrics ------------------------------------------


def test_ratios_and_capital_returned() -> None:
    row = _build_one_year(
        fcf=10_000, repo=2_500, sbc=1_500, dsg=-0.03, net_cash=5_000,
        prior_net_cash=4_800, roic=0.30,
    )
    assert row.repurchases_over_fcf == 0.25
    assert row.sbc_over_fcf == 0.15
    assert row.capital_returned == 2_500  # no dividend program -> dividends 0
    assert row.capital_returned_over_fcf == 0.25
    assert row.retained_fcf == 7_500
    assert Drv.NO_DIVIDEND_PROGRAM in row.drivers


def test_negative_retained_fcf_preserved() -> None:
    row = _build_one_year(
        fcf=9_500, repo=11_281, sbc=1_942, dsg=-0.05, net_cash=385,
        prior_net_cash=2_258, roic=0.60,
    )
    assert row.retained_fcf == 9_500 - 11_281
    assert row.retained_fcf < 0
    assert Drv.RETAINED_FCF_NEGATIVE in row.drivers


def test_ratios_omitted_when_fcf_non_positive() -> None:
    row = _build_one_year(
        fcf=0, repo=2_500, sbc=1_500, dsg=-0.03, net_cash=5_000,
        prior_net_cash=4_800, roic=0.30,
    )
    assert row.repurchases_over_fcf is None
    assert row.sbc_over_fcf is None


# --- User Story 5: classification -------------------------------------------


def test_owner_friendly_effective_reduction_high_roic() -> None:
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=1_000, dsg=-0.05, net_cash=5_000,
        prior_net_cash=4_900, roic=0.40,
    )
    assert row.buyback_effectiveness is Eff.EFFECTIVE_BUYBACKS
    assert row.classification is Cls.OWNER_FRIENDLY
    assert Drv.SHARE_COUNT_SHRANK in row.drivers
    assert Drv.HIGH_ROIC_CONTEXT in row.drivers


def test_balanced_minimal_activity() -> None:
    row = _build_one_year(
        fcf=10_000, repo=200, sbc=500, dsg=0.0, net_cash=5_000,
        prior_net_cash=4_900, roic=0.30,
    )
    assert row.classification is Cls.BALANCED


def test_questionable_offset_buybacks_high_sbc() -> None:
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=2_000, dsg=0.0, net_cash=5_000,
        prior_net_cash=4_900, roic=0.30,
    )
    assert row.buyback_effectiveness is Eff.PARTIALLY_OFFSET_BY_DILUTION
    assert row.classification is Cls.QUESTIONABLE
    assert Drv.HIGH_SBC_BURDEN in row.drivers


def test_owner_unfriendly_dilution_and_leverage() -> None:
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=2_500, dsg=0.03, net_cash=-1_000,
        prior_net_cash=1_000, roic=0.20,
    )
    assert row.classification is Cls.OWNER_UNFRIENDLY
    assert Drv.MATERIAL_DILUTION in row.drivers


def test_classification_is_deterministic() -> None:
    kwargs = {
        "fcf": 10_000,
        "repo": 6_000,
        "sbc": 1_000,
        "dsg": -0.05,
        "net_cash": 5_000,
        "prior_net_cash": 4_900,
        "roic": 0.40,
    }
    assert _build_one_year(**kwargs).drivers == _build_one_year(**kwargs).drivers


# --- User Story 6: balance-sheet and ROIC context ---------------------------


def test_surplus_cash_drawdown_is_not_deterioration() -> None:
    # Net cash falls sharply but stays strongly net-cash positive.
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=1_000, dsg=-0.05, net_cash=400,
        prior_net_cash=5_000, roic=0.40,
    )
    assert Drv.BALANCE_SHEET_DETERIORATED not in row.drivers
    assert row.classification is Cls.OWNER_FRIENDLY


def test_deepening_net_debt_is_deterioration() -> None:
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=1_000, dsg=-0.05, net_cash=-3_000,
        prior_net_cash=-1_000, roic=0.40,
    )
    assert Drv.BALANCE_SHEET_DETERIORATED in row.drivers
    assert row.classification is Cls.QUESTIONABLE


def test_roic_context_and_direction_drivers() -> None:
    row = _build_one_year(
        fcf=10_000, repo=6_000, sbc=1_000, dsg=-0.05, net_cash=5_000,
        prior_net_cash=4_900, roic=0.10, roic_change=-0.05,
    )
    assert Drv.LOW_ROIC_CONTEXT in row.drivers
    assert Drv.ROIC_DETERIORATING in row.drivers


def test_visa_buyback_effectiveness_insufficient_but_facts_available() -> None:
    from _fixtures import visa_facts

    from owner_lens import capital_allocation_from_facts

    rows = capital_allocation_from_facts(visa_facts(), ticker="V")
    latest = rows[0]

    assert latest.classification is Cls.INSUFFICIENT_DATA
    assert latest.buyback_effectiveness is BuybackEffectiveness.INSUFFICIENT_DATA
    # Reported capital-allocation facts remain available (not fabricated).
    assert latest.repurchases is not None
    assert latest.sbc is not None
    assert latest.free_cash_flow is not None

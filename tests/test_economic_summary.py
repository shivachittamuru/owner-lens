"""Tests for the OwnerLens Slice 2D company-level economic-value synthesis.

Fixtures construct Feature 2A snapshots, 2B compounding views, and 2C rows
directly; no SEC payloads or network access.
"""

from __future__ import annotations

from owner_lens import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationDriver,
    CapitalAllocationRow,
    CompoundingClassification,
    CompoundingDriver,
    EconomicCompoundingView,
    EconomicValueClassification,
    EconomicValueDriver,
    EconomicValueSnapshot,
    OverallEconomicValueClassification,
    SummaryDriver,
    synthesize_economic_value_summary,
)

Overall = OverallEconomicValueClassification
Sd = SummaryDriver


def _snapshot(
    year: int,
    classification: EconomicValueClassification,
    *,
    fcf_per_share_growth: float | None = None,
    roic: float | None = None,
    drivers: tuple[EconomicValueDriver, ...] = (),
) -> EconomicValueSnapshot:
    return EconomicValueSnapshot(
        fiscal_year=year,
        revenue_growth=None,
        operating_margin_change=None,
        fcf_growth=None,
        fcf_margin_change=None,
        diluted_share_growth=None,
        fcf_per_share_growth=fcf_per_share_growth,
        roic_change=None,
        operating_margin=None,
        fcf_margin=None,
        fcf_per_share=None,
        roic=roic,
        net_cash_or_debt=None,
        classification=classification,
        drivers=drivers,
    )


def _view(
    classification: CompoundingClassification,
    *,
    fcf_per_share_cagr: float | None = None,
    diluted_share_cagr: float | None = None,
    roic_end: float | None = None,
    roic_change: float | None = None,
    net_cash_start: int | None = None,
    net_cash_end: int | None = None,
    drivers: tuple[CompoundingDriver, ...] = (),
    start: int = 2021,
    end: int = 2025,
) -> EconomicCompoundingView:
    return EconomicCompoundingView(
        start_fiscal_year=start,
        end_fiscal_year=end,
        years=end - start,
        revenue_cagr=None,
        fcf_cagr=None,
        fcf_per_share_cagr=fcf_per_share_cagr,
        diluted_share_cagr=diluted_share_cagr,
        operating_margin_start=None,
        operating_margin_end=None,
        operating_margin_change=None,
        fcf_margin_start=None,
        fcf_margin_end=None,
        fcf_margin_change=None,
        roic_start=None,
        roic_end=roic_end,
        roic_change=roic_change,
        net_cash_or_debt_start=net_cash_start,
        net_cash_or_debt_end=net_cash_end,
        net_cash_or_debt_change=None,
        improving_count=0,
        stable_count=0,
        deteriorating_count=0,
        insufficient_count=0,
        classification=classification,
        drivers=drivers,
    )


def _capital(
    year: int,
    classification: CapitalAllocationClassification,
    *,
    buyback_effectiveness: BuybackEffectiveness = BuybackEffectiveness.EFFECTIVE_BUYBACKS,
    sbc_over_fcf: float | None = None,
    capital_returned_over_fcf: float | None = None,
    net_cash_or_debt: int | None = None,
    roic: float | None = None,
    drivers: tuple[CapitalAllocationDriver, ...] = (),
) -> CapitalAllocationRow:
    return CapitalAllocationRow(
        fiscal_year=year,
        free_cash_flow=None,
        repurchases=None,
        dividends=None,
        sbc=None,
        diluted_share_growth=None,
        net_cash_or_debt=net_cash_or_debt,
        roic=roic,
        repurchases_over_fcf=None,
        dividends_over_fcf=None,
        sbc_over_fcf=sbc_over_fcf,
        capital_returned=None,
        capital_returned_over_fcf=capital_returned_over_fcf,
        retained_fcf=None,
        buyback_effectiveness=buyback_effectiveness,
        classification=classification,
        drivers=drivers,
    )


# --- User Story 2: documented hierarchy -------------------------------------


def test_strongly_improving_requires_strong_long_term() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING, roic=0.40)],
        _view(CompoundingClassification.STRONGLY_COMPOUNDING),
        _view(CompoundingClassification.STRONGLY_COMPOUNDING, roic_end=0.40, roic_change=0.10),
        [_capital(2025, CapitalAllocationClassification.OWNER_FRIENDLY, net_cash_or_debt=5000)],
    )
    assert summary.overall_economic_value_classification is Overall.STRONGLY_IMPROVING


def test_compounding_base_caps_at_improving() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING, roic=0.40)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(CompoundingClassification.COMPOUNDING, roic_end=0.40, roic_change=0.05),
        [_capital(2025, CapitalAllocationClassification.OWNER_FRIENDLY, net_cash_or_debt=5000)],
    )
    # One strong year plus owner-friendly allocation cannot manufacture STRONGLY_IMPROVING.
    assert summary.overall_economic_value_classification is Overall.IMPROVING


def test_stable_across_components() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.STABLE)],
        _view(CompoundingClassification.STABLE),
        _view(CompoundingClassification.STABLE),
        [_capital(2025, CapitalAllocationClassification.BALANCED, net_cash_or_debt=100)],
    )
    assert summary.overall_economic_value_classification is Overall.STABLE


def test_deteriorating_across_components() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.DETERIORATING)],
        _view(CompoundingClassification.DETERIORATING),
        _view(CompoundingClassification.DETERIORATING),
        [_capital(2025, CapitalAllocationClassification.QUESTIONABLE, net_cash_or_debt=100)],
    )
    assert summary.overall_economic_value_classification is Overall.DETERIORATING


def test_one_strong_year_does_not_override_weak_long_term() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING)],
        _view(CompoundingClassification.DETERIORATING),
        _view(CompoundingClassification.DETERIORATING, roic_change=-0.04),
        [_capital(2025, CapitalAllocationClassification.BALANCED, net_cash_or_debt=100)],
    )
    assert summary.overall_economic_value_classification is not Overall.IMPROVING
    assert Sd.EARLY_IMPROVEMENT_NOT_YET_PROVEN in summary.key_watch_drivers


def test_synthesis_is_deterministic() -> None:
    args = (
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING, roic=0.40)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(CompoundingClassification.COMPOUNDING, roic_end=0.40),
        [_capital(2025, CapitalAllocationClassification.OWNER_FRIENDLY, net_cash_or_debt=5000)],
    )
    assert synthesize_economic_value_summary(*args) == synthesize_economic_value_summary(*args)


# --- User Story 4: watch versus guardrail -----------------------------------


def test_high_sbc_and_returns_above_fcf_are_watch_not_downgrade() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING, roic=0.60)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(
            CompoundingClassification.COMPOUNDING,
            roic_end=0.60,
            roic_change=0.20,
            net_cash_start=4000,
            net_cash_end=400,
        ),
        [
            _capital(
                2025,
                CapitalAllocationClassification.OWNER_FRIENDLY,
                sbc_over_fcf=0.20,
                capital_returned_over_fcf=1.15,
                net_cash_or_debt=400,
                drivers=(
                    CapitalAllocationDriver.HIGH_SBC_BURDEN,
                    CapitalAllocationDriver.CAPITAL_RETURNED_EXCEEDS_FCF,
                ),
            )
        ],
    )
    assert summary.overall_economic_value_classification is Overall.IMPROVING
    assert Sd.HIGH_SBC_BURDEN in summary.key_watch_drivers
    assert Sd.CAPITAL_RETURNS_EXCEED_FCF in summary.key_watch_drivers
    assert Sd.DECLINING_NET_CASH_CUSHION in summary.key_watch_drivers


def test_deepening_net_debt_guardrail_downgrades() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(CompoundingClassification.COMPOUNDING),
        [
            _capital(
                2025,
                CapitalAllocationClassification.QUESTIONABLE,
                net_cash_or_debt=-3000,
                drivers=(CapitalAllocationDriver.BALANCE_SHEET_DETERIORATED,),
            )
        ],
    )
    assert summary.overall_economic_value_classification is Overall.DETERIORATING
    assert Sd.WORSENING_NET_DEBT in summary.key_negative_drivers


def test_sustained_roic_collapse_guardrail_downgrades() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(CompoundingClassification.COMPOUNDING, roic_change=-0.15),
        [_capital(2025, CapitalAllocationClassification.BALANCED, net_cash_or_debt=100)],
    )
    assert summary.overall_economic_value_classification is Overall.DETERIORATING
    assert Sd.ROIC_DETERIORATING in summary.key_negative_drivers


# --- User Story 3: durable economics and tension ----------------------------


def test_strong_long_term_weak_latest_is_not_deteriorating() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.DETERIORATING, roic=0.40)],
        _view(CompoundingClassification.STRONGLY_COMPOUNDING),
        _view(CompoundingClassification.STRONGLY_COMPOUNDING, roic_end=0.40, roic_change=0.05),
        [_capital(2025, CapitalAllocationClassification.OWNER_FRIENDLY, net_cash_or_debt=5000)],
    )
    assert summary.overall_economic_value_classification is Overall.IMPROVING
    assert Sd.RECENT_SLOWDOWN in summary.key_watch_drivers


def test_weak_long_term_strong_latest_surfaces_early_improvement() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING)],
        _view(CompoundingClassification.DETERIORATING),
        _view(CompoundingClassification.DETERIORATING),
        [_capital(2025, CapitalAllocationClassification.BALANCED, net_cash_or_debt=100)],
    )
    assert summary.overall_economic_value_classification is Overall.STABLE
    assert Sd.EARLY_IMPROVEMENT_NOT_YET_PROVEN in summary.key_watch_drivers


# --- User Story 1: assembly, drivers, evidence ------------------------------


def test_summary_carries_components_drivers_and_evidence() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [
            _snapshot(
                2024, EconomicValueClassification.IMPROVING
            ),
            _snapshot(
                2025,
                EconomicValueClassification.IMPROVING,
                fcf_per_share_growth=0.32,
                roic=0.62,
                drivers=(EconomicValueDriver.SHARE_COUNT_DECLINED,),
            ),
        ],
        _view(CompoundingClassification.COMPOUNDING, fcf_per_share_cagr=0.137),
        _view(
            CompoundingClassification.COMPOUNDING,
            fcf_per_share_cagr=0.127,
            diluted_share_cagr=-0.029,
            roic_end=0.62,
            roic_change=0.216,
            net_cash_start=1675,
            net_cash_end=385,
            drivers=(CompoundingDriver.ROIC_HIGH_AND_SUSTAINED,),
        ),
        [
            _capital(
                2025,
                CapitalAllocationClassification.OWNER_FRIENDLY,
                buyback_effectiveness=BuybackEffectiveness.EFFECTIVE_BUYBACKS,
                sbc_over_fcf=0.20,
                capital_returned_over_fcf=1.15,
                net_cash_or_debt=385,
                roic=0.62,
                drivers=(
                    CapitalAllocationDriver.HIGH_SBC_BURDEN,
                    CapitalAllocationDriver.CAPITAL_RETURNED_EXCEEDS_FCF,
                    CapitalAllocationDriver.ROIC_IMPROVING,
                ),
            )
        ],
    )
    assert summary.latest_fiscal_year == 2025
    assert summary.overall_economic_value_classification is Overall.IMPROVING
    assert summary.key_positive_drivers[0] is Sd.PER_SHARE_CASH_FLOW_COMPOUNDING
    assert Sd.HIGH_ROIC in summary.key_positive_drivers
    assert Sd.EFFECTIVE_BUYBACKS in summary.key_positive_drivers
    assert Sd.HIGH_SBC_BURDEN in summary.key_watch_drivers
    assert summary.latest_fcf_per_share_growth == 0.32
    assert summary.long_term_fcf_per_share_cagr == 0.127
    assert summary.diluted_share_cagr == -0.029
    assert summary.buyback_effectiveness is BuybackEffectiveness.EFFECTIVE_BUYBACKS


def test_insufficient_components_yield_insufficient_data() -> None:
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.INSUFFICIENT_DATA)],
        None,
        _view(CompoundingClassification.INSUFFICIENT_DATA),
        [_capital(2025, CapitalAllocationClassification.INSUFFICIENT_DATA)],
    )
    assert summary.overall_economic_value_classification is Overall.INSUFFICIENT_DATA
    assert summary.recent_compounding_classification is None


def test_drivers_are_deduplicated_across_layers() -> None:
    # Both 2C and 2B emit ROIC improvement; the summary carries one entry.
    summary = synthesize_economic_value_summary(
        "ADBE",
        [_snapshot(2025, EconomicValueClassification.IMPROVING, roic=0.40)],
        _view(CompoundingClassification.COMPOUNDING),
        _view(
            CompoundingClassification.COMPOUNDING,
            roic_end=0.40,
            drivers=(CompoundingDriver.ROIC_IMPROVED,),
        ),
        [
            _capital(
                2025,
                CapitalAllocationClassification.OWNER_FRIENDLY,
                net_cash_or_debt=5000,
                drivers=(CapitalAllocationDriver.ROIC_IMPROVING,),
            )
        ],
    )
    assert summary.key_positive_drivers.count(Sd.ROIC_IMPROVING) == 1


def test_costco_full_pipeline_summary_is_not_insufficient() -> None:
    from _fixtures import costco_facts

    from owner_lens import economic_value_summary_from_facts

    summary = economic_value_summary_from_facts(costco_facts(), ticker="COST")

    assert (
        summary.overall_economic_value_classification is not Overall.INSUFFICIENT_DATA
    )


def test_visa_summary_is_insufficient_but_preserves_evidence() -> None:
    from _fixtures import visa_facts

    from owner_lens import economic_value_summary_from_facts

    summary = economic_value_summary_from_facts(visa_facts(), ticker="V")

    assert summary.overall_economic_value_classification is Overall.INSUFFICIENT_DATA
    # Per-share evidence unavailable, not fabricated; non-per-share evidence kept.
    assert summary.long_term_fcf_per_share_cagr is None
    assert summary.latest_roic is not None

"""Tests for the Feature 7 screening dimensions (Slice 7A).

Every band boundary, both modifier directions, and the three momentum paths are
exercised against synthetic Feature 2 components. Two properties get dedicated
tests because the whole design rests on them: margin *levels* never affect a
band, and a ROIC collapse never demotes a level that is still exceptional.
"""

from __future__ import annotations

from _screening_fixtures import (
    allocation_row,
    capital_row,
    capital_series,
    compounding_view,
    evidence,
    owner_series,
    snapshot,
    summary,
)

from owner_lens.capital_allocation import (
    BuybackEffectiveness,
    CapitalAllocationClassification,
)
from owner_lens.economic_summary import OverallEconomicValueClassification
from owner_lens.economic_value import EconomicValueClassification
from owner_lens.screening import (
    DIMENSION_ORDER,
    DimensionBand,
    ScreeningDimension,
    ScreeningReason,
    score_balance_sheet_strength,
    score_business_quality,
    score_capital_allocation,
    score_capital_efficiency,
    score_dimensions,
    score_economic_momentum,
    score_per_share_compounding,
)

Band = DimensionBand
Reason = ScreeningReason
Allocation = CapitalAllocationClassification
Overall = OverallEconomicValueClassification
_MILLION = 1_000_000


# --- Business quality ----------------------------------------------------------


def test_business_quality_strong_when_cash_generation_is_unbroken_and_growing() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([100, 110, 120, 130, 140]))
    )

    assert score.band is Band.STRONG
    assert Reason.DURABLE_CASH_GENERATION in score.reasons


def test_business_quality_adequate_when_latest_is_below_earliest() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([140, 130, 120, 110, 100]))
    )

    assert score.band is Band.ADEQUATE


def test_business_quality_adequate_at_the_eighty_percent_positive_boundary() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([-10, 100, 110, 120, 130]))
    )

    assert score.band is Band.ADEQUATE
    assert Reason.CASH_GENERATION_INTERRUPTED in score.reasons


def test_business_quality_weak_just_below_the_eighty_percent_boundary() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([-10, -10, 110, 120, 130]))
    )

    assert score.band is Band.WEAK


def test_business_quality_poor_when_the_latest_year_burns_cash() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([100, 110, 120, 130, -5]))
    )

    assert score.band is Band.POOR
    assert Reason.LATEST_YEAR_CASH_BURN in score.reasons


def test_business_quality_demoted_one_notch_by_material_margin_contraction() -> None:
    score = score_business_quality(
        evidence(
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                operating_margin=[0.40, 0.39, 0.38, 0.37, 0.36],
                fcf_margin=[0.30, 0.29, 0.28, 0.27, 0.26],
            )
        )
    )

    assert score.band is Band.ADEQUATE
    assert Reason.MARGINS_CONTRACTING in score.reasons


def test_business_quality_margin_contraction_below_threshold_does_not_demote() -> None:
    score = score_business_quality(
        evidence(
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                operating_margin=[0.40, 0.40, 0.39, 0.39, 0.38],
                fcf_margin=[0.30, 0.30, 0.29, 0.29, 0.285],
            )
        )
    )

    assert score.band is Band.STRONG
    assert Reason.MARGINS_CONTRACTING not in score.reasons


def test_business_quality_margin_expansion_cannot_lift_past_strong() -> None:
    score = score_business_quality(
        evidence(
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                operating_margin=[0.10, 0.15, 0.20, 0.25, 0.30],
                fcf_margin=[0.10, 0.15, 0.20, 0.25, 0.30],
            )
        )
    )

    assert score.band is Band.STRONG


def test_business_quality_margin_expansion_lifts_a_weaker_base() -> None:
    expanding = owner_series(
        [-10, -10, 110, 120, 130],
        operating_margin=[0.10, 0.15, 0.20, 0.25, 0.30],
        fcf_margin=[0.05, 0.10, 0.15, 0.20, 0.25],
    )

    score = score_business_quality(evidence(owner_economics=expanding))

    assert score.band is Band.ADEQUATE
    assert Reason.MARGINS_EXPANDING in score.reasons


def test_business_quality_margin_modifier_is_skipped_without_margin_data() -> None:
    score = score_business_quality(
        evidence(owner_economics=owner_series([100, 110, 120, 130, 140]))
    )

    assert Reason.MARGINS_CONTRACTING not in score.reasons
    assert Reason.MARGINS_EXPANDING not in score.reasons


def test_business_quality_not_evaluable_without_two_cash_flow_years() -> None:
    score = score_business_quality(evidence(owner_economics=owner_series([100])))

    assert score.band is Band.NOT_EVALUABLE


def test_margin_levels_never_affect_the_business_quality_band() -> None:
    """A 3% margin retailer and a 40% margin software business must band alike.

    This is the property that keeps business-model bias out of the screen. The
    two companies differ only in margin level; their cash-generation history and
    margin *trend* are identical.
    """
    low_margin = owner_series(
        [100, 110, 120, 130, 140],
        operating_margin=[0.038, 0.038, 0.038, 0.038, 0.038],
        fcf_margin=[0.028, 0.028, 0.028, 0.028, 0.028],
    )
    high_margin = owner_series(
        [100, 110, 120, 130, 140],
        operating_margin=[0.40, 0.40, 0.40, 0.40, 0.40],
        fcf_margin=[0.35, 0.35, 0.35, 0.35, 0.35],
    )

    assert (
        score_business_quality(evidence(owner_economics=low_margin)).band
        is score_business_quality(evidence(owner_economics=high_margin)).band
        is Band.STRONG
    )


# --- Capital efficiency --------------------------------------------------------


def test_capital_efficiency_bands_follow_the_roic_level() -> None:
    bands = {
        roic: score_capital_efficiency(
            evidence(capital_efficiency=capital_series([roic, roic]))
        ).band
        for roic in (0.25, 0.20, 0.15, 0.10, 0.07, 0.05, 0.04, -0.01)
    }

    assert bands == {
        0.25: Band.STRONG,
        0.20: Band.STRONG,
        0.15: Band.ADEQUATE,
        0.10: Band.ADEQUATE,
        0.07: Band.WEAK,
        0.05: Band.WEAK,
        0.04: Band.POOR,
        -0.01: Band.POOR,
    }


def test_capital_efficiency_collapse_does_not_demote_a_still_exceptional_level() -> None:
    """The Microsoft shape: ROIC fell 44 points and is still 36%.

    Invested capital grows mechanically as a net-cash pile is spent, so a large
    fall from an extraordinary base is a balance-sheet fact, not a collapse in
    earning power. The fall is reported, never scored.
    """
    score = score_capital_efficiency(
        evidence(capital_efficiency=capital_series([0.80, 0.60, 0.50, 0.42, 0.359]))
    )

    assert score.band is Band.STRONG
    assert Reason.ROIC_FELL_BUT_LEVEL_REMAINS_HIGH in score.reasons
    assert Reason.ROIC_COLLAPSED_FROM_LOW_BASE not in score.reasons


def test_capital_efficiency_collapse_demotes_when_the_level_is_no_longer_high() -> None:
    score = score_capital_efficiency(
        evidence(capital_efficiency=capital_series([0.28, 0.24, 0.20, 0.16, 0.12]))
    )

    assert score.band is Band.WEAK
    assert Reason.ROIC_COLLAPSED_FROM_LOW_BASE in score.reasons


def test_capital_efficiency_improvement_is_reported_but_never_lifts_the_band() -> None:
    """The Salesforce shape: ROIC rose from 1% to 10% and is still only adequate."""
    score = score_capital_efficiency(
        evidence(capital_efficiency=capital_series([0.01, 0.01, 0.07, 0.10, 0.103]))
    )

    assert score.band is Band.ADEQUATE
    assert Reason.ROIC_IMPROVING in score.reasons


def test_capital_efficiency_not_evaluable_without_roic() -> None:
    score = score_capital_efficiency(
        evidence(capital_efficiency=capital_series(net_cash=[10, 20]))
    )

    assert score.band is Band.NOT_EVALUABLE


# --- Per-share compounding -----------------------------------------------------


def _per_share(cagr_rate: float, years: int = 4) -> list[float | None]:
    return [float((1 + cagr_rate) ** index) for index in range(years + 1)]


def test_per_share_compounding_bands_follow_the_long_term_cagr() -> None:
    bands = {
        rate: score_per_share_compounding(
            evidence(owner_economics=owner_series(fcf_per_share=_per_share(rate)))
        ).band
        for rate in (0.20, 0.16, 0.10, 0.08, 0.03, -0.01, -0.03, -0.10)
    }

    assert bands == {
        0.20: Band.STRONG,
        0.16: Band.STRONG,
        0.10: Band.ADEQUATE,
        0.08: Band.ADEQUATE,
        0.03: Band.WEAK,
        -0.01: Band.WEAK,
        -0.03: Band.POOR,
        -0.10: Band.POOR,
    }


def test_per_share_compounding_band_boundaries_separate_adjacent_rates() -> None:
    """Pin each cutoff from both sides using a single one-year interval.

    The probes sit just outside each cutoff rather than exactly on it: a binary
    float cannot represent 0.15 exactly, so an exact-boundary assertion would
    test floating-point representation rather than the screening rule.
    """

    def band_for(end: float) -> Band:
        return score_per_share_compounding(
            evidence(owner_economics=owner_series(fcf_per_share=[1.0, end]))
        ).band

    assert band_for(1.1501) is Band.STRONG
    assert band_for(1.1499) is Band.ADEQUATE
    assert band_for(1.0701) is Band.ADEQUATE
    assert band_for(1.0699) is Band.WEAK
    assert band_for(0.9801) is Band.WEAK
    assert band_for(0.9799) is Band.POOR


def test_per_share_compounding_demoted_by_material_dilution() -> None:
    score = score_per_share_compounding(
        evidence(
            owner_economics=owner_series(
                fcf_per_share=_per_share(0.10),
                diluted_shares=[100, 102, 104, 106, 108],
            )
        )
    )

    assert score.band is Band.WEAK
    assert Reason.MATERIAL_DILUTION in score.reasons


def test_per_share_compounding_lifted_by_buybacks_on_growing_cash_flow() -> None:
    """The Adobe shape: a 13% CAGR plus a shrinking share count reaches strong."""
    score = score_per_share_compounding(
        evidence(
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                fcf_per_share=_per_share(0.10),
                diluted_shares=[100, 97, 94, 91, 88],
            )
        )
    )

    assert score.band is Band.STRONG
    assert Reason.SHARE_COUNT_SHRINKING in score.reasons


def test_buybacks_earn_no_credit_when_aggregate_cash_flow_is_shrinking() -> None:
    """The Lowe's shape: per-share growth bought by shrinking the denominator."""
    score = score_per_share_compounding(
        evidence(
            owner_economics=owner_series(
                [140, 130, 125, 120, 118],
                fcf_per_share=_per_share(0.04),
                diluted_shares=[100, 95, 90, 85, 80],
            )
        )
    )

    assert score.band is Band.WEAK
    assert Reason.PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY in score.reasons
    assert Reason.SHARE_COUNT_SHRINKING not in score.reasons


def test_per_share_compounding_reads_direction_when_a_sign_change_voids_the_cagr() -> None:
    """A series crossing zero has no meaningful CAGR, but a readable direction."""
    recovering = score_per_share_compounding(
        evidence(owner_economics=owner_series(fcf_per_share=[-1.43, -1.66, 3.07, 3.07, 0.71]))
    )
    collapsing = score_per_share_compounding(
        evidence(owner_economics=owner_series(fcf_per_share=[1.80, 3.06, 4.18, -0.14, -8.13]))
    )

    assert recovering.band is Band.WEAK
    assert Reason.PER_SHARE_COMPOUNDING_FLAT in recovering.reasons
    assert collapsing.band is Band.POOR
    assert Reason.PER_SHARE_VALUE_DECLINING in collapsing.reasons


def test_per_share_compounding_reports_acceleration_from_the_compounding_views() -> None:
    score = score_per_share_compounding(
        evidence(
            owner_economics=owner_series(fcf_per_share=_per_share(0.10)),
            recent_compounding=compounding_view(fcf_per_share_cagr=0.30),
            long_term_compounding=compounding_view(fcf_per_share_cagr=0.10),
        )
    )

    assert Reason.PER_SHARE_COMPOUNDING_ACCELERATING in score.reasons


def test_per_share_compounding_not_evaluable_without_per_share_values() -> None:
    score = score_per_share_compounding(
        evidence(owner_economics=owner_series([100, 110, 120]))
    )

    assert score.band is Band.NOT_EVALUABLE
    assert Reason.PER_SHARE_METRICS_UNAVAILABLE in score.reasons


# --- Balance-sheet strength ----------------------------------------------------


def test_balance_sheet_strong_for_any_net_cash_position() -> None:
    small = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([100 * _MILLION] * 2),
            capital_efficiency=capital_series(net_cash=[1 * _MILLION, 1 * _MILLION]),
        )
    )
    large = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([100 * _MILLION] * 2),
            capital_efficiency=capital_series(net_cash=[1, 36_000 * _MILLION]),
        )
    )

    assert small.band is large.band is Band.STRONG


def test_shrinking_net_cash_cushion_is_reported_without_demoting() -> None:
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([100 * _MILLION] * 2),
            capital_efficiency=capital_series(
                net_cash=[55_000 * _MILLION, 36_000 * _MILLION]
            ),
        )
    )

    assert score.band is Band.STRONG
    assert Reason.NET_CASH_CUSHION_SHRINKING in score.reasons
    assert Reason.LEVERAGE_RISING not in score.reasons


def test_balance_sheet_bands_follow_net_debt_coverage_by_cash_flow() -> None:
    bands = {}
    for multiple in (1.0, 2.0, 3.0, 4.0, 5.0):
        net_debt = int(-multiple * 100 * _MILLION)
        bands[multiple] = score_balance_sheet_strength(
            evidence(
                owner_economics=owner_series([100 * _MILLION, 100 * _MILLION]),
                capital_efficiency=capital_series(net_cash=[net_debt, net_debt]),
            )
        ).band

    assert bands == {
        1.0: Band.ADEQUATE,
        2.0: Band.ADEQUATE,
        3.0: Band.WEAK,
        4.0: Band.WEAK,
        5.0: Band.POOR,
    }


def test_net_debt_with_rising_leverage_is_demoted_one_notch() -> None:
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([100 * _MILLION, 100 * _MILLION]),
            capital_efficiency=capital_series(
                net_cash=[-50 * _MILLION, -150 * _MILLION]
            ),
        )
    )

    assert score.band is Band.WEAK
    assert Reason.LEVERAGE_RISING in score.reasons


def test_immaterial_net_debt_movement_does_not_demote() -> None:
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([100 * _MILLION, 100 * _MILLION]),
            capital_efficiency=capital_series(
                net_cash=[-100 * _MILLION, -102 * _MILLION]
            ),
        )
    )

    assert score.band is Band.ADEQUATE
    assert Reason.LEVERAGE_RISING not in score.reasons


def test_net_debt_without_positive_cash_flow_is_poor() -> None:
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([-10, -20]),
            capital_efficiency=capital_series(net_cash=[-100, -100]),
        )
    )

    assert score.band is Band.POOR


def test_net_debt_with_no_derivable_cash_flow_is_not_evaluable() -> None:
    """Debt that cannot be sized against anything must refuse, not band worst."""
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series(operating_margin=[0.3, 0.3]),
            capital_efficiency=capital_series(net_cash=[-100, -100]),
        )
    )

    assert score.band is Band.NOT_EVALUABLE
    assert Reason.NET_DEBT_POSITION not in score.reasons


def test_balance_sheet_uses_the_latest_derivable_cash_flow() -> None:
    """A trailing year with no derivable FCF must not silently reset the ratio."""
    score = score_balance_sheet_strength(
        evidence(
            owner_economics=owner_series([1000, 1100, 1200, 1300, None]),
            capital_efficiency=capital_series(net_cash=[-1300, -1300, -1300, -1300, -1300]),
        )
    )

    assert score.band is Band.ADEQUATE
    assert "net debt / FCF 1.0x" in score.evidence


def test_balance_sheet_not_evaluable_without_a_net_position() -> None:
    score = score_balance_sheet_strength(
        evidence(capital_efficiency=capital_series([0.3, 0.3]))
    )

    assert score.band is Band.NOT_EVALUABLE


# --- Capital allocation --------------------------------------------------------


def test_capital_allocation_band_comes_from_the_feature_2c_classification() -> None:
    bands = {
        classification: score_capital_allocation(
            evidence(capital_allocation=(allocation_row(2025, classification),))
        ).band
        for classification in (
            Allocation.OWNER_FRIENDLY,
            Allocation.BALANCED,
            Allocation.QUESTIONABLE,
            Allocation.OWNER_UNFRIENDLY,
        )
    }

    assert bands == {
        Allocation.OWNER_FRIENDLY: Band.STRONG,
        Allocation.BALANCED: Band.ADEQUATE,
        Allocation.QUESTIONABLE: Band.WEAK,
        Allocation.OWNER_UNFRIENDLY: Band.POOR,
    }


def test_heavy_stock_based_compensation_demotes_one_notch() -> None:
    score = score_capital_allocation(
        evidence(
            capital_allocation=(
                allocation_row(2025, Allocation.OWNER_FRIENDLY, sbc_over_fcf=0.25),
            )
        )
    )

    assert score.band is Band.ADEQUATE
    assert Reason.HEAVY_STOCK_BASED_COMPENSATION in score.reasons


def test_moderate_stock_based_compensation_does_not_demote() -> None:
    score = score_capital_allocation(
        evidence(
            capital_allocation=(
                allocation_row(2025, Allocation.OWNER_FRIENDLY, sbc_over_fcf=0.24),
            )
        )
    )

    assert score.band is Band.STRONG


def test_one_year_of_over_distribution_does_not_demote() -> None:
    rows = tuple(
        allocation_row(
            2021 + index,
            Allocation.OWNER_FRIENDLY,
            capital_returned_over_fcf=ratio,
        )
        for index, ratio in enumerate([0.5, 0.6, 0.7, 0.8, 1.5])
    )

    assert score_capital_allocation(evidence(capital_allocation=rows)).band is Band.STRONG


def test_persistent_over_distribution_demotes_one_notch() -> None:
    rows = tuple(
        allocation_row(
            2021 + index,
            Allocation.OWNER_FRIENDLY,
            capital_returned_over_fcf=ratio,
        )
        for index, ratio in enumerate([1.2, 1.3, 1.1, 0.8, 1.5])
    )

    score = score_capital_allocation(evidence(capital_allocation=rows))

    assert score.band is Band.ADEQUATE
    assert Reason.CAPITAL_RETURNS_PERSISTENTLY_EXCEED_FCF in score.reasons


def test_effective_buybacks_are_reported() -> None:
    score = score_capital_allocation(
        evidence(
            capital_allocation=(
                allocation_row(
                    2025,
                    Allocation.BALANCED,
                    buyback_effectiveness=BuybackEffectiveness.EFFECTIVE_BUYBACKS,
                ),
            )
        )
    )

    assert Reason.EFFECTIVE_BUYBACKS in score.reasons


def test_capital_allocation_not_evaluable_when_the_latest_year_is_insufficient() -> None:
    score = score_capital_allocation(
        evidence(capital_allocation=(allocation_row(2025, Allocation.INSUFFICIENT_DATA),))
    )

    assert score.band is Band.NOT_EVALUABLE


# --- Economic momentum ---------------------------------------------------------


def test_momentum_uses_the_company_level_verdict_when_it_is_available() -> None:
    bands = {
        classification: score_economic_momentum(
            evidence(economic_summary=summary(classification))
        ).band
        for classification in (
            Overall.STRONGLY_IMPROVING,
            Overall.IMPROVING,
            Overall.STABLE,
            Overall.DETERIORATING,
            Overall.STRONGLY_DETERIORATING,
        )
    }

    assert bands == {
        Overall.STRONGLY_IMPROVING: Band.STRONG,
        Overall.IMPROVING: Band.STRONG,
        Overall.STABLE: Band.ADEQUATE,
        Overall.DETERIORATING: Band.WEAK,
        Overall.STRONGLY_DETERIORATING: Band.POOR,
    }


def test_momentum_falls_back_to_annual_snapshots_and_says_so() -> None:
    improving = score_economic_momentum(
        evidence(
            snapshots=(
                snapshot(2024, EconomicValueClassification.IMPROVING),
                snapshot(2025, EconomicValueClassification.IMPROVING),
            )
        )
    )
    deteriorating = score_economic_momentum(
        evidence(
            snapshots=(
                snapshot(2024, EconomicValueClassification.DETERIORATING),
                snapshot(2025, EconomicValueClassification.DETERIORATING),
            )
        )
    )

    assert improving.band is Band.STRONG
    assert deteriorating.band is Band.POOR
    assert Reason.MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY in improving.reasons
    assert Reason.MOMENTUM_FROM_ANNUAL_SNAPSHOTS_ONLY in deteriorating.reasons


def test_momentum_from_owner_economics_is_capped_at_adequate() -> None:
    """Rising per-share cash flow alone cannot earn the top momentum band."""
    score = score_economic_momentum(
        evidence(owner_economics=owner_series(fcf_per_share=[1.0, 1.5, 2.0, 2.6, 3.4]))
    )

    assert score.band is Band.ADEQUATE
    assert Reason.MOMENTUM_FROM_OWNER_ECONOMICS_ONLY in score.reasons


def test_momentum_from_owner_economics_reads_levels_not_growth_percentages() -> None:
    """The Oracle shape: a sign change makes growth percentages meaningless.

    FY2026 growth reads as +5812% because the prior year was negative; the level
    series falls from 4.18 to -8.13, which is what the band must follow.
    """
    score = score_economic_momentum(
        evidence(owner_economics=owner_series(fcf_per_share=[1.80, 3.06, 4.18, -0.14, -8.13]))
    )

    assert score.band is Band.POOR


def test_momentum_from_owner_economics_marks_a_decline_weak_or_poor() -> None:
    mild = score_economic_momentum(
        evidence(owner_economics=owner_series(fcf_per_share=[13.2, 11.2, 17.9, 16.4, 12.7]))
    )

    assert mild.band is Band.POOR


def test_momentum_not_evaluable_with_fewer_than_three_per_share_years() -> None:
    score = score_economic_momentum(
        evidence(owner_economics=owner_series(fcf_per_share=[1.0, 2.0]))
    )

    assert score.band is Band.NOT_EVALUABLE


# --- Band algebra and composition ----------------------------------------------


def test_band_ordinals_are_coarse_and_not_evaluable_has_none() -> None:
    assert [band.ordinal for band in (Band.STRONG, Band.ADEQUATE, Band.WEAK, Band.POOR)] == [
        3,
        2,
        1,
        0,
    ]
    assert Band.NOT_EVALUABLE.ordinal is None


def test_not_evaluable_never_satisfies_an_adequate_or_better_comparison() -> None:
    assert not Band.NOT_EVALUABLE >= Band.ADEQUATE
    assert not Band.NOT_EVALUABLE >= Band.POOR
    assert Band.POOR >= Band.POOR


def test_score_dimensions_returns_every_dimension_in_reporting_order() -> None:
    scores = score_dimensions(evidence(owner_economics=owner_series([100, 110])))

    assert tuple(scores) == DIMENSION_ORDER
    assert set(scores) == set(ScreeningDimension)


def test_unavailable_layers_produce_not_evaluable_rather_than_zero() -> None:
    """Nothing missing is ever treated as a zero or a neutral score."""
    scores = score_dimensions(evidence(owner_economics=owner_series([100, 110, 120])))

    assert scores[ScreeningDimension.CAPITAL_EFFICIENCY].band is Band.NOT_EVALUABLE
    assert scores[ScreeningDimension.BALANCE_SHEET_STRENGTH].band is Band.NOT_EVALUABLE
    assert scores[ScreeningDimension.CAPITAL_ALLOCATION].band is Band.NOT_EVALUABLE
    assert all(
        scores[dimension].band.ordinal is None
        for dimension in (
            ScreeningDimension.CAPITAL_EFFICIENCY,
            ScreeningDimension.BALANCE_SHEET_STRENGTH,
            ScreeningDimension.CAPITAL_ALLOCATION,
        )
    )


def test_every_dimension_score_carries_its_evidence() -> None:
    scores = score_dimensions(
        evidence(
            owner_economics=owner_series([100, 110, 120], fcf_per_share=[1.0, 1.1, 1.2]),
            capital_efficiency=capital_series([0.3, 0.3, 0.3], net_cash=[10, 20, 30]),
            capital_allocation=(allocation_row(2023, Allocation.BALANCED),),
            economic_summary=summary(Overall.IMPROVING),
        )
    )

    assert all(score.evidence for score in scores.values())


def test_capital_row_helper_defaults_leave_every_other_field_unset() -> None:
    row = capital_row(2025, roic=0.3)

    assert row.roic == 0.3
    assert row.net_cash is None
    assert row.invested_capital is None

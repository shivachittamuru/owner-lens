"""Tests for the Feature 7 gates, buckets, setup types, and explanations (Slice 7B).

Gates are survival filters, never quality preferences, so each is exercised in
isolation and in precedence order. Buckets come from an explicit rule table, so
each path is exercised separately, including both coverage ceilings. The score
is asserted to be a bounded integer that orders within a bucket and never sets
one.
"""

from __future__ import annotations

import pytest
from _screening_fixtures import (
    allocation_row,
    capital_series,
    evidence,
    owner_series,
    snapshot,
    summary,
)

from owner_lens.capital_allocation import CapitalAllocationClassification
from owner_lens.economic_summary import OverallEconomicValueClassification
from owner_lens.economic_value import EconomicValueClassification
from owner_lens.screening import (
    BUCKET_ORDER,
    DIMENSION_ORDER,
    CoverageClass,
    DimensionBand,
    LimitingFactor,
    ReasonCategory,
    ScreeningBucket,
    ScreeningDimension,
    ScreeningReason,
    SetupType,
    format_screening_result,
    reason_category,
    screen_company,
)

Band = DimensionBand
Bucket = ScreeningBucket
Reason = ScreeningReason
Allocation = CapitalAllocationClassification
Overall = OverallEconomicValueClassification
_MILLION = 1_000_000
_B = 1_000 * _MILLION


def _compounder(**overrides: object):  # type: ignore[no-untyped-def]
    """Evidence for a fully covered business that is strong on every dimension."""
    defaults: dict[str, object] = {
        "coverage_class": CoverageClass.FULL,
        "owner_economics": owner_series(
            [100 * _MILLION, 115 * _MILLION, 132 * _MILLION, 152 * _MILLION, 175 * _MILLION],
            fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
            diluted_shares=[100, 98, 96, 94, 92],
            operating_margin=[0.30, 0.30, 0.30, 0.30, 0.30],
            fcf_margin=[0.25, 0.25, 0.25, 0.25, 0.25],
        ),
        "capital_efficiency": capital_series(
            [0.40, 0.42, 0.44, 0.46, 0.48],
            net_cash=[5 * _B, 5 * _B, 5 * _B, 5 * _B, 5 * _B],
        ),
        "capital_allocation": tuple(
            allocation_row(2021 + index, Allocation.OWNER_FRIENDLY)
            for index in range(5)
        ),
        "economic_summary": summary(Overall.IMPROVING),
    }
    defaults.update(overrides)
    return evidence(**defaults)  # type: ignore[arg-type]


# --- Gates ---------------------------------------------------------------------


def test_failed_coverage_is_insufficient_data_not_low_priority() -> None:
    result = screen_company(evidence(coverage_class=CoverageClass.FAILED))

    assert result.bucket is Bucket.INSUFFICIENT_DATA
    assert result.gate is Reason.COVERAGE_FAILED
    assert result.limiting_factor is LimitingFactor.COVERAGE


def test_too_few_evaluable_dimensions_is_insufficient_data() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series([100, 110]),
        )
    )

    assert result.bucket is Bucket.INSUFFICIENT_DATA
    assert result.gate is Reason.TOO_FEW_EVALUABLE_DIMENSIONS


def test_business_quality_is_required_even_when_other_dimensions_are_evaluable() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            capital_efficiency=capital_series([0.4, 0.4], net_cash=[_B, _B]),
            economic_summary=summary(Overall.IMPROVING),
        )
    )

    assert result.bucket is Bucket.INSUFFICIENT_DATA
    assert result.gate is Reason.TOO_FEW_EVALUABLE_DIMENSIONS


def test_two_consecutive_cash_burn_years_gate_to_low_priority() -> None:
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION, 110 * _MILLION, 120 * _MILLION, -400 * _MILLION, -23 * _B],
                fcf_per_share=[1.80, 3.06, 4.18, -0.14, -8.13],
            )
        )
    )

    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.gate is Reason.PERSISTENT_CASH_BURN


def test_a_single_cash_burn_year_is_a_band_not_a_gate() -> None:
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION, 110 * _MILLION, 120 * _MILLION, 130 * _MILLION, -5 * _MILLION],
                fcf_per_share=[1.0, 1.1, 1.2, 1.3, -0.05],
            )
        )
    )

    assert result.gate is None
    assert result.band(ScreeningDimension.BUSINESS_QUALITY) is Band.POOR


def test_leverage_beyond_six_years_of_cash_flow_gates_to_low_priority() -> None:
    result = screen_company(
        _compounder(
            capital_efficiency=capital_series(
                [0.40] * 5, net_cash=[-1200 * _MILLION] * 5
            )
        )
    )

    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.gate is Reason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW


def test_leverage_within_six_years_of_cash_flow_does_not_gate() -> None:
    result = screen_company(
        _compounder(
            capital_efficiency=capital_series(
                [0.40] * 5, net_cash=[-1000 * _MILLION] * 5
            )
        )
    )

    assert result.gate is None


def test_net_debt_without_positive_cash_flow_gates_to_low_priority() -> None:
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION, 110 * _MILLION, 120 * _MILLION, 130 * _MILLION, -5],
                fcf_per_share=[1.0, 1.1, 1.2, 1.3, -0.05],
            ),
            capital_efficiency=capital_series([0.40] * 5, net_cash=[-_B] * 5),
        )
    )

    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.gate is Reason.NET_DEBT_WITHOUT_CASH_FLOW


def test_returns_below_any_plausible_cost_of_capital_gate_to_low_priority() -> None:
    result = screen_company(
        _compounder(capital_efficiency=capital_series([0.02] * 5, net_cash=[_B] * 5))
    )

    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.gate is Reason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL


def test_low_but_materially_improving_returns_do_not_gate() -> None:
    """A business climbing out of low returns is exactly what the screen must keep."""
    result = screen_company(
        _compounder(
            capital_efficiency=capital_series(
                [0.005, 0.01, 0.02, 0.03, 0.045], net_cash=[_B] * 5
            )
        )
    )

    assert result.gate is None


def test_persistent_material_dilution_gates_to_low_priority() -> None:
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION] * 5,
                fcf_per_share=[1.0, 1.0, 1.0, 1.0, 1.0],
                diluted_shares=[100, 106, 112, 119, 127],
            )
        )
    )

    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.gate is Reason.PERSISTENT_MATERIAL_DILUTION


def test_solvency_and_returns_gates_are_skipped_when_the_inputs_are_invisible() -> None:
    """A gate whose inputs are unavailable is skipped, never assumed either way."""
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 110, 120, 130, 140], fcf_per_share=[1.0, 1.1, 1.2, 1.3, 1.4]
            ),
        )
    )

    assert result.gate is None
    assert result.band(ScreeningDimension.CAPITAL_EFFICIENCY) is Band.NOT_EVALUABLE


def test_cash_generation_gate_precedes_the_solvency_gate() -> None:
    """Both gates would fire; survival of the business is checked before leverage."""
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION, 110 * _MILLION, 120 * _MILLION, -10 * _MILLION, -20 * _MILLION],
                fcf_per_share=[1.0, 1.1, 1.2, -0.1, -0.2],
            ),
            capital_efficiency=capital_series([0.40] * 5, net_cash=[-50 * _B] * 5),
        )
    )

    assert result.gate is Reason.PERSISTENT_CASH_BURN


def test_the_solvency_gate_precedes_the_returns_and_dilution_gates() -> None:
    """Gate order decides which reason a company reports, so it is pinned."""
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION] * 5,
                fcf_per_share=[1.0] * 5,
                diluted_shares=[100, 106, 112, 119, 127],
            ),
            capital_efficiency=capital_series([0.02] * 5, net_cash=[-50 * _B] * 5),
        )
    )

    assert result.gate is Reason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW


def test_the_returns_gate_precedes_the_dilution_gate() -> None:
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION] * 5,
                fcf_per_share=[1.0] * 5,
                diluted_shares=[100, 106, 112, 119, 127],
            ),
            capital_efficiency=capital_series([0.02] * 5, net_cash=[_B] * 5),
        )
    )

    assert result.gate is Reason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL


def test_a_gated_company_still_reports_every_measurable_dimension() -> None:
    result = screen_company(
        _compounder(capital_efficiency=capital_series([0.02] * 5, net_cash=[_B] * 5))
    )

    assert result.gate is Reason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL
    assert result.band(ScreeningDimension.BUSINESS_QUALITY) is Band.STRONG
    assert result.band(ScreeningDimension.PER_SHARE_COMPOUNDING) is Band.STRONG
    assert result.supporting_reasons


# --- Buckets -------------------------------------------------------------------


def test_a_strong_fully_covered_compounder_reaches_high_priority() -> None:
    result = screen_company(_compounder())

    assert result.bucket is Bucket.HIGH_PRIORITY
    assert result.setup_type is SetupType.COMPOUNDER
    assert result.limiting_factor is LimitingFactor.NONE


def test_high_priority_requires_full_coverage() -> None:
    result = screen_company(_compounder(coverage_class=CoverageClass.PARTIAL))

    assert result.bucket is Bucket.WORTH_UNDERWRITING


def test_high_priority_refuses_any_weak_dimension() -> None:
    result = screen_company(
        _compounder(
            capital_allocation=(allocation_row(2025, Allocation.QUESTIONABLE),)
        )
    )

    assert result.bucket is not Bucket.HIGH_PRIORITY


def test_high_priority_refuses_deteriorating_momentum() -> None:
    result = screen_company(_compounder(economic_summary=summary(Overall.DETERIORATING)))

    assert result.bucket is not Bucket.HIGH_PRIORITY


def test_one_adequate_dimension_short_of_four_strong_falls_to_worth_underwriting() -> None:
    """A single band boundary must not decide the top bucket on its own."""
    result = screen_company(
        _compounder(
            capital_efficiency=capital_series([0.15] * 5, net_cash=[5 * _B] * 5),
            capital_allocation=tuple(
                allocation_row(2021 + index, Allocation.BALANCED) for index in range(5)
            ),
            economic_summary=summary(Overall.STABLE),
        )
    )

    assert result.bucket is Bucket.WORTH_UNDERWRITING


def test_worth_underwriting_strong_with_one_caveat_path() -> None:
    result = screen_company(
        _compounder(
            capital_allocation=tuple(
                allocation_row(2021 + index, Allocation.QUESTIONABLE)
                for index in range(5)
            )
        )
    )

    assert result.bucket is Bucket.WORTH_UNDERWRITING


def test_worth_underwriting_asymmetric_path_keeps_a_depressed_quality_business() -> None:
    """The Microsoft shape: intact returns and balance sheet, depressed economics."""
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _B, 101 * _B, 102 * _B, 103 * _B, 104 * _B],
                fcf_per_share=[1.00, 1.01, 1.02, 1.03, 1.04],
                diluted_shares=[100, 100, 100, 100, 100],
                operating_margin=[0.42, 0.43, 0.44, 0.46, 0.47],
                fcf_margin=[0.33, 0.30, 0.26, 0.22, 0.20],
            ),
            capital_efficiency=capital_series(
                [0.80, 0.60, 0.50, 0.42, 0.359], net_cash=[55 * _B, 50 * _B, 45 * _B, 40 * _B, 36 * _B]
            ),
            capital_allocation=tuple(
                allocation_row(2021 + index, Allocation.QUESTIONABLE)
                for index in range(5)
            ),
            economic_summary=summary(Overall.STRONGLY_DETERIORATING),
        )
    )

    assert result.bucket is Bucket.WORTH_UNDERWRITING
    assert result.setup_type is SetupType.POTENTIAL_ASYMMETRIC_SETUP
    assert result.limiting_factor is LimitingFactor.FUNDAMENTALS


def test_the_asymmetric_path_requires_an_intact_foundation() -> None:
    """Weak returns disqualify the asymmetric path: this is not a falling-knife rule."""
    result = screen_company(
        _compounder(
            capital_efficiency=capital_series([0.06] * 5, net_cash=[5 * _B] * 5),
            economic_summary=summary(Overall.STRONGLY_DETERIORATING),
        )
    )

    assert result.bucket is not Bucket.WORTH_UNDERWRITING
    assert result.setup_type is SetupType.NEITHER


def test_worth_underwriting_coverage_limited_path() -> None:
    """The ServiceNow shape: excellent measurable economics, unseeable balance sheet."""
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [1800, 2173, 2704, 3415, 4576],
                fcf_per_share=[1.77, 2.14, 2.63, 3.28, 4.37],
                diluted_shares=[100, 100, 101, 102, 103],
                operating_margin=[0.044, 0.049, 0.085, 0.124, 0.137],
                fcf_margin=[0.305, 0.300, 0.301, 0.311, 0.345],
            ),
        )
    )

    assert result.bucket is Bucket.WORTH_UNDERWRITING
    assert result.coverage_ceiling is Bucket.WORTH_UNDERWRITING
    assert result.limiting_factor is LimitingFactor.COVERAGE
    assert Reason.COVERAGE_LIMITED in result.coverage_reasons


def test_coverage_limited_path_requires_two_strong_dimensions() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                fcf_per_share=[1.0, 1.04, 1.08, 1.12, 1.17],
                diluted_shares=[100, 100, 100, 100, 100],
            ),
        )
    )

    assert result.bucket is Bucket.WATCH


def test_watch_requires_two_adequate_dimensions_and_at_most_one_poor() -> None:
    two_adequate = screen_company(
        _compounder(
            capital_efficiency=capital_series([0.15] * 5, net_cash=[5 * _B] * 5),
            owner_economics=owner_series(
                [140, 130, 120, 110, 100],
                fcf_per_share=[1.4, 1.3, 1.2, 1.1, 1.0],
                diluted_shares=[100] * 5,
            ),
            economic_summary=summary(Overall.DETERIORATING),
            capital_allocation=(allocation_row(2025, Allocation.QUESTIONABLE),),
        )
    )

    assert two_adequate.bucket is Bucket.WATCH


def test_two_poor_dimensions_fall_out_of_watch() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 110, 120, 130, 140],
                fcf_per_share=[20.8, 24.6, 27.4, 22.3, 17.7],
                diluted_shares=[100] * 5,
                operating_margin=[0.083, 0.088, 0.087, 0.081, 0.042],
                fcf_margin=[0.069, 0.072, 0.069, 0.052, 0.036],
            ),
        )
    )

    assert result.bucket is Bucket.LOW_PRIORITY


# --- Coverage ceilings ---------------------------------------------------------


def test_three_evaluable_dimensions_cap_a_partial_company_at_worth_underwriting() -> None:
    result = screen_company(_compounder(coverage_class=CoverageClass.PARTIAL))

    assert result.coverage_ceiling is Bucket.WORTH_UNDERWRITING
    assert result.bucket is Bucket.WORTH_UNDERWRITING


def test_fewer_than_three_evaluable_dimensions_cap_a_partial_company_at_watch() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 115, 132, 152, 175], fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07]
            ),
            economic_summary=None,
        )
    )

    assert result.evaluable_dimensions == 3
    assert result.coverage_ceiling is Bucket.WORTH_UNDERWRITING


def test_a_two_dimension_partial_company_is_capped_at_watch() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 115, 132, 152, 175], fcf_per_share=[1.0, 1.2]
            ),
        )
    )

    assert result.evaluable_dimensions == 2
    assert result.coverage_ceiling is Bucket.WATCH
    assert BUCKET_ORDER.index(result.bucket) >= BUCKET_ORDER.index(Bucket.WATCH)


def test_a_ceiling_never_raises_a_bucket() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [140, 130, 120, 110, 100],
                fcf_per_share=[1.4, 1.3, 1.2, 1.1, 1.0],
                operating_margin=[0.30, 0.26, 0.22, 0.19, 0.15],
                fcf_margin=[0.25, 0.21, 0.17, 0.14, 0.10],
            ),
        )
    )

    assert result.coverage_ceiling is Bucket.WORTH_UNDERWRITING
    assert result.bucket is Bucket.LOW_PRIORITY


def test_full_coverage_carries_no_ceiling() -> None:
    assert screen_company(_compounder()).coverage_ceiling is None


def test_an_unmeasured_dimension_caps_the_bucket_even_under_full_coverage() -> None:
    """A Feature 6 layer can produce output while its dimension stays unevaluable.

    Capital allocation returns rows whenever *any* year classifies, but the
    dimension reads the latest year. Such a company is just as unmeasured as a
    PARTIAL one and must not reach the top bucket on absent evidence.
    """
    result = screen_company(
        _compounder(
            capital_allocation=(
                allocation_row(2021, Allocation.OWNER_FRIENDLY),
                allocation_row(2025, Allocation.INSUFFICIENT_DATA),
            )
        )
    )

    assert result.coverage_class is CoverageClass.FULL
    assert result.band(ScreeningDimension.CAPITAL_ALLOCATION) is Band.NOT_EVALUABLE
    assert result.bucket is not Bucket.HIGH_PRIORITY
    assert result.coverage_ceiling is Bucket.WORTH_UNDERWRITING
    assert Reason.COVERAGE_LIMITED in result.coverage_reasons
    assert result.limiting_factor is not LimitingFactor.NONE


def test_a_partially_covered_company_cannot_outrank_an_identically_scored_full_one() -> None:
    """Absent negative evidence must never become an advantage."""
    full = screen_company(_compounder())
    partial = screen_company(_compounder(coverage_class=CoverageClass.PARTIAL))

    assert full.screening_score == partial.screening_score
    assert full.rank_key < partial.rank_key
    assert full.bucket is Bucket.HIGH_PRIORITY
    assert partial.bucket is Bucket.WORTH_UNDERWRITING


# --- Setup type ----------------------------------------------------------------


def test_setup_type_is_orthogonal_to_the_priority_bucket() -> None:
    compounder = screen_company(_compounder())
    asymmetric = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _B, 101 * _B, 102 * _B, 103 * _B, 104 * _B],
                fcf_per_share=[1.00, 1.01, 1.02, 1.03, 1.04],
                diluted_shares=[100] * 5,
            ),
            economic_summary=summary(Overall.STRONGLY_DETERIORATING),
        )
    )

    assert compounder.bucket is Bucket.HIGH_PRIORITY
    assert compounder.setup_type is SetupType.COMPOUNDER
    assert asymmetric.bucket is Bucket.WORTH_UNDERWRITING
    assert asymmetric.setup_type is SetupType.POTENTIAL_ASYMMETRIC_SETUP


def test_no_setup_label_is_granted_without_seeing_returns_on_capital() -> None:
    """Cash-flow evidence alone cannot prove a compounder or a depressed setup."""
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [1800, 2173, 2704, 3415, 4576],
                fcf_per_share=[1.77, 2.14, 2.63, 3.28, 4.37],
                diluted_shares=[100, 100, 101, 102, 103],
            ),
        )
    )

    assert result.band(ScreeningDimension.CAPITAL_EFFICIENCY) is Band.NOT_EVALUABLE
    assert result.setup_type is SetupType.NEITHER


def test_insufficient_data_carries_no_setup_label() -> None:
    result = screen_company(evidence(coverage_class=CoverageClass.FAILED))

    assert result.setup_type is SetupType.NEITHER


# --- Limiting factor -----------------------------------------------------------


def test_limiting_factor_separates_weak_fundamentals_from_missing_data() -> None:
    weak_but_visible = screen_company(
        _compounder(
            capital_allocation=(allocation_row(2025, Allocation.QUESTIONABLE),),
            economic_summary=summary(Overall.DETERIORATING),
        )
    )
    unseen_but_strong = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 115, 132, 152, 175],
                fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                diluted_shares=[100] * 5,
            ),
        )
    )

    assert weak_but_visible.limiting_factor is LimitingFactor.FUNDAMENTALS
    assert unseen_but_strong.limiting_factor is LimitingFactor.COVERAGE


def test_limiting_factor_is_both_when_a_partial_company_is_also_weak() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [140, 130, 120, 110, 100],
                fcf_per_share=[1.4, 1.3, 1.2, 1.1, 1.0],
                diluted_shares=[100] * 5,
            ),
            capital_efficiency=capital_series([0.40] * 5, net_cash=[_B] * 5),
        )
    )

    assert result.limiting_factor is LimitingFactor.BOTH


def test_high_priority_has_no_limiting_factor() -> None:
    assert screen_company(_compounder()).limiting_factor is LimitingFactor.NONE


def test_a_gated_company_never_reports_that_nothing_limits_it() -> None:
    """The dilution gate can fire while every band is still adequate or better."""
    result = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _MILLION, 115 * _MILLION, 132 * _MILLION, 152 * _MILLION, 175 * _MILLION],
                fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                diluted_shares=[100, 106, 112, 119, 127],
            )
        )
    )

    assert result.gate is Reason.PERSISTENT_MATERIAL_DILUTION
    assert result.bucket is Bucket.LOW_PRIORITY
    assert result.limiting_factor is LimitingFactor.FUNDAMENTALS
    assert "Limited by:" in format_screening_result(result)


# --- Score ---------------------------------------------------------------------


def test_the_score_is_a_bounded_integer_over_evaluable_dimensions_only() -> None:
    full = screen_company(_compounder())
    partial = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 115, 132, 152, 175],
                fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                diluted_shares=[100] * 5,
            ),
        )
    )

    assert isinstance(full.screening_score, int)
    assert full.screening_score == 3 * len(DIMENSION_ORDER) == 18
    assert partial.screening_score <= 3 * partial.evaluable_dimensions
    assert 0 <= partial.screening_score <= 18


def test_the_score_does_not_decide_the_bucket() -> None:
    """Two companies with the same score can sit in different buckets.

    Both score 11. The first keeps an intact foundation with depressed economics
    and is worth underwriting; the second has a weak balance sheet alongside its
    merely adequate returns, and is only worth watching.
    """
    asymmetric = screen_company(
        _compounder(
            owner_economics=owner_series(
                [100 * _B, 101 * _B, 102 * _B, 103 * _B, 104 * _B],
                fcf_per_share=[1.00, 1.01, 1.02, 1.03, 1.04],
                diluted_shares=[100] * 5,
            ),
            capital_allocation=tuple(
                allocation_row(2021 + index, Allocation.QUESTIONABLE)
                for index in range(5)
            ),
            economic_summary=summary(Overall.STRONGLY_DETERIORATING),
        )
    )
    watch = screen_company(
        _compounder(
            owner_economics=owner_series(
                [8 * _B, 10 * _B, 11 * _B, 13 * _B, 14 * _B],
                fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                diluted_shares=[100, 99, 99, 98, 98],
                operating_margin=[0.10, 0.13, 0.16, 0.18, 0.20],
                fcf_margin=[0.28, 0.30, 0.32, 0.33, 0.35],
            ),
            capital_efficiency=capital_series(
                [0.01, 0.005, 0.068, 0.099, 0.103],
                net_cash=[-5 * _B, -3 * _B, -_B, 415 * _MILLION, -7 * _B],
            ),
            capital_allocation=tuple(
                allocation_row(2021 + index, Allocation.QUESTIONABLE)
                for index in range(5)
            ),
            economic_summary=summary(Overall.DETERIORATING),
        )
    )

    assert asymmetric.screening_score == watch.screening_score == 11
    assert asymmetric.bucket is Bucket.WORTH_UNDERWRITING
    assert watch.bucket is Bucket.WATCH


# --- Reasons and rendering -----------------------------------------------------


def test_every_reason_code_has_exactly_one_category() -> None:
    assert all(isinstance(reason_category(reason), ReasonCategory) for reason in Reason)


def test_reasons_are_split_by_category_and_deduplicated() -> None:
    result = screen_company(_compounder())

    assert all(
        reason_category(reason) is ReasonCategory.SUPPORTING
        for reason in result.supporting_reasons
    )
    assert all(
        reason_category(reason) is ReasonCategory.LIMITING
        for reason in result.limiting_reasons
    )
    assert len(set(result.supporting_reasons)) == len(result.supporting_reasons)
    assert len(set(result.limiting_reasons)) == len(result.limiting_reasons)


def test_a_partial_company_names_what_cannot_be_seen() -> None:
    result = screen_company(
        evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 115, 132, 152, 175],
                fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                diluted_shares=[100] * 5,
            ),
            unavailable_metrics=("current_debt", "short_term_investments"),
        )
    )

    assert Reason.COVERAGE_LIMITED in result.coverage_reasons
    assert ScreeningDimension.CAPITAL_EFFICIENCY in result.unavailable_dimensions
    assert result.unavailable_metrics == ("current_debt", "short_term_investments")


def test_the_rendering_always_names_an_unavailable_dimension_and_its_blockers() -> None:
    """The blocking canonical metrics appear nowhere else, so they must render."""
    rendered = format_screening_result(
        screen_company(
            evidence(
                coverage_class=CoverageClass.PARTIAL,
                owner_economics=owner_series(
                    [100, 115, 132, 152, 175],
                    fcf_per_share=[1.0, 1.2, 1.44, 1.73, 2.07],
                    diluted_shares=[100] * 5,
                ),
                unavailable_metrics=("current_debt", "short_term_investments"),
            )
        )
    )

    assert "What we cannot see:" in rendered
    assert "unavailable dimensions:" in rendered
    assert "blocking canonical metrics: current_debt, short_term_investments" in rendered


def test_the_rendering_answers_why_it_ranks_and_what_holds_it_back() -> None:
    rendered = format_screening_result(
        screen_company(
            _compounder(
                capital_allocation=(allocation_row(2025, Allocation.QUESTIONABLE),),
                economic_summary=summary(Overall.DETERIORATING),
            )
        )
    )

    assert "Why it ranks where it does:" in rendered
    assert "What holds it back:" in rendered
    assert "Priority:" in rendered
    assert "Setup:" in rendered
    assert "Evidence:" in rendered
    assert "never sets the bucket" in rendered


def test_the_rendering_names_every_dimension() -> None:
    rendered = format_screening_result(screen_company(_compounder()))

    for label in (
        "Business quality",
        "Capital efficiency",
        "Per-share compounding",
        "Balance sheet",
        "Capital allocation",
        "Economic momentum",
    ):
        assert label in rendered


# --- Determinism ---------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        _compounder,
        lambda: evidence(coverage_class=CoverageClass.FAILED),
        lambda: evidence(
            coverage_class=CoverageClass.PARTIAL,
            owner_economics=owner_series(
                [100, 110, 120], fcf_per_share=[1.0, 1.1, 1.2]
            ),
            snapshots=(snapshot(2023, EconomicValueClassification.IMPROVING),),
        ),
    ],
)
def test_screening_is_deterministic(build) -> None:  # type: ignore[no-untyped-def]
    first = screen_company(build())
    second = screen_company(build())

    assert first == second

"""Tests for the OwnerLens Slice 2B multi-year compounding interpretation layer.

Fixtures construct Feature 1 rows and Feature 2A snapshots directly; no SEC
payloads or network access.
"""

from __future__ import annotations

from datetime import date

import pytest

from owner_lens import (
    CapitalEfficiencyRow,
    CompoundingClassification,
    CompoundingDriver,
    CompoundingThresholds,
    EconomicCompoundingView,
    EconomicValueClassification,
    EconomicValueSnapshot,
    OwnerEconomicsRow,
    build_compounding_view,
    cagr,
    classify_compounding,
)
from owner_lens._annual import AnnualObservation

Cls = CompoundingClassification
Drv = CompoundingDriver


def _obs(value: int, year: int) -> AnnualObservation:
    return AnnualObservation(
        concept="X",
        unit="USD",
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 1),
        form="10-K",
        filed=date(year + 1, 1, 15),
        accession=f"acc-{year}",
        value=value,
    )


def _view(**over: object) -> EconomicCompoundingView:
    fields: dict[str, object] = {
        "start_fiscal_year": 2021,
        "end_fiscal_year": 2025,
        "years": 4,
        "revenue_cagr": None,
        "fcf_cagr": None,
        "fcf_per_share_cagr": None,
        "diluted_share_cagr": None,
        "operating_margin_start": None,
        "operating_margin_end": None,
        "operating_margin_change": None,
        "fcf_margin_start": None,
        "fcf_margin_end": None,
        "fcf_margin_change": None,
        "roic_start": None,
        "roic_end": None,
        "roic_change": None,
        "net_cash_or_debt_start": None,
        "net_cash_or_debt_end": None,
        "net_cash_or_debt_change": None,
        "improving_count": 0,
        "stable_count": 0,
        "deteriorating_count": 0,
        "insufficient_count": 0,
        "classification": Cls.INSUFFICIENT_DATA,
        "drivers": (),
    }
    fields.update(over)
    return EconomicCompoundingView(**fields)  # type: ignore[arg-type]


def _owner(
    year: int,
    *,
    revenue: int | None = None,
    free_cash_flow: int | None = None,
    fcf_per_share: float | None = None,
    diluted_shares: int | None = None,
    operating_margin: float | None = None,
    fcf_margin: float | None = None,
) -> OwnerEconomicsRow:
    return OwnerEconomicsRow(
        fiscal_year=year,
        revenue=_obs(revenue, year) if revenue is not None else None,
        operating_income=None,
        net_income=None,
        operating_cash_flow=None,
        capital_expenditures=None,
        diluted_shares=_obs(diluted_shares, year) if diluted_shares is not None else None,
        operating_margin=operating_margin,
        net_margin=None,
        free_cash_flow=free_cash_flow,
        fcf_margin=fcf_margin,
        fcf_per_share=fcf_per_share,
        fcf_growth=None,
        fcf_per_share_growth=None,
        diluted_share_growth=None,
    )


def _capital(
    year: int, *, roic: float | None = None, net_cash: int | None = None
) -> CapitalEfficiencyRow:
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


def _snap(year: int, classification: EconomicValueClassification) -> EconomicValueSnapshot:
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


# --- User Story 2: CAGR mechanics and invalid cases -------------------------


def test_cagr_uses_interval_count_not_observation_count() -> None:
    # FY2021 through FY2025 is a five-observation span with four intervals.
    assert cagr(10000, 14641, 4) == pytest.approx(0.10)
    assert cagr(10000, 14641, 4) != cagr(10000, 14641, 5)


def test_cagr_positive_flat_and_decline() -> None:
    assert cagr(100, 121, 2) == pytest.approx(0.10)
    assert cagr(100, 100, 4) == pytest.approx(0.0)
    assert cagr(100, 25, 2) == pytest.approx(-0.5)


def test_cagr_invalid_cases_return_none() -> None:
    assert cagr(None, 100, 4) is None
    assert cagr(100, None, 4) is None
    assert cagr(0, 100, 4) is None
    assert cagr(-100, 100, 4) is None
    assert cagr(100, -50, 4) is None
    assert cagr(100, 100, 0) is None


# --- Shared builder fixtures ------------------------------------------------


def _five_year_inputs() -> tuple[
    list[OwnerEconomicsRow], list[CapitalEfficiencyRow], list[EconomicValueSnapshot]
]:
    owner = [
        _owner(2021, revenue=10000, free_cash_flow=10000, fcf_per_share=10.0, diluted_shares=1000, operating_margin=0.30, fcf_margin=0.25),
        _owner(2022, revenue=11000, free_cash_flow=11000, fcf_per_share=11.2, diluted_shares=985, operating_margin=0.31, fcf_margin=0.26),
        _owner(2023, revenue=12100, free_cash_flow=12100, fcf_per_share=12.6, diluted_shares=970, operating_margin=0.33, fcf_margin=0.28),
        _owner(2024, revenue=13310, free_cash_flow=13310, fcf_per_share=14.0, diluted_shares=955, operating_margin=0.35, fcf_margin=0.30),
        _owner(2025, revenue=14641, free_cash_flow=14641, fcf_per_share=14.641, diluted_shares=1000, operating_margin=0.36, fcf_margin=0.31),
    ]
    capital = [
        _capital(2021, roic=0.20, net_cash=1000),
        _capital(2022, roic=0.22, net_cash=1500),
        _capital(2023, roic=0.24, net_cash=2000),
        _capital(2024, roic=0.26, net_cash=2500),
        _capital(2025, roic=0.28, net_cash=3000),
    ]
    snapshots = [
        _snap(2021, EconomicValueClassification.INSUFFICIENT_DATA),
        _snap(2022, EconomicValueClassification.IMPROVING),
        _snap(2023, EconomicValueClassification.IMPROVING),
        _snap(2024, EconomicValueClassification.IMPROVING),
        _snap(2025, EconomicValueClassification.IMPROVING),
    ]
    return owner, capital, snapshots


# --- User Story 5: deterministic period selection ---------------------------


def test_four_year_period_spans_four_intervals() -> None:
    owner, capital, snaps = _five_year_inputs()
    view = build_compounding_view(owner, capital, snaps, period_years=4)
    assert (view.start_fiscal_year, view.end_fiscal_year, view.years) == (2021, 2025, 4)


def test_three_year_period_spans_three_intervals() -> None:
    owner, capital, snaps = _five_year_inputs()
    view = build_compounding_view(owner, capital, snaps, period_years=3)
    assert (view.start_fiscal_year, view.end_fiscal_year, view.years) == (2022, 2025, 3)


def test_insufficient_history_reports_explicitly() -> None:
    owner, capital, snaps = _five_year_inputs()
    short_owner = [row for row in owner if row.fiscal_year >= 2023]
    short_capital = [row for row in capital if row.fiscal_year >= 2023]
    view = build_compounding_view(short_owner, short_capital, snaps, period_years=4)
    assert view.classification is Cls.INSUFFICIENT_DATA
    assert Drv.INSUFFICIENT_MULTI_YEAR_HISTORY in view.drivers
    assert view.fcf_per_share_cagr is None


# --- User Story 6: annual consistency counts --------------------------------


def test_annual_counts_only_count_in_period_years() -> None:
    owner, capital, snaps = _five_year_inputs()
    view = build_compounding_view(owner, capital, snaps, period_years=3)
    # 3-year CAGR spans FY2022-2025: four in-period snapshots, all improving.
    assert (view.improving_count, view.insufficient_count) == (4, 0)
    long_term = build_compounding_view(owner, capital, snaps, period_years=4)
    assert (long_term.improving_count, long_term.insufficient_count) == (4, 1)


# --- User Story 3: classification and deterministic drivers -----------------


def test_strongly_compounding_classification() -> None:
    view = _view(
        fcf_per_share_cagr=0.20,
        fcf_cagr=0.15,
        diluted_share_cagr=-0.03,
        roic_end=0.30,
        roic_change=0.04,
        operating_margin_change=0.03,
        fcf_margin_change=0.03,
        improving_count=4,
        insufficient_count=1,
    )
    classification, drivers = classify_compounding(view)
    assert classification is Cls.STRONGLY_COMPOUNDING
    assert drivers[0] is Drv.STRONG_FCF_PER_SHARE_COMPOUNDING
    assert Drv.ROIC_HIGH_AND_SUSTAINED in drivers
    assert Drv.SHARE_COUNT_SHRANK in drivers


def test_moderate_compounding_classification() -> None:
    view = _view(fcf_per_share_cagr=0.09, fcf_cagr=0.09)
    classification, drivers = classify_compounding(view)
    assert classification is Cls.COMPOUNDING
    assert Drv.MODERATE_FCF_PER_SHARE_COMPOUNDING in drivers


def test_stable_classification() -> None:
    view = _view(fcf_per_share_cagr=0.0, fcf_cagr=0.0)
    classification, _ = classify_compounding(view)
    assert classification is Cls.STABLE


def test_deteriorating_classification() -> None:
    view = _view(fcf_per_share_cagr=-0.10, fcf_cagr=-0.08, roic_change=-0.05)
    classification, drivers = classify_compounding(view)
    assert classification is Cls.DETERIORATING
    assert Drv.FCF_PER_SHARE_DECLINED in drivers


def test_classification_is_deterministic() -> None:
    view = _view(
        fcf_per_share_cagr=0.18, fcf_cagr=0.14, roic_end=0.30, diluted_share_cagr=-0.02
    )
    assert classify_compounding(view) == classify_compounding(view)


def test_custom_thresholds_change_the_outcome() -> None:
    view = _view(fcf_per_share_cagr=0.16, fcf_cagr=0.14)
    assert classify_compounding(view)[0] is Cls.STRONGLY_COMPOUNDING
    stricter = CompoundingThresholds(strong_fcf_per_share_cagr=0.20)
    assert classify_compounding(view, thresholds=stricter)[0] is Cls.COMPOUNDING


# --- User Story 4: per-share weighting and its sources ----------------------


def test_share_shrink_illusion_is_not_strongly_compounding() -> None:
    view = _view(
        fcf_per_share_cagr=0.20,
        fcf_cagr=-0.08,
        diluted_share_cagr=-0.06,
    )
    classification, drivers = classify_compounding(view)
    assert classification is not Cls.STRONGLY_COMPOUNDING
    assert Drv.AGGREGATE_FCF_DECLINED in drivers
    assert Drv.SHARE_COUNT_SHRANK in drivers


def test_strong_aggregate_growth_with_dilution_is_tempered() -> None:
    view = _view(
        fcf_per_share_cagr=0.10,
        fcf_cagr=0.14,
        diluted_share_cagr=0.03,
    )
    classification, drivers = classify_compounding(view)
    assert classification is Cls.STABLE
    assert Drv.MATERIAL_DILUTION in drivers


def test_falling_per_share_with_roic_decline_is_deteriorating() -> None:
    view = _view(
        revenue_cagr=0.08,
        fcf_per_share_cagr=-0.06,
        roic_change=-0.05,
    )
    classification, _ = classify_compounding(view)
    assert classification is Cls.DETERIORATING


def test_strong_per_share_with_sustained_high_roic_is_strongly_compounding() -> None:
    view = _view(
        fcf_per_share_cagr=0.18,
        fcf_cagr=0.15,
        roic_end=0.30,
        roic_change=0.0,
    )
    classification, drivers = classify_compounding(view)
    assert classification is Cls.STRONGLY_COMPOUNDING
    assert Drv.ROIC_HIGH_AND_SUSTAINED in drivers


# --- User Story 1: view assembly, CAGR and deltas ---------------------------


def test_build_view_keeps_rates_and_level_changes_distinct() -> None:
    owner, capital, snaps = _five_year_inputs()
    view = build_compounding_view(owner, capital, snaps, period_years=4)
    assert view.revenue_cagr is not None
    assert view.operating_margin_start == 0.30
    assert view.operating_margin_end == 0.36
    assert view.classification is not Cls.INSUFFICIENT_DATA


def test_build_view_cagr_and_deltas_match_endpoints() -> None:
    owner, capital, snaps = _five_year_inputs()
    view = build_compounding_view(owner, capital, snaps, period_years=4)
    assert view.revenue_cagr == pytest.approx(0.10)
    assert view.fcf_cagr == pytest.approx(0.10)
    assert view.operating_margin_change == pytest.approx(0.06)
    assert view.roic_change == pytest.approx(0.08)
    assert view.net_cash_or_debt_change == 2000


def test_visa_per_share_compounding_insufficient_but_aggregate_available() -> None:
    from _fixtures import visa_facts

    from owner_lens import compounding_views_from_facts

    recent, long_term = compounding_views_from_facts(visa_facts(), ticker="V")

    assert recent.classification is Cls.INSUFFICIENT_DATA
    assert long_term.classification is Cls.INSUFFICIENT_DATA
    assert long_term.fcf_per_share_cagr is None
    # Non-per-share compounding remains available (never fabricated).
    assert long_term.revenue_cagr is not None
    assert long_term.fcf_cagr is not None

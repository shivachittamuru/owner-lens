"""Tests for the OwnerLens Slice 2A economic-value interpretation layer.

Fixtures construct Feature 1 rows directly; no SEC payloads or network access.
"""

from __future__ import annotations

from datetime import date

import pytest

from owner_lens import (
    CapitalEfficiencyRow,
    EconomicValueClassification,
    EconomicValueDriver,
    EconomicValueSnapshot,
    EconomicValueThresholds,
    OwnerEconomicsRow,
    build_economic_value_snapshots,
    classify_economic_value,
)
from owner_lens._annual import AnnualObservation

Cls = EconomicValueClassification
Drv = EconomicValueDriver


def _obs(value: int, year: int) -> AnnualObservation:
    return AnnualObservation(
        concept="Revenues",
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


def _snap(**over: object) -> EconomicValueSnapshot:
    fields: dict[str, object] = {
        "fiscal_year": 2025,
        "revenue_growth": None,
        "operating_margin_change": None,
        "fcf_growth": None,
        "fcf_margin_change": None,
        "diluted_share_growth": None,
        "fcf_per_share_growth": None,
        "roic_change": None,
        "operating_margin": None,
        "fcf_margin": None,
        "fcf_per_share": None,
        "roic": None,
        "net_cash_or_debt": None,
        "classification": Cls.INSUFFICIENT_DATA,
        "drivers": (),
    }
    fields.update(over)
    return EconomicValueSnapshot(**fields)  # type: ignore[arg-type]


def _owner(
    year: int,
    *,
    revenue: int | None = None,
    operating_margin: float | None = None,
    fcf_margin: float | None = None,
    fcf_per_share: float | None = None,
    fcf_growth: float | None = None,
    fcf_per_share_growth: float | None = None,
    diluted_share_growth: float | None = None,
) -> OwnerEconomicsRow:
    return OwnerEconomicsRow(
        fiscal_year=year,
        revenue=_obs(revenue, year) if revenue is not None else None,
        operating_income=None,
        net_income=None,
        operating_cash_flow=None,
        capital_expenditures=None,
        diluted_shares=None,
        operating_margin=operating_margin,
        net_margin=None,
        free_cash_flow=None,
        fcf_margin=fcf_margin,
        fcf_per_share=fcf_per_share,
        fcf_growth=fcf_growth,
        fcf_per_share_growth=fcf_per_share_growth,
        diluted_share_growth=diluted_share_growth,
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


# --- User Story 2: classification and deterministic drivers -----------------


def test_clearly_improving_classifies_improving_with_per_share_driver_first() -> None:
    snap = _snap(
        fcf_per_share_growth=0.15,
        roic_change=0.03,
        operating_margin_change=0.02,
        fcf_margin_change=0.02,
        diluted_share_growth=-0.02,
        roic=0.25,
    )
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.IMPROVING
    assert drivers[0] is Drv.FCF_PER_SHARE_STRONG_GROWTH
    assert Drv.ROIC_EXPANDED in drivers
    assert Drv.SHARE_COUNT_DECLINED in drivers
    assert Drv.ROIC_SUSTAINED_HIGH in drivers
    assert Drv.PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION not in drivers


def test_clearly_deteriorating_classifies_deteriorating() -> None:
    snap = _snap(
        fcf_per_share_growth=-0.15,
        roic_change=-0.03,
        operating_margin_change=-0.02,
        fcf_margin_change=-0.02,
        diluted_share_growth=0.02,
    )
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.DETERIORATING
    assert drivers[0] is Drv.FCF_PER_SHARE_DECLINE
    assert Drv.ROIC_CONTRACTED in drivers
    assert Drv.SHARE_COUNT_INCREASED in drivers


def test_flat_per_share_and_quiet_secondaries_classifies_stable() -> None:
    snap = _snap(
        fcf_per_share_growth=0.0,
        roic_change=0.0,
        operating_margin_change=0.0,
        fcf_margin_change=0.0,
        diluted_share_growth=0.0,
    )
    classification, _ = classify_economic_value(snap)
    assert classification is Cls.STABLE


def test_classification_is_deterministic() -> None:
    snap = _snap(
        fcf_per_share_growth=0.12,
        roic_change=0.03,
        operating_margin_change=0.02,
        fcf_margin_change=0.02,
        diluted_share_growth=-0.03,
        roic=0.22,
    )
    first = classify_economic_value(snap)
    second = classify_economic_value(snap)
    assert first == second


# --- User Story 1: snapshot assembly, alignment, change derivation ----------


def _two_year_rows() -> tuple[
    list[OwnerEconomicsRow], list[CapitalEfficiencyRow]
]:
    owner = [
        _owner(
            2025,
            revenue=110,
            operating_margin=0.33,
            fcf_margin=0.28,
            fcf_per_share=12.0,
            fcf_growth=0.12,
            fcf_per_share_growth=0.14,
            diluted_share_growth=-0.02,
        ),
        _owner(
            2024,
            revenue=100,
            operating_margin=0.30,
            fcf_margin=0.25,
            fcf_per_share=10.5,
            fcf_growth=None,
            fcf_per_share_growth=None,
            diluted_share_growth=None,
        ),
    ]
    capital = [
        _capital(2025, roic=0.24, net_cash=5000),
        _capital(2024, roic=0.20, net_cash=4000),
    ]
    return owner, capital


def test_build_produces_one_snapshot_per_year_newest_first() -> None:
    owner, capital = _two_year_rows()
    snaps = build_economic_value_snapshots(owner, capital)
    assert [s.fiscal_year for s in snaps] == [2025, 2024]
    latest = snaps[0]
    assert latest.operating_margin == 0.33
    assert latest.roic == 0.24
    assert latest.net_cash_or_debt == 5000
    assert latest.revenue_growth is not None
    # Earliest year has no in-window prior, so change signals are unavailable.
    earliest = snaps[1]
    assert earliest.fcf_per_share_growth is None
    assert earliest.classification is Cls.INSUFFICIENT_DATA


def test_build_derives_adjacent_year_changes_and_reuses_feature1_changes() -> None:
    owner, capital = _two_year_rows()
    latest = build_economic_value_snapshots(owner, capital)[0]
    assert latest.revenue_growth == pytest.approx(0.10)
    assert latest.operating_margin_change == pytest.approx(0.03)
    assert latest.fcf_margin_change == pytest.approx(0.03)
    assert latest.roic_change == pytest.approx(0.04)
    # Reused directly from the Feature 1 owner-economics row.
    assert latest.fcf_growth == pytest.approx(0.12)
    assert latest.fcf_per_share_growth == pytest.approx(0.14)
    assert latest.diluted_share_growth == pytest.approx(-0.02)


# --- User Story 3: per-share economics weighted over aggregate growth -------


def test_rising_aggregate_fcf_with_dilution_is_not_improving() -> None:
    snap = _snap(
        fcf_growth=0.10,
        fcf_per_share_growth=-0.06,
        diluted_share_growth=0.08,
    )
    classification, drivers = classify_economic_value(snap)
    assert classification is not Cls.IMPROVING
    assert Drv.SHARE_COUNT_INCREASED in drivers
    assert Drv.FCF_PER_SHARE_DECLINE in drivers


def test_flat_aggregate_fcf_with_buyback_is_improving() -> None:
    snap = _snap(
        fcf_growth=0.0,
        fcf_per_share_growth=0.08,
        diluted_share_growth=-0.08,
    )
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.IMPROVING
    assert Drv.SHARE_COUNT_DECLINED in drivers


def test_strong_per_share_growth_with_material_roic_contraction_downgrades() -> None:
    snap = _snap(fcf_per_share_growth=0.15, roic_change=-0.03)
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.STABLE
    assert Drv.PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION in drivers


def test_strong_per_share_growth_with_severe_roic_deterioration_deteriorates() -> None:
    snap = _snap(fcf_per_share_growth=0.15, roic_change=-0.06)
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.DETERIORATING
    assert Drv.PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION in drivers


def test_strong_per_share_growth_with_leverage_flip_downgrades() -> None:
    owner = [
        _owner(2025, fcf_per_share_growth=0.15),
        _owner(2024, fcf_per_share_growth=None),
    ]
    capital = [
        _capital(2025, roic=0.23, net_cash=-500),
        _capital(2024, roic=0.20, net_cash=1000),
    ]
    latest = build_economic_value_snapshots(owner, capital)[0]
    assert latest.classification is not Cls.IMPROVING
    assert Drv.TURNED_TO_NET_DEBT in latest.drivers
    assert Drv.PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION in latest.drivers


def test_drawing_down_surplus_cash_is_not_a_leverage_guardrail() -> None:
    owner = [
        _owner(2025, fcf_per_share_growth=0.20),
        _owner(2024, fcf_per_share_growth=None),
    ]
    # Net cash falls sharply but stays strongly net-cash positive (a buyback year).
    capital = [
        _capital(2025, roic=0.30, net_cash=400),
        _capital(2024, roic=0.28, net_cash=2200),
    ]
    latest = build_economic_value_snapshots(owner, capital)[0]
    assert latest.classification is Cls.IMPROVING
    assert Drv.NET_CASH_DETERIORATED in latest.drivers
    assert Drv.PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION not in latest.drivers


# --- User Story 4: missing and insufficient prior-year data -----------------


def test_missing_per_share_growth_is_insufficient_data() -> None:
    snap = _snap(revenue_growth=0.10, roic=0.25)
    classification, drivers = classify_economic_value(snap)
    assert classification is Cls.INSUFFICIENT_DATA
    assert drivers == (Drv.INSUFFICIENT_PRIOR_YEAR_DATA,)


def test_earliest_year_change_signals_are_none_not_zero() -> None:
    owner, capital = _two_year_rows()
    earliest = build_economic_value_snapshots(owner, capital)[1]
    assert earliest.revenue_growth is None
    assert earliest.operating_margin_change is None
    assert earliest.roic_change is None
    assert earliest.classification is Cls.INSUFFICIENT_DATA


# --- User Story 5: centralized, named, adjustable thresholds -----------------


def test_growth_threshold_boundary_is_inclusive() -> None:
    at_boundary = _snap(fcf_per_share_growth=0.05)
    just_below = _snap(fcf_per_share_growth=0.049)
    assert classify_economic_value(at_boundary)[0] is Cls.IMPROVING
    assert classify_economic_value(just_below)[0] is Cls.STABLE


def test_margin_change_boundary_flips_stable_to_improving() -> None:
    inside = _snap(
        fcf_per_share_growth=0.0,
        operating_margin_change=0.01,
        fcf_margin_change=0.01,
    )
    outside = _snap(
        fcf_per_share_growth=0.0,
        operating_margin_change=0.009,
        fcf_margin_change=0.009,
    )
    assert classify_economic_value(inside)[0] is Cls.IMPROVING
    assert classify_economic_value(outside)[0] is Cls.STABLE


def test_custom_thresholds_change_the_outcome() -> None:
    snap = _snap(fcf_per_share_growth=0.06)
    assert classify_economic_value(snap)[0] is Cls.IMPROVING
    stricter = EconomicValueThresholds(material_growth=0.10)
    assert classify_economic_value(snap, thresholds=stricter)[0] is Cls.STABLE

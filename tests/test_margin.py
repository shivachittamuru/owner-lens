"""Tests for operating-margin derivation and metric alignment."""

from __future__ import annotations

from datetime import date

import pytest

from owner_lens import (
    AnnualObservation,
    AnnualOperatingIncomeSeries,
    AnnualRevenueSeries,
    align_annual_metrics,
    operating_margins,
)


def _obs(year: int, value: int, *, accession: str) -> AnnualObservation:
    return AnnualObservation(
        concept="Concept",
        unit="USD",
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year - 1, 12, 1),
        period_end=date(year, 11, 30),
        form="10-K",
        filed=date(year + 1, 1, 15),
        accession=accession,
        value=value,
    )


def _revenue(*observations: AnnualObservation) -> AnnualRevenueSeries:
    return AnnualRevenueSeries(ticker="ADBE", concept="Revenues", observations=observations)


def _operating_income(*observations: AnnualObservation) -> AnnualOperatingIncomeSeries:
    return AnnualOperatingIncomeSeries(
        ticker="ADBE", concept="OperatingIncomeLoss", observations=observations
    )


def test_margin_equals_operating_income_over_revenue() -> None:
    revenue = _revenue(_obs(2025, 23769000000, accession="rev-2025"))
    income = _operating_income(_obs(2025, 8706000000, accession="oi-2025"))

    margins = operating_margins(revenue, income)

    assert len(margins) == 1
    margin = margins[0]
    assert margin.fiscal_year == 2025
    assert margin.value == pytest.approx(8706000000 / 23769000000)
    assert margin.revenue == 23769000000
    assert margin.operating_income == 8706000000
    assert margin.revenue_accession == "rev-2025"
    assert margin.operating_income_accession == "oi-2025"


def test_alignment_pairs_by_fiscal_year_newest_first() -> None:
    revenue = _revenue(
        _obs(2024, 21505000000, accession="rev-2024"),
        _obs(2025, 23769000000, accession="rev-2025"),
    )
    income = _operating_income(
        _obs(2024, 6741000000, accession="oi-2024"),
        _obs(2025, 8706000000, accession="oi-2025"),
    )

    rows = align_annual_metrics(revenue, income)

    assert [r.fiscal_year for r in rows] == [2025, 2024]
    assert all(r.operating_margin is not None for r in rows)
    assert rows[0].revenue is not None and rows[0].revenue.value == 23769000000
    assert rows[0].operating_income is not None and rows[0].operating_income.value == 8706000000


def test_year_missing_revenue_yields_no_margin() -> None:
    revenue = _revenue(_obs(2025, 23769000000, accession="rev-2025"))
    income = _operating_income(
        _obs(2024, 6741000000, accession="oi-2024"),
        _obs(2025, 8706000000, accession="oi-2025"),
    )

    rows = align_annual_metrics(revenue, income)
    by_year = {r.fiscal_year: r for r in rows}

    assert by_year[2024].revenue is None
    assert by_year[2024].operating_income is not None
    assert by_year[2024].operating_margin is None
    assert [m.fiscal_year for m in operating_margins(revenue, income)] == [2025]


def test_year_missing_operating_income_yields_no_margin() -> None:
    revenue = _revenue(
        _obs(2024, 21505000000, accession="rev-2024"),
        _obs(2025, 23769000000, accession="rev-2025"),
    )
    income = _operating_income(_obs(2025, 8706000000, accession="oi-2025"))

    by_year = {r.fiscal_year: r for r in align_annual_metrics(revenue, income)}

    assert by_year[2024].operating_income is None
    assert by_year[2024].operating_margin is None


def test_zero_revenue_yields_no_margin() -> None:
    revenue = _revenue(_obs(2025, 0, accession="rev-2025"))
    income = _operating_income(_obs(2025, 8706000000, accession="oi-2025"))

    rows = align_annual_metrics(revenue, income)

    assert rows[0].revenue is not None
    assert rows[0].operating_income is not None
    assert rows[0].operating_margin is None
    assert operating_margins(revenue, income) == ()


def test_negative_operating_income_yields_negative_margin() -> None:
    revenue = _revenue(_obs(2025, 20000000000, accession="rev-2025"))
    income = _operating_income(_obs(2025, -1000000000, accession="oi-2025"))

    margin = operating_margins(revenue, income)[0]

    assert margin.value == pytest.approx(-0.05)


def test_alignment_covers_union_of_years() -> None:
    revenue = _revenue(_obs(2023, 19409000000, accession="rev-2023"))
    income = _operating_income(_obs(2025, 8706000000, accession="oi-2025"))

    rows = align_annual_metrics(revenue, income)

    assert [r.fiscal_year for r in rows] == [2025, 2023]
    assert all(r.operating_margin is None for r in rows)

"""Tests for derived owner-economics metrics and alignment (Slice 1D)."""

from __future__ import annotations

from datetime import date

import pytest

from owner_lens import (
    AnnualObservation,
    AnnualOperatingIncomeSeries,
    AnnualRevenueSeries,
    AnnualSeries,
    OwnerEconomicsRow,
    compute_owner_economics,
)


def _obs(year: int, value: int, *, concept: str = "C", unit: str = "USD", accession: str | None = None) -> AnnualObservation:
    return AnnualObservation(
        concept=concept,
        unit=unit,
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year - 1, 12, 1),
        period_end=date(year, 11, 30),
        form="10-K",
        filed=date(year + 1, 1, 15),
        accession=accession or f"{concept}-{year}",
        value=value,
    )


def _revenue(*obs: AnnualObservation) -> AnnualRevenueSeries:
    return AnnualRevenueSeries(ticker="ADBE", concept="Revenues", observations=obs)


def _oi(*obs: AnnualObservation) -> AnnualOperatingIncomeSeries:
    return AnnualOperatingIncomeSeries(
        ticker="ADBE", concept="OperatingIncomeLoss", observations=obs
    )


def _series(metric: str, unit: str, *obs: AnnualObservation) -> AnnualSeries:
    return AnnualSeries(
        metric=metric, ticker="ADBE", concept="C", unit=unit, observations=obs
    )


def _adbe_two_years() -> dict[str, object]:
    return {
        "revenue": _revenue(_obs(2024, 21505000000), _obs(2025, 23769000000)),
        "operating_income": _oi(_obs(2024, 6741000000), _obs(2025, 8706000000)),
        "net_income": _series("net_income", "USD", _obs(2024, 5560000000), _obs(2025, 7130000000)),
        "operating_cash_flow": _series(
            "operating_cash_flow", "USD", _obs(2024, 8056000000), _obs(2025, 10031000000)
        ),
        "capital_expenditures": _series(
            "capital_expenditures", "USD", _obs(2024, 183000000), _obs(2025, 179000000)
        ),
        "diluted_shares": _series(
            "diluted_shares", "shares", _obs(2024, 449700000), _obs(2025, 427000000)
        ),
    }


def test_derived_metrics_match_formulas() -> None:
    rows = compute_owner_economics(**_adbe_two_years())  # type: ignore[arg-type]
    latest = rows[0]

    assert latest.fiscal_year == 2025
    assert latest.free_cash_flow == 10031000000 - 179000000
    assert latest.net_margin == pytest.approx(7130000000 / 23769000000)
    assert latest.fcf_margin == pytest.approx(9852000000 / 23769000000)
    assert latest.fcf_per_share == pytest.approx(9852000000 / 427000000)
    assert latest.operating_margin == pytest.approx(8706000000 / 23769000000)


def test_free_cash_flow_uses_positive_capex_magnitude() -> None:
    data = _adbe_two_years()
    # Defensive: a negative-source CapEx must still yield the same positive-magnitude FCF.
    data["capital_expenditures"] = _series(
        "capital_expenditures", "USD", _obs(2024, -183000000), _obs(2025, -179000000)
    )

    rows = compute_owner_economics(**data)  # type: ignore[arg-type]

    assert rows[0].free_cash_flow == 10031000000 - 179000000


def test_adjacent_year_growth_and_earliest_year_omitted() -> None:
    rows = compute_owner_economics(**_adbe_two_years())  # type: ignore[arg-type]
    by_year = {r.fiscal_year: r for r in rows}

    fcf_2025 = 10031000000 - 179000000
    fcf_2024 = 8056000000 - 183000000
    assert by_year[2025].fcf_growth == pytest.approx((fcf_2025 - fcf_2024) / fcf_2024)
    assert by_year[2025].diluted_share_growth == pytest.approx(
        (427000000 - 449700000) / 449700000
    )
    # Earliest year has no prior-year comparison.
    assert by_year[2024].fcf_growth is None
    assert by_year[2024].fcf_per_share_growth is None
    assert by_year[2024].diluted_share_growth is None


def test_missing_denominator_and_input_omit_metrics() -> None:
    rows = compute_owner_economics(
        revenue=_revenue(_obs(2025, 0)),
        operating_income=_oi(_obs(2025, 8706000000)),
        net_income=_series("net_income", "USD", _obs(2025, 7130000000)),
        operating_cash_flow=_series("operating_cash_flow", "USD", _obs(2025, 10031000000)),
        capital_expenditures=_series("capital_expenditures", "USD", _obs(2025, 179000000)),
        diluted_shares=_series("diluted_shares", "shares"),  # missing shares
    )
    row = rows[0]

    assert row.net_margin is None  # revenue is zero
    assert row.fcf_margin is None  # revenue is zero
    assert row.free_cash_flow == 10031000000 - 179000000
    assert row.fcf_per_share is None  # diluted shares missing


def test_alignment_covers_union_of_years() -> None:
    rows = compute_owner_economics(
        revenue=_revenue(_obs(2023, 19409000000)),
        operating_income=_oi(),
        net_income=_series("net_income", "USD"),
        operating_cash_flow=_series("operating_cash_flow", "USD", _obs(2025, 10031000000)),
        capital_expenditures=_series("capital_expenditures", "USD", _obs(2025, 179000000)),
        diluted_shares=_series("diluted_shares", "shares", _obs(2025, 427000000)),
    )

    assert [r.fiscal_year for r in rows] == [2025, 2023]
    assert rows[0].revenue is None
    assert rows[0].free_cash_flow == 10031000000 - 179000000
    assert rows[1].operating_cash_flow is None


def test_negative_net_income_yields_negative_margin() -> None:
    rows = compute_owner_economics(
        revenue=_revenue(_obs(2025, 20000000000)),
        operating_income=_oi(_obs(2025, -1000000000)),
        net_income=_series("net_income", "USD", _obs(2025, -2000000000)),
        operating_cash_flow=_series("operating_cash_flow", "USD", _obs(2025, 3000000000)),
        capital_expenditures=_series("capital_expenditures", "USD", _obs(2025, 100000000)),
        diluted_shares=_series("diluted_shares", "shares", _obs(2025, 400000000)),
    )

    assert rows[0].net_margin == pytest.approx(-0.1)


def test_reported_and_derived_fields_are_distinct_types() -> None:
    rows = compute_owner_economics(**_adbe_two_years())  # type: ignore[arg-type]
    row = rows[0]

    assert isinstance(row, OwnerEconomicsRow)
    assert isinstance(row.net_income, AnnualObservation)
    # Derived fields are plain numbers, not observations.
    assert isinstance(row.net_margin, float)
    assert isinstance(row.free_cash_flow, int)
    assert not isinstance(row.free_cash_flow, AnnualObservation)

"""Tests for derived capital-efficiency metrics and alignment (Slice 1E)."""

from __future__ import annotations

from datetime import date

import pytest

from owner_lens import (
    AnnualObservation,
    AnnualOperatingIncomeSeries,
    AnnualSeries,
    CapitalEfficiencyRow,
    compute_capital_efficiency,
)


def _obs(year: int, value: int, *, concept: str = "C", accession: str | None = None) -> AnnualObservation:
    return AnnualObservation(
        concept=concept,
        unit="USD",
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year, 11, 30),
        period_end=date(year, 11, 30),
        form="10-K",
        filed=date(year + 1, 1, 15),
        accession=accession or f"{concept}-{year}",
        value=value,
    )


def _series(metric: str, values: dict[int, int]) -> AnnualSeries:
    obs = tuple(_obs(y, v, concept=metric) for y, v in sorted(values.items(), reverse=True))
    return AnnualSeries(metric=metric, ticker="ADBE", concept=metric, unit="USD", observations=obs)


def _oi(values: dict[int, int]) -> AnnualOperatingIncomeSeries:
    obs = tuple(_obs(y, v, concept="OperatingIncomeLoss") for y, v in sorted(values.items(), reverse=True))
    return AnnualOperatingIncomeSeries(ticker="ADBE", concept="OperatingIncomeLoss", observations=obs)


def _adbe_inputs() -> dict[str, object]:
    return {
        "operating_income": _oi({2024: 6741000000, 2025: 8706000000}),
        "net_income": _series("net_income", {2024: 5560000000, 2025: 7130000000}),
        "income_tax_expense": _series("income_tax_expense", {2024: 1000000000, 2025: 1000000000}),
        "pretax_income": _series("pretax_income", {2024: 8000000000, 2025: 8000000000}),
        "cash": _series("cash", {2023: 7141000000, 2024: 7613000000, 2025: 5431000000}),
        "short_term_investments": _series(
            "short_term_investments", {2023: 701000000, 2024: 273000000, 2025: 1164000000}
        ),
        "current_debt": _series("current_debt", {2024: 1499000000, 2025: 0}),
        "long_term_debt": _series(
            "long_term_debt", {2023: 3634000000, 2024: 4129000000, 2025: 6210000000}
        ),
        "total_assets": _series(
            "total_assets", {2023: 29779000000, 2024: 30230000000, 2025: 29496000000}
        ),
        "total_equity": _series(
            "total_equity", {2023: 16518000000, 2024: 14105000000, 2025: 11623000000}
        ),
    }


def test_cash_debt_and_net_cash() -> None:
    rows = compute_capital_efficiency(display_years=2, **_adbe_inputs())  # type: ignore[arg-type]
    latest = rows[0]

    assert latest.fiscal_year == 2025
    assert latest.cash_plus_sti == 5431000000 + 1164000000  # no double counting
    assert latest.total_debt == 0 + 6210000000
    assert latest.net_cash == 6595000000 - 6210000000


def test_tax_rate_nopat_and_invested_capital() -> None:
    rows = compute_capital_efficiency(display_years=2, **_adbe_inputs())  # type: ignore[arg-type]
    latest = rows[0]

    assert latest.effective_tax_rate == pytest.approx(1000000000 / 8000000000)
    assert latest.nopat == round(8706000000 * (1 - 0.125))
    assert latest.invested_capital == 6210000000 + 11623000000 - 6595000000


def test_returns_use_average_balances() -> None:
    rows = compute_capital_efficiency(display_years=2, **_adbe_inputs())  # type: ignore[arg-type]
    latest = rows[0]

    avg_assets = (29496000000 + 30230000000) / 2
    avg_equity = (11623000000 + 14105000000) / 2
    ic_2025 = 6210000000 + 11623000000 - 6595000000
    ic_2024 = 5628000000 + 14105000000 - 7886000000
    avg_ic = (ic_2025 + ic_2024) / 2

    assert latest.roa == pytest.approx(7130000000 / avg_assets)
    assert latest.roe == pytest.approx(7130000000 / avg_equity)
    assert latest.roic == pytest.approx(round(8706000000 * 0.875) / avg_ic)


def test_missing_prior_year_baseline_omits_average_metrics() -> None:
    inputs = _adbe_inputs()
    # Drop the 2023 baseline so 2024 has no beginning balance.
    inputs["cash"] = _series("cash", {2024: 7613000000, 2025: 5431000000})
    inputs["short_term_investments"] = _series(
        "short_term_investments", {2024: 273000000, 2025: 1164000000}
    )
    inputs["long_term_debt"] = _series("long_term_debt", {2024: 4129000000, 2025: 6210000000})
    inputs["total_assets"] = _series("total_assets", {2024: 30230000000, 2025: 29496000000})
    inputs["total_equity"] = _series("total_equity", {2024: 14105000000, 2025: 11623000000})

    rows = compute_capital_efficiency(display_years=2, **inputs)  # type: ignore[arg-type]
    by_year = {r.fiscal_year: r for r in rows}

    # 2024 is the earliest year and has no prior baseline.
    assert by_year[2024].roa is None
    assert by_year[2024].roe is None
    assert by_year[2024].roic is None
    # 2025 still computes from the 2024 balances.
    assert by_year[2025].roa is not None


def test_absent_sti_and_current_debt_are_treated_as_zero() -> None:
    inputs = _adbe_inputs()
    inputs["short_term_investments"] = _series("short_term_investments", {})
    inputs["current_debt"] = _series("current_debt", {})

    rows = compute_capital_efficiency(display_years=2, **inputs)  # type: ignore[arg-type]
    latest = rows[0]

    assert latest.cash_plus_sti == 5431000000  # cash only
    assert latest.total_debt == 6210000000  # long-term only


def test_zero_average_equity_omits_roe() -> None:
    inputs = _adbe_inputs()
    inputs["total_equity"] = _series("total_equity", {2023: 0, 2024: 0, 2025: 0})

    rows = compute_capital_efficiency(display_years=2, **inputs)  # type: ignore[arg-type]

    assert rows[0].roe is None


def test_missing_pretax_omits_tax_rate_nopat_and_roic() -> None:
    inputs = _adbe_inputs()
    inputs["pretax_income"] = _series("pretax_income", {})

    rows = compute_capital_efficiency(display_years=2, **inputs)  # type: ignore[arg-type]
    latest = rows[0]

    assert latest.effective_tax_rate is None
    assert latest.nopat is None
    assert latest.roic is None


def test_reported_and_derived_fields_are_distinct_types() -> None:
    rows = compute_capital_efficiency(display_years=2, **_adbe_inputs())  # type: ignore[arg-type]
    row = rows[0]

    assert isinstance(row, CapitalEfficiencyRow)
    assert isinstance(row.total_assets, AnnualObservation)
    assert isinstance(row.net_cash, int)
    assert isinstance(row.roe, float)
    assert not isinstance(row.net_cash, AnnualObservation)

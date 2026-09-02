"""Derived Adobe capital-efficiency metrics and per-fiscal-year alignment.

This module supports OwnerLens Slice 1E. It aligns the canonical fiscal-year-end
balance-sheet series with the operating-income, net-income, income-tax-expense,
and pretax-income duration series and derives cash position, net cash or net
debt, effective tax rate, NOPAT, invested capital, and the average-balance
returns ROA, ROE, and ROIC. Derived metrics are calculated deterministically and
kept in a distinct row type. A derived value is produced only when its inputs
exist, any required prior-year baseline exists, and its denominator is non-zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from owner_lens._annual import AnnualObservation
from owner_lens.balance_sheet import (
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.operating_income import (
    AnnualOperatingIncomeSeries,
    normalize_annual_operating_income,
)
from owner_lens.reported import (
    AnnualSeries,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_pretax_income,
)

__all__ = [
    "CapitalEfficiencyRow",
    "capital_efficiency_from_facts",
    "compute_capital_efficiency",
]


@dataclass(frozen=True)
class CapitalEfficiencyRow:
    """One fiscal year of balance-sheet facts and derived capital-efficiency metrics."""

    fiscal_year: int
    # Reported facts (source provenance preserved).
    cash: AnnualObservation | None
    short_term_investments: AnnualObservation | None
    current_debt: AnnualObservation | None
    long_term_debt: AnnualObservation | None
    total_assets: AnnualObservation | None
    total_equity: AnnualObservation | None
    # Derived metrics (calculated, not reported).
    cash_plus_sti: int | None
    total_debt: int | None
    net_cash: int | None
    effective_tax_rate: float | None
    nopat: int | None
    invested_capital: int | None
    roa: float | None
    roe: float | None
    roic: float | None


def _by_year(observations: tuple[AnnualObservation, ...]) -> dict[int, AnnualObservation]:
    return {obs.fiscal_year: obs for obs in observations}


def _value(obs: AnnualObservation | None) -> int | None:
    return obs.value if obs is not None else None


def _average(current: int | None, prior: int | None) -> float | None:
    if current is None or prior is None:
        return None
    return (current + prior) / 2


def _divide(numerator: int | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_capital_efficiency(
    *,
    operating_income: AnnualOperatingIncomeSeries,
    net_income: AnnualSeries,
    income_tax_expense: AnnualSeries,
    pretax_income: AnnualSeries,
    cash: AnnualSeries,
    short_term_investments: AnnualSeries,
    current_debt: AnnualSeries,
    long_term_debt: AnnualSeries,
    total_assets: AnnualSeries,
    total_equity: AnnualSeries,
    display_years: int = 5,
) -> tuple[CapitalEfficiencyRow, ...]:
    """Align all series by fiscal year and derive capital-efficiency metrics."""
    oi = _by_year(operating_income.observations)
    ni = _by_year(net_income.observations)
    tax = _by_year(income_tax_expense.observations)
    pretax = _by_year(pretax_income.observations)
    cash_by = _by_year(cash.observations)
    sti_by = _by_year(short_term_investments.observations)
    cur_debt_by = _by_year(current_debt.observations)
    lt_debt_by = _by_year(long_term_debt.observations)
    assets_by = _by_year(total_assets.observations)
    equity_by = _by_year(total_equity.observations)

    # Balance-sheet-derived quantities per year, used for values and averages.
    cash_plus_sti: dict[int, int] = {}
    total_debt: dict[int, int] = {}
    invested_capital: dict[int, int] = {}
    all_years = (
        set(cash_by)
        | set(sti_by)
        | set(cur_debt_by)
        | set(lt_debt_by)
        | set(assets_by)
        | set(equity_by)
    )
    for year in all_years:
        cash_obs = cash_by.get(year)
        if cash_obs is not None:
            cash_plus_sti[year] = cash_obs.value + (_value(sti_by.get(year)) or 0)
        lt = lt_debt_by.get(year)
        if lt is not None:
            total_debt[year] = (_value(cur_debt_by.get(year)) or 0) + lt.value
        if year in cash_plus_sti and year in total_debt and year in equity_by:
            invested_capital[year] = (
                total_debt[year] + equity_by[year].value - cash_plus_sti[year]
            )

    displayed = sorted(set(oi) | set(ni) | all_years, reverse=True)[:display_years]
    rows: list[CapitalEfficiencyRow] = []
    for year in displayed:
        prior = year - 1
        ni_value = _value(ni.get(year))

        # Effective tax rate and NOPAT.
        pretax_value = _value(pretax.get(year))
        tax_value = _value(tax.get(year))
        tax_rate = _divide(tax_value, pretax_value)
        oi_value = _value(oi.get(year))
        nopat = (
            round(oi_value * (1 - tax_rate))
            if oi_value is not None and tax_rate is not None
            else None
        )

        avg_assets = _average(_value(assets_by.get(year)), _value(assets_by.get(prior)))
        avg_equity = _average(_value(equity_by.get(year)), _value(equity_by.get(prior)))
        avg_ic = _average(invested_capital.get(year), invested_capital.get(prior))

        rows.append(
            CapitalEfficiencyRow(
                fiscal_year=year,
                cash=cash_by.get(year),
                short_term_investments=sti_by.get(year),
                current_debt=cur_debt_by.get(year),
                long_term_debt=lt_debt_by.get(year),
                total_assets=assets_by.get(year),
                total_equity=equity_by.get(year),
                cash_plus_sti=cash_plus_sti.get(year),
                total_debt=total_debt.get(year),
                net_cash=(
                    cash_plus_sti[year] - total_debt[year]
                    if year in cash_plus_sti and year in total_debt
                    else None
                ),
                effective_tax_rate=tax_rate,
                nopat=nopat,
                invested_capital=invested_capital.get(year),
                roa=_divide(ni_value, avg_assets),
                roe=_divide(ni_value, avg_equity),
                roic=_divide(nopat, avg_ic),
            )
        )
    return tuple(rows)


def capital_efficiency_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> tuple[CapitalEfficiencyRow, ...]:
    """Normalize all series from a payload, then derive capital efficiency.

    Balance-sheet series are fetched with one extra baseline year so the earliest
    displayed year has a prior fiscal-year-end for average denominators.
    """
    baseline_years = max_years + 1
    return compute_capital_efficiency(
        operating_income=normalize_annual_operating_income(
            raw_facts, ticker=ticker, max_years=max_years
        ),
        net_income=normalize_net_income(raw_facts, ticker=ticker, max_years=max_years),
        income_tax_expense=normalize_income_tax_expense(
            raw_facts, ticker=ticker, max_years=max_years
        ),
        pretax_income=normalize_pretax_income(
            raw_facts, ticker=ticker, max_years=max_years
        ),
        cash=normalize_cash(raw_facts, ticker=ticker, max_years=baseline_years),
        short_term_investments=normalize_short_term_investments(
            raw_facts, ticker=ticker, max_years=baseline_years
        ),
        current_debt=normalize_current_debt(
            raw_facts, ticker=ticker, max_years=baseline_years
        ),
        long_term_debt=normalize_long_term_debt(
            raw_facts, ticker=ticker, max_years=baseline_years
        ),
        total_assets=normalize_total_assets(
            raw_facts, ticker=ticker, max_years=baseline_years
        ),
        total_equity=normalize_total_equity(
            raw_facts, ticker=ticker, max_years=baseline_years
        ),
        display_years=max_years,
    )

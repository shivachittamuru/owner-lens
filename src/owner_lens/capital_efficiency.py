"""Derived Adobe capital-efficiency metrics and per-fiscal-year alignment.

This module supports OwnerLens Slice 1E. It aligns the canonical fiscal-year-end
balance-sheet series with the operating-income, net-income, income-tax-expense,
and pretax-income duration series and derives cash position, net cash or net
debt, effective tax rate, NOPAT, invested capital, and the average-balance
returns ROA, ROE, and ROIC. Derived metrics are calculated deterministically and
kept in a distinct row type. A derived value is produced only when its inputs
exist, any required prior-year baseline exists, and its denominator is non-zero.

Since Slice 5A the module consumes only a provider-neutral
``CanonicalFinancialHistory``; ``capital_efficiency_from_facts`` remains as a
thin compatibility wrapper that maps raw SEC Company Facts through the SEC adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from owner_lens.canonical import (
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalSeries,
)
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "CapitalEfficiencyRow",
    "capital_efficiency_from_facts",
    "capital_efficiency_from_history",
    "compute_capital_efficiency",
]


@dataclass(frozen=True)
class CapitalEfficiencyRow:
    """One fiscal year of balance-sheet facts and derived capital-efficiency metrics."""

    fiscal_year: int
    # Reported facts (source provenance preserved).
    cash: CanonicalFact | None
    short_term_investments: CanonicalFact | None
    current_debt: CanonicalFact | None
    long_term_debt: CanonicalFact | None
    total_assets: CanonicalFact | None
    total_equity: CanonicalFact | None
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


def _by_year(observations: tuple[CanonicalFact, ...]) -> dict[int, CanonicalFact]:
    return {obs.fiscal_year: obs for obs in observations}


def _value(obs: CanonicalFact | None) -> int | None:
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
    operating_income: CanonicalSeries,
    net_income: CanonicalSeries,
    income_tax_expense: CanonicalSeries,
    pretax_income: CanonicalSeries,
    cash: CanonicalSeries,
    short_term_investments: CanonicalSeries,
    current_debt: CanonicalSeries,
    long_term_debt: CanonicalSeries,
    total_assets: CanonicalSeries,
    total_equity: CanonicalSeries,
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


def capital_efficiency_from_history(
    history: CanonicalFinancialHistory,
) -> tuple[CapitalEfficiencyRow, ...]:
    """Derive capital efficiency from a provider-neutral canonical history.

    Instant (balance-sheet) series carry one extra baseline fiscal-year-end so
    the earliest displayed year has a prior balance for average denominators;
    ``history.max_years`` bounds the displayed years.
    """
    return compute_capital_efficiency(
        operating_income=history.require("operating_income"),
        net_income=history.require("net_income"),
        income_tax_expense=history.require("income_tax_expense"),
        pretax_income=history.require("pretax_income"),
        cash=history.require("cash"),
        short_term_investments=history.require("short_term_investments"),
        current_debt=history.require("current_debt"),
        long_term_debt=history.require("long_term_debt"),
        total_assets=history.require("total_assets"),
        total_equity=history.require("total_equity"),
        display_years=history.max_years,
    )


def capital_efficiency_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> tuple[CapitalEfficiencyRow, ...]:
    """Compatibility wrapper: map raw SEC Company Facts, then derive capital efficiency."""
    return capital_efficiency_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
    )

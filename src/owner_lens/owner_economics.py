"""Derived Adobe owner-economics metrics and per-fiscal-year alignment.

This module supports OwnerLens Slice 1D. It aligns the canonical revenue,
operating-income, net-income, operating-cash-flow, capital-expenditure, and
diluted-share series by economic fiscal year and derives net margin, free cash
flow, FCF margin, FCF per diluted share, and adjacent-year growth. Derived
metrics are calculated deterministically in application code and are kept in a
distinct row type so a consumer can tell a filed fact from a calculated metric.
A derived value is produced only when its inputs exist and its denominator is
non-zero.

Since Slice 5A the module consumes only a provider-neutral
``CanonicalFinancialHistory``; ``owner_economics_from_facts`` remains as a thin
compatibility wrapper that maps raw SEC Company Facts through the SEC adapter.
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
    "OwnerEconomicsRow",
    "compute_owner_economics",
    "owner_economics_from_facts",
    "owner_economics_from_history",
]


@dataclass(frozen=True)
class OwnerEconomicsRow:
    """One fiscal year of reported facts and derived owner-economics metrics."""

    fiscal_year: int
    # Reported facts (source provenance preserved).
    revenue: CanonicalFact | None
    operating_income: CanonicalFact | None
    net_income: CanonicalFact | None
    operating_cash_flow: CanonicalFact | None
    capital_expenditures: CanonicalFact | None
    diluted_shares: CanonicalFact | None
    # Derived metrics (calculated, not reported).
    operating_margin: float | None
    net_margin: float | None
    free_cash_flow: int | None
    fcf_margin: float | None
    fcf_per_share: float | None
    fcf_growth: float | None
    fcf_per_share_growth: float | None
    diluted_share_growth: float | None


def _by_year(observations: tuple[CanonicalFact, ...]) -> dict[int, CanonicalFact]:
    return {obs.fiscal_year: obs for obs in observations}


def _ratio(numerator: int | None, denominator: CanonicalFact | None) -> float | None:
    if numerator is None or denominator is None or denominator.value == 0:
        return None
    return numerator / denominator.value


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / prior


def compute_owner_economics(
    *,
    revenue: CanonicalSeries,
    operating_income: CanonicalSeries,
    net_income: CanonicalSeries,
    operating_cash_flow: CanonicalSeries,
    capital_expenditures: CanonicalSeries,
    diluted_shares: CanonicalSeries,
) -> tuple[OwnerEconomicsRow, ...]:
    """Align the six series by fiscal year and derive owner-economics metrics."""
    rev = _by_year(revenue.observations)
    oi = _by_year(operating_income.observations)
    ni = _by_year(net_income.observations)
    ocf = _by_year(operating_cash_flow.observations)
    capex = _by_year(capital_expenditures.observations)
    shares = _by_year(diluted_shares.observations)

    years = sorted(
        set(rev) | set(oi) | set(ni) | set(ocf) | set(capex) | set(shares),
        reverse=True,
    )

    # Free cash flow and FCF/share per year, used for both the row and growth.
    free_cash_flow: dict[int, int] = {}
    fcf_per_share: dict[int, float] = {}
    for year in years:
        ocf_obs = ocf.get(year)
        capex_obs = capex.get(year)
        if ocf_obs is not None and capex_obs is not None:
            fcf = ocf_obs.value - abs(capex_obs.value)
            free_cash_flow[year] = fcf
            fps = _ratio(fcf, shares.get(year))
            if fps is not None:
                fcf_per_share[year] = fps

    rows: list[OwnerEconomicsRow] = []
    for year in years:
        rev_obs = rev.get(year)
        ni_obs = ni.get(year)
        year_fcf = free_cash_flow.get(year)
        prior = year - 1
        rows.append(
            OwnerEconomicsRow(
                fiscal_year=year,
                revenue=rev_obs,
                operating_income=oi.get(year),
                net_income=ni_obs,
                operating_cash_flow=ocf.get(year),
                capital_expenditures=capex.get(year),
                diluted_shares=shares.get(year),
                operating_margin=_ratio(
                    oi[year].value if year in oi else None, rev_obs
                ),
                net_margin=_ratio(ni_obs.value if ni_obs else None, rev_obs),
                free_cash_flow=year_fcf,
                fcf_margin=_ratio(year_fcf, rev_obs),
                fcf_per_share=fcf_per_share.get(year),
                fcf_growth=_growth(year_fcf, free_cash_flow.get(prior)),
                fcf_per_share_growth=_growth(
                    fcf_per_share.get(year), fcf_per_share.get(prior)
                ),
                diluted_share_growth=_growth(
                    shares[year].value if year in shares else None,
                    shares[prior].value if prior in shares else None,
                ),
            )
        )
    return tuple(rows)


def owner_economics_from_history(
    history: CanonicalFinancialHistory,
) -> tuple[OwnerEconomicsRow, ...]:
    """Derive owner economics from a provider-neutral canonical history.

    Diluted weighted-average shares can be unsupported for some companies (for
    example, Visa). When they are, the empty series is used so the per-share
    fields degrade to ``None`` while every non-per-share metric is still derived;
    no share count is ever fabricated or substituted.
    """
    diluted_shares = history.require("diluted_shares", allow_unsupported=True)
    return compute_owner_economics(
        revenue=history.require("revenue"),
        operating_income=history.require("operating_income"),
        net_income=history.require("net_income"),
        operating_cash_flow=history.require("operating_cash_flow"),
        capital_expenditures=history.require("capital_expenditures"),
        diluted_shares=diluted_shares,
    )


def owner_economics_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> tuple[OwnerEconomicsRow, ...]:
    """Compatibility wrapper: map raw SEC Company Facts, then derive owner economics."""
    return owner_economics_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
    )

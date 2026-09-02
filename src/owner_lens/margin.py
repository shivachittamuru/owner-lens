"""Derived operating margin and per-fiscal-year metric alignment.

This module supports OwnerLens Slice 1C. Operating margin is a derived metric,
calculated deterministically in application code from the canonical revenue and
operating-income series. It is kept in a type distinct from reported observations
so a consumer can always tell a filed fact from a calculated ratio. A margin is
produced only where both canonical inputs exist and revenue is non-zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from owner_lens._annual import AnnualObservation
from owner_lens.operating_income import AnnualOperatingIncomeSeries
from owner_lens.revenue import AnnualRevenueSeries

__all__ = [
    "AnnualMetricRow",
    "OperatingMargin",
    "align_annual_metrics",
    "operating_margins",
]


@dataclass(frozen=True)
class OperatingMargin:
    """A derived annual operating margin referencing its two reported inputs."""

    fiscal_year: int
    value: float
    revenue: int
    operating_income: int
    revenue_accession: str
    operating_income_accession: str


@dataclass(frozen=True)
class AnnualMetricRow:
    """One fiscal year aligning revenue, operating income, and margin."""

    fiscal_year: int
    revenue: AnnualObservation | None
    operating_income: AnnualObservation | None
    operating_margin: OperatingMargin | None


def _derive_margin(
    fiscal_year: int,
    revenue: AnnualObservation | None,
    operating_income: AnnualObservation | None,
) -> OperatingMargin | None:
    # Explicit: a margin requires both inputs and a non-zero revenue divisor.
    if revenue is None or operating_income is None or revenue.value == 0:
        return None
    return OperatingMargin(
        fiscal_year=fiscal_year,
        value=operating_income.value / revenue.value,
        revenue=revenue.value,
        operating_income=operating_income.value,
        revenue_accession=revenue.accession,
        operating_income_accession=operating_income.accession,
    )


def align_annual_metrics(
    revenue: AnnualRevenueSeries,
    operating_income: AnnualOperatingIncomeSeries,
) -> tuple[AnnualMetricRow, ...]:
    """Align revenue and operating income by economic fiscal year."""
    revenue_by_year = {obs.fiscal_year: obs for obs in revenue.observations}
    income_by_year = {obs.fiscal_year: obs for obs in operating_income.observations}

    years = sorted(set(revenue_by_year) | set(income_by_year), reverse=True)
    rows: list[AnnualMetricRow] = []
    for year in years:
        rev = revenue_by_year.get(year)
        inc = income_by_year.get(year)
        rows.append(
            AnnualMetricRow(
                fiscal_year=year,
                revenue=rev,
                operating_income=inc,
                operating_margin=_derive_margin(year, rev, inc),
            )
        )
    return tuple(rows)


def operating_margins(
    revenue: AnnualRevenueSeries,
    operating_income: AnnualOperatingIncomeSeries,
) -> tuple[OperatingMargin, ...]:
    """Return the computable operating margins, newest first."""
    return tuple(
        row.operating_margin
        for row in align_annual_metrics(revenue, operating_income)
        if row.operating_margin is not None
    )

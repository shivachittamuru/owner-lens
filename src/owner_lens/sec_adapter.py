"""SEC Company Facts adapter: raw SEC payload -> canonical financial history.

This is the only module that knows both the SEC normalizers and the canonical
model. It reuses every existing SEC normalization rule unchanged (concept
preferences, per-company overrides, full-year and instant selection,
comparative deduplication, ambiguity detection) and translates each result into
provider-neutral ``CanonicalFact`` values that keep SEC provenance as data.

Per-metric normalization failures are stored on the metric's series, not raised,
so each downstream layer fails only when it actually requires an unusable metric
(see ``CanonicalFinancialHistory.require``). Duration metrics use the requested
``max_years`` window; instant metrics use one extra baseline fiscal-year-end for
average-balance denominators, exactly as capital efficiency always has.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from owner_lens._annual import (
    DEFAULT_MAX_YEARS,
    DEFAULT_TICKER,
    AmbiguousValueError,
    AnnualObservation,
    ConceptNotFoundError,
    MalformedFactsError,
    canonicalize_ticker,
)
from owner_lens.balance_sheet import (
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.canonical import (
    CANONICAL_METRICS,
    CanonicalDataError,
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalSeries,
    MetricKind,
    MetricStatus,
)
from owner_lens.operating_income import (
    AmbiguousOperatingIncomeError,
    OperatingIncomeConceptNotFoundError,
    normalize_annual_operating_income,
)
from owner_lens.reported import (
    normalize_capital_expenditures,
    normalize_diluted_shares,
    normalize_dividends_paid,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_operating_cash_flow,
    normalize_pretax_income,
    normalize_repurchases,
    normalize_stock_based_compensation,
)
from owner_lens.revenue import (
    AmbiguousRevenueError,
    RevenueConceptNotFoundError,
    normalize_annual_revenue,
)

__all__ = ["SEC_PROVIDER", "canonical_history_from_sec"]

SEC_PROVIDER: Final = "sec"

_Normalizer = Callable[..., Any]

# One SEC normalizer per canonical metric, in canonical vocabulary order.
_NORMALIZERS: Final[dict[str, _Normalizer]] = {
    "revenue": normalize_annual_revenue,
    "operating_income": normalize_annual_operating_income,
    "net_income": normalize_net_income,
    "operating_cash_flow": normalize_operating_cash_flow,
    "capital_expenditures": normalize_capital_expenditures,
    "diluted_shares": normalize_diluted_shares,
    "income_tax_expense": normalize_income_tax_expense,
    "pretax_income": normalize_pretax_income,
    "repurchases": normalize_repurchases,
    "stock_based_compensation": normalize_stock_based_compensation,
    "dividends_paid": normalize_dividends_paid,
    "cash": normalize_cash,
    "short_term_investments": normalize_short_term_investments,
    "current_debt": normalize_current_debt,
    "long_term_debt": normalize_long_term_debt,
    "total_assets": normalize_total_assets,
    "total_equity": normalize_total_equity,
}

_UNSUPPORTED_ERRORS: Final = (
    ConceptNotFoundError,
    RevenueConceptNotFoundError,
    OperatingIncomeConceptNotFoundError,
)
_INVALID_ERRORS: Final = (
    AmbiguousValueError,
    AmbiguousRevenueError,
    AmbiguousOperatingIncomeError,
    MalformedFactsError,
)


def _to_fact(metric: str, kind: MetricKind, obs: AnnualObservation) -> CanonicalFact:
    return CanonicalFact(
        metric=metric,
        value=obs.value,
        unit=obs.unit,
        fiscal_year=obs.fiscal_year,
        fiscal_period=obs.fiscal_period,
        period_end=obs.period_end,
        period_start=obs.period_start if kind is MetricKind.DURATION else None,
        provider=SEC_PROVIDER,
        provider_field=obs.concept,
        form=obs.form,
        filed=obs.filed,
        accession=obs.accession,
    )


def _failed(metric: str, unit: str, status: MetricStatus, exc: CanonicalDataError) -> CanonicalSeries:
    return CanonicalSeries(metric, unit, status, reason=str(exc), error=exc)


def canonical_history_from_sec(
    raw_facts: dict[str, Any],
    *,
    ticker: str = DEFAULT_TICKER,
    max_years: int = DEFAULT_MAX_YEARS,
) -> CanonicalFinancialHistory:
    """Map raw SEC Company Facts into a provider-neutral canonical financial history."""
    canonical_ticker = canonicalize_ticker(ticker)
    series: list[CanonicalSeries] = []
    for spec in CANONICAL_METRICS:
        window = max_years + 1 if spec.kind is MetricKind.INSTANT else max_years
        try:
            normalized = _NORMALIZERS[spec.name](
                raw_facts, ticker=canonical_ticker, max_years=window
            )
        except _UNSUPPORTED_ERRORS as exc:
            series.append(_failed(spec.name, spec.unit, MetricStatus.UNSUPPORTED, exc))
            continue
        except _INVALID_ERRORS as exc:
            series.append(_failed(spec.name, spec.unit, MetricStatus.INVALID, exc))
            continue
        facts = tuple(_to_fact(spec.name, spec.kind, obs) for obs in normalized.observations)
        status = MetricStatus.AVAILABLE if facts else MetricStatus.STRUCTURALLY_ABSENT
        series.append(CanonicalSeries(spec.name, spec.unit, status, facts))
    return CanonicalFinancialHistory(
        ticker=canonical_ticker, max_years=max_years, series=tuple(series)
    )

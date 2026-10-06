"""FMP adapter: annual FMP financial statements -> canonical financial history.

FMP supplies provider-normalized reported line items. This module maps only the
line items OwnerLens's canonical vocabulary needs and never uses FMP's
precomputed free cash flow, margins, ratios, growth, or ROIC: OwnerLens computes
those itself downstream of the canonical boundary.

FMP-specific mapping policy, all deterministic and documented here:

* Each canonical metric maps to exactly one FMP statement field, preferring FMP's
  as-reported line item over its standardized summary variant (for example
  ``investmentsInPropertyPlantAndEquipment`` rather than ``capitalExpenditure``,
  which live ADBE data showed can differ). ``provider_field`` records the field.
* Fiscal year follows the canonical rule: the calendar year of the period end
  (FMP's ``date``). FMP supplies no period start, form, or accession, so those
  stay ``None``; ``filed`` is FMP's ``filingDate`` when present.
* Cash outflows (capital expenditures, repurchases, dividends) arrive negative and
  are normalized to positive magnitudes. A positive outflow is ``INVALID``.
* FMP fills unreported line items with zero. A zero is therefore not trusted as a
  value where zero is economically implausible (revenue, diluted shares, total
  assets): that year is treated as not supplied. Dividends and short-term
  investments that are zero in every year are ``STRUCTURALLY_ABSENT``.
* A field absent from every row is ``UNSUPPORTED``. Non-numeric values,
  conflicting duplicate fiscal years,
  or a non-USD reporting currency make the metric ``INVALID``.

Duration metrics use the latest ``max_years`` fiscal years; instant metrics may
carry one extra baseline year when the statements contain it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from owner_lens.canonical import (
    CANONICAL_METRICS,
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalMetricSpec,
    CanonicalSeries,
    MetricInvalidError,
    MetricKind,
    MetricStatus,
    MetricUnsupportedError,
)
from owner_lens.fmp import FmpStatements

__all__ = [
    "FMP_FIELD_MAP",
    "FMP_PROVIDER",
    "FmpFieldMapping",
    "FmpInvalidMetricError",
    "FmpUnsupportedMetricError",
    "canonical_history_from_fmp",
]

FMP_PROVIDER: Final = "fmp"
_USD: Final = "USD"


class FmpUnsupportedMetricError(MetricUnsupportedError):
    """Raised when FMP supplies no trusted field value for a required metric."""


class FmpInvalidMetricError(MetricInvalidError):
    """Raised when FMP data for a metric is malformed, conflicting, or mis-signed."""


@dataclass(frozen=True)
class FmpFieldMapping:
    """How one canonical metric is read from one FMP statement field."""

    statement: str
    field: str
    outflow: bool = False
    zero_is_missing: bool = False
    all_zero_is_absent: bool = False


FMP_FIELD_MAP: Final[dict[str, FmpFieldMapping]] = {
    "revenue": FmpFieldMapping("income", "revenue", zero_is_missing=True),
    "operating_income": FmpFieldMapping("income", "operatingIncome"),
    "net_income": FmpFieldMapping("income", "netIncome"),
    "operating_cash_flow": FmpFieldMapping("cash_flow", "netCashProvidedByOperatingActivities"),
    "capital_expenditures": FmpFieldMapping(
        "cash_flow", "investmentsInPropertyPlantAndEquipment", outflow=True
    ),
    "diluted_shares": FmpFieldMapping("income", "weightedAverageShsOutDil", zero_is_missing=True),
    "income_tax_expense": FmpFieldMapping("income", "incomeTaxExpense"),
    "pretax_income": FmpFieldMapping("income", "incomeBeforeTax"),
    "repurchases": FmpFieldMapping("cash_flow", "commonStockRepurchased", outflow=True),
    "stock_based_compensation": FmpFieldMapping("cash_flow", "stockBasedCompensation"),
    "dividends_paid": FmpFieldMapping(
        "cash_flow", "commonDividendsPaid", outflow=True, all_zero_is_absent=True
    ),
    "cash": FmpFieldMapping("balance_sheet", "cashAndCashEquivalents"),
    "short_term_investments": FmpFieldMapping(
        "balance_sheet", "shortTermInvestments", all_zero_is_absent=True
    ),
    "current_debt": FmpFieldMapping("balance_sheet", "shortTermDebt"),
    "long_term_debt": FmpFieldMapping("balance_sheet", "longTermDebt"),
    "total_assets": FmpFieldMapping("balance_sheet", "totalAssets", zero_is_missing=True),
    "total_equity": FmpFieldMapping("balance_sheet", "totalStockholdersEquity"),
}


@dataclass(frozen=True)
class _Row:
    fiscal_year: int
    period_end: date
    filed: date | None
    currency: Any
    data: dict[str, Any]


def _parse_rows(rows: tuple[dict[str, Any], ...]) -> list[_Row]:
    parsed: list[_Row] = []
    for row in rows:
        period_end = date.fromisoformat(str(row["date"]))
        filed_raw = row.get("filingDate")
        try:
            filed = date.fromisoformat(str(filed_raw)[:10]) if filed_raw else None
        except ValueError:
            filed = None
        parsed.append(
            _Row(period_end.year, period_end, filed, row.get("reportedCurrency"), row)
        )
    return sorted(parsed, key=lambda r: (r.period_end, r.filed or date.min), reverse=True)


def _as_int(value: Any, field: str, fiscal_year: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FmpInvalidMetricError(
            f"FMP field {field} for FY{fiscal_year} is not numeric: {value!r}."
        )
    if isinstance(value, float):
        if not value.is_integer():
            raise FmpInvalidMetricError(
                f"FMP field {field} for FY{fiscal_year} is not a whole number: {value!r}."
            )
        return int(value)
    return value


def _year_values(rows: list[_Row], mapping: FmpFieldMapping) -> dict[int, tuple[int, _Row]]:
    """Return one validated, sign-normalized value per fiscal year."""
    by_year: dict[int, tuple[int, _Row]] = {}
    for row in rows:
        raw = row.data.get(mapping.field)
        if raw is None:
            continue
        value = _as_int(raw, mapping.field, row.fiscal_year)
        if mapping.outflow:
            if value > 0:
                raise FmpInvalidMetricError(
                    f"FMP outflow field {mapping.field} is positive ({value}) for "
                    f"FY{row.fiscal_year}; the sign is ambiguous."
                )
            value = -value
        if value == 0 and mapping.zero_is_missing:
            continue
        existing = by_year.get(row.fiscal_year)
        if existing is not None:
            if existing[0] != value:
                raise FmpInvalidMetricError(
                    f"FY{row.fiscal_year} has conflicting FMP {mapping.field} values: "
                    f"{sorted({existing[0], value})}."
                )
            continue
        by_year[row.fiscal_year] = (value, row)
    return by_year


def _map_metric(
    spec: CanonicalMetricSpec, statements: FmpStatements, max_years: int
) -> CanonicalSeries:
    mapping = FMP_FIELD_MAP[spec.name]
    raw_rows = statements.rows(mapping.statement)
    if not any(mapping.field in row for row in raw_rows):
        error = FmpUnsupportedMetricError(
            f"FMP {mapping.statement} statement has no {mapping.field} field."
        )
        return CanonicalSeries(
            spec.name, spec.unit, MetricStatus.UNSUPPORTED, reason=str(error), error=error
        )
    window = max_years + 1 if spec.kind is MetricKind.INSTANT else max_years
    try:
        by_year = _year_values(_parse_rows(raw_rows), mapping)
    except FmpInvalidMetricError as exc:
        return CanonicalSeries(
            spec.name, spec.unit, MetricStatus.INVALID, reason=str(exc), error=exc
        )
    years = sorted(by_year, reverse=True)[:window]
    foreign = [y for y in years if spec.unit == _USD and by_year[y][1].currency != _USD]
    if foreign:
        currency_error = FmpInvalidMetricError(
            f"FMP reports FY{foreign[0]} {mapping.field} in "
            f"{by_year[foreign[0]][1].currency!r}, not USD."
        )
        return CanonicalSeries(
            spec.name,
            spec.unit,
            MetricStatus.INVALID,
            reason=str(currency_error),
            error=currency_error,
        )
    if mapping.all_zero_is_absent and years and all(by_year[y][0] == 0 for y in years):
        return CanonicalSeries(
            spec.name,
            spec.unit,
            MetricStatus.STRUCTURALLY_ABSENT,
            reason=f"FMP reports {mapping.field} as zero in every fiscal year.",
        )
    if not years:
        error = FmpUnsupportedMetricError(
            f"FMP supplies no usable {mapping.field} value in any fiscal year."
        )
        return CanonicalSeries(
            spec.name, spec.unit, MetricStatus.UNSUPPORTED, reason=str(error), error=error
        )
    facts = tuple(
        CanonicalFact(
            metric=spec.name,
            value=by_year[year][0],
            unit=spec.unit,
            fiscal_year=year,
            fiscal_period="FY",
            period_end=by_year[year][1].period_end,
            period_start=None,
            provider=FMP_PROVIDER,
            provider_field=mapping.field,
            form=None,
            filed=by_year[year][1].filed,
            accession=None,
        )
        for year in years
    )
    return CanonicalSeries(spec.name, spec.unit, MetricStatus.AVAILABLE, facts)


def canonical_history_from_fmp(
    statements: FmpStatements,
    *,
    max_years: int = 5,
) -> CanonicalFinancialHistory:
    """Map validated FMP annual statements into a provider-neutral canonical history."""
    series = tuple(_map_metric(spec, statements, max_years) for spec in CANONICAL_METRICS)
    return CanonicalFinancialHistory(
        ticker=statements.symbol, max_years=max_years, series=series
    )

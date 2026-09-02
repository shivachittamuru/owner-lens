---
title: Core Owner Economics Public API Contract
description: Minimal Python library contract for Adobe reported facts and owner-economics metrics
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds deterministic, offline normalization for four reported facts (net income, operating
cash flow, capital expenditures, diluted weighted-average shares) and a derived owner-economics view
combining them with the existing revenue and operating-income series. It supports ADBE only and adds
no network access. It reuses and preserves all prior slices. This contract does not define a
generalized metric framework.

## Internal primitive change (`owner_lens._annual`)

`select_annual_series` gains one additive keyword parameter `unit: str = TARGET_UNIT`. Value metrics
use the default `USD`; diluted shares use `shares`. `AnnualObservation` and all other behavior are
unchanged. `_annual` remains internal.

## Reported metric normalization (`owner_lens.reported`)

### `AnnualSeries`

Immutable generic reported-metric series with readable attributes:

| Attribute      | Type                            | Contract                                   |
|----------------|---------------------------------|--------------------------------------------|
| `metric`       | `str`                           | Metric name                                |
| `ticker`       | `str`                           | `ADBE`                                      |
| `concept`      | `str`                           | Single concept shared by all observations  |
| `unit`         | `str`                           | Unit shared by all observations            |
| `observations` | `tuple[AnnualObservation, ...]` | At most one per year, newest first         |

### `MetricSpec`

Immutable specification with `metric: str`, `concept_preference: tuple[str, ...]`, and `unit: str`.

The module defines: `NET_INCOME`, `OPERATING_CASH_FLOW`, `CAPITAL_EXPENDITURES`, `DILUTED_SHARES`.

### Functions

```text
normalize_annual_metric(
    raw_facts: dict[str, Any],
    spec: MetricSpec,
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> AnnualSeries

normalize_net_income(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_operating_cash_flow(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_capital_expenditures(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_diluted_shares(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
```

Contract for each:

1. Accept the raw Company Facts mapping produced by Slice 1 retrieval.
2. Reject any `ticker` other than `ADBE`.
3. Select one concept using the spec's documented preference order and the spec's unit.
4. Keep only that-unit, `fp == "FY"` observations whose period duration is 350 to 380 days.
5. Derive each observation's fiscal year from its period end date.
6. Collapse identical comparative repeats per fiscal year, retaining earliest-filed provenance.
7. Return up to `max_years` observations ordered by fiscal year descending.
8. Perform no network access and no value estimation, interpolation, or aggregation.

The reported CapEx observation preserves the source value unchanged; the positive-magnitude
canonicalization is applied only in free-cash-flow derivation.

## Derived owner economics (`owner_lens.owner_economics`)

### `OwnerEconomicsRow`

Immutable per-year row with readable attributes for the reported observations and derived metrics
listed in the [data model](data-model.md): `fiscal_year`; optional `revenue`, `operating_income`,
`net_income`, `operating_cash_flow`, `capital_expenditures`, `diluted_shares` (each
`AnnualObservation | None`); and optional derived `operating_margin`, `net_margin`, `free_cash_flow`,
`fcf_margin`, `fcf_per_share`, `fcf_growth`, `fcf_per_share_growth`, `diluted_share_growth`.

### Functions

```text
compute_owner_economics(
    *,
    revenue: AnnualRevenueSeries,
    operating_income: AnnualOperatingIncomeSeries,
    net_income: AnnualSeries,
    operating_cash_flow: AnnualSeries,
    capital_expenditures: AnnualSeries,
    diluted_shares: AnnualSeries,
) -> tuple[OwnerEconomicsRow, ...]

owner_economics_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> tuple[OwnerEconomicsRow, ...]
```

Contract:

1. `compute_owner_economics` aligns the six series by economic fiscal year and derives per-year and
   adjacent-year growth metrics deterministically.
2. `owner_economics_from_facts` normalizes all six series from the payload, then calls
   `compute_owner_economics`.
3. Free cash flow uses `operating_cash_flow - abs(capital_expenditures)`.
4. Each derived metric is present only when its inputs exist and its denominator is non-zero;
   otherwise it is `None`.
5. Growth compares only immediately adjacent fiscal years with a present, non-zero prior value.
6. Rows are ordered by fiscal year descending. No network access occurs.

## Exceptions

New reported-metric failures use shared generic errors:

| Exception                | Meaning                                                     |
|--------------------------|-------------------------------------------------------------|
| `UnsupportedTickerError` | Input ticker is not ADBE                                    |
| `MalformedFactsError`    | Payload lacks a usable `facts.us-gaap` fact structure       |
| `ConceptNotFoundError`   | No preference-order concept has a qualifying observation     |
| `AmbiguousValueError`    | A fiscal year has conflicting distinct full-year values      |

`ConceptNotFoundError` and `AmbiguousValueError` messages name the affected metric and, for
ambiguity, the fiscal year. Derived and growth functions do not raise on missing inputs or zero
denominators; they omit the affected value. No failure is converted to `None`, an empty series, or a
partial result, except the documented explicit omission of an individual derived value.

## Preserved public surface

All Slice 1A through 1C exports remain and behave exactly as before: `SecClient` and the retrieval
types; `normalize_annual_revenue`, `AnnualRevenueSeries`, `AnnualRevenueObservation`,
`REVENUE_CONCEPT_PREFERENCE`, and revenue errors; `normalize_annual_operating_income`,
`AnnualOperatingIncomeSeries`, and operating-income errors; `AnnualObservation`; and the Slice 1C
`OperatingMargin`, `AnnualMetricRow`, `align_annual_metrics`, and `operating_margins`.

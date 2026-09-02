---
title: Operating Income and Margin Public API Contract
description: Minimal Python library contract for ADBE operating income, margin, and metric alignment
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds deterministic, offline operating-income normalization, a derived operating-margin
calculation, and per-fiscal-year alignment of the two canonical series. It supports ADBE only and
adds no network access. It reuses the existing revenue normalization and preserves its public API.
This contract does not define a generalized metric framework.

## Internal primitive (`owner_lens._annual`)

`_annual` is internal. It is not part of the public contract and may change as more metrics reuse it.
It provides the shared annual selection engine, the shared reported-observation type, and the shared
full-year, fiscal-year, deduplication, and provenance behavior. Metric modules inject their concept
preference list and typed error classes. Consumers depend on the public metric modules below, not on
`_annual`.

## Reported fact values

### `AnnualObservation`

The shared reported-fact observation, re-exported by each metric module. Immutable, with these
readable attributes:

| Attribute       | Type  | Contract                                        |
|-----------------|-------|-------------------------------------------------|
| `concept`       | `str` | Selected US-GAAP concept                        |
| `unit`          | `str` | Reporting unit, `USD`                           |
| `fiscal_year`   | `int` | Fiscal year derived from the period end date     |
| `fiscal_period` | `str` | Source fiscal period, `FY`                      |
| `period_start`  | `date`| Source period start date                        |
| `period_end`    | `date`| Source period end date                          |
| `form`          | `str` | Source filing form                              |
| `filed`         | `date`| Source filing date of the retained observation   |
| `accession`     | `str` | Source accession number of the retained observation |
| `value`         | `int` | Reported value, preserved exactly; may be negative |

### `AnnualOperatingIncomeSeries`

Immutable, with these readable attributes:

| Attribute      | Type                             | Contract                                   |
|----------------|----------------------------------|--------------------------------------------|
| `ticker`       | `str`                            | `ADBE`                                     |
| `concept`      | `str`                            | Single concept shared by all observations  |
| `observations` | `tuple[AnnualObservation, ...]`  | At most one per year, newest first         |

The existing `AnnualRevenueSeries` and `AnnualRevenueObservation` remain unchanged and are preserved.

## Operating-income normalization

```text
normalize_annual_operating_income(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> AnnualOperatingIncomeSeries
```

Contract:

1. Accept the raw Company Facts mapping produced by Slice 1 retrieval.
2. Reject any `ticker` other than `ADBE`.
3. Select one concept using the documented operating-income preference order.
4. Keep only `USD`, `fp == "FY"` observations whose period duration is 350 to 380 days.
5. Derive each observation's fiscal year from its period end date.
6. Collapse identical comparative repeats per fiscal year, retaining earliest-filed provenance.
7. Return up to `max_years` observations ordered by fiscal year descending.
8. Perform no network access and no value estimation, interpolation, or aggregation.

## Derived metric

### `OperatingMargin`

Immutable derived value, distinct from `AnnualObservation`, with these readable attributes:

| Attribute                    | Type    | Contract                                        |
|------------------------------|---------|-------------------------------------------------|
| `fiscal_year`                | `int`   | Economic fiscal year shared by both inputs      |
| `value`                      | `float` | `operating_income / revenue`; may be negative   |
| `revenue`                    | `int`   | Revenue input value                             |
| `operating_income`           | `int`   | Operating income input value                    |
| `revenue_accession`          | `str`   | Provenance of the revenue input                 |
| `operating_income_accession` | `str`   | Provenance of the operating-income input        |

### `AnnualMetricRow`

Immutable per-year alignment row, with these readable attributes:

| Attribute          | Type                          | Contract                                    |
|--------------------|-------------------------------|---------------------------------------------|
| `fiscal_year`      | `int`                         | Economic fiscal year                        |
| `revenue`          | `AnnualObservation \| None`   | Canonical revenue for the year, or `None`   |
| `operating_income` | `AnnualObservation \| None`   | Canonical operating income, or `None`       |
| `operating_margin` | `OperatingMargin \| None`     | Derived margin, or `None` when not computable |

## Alignment and margin functions

```text
align_annual_metrics(
    revenue: AnnualRevenueSeries,
    operating_income: AnnualOperatingIncomeSeries,
) -> tuple[AnnualMetricRow, ...]
```

Contract:

1. Union the fiscal years present in either series.
2. For each year, attach the canonical revenue and operating-income observations when present.
3. Compute `operating_margin` only when both inputs exist and revenue is non-zero.
4. Order rows by fiscal year descending.

```text
operating_margins(
    revenue: AnnualRevenueSeries,
    operating_income: AnnualOperatingIncomeSeries,
) -> tuple[OperatingMargin, ...]
```

Contract: return only the computable margins, newest first. Years missing an input or with zero
revenue are omitted explicitly.

Both functions are deterministic, perform no network access, and never emit an invented, infinite, or
undefined margin.

## Exceptions

Operating-income failures inherit from `OperatingIncomeNormalizationError`. Public categories:

| Exception                             | Meaning                                                     |
|---------------------------------------|-------------------------------------------------------------|
| `UnsupportedTickerError`              | Input ticker is not ADBE                                    |
| `MalformedFactsError`                 | Payload lacks a usable `facts.us-gaap` fact structure       |
| `OperatingIncomeConceptNotFoundError` | No preference-order concept has a qualifying observation    |
| `AmbiguousOperatingIncomeError`       | A fiscal year has conflicting distinct full-year values      |

Revenue keeps its existing `RevenueNormalizationError` hierarchy. Margin and alignment functions do
not raise on missing inputs or zero revenue; they omit the margin explicitly. No failure is converted
to `None`, an empty series, or a partial result, except the documented explicit omission of a single
year's margin.

## Preserved public surface

`SecClient`, the Slice 1 identity and retrieval types, `normalize_annual_revenue`,
`AnnualRevenueSeries`, `AnnualRevenueObservation`, `REVENUE_CONCEPT_PREFERENCE`, and the revenue error
classes remain exported and behave exactly as before.

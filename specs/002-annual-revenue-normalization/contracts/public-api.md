---
title: Annual Revenue Normalization Public API Contract
description: Minimal Python library contract for the ADBE annual revenue series
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package exposes one deterministic, offline function that turns a raw Adobe Company Facts payload
into a canonical annual revenue series, plus the value types and typed failures it uses. It supports
ADBE revenue only and adds no network access. This contract does not define a generic metric
normalization interface.

## Values

### `AnnualRevenueObservation`

An immutable value with these readable attributes:

| Attribute       | Type  | Contract                                                    |
|-----------------|-------|-------------------------------------------------------------|
| `concept`       | `str` | Selected US-GAAP revenue concept                            |
| `unit`          | `str` | Reporting unit, `USD`                                       |
| `fiscal_year`   | `int` | Fiscal year derived from the period end date                |
| `fiscal_period` | `str` | Source fiscal period, `FY`                                  |
| `period_start`  | `date`| Source period start date                                    |
| `period_end`    | `date`| Source period end date                                      |
| `form`          | `str` | Source filing form                                          |
| `filed`         | `date`| Source filing date of the retained observation              |
| `accession`     | `str` | Source accession number of the retained observation         |
| `value`         | `int` | Reported revenue value, preserved exactly                   |

### `AnnualRevenueSeries`

An immutable value with these readable attributes:

| Attribute      | Type                              | Contract                                   |
|----------------|-----------------------------------|--------------------------------------------|
| `ticker`       | `str`                             | `ADBE`                                     |
| `concept`      | `str`                             | Single concept shared by all observations  |
| `observations` | `tuple[AnnualRevenueObservation, ...]` | At most one per year, newest first    |

## Function

```text
normalize_annual_revenue(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> AnnualRevenueSeries
```

Contract:

1. Accept the raw Company Facts mapping produced by Slice 1 retrieval.
2. Reject any `ticker` other than `ADBE` for this slice.
3. Select one revenue concept using the documented preference order.
4. Keep only `USD`, `fp == "FY"` observations whose period duration is 350 to 380 days.
5. Derive each observation's fiscal year from its period end date.
6. Collapse identical comparative repeats per fiscal year, retaining the earliest-filed provenance.
7. Return up to `max_years` observations ordered by fiscal year descending.
8. Perform no network access and no value estimation, interpolation, or aggregation.

The function returns a series only when at least one qualifying observation resolves and no targeted
fiscal year is conflicting.

## Exceptions

All feature failures inherit from `RevenueNormalizationError`. Public exception categories are:

| Exception                     | Meaning                                                        |
|-------------------------------|----------------------------------------------------------------|
| `UnsupportedTickerError`      | Input ticker is not ADBE                                        |
| `MalformedFactsError`         | Payload lacks a usable `facts.us-gaap` fact structure          |
| `RevenueConceptNotFoundError` | No preference-order concept has a qualifying annual observation |
| `AmbiguousRevenueError`       | A fiscal year has conflicting distinct full-year values         |

The function does not convert these failures to `None`, empty series, or partial results. Messages
identify the failed stage and the affected fiscal year when applicable, without a fabricated value.

> Note: `UnsupportedTickerError` is specific to this normalization module and is distinct from the
> Slice 1 SEC retrieval error of the same intent. The two slices keep separate failure hierarchies
> until a shared abstraction has a demonstrated consumer.

## Input contract

The function reads standard SEC Company Facts fields from each fact: `start`, `end`, `val`, `accn`,
`fp`, `form`, and `filed`. It reads concepts under `facts.us-gaap` and units under each concept's
`units` mapping. It ignores unknown fields and does not mutate the input payload.

---
title: Adobe Annual Revenue Normalization Data Model
description: Values, validation rules, relationships, and states for the canonical annual revenue series
ms.date: 2026-09-01
ms.topic: reference
---

## Annual Revenue Observation

One canonical full fiscal-year revenue value with complete SEC provenance.

### Fields

| Field            | Type    | Required | Meaning                                                     |
|------------------|---------|----------|-------------------------------------------------------------|
| `concept`        | string  | Yes      | Selected US-GAAP revenue concept, for example `Revenues`    |
| `unit`           | string  | Yes      | Reporting unit, `USD` for this slice                        |
| `fiscal_year`    | integer | Yes      | Fiscal year derived from the period end date                |
| `fiscal_period`  | string  | Yes      | Source fiscal period, `FY` for annual observations          |
| `period_start`   | date    | Yes      | Source `start` date of the reporting period                 |
| `period_end`     | date    | Yes      | Source `end` date of the reporting period                   |
| `form`           | string  | Yes      | Source filing form, for example `10-K` or `10-K/A`          |
| `filed`          | date    | Yes      | Source filing date of the retained observation              |
| `accession`      | string  | Yes      | Source accession number of the retained observation         |
| `value`          | integer | Yes      | Reported revenue value, preserved as supplied               |

### Validation rules

* `unit` must be `USD`; observations in other units are excluded before selection.
* `fiscal_period` must be `FY`.
* `period_end` minus `period_start` must fall within 350 to 380 days.
* `fiscal_year` equals the calendar year of `period_end`.
* `value` is preserved exactly from the source fact and is neither rounded nor rescaled.
* Every field derives from one retained source fact; no field is invented.

## Canonical Annual Revenue Series

The ordered result for Adobe revenue.

### Fields

| Field          | Type                          | Required | Meaning                                        |
|----------------|-------------------------------|----------|------------------------------------------------|
| `ticker`       | string                        | Yes      | `ADBE` for this slice                          |
| `concept`      | string                        | Yes      | The single concept used across all observations|
| `observations` | list of Annual Revenue Observation | Yes | At most one per fiscal year, newest first      |

### Relationships and constraints

* All observations share one `concept`; the series never mixes concepts.
* `observations` contains at most one entry per `fiscal_year`.
* `observations` holds up to five entries, ordered by `fiscal_year` descending.
* A non-empty series is required for success; an empty result is a failure, not a valid series.

## Concept preference order

An ordered, documented list used to select one concept:

1. `RevenueFromContractWithCustomerExcludingAssessedTax`
2. `Revenues`
3. `SalesRevenueNet`

The first concept present with at least one qualifying annual observation is chosen. Adobe currently
resolves to `Revenues`.

## Normalization Failure

An explicit exceptional outcome instead of returned data.

### Failure categories

| Category                 | Trigger                                                              |
|--------------------------|---------------------------------------------------------------------|
| Missing revenue concept  | No preference-order concept has a qualifying annual observation      |
| Ambiguous fiscal year    | A fiscal year has two or more distinct qualifying full-year values   |
| Malformed facts input    | The payload lacks a `facts.us-gaap` object or a usable fact structure|

A failure identifies the affected fiscal year when applicable and carries no invented or partial
values.

## State transitions

```text
Received payload
  -> FailedMalformedInput
  -> SelectingConcept
       -> FailedMissingConcept
       -> ConceptSelected
            -> FilteringFullYearUsdObservations
                 -> GroupingByDerivedFiscalYear
                      -> FailedAmbiguousYear
                      -> SeriesResolved (up to latest five, one per year)
```

Only `SeriesResolved` yields a Canonical Annual Revenue Series. Every failure state terminates
without partial output.

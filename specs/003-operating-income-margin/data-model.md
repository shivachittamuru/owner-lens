---
title: Adobe Operating Income and Margin Data Model
description: Values, validation rules, relationships, and states for operating income and margin
ms.date: 2026-09-01
ms.topic: reference
---

## Annual Observation (shared reported fact)

The canonical full fiscal-year reported value with SEC provenance, shared by revenue and operating
income and defined once in the internal primitive.

### Fields

| Field            | Type    | Required | Meaning                                                     |
|------------------|---------|----------|-------------------------------------------------------------|
| `concept`        | string  | Yes      | Selected US-GAAP concept, for example `OperatingIncomeLoss` |
| `unit`           | string  | Yes      | Reporting unit, `USD`                                        |
| `fiscal_year`    | integer | Yes      | Fiscal year derived from the period end date                |
| `fiscal_period`  | string  | Yes      | Source fiscal period, `FY`                                   |
| `period_start`   | date    | Yes      | Source period start date                                    |
| `period_end`     | date    | Yes      | Source period end date                                      |
| `form`           | string  | Yes      | Source filing form, for example `10-K`                      |
| `filed`          | date    | Yes      | Source filing date of the retained observation              |
| `accession`      | string  | Yes      | Source accession number of the retained observation         |
| `value`          | integer | Yes      | Reported value, preserved exactly as supplied               |

### Validation rules

* `unit` must be `USD`; other units are excluded before selection.
* `fiscal_period` must be `FY`.
* `period_end` minus `period_start` must fall within 350 to 380 days.
* `fiscal_year` equals the calendar year of `period_end`.
* `value` is preserved exactly; operating income may be negative.
* Every field derives from one retained source fact; no field is invented.

## Canonical Annual Operating Income Series

The ordered operating-income result.

### Fields

| Field          | Type                          | Required | Meaning                                        |
|----------------|-------------------------------|----------|------------------------------------------------|
| `ticker`       | string                        | Yes      | `ADBE`                                         |
| `concept`      | string                        | Yes      | Single concept shared by all observations      |
| `observations` | list of Annual Observation    | Yes      | At most one per fiscal year, newest first      |

### Constraints

* All observations share one concept; the series never mixes concepts.
* At most one observation per fiscal year, up to five, ordered by fiscal year descending.

## Operating-income concept preference order

An ordered, documented list used to select one concept:

1. `OperatingIncomeLoss`

Adobe resolves to `OperatingIncomeLoss`. The list is ordered so an alternate tag could be added later
without changing selection semantics.

## Operating Margin (derived metric)

A calculated annual ratio, kept distinct from reported observations.

### Fields

| Field                     | Type    | Required | Meaning                                            |
|---------------------------|---------|----------|----------------------------------------------------|
| `fiscal_year`             | integer | Yes      | Economic fiscal year shared by both inputs         |
| `value`                   | float   | Yes      | Operating income divided by revenue                |
| `revenue`                 | integer | Yes      | Revenue input value used                           |
| `operating_income`        | integer | Yes      | Operating income input value used                  |
| `revenue_accession`       | string  | Yes      | Provenance of the revenue input                    |
| `operating_income_accession` | string | Yes    | Provenance of the operating-income input           |

### Validation rules

* A margin exists only when both canonical inputs exist for the fiscal year.
* A margin is never produced when revenue is zero.
* `value` equals `operating_income / revenue`; it may be negative when operating income is negative.
* The margin type is separate from Annual Observation so a consumer can distinguish a derived metric
  from a reported fact.

## Aligned Annual Metrics

The per-fiscal-year alignment used for display and explicit omission.

### Fields

| Field              | Type                          | Required | Meaning                                     |
|--------------------|-------------------------------|----------|---------------------------------------------|
| `fiscal_year`      | integer                       | Yes      | Economic fiscal year                        |
| `revenue`          | Annual Observation or absent  | No       | Canonical revenue for the year, if present  |
| `operating_income` | Annual Observation or absent  | No       | Canonical operating income, if present      |
| `operating_margin` | Operating Margin or absent    | No       | Derived margin, present only when computable |

### Constraints

* Rows are ordered by fiscal year descending.
* A row exists for each fiscal year present in either input series.
* `operating_margin` is absent whenever a required input is missing or revenue is zero, making the
  omission explicit.

## Normalization Failure

Explicit exceptional outcomes instead of returned data.

| Category                       | Trigger                                                         |
|--------------------------------|-----------------------------------------------------------------|
| Unsupported ticker             | Input ticker is not ADBE                                        |
| Malformed facts input          | Payload lacks a usable `facts.us-gaap` fact structure           |
| Operating-income concept missing | No preference-order concept has a qualifying annual observation |
| Ambiguous fiscal year          | A fiscal year has conflicting distinct full-year values         |

A failure identifies the affected fiscal year when applicable and carries no invented or partial
values. Margin derivation does not raise on missing inputs or zero revenue; it omits the margin
explicitly.

## State transitions

```text
Received payload
  -> FailedUnsupportedTicker
  -> FailedMalformedInput
  -> SelectingOperatingIncomeConcept
       -> FailedConceptMissing
       -> ConceptSelected
            -> FilteringFullYearUsdObservations
                 -> GroupingByDerivedFiscalYear
                      -> FailedAmbiguousYear
                      -> OperatingIncomeSeriesResolved
                           -> AligningWithRevenueSeries
                                -> ComputingMarginsWhereBothInputsAndNonZeroRevenue
                                     -> AlignedMetricsReady
```

Only the aligned-metrics-ready state yields margins. Every failure state terminates without partial
output.

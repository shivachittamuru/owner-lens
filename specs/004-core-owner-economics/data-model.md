---
title: Adobe Core Owner Economics Data Model
description: Values, validation rules, relationships, and states for owner-economics metrics
ms.date: 2026-09-01
ms.topic: reference
---

## Annual Observation (shared reported fact)

The canonical full fiscal-year reported value with SEC provenance, shared across metrics and defined
in the internal primitive. Its `unit` now varies by metric.

### Fields

| Field           | Type    | Required | Meaning                                                    |
|-----------------|---------|----------|------------------------------------------------------------|
| `concept`       | string  | Yes      | Selected US-GAAP concept                                   |
| `unit`          | string  | Yes      | Reporting unit, `USD` for value facts or `shares`          |
| `fiscal_year`   | integer | Yes      | Fiscal year derived from the period end date               |
| `fiscal_period` | string  | Yes      | Source fiscal period, `FY`                                 |
| `period_start`  | date    | Yes      | Source period start date                                   |
| `period_end`    | date    | Yes      | Source period end date                                     |
| `form`          | string  | Yes      | Source filing form                                         |
| `filed`         | date    | Yes      | Source filing date of the retained observation             |
| `accession`     | string  | Yes      | Source accession number of the retained observation        |
| `value`         | integer | Yes      | Reported value, preserved exactly; may be negative         |

### Validation rules

* `unit` matches the metric's declared unit; other units are excluded before selection.
* `fiscal_period` must be `FY`; period duration must fall within 350 to 380 days.
* `fiscal_year` equals the calendar year of `period_end`.
* `value` is preserved exactly from the source; net income and similar facts may be negative.

## Metric Specification

Defines how a reported metric is selected.

### Fields

| Field                | Type              | Meaning                                            |
|----------------------|-------------------|----------------------------------------------------|
| `metric`             | string            | Metric name used in messages and provenance context |
| `concept_preference` | tuple of strings  | Ordered concepts to try                            |
| `unit`               | string            | Required source unit for this metric               |

### Documented specifications

| Metric               | `concept_preference`                                                             | `unit`   |
|----------------------|----------------------------------------------------------------------------------|----------|
| Net income           | (`NetIncomeLoss`,)                                                               | `USD`    |
| Operating cash flow  | (`NetCashProvidedByUsedInOperatingActivities`,)                                 | `USD`    |
| Capital expenditures | (`PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`) | `USD` |
| Diluted shares       | (`WeightedAverageNumberOfDilutedSharesOutstanding`,)                             | `shares` |

## Canonical Annual Series

The generic ordered result for a reported metric.

| Field          | Type                          | Meaning                                    |
|----------------|-------------------------------|--------------------------------------------|
| `metric`       | string                        | Metric name                                |
| `ticker`       | string                        | `ADBE`                                     |
| `concept`      | string                        | Single concept shared by all observations  |
| `unit`         | string                        | Unit shared by all observations            |
| `observations` | tuple of Annual Observation   | At most one per fiscal year, newest first  |

## Derived Owner-Economics Metrics

Calculated values, kept distinct from reported observations.

### Per-year derived fields

| Metric               | Formula                                          | Omitted when                                   |
|----------------------|--------------------------------------------------|------------------------------------------------|
| Operating margin     | operating income / revenue                       | operating income or revenue missing; revenue 0 |
| Net margin           | net income / revenue                             | net income or revenue missing; revenue 0       |
| Free cash flow       | operating cash flow - abs(capex)                 | operating cash flow or capex missing           |
| FCF margin           | free cash flow / revenue                         | free cash flow missing; revenue missing or 0   |
| FCF per diluted share| free cash flow / diluted shares                  | free cash flow missing; shares missing or 0    |

### Growth fields

| Metric                | Formula                                       | Omitted when                                   |
|-----------------------|-----------------------------------------------|------------------------------------------------|
| FCF growth            | (fcf[y] - fcf[y-1]) / fcf[y-1]                 | year y-1 absent or fcf[y-1] missing or 0       |
| FCF per share growth  | (fps[y] - fps[y-1]) / fps[y-1]                 | year y-1 absent or fps[y-1] missing or 0       |
| Diluted share growth  | (sh[y] - sh[y-1]) / sh[y-1]                    | year y-1 absent or sh[y-1] missing or 0        |

### Validation rules

* Ratios are floats; free cash flow is an integer currency amount.
* A derived metric references the fiscal year and the inputs used.
* Negative net income or free cash flow is valid and yields a valid negative dependent metric.
* Growth compares only immediately adjacent fiscal years and is omitted for the earliest year.

## Owner-Economics Row and View

The per-fiscal-year alignment used for display and inspection.

### Row fields

| Field                    | Type                          | Meaning                                    |
|--------------------------|-------------------------------|--------------------------------------------|
| `fiscal_year`            | integer                       | Economic fiscal year                       |
| `revenue`                | Annual Observation or absent  | Canonical revenue                          |
| `operating_income`       | Annual Observation or absent  | Canonical operating income                 |
| `net_income`             | Annual Observation or absent  | Canonical net income                       |
| `operating_cash_flow`    | Annual Observation or absent  | Canonical operating cash flow              |
| `capital_expenditures`   | Annual Observation or absent  | Canonical capital expenditures             |
| `diluted_shares`         | Annual Observation or absent  | Canonical diluted weighted-average shares  |
| `operating_margin`       | float or absent               | Derived operating margin                   |
| `net_margin`             | float or absent               | Derived net margin                         |
| `free_cash_flow`         | integer or absent             | Derived free cash flow                     |
| `fcf_margin`             | float or absent               | Derived FCF margin                         |
| `fcf_per_share`          | float or absent               | Derived FCF per diluted share              |
| `fcf_growth`             | float or absent               | Derived adjacent-year FCF growth           |
| `fcf_per_share_growth`   | float or absent               | Derived adjacent-year FCF-per-share growth |
| `diluted_share_growth`   | float or absent               | Derived adjacent-year diluted-share growth |

### View constraints

* Rows are ordered by fiscal year descending.
* A row exists for each fiscal year present in any input series.
* Reported observation fields carry source provenance; derived fields are absent when their inputs or
  denominators do not permit a valid value.

## Normalization Failure

Explicit exceptional outcomes instead of returned data.

| Category               | Trigger                                                        |
|------------------------|-----------------------------------------------------------------|
| Unsupported ticker     | Input ticker is not ADBE                                        |
| Malformed facts input  | Payload lacks a usable `facts.us-gaap` fact structure           |
| Concept not found      | No preference-order concept has a qualifying annual observation  |
| Ambiguous fiscal year  | A fiscal year has conflicting distinct full-year values          |

Derived metrics and growth never raise on missing inputs or zero denominators; they omit the affected
value explicitly.

## State transitions

```text
Received payload
  -> FailedUnsupportedTicker
  -> FailedMalformedInput
  -> NormalizingReportedMetrics (revenue, operating income, net income, OCF, capex, diluted shares)
       -> FailedConceptNotFound
       -> FailedAmbiguousYear
       -> ReportedSeriesResolved
            -> AligningByEconomicFiscalYear
                 -> DerivingPerYearMetricsWhereInputsAndNonZeroDenominators
                      -> DerivingAdjacentYearGrowthWherePriorYearValid
                           -> OwnerEconomicsViewReady
```

Only the view-ready state yields derived metrics. Every failure state terminates without partial
reported output.

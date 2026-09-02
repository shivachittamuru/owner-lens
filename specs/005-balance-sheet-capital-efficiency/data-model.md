---
title: Adobe Balance Sheet and Capital Efficiency Data Model
description: Values, validation rules, relationships, and states for instant facts and capital efficiency
ms.date: 2026-09-01
ms.topic: reference
---

## Instant Annual Observation

The canonical fiscal-year-end reported value with SEC provenance. It reuses the shared
`AnnualObservation` type; for instant facts `period_start` equals `period_end` (the instant date).

### Fields

| Field           | Type    | Required | Meaning                                                    |
|-----------------|---------|----------|------------------------------------------------------------|
| `concept`       | string  | Yes      | Selected US-GAAP concept                                   |
| `unit`          | string  | Yes      | Reporting unit, `USD`                                      |
| `fiscal_year`   | integer | Yes      | Fiscal year derived from the period-end date               |
| `fiscal_period` | string  | Yes      | Source fiscal period, `FY`                                 |
| `period_start`  | date    | Yes      | Equal to `period_end` for instant facts                    |
| `period_end`    | date    | Yes      | Instant fiscal-year-end date                               |
| `form`          | string  | Yes      | Source filing form, `10-K` or `10-K/A`                     |
| `filed`         | date    | Yes      | Source filing date of the retained observation             |
| `accession`     | string  | Yes      | Source accession number of the retained observation        |
| `value`         | integer | Yes      | Reported value, preserved exactly; may be negative         |

### Validation rules

* The source fact must be instant (no `start`), fiscal period `FY`, and from a `10-K` form.
* `fiscal_year` equals the calendar year of `period_end`.
* Identical repeats collapse to the earliest-filed observation; distinct values for one fiscal year
  raise a typed ambiguity error.
* `value` is preserved exactly; balance-sheet values such as net cash inputs may be zero.

## Instant Metric Specification

Defines how an instant balance-sheet metric is selected. Reuses the Slice 1D `MetricSpec` shape
(metric, concept_preference, unit), interpreted with instant selection.

### Documented specifications

| Metric                 | `concept_preference`                          | `unit` |
|------------------------|-----------------------------------------------|--------|
| Cash                   | (`CashAndCashEquivalentsAtCarryingValue`,)    | `USD`  |
| Short-term investments | (`ShortTermInvestments`,)                     | `USD`  |
| Current debt           | (`DebtCurrent`,)                              | `USD`  |
| Long-term debt         | (`LongTermDebt`,)                            | `USD`  |
| Total assets           | (`Assets`,)                                  | `USD`  |
| Total equity           | (`StockholdersEquity`,)                       | `USD`  |

Short-term investments and current debt are optional; when absent their contribution is zero.

## Duration specifications added for the tax rate

Reuses the Slice 1D duration normalizer.

| Metric              | `concept_preference`                                                                                                  | `unit` |
|---------------------|----------------------------------------------------------------------------------------------------------------------|--------|
| Income tax expense  | (`IncomeTaxExpenseBenefit`,)                                                                                          | `USD`  |
| Pretax income       | (`IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, `IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments`) | `USD` |

## Reported definitions (explicit, provenance-preserving)

| Definition                    | Formula                                            | Notes                                   |
|-------------------------------|----------------------------------------------------|-----------------------------------------|
| Cash plus short-term invest.  | cash + short_term_investments (STI optional, 0)    | Avoids double counting the combined tag |
| Total debt                    | current_debt + long_term_debt (current optional, 0)| Preserves provenance of both components |

## Derived Capital-Efficiency Metrics

Calculated values kept distinct from reported observations.

| Metric                | Formula                                             | Omitted when                                        |
|-----------------------|-----------------------------------------------------|-----------------------------------------------------|
| Net cash or net debt  | cash_plus_sti - total_debt                          | cash or debt inputs missing                         |
| Effective tax rate    | income_tax_expense / pretax_income                  | tax expense or pretax income missing; pretax 0      |
| NOPAT                 | operating_income * (1 - effective_tax_rate)         | operating income or effective tax rate missing      |
| Invested capital      | total_debt + total_equity - cash_plus_sti           | debt, equity, or cash inputs missing                |
| ROA                   | net_income / average_total_assets                   | net income missing; beginning assets missing; avg 0 |
| ROE                   | net_income / average_total_equity                   | net income missing; beginning equity missing; avg 0 |
| ROIC                  | nopat / average_invested_capital                    | NOPAT missing; beginning IC missing; avg 0          |

Average balance = (beginning fiscal-year-end + ending fiscal-year-end) / 2. The beginning balance is
the prior fiscal-year-end value, which may be a calculation-only baseline year.

### Validation rules

* Ratios are floats; net cash, total debt, invested capital, and NOPAT are integer currency amounts
  (NOPAT rounded to the nearest dollar).
* A derived metric references the fiscal year and the inputs used.
* Zero or negative average equity omits ROE; the behavior is documented and tested.
* Economically valid negatives (net debt, negative equity) are valid inputs, not malformed data.

## Capital-Efficiency Row and View

The per-fiscal-year alignment used for display and inspection.

### Row fields

| Field                    | Type                          | Meaning                                    |
|--------------------------|-------------------------------|--------------------------------------------|
| `fiscal_year`            | integer                       | Economic fiscal year                       |
| `cash`                   | Instant Observation or absent | Canonical cash                             |
| `short_term_investments` | Instant Observation or absent | Canonical short-term investments           |
| `current_debt`           | Instant Observation or absent | Canonical current debt                     |
| `long_term_debt`         | Instant Observation or absent | Canonical long-term debt                   |
| `total_assets`           | Instant Observation or absent | Canonical total assets                     |
| `total_equity`           | Instant Observation or absent | Canonical total stockholders' equity       |
| `cash_plus_sti`          | integer or absent             | Derived cash plus short-term investments   |
| `total_debt`             | integer or absent             | Derived total debt                         |
| `net_cash`               | integer or absent             | Derived net cash or net debt               |
| `effective_tax_rate`     | float or absent               | Derived effective tax rate                 |
| `nopat`                  | integer or absent             | Derived NOPAT                              |
| `invested_capital`       | integer or absent             | Derived invested capital                   |
| `roa`                    | float or absent               | Derived return on assets                   |
| `roe`                    | float or absent               | Derived return on equity                   |
| `roic`                   | float or absent               | Derived return on invested capital         |

### View constraints

* Rows are ordered by fiscal year descending and display only the latest target years.
* The calculation-only baseline year is used for averages but not displayed as a row.
* Reported observation fields carry source provenance; derived fields are absent when their inputs,
  baselines, or non-zero denominators do not permit a valid value.

## Normalization Failure

Explicit exceptional outcomes instead of returned data.

| Category               | Trigger                                                        |
|------------------------|-----------------------------------------------------------------|
| Unsupported ticker     | Input ticker is not ADBE                                        |
| Malformed facts input  | Payload lacks a usable `facts.us-gaap` fact structure           |
| Concept not found      | No preference-order concept has a qualifying observation         |
| Ambiguous fiscal year  | A fiscal-year-end has conflicting distinct values                |

Derived metrics never raise on missing inputs, missing baselines, or zero denominators; they omit the
affected value explicitly.

## State transitions

```text
Received payload
  -> FailedUnsupportedTicker
  -> FailedMalformedInput
  -> NormalizingInstantBalanceSheetFacts (cash, STI, current debt, long-term debt, assets, equity)
       -> FailedConceptNotFound
       -> FailedAmbiguousYearEnd
       -> BalanceSheetSeriesResolved (including one baseline year)
            -> ReusingDurationSeries (operating income, net income, income tax, pretax income)
                 -> AligningByEconomicFiscalYear
                      -> DerivingCashDebtAndAverages
                           -> DerivingTaxRateNopatAndReturns
                                -> CapitalEfficiencyViewReady (latest target years displayed)
```

Only the view-ready state yields derived metrics. Every failure state terminates without partial
reported output.

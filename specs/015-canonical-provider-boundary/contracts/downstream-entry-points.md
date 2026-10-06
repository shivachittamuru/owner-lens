---
title: "Contract: Downstream Entry Points"
description: Canonical-history entry points and compatibility wrappers for the seven OwnerLens analytical modules in Slice 5A
ms.date: 2026-10-05
ms.topic: reference
---

## Canonical entry points (new)

Each function accepts one positional `CanonicalFinancialHistory`, plus the optional keyword
arguments that already exist today (`thresholds`, `period_years`). None of these functions accepts
raw facts, `ticker`, or `max_years`. Both values come from the history.

| Module               | Function                                                                     | Returns                                               | Requires, in order (R4)                                                 |
|----------------------|------------------------------------------------------------------------------|-------------------------------------------------------|-------------------------------------------------------------------------|
| `owner_economics`    | `owner_economics_from_history(history)`                                      | `tuple[OwnerEconomicsRow, ...]`                       | `diluted_shares` (unsupported allowed), `revenue`, `operating_income`, `net_income`, `operating_cash_flow`, `capital_expenditures` |
| `capital_efficiency` | `capital_efficiency_from_history(history)`                                   | `tuple[CapitalEfficiencyRow, ...]`                    | `operating_income`, `net_income`, `income_tax_expense`, `pretax_income`, `cash`, `short_term_investments`, `current_debt`, `long_term_debt`, `total_assets`, `total_equity` |
| `economic_value`     | `economic_value_from_history(history, *, thresholds=...)`                    | `tuple[EconomicValueSnapshot, ...]`                   | Owner economics, then capital efficiency.                               |
| `compounding`        | `compounding_view_from_history(history, *, period_years, thresholds=...)`    | `EconomicCompoundingView`                             | Owner economics, capital efficiency, then economic value.               |
| `compounding`        | `compounding_views_from_history(history, *, thresholds=...)`                 | `tuple[EconomicCompoundingView, EconomicCompoundingView]` | Same as above.                                                      |
| `capital_allocation` | `capital_allocation_from_history(history, *, thresholds=...)`                | `tuple[CapitalAllocationRow, ...]`                    | Owner economics, capital efficiency, economic value, `repurchases`, `stock_based_compensation`, `dividends_paid` |
| `economic_summary`   | `economic_value_summary_from_history(history, *, thresholds=...)`            | `EconomicValueSummary`                                | Economic value, compounding views, then capital allocation. The summary ticker is `history.ticker`. |
| `coverage`           | `company_coverage_from_history(history)`                                     | `CompanyCoverage`                                     | Input statuses in vocabulary order, then each layer in `LAYER_ORDER`.   |
| `coverage`           | `company_output_from_history(coverage, history)`                             | `str`                                                 | Economic summary, only when coverage is full.                           |

Semantics:

* `capital_efficiency_from_history` uses `history.max_years` as `display_years`.
* The capital-allocation kernel treats `dividends_paid.status is STRUCTURALLY_ABSENT` as "no
  dividend program". This replaces the SEC `concept == ""` sentinel.
* Coverage maps statuses to `MetricCoverage` as described in
  [data-model.md](../data-model.md#metricstatus-enum). It catches `MetricUnsupportedError` wherever
  it caught concept-not-found errors before. Layer reasons stay `str(exc)`.
* Every derived value, classification, driver, and coverage state equals the previous
  `*_from_facts` result for the same inputs.

## Kernels (retyped, same names)

| Function                         | Parameter change                                                                 |
|----------------------------------|----------------------------------------------------------------------------------|
| `compute_owner_economics`        | `revenue`, `operating_income`, `net_income`, `operating_cash_flow`, `capital_expenditures`, `diluted_shares`: `CanonicalSeries` |
| `compute_capital_efficiency`     | Every series parameter becomes `CanonicalSeries`. `display_years` is unchanged.  |
| `build_capital_allocation_rows`  | `repurchases`, `stock_based_compensation`, `dividends_paid`: `CanonicalSeries`   |
| `build_economic_value_snapshots`, `build_compounding_view`, `synthesize_economic_value_summary` | Unchanged (they consume rows). |

## Compatibility wrappers (retained)

The wrappers keep their signatures, defaults, return types, and exception behavior exactly:

* `owner_economics_from_facts`
* `capital_efficiency_from_facts`
* `economic_value_from_facts`
* `compounding_view_from_facts`
* `compounding_views_from_facts`
* `capital_allocation_from_facts`
* `economic_value_summary_from_facts`
* `company_coverage`
* `company_output`

Each wrapper body is:

```text
history = canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
return <name>_from_history(history, ...)
```

Two wrappers differ:

* `economic_value_summary_from_facts` composes the history-based components and then calls
  `synthesize_economic_value_summary(ticker, ...)` with the caller's literal `ticker`, as today.
* `company_output` keeps its legacy rendering, including that literal-ticker behavior.

## Boundary rule (enforced by `tests/test_canonical_boundary.py`)

Allowed imports in the seven downstream modules:

* The standard library.
* `owner_lens.canonical` and `owner_lens._trajectory`.
* The other six downstream modules.
* Exactly one SEC-side import, used only by the wrappers:
  `from owner_lens.sec_adapter import canonical_history_from_sec`.

The `*_from_history` functions and the kernels must not call that import.

Forbidden in those modules:

* Imports of `owner_lens._annual`, `reported`, `balance_sheet`, `revenue`, `operating_income`,
  `metrics`, or `sec`.
* Any string literal equal to an SEC concept defined in `metrics.py`.

The wrappers are a documented, temporary exception. They are removed once every caller uses
`*_from_history`.

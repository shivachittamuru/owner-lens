---
title: Balance Sheet and Capital Efficiency Public API Contract
description: Minimal Python library contract for Adobe balance-sheet facts and capital-efficiency metrics
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds deterministic, offline normalization for five fiscal-year-end balance-sheet facts
and a derived capital-efficiency view combining them with the existing operating-income and
net-income series and duration tax inputs. It supports ADBE only and adds no network access. It reuses
and preserves all prior slices. This contract does not define a generalized accounting ontology.

## Internal primitive change (`owner_lens._annual`)

`_annual` gains a distinct instant selection path `select_instant_series(...)` that shares the
fiscal-year grouping, earliest-filed deduplication, and ambiguity resolution used by
`select_annual_series`, but qualifies facts as instant (no `start`), fiscal period `FY`, and `10-K`
form. `AnnualObservation` is reused with `period_start == period_end` for instant facts. `_annual`
remains internal, and the duration and instant paths remain two clearly named functions.

## Balance-sheet normalization (`owner_lens.balance_sheet`)

### Metric specs

Reuses `MetricSpec` from `owner_lens.reported`. The module defines: `CASH`,
`SHORT_TERM_INVESTMENTS`, `CURRENT_DEBT`, `LONG_TERM_DEBT`, `TOTAL_ASSETS`, `TOTAL_EQUITY`.

### Functions

```text
normalize_annual_instant(
    raw_facts: dict[str, Any],
    spec: MetricSpec,
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> AnnualSeries

normalize_cash(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_short_term_investments(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_current_debt(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_long_term_debt(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_total_assets(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_total_equity(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
```

Contract for each:

1. Accept the raw Company Facts mapping produced by Slice 1 retrieval.
2. Reject any `ticker` other than `ADBE`.
3. Select the concept using instant fiscal-year-end semantics (no `start`, `FY`, `10-K`).
4. Derive each observation's fiscal year from its period-end date.
5. Collapse identical comparative repeats per fiscal year, retaining earliest-filed provenance.
6. Return up to `max_years` observations ordered by fiscal year descending.
7. Perform no network access and no value estimation, interpolation, or aggregation.

`AnnualSeries` and the reported errors (`ConceptNotFoundError`, `AmbiguousValueError`,
`MalformedFactsError`, `UnsupportedTickerError`) are reused from Slice 1D.

## Duration specs added (`owner_lens.reported`)

The module adds `INCOME_TAX_EXPENSE` and `PRETAX_INCOME` metric specs and the convenience functions
`normalize_income_tax_expense` and `normalize_pretax_income`, each returning `AnnualSeries` via the
existing duration normalizer.

## Capital efficiency (`owner_lens.capital_efficiency`)

### `CapitalEfficiencyRow`

Immutable per-year row with the reported observations and derived metrics listed in the
[data model](data-model.md): `fiscal_year`; optional `cash`, `short_term_investments`, `current_debt`,
`long_term_debt`, `total_assets`, `total_equity` (each `AnnualObservation | None`); and optional
derived `cash_plus_sti`, `total_debt`, `net_cash`, `effective_tax_rate`, `nopat`, `invested_capital`,
`roa`, `roe`, `roic`.

### Functions

```text
compute_capital_efficiency(
    *,
    operating_income: AnnualOperatingIncomeSeries,
    net_income: AnnualSeries,
    income_tax_expense: AnnualSeries,
    pretax_income: AnnualSeries,
    cash: AnnualSeries,
    short_term_investments: AnnualSeries,
    current_debt: AnnualSeries,
    long_term_debt: AnnualSeries,
    total_assets: AnnualSeries,
    total_equity: AnnualSeries,
    display_years: int = 5,
) -> tuple[CapitalEfficiencyRow, ...]

capital_efficiency_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> tuple[CapitalEfficiencyRow, ...]
```

Contract:

1. `compute_capital_efficiency` aligns all series by economic fiscal year, derives cash plus
   short-term investments, total debt, net cash, effective tax rate, NOPAT, invested capital, and the
   average-balance returns ROA, ROE, and ROIC, and returns the latest `display_years` rows.
2. `capital_efficiency_from_facts` normalizes the balance-sheet series with one extra baseline year
   (`max_years + 1`) and the duration series with `max_years`, then calls
   `compute_capital_efficiency` with `display_years = max_years`.
3. Free-standing definitions: cash plus short-term investments is `cash + (short_term_investments or 0)`;
   total debt is `(current_debt or 0) + long_term_debt`; net cash is `cash_plus_sti - total_debt`;
   invested capital is `total_debt + total_equity - cash_plus_sti`.
4. Averages use the prior fiscal-year-end balance; a metric requiring an unavailable beginning balance
   is omitted rather than computed from the ending balance.
5. Each derived metric is present only when its inputs exist and its denominator is non-zero.
6. Rows are ordered by fiscal year descending. No network access occurs.

## Exceptions

Balance-sheet and duration-spec failures reuse the shared generic errors from Slice 1D:
`UnsupportedTickerError`, `MalformedFactsError`, `ConceptNotFoundError`, and `AmbiguousValueError`.
`ConceptNotFoundError` and `AmbiguousValueError` messages name the affected metric and, for ambiguity,
the fiscal year. Derived functions do not raise on missing inputs, missing baselines, or zero
denominators; they omit the affected value. No failure is converted to `None`, an empty series, or a
partial result, except the documented explicit omission of an individual derived value.

## Preserved public surface

All Slice 1A through 1D exports remain and behave exactly as before, including `SecClient` and the
retrieval types; the revenue, operating-income, and margin surfaces; `AnnualObservation`, `AnnualSeries`,
`MetricSpec`, and the reported normalizers; and the owner-economics surface.

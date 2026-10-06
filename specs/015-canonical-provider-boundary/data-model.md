---
title: "Data Model: Canonical Provider Boundary"
description: Entities, fields, validation rules, and state semantics for OwnerLens Slice 5A canonical financial history
ms.date: 2026-10-05
ms.topic: reference
---

All entities live in `src/owner_lens/canonical.py`. They are immutable (`@dataclass(frozen=True)`
or `Enum`), deterministic, and have no SEC dependency.

## MetricKind (enum)

| Member     | Value        | Meaning                                                   |
|------------|--------------|-----------------------------------------------------------|
| `DURATION` | `"duration"` | Value covers a fiscal period with a start and end date.   |
| `INSTANT`  | `"instant"`  | Value is a point-in-time fiscal-year-end balance.         |

Moved from `metrics.py`, which re-exports it for compatibility.

## CanonicalMetricSpec

The fixed OwnerLens vocabulary. One spec exists for each canonical metric.

| Field  | Type         | Notes                                 |
|--------|--------------|---------------------------------------|
| `name` | `str`        | Provider-neutral OwnerLens name.      |
| `kind` | `MetricKind` | Duration or instant.                  |
| `unit` | `str`        | `"USD"` or `"shares"`.                |

`CANONICAL_METRICS: tuple[CanonicalMetricSpec, ...]` lists them in this order:

| #  | Name                       | Kind     | Unit   |
|----|----------------------------|----------|--------|
| 1  | `revenue`                  | duration | USD    |
| 2  | `operating_income`         | duration | USD    |
| 3  | `net_income`               | duration | USD    |
| 4  | `operating_cash_flow`      | duration | USD    |
| 5  | `capital_expenditures`     | duration | USD    |
| 6  | `diluted_shares`           | duration | shares |
| 7  | `income_tax_expense`       | duration | USD    |
| 8  | `pretax_income`            | duration | USD    |
| 9  | `repurchases`              | duration | USD    |
| 10 | `stock_based_compensation` | duration | USD    |
| 11 | `dividends_paid`           | duration | USD    |
| 12 | `cash`                     | instant  | USD    |
| 13 | `short_term_investments`   | instant  | USD    |
| 14 | `current_debt`             | instant  | USD    |
| 15 | `long_term_debt`           | instant  | USD    |
| 16 | `total_assets`             | instant  | USD    |
| 17 | `total_equity`             | instant  | USD    |

The order matches today's coverage input order (`coverage._INPUTS`), so coverage `inputs` dict
ordering is unchanged.

## CanonicalFact

One reported annual value for one metric and fiscal year.

| Field            | Type           | Notes                                                                 |
|------------------|----------------|-----------------------------------------------------------------------|
| `metric`         | `str`          | Must be a `CANONICAL_METRICS` name.                                   |
| `value`          | `int`          | As reported. Sign conventions are preserved; downstream applies `abs()` where defined. |
| `unit`           | `str`          | Must equal the metric spec's unit.                                    |
| `fiscal_year`    | `int`          | Economic fiscal year (period-end year, per the existing SEC rule).    |
| `fiscal_period`  | `str`          | `"FY"` in 5A.                                                         |
| `period_end`     | `date`         | Fiscal-period end, or the instant date.                               |
| `period_start`   | `date \| None` | Required for duration metrics. Must be `None` for instant metrics.    |
| `provider`       | `str`          | Provider identifier, for example `"sec"`.                             |
| `provider_field` | `str`          | Provider's source field or concept, for example `"Revenues"`. Non-empty. |
| `form`           | `str`          | Source filing form, for example `"10-K"`.                             |
| `filed`          | `date`         | Source filing date.                                                   |
| `accession`      | `str`          | Source filing or document identifier.                                 |

Validation (`__post_init__`, raising `ValueError`):

* `metric` is in the vocabulary, and `unit` matches the spec.
* A duration metric has a `period_start`, and `period_start < period_end`. An instant metric has
  `period_start is None`.
* `provider` and `provider_field` are non-empty.

## MetricStatus (enum)

| Member                | Facts     | `reason`  | `error`   | Downstream `require()`                                         |
|-----------------------|-----------|-----------|-----------|----------------------------------------------------------------|
| `AVAILABLE`           | ≥ 1       | `None`    | `None`    | Returns the series.                                            |
| `STRUCTURALLY_ABSENT` | 0         | optional  | `None`    | Returns the empty series.                                      |
| `UNSUPPORTED`         | 0         | required  | optional  | Raises the stored error, or `MetricUnsupportedError(reason)`. With `allow_unsupported=True`, returns the empty series. |
| `INVALID`             | 0         | required  | required  | Always raises the stored error.                                |

Coverage maps `AVAILABLE`, `STRUCTURALLY_ABSENT`, and `UNSUPPORTED` one-to-one onto the existing
`MetricCoverage` members. `INVALID` re-raises, which preserves today's propagation of malformed or
ambiguous data out of `company_coverage`.

## CanonicalSeries

All canonical facts for one metric, plus that metric's status.

| Field          | Type                                 | Notes                                                    |
|----------------|--------------------------------------|----------------------------------------------------------|
| `metric`       | `str`                                | Vocabulary name.                                         |
| `unit`         | `str`                                | Spec unit.                                               |
| `status`       | `MetricStatus`                       | See the table above.                                     |
| `observations` | `tuple[CanonicalFact, ...]`          | Newest fiscal year first, matching today's series order. |
| `reason`       | `str \| None`                        | Human-readable status reason (opaque provider text).     |
| `error`        | `CanonicalDataError \| None`         | Provider's typed error, re-raised on `require`.          |

Validation:

* Every observation has `metric == self.metric`.
* Fiscal years are unique.
* Observations are ordered by descending fiscal year.
* The status matches the facts, reason, and error invariants in the table above.

## CanonicalFinancialHistory

The only input accepted by downstream OwnerLens logic.

| Field       | Type                          | Notes                                                                 |
|-------------|-------------------------------|-----------------------------------------------------------------------|
| `ticker`    | `str`                         | Canonical uppercase ticker.                                           |
| `max_years` | `int`                         | Requested annual window. Instant metrics may hold one extra baseline year. |
| `series`    | `tuple[CanonicalSeries, ...]` | Exactly one series per vocabulary metric, in vocabulary order.        |

Methods:

* `series_for(metric) -> CanonicalSeries` returns the series regardless of status.
* `require(metric, *, allow_unsupported=False) -> CanonicalSeries` applies the status semantics in
  the `MetricStatus` table. Errors are re-raised with `error.with_traceback(None)`.
* `statuses() -> dict[str, MetricStatus]` returns statuses in vocabulary order.
* `providers() -> frozenset[str]` returns the set of providers across all facts, for display and
  notebooks.
* `classmethod build(*, ticker, max_years, facts, structurally_absent=(), unsupported={})` is a
  convenience constructor for tests and notebooks. It groups facts by metric and marks metrics
  that have facts as `AVAILABLE`. Each remaining metric must appear in `structurally_absent` or
  `unsupported` (metric → reason). Otherwise it raises `ValueError` so that an omission fails
  loudly.

Validation:

* `max_years >= 1`.
* The ticker is non-empty and uppercase.
* The series set equals the vocabulary, with no duplicates and none missing.

## Errors

| Class                    | Base                 | Raised when                                              |
|--------------------------|----------------------|----------------------------------------------------------|
| `CanonicalDataError`     | `Exception`          | Base for provider-neutral data failures.                 |
| `MetricUnsupportedError` | `CanonicalDataError` | A required metric has no trusted provider field.         |
| `MetricInvalidError`     | `CanonicalDataError` | Provider data for a metric is malformed or ambiguous.    |

The SEC error classes gain these bases additively (research R5):

| SEC class                                | Added canonical base     |
|------------------------------------------|--------------------------|
| `_annual.ConceptNotFoundError`           | `MetricUnsupportedError` |
| `revenue.RevenueConceptNotFoundError`    | `MetricUnsupportedError` |
| `operating_income.OperatingIncomeConceptNotFoundError` | `MetricUnsupportedError` |
| `_annual.AmbiguousValueError`            | `MetricInvalidError`     |
| `_annual.MalformedFactsError`            | `MetricInvalidError`     |
| `revenue.AmbiguousRevenueError`          | `MetricInvalidError`     |
| `operating_income.AmbiguousOperatingIncomeError` | `MetricInvalidError` |

## SEC mapping (owned by `sec_adapter.py`)

| Canonical metric                         | SEC normalizer                           | Window  | Concept not found       |
|------------------------------------------|------------------------------------------|---------|-------------------------|
| `revenue`                                | `normalize_annual_revenue`               | N       | `UNSUPPORTED`           |
| `operating_income`                       | `normalize_annual_operating_income`      | N       | `UNSUPPORTED`           |
| `net_income`, `operating_cash_flow`, `capital_expenditures`, `diluted_shares`, `income_tax_expense`, `pretax_income`, `repurchases`, `stock_based_compensation` | `reported.normalize_*` | N | `UNSUPPORTED` |
| `dividends_paid`                         | `normalize_dividends_paid`               | N       | `STRUCTURALLY_ABSENT`, because the normalizer returns an empty series |
| `cash`, `current_debt`, `long_term_debt`, `total_assets`, `total_equity` | `balance_sheet.normalize_*` | N + 1 | `UNSUPPORTED` |
| `short_term_investments`                 | `normalize_short_term_investments`       | N + 1   | `STRUCTURALLY_ABSENT`, because the normalizer returns an empty series |

How the adapter assigns status:

* An ambiguous or malformed result makes the metric `INVALID`, and the adapter stores the error.
* An `AnnualObservation` becomes a `CanonicalFact` with `provider="sec"` and
  `provider_field=obs.concept`. The adapter copies `form`, `filed`, and `accession`, and sets
  `period_start=None` for instant metrics.
* The ticker is canonicalized eagerly. An empty ticker raises `ValueError` at mapping time, as the
  first normalizer call does today.

## Downstream row type changes

| Row                   | Field type before          | Field type after          |
|-----------------------|----------------------------|---------------------------|
| `OwnerEconomicsRow`   | `AnnualObservation \| None` | `CanonicalFact \| None`   |
| `CapitalEfficiencyRow`| `AnnualObservation \| None` | `CanonicalFact \| None`   |

Derived-field names and types do not change. Consumers that read `.value`, `.fiscal_year`,
`.form`, `.filed`, and `.accession` are unaffected. A consumer that read `.concept` now reads
`.provider_field`; the only such consumer in `src` is `persistence/adapters.py`.

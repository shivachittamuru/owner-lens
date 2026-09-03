---
title: Canonical Metric Normalization Public API Contract
description: Library contract for canonical metric definitions, per-company resolution, and multi-company normalization
ms.date: 2026-09-02
ms.topic: reference
---

## Scope

The package exposes a canonical metric-definition layer and generalized normalization functions.
Callers request canonical OwnerLens metrics for a company; they never pass SEC concept names. The
duration and instant normalization primitives are preserved and remain distinct. Financial
interpretation (Feature 2) is out of scope and unchanged.

## Canonical metric definitions

### `CanonicalMetricDefinition`

An immutable value describing one economic concept:

| Attribute | Type | Contract |
|-----------|------|----------|
| `name` | `str` | Canonical metric name |
| `kind` | enum | `duration` or `instant` |
| `unit` | `str` | `USD`, or `shares` for diluted shares |
| `default_concepts` | `tuple[str, ...]` | Non-empty ordered default source-concept preference |
| `overrides` | `dict[str, tuple[str, ...]]` | Ticker to replacement preference; empty when none |

The registry defines one such value per in-scope metric. Adobe appears in no `overrides` map.

### Resolver

```text
resolve_concepts(metric: CanonicalMetricDefinition, ticker: str) -> tuple[str, ...]
```

Contract:

1. Canonicalize `ticker` (trim, uppercase); no allow-list is consulted.
2. Return `metric.overrides[ticker]` when present, otherwise `metric.default_concepts`.
3. Never access the network or company facts; resolution is pure and deterministic.

## Generalized normalization

The existing duration and instant normalizers accept any ticker and resolve their concept preference
through the registry. Signatures keep a `ticker` parameter; the Adobe-only gate is removed.

```text
normalize_annual_metric(raw_facts, spec, *, ticker, max_years=5) -> AnnualSeries          # duration
normalize_annual_instant(raw_facts, spec, *, ticker, max_years=5) -> AnnualSeries          # instant
```

Contract:

1. Canonicalize `ticker`; do not reject any ticker on an allow-list.
2. Resolve the per-ticker concept preference for the metric.
3. Feed it to `select_annual_series` (duration) or `select_instant_series` (instant), preserving all
   existing semantics: fiscal-year derivation from period end, full-year and 52/53-week filtering,
   comparative deduplication, explicit ambiguity failures, and unit validation.
4. Return an `AnnualSeries` whose `concept` is the actual selected source concept (provenance).

The thin metric wrappers (`normalize_annual_revenue`, `normalize_annual_operating_income`,
`normalize_net_income`, `normalize_operating_cash_flow`, `normalize_capital_expenditures`,
`normalize_diluted_shares`, `normalize_income_tax_expense`, `normalize_pretax_income`,
`normalize_repurchases`, `normalize_stock_based_compensation`, `normalize_cash`,
`normalize_current_debt`, `normalize_long_term_debt`, `normalize_total_assets`,
`normalize_total_equity`) keep their names and gain a working `ticker` argument.

### Tolerant-absence metrics

```text
normalize_dividends_paid(raw_facts, *, ticker, max_years=5) -> AnnualSeries
normalize_short_term_investments(raw_facts, *, ticker, max_years=5) -> AnnualSeries
```

Contract: when the concept is structurally absent, return an empty `AnnualSeries` (empty `concept`,
no observations) rather than raising, preserving the distinction between a company that lacks the
item and unavailable data. Short-term investments becomes tolerant to support companies such as Visa
that report no `ShortTermInvestments` concept; its investment securities are deliberately not
absorbed into the canonical corporate-cash meaning.

## Failure and coverage behavior

| Outcome | Meaning |
|---------|---------|
| `ConceptNotFoundError` | No default or override concept resolved a qualifying observation (unsupported), for example Visa diluted weighted-average shares |
| `AmbiguousValueError` | A fiscal year had conflicting distinct full-year values (unchanged) |
| `MalformedFactsError` | The payload lacks a usable us-gaap fact structure (unchanged) |
| Empty tolerant series | The concept is structurally absent for a tolerant metric (dividends, short-term investments) |

No normalization returns a fabricated or silently zeroed value. Unsupported metrics fail explicitly
and block dependent per-company outputs that require them.

## Provenance contract

Every returned `AnnualSeries` and each observation exposes the actual selected source concept
alongside the canonical metric name, the company ticker, unit, fiscal year, and filing context, so a
reviewer or agent can always distinguish canonical meaning (for example, `revenue`) from source
concept (for example, `RevenueFromContractWithCustomerExcludingAssessedTax`) and company.

## Regression contract

Adobe results are unchanged: the generalized registry resolves the same concepts Adobe selected
before this slice, and all existing Adobe Feature 1 and Feature 2 outputs, values, and tests are
preserved.

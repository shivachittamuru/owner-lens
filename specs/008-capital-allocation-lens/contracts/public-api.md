---
title: Capital Allocation Lens Public API Contract
description: Minimal Python library contract for Adobe capital-allocation facts and the interpretation layer
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds three reported capital-allocation facts and a deterministic, offline interpretation
layer that explains how Adobe deployed generated cash and whether decisions helped per-share owners. It
supports ADBE only. The reported layer normalizes over an already-retrieved payload; the interpretation
layer performs no SEC retrieval or re-normalization. It reuses and preserves all prior slices and
defines no rules-engine framework, no configurable weights, and no numeric composite or 0-to-100 score.

## Reported facts (`owner_lens.reported`)

Three new duration metric specs and normalizers, reusing `MetricSpec`, `AnnualSeries`, and the existing
`normalize_annual_metric` machinery.

```text
REPURCHASES                = MetricSpec("repurchases", ("PaymentsForRepurchaseOfCommonStock",))
STOCK_BASED_COMPENSATION   = MetricSpec("stock_based_compensation",
                                        ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"))
DIVIDENDS_PAID             = MetricSpec("dividends_paid",
                                        ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"))

normalize_repurchases(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_stock_based_compensation(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries
normalize_dividends_paid(raw_facts, *, ticker="ADBE", max_years=5) -> AnnualSeries  # tolerant: absent -> empty series
```

Contract for each:

1. Accept the raw Company Facts mapping produced by Slice 1 retrieval; reject any ticker other than ADBE.
2. Select the concept using full-year duration semantics and derive the fiscal year from the period-end date.
3. Collapse identical comparative repeats per year, retaining earliest-filed provenance, and raise a
   typed ambiguity error on conflicting distinct values.
4. `normalize_repurchases` and `normalize_stock_based_compensation` raise `ConceptNotFoundError` when no
   concept qualifies; `normalize_dividends_paid` returns an empty `AnnualSeries` instead, because Adobe
   reports no dividend concept.
5. Perform no value estimation, interpolation, or aggregation, and no network access.

## New module (`owner_lens.capital_allocation`)

### Enumerations and types

* `BuybackEffectiveness` — `EFFECTIVE_BUYBACKS`, `PARTIALLY_OFFSET_BY_DILUTION`, `INEFFECTIVE_BUYBACKS`,
  `NET_DILUTION`, `NO_MEANINGFUL_BUYBACK_ACTIVITY`, `INSUFFICIENT_DATA`.
* `CapitalAllocationClassification` — `OWNER_FRIENDLY`, `BALANCED`, `QUESTIONABLE`, `OWNER_UNFRIENDLY`,
  `INSUFFICIENT_DATA`.
* `CapitalAllocationDriver` — the named reason codes in the [data model](data-model.md).
* `CapitalAllocationThresholds` — the named thresholds with the default first-pass values, plus a
  module-level `DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS`.
* `CapitalAllocationRow` — the immutable per-year record listed in the [data model](data-model.md).

### Functions

```text
classify_buyback_effectiveness(
    *, repurchases, repurchases_over_fcf, diluted_share_growth,
    thresholds=DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> BuybackEffectiveness

build_capital_allocation_rows(
    owner_economics, capital_efficiency, snapshots,
    repurchases, stock_based_compensation, dividends_paid,
    *, thresholds=DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> tuple[CapitalAllocationRow, ...]

capital_allocation_from_facts(
    raw_facts, *, ticker="ADBE", max_years=5,
    thresholds=DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
) -> tuple[CapitalAllocationRow, ...]

format_capital_allocation_view(rows) -> str
capital_allocation_summary(rows) -> str
```

Contract:

1. `build_capital_allocation_rows` aligns the reused Feature 1 and 2A outputs and the new facts by
   fiscal year, derives repurchases/FCF, dividends/FCF, SBC/FCF, capital returned, capital returned/FCF,
   and retained FCF (preserving negative), interprets buyback effectiveness from the actual
   diluted-share-count change, classifies each year, and returns rows newest first.
2. Retained FCF is never clamped; ratios are omitted when free cash flow is absent or non-positive; a
   missing repurchase or SBC input omits dependent metrics; a confidently-absent dividend concept
   contributes zero to aggregation and emits `NO_DIVIDEND_PROGRAM`.
3. Buyback effectiveness and the classification are deterministic; identical inputs yield identical
   results and identical ordered drivers, and the classification summarizes observable outcomes, never
   management intent or valuation.
4. The balance-sheet guardrail uses the shared net-cash trajectory helper; ROIC is surfaced as context
   only, with no return on retained free cash flow.
5. `capital_allocation_from_facts` calls the existing `owner_economics_from_facts`,
   `capital_efficiency_from_facts`, and `economic_value_from_facts` and the new reported normalizers,
   then calls `build_capital_allocation_rows`. No network access occurs in the interpretation layer.
6. `format_capital_allocation_view` renders the compact per-year view with drivers;
   `capital_allocation_summary` renders the multi-year owner-question answers.

## Shared helper (`owner_lens._trajectory`)

An internal module exposing a net-cash trajectory function that returns a direction, a sign-flip flag,
and a net-debt flag from a start and end net cash or net debt value. Feature 2A and 2B are refactored to
use it, behavior-preserving, and Feature 2C reuses it. It remains internal.

## Package exports (`owner_lens`)

`owner_lens/__init__.py` re-exports the three normalizers, `BuybackEffectiveness`,
`CapitalAllocationClassification`, `CapitalAllocationDriver`, `CapitalAllocationThresholds`,
`DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS`, `CapitalAllocationRow`, `classify_buyback_effectiveness`,
`build_capital_allocation_rows`, `capital_allocation_from_facts`, `format_capital_allocation_view`, and
`capital_allocation_summary`. No existing export is removed or changed.

## Preservation

All Slice 1A through 1E, 2A, and 2B modules, types, functions, errors, and tests are unchanged in
behavior, including after Feature 2A and 2B are refactored to use the shared trajectory helper.

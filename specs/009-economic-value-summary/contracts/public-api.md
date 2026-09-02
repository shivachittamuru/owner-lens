---
title: Company-Level Economic Value Summary Public API Contract
description: Minimal Python library contract for the deterministic company-level synthesis layer
ms.date: 2026-09-02
ms.topic: reference
---

## Scope

The package adds a deterministic, offline synthesis layer that composes the existing Feature 2A annual
snapshots, Feature 2B recent and long-term compounding views, and Feature 2C capital-allocation rows into
one company-level `EconomicValueSummary`. It supports ADBE only. It adds no SEC facts, makes no SEC
calls, performs no normalization, duplicates no Feature 1 calculation, and reimplements no Feature 2
component logic. It reuses and preserves all prior slices and defines no rules-engine or scoring
framework, no configurable weights, and no numeric composite or 0-to-100 score.

## New module (`owner_lens.economic_summary`)

### `OverallEconomicValueClassification`

An enumeration with members `STRONGLY_IMPROVING`, `IMPROVING`, `STABLE`, `DETERIORATING`,
`STRONGLY_DETERIORATING`, and `INSUFFICIENT_DATA`.

### `SummaryDriver`

An enumeration of the named reason codes listed in the [data model](data-model.md), spanning the
positive, watch, and negative categories. Values are stable code strings; membership is closed for this
slice.

### `EconomicSummaryThresholds`

An immutable value type carrying `severe_roic_collapse` and `high_roic_level` with the default first-pass
values from the [data model](data-model.md), plus a module-level `DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS`.
Most severity reuses component drivers; these thresholds are inspectable cutoffs, not weights.

### `EconomicValueSummary`

Immutable company-level record with the fields listed in the [data model](data-model.md): the ticker and
latest fiscal year, the component classifications (with the recent compounding classification optional),
the overall classification, the ordered positive, watch, and negative driver tuples, and the compact
evidence set. The evidence set is exposed as a nested immutable value or as flat optional fields.

### Functions

```text
synthesize_economic_value_summary(
    ticker: str,
    snapshots: Sequence[EconomicValueSnapshot],
    recent_view: EconomicCompoundingView | None,
    long_term_view: EconomicCompoundingView,
    capital_rows: Sequence[CapitalAllocationRow],
    *,
    thresholds: EconomicSummaryThresholds = DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
) -> EconomicValueSummary

economic_value_summary_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: EconomicSummaryThresholds = DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
) -> EconomicValueSummary

format_economic_value_summary(summary: EconomicValueSummary) -> str
```

Contract:

1. `synthesize_economic_value_summary` reads the latest annual snapshot, the recent and long-term
   compounding views, and the latest capital-allocation row, applies the documented priority hierarchy in
   the [data model](data-model.md) (insufficiency gate, long-term base, latest-year adjustment,
   capital-allocation modifier, severe guardrails), synthesizes ordered deduplicated positive, watch, and
   negative drivers traceable to the component outputs, assembles the compact evidence set, and returns the
   summary. The positive result never exceeds the long-term base, so `STRONGLY_IMPROVING` requires
   long-term `STRONGLY_COMPOUNDING`.
2. Watch signals become drivers only; guardrail signals (sustained ROIC collapse, deepening or persistent
   net debt) downgrade the score. Identical inputs return the identical classification and identical
   ordered drivers, and the verdict is never a mapping, average, or weighted score of the components.
3. When the long-term and latest annual components are both insufficient, the overall classification is
   `INSUFFICIENT_DATA`; when the recent view is unavailable, its classification is omitted and the
   long-term view alone anchors the base.
4. `economic_value_summary_from_facts` calls the existing `economic_value_from_facts`,
   `compounding_views_from_facts`, and `capital_allocation_from_facts` on the already-retrieved payload,
   then calls `synthesize_economic_value_summary`. No network access occurs in the synthesis layer.
5. `format_economic_value_summary` renders the compact owner-readable lens (component classifications,
   overall classification, core evidence, and the positive, watch, and negative drivers).
6. `ticker` other than `ADBE` is rejected by the underlying entry points; the synthesis layer adds no new
   ticker handling.

## Package exports (`owner_lens`)

`owner_lens/__init__.py` re-exports `OverallEconomicValueClassification`, `SummaryDriver`,
`EconomicSummaryThresholds`, `DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS`, `EconomicValueSummary`,
`synthesize_economic_value_summary`, `economic_value_summary_from_facts`, and
`format_economic_value_summary`. No existing export is removed or changed.

## Preservation

All Slice 1A through 1E, 2A, 2B, and 2C modules, types, functions, errors, and tests are unchanged. The
feature adds only the synthesis module and its exports and edits no prior behavior.

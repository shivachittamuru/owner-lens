---
title: Multi-Year Economic Compounding View Public API Contract
description: Minimal Python library contract for the deterministic multi-year compounding interpretation layer
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds a deterministic, offline interpretation layer that turns the existing Feature 1
metrics and Feature 2A annual snapshots into a per-period `EconomicCompoundingView` with a transparent
classification and ordered named drivers. It supports ADBE only, performs no SEC retrieval or
re-normalization inside the layer, duplicates no Feature 1 calculation, adds no network access of its
own, and reuses and preserves all prior slices. It defines no analytics framework, no rules-engine
framework, no configurable weights, and no numeric composite or 0-to-100 score.

## New module (`owner_lens.compounding`)

### `CompoundingClassification`

An enumeration with members `STRONGLY_COMPOUNDING`, `COMPOUNDING`, `STABLE`, `DETERIORATING`, and
`INSUFFICIENT_DATA`.

### `CompoundingDriver`

An enumeration of the named reason codes listed in the [data model](data-model.md). Values are stable
code strings; membership is closed for this slice.

### `CompoundingThresholds`

An immutable value type carrying the named thresholds `strong_fcf_per_share_cagr`,
`healthy_fcf_per_share_cagr`, `flat_cagr_band`, `material_fcf_cagr`, `material_margin_change`,
`material_roic_change`, `material_share_cagr`, and `high_roic_level`, with the default first-pass
values from the [data model](data-model.md). A module-level `DEFAULT_COMPOUNDING_THRESHOLDS` instance
is exposed. Thresholds may be supplied to the classification and builder functions to test boundaries;
they are not weights.

### `EconomicCompoundingView`

Immutable per-period record with the fields listed in the [data model](data-model.md): the period
bounds and `years`; the CAGRs; the start, end, and change of operating margin, FCF margin, ROIC, and
net cash or net debt; the four annual-classification counts; the `classification`; and the ordered
`drivers` tuple. All rate and level fields are optional (`... | None`) except the period bounds,
`years`, and the counts.

### Functions

```text
cagr(
    begin: float | None,
    end: float | None,
    years: int,
) -> float | None

classify_compounding(
    view: EconomicCompoundingView,
    *,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> tuple[CompoundingClassification, tuple[CompoundingDriver, ...]]

build_compounding_view(
    owner_economics: Sequence[OwnerEconomicsRow],
    capital_efficiency: Sequence[CapitalEfficiencyRow],
    snapshots: Sequence[EconomicValueSnapshot],
    *,
    period_years: int,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> EconomicCompoundingView

compounding_view_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    period_years: int,
    max_years: int = 5,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> EconomicCompoundingView

compounding_views_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: CompoundingThresholds = DEFAULT_COMPOUNDING_THRESHOLDS,
) -> tuple[EconomicCompoundingView, EconomicCompoundingView]

format_compounding_view(view: EconomicCompoundingView) -> str
```

Contract:

1. `cagr` returns `(end / begin) ** (1 / years) - 1` only when both endpoints are present, `years` is
   positive, `begin` is positive, and `end` is positive; otherwise it returns `None`. It never
   fabricates a rate and never uses the observation count as the exponent denominator.
2. `classify_compounding` applies the documented deterministic rule in the [data model](data-model.md):
   an insufficiency gate on `fcf_per_share_cagr`, a primary per-share base, tempering for the
   share-count-driven illusion, material dilution, and ROIC deterioration (clamped at `STABLE`), a
   deteriorating-base confirmation, and a corroborating-signal tie-break on a stable base. It returns
   the classification and the drivers in fixed priority order. Identical inputs return identical
   results, and the verdict is never an average of the annual classifications.
3. `build_compounding_view` selects the period's start and end fiscal years deterministically from the
   canonical fiscal years for the requested `period_years` interval count (an N-year CAGR spans
   `FY(end - N)` through `FY(end)`), computes the CAGRs over `years = end - start = period_years`
   intervals, computes the start-to-end deltas, counts the annual classifications within the period,
   classifies, and returns the view. When the requested span exceeds the available history, it returns
   a view marked `INSUFFICIENT_DATA` with `INSUFFICIENT_MULTI_YEAR_HISTORY` rather than fabricating
   endpoints.
4. `compounding_view_from_facts` calls the existing `owner_economics_from_facts`,
   `capital_efficiency_from_facts`, and `economic_value_from_facts` (with `max_years`), then calls
   `build_compounding_view`. All network access and normalization occur inside those Feature 1 and
   Feature 2A entry points, never inside the compounding layer.
5. `compounding_views_from_facts` returns the recent 3-year CAGR view and the longest available view
   (capped at a 5-year CAGR; a 4-year CAGR with five observations).
6. `ticker` other than `ADBE` is rejected by the underlying Feature 1 and Feature 2A entry points; the
   compounding layer adds no new ticker handling.

## Package exports (`owner_lens`)

`owner_lens/__init__.py` re-exports `CompoundingClassification`, `CompoundingDriver`,
`CompoundingThresholds`, `DEFAULT_COMPOUNDING_THRESHOLDS`, `EconomicCompoundingView`, `cagr`,
`classify_compounding`, `build_compounding_view`, `compounding_view_from_facts`,
`compounding_views_from_facts`, and `format_compounding_view`. No existing export is removed or changed.

## Preservation

All Slice 1A through 1E and Slice 2A modules, types, functions, errors, and tests are unchanged. The
feature adds only the compounding module and its exports and edits no prior behavior.

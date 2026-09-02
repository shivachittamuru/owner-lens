---
title: Annual Economic Value Snapshot Public API Contract
description: Minimal Python library contract for the deterministic owner-economics interpretation layer
ms.date: 2026-09-01
ms.topic: reference
---

## Scope

The package adds a deterministic, offline interpretation layer that turns the existing Feature 1
owner-economics and capital-efficiency outputs into a per-fiscal-year `EconomicValueSnapshot` with a
transparent classification and ordered named drivers. It supports ADBE only, performs no SEC retrieval
or re-normalization inside the layer, adds no network access of its own, and reuses and preserves all
prior slices. It defines no rules-engine framework, no configurable weights, and no numeric
composite or 0-to-100 score.

## New module (`owner_lens.economic_value`)

### `EconomicValueClassification`

An enumeration with members `IMPROVING`, `STABLE`, `DETERIORATING`, and `INSUFFICIENT_DATA`.

### `EconomicValueDriver`

An enumeration of the named reason codes listed in the [data model](data-model.md). Values are stable
code strings; membership is closed for this slice.

### `EconomicValueThresholds`

An immutable value type carrying the named materiality thresholds `material_growth`,
`material_margin_change`, `material_roic_change`, `severe_roic_change`, `material_share_change`, and
`high_roic_level`, with the default first-pass values from the [data model](data-model.md). A
module-level `DEFAULT_THRESHOLDS` instance is exposed. Thresholds may be supplied to the classification
and builder functions to test boundaries; they are not weights.

### `EconomicValueSnapshot`

Immutable per-year record with the fields listed in the [data model](data-model.md): `fiscal_year`;
the LEVEL signals `operating_margin`, `fcf_margin`, `fcf_per_share`, `roic`, `net_cash_or_debt`; the
CHANGE signals `revenue_growth`, `operating_margin_change`, `fcf_growth`, `fcf_margin_change`,
`diluted_share_growth`, `fcf_per_share_growth`, `roic_change`; the `classification`; and the ordered
`drivers` tuple. All signal fields are optional (`... | None`) except `fiscal_year`.

### Functions

```text
classify_economic_value(
    snapshot: EconomicValueSnapshot,
    *,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueClassification, tuple[EconomicValueDriver, ...]]

build_economic_value_snapshots(
    owner_economics: Sequence[OwnerEconomicsRow],
    capital_efficiency: Sequence[CapitalEfficiencyRow],
    *,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueSnapshot, ...]

economic_value_from_facts(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
    thresholds: EconomicValueThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EconomicValueSnapshot, ...]
```

Contract:

1. `classify_economic_value` applies the documented deterministic rule in the
   [data model](data-model.md): an insufficiency gate on `fcf_per_share_growth`, a primary per-share
   verdict, capital-efficiency and leverage guardrails on an improving base, a tempering rule on a
   deteriorating base, and a corroborating-signal tie-break on a stable base. It returns the
   classification and the drivers in fixed priority order. Identical inputs return identical results.
2. `classify_economic_value` reads only the snapshot's fields and the thresholds; it performs no
   input mutation, no network access, and no randomness.
3. `build_economic_value_snapshots` aligns the two row sequences by fiscal year, reuses the change and
   level signals Feature 1 already exposes, derives `revenue_growth`, `operating_margin_change`,
   `fcf_margin_change`, and `roic_change` as adjacent-year deltas within the provided window, assembles
   one snapshot per fiscal year, classifies each, and returns them ordered by fiscal year descending.
4. A CHANGE signal is `None` whenever its prior-year input is absent; the earliest year in the window
   therefore has `None` change signals and classifies as `INSUFFICIENT_DATA`. Zero is never
   substituted for a missing change.
5. `economic_value_from_facts` calls the existing `owner_economics_from_facts` and
   `capital_efficiency_from_facts` (both with `max_years`), then calls
   `build_economic_value_snapshots`. All network access and normalization occur inside those Feature 1
   entry points, never inside the interpretation layer.
6. `ticker` other than `ADBE` is rejected by the underlying Feature 1 entry points; the interpretation
   layer adds no new ticker handling.

## Package exports (`owner_lens`)

`owner_lens/__init__.py` re-exports `EconomicValueClassification`, `EconomicValueDriver`,
`EconomicValueThresholds`, `DEFAULT_THRESHOLDS`, `EconomicValueSnapshot`, `classify_economic_value`,
`build_economic_value_snapshots`, and `economic_value_from_facts`. No existing export is removed or
changed.

## Preservation

All Slice 1A through 1E modules, types, functions, errors, and tests are unchanged. The feature adds
only the interpretation module and its exports and edits no Feature 1 behavior.

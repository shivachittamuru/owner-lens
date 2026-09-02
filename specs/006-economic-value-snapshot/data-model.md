---
title: Annual Economic Value Snapshot Data Model
description: Snapshot fields, signals, thresholds, drivers, classification states, and validation rules
ms.date: 2026-09-01
ms.topic: reference
---

## Economic Value Snapshot

One completed fiscal year of owner-oriented signals, its classification, and the ordered drivers that
explain the classification. It is a derived interpretation record built only from Feature 1 outputs.

### Fields

| Field                     | Type                              | Meaning                                                      |
|---------------------------|-----------------------------------|--------------------------------------------------------------|
| `fiscal_year`             | integer                           | Economic fiscal year                                         |
| `revenue_growth`          | float or absent                   | CHANGE: adjacent-year revenue growth                         |
| `operating_margin`        | float or absent                   | LEVEL: operating income / revenue                            |
| `operating_margin_change` | float or absent                   | CHANGE: adjacent-year operating-margin delta (percentage points) |
| `fcf_growth`              | float or absent                   | CHANGE: adjacent-year aggregate free-cash-flow growth        |
| `fcf_margin`              | float or absent                   | LEVEL: free cash flow / revenue                              |
| `fcf_margin_change`       | float or absent                   | CHANGE: adjacent-year FCF-margin delta (percentage points)   |
| `diluted_share_growth`    | float or absent                   | CHANGE: adjacent-year diluted-share-count growth (dilution positive) |
| `fcf_per_share`           | float or absent                   | LEVEL: free cash flow per diluted share                      |
| `fcf_per_share_growth`    | float or absent                   | CHANGE: adjacent-year FCF-per-share growth (primary signal)  |
| `roic`                    | float or absent                   | LEVEL: return on invested capital                            |
| `roic_change`             | float or absent                   | CHANGE: adjacent-year ROIC delta (percentage points)         |
| `net_cash_or_debt`        | integer or absent                 | LEVEL: net cash (positive) or net debt (negative)            |
| `classification`          | Economic Value Classification     | Deterministic verdict for the year                           |
| `drivers`                 | ordered tuple of Driver           | Named reason codes explaining the classification             |

### Validation rules

* LEVEL fields and CHANGE fields are distinct; no field blends a level with a change.
* Every CHANGE field is absent when its prior-year input is unavailable; zero is never substituted.
* `revenue_growth`, `operating_margin_change`, `fcf_margin_change`, and `roic_change` are derived here
  as adjacent-year deltas of Feature 1 level values; `fcf_growth`, `fcf_per_share_growth`, and
  `diluted_share_growth` are reused directly from `OwnerEconomicsRow`.
* Margin and ROIC change fields are differences of ratios (percentage points), not growth rates.
* `drivers` is emitted in a fixed priority order, so identical inputs yield identical ordered drivers.
* Economically valid negatives (net debt, negative growth, margin contraction) are valid inputs.

## Signal Source Map

Where each snapshot field originates. The interpretation layer performs no SEC retrieval.

| Snapshot field            | Source                                                                 |
|---------------------------|------------------------------------------------------------------------|
| `operating_margin`        | `OwnerEconomicsRow.operating_margin` (level, reused)                   |
| `fcf_margin`              | `OwnerEconomicsRow.fcf_margin` (level, reused)                         |
| `fcf_per_share`           | `OwnerEconomicsRow.fcf_per_share` (level, reused)                      |
| `fcf_growth`              | `OwnerEconomicsRow.fcf_growth` (change, reused)                        |
| `fcf_per_share_growth`    | `OwnerEconomicsRow.fcf_per_share_growth` (change, reused)              |
| `diluted_share_growth`    | `OwnerEconomicsRow.diluted_share_growth` (change, reused)              |
| `roic`                    | `CapitalEfficiencyRow.roic` (level, reused)                            |
| `net_cash_or_debt`        | `CapitalEfficiencyRow.net_cash` (level, reused)                        |
| `revenue_growth`          | Derived: adjacent-year growth of `OwnerEconomicsRow.revenue.value`     |
| `operating_margin_change` | Derived: adjacent-year delta of `OwnerEconomicsRow.operating_margin`   |
| `fcf_margin_change`       | Derived: adjacent-year delta of `OwnerEconomicsRow.fcf_margin`         |
| `roic_change`             | Derived: adjacent-year delta of `CapitalEfficiencyRow.roic`            |

## Economic Value Classification

The deterministic verdict for a fiscal year.

| Value               | Meaning                                                                    |
|---------------------|----------------------------------------------------------------------------|
| `IMPROVING`         | Per-share economics strengthened without material offsetting deterioration |
| `STABLE`            | Per-share economics roughly unchanged, or offsetting signals balance out   |
| `DETERIORATING`     | Per-share economics weakened, or negative signals dominate                 |
| `INSUFFICIENT_DATA` | The minimum comparison information (present FCF-per-share growth) is absent |

## Economic Value Thresholds

Centralized, named, immutable cutoffs with a single module-level default. Not configurable weights;
these are inspectable materiality boundaries.

| Name                     | Default | Concept                                                       |
|--------------------------|---------|---------------------------------------------------------------|
| `material_growth`        | 0.05    | Materiality for growth-type change signals (±5%)              |
| `material_margin_change` | 0.01    | Margin expansion/contraction (±1 percentage point)           |
| `material_roic_change`   | 0.02    | ROIC improvement/deterioration (±2 percentage points)        |
| `severe_roic_change`     | 0.05    | Severe ROIC deterioration guardrail (−5 percentage points)   |
| `material_share_change`  | 0.01    | Material dilution or buyback (±1%)                            |
| `high_roic_level`        | 0.20    | Sustained-high-ROIC level driver (≥20%)                      |

### Validation rules

* All thresholds are non-negative floats and compared symmetrically for positive and negative moves.
* Thresholds are documented in one place and may be changed without touching classification logic.
* No per-signal weight is exposed; the classification is a rule, not a weighted sum.

## Driver (Reason Code)

A named, deterministic explanation contributing to a classification. Emitted in a fixed priority order:
per-share, then capital efficiency, then margins, then share count and balance sheet, then aggregate
revenue and free cash flow, with guardrail and insufficiency codes attached where they apply.

| Driver                                               | Emitted when                                              |
|------------------------------------------------------|-----------------------------------------------------------|
| `FCF_PER_SHARE_STRONG_GROWTH`                        | FCF/share growth ≥ `material_growth`                      |
| `FCF_PER_SHARE_DECLINE`                              | FCF/share growth ≤ −`material_growth`                     |
| `ROIC_EXPANDED`                                      | ROIC change ≥ `material_roic_change`                      |
| `ROIC_CONTRACTED`                                    | ROIC change ≤ −`material_roic_change`                     |
| `ROIC_SUSTAINED_HIGH`                                | ROIC level ≥ `high_roic_level`                            |
| `OPERATING_MARGIN_EXPANDED`                          | Operating-margin change ≥ `material_margin_change`        |
| `OPERATING_MARGIN_CONTRACTED`                        | Operating-margin change ≤ −`material_margin_change`       |
| `FCF_MARGIN_EXPANDED`                                | FCF-margin change ≥ `material_margin_change`              |
| `FCF_MARGIN_CONTRACTED`                              | FCF-margin change ≤ −`material_margin_change`             |
| `SHARE_COUNT_DECLINED`                               | Diluted-share growth ≤ −`material_share_change`           |
| `SHARE_COUNT_INCREASED`                              | Diluted-share growth ≥ `material_share_change`            |
| `NET_CASH_IMPROVED`                                  | Net position materially improved without a sign flip      |
| `NET_CASH_DETERIORATED`                              | Net position materially worsened without a sign flip      |
| `TURNED_TO_NET_CASH`                                 | Net position flipped from net debt to net cash            |
| `TURNED_TO_NET_DEBT`                                 | Net position flipped from net cash to net debt            |
| `REVENUE_MATERIAL_GROWTH`                            | Revenue growth ≥ `material_growth`                        |
| `REVENUE_DECLINE`                                    | Revenue growth ≤ −`material_growth`                       |
| `FCF_MATERIAL_GROWTH`                                | Aggregate FCF growth ≥ `material_growth`                  |
| `FCF_DECLINE`                                        | Aggregate FCF growth ≤ −`material_growth`                 |
| `PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION`      | Improving per-share base tempered by ROIC deterioration   |
| `PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION`  | Improving per-share base tempered by leverage deterioration |
| `PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY`         | Marginal per-share decline offset by ROIC and margin expansion |
| `INSUFFICIENT_PRIOR_YEAR_DATA`                       | FCF/share growth unavailable, so the year cannot be judged |

The exact code names may evolve; their behavior is fixed for given inputs and covered by tests.

## Classification State Transitions

```text
Snapshot signals for a fiscal year
  -> fcf_per_share_growth unavailable
       -> INSUFFICIENT_DATA (driver INSUFFICIENT_PRIOR_YEAR_DATA)
  -> fcf_per_share_growth available
       -> primary per-share verdict (IMPROVING / STABLE / DETERIORATING base)
            -> base IMPROVING
                 -> material/severe ROIC or leverage deterioration
                      -> downgrade to STABLE or DETERIORATING (offset driver)
                 -> otherwise -> IMPROVING
            -> base DETERIORATING
                 -> marginal decline offset by strong ROIC and margin expansion
                      -> raise to STABLE (offset driver)
                 -> otherwise -> DETERIORATING
            -> base STABLE
                 -> corroborating secondary signals counted
                      -> >=2 net positive -> IMPROVING
                      -> >=2 net negative -> DETERIORATING
                      -> otherwise -> STABLE
```

Every branch emits its contributing drivers in the fixed priority order; no branch fabricates a value
for a missing signal.

## Compact Owner-Oriented View

The per-year presentation over approximately the latest five completed fiscal years, newest first.

* Columns: fiscal year, revenue growth, operating-margin change, FCF growth, FCF-per-share growth,
  share growth, ROIC, ROIC change, net cash or net debt, classification.
* The structured drivers for each year are displayed alongside or beneath the row.
* The earliest displayed year shows `INSUFFICIENT_DATA` because its adjacent-year change signals require
  a prior year not present in the display window.

---
title: Multi-Year Economic Compounding View Data Model
description: View fields, CAGR and delta semantics, thresholds, drivers, classification states, and validation rules
ms.date: 2026-09-01
ms.topic: reference
---

## Economic Compounding View

One requested multi-year period of compounding rates, start-to-end changes, annual-classification
counts, the classification, and the ordered drivers. It is a derived interpretation record built only
from Feature 1 metrics and Feature 2A snapshots.

### Fields

| Field                        | Type                            | Meaning                                                     |
|------------------------------|---------------------------------|-------------------------------------------------------------|
| `start_fiscal_year`          | integer                         | First fiscal year of the period                             |
| `end_fiscal_year`            | integer                         | Last fiscal year of the period                              |
| `years`                      | integer                         | Fiscal-year intervals (`end - start`); CAGR exponent denominator |
| `revenue_cagr`               | float or absent                 | Revenue CAGR over the period                                |
| `fcf_cagr`                   | float or absent                 | Aggregate free-cash-flow CAGR over the period               |
| `fcf_per_share_cagr`         | float or absent                 | Free-cash-flow-per-share CAGR (primary per-share measure)   |
| `diluted_share_cagr`         | float or absent                 | Diluted-share-count CAGR (positive is dilution)             |
| `operating_margin_start`     | float or absent                 | Operating margin at the start fiscal year                   |
| `operating_margin_end`       | float or absent                 | Operating margin at the end fiscal year                     |
| `operating_margin_change`    | float or absent                 | End minus start operating margin (percentage points)        |
| `fcf_margin_start`           | float or absent                 | FCF margin at the start fiscal year                         |
| `fcf_margin_end`             | float or absent                 | FCF margin at the end fiscal year                           |
| `fcf_margin_change`          | float or absent                 | End minus start FCF margin (percentage points)              |
| `roic_start`                 | float or absent                 | ROIC at the start fiscal year                               |
| `roic_end`                   | float or absent                 | ROIC at the end fiscal year                                 |
| `roic_change`                | float or absent                 | End minus start ROIC (percentage points)                    |
| `net_cash_or_debt_start`     | integer or absent               | Net cash or net debt at the start fiscal year               |
| `net_cash_or_debt_end`       | integer or absent               | Net cash or net debt at the end fiscal year                 |
| `net_cash_or_debt_change`    | integer or absent               | End minus start net cash or net debt                        |
| `improving_count`            | integer                         | Annual snapshots in the period classified improving         |
| `stable_count`               | integer                         | Annual snapshots in the period classified stable            |
| `deteriorating_count`        | integer                         | Annual snapshots in the period classified deteriorating     |
| `insufficient_count`         | integer                         | Annual snapshots in the period classified insufficient-data |
| `classification`             | Compounding Classification      | Deterministic period verdict                                |
| `drivers`                    | ordered tuple of Driver         | Named reason codes explaining the classification            |

### Validation rules

* Compounding rates (CAGRs) and start-to-end level changes are distinct fields; no field blends them.
* `years` equals `end_fiscal_year - start_fiscal_year` and is the CAGR exponent denominator.
* Any CAGR is absent when its computation is invalid (see CAGR rules); no rate is fabricated.
* Change fields are `end - start`; they are absent when either endpoint is absent.
* The annual counts sum to the number of annual snapshots within the period.
* `drivers` is emitted in a fixed priority order, so identical inputs yield identical ordered drivers.
* Economically valid negatives (net debt, negative change) are valid inputs.

## CAGR Semantics

| Aspect            | Rule                                                                              |
|-------------------|-----------------------------------------------------------------------------------|
| Formula           | `(end / begin) ** (1 / years) - 1`                                                 |
| `years`           | Fiscal-year intervals = `end_fiscal_year - start_fiscal_year` (observations − 1)  |
| Missing endpoint  | Absent (`None`)                                                                    |
| `years <= 0`      | Absent (`None`)                                                                    |
| `begin == 0`      | Absent (`None`)                                                                    |
| `begin < 0`       | Absent (`None`)                                                                    |
| `end <= 0`        | Absent (`None`) — sign change or non-positive ending                              |
| Otherwise         | Standard formula                                                                   |

## Signal Source Map

Where each view field originates. The compounding layer performs no SEC retrieval.

| View field                 | Source                                                                    |
|----------------------------|---------------------------------------------------------------------------|
| `revenue_cagr`             | CAGR of `OwnerEconomicsRow.revenue.value` at end vs start                  |
| `fcf_cagr`                 | CAGR of `OwnerEconomicsRow.free_cash_flow` at end vs start                 |
| `fcf_per_share_cagr`       | CAGR of `OwnerEconomicsRow.fcf_per_share` at end vs start                  |
| `diluted_share_cagr`       | CAGR of `OwnerEconomicsRow.diluted_shares.value` at end vs start           |
| `operating_margin_*`       | `OwnerEconomicsRow.operating_margin` at start and end, and their delta     |
| `fcf_margin_*`             | `OwnerEconomicsRow.fcf_margin` at start and end, and their delta           |
| `roic_*`                   | `CapitalEfficiencyRow.roic` at start and end, and their delta              |
| `net_cash_or_debt_*`       | `CapitalEfficiencyRow.net_cash` at start and end, and their delta          |
| annual counts              | `EconomicValueSnapshot.classification` for snapshots within the period     |

## Compounding Classification

| Value                  | Meaning                                                                    |
|------------------------|----------------------------------------------------------------------------|
| `STRONGLY_COMPOUNDING` | Strong per-share compounding without material offsetting deterioration     |
| `COMPOUNDING`          | Healthy per-share compounding, or a tempered strong result                 |
| `STABLE`               | Roughly flat per-share compounding, or balanced offsetting signals         |
| `DETERIORATING`        | Per-share compounding declined, or negative signals dominate               |
| `INSUFFICIENT_DATA`    | Required CAGR endpoints or multi-year history are unavailable               |

## Compounding Thresholds

Centralized, named, immutable cutoffs with a single module-level default. Not configurable weights.

| Name                         | Default | Concept                                                    |
|------------------------------|---------|------------------------------------------------------------|
| `strong_fcf_per_share_cagr`  | 0.15    | Strong per-share compounding (≥15%)                       |
| `healthy_fcf_per_share_cagr` | 0.07    | Healthy per-share compounding (≥7%)                       |
| `flat_cagr_band`             | 0.02    | Roughly flat compounding (absolute <2%)                   |
| `material_fcf_cagr`          | 0.05    | Material aggregate FCF decline or growth (±5%)            |
| `material_margin_change`     | 0.02    | Meaningful multi-year margin change (±2 pp)               |
| `material_roic_change`       | 0.03    | Meaningful multi-year ROIC change (±3 pp)                 |
| `material_share_cagr`        | 0.01    | Meaningful dilution or shrinkage (±1%)                    |
| `high_roic_level`            | 0.20    | Sustained high ROIC (≥20%)                                |

### Validation rules

* All thresholds are non-negative floats and compared symmetrically for positive and negative moves.
* Thresholds are documented in one place and may be changed without touching classification logic.
* No per-signal weight is exposed; the classification is a rule, not a weighted sum.

## Compounding Driver (Reason Code)

Emitted in a fixed priority order: per-share compounding, aggregate-versus-per-share, capital
efficiency, margins, share count, balance sheet, annual consistency, with the insufficiency code where
it applies. See [research](research.md) for the full mapping. Members include
`STRONG_FCF_PER_SHARE_COMPOUNDING`, `MODERATE_FCF_PER_SHARE_COMPOUNDING`,
`WEAK_FCF_PER_SHARE_COMPOUNDING`, `FCF_PER_SHARE_DECLINED`, `AGGREGATE_FCF_GREW`,
`AGGREGATE_FCF_DECLINED`, `SHARE_COUNT_SHRANK`, `MATERIAL_DILUTION`, `ROIC_HIGH_AND_SUSTAINED`,
`ROIC_IMPROVED`, `ROIC_DETERIORATED`, `OPERATING_MARGIN_EXPANDED`, `OPERATING_MARGIN_CONTRACTED`,
`FCF_MARGIN_EXPANDED`, `FCF_MARGIN_CONTRACTED`, `BALANCE_SHEET_IMPROVED`, `BALANCE_SHEET_DETERIORATED`,
`CONSISTENT_ANNUAL_IMPROVEMENT`, `MIXED_ANNUAL_ECONOMICS`, and `INSUFFICIENT_MULTI_YEAR_HISTORY`.

## Period Selection

| Period            | End fiscal year          | Start fiscal year                 | Insufficient when                     |
|-------------------|--------------------------|-----------------------------------|---------------------------------------|
| Recent 3-year CAGR| Latest common fiscal year| `end - 3` (3 intervals)           | `end - 3` not in canonical fiscal years |
| Longest available | Latest common fiscal year| `end - min(5, available_intervals)` | Fewer than two canonical fiscal years |

`period_years` is the number of fiscal-year intervals (years of compounding), and `years` always
equals `end_fiscal_year - start_fiscal_year = period_years`. `available_intervals` is the count of
canonical fiscal years minus one. The long view is capped at a 5-year CAGR and uses the longest span
the history supports (a 4-year CAGR with five observations, a 5-year CAGR with six). Selection is a
pure function of the sorted canonical fiscal years and assumes no fixed history length.

## Classification State Transitions

```text
Period signals
  -> fcf_per_share_cagr unavailable (missing endpoints / insufficient history)
       -> INSUFFICIENT_DATA (driver INSUFFICIENT_MULTI_YEAR_HISTORY)
  -> fcf_per_share_cagr available
       -> primary per-share base (STRONGLY_COMPOUNDING / COMPOUNDING / STABLE / DETERIORATING)
            -> base compounding (strong or healthy or weak)
                 -> share-count-driven illusion, material dilution, or ROIC deterioration
                      -> notch downgrade(s), clamped at STABLE (with offset drivers)
                 -> otherwise -> keep base
            -> base DETERIORATING
                 -> marginal decline offset by ROIC and margin expansion -> STABLE
                 -> otherwise -> DETERIORATING
            -> base STABLE
                 -> >=2 net-positive secondary signals -> COMPOUNDING
                 -> >=2 net-negative or deteriorating annual majority -> DETERIORATING
                 -> otherwise -> STABLE
```

Annual counts always emit a consistency driver as context and inform only the stable-base tie-break;
the multi-year verdict is never an average of the annual verdicts.

## Compact Compounding View (presentation)

* Header: `ADBE Economic Compounding — FY{start} → FY{end}` with the interval count.
* Compounding rates: revenue, aggregate FCF, FCF per share, diluted-share CAGR.
* Quality and balance sheet: operating margin, FCF margin, ROIC, and net cash or net debt, each start → end.
* Annual snapshots: improving, stable, deteriorating, and insufficient-data counts.
* Classification and the ordered drivers.

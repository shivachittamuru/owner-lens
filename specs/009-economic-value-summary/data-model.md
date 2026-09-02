---
title: Company-Level Economic Value Summary Data Model
description: Summary fields, evidence set, classification, drivers, thresholds, hierarchy, and states
ms.date: 2026-09-02
ms.topic: reference
---

## Economic Value Summary

The company-level synthesis record. It is a derived composition of Feature 2A, 2B, and 2C outputs.

### Fields

| Field                                   | Type                                   | Meaning                                            |
|-----------------------------------------|----------------------------------------|----------------------------------------------------|
| `ticker`                                | string                                 | Company ticker (ADBE)                              |
| `latest_fiscal_year`                    | integer                                | Most recent completed fiscal year available        |
| `latest_annual_classification`          | Economic Value Classification          | Latest Feature 2A snapshot verdict                 |
| `recent_compounding_classification`     | Compounding Classification or absent   | Feature 2B recent-view verdict, absent if too short |
| `long_term_compounding_classification`  | Compounding Classification             | Feature 2B long-term-view verdict                  |
| `latest_capital_allocation_classification` | Capital Allocation Classification   | Latest Feature 2C row verdict                      |
| `overall_economic_value_classification` | Overall Economic Value Classification  | Deterministic company-level verdict                |
| `key_positive_drivers`                  | ordered tuple of Summary Driver        | Ordered, deduplicated positive drivers             |
| `key_watch_drivers`                     | ordered tuple of Summary Driver        | Ordered, deduplicated watch drivers                |
| `key_negative_drivers`                  | ordered tuple of Summary Driver        | Ordered, deduplicated negative drivers             |
| `evidence`                              | Evidence Set                           | Compact headline metrics                           |

### Validation rules

* Every field is read or mapped from an existing Feature 2 output; none is recomputed from raw facts.
* The recent compounding classification is absent when the recent view is unavailable (short history).
* Drivers are ordered by the fixed priority and deduplicated so each appears once across categories.
* The overall classification is coarse (six values) and never a numeric or weighted score.

## Evidence Set

A compact selection of existing metrics, not a re-derivation.

| Field                            | Source                                                        |
|----------------------------------|---------------------------------------------------------------|
| `latest_fcf_per_share_growth`    | Latest `EconomicValueSnapshot.fcf_per_share_growth`           |
| `long_term_fcf_per_share_cagr`   | Long-term `EconomicCompoundingView.fcf_per_share_cagr`        |
| `recent_fcf_per_share_cagr`      | Recent `EconomicCompoundingView.fcf_per_share_cagr` (or absent) |
| `diluted_share_cagr`             | Long-term `EconomicCompoundingView.diluted_share_cagr`        |
| `latest_roic`                    | Latest `EconomicValueSnapshot.roic` (or long-term `roic_end`) |
| `long_term_roic_change`          | Long-term `EconomicCompoundingView.roic_change`               |
| `latest_net_cash_or_debt`        | Latest `CapitalAllocationRow.net_cash_or_debt`                |
| `latest_sbc_to_fcf`              | Latest `CapitalAllocationRow.sbc_over_fcf`                    |
| `latest_capital_returned_to_fcf` | Latest `CapitalAllocationRow.capital_returned_over_fcf`       |
| `buyback_effectiveness`          | Latest `CapitalAllocationRow.buyback_effectiveness`           |

## Overall Economic Value Classification

| Value                     | Ordinal | Meaning                                                     |
|---------------------------|---------|-------------------------------------------------------------|
| `STRONGLY_IMPROVING`      | +2      | Durable strong compounding, confirmed and unguarded         |
| `IMPROVING`               | +1      | Healthy compounding, confirmed by recent economics          |
| `STABLE`                  | 0       | Roughly flat or balanced owner economics                    |
| `DETERIORATING`           | -1      | Weakening per-share economics or a guardrail downgrade      |
| `STRONGLY_DETERIORATING`  | -2      | Severe, guardrail-confirmed deterioration                   |
| `INSUFFICIENT_DATA`       | n/a     | Long-term and latest annual components both unavailable      |

## Synthesis Hierarchy (deterministic)

```text
components
  -> long-term compounding INSUFFICIENT and latest annual INSUFFICIENT
       -> INSUFFICIENT_DATA
  -> long-term compounding base (STRONGLY_COMPOUNDING +2 / COMPOUNDING +1 / STABLE 0 / DETERIORATING -1;
       INSUFFICIENT -> latest annual base, marked not-yet-established)
       -> latest-year adjustment (bounded one notch, never flips a strong base)
            base>=+1 & latest DETERIORATING -> -1 notch + RECENT_SLOWDOWN
            base<=-1 & latest IMPROVING     -> +1 notch + EARLY_IMPROVEMENT_NOT_YET_PROVEN
            agree in sign                   -> confirm (no change)
            -> capital-allocation modifier (bounded, never lifts above base)
                 OWNER_UNFRIENDLY -> -1
                 QUESTIONABLE     -> -1 only if score currently positive; else watch
                 OWNER_FRIENDLY/BALANCED -> confirm
                 -> severe guardrails (force down, last)
                      sustained ROIC collapse (LT roic_change <= -severe_roic_collapse) -> score<=-1 (or -2)
                      deepening/persistent net debt (latest net debt + deterioration driver) -> score<=-1
                      -> clamp [-2,+2] -> overall enum
                      -> attach watch drivers (no score change)
```

The positive result never exceeds the long-term base, so `STRONGLY_IMPROVING` requires long-term
`STRONGLY_COMPOUNDING`.

## Economic Summary Thresholds

Centralized, named, immutable cutoffs with a single module-level default. Not configurable weights.
Most severity reuses component drivers for traceability.

| Name                   | Default | Concept                                                   |
|------------------------|---------|-----------------------------------------------------------|
| `severe_roic_collapse` | 0.10    | Sustained ROIC collapse guardrail (long-term ROIC change ≤ −10 pp) |
| `high_roic_level`      | 0.20    | High ROIC evidence and driver (ROIC ≥ 20%)               |

## Summary Driver (Reason Code)

Ordered within each category by a fixed priority (per-share compounding, ROIC, share count and buybacks,
capital allocation, margins, balance sheet, then tension) and deduplicated. Categories and members:

* **Positive**: `PER_SHARE_CASH_FLOW_COMPOUNDING`, `FCF_PER_SHARE_ACCELERATING`, `HIGH_ROIC`,
  `ROIC_IMPROVING`, `SHARE_COUNT_SHRINKING`, `EFFECTIVE_BUYBACKS`, `OWNER_FRIENDLY_CAPITAL_ALLOCATION`,
  `HEALTHY_BALANCE_SHEET`, `MARGINS_EXPANDING`.
* **Watch**: `HIGH_SBC_BURDEN`, `CAPITAL_RETURNS_EXCEED_FCF`, `DECLINING_NET_CASH_CUSHION`,
  `BUYBACKS_PARTLY_OFFSET_BY_DILUTION`, `MIXED_RECENT_ECONOMICS`, `RECENT_SLOWDOWN`,
  `EARLY_IMPROVEMENT_NOT_YET_PROVEN`.
* **Negative**: `FCF_PER_SHARE_DECLINING`, `MATERIAL_DILUTION`, `ROIC_DETERIORATING`,
  `OWNER_UNFRIENDLY_CAPITAL_ALLOCATION`, `WORSENING_NET_DEBT`, `MARGINS_CONTRACTING`,
  `AGGREGATE_FCF_DECLINING`.

Each driver is traceable to a component classification or component driver. The exact names may evolve;
behavior is fixed for given inputs.

## Compact Summary (presentation)

* Header: `{TICKER} — Economic Value Lens`.
* Component classifications: latest annual, recent compounding, long-term compounding, capital allocation.
* Overall classification.
* Core evidence: FCF/share CAGR, share-count CAGR, ROIC, net cash or net debt.
* What is working (positive drivers), what to watch (watch drivers), and, when present, what is negative.

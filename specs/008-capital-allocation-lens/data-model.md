---
title: Capital Allocation Lens Data Model
description: Reported facts, derived metrics, buyback effectiveness, classification, thresholds, drivers, and states
ms.date: 2026-09-01
ms.topic: reference
---

## Reported Capital-Allocation Observation

One canonical annual reported value with SEC provenance, produced by the existing duration normalizer.

### Documented specifications

| Metric        | `concept_preference`                                                       | `unit` | Absence behavior            |
|---------------|----------------------------------------------------------------------------|--------|-----------------------------|
| Repurchases   | (`PaymentsForRepurchaseOfCommonStock`,)                                    | `USD`  | Fail (expected to exist)    |
| SBC           | (`ShareBasedCompensation`, `AllocatedShareBasedCompensationExpense`)       | `USD`  | Fail (expected to exist)    |
| Dividends paid| (`PaymentsOfDividendsCommonStock`, `PaymentsOfDividends`)                  | `USD`  | Tolerant: return absent series |

### Validation rules

* Selected via full-year duration semantics (has `start`, `fp == FY`, 10-K form, 350-380 day period).
* Fiscal year derived from the period-end date, not the raw XBRL `fy`.
* Identical comparative repeats collapse to the earliest-filed observation; distinct conflicting values
  raise a typed ambiguity error.
* Repurchases are a positive cash-outflow magnitude; the value is preserved exactly.
* The dividend normalizer returns an empty series when no dividend concept is present (absent), rather
  than raising, because Adobe reports no dividend concept.

## Derived Capital-Allocation Metrics

Calculated per fiscal year and kept distinct from reported facts.

| Metric                    | Formula                                              | Omitted when                        |
|---------------------------|------------------------------------------------------|-------------------------------------|
| Repurchases / FCF         | repurchases / free_cash_flow                         | repurchases absent; FCF absent or ≤ 0 |
| Dividends / FCF           | dividends / free_cash_flow                           | dividends absent; FCF absent or ≤ 0 |
| SBC / FCF                 | sbc / free_cash_flow                                 | SBC absent; FCF absent or ≤ 0       |
| Capital returned          | repurchases + dividends (dividends 0 if no program)  | repurchases absent                  |
| Capital returned / FCF    | capital_returned / free_cash_flow                    | capital returned absent; FCF ≤ 0    |
| Retained FCF              | free_cash_flow − repurchases − dividends             | free cash flow or repurchases absent|

### Validation rules

* Retained FCF is an interpretive residual; a negative value (capital returned exceeds free cash flow)
  is preserved, never clamped to zero.
* Conventional free cash flow is shown intact; SBC is never subtracted from it.
* Dividends contribute zero to capital returned and retained FCF only when the dividend concept is
  confidently absent (no program), and this is surfaced by a `NO_DIVIDEND_PROGRAM` driver.
* Ratios are floats; capital returned and retained FCF are integer currency amounts.

## Capital Allocation Row

The per-fiscal-year alignment for display and inspection.

| Field                     | Type                          | Meaning                                   |
|---------------------------|-------------------------------|-------------------------------------------|
| `fiscal_year`             | integer                       | Economic fiscal year                      |
| `free_cash_flow`          | integer or absent             | Reused Feature 1 free cash flow           |
| `repurchases`             | integer or absent             | Reported repurchase cash outflow          |
| `dividends`               | integer or absent             | Reported cash dividends paid (absent for Adobe) |
| `sbc`                     | integer or absent             | Reported stock-based compensation         |
| `repurchases_over_fcf`    | float or absent               | Derived                                   |
| `dividends_over_fcf`      | float or absent               | Derived                                   |
| `sbc_over_fcf`            | float or absent               | Derived                                   |
| `capital_returned`        | integer or absent             | Derived                                   |
| `capital_returned_over_fcf`| float or absent              | Derived                                   |
| `retained_fcf`            | integer or absent             | Derived; may be negative                  |
| `diluted_share_growth`    | float or absent               | Reused Feature 1 share-count growth       |
| `net_cash_or_debt`        | integer or absent             | Reused Feature 1 net cash or net debt     |
| `roic`                    | float or absent               | Reused Feature 1 ROIC                     |
| `buyback_effectiveness`   | Buyback Effectiveness         | Derived interpretation                    |
| `classification`          | Capital Allocation Classification | Derived per-year verdict              |
| `drivers`                 | ordered tuple of Driver       | Named reason codes                        |

## Buyback Effectiveness

| Value                             | Meaning                                                       |
|-----------------------------------|---------------------------------------------------------------|
| `EFFECTIVE_BUYBACKS`              | Meaningful repurchases and a meaningful share-count decline    |
| `PARTIALLY_OFFSET_BY_DILUTION`    | Meaningful repurchases but a roughly flat share count         |
| `INEFFECTIVE_BUYBACKS`            | Meaningful repurchases but a rising share count               |
| `NET_DILUTION`                    | Minimal repurchases and a rising share count                  |
| `NO_MEANINGFUL_BUYBACK_ACTIVITY`  | Minimal repurchases and a flat or shrinking share count       |
| `INSUFFICIENT_DATA`               | Repurchases or the share-count change is unavailable          |

## Capital Allocation Classification

| Value              | Meaning                                                                    |
|--------------------|----------------------------------------------------------------------------|
| `OWNER_FRIENDLY`   | Effective share reduction, manageable SBC, healthy balance sheet, high ROIC |
| `BALANCED`         | Moderate distributions, manageable dilution, no strong signal               |
| `QUESTIONABLE`     | Ineffective or offset buybacks, high SBC, or returns straining the balance sheet |
| `OWNER_UNFRIENDLY` | Material dilution, high SBC, or distributions funded by worsening leverage   |
| `INSUFFICIENT_DATA`| Share-count change or buyback effectiveness unavailable                      |

## Capital Allocation Thresholds

Centralized, named, immutable cutoffs with a single module-level default. Not configurable weights.

| Name                                 | Default | Concept                                          |
|--------------------------------------|---------|--------------------------------------------------|
| `material_share_change`              | 0.01    | Material share-count shrinkage or dilution (±1%)  |
| `high_sbc_to_fcf`                    | 0.15    | High SBC burden (SBC / FCF ≥ 15%)                |
| `meaningful_repurchase_to_fcf`       | 0.25    | Meaningful repurchase activity (≥ 25% of FCF)    |
| `capital_returned_over_fcf_material` | 1.00    | Capital returns materially above free cash flow   |
| `high_roic_level`                    | 0.20    | High ROIC context (ROIC ≥ 20%)                  |
| `material_roic_change`               | 0.03    | ROIC improving or deteriorating (±3 pp)          |

Balance-sheet deterioration reuses the shared net-cash trajectory helper (a turn to net debt or a
deepening net-debt position), not a new dollar threshold.

## Capital Allocation Driver (Reason Code)

Emitted in a fixed priority order: per-share outcome, buyback effectiveness, SBC burden, capital
returned relative to free cash flow, balance-sheet trajectory, ROIC context, then dividend and retained
context. Members include `SHARE_COUNT_SHRANK`, `MATERIAL_DILUTION`, `SHARE_COUNT_FLAT`,
`EFFECTIVE_BUYBACKS`, `BUYBACKS_OFFSET_BY_DILUTION`, `INEFFECTIVE_BUYBACKS`, `NO_MEANINGFUL_BUYBACKS`,
`HIGH_SBC_BURDEN`, `MEANINGFUL_REPURCHASES`, `CAPITAL_RETURNED_EXCEEDS_FCF`, `BALANCE_SHEET_IMPROVED`,
`BALANCE_SHEET_DETERIORATED`, `HIGH_ROIC_CONTEXT`, `LOW_ROIC_CONTEXT`, `ROIC_IMPROVING`,
`ROIC_DETERIORATING`, `RETAINED_FCF_NEGATIVE`, `NO_DIVIDEND_PROGRAM`, and `INSUFFICIENT_CAPITAL_DATA`.
The exact names may evolve; behavior is fixed for given inputs.

## State Transitions

```text
Received payload
  -> Normalizing reported facts (repurchases, SBC, dividends[tolerant])
       -> FailedConceptNotFound (repurchases or SBC missing)
       -> FailedAmbiguousYear (conflicting distinct values)
       -> ReportedFactsResolved (dividends may be absent)
            -> Reusing Feature 1 and 2A outputs (FCF, shares, net cash, ROIC, snapshots)
                 -> Deriving ratios, capital returned, retained FCF
                      -> Interpreting buyback effectiveness
                           -> Classifying capital allocation with ordered drivers
                                -> CapitalAllocationViewReady (latest ~5 years)
```

Every failure state terminates without partial output; unavailable inputs omit dependent metrics and
classify conservatively rather than fabricating values.

## Compact View and Multi-Year Summary

* Per-year columns: fiscal year, free cash flow, repurchases, repurchases / FCF, dividends, SBC,
  SBC / FCF, capital returned, capital returned / FCF, retained FCF, diluted-share growth, buyback
  effectiveness, net cash or net debt, ROIC, and classification, with ordered drivers per year.
* The multi-year summary answers: total free cash flow generated, total repurchases, total dividends,
  SBC relative to free cash flow, whether the diluted share count shrank, whether repurchases overcame
  dilution, whether the balance sheet remained healthy, and whether ROIC remained attractive.

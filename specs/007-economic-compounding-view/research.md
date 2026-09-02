---
title: Multi-Year Economic Compounding View Research
description: CAGR mechanics, period selection, first-pass thresholds, driver codes, and the deterministic compounding classification
ms.date: 2026-09-01
ms.topic: reference
---

## Inputs already available from Feature 1 and Feature 2A

The compounding layer consumes three existing outputs and adds no external data.

`OwnerEconomicsRow` (`owner_lens.owner_economics`) supplies, per fiscal year: `revenue` (observation
with `.value`), `free_cash_flow`, `fcf_per_share`, `diluted_shares` (observation with `.value`),
`operating_margin`, and `fcf_margin`.

`CapitalEfficiencyRow` (`owner_lens.capital_efficiency`) supplies, per fiscal year: `roic` and
`net_cash` (net cash or net debt).

`EconomicValueSnapshot` (`owner_lens.economic_value`) supplies, per fiscal year: `classification`
(one of IMPROVING, STABLE, DETERIORATING, INSUFFICIENT_DATA).

**Decision**: Feature 2B reads these rows and snapshots as-is and never re-normalizes SEC facts or
recomputes a Feature 1 metric. The only period-level values it derives are CAGRs, start-to-end deltas,
and annual-classification counts.

**Rationale**: Every CAGR endpoint and level is already a trusted Feature 1 value; the annual verdicts
are trusted Feature 2A values. Deriving period aggregates from them respects the layer boundary.

**Alternatives considered**: Re-deriving endpoints from raw facts would duplicate normalization and
violate the boundary.

## CAGR definition and interval count

**Decision**: Compute CAGR as `(end / begin) ** (1 / years) - 1`, where `years` is the number of
fiscal-year intervals between the start and end observations, equal to `end_fiscal_year -
start_fiscal_year`. For a span from FY2021 through FY2025 (five observations) `years` is 4, not 5. The
view's `years` field stores this interval count.

**Rationale**: The interval count is the correct exponent denominator; using the observation count
would understate the rate. Deriving `years` from the fiscal-year labels is deterministic and matches
the spec's worked example (FY2021 through FY2025 is a five-year period with four intervals).

**Alternatives considered**: Using the observation count (five) as the denominator is the exact error
the spec forbids; counting calendar days would add false precision without benefit.

## Invalid CAGR handling

**Decision**: `cagr(begin, end, years)` returns `None` (explicit unavailable) when: either endpoint is
missing; `years` is not positive; `begin` is zero; `begin` is negative; or `end` is not positive (a
sign change from a positive beginning to a non-positive ending, which makes the ratio non-positive and
a fractional power undefined or economically meaningless). Otherwise it returns the standard formula.

**Rationale**: A CAGR is only well defined for a positive beginning and a positive ending over a
positive number of intervals. Every excluded case would otherwise force a complex, undefined, or
misleading value. Returning `None` upholds fail-loudly and never fabricates a rate. Free cash flow and
FCF per share can be negative in weak years, so these guards matter in practice; revenue and diluted
shares are positive and pass through normally.

**Alternatives considered**:

* Taking the magnitude or clamping the ratio would invent a rate for a sign change.
* Returning a large sentinel would be mistaken for a real value.

## Deterministic period selection

**Decision**: A period is identified by its number of fiscal-year intervals, `period_years` (the
years of compounding), so an N-year CAGR spans `FY(end - N)` through `FY(end)`. The end fiscal year is
the latest fiscal year present in both the owner-economics and capital-efficiency series. The recent
view is a true 3-year CAGR (`period_years = 3`, start `end - 3`) and requires that start fiscal year to
be present; otherwise it is an explicit insufficient-history result. The long view uses the longest
CAGR the history supports, capped at a 5-year CAGR: `period_years = min(5, available_intervals)`, where
`available_intervals` is the count of canonical fiscal years minus one. With five observations that is
a 4-year CAGR, and it becomes a 5-year CAGR once a sixth year exists. `years` always equals
`end - start`, which equals `period_years`. Selection is a pure function of the sorted canonical fiscal
years and never assumes a fixed history length.

**Rationale**: Naming a period by its interval count keeps the CAGR label mathematically honest: a
3-year CAGR compounds over three intervals (FY(end-3) through FY(end)), not over three observations.
Anchoring on canonical fiscal years and computing intervals from the labels keeps selection
deterministic and reproducible. Capping the long view at a 5-year CAGR while using the longest
available lets a short history still produce a view, while the 3-year view is reported as
the longest run.

**Alternatives considered**:

* Assuming a fixed five-observation history would break on shorter histories.
* Selecting by array position rather than fiscal-year label would misbehave if a year were missing.

## First-pass thresholds

**Decision**: Centralize named thresholds in one immutable `CompoundingThresholds` value with a
module-level default. Initial first-pass values, chosen to be economically intuitive and deliberately
imprecise:

| Name                          | Value | Applies to                                                       |
|-------------------------------|-------|------------------------------------------------------------------|
| `strong_fcf_per_share_cagr`   | 0.15  | Strong per-share compounding (FCF/share CAGR at or above 15%).    |
| `healthy_fcf_per_share_cagr`  | 0.07  | Healthy per-share compounding (FCF/share CAGR at or above 7%).    |
| `flat_cagr_band`              | 0.02  | Roughly flat compounding (absolute FCF/share CAGR below 2%).      |
| `material_fcf_cagr`           | 0.05  | Material aggregate free-cash-flow decline or growth (±5%).        |
| `material_margin_change`      | 0.02  | Meaningful multi-year margin expansion or contraction (±2 pp).    |
| `material_roic_change`        | 0.03  | Meaningful multi-year ROIC improvement or deterioration (±3 pp).  |
| `material_share_cagr`         | 0.01  | Meaningful dilution or share shrinkage (share-count CAGR ±1%).    |
| `high_roic_level`             | 0.20  | Sustained high ROIC (end-of-period ROIC at or above 20%).        |

**Rationale**: Fifteen percent sustained per-share compounding is genuinely strong for a mature
operating company; seven percent is healthy and clears inflation and modest real growth; two percent
brackets noise. Five percent marks a material multi-year change in aggregate free cash flow. Two and
three percentage points mark real multi-year margin and ROIC moves (wider than the annual thresholds
because a multi-year drift accumulates). One percent annual share-count change distinguishes genuine
buyback or dilution from rounding. Twenty percent ROIC marks a high-return business. The values are
round, inspectable in one place, avoid false precision, plausible for conventional companies, and not
tuned to make Adobe look favorable.

**Alternatives considered**:

* Reusing the tighter annual Feature 2A thresholds would over-trigger on multi-year drift.
* Company-specific thresholds tuned to Adobe would overfit and were rejected.
* Configurable weights were explicitly excluded.

## Driver (reason-code) vocabulary

**Decision**: Each period-level signal maps to a direction using the thresholds, and each non-neutral
direction emits a named driver in a fixed priority order (per-share compounding, aggregate-versus-per-
share, capital efficiency, margins, share count, balance sheet, annual consistency). Initial reason
codes:

| Signal / condition                                       | Driver                              |
|----------------------------------------------------------|-------------------------------------|
| FCF/share CAGR at or above strong                        | `STRONG_FCF_PER_SHARE_COMPOUNDING`  |
| FCF/share CAGR at or above healthy                       | `MODERATE_FCF_PER_SHARE_COMPOUNDING`|
| FCF/share CAGR positive but below healthy                | `WEAK_FCF_PER_SHARE_COMPOUNDING`    |
| FCF/share CAGR materially negative                       | `FCF_PER_SHARE_DECLINED`            |
| Aggregate FCF CAGR materially positive                   | `AGGREGATE_FCF_GREW`                |
| Aggregate FCF CAGR materially negative                   | `AGGREGATE_FCF_DECLINED`            |
| Diluted-share CAGR materially negative (shrinkage)       | `SHARE_COUNT_SHRANK`                |
| Diluted-share CAGR materially positive (dilution)        | `MATERIAL_DILUTION`                 |
| End ROIC at or above high level                          | `ROIC_HIGH_AND_SUSTAINED`           |
| ROIC change materially positive                          | `ROIC_IMPROVED`                     |
| ROIC change materially negative                          | `ROIC_DETERIORATED`                 |
| Operating-margin change materially positive              | `OPERATING_MARGIN_EXPANDED`         |
| Operating-margin change materially negative              | `OPERATING_MARGIN_CONTRACTED`       |
| FCF-margin change materially positive                    | `FCF_MARGIN_EXPANDED`               |
| FCF-margin change materially negative                    | `FCF_MARGIN_CONTRACTED`             |
| Net cash or net debt improved across the period          | `BALANCE_SHEET_IMPROVED`            |
| Net cash or net debt deteriorated across the period      | `BALANCE_SHEET_DETERIORATED`        |
| All annual snapshots in the period classified improving  | `CONSISTENT_ANNUAL_IMPROVEMENT`     |
| Mixed annual classifications in the period               | `MIXED_ANNUAL_ECONOMICS`            |
| Required CAGR endpoints or history unavailable           | `INSUFFICIENT_MULTI_YEAR_HISTORY`   |

**Rationale**: Named codes make each classification transparent and testable; a fixed emission order
guarantees identical ordered drivers for identical inputs. Exact names may evolve while behavior stays
deterministic.

**Alternatives considered**: Free-text explanations would not be testable; an opaque score would
violate the transparency requirement.

## Deterministic compounding classification

**Decision**: Classify with an explicit, documented, priority-ordered rule (small composable functions,
no numeric composite score, never an average of annual verdicts):

1. **Insufficiency gate**: If FCF/share CAGR is unavailable (missing endpoints or insufficient
   history), return `INSUFFICIENT_DATA` with `INSUFFICIENT_MULTI_YEAR_HISTORY`.
2. **Primary per-share base** from FCF/share CAGR:
   * at or above `strong_fcf_per_share_cagr` → base `STRONGLY_COMPOUNDING`
   * at or above `healthy_fcf_per_share_cagr` → base `COMPOUNDING`
   * absolute value below `flat_cagr_band` → base `STABLE`
   * at or below `-flat_cagr_band` → base `DETERIORATING`
   * otherwise (small positive, below healthy) → base `COMPOUNDING` (weak) with
     `WEAK_FCF_PER_SHARE_COMPOUNDING`
3. **Tempering on a compounding base** (ordered notch downgrades along
   STRONGLY_COMPOUNDING > COMPOUNDING > STABLE > DETERIORATING):
   * Share-count-driven illusion: aggregate FCF CAGR at or below `-material_fcf_cagr` while diluted-
     share CAGR at or below `-material_share_cagr` (per-share boosted by shrinkage while aggregate
     falls) downgrades one notch and emits `AGGREGATE_FCF_DECLINED` and `SHARE_COUNT_SHRANK`.
   * Material dilution: diluted-share CAGR at or above `material_share_cagr` downgrades one notch and
     emits `MATERIAL_DILUTION`.
   * ROIC deterioration: ROIC change at or below `-material_roic_change` downgrades one notch and emits
     `ROIC_DETERIORATED`.
   The downgrade is clamped so a compounding base never falls below `STABLE` on tempering alone.
4. **Confirm a deteriorating base**: A `DETERIORATING` base stays deteriorating; falling FCF/share CAGR
   with ROIC deterioration is the canonical deteriorating case. It may rise to `STABLE` only when the
   per-share decline is marginal (magnitude below `2 × flat_cagr_band`) and ROIC improved materially
   and both margins expanded.
5. **Resolve a stable base** by corroborating secondary signals among ROIC change, operating-margin
   change, FCF-margin change, share-count CAGR, and balance-sheet direction: at least two net-positive
   and none of the tempering deteriorations present → `COMPOUNDING`; at least two net-negative or a
   deteriorating annual majority → `DETERIORATING`; otherwise `STABLE`.

Annual-classification counts always emit `CONSISTENT_ANNUAL_IMPROVEMENT` or `MIXED_ANNUAL_ECONOMICS`
as context; they inform the stable-base tie-break but never override the per-share-driven verdict, so
the multi-year classification is not an average of the annual verdicts.

**Rationale**: The rule weights per-share compounding first (steps 1-2), surfaces and tempers the
share-count-driven illusion, material dilution, and ROIC deterioration (step 3), confirms the
canonical deteriorating case (step 4), and resolves flat periods by corroboration (step 5). It is
economically intuitive, transferable to another conventional operating company, and fully determined
by the inputs and named thresholds.

**Alternatives considered**:

* Averaging annual Feature 2A classifications would hide the period economics and is explicitly
  forbidden.
* A weighted score across all signals would be an opaque composite the spec forbids.
* A rules-engine or analytics framework was rejected as over-engineering.

## Orchestration and the two standard periods

**Decision**: `compounding_view_from_facts` calls the existing `owner_economics_from_facts`,
`capital_efficiency_from_facts`, and `economic_value_from_facts` (default `max_years=5`), then builds a
view for a requested target span. `compounding_views_from_facts` returns the recent three-year and the
longest five-year views. `build_compounding_view` accepts already-computed Feature 1 rows and Feature
2A snapshots for offline, deterministic testing.

**Rationale**: Delegating retrieval and normalization to Feature 1 and Feature 2A keeps all network
access outside the compounding layer and keeps the layer independently testable with constructed
inputs.

**Alternatives considered**: Fetching inside the compounding layer would violate the layer boundary
and the no-SEC-calls constraint.

## Test strategy

**Decision**: Add `test_compounding.py` using in-memory `OwnerEconomicsRow`, `CapitalEfficiencyRow`,
and `EconomicValueSnapshot` fixtures constructed directly. Cover the CAGR mechanics (correct interval
count, positive growth, flat series, decline, missing endpoints, zero beginning, negative and
sign-changing values); the compounding interpretation (strongly compounding, moderate, stable,
deteriorating, share-count-driven per-share with falling aggregate FCF, aggregate growth with material
dilution, strong growth with ROIC deterioration, strong per-share with sustained high ROIC,
deteriorating balance sheet, mixed annual classifications, insufficient history); deterministic period
selection; and deterministic, order-stable driver generation. Keep all existing Slice 1A-1E and Slice
2A tests.

**Rationale**: Constructed fixtures make every CAGR case, classification branch, guardrail, period, and
insufficiency path reproducible and deterministic without any network or SEC payloads, and repeated
runs assert identical classifications and ordered drivers.

**Alternatives considered**: Live-only validation is nondeterministic and cannot reliably reproduce the
invalid-CAGR, guardrail, and insufficient-history cases.

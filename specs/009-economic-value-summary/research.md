---
title: Company-Level Economic Value Summary Research
description: Component inputs, the ordinal synthesis hierarchy, watch-versus-guardrail thresholds, tension handling, and driver mapping
ms.date: 2026-09-02
ms.topic: reference
---

## Inputs consumed from Feature 2

The synthesis layer consumes three existing outputs and adds no new data.

`EconomicValueSnapshot` (`owner_lens.economic_value`), latest fiscal year: `classification`
(IMPROVING / STABLE / DETERIORATING / INSUFFICIENT_DATA), `fcf_per_share_growth`, `roic`, `roic_change`,
`net_cash_or_debt`, and `drivers`.

`EconomicCompoundingView` (`owner_lens.compounding`), the recent and long-term views from
`compounding_views_from_facts`: `classification` (STRONGLY_COMPOUNDING / COMPOUNDING / STABLE /
DETERIORATING / INSUFFICIENT_DATA), `fcf_per_share_cagr`, `diluted_share_cagr`, `roic_end`,
`roic_change`, `net_cash_or_debt_end`, and `drivers`.

`CapitalAllocationRow` (`owner_lens.capital_allocation`), latest fiscal year: `classification`
(OWNER_FRIENDLY / BALANCED / QUESTIONABLE / OWNER_UNFRIENDLY / INSUFFICIENT_DATA),
`buyback_effectiveness`, `sbc_over_fcf`, `capital_returned_over_fcf`, `net_cash_or_debt`, `roic`, and
`drivers`.

**Decision**: The layer reads these objects and never re-derives a metric or reimplements component
logic. The compact evidence set is a selection of existing values, not a recomputation.

**Rationale**: Every value is already verified and classified; composing them respects the layer
boundary and keeps the capstone thin.

**Alternatives considered**: Recomputing evidence from Feature 1 rows would duplicate calculations and
blur the boundary.

## Ordinal scale and overall classification

**Decision**: Map the overall verdict to a small integer scale and back:
`STRONGLY_IMPROVING = +2`, `IMPROVING = +1`, `STABLE = 0`, `DETERIORATING = -1`,
`STRONGLY_DETERIORATING = -2`, with `INSUFFICIENT_DATA` handled separately. The final score is clamped
to `[-2, +2]` and converted to the enum.

**Rationale**: A coarse ordinal scale makes a documented hierarchy expressible as explicit
confirm/dampen/guardrail steps without any weighted average or hidden points, and the coarseness avoids
false precision.

**Alternatives considered**: A continuous score would be a numeric composite the spec forbids; a direct
mapping of one component would ignore the others.

## Documented priority hierarchy

**Decision**: Compute the overall classification with this explicit, ordered rule:

1. **Insufficiency gate**: If the long-term compounding classification is insufficient-data and the
   latest annual classification is insufficient-data, return `INSUFFICIENT_DATA`.
2. **Long-term compounding base** (the anchor and positive ceiling):
   * `STRONGLY_COMPOUNDING` → base `+2`
   * `COMPOUNDING` → base `+1`
   * `STABLE` → base `0`
   * `DETERIORATING` → base `-1`
   * `INSUFFICIENT_DATA` → fall back to the latest annual base (IMPROVING `+1`, STABLE `0`,
     DETERIORATING `-1`) and mark the verdict as not-yet-established.
3. **Latest-year adjustment** (durable-first, bounded to one notch, never flips a strong base):
   * base `>= +1` and latest annual `DETERIORATING` → dampen one notch (`score = base - 1`) and emit
     `RECENT_SLOWDOWN`.
   * base `<= -1` and latest annual `IMPROVING` → temper one notch toward stable (`score = base + 1`)
     and emit `EARLY_IMPROVEMENT_NOT_YET_PROVEN`.
   * base and latest annual agree in sign → confirm (score stays at base); a `+2` base with improving
     latest stays `+2`.
   * otherwise → score stays at base.
   The positive result never exceeds the long-term base, so `STRONGLY_IMPROVING` requires long-term
   `STRONGLY_COMPOUNDING`.
4. **Capital-allocation modifier** (bounded, never lifts above the base):
   * `OWNER_UNFRIENDLY` → `score = score - 1`.
   * `QUESTIONABLE` → dampen one notch only if the score is currently positive (`score = min(score,
     base) - 1` clamped at `0`); otherwise it is a watch driver.
   * `OWNER_FRIENDLY` or `BALANCED` → confirm (no lift above the base).
5. **Severe guardrails** (force the score down, applied last):
   * Sustained ROIC collapse: long-term `roic_change <= -severe_roic_collapse` → `score = min(score, -1)`;
     if the score is already negative, `score = -2`. Emit `ROIC_DETERIORATING` as a guardrail.
   * Deepening or persistent net debt: latest `net_cash_or_debt < 0` and a component leverage-
     deterioration driver is present → `score = min(score, -1)`. Emit `WORSENING_NET_DEBT`.
6. **Watch drivers**: surface the remaining economically relevant signals without changing the score.

Convert the clamped score to the overall enum.

**Rationale**: The hierarchy prefers durable multi-year compounding (step 2 anchors the ceiling), lets
the latest year reconcile tension without dominating (step 3), applies capital-allocation quality as a
bounded modifier (step 4), and reserves score-changing power for genuinely severe deterioration (step
5), while everything else is transparent context (step 6). Applied to Adobe (long-term `COMPOUNDING`,
latest annual `IMPROVING`, `OWNER_FRIENDLY` capital allocation, ROIC high and improving, still net-cash
positive), the base is `+1`, latest confirms, no guardrail fires, and the overall is `IMPROVING` with
watch drivers, matching the intended owner reading.

**Alternatives considered**: Averaging the three component classifications would let one strong year or
one weak component dominate and hide the reasoning; a weighted score is explicitly forbidden.

## Watch signals versus verdict-changing guardrails

**Decision**: Classify each warning explicitly.

| Signal                                   | Treatment  | Condition                                                     |
|------------------------------------------|------------|--------------------------------------------------------------|
| High SBC burden                          | Watch      | SBC / FCF high while the diluted share count is still shrinking |
| Capital returns above free cash flow     | Watch      | Capital returned / FCF at or above 1 while net-cash positive  |
| Declining net-cash cushion               | Watch      | Net cash fell materially but remains positive                 |
| Buybacks partly offset by dilution       | Watch      | Capital-allocation buyback effectiveness is partially offset  |
| Mixed recent economics                   | Watch      | Recent and long-term compounding disagree                     |
| Deepening or persistent net debt         | Guardrail  | Net debt position with a component deterioration driver       |
| Sustained ROIC collapse                  | Guardrail  | Long-term ROIC change at or below `severe_roic_collapse`      |
| Owner-unfriendly capital allocation      | Modifier   | Capital-allocation classification is owner-unfriendly         |

Watch signals become drivers only; guardrails downgrade the score.

**Rationale**: A high SBC burden or returns above free cash flow are real but not thesis-breaking while
shares still shrink and the company stays net-cash positive, so the summary should not overreact. A turn
to net debt with worsening leverage, or a sustained ROIC collapse, genuinely changes the owner picture.

**Alternatives considered**: Treating every warning as verdict-changing would make the summary volatile
and pessimistic; ignoring severe signals would make it complacent.

## First-pass thresholds

**Decision**: Centralize the few synthesis-specific thresholds in one immutable
`EconomicSummaryThresholds` value with a module-level default. Most severity reuses component drivers
directly for traceability.

| Name                    | Value | Concept                                                  |
|-------------------------|-------|----------------------------------------------------------|
| `severe_roic_collapse`  | 0.10  | Sustained ROIC collapse guardrail (long-term ROIC change ≤ −10 pp) |
| `high_roic_level`       | 0.20  | High ROIC evidence and driver (ROIC ≥ 20%)              |

Watch and negative drivers are otherwise derived from the presence of the corresponding Feature 2
component drivers, so the synthesis inherits the already-documented component thresholds rather than
introducing new ones.

**Rationale**: Ten percentage points of long-term ROIC decline is a genuine collapse for a high-return
business; twenty percent marks a high-return business, consistent with Feature 2A, 2B, and 2C. Reusing
component drivers keeps thresholds centralized where they were first defined and keeps the capstone
traceable.

**Alternatives considered**: Re-deriving every threshold here would duplicate the component definitions
and risk drift; company-specific tuning would overfit.

## Recent-versus-long-term tension

**Decision**: Reconcile disagreement explicitly. Long-term strong with a weak latest year emits
`RECENT_SLOWDOWN` and dampens one notch. Long-term weak with a strong latest year emits
`EARLY_IMPROVEMENT_NOT_YET_PROVEN` and tempers toward stable without declaring improvement. Recent and
long-term agreement reinforces the verdict. When the recent compounding view is unavailable (short
history), it is omitted from the summary and the long-term view alone anchors the base.

**Rationale**: A company-level view must distinguish an established compounding history from a trend
change; surfacing the tension as a driver is more honest than collapsing it into a single verdict.

**Alternatives considered**: Letting the latest year flip a durable long-term base would overreact to
noise.

## Driver synthesis and deduplication

**Decision**: Collect signals from the component classifications and drivers, map them into ordered
positive, watch, and negative categories, and deduplicate so each summary driver appears once even when
several component layers emit related signals. Ordering within each category follows a fixed priority
(per-share compounding, ROIC, share count and buybacks, capital allocation, margins, balance sheet, then
tension). Representative mapping:

* Positive: `PER_SHARE_CASH_FLOW_COMPOUNDING`, `FCF_PER_SHARE_ACCELERATING`, `HIGH_ROIC`,
  `ROIC_IMPROVING`, `SHARE_COUNT_SHRINKING`, `EFFECTIVE_BUYBACKS`, `OWNER_FRIENDLY_CAPITAL_ALLOCATION`,
  `HEALTHY_BALANCE_SHEET`, `MARGINS_EXPANDING`.
* Watch: `HIGH_SBC_BURDEN`, `CAPITAL_RETURNS_EXCEED_FCF`, `DECLINING_NET_CASH_CUSHION`,
  `BUYBACKS_PARTLY_OFFSET_BY_DILUTION`, `MIXED_RECENT_ECONOMICS`, `RECENT_SLOWDOWN`,
  `EARLY_IMPROVEMENT_NOT_YET_PROVEN`.
* Negative: `FCF_PER_SHARE_DECLINING`, `MATERIAL_DILUTION`, `ROIC_DETERIORATING`,
  `OWNER_UNFRIENDLY_CAPITAL_ALLOCATION`, `WORSENING_NET_DEBT`, `MARGINS_CONTRACTING`,
  `AGGREGATE_FCF_DECLINING`.

**Rationale**: Named, ordered, deduplicated, traceable drivers make the verdict inspectable and prevent
free-form prose from becoming the source of truth. Exact code names may evolve while behavior stays
deterministic.

**Alternatives considered**: Emitting every component driver verbatim would be noisy and would double
count related signals.

## Evidence set

**Decision**: Carry a compact evidence set drawn from existing outputs: `latest_fcf_per_share_growth`
(latest snapshot), `long_term_fcf_per_share_cagr` and `recent_fcf_per_share_cagr` (compounding views),
`diluted_share_cagr` (long-term view), `latest_roic` (latest snapshot or long-term `roic_end`),
`long_term_roic_change` (long-term view), `latest_net_cash_or_debt` (latest capital-allocation row),
`latest_sbc_to_fcf` and `latest_capital_returned_to_fcf` (latest capital-allocation row), and the latest
`buyback_effectiveness`.

**Rationale**: A small headline set supports the verdict without duplicating every underlying metric,
keeping the summary compact and owner-readable.

**Alternatives considered**: Carrying every component field would defeat the point of a summary.

## Orchestration

**Decision**: `synthesize_economic_value_summary(ticker, snapshots, recent_view, long_term_view,
capital_rows, *, thresholds)` accepts already-computed component objects for offline, deterministic
testing. `economic_value_summary_from_facts(raw_facts, *, ticker, max_years, thresholds)` calls the
existing `economic_value_from_facts`, `compounding_views_from_facts`, and `capital_allocation_from_facts`
on the already-retrieved payload, then synthesizes. `format_economic_value_summary` renders the compact
owner-readable lens.

**Rationale**: Delegating to the component entry points keeps all network access and computation outside
the synthesis layer and keeps it independently testable with constructed objects.

**Alternatives considered**: Fetching or recomputing inside the synthesis layer would violate the layer
boundary.

## Test strategy

**Decision**: Add `test_economic_summary.py` using constructed component objects. Cover the hierarchy
(strong/strong/owner-friendly, strong long-term with weak latest, weak long-term with improving latest,
stable across all, deteriorating across all), owner-unfriendly tempering, high SBC with effective
buybacks, capital returns above free cash flow while healthy, worsening net debt guardrail, high ROIC
protecting against one weak year, collapsing ROIC guardrail, and insufficient component data; plus
ordered positive/watch/negative driver generation, deduplication, watch-versus-guardrail distinction,
and determinism. Keep all existing tests.

**Rationale**: Constructed component fixtures make every hierarchy branch, tension case, watch/guardrail
distinction, and dedup reproducible and deterministic without network access.

**Alternatives considered**: Live-only validation is nondeterministic and cannot reproduce the crafted
tension and guardrail cases.

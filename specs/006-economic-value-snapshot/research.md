---
title: Annual Economic Value Snapshot Research
description: Signals, first-pass thresholds, driver codes, and the deterministic classification rule for the owner-economics lens
ms.date: 2026-09-01
ms.topic: reference
---

## Inputs already available from Feature 1

The interpretation layer consumes two aligned Feature 1 row types and adds no external data.

`OwnerEconomicsRow` (`owner_lens.owner_economics`) supplies, per fiscal year: `operating_margin`,
`net_margin`, `free_cash_flow`, `fcf_margin`, `fcf_per_share`, `fcf_growth`, `fcf_per_share_growth`,
`diluted_share_growth`, plus the reported observations (revenue, operating income, net income,
operating cash flow, CapEx, diluted shares).

`CapitalEfficiencyRow` (`owner_lens.capital_efficiency`) supplies, per fiscal year: `roic`, `net_cash`
(net cash or net debt), and the other capital-structure facts and metrics.

**Decision**: Feature 2A reads these rows as-is and never re-normalizes SEC facts. Four CHANGE signals
the snapshot needs are not already exposed by Feature 1 rows and are derived here as simple
adjacent-year deltas of Feature 1 LEVEL values: `revenue_growth` (from adjacent revenue observations),
`operating_margin_change` (adjacent `operating_margin`), `fcf_margin_change` (adjacent `fcf_margin`),
and `roic_change` (adjacent `roic`).

**Rationale**: Deriving an adjacent-year delta of an already-trusted Feature 1 metric is interpretation
over existing outputs, not a new normalization of SEC facts, so it respects the layer boundary while
avoiding a change to Feature 1 modules. Growth-type deltas already present in Feature 1
(`fcf_growth`, `fcf_per_share_growth`, `diluted_share_growth`) are reused directly rather than
recomputed.

**Alternatives considered**:

* Extending `OwnerEconomicsRow`/`CapitalEfficiencyRow` with the four extra deltas would edit Feature 1
  modules for a Feature 2 concern and blur the layer boundary.
* Recomputing every change from raw facts would duplicate normalization and violate the boundary.

## Snapshot shape: LEVEL versus CHANGE

**Decision**: `EconomicValueSnapshot` stores LEVEL signals (`operating_margin`, `fcf_margin`, `roic`,
`net_cash_or_debt`) and CHANGE signals (`revenue_growth`, `operating_margin_change`, `fcf_growth`,
`fcf_margin_change`, `diluted_share_growth`, `fcf_per_share_growth`, `roic_change`) as separate named
fields, alongside `fcf_per_share` (a per-share level), `fiscal_year`, `classification`, and `drivers`.
No field blends a level with a change.

**Rationale**: The spec forbids collapsing levels and changes into one generic number. Distinct named
fields make each signal independently inspectable and testable and keep the classification rule
readable.

**Alternatives considered**: A single composite "economic value" number was explicitly excluded by the
spec (no 0-to-100 score).

## Missing-data and earliest-year behavior

**Decision**: Every CHANGE signal is `None` when its prior-year input is unavailable. The layer aligns
exactly the Feature 1 rows returned for the display window (default five years), so the earliest
displayed year has no in-window prior and therefore has `None` for all adjacent-year change signals.
Zero is never substituted for a missing change. The minimum information required to classify is a
present `fcf_per_share_growth` (the primary per-share signal); when it is `None`, the year is
`INSUFFICIENT_DATA`.

**Rationale**: Per-share economics is the primary lens, so a year whose per-share change cannot be
computed cannot be judged and must be `INSUFFICIENT_DATA`. Tying insufficiency to the primary signal
makes the earliest displayed year naturally `INSUFFICIENT_DATA`, which is the intended teaching point,
without over-fetching an extra display year. Explicit `None` preserves the fail-loudly principle.

**Alternatives considered**:

* Fetching one extra year so the earliest displayed year gets real changes would remove the intended
  `INSUFFICIENT_DATA` demonstration and still leave a new earliest year unclassifiable.
* Substituting zero for a missing change would fabricate a movement and is explicitly forbidden.

## First-pass thresholds

**Decision**: Centralize named thresholds in one immutable `EconomicValueThresholds` value with a
module-level default. Initial first-pass values, chosen to be economically intuitive and deliberately
imprecise:

| Name                       | Value | Applies to                                                        |
|----------------------------|-------|-------------------------------------------------------------------|
| `material_growth`          | 0.05  | Growth-type change signals: revenue growth, FCF growth, FCF/share growth. A move of at least ±5% is material; within (−5%, +5%) is roughly stable. |
| `material_margin_change`   | 0.01  | Operating-margin and FCF-margin change (levels in [0,1]); ±1 percentage point is expansion/contraction. |
| `material_roic_change`     | 0.02  | ROIC change; ±2 percentage points is improvement/deterioration.   |
| `severe_roic_change`       | 0.05  | ROIC change guardrail; a drop of at least 5 percentage points is severe deterioration. |
| `material_share_change`    | 0.01  | Diluted-share-count change; ±1% is material dilution or buyback.   |
| `high_roic_level`          | 0.20  | Sustained-high-ROIC level driver; ROIC at or above 20%.           |

**Rationale**: Five percent separates ordinary noise from a move an owner would notice in annual free
cash flow per share. One percentage point is a meaningful annual margin move for a large software
company without being hair-trigger. Two percentage points marks a real capital-efficiency shift, and
five marks a severe one that should temper an otherwise positive year. One percent share-count movement
distinguishes genuine buyback or dilution from rounding. Twenty percent ROIC is a conventional marker
of a high-return business. The values are round and easy to inspect and change, avoid false precision,
and are not tuned to make Adobe look favorable.

**Alternatives considered**:

* Tighter thresholds (for example ±1% growth) would classify noise as signal.
* Per-signal bespoke thresholds tuned to Adobe's history would overfit and were rejected.
* Configurable scoring weights were explicitly excluded for this slice.

## Signal directions and driver (reason-code) vocabulary

**Decision**: Each available signal maps to a direction (positive for owners, negative for owners, or
neutral) using the thresholds above, and each non-neutral direction emits a named driver. Share-count
*decline* is positive and share-count *growth* (dilution) is negative. Initial reason codes:

| Signal / condition                                  | Positive driver              | Negative driver                    |
|-----------------------------------------------------|------------------------------|------------------------------------|
| FCF per share growth                                | `FCF_PER_SHARE_STRONG_GROWTH`| `FCF_PER_SHARE_DECLINE`            |
| Diluted share count change                          | `SHARE_COUNT_DECLINED`       | `SHARE_COUNT_INCREASED`           |
| ROIC change                                         | `ROIC_EXPANDED`              | `ROIC_CONTRACTED`                 |
| ROIC level (sustained high)                         | `ROIC_SUSTAINED_HIGH`        | —                                  |
| Operating-margin change                             | `OPERATING_MARGIN_EXPANDED`  | `OPERATING_MARGIN_CONTRACTED`     |
| FCF-margin change                                   | `FCF_MARGIN_EXPANDED`        | `FCF_MARGIN_CONTRACTED`           |
| Revenue growth                                      | `REVENUE_MATERIAL_GROWTH`    | `REVENUE_DECLINE`                 |
| Aggregate FCF growth                                | `FCF_MATERIAL_GROWTH`        | `FCF_DECLINE`                     |
| Net cash / net debt direction                       | `NET_CASH_IMPROVED`          | `NET_CASH_DETERIORATED`           |
| Net position sign flip                              | `TURNED_TO_NET_CASH`         | `TURNED_TO_NET_DEBT`              |
| Guardrail: strong per-share growth amid ROIC drop   | —                            | `PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION` |
| Guardrail: strong per-share growth amid leverage up | —                            | `PER_SHARE_GROWTH_OFFSET_BY_LEVERAGE_DETERIORATION` |
| Mixed: per-share decline offset by strong quality   | `PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY` | —                  |
| Insufficient comparison data                        | —                            | `INSUFFICIENT_PRIOR_YEAR_DATA`    |

Drivers are emitted in a fixed priority order (per-share first, then capital efficiency, then margins,
then share count and balance sheet, then aggregate revenue and FCF) so the ordered driver list is
deterministic.

**Rationale**: Named codes make each classification transparent and testable, and the exact-name
requirement in the spec allows this vocabulary to evolve as long as behavior stays deterministic. A
fixed emission order guarantees identical ordered drivers for identical inputs.

**Alternatives considered**: Free-text explanations would not be testable; an opaque numeric score
would violate the transparency requirement.

## Net cash / net debt direction

**Decision**: Compare current `net_cash_or_debt` with the prior year's. A sign flip from non-negative
to negative is deterioration (`TURNED_TO_NET_DEBT`); a flip from negative to non-negative is improvement
(`TURNED_TO_NET_CASH`). Without a sign flip, direction is material when the change exceeds
`material_growth` of the prior absolute magnitude, emitting `NET_CASH_DETERIORATED` or
`NET_CASH_IMPROVED`. When the prior year's value is unavailable, the direction is neutral and no
balance-sheet driver is emitted. For the leverage guardrail, "material leverage deterioration" means a
`TURNED_TO_NET_DEBT` sign flip or a material deepening of an existing net-debt position.

**Rationale**: A sign flip between net cash and net debt is the clearest, most economically intuitive
balance-sheet change and needs no arbitrary dollar threshold. Reusing `material_growth` for magnitude
changes avoids a new bespoke number while still avoiding false precision.

**Alternatives considered**: A fixed dollar threshold would not transfer across companies; ignoring the
balance sheet would miss the required guardrail.

## Deterministic classification rule

**Decision**: Classify with an explicit, documented, priority-ordered rule (small composable functions,
no numeric composite score):

1. **Insufficiency gate**: If `fcf_per_share_growth` is unavailable, return `INSUFFICIENT_DATA` with
   `INSUFFICIENT_PRIOR_YEAR_DATA`.
2. **Primary per-share verdict** from `fcf_per_share_growth`:
   * at least `+material_growth` → base `IMPROVING`
   * at most `−material_growth` → base `DETERIORATING`
   * otherwise → base `STABLE`
3. **Guardrails on an IMPROVING base** (per-share economics cannot alone declare improvement amid
   material deterioration):
   * If ROIC deteriorated at least `severe_roic_change`, or leverage deteriorated materially
     (`TURNED_TO_NET_DEBT` or material net-debt deepening): downgrade. Downgrade to `DETERIORATING`
     when both guardrails fire or ROIC deterioration is severe on its own; otherwise downgrade to
     `STABLE`. Emit the corresponding offset driver.
   * If ROIC contracted at the ordinary `material_roic_change` level (but not severe), downgrade
     `IMPROVING` to `STABLE` and emit `ROIC_CONTRACTED` plus
     `PER_SHARE_GROWTH_OFFSET_BY_ROIC_DETERIORATION`.
4. **Temper a DETERIORATING base**: If per-share decline is only marginal (magnitude below
   `2 × material_growth`) while ROIC expanded at least `material_roic_change` and both margins expanded,
   raise to `STABLE` and emit `PER_SHARE_DECLINE_OFFSET_BY_STRONG_QUALITY`.
5. **Resolve a STABLE base** by a documented count of corroborating secondary signals among ROIC
   change, operating-margin change, FCF-margin change, share-count change, and net-cash direction:
   * at least two net-positive and no material guardrail deterioration → `IMPROVING`
   * at least two net-negative → `DETERIORATING`
   * otherwise → `STABLE`

The small count in step 5 is a documented tie-break within the neutral per-share branch, not a global
opaque score, and every contributing signal is emitted as a driver.

**Rationale**: The rule weights per-share economics first (steps 1-2), honors the required guardrails so
strong FCF/share growth with collapsing ROIC or worsening leverage does not auto-classify as improving
(step 3), handles the symmetric mixed case (step 4), and resolves genuinely flat years by corroborating
quality signals (step 5). It is economically intuitive, transferable to another conventional operating
company, and fully determined by the inputs and named thresholds.

**Alternatives considered**:

* A single weighted score across all signals would be an opaque numeric composite the spec forbids and
  would hide why a year was classified.
* A pure FCF/share rule with no guardrails would mis-classify buyback-driven years with deteriorating
  returns as improving, which the spec explicitly warns against.
* A rules-engine framework was rejected as over-engineering for this slice.

## Orchestration and display window

**Decision**: `economic_value_from_facts` calls the existing `owner_economics_from_facts` and
`capital_efficiency_from_facts` (default `max_years=5`), aligns the returned rows by fiscal year, derives
the four adjacent-year changes within that window, builds one `EconomicValueSnapshot` per year, and
returns them newest first. `build_economic_value_snapshots` accepts already-computed
`OwnerEconomicsRow` and `CapitalEfficiencyRow` sequences for offline, deterministic testing.

**Rationale**: Delegating retrieval and normalization to Feature 1 keeps all network access outside the
interpretation layer and keeps the layer independently testable with constructed rows.

**Alternatives considered**: Fetching inside the interpretation layer would violate the layer boundary
and the no-SEC-calls constraint.

## Test strategy

**Decision**: Add `test_economic_value.py` using in-memory `OwnerEconomicsRow` and `CapitalEfficiencyRow`
fixtures constructed directly. Cover: clearly improving, clearly deteriorating, and stable years; the
earliest-year and missing-individual-metric `INSUFFICIENT_DATA` paths; FCF/share growth boosted by share
shrinkage; aggregate FCF growth with per-share deterioration; strong growth with material and severe
ROIC deterioration (guardrails); operating-margin and FCF-margin expansion and contraction; net-cash
sign-flip deterioration and improvement; threshold-boundary values just inside and just outside each
cutoff; and deterministic, order-stable driver generation. Keep all existing Slice 1A-1E tests.

**Rationale**: Constructed row fixtures make every classification branch, guardrail, boundary, and
insufficiency path reproducible and deterministic without any network or SEC payloads, and repeated runs
assert identical classifications and ordered drivers.

**Alternatives considered**: Live-only validation is nondeterministic and cannot reliably reproduce
guardrail, boundary, and insufficiency cases.

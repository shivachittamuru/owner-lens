---
title: Capital Allocation Lens Research
description: Verified Adobe concepts, capital-allocation definitions, buyback-effectiveness and classification rules, and first-pass thresholds
ms.date: 2026-09-01
ms.topic: reference
---

## Live-verified Adobe concepts

A live inspection of Adobe's Company Facts (CIK 0000796343) confirmed the concepts and their shapes.
Values below verify coverage and sign only; OwnerLens never hard-codes them.

| Fact           | Concept (preference order)                                                    | Unit  | Coverage (FY2020-2025) | Sign               |
|----------------|-------------------------------------------------------------------------------|-------|------------------------|--------------------|
| Repurchases    | `PaymentsForRepurchaseOfCommonStock`                                          | USD   | Full, all years        | Positive outflow   |
| SBC            | `ShareBasedCompensation`, then `AllocatedShareBasedCompensationExpense`       | USD   | Full, all years        | Positive expense   |
| Dividends paid | `PaymentsOfDividendsCommonStock`, then `PaymentsOfDividends`                  | USD   | **Absent (no concept)**| n/a                |

Verified annual repurchase outflow: FY2020 3,050; FY2021 3,950; FY2022 6,550; FY2023 4,400; FY2024
9,500; FY2025 11,281 (USD millions). Verified SBC: FY2020 909; FY2021 1,069; FY2022 1,440; FY2023
1,718; FY2024 1,833; FY2025 1,942. Both SBC concepts agree except FY2021 (1,069 versus 1,090).

## Repurchase concept and double counting

**Decision**: Use `PaymentsForRepurchaseOfCommonStock` as the single canonical repurchase concept.
Its value is the cash paid for common-share repurchases during the fiscal year, reported as a positive
outflow magnitude. Do not add treasury-stock roll-forward concepts (`TreasuryStockValueAcquiredCostMethod`,
`TreasuryStockValue`) to it.

**Rationale**: The cash-flow-statement repurchase outflow is exactly the canonical OwnerLens meaning
(cash spent buying own shares). The treasury-stock concepts are equity/balance-sheet roll-forwards that
can differ by settlement timing and would double count if summed with the cash outflow. Using one
cash-flow concept avoids double counting and never infers repurchases from share-count or treasury
changes.

**Alternatives considered**:

* Summing cash outflow and treasury-stock acquired would double count.
* Inferring repurchases from the diluted-share-count change is explicitly forbidden and conflates
  issuance with repurchase.

## SBC concept

**Decision**: Prefer `ShareBasedCompensation` (the cash-flow-statement non-cash add-back), falling back
to `AllocatedShareBasedCompensationExpense`. Treat the value as total company stock-based compensation
expense for the fiscal year. Show SBC and SBC over free cash flow as a burden signal; never subtract
SBC from free cash flow.

**Rationale**: `ShareBasedCompensation` is the reconciling total SBC in the cash-flow statement,
consistent with the free-cash-flow context this lens uses, and is present in every year alongside
operating cash flow. It equals `AllocatedShareBasedCompensationExpense` in every verified year except
FY2021 (a ~21 million reclassification), so a documented preference order selects one deterministically.
Keeping conventional free cash flow intact and showing SBC separately avoids silently redefining a
headline metric.

**Alternatives considered**:

* Subtracting SBC from free cash flow would redefine free cash flow and is out of scope.
* Using only the income-statement allocation concept risks a year where it diverges from the cash-flow
  total; the preference order handles that.

## Dividends: structural absence

**Decision**: Normalize dividends with a tolerant normalizer that returns an empty (absent) series when
no dividend concept is present. Adobe reports no `PaymentsOfDividendsCommonStock` or `PaymentsOfDividends`
concept in any filing, so dividends are structurally absent (no dividend program), not merely missing
for one year. Preserve the dividend fact as absent. For the capital-returned and retained-FCF
arithmetic only, treat a confidently-absent dividend concept as zero distributions, and emit a
`NO_DIVIDEND_PROGRAM` driver so the absence is explicit rather than a fabricated zero value.

**Rationale**: The spec requires preserving dividend absence rather than fabricating zero. Because the
concept is absent across every filing, the "no applicable activity" case is reliably distinguishable
from "unavailable," which justifies treating distributions as zero for aggregation while keeping the
reported dividend field absent and surfacing the fact through a driver. A normalizer that raised a
concept-not-found error would force every Adobe year to fail, which is wrong for a company that simply
pays no dividend.

**Alternatives considered**:

* Raising `ConceptNotFoundError` for dividends would break every Adobe year.
* Substituting a zero dividend observation would fabricate a reported value and lose the distinction
  between a paid-zero and a no-program company.

## Missing-data semantics

**Decision**: Distinguish three cases. A reported zero is a present observation with value zero. A
confidently-absent concept (no dividend program) is an absent series treated as zero only for
aggregation, with an explicit driver. Unavailable data (a required input such as free cash flow missing
for a year) omits the dependent ratio and classifies conservatively. Never substitute zero for a
missing repurchase or SBC concept; those are expected to exist and their absence is a normalization
failure surfaced explicitly.

**Rationale**: This honors fail-loudly while still producing a usable view for a no-dividend company.
The only zero-for-absent treatment is the research-confirmed no-dividend-program case, applied to
aggregation and always made explicit by a driver.

**Alternatives considered**: A single blanket zero-substitution rule would violate the spec; a single
blanket raise rule would break the no-dividend company.

## Derived metrics

**Decision**: Per fiscal year, using the reused Feature 1 free cash flow as the base, derive:

| Metric                    | Formula                                              | Omitted when                        |
|---------------------------|------------------------------------------------------|-------------------------------------|
| Repurchases / FCF         | repurchases / free_cash_flow                         | repurchases absent; FCF absent or ≤ 0 |
| Dividends / FCF           | dividends / free_cash_flow                           | dividends absent; FCF absent or ≤ 0 |
| SBC / FCF                 | sbc / free_cash_flow                                 | SBC absent; FCF absent or ≤ 0       |
| Capital returned          | repurchases + dividends (dividends 0 if no program)  | repurchases absent                  |
| Capital returned / FCF    | capital_returned / free_cash_flow                    | capital returned absent; FCF ≤ 0    |
| Retained FCF              | free_cash_flow − repurchases − dividends             | free cash flow or repurchases absent|

Retained FCF may be negative when capital returned exceeds free cash flow; the negative value is
preserved, never clamped to zero. Ratios are omitted rather than computed when free cash flow is absent
or non-positive, to avoid a meaningless or sign-flipping ratio.

**Rationale**: These are the standard capital-allocation ratios expressed against free cash flow, the
cash actually available to return. Retained FCF is an interpretive residual, not a claim of economic
reinvestment; preserving its negative sign shows years where Adobe returned more than it generated
(FY2024 and FY2025 repurchases exceed free cash flow). Guarding non-positive free cash flow keeps
ratios honest.

**Alternatives considered**: Clamping retained FCF at zero would hide over-distribution; using operating
cash flow instead of free cash flow would ignore capital intensity.

## Buyback effectiveness

**Decision**: Interpret buyback effectiveness by comparing repurchase spending against the actual
diluted-share-count change (reused from Feature 1 share-count growth), never inferring share reduction
from spending. Using centralized thresholds:

* meaningful repurchase activity: repurchases / FCF ≥ `meaningful_repurchase_to_fcf` (0.25), or
  repurchases present and positive when the ratio is unavailable;
* share shrank: diluted-share growth ≤ −`material_share_change` (0.01);
* share flat: absolute diluted-share growth < `material_share_change`;
* share rose (dilution): diluted-share growth ≥ `material_share_change`.

| Repurchase activity | Share-count outcome | Effectiveness                    |
|---------------------|---------------------|----------------------------------|
| Meaningful          | Shrank              | `EFFECTIVE_BUYBACKS`             |
| Meaningful          | Flat                | `PARTIALLY_OFFSET_BY_DILUTION`  |
| Meaningful          | Rose                | `INEFFECTIVE_BUYBACKS`          |
| Minimal             | Rose                | `NET_DILUTION`                  |
| Minimal             | Flat or shrank      | `NO_MEANINGFUL_BUYBACK_ACTIVITY`|
| Repurchases or share change unavailable | —      | `INSUFFICIENT_DATA`             |

**Rationale**: This is the core insight of the slice: spending is not the same as share reduction
because SBC and other issuance offset repurchases. Using the actual diluted-share-count change as the
primary signal captures the true per-share ownership outcome. It makes no intrinsic-value judgment.

**Alternatives considered**: Judging repurchases against intrinsic value is out of scope; inferring
share reduction from spending would mis-measure the outcome.

## Balance-sheet trajectory (shared helper)

**Decision**: Extract the net-cash trajectory rule shared by Feature 2A and 2B into an internal helper
that returns a direction, a sign-flip flag, and a net-debt flag from a start and end net cash or net
debt. Genuine deterioration is a turn to net debt or a deepening net-debt position; drawing down surplus
cash while remaining net-cash positive is not deterioration. Refactor Feature 2A and 2B to use it,
behavior-preserving, and reuse it for the Feature 2C guardrail.

**Rationale**: Three concrete consumers of the identical rule justify one small primitive. Reusing it
keeps a single definition of leverage deterioration and satisfies the requirement to reuse the 2A and
2B trajectory logic rather than introduce a separate leverage framework.

**Alternatives considered**: Duplicating the rule a third time would drift; a general leverage framework
is out of scope.

## ROIC context

**Decision**: Surface ROIC as context only: `HIGH_ROIC_CONTEXT` when end-of-year ROIC ≥ `high_roic_level`
(0.20), otherwise `LOW_ROIC_CONTEXT`; and `ROIC_IMPROVING` or `ROIC_DETERIORATING` from the Feature 2A
annual ROIC change against `material_roic_change` (0.03). Do not compute a return on retained free cash
flow and do not claim retained cash earned the company-wide ROIC.

**Rationale**: ROIC indicates whether retaining and reinvesting capital occurs in an economically
productive business, without overclaiming that the residual retained dollars earned that exact return.

**Alternatives considered**: Computing return on retained FCF would require attribution the slice
explicitly avoids.

## Capital-allocation classification

**Decision**: Classify each year with an explicit, documented, priority-ordered rule (small functions,
no numeric score, observable outcomes not intent), prioritizing per-share ownership outcome, then
buyback effectiveness, then SBC burden, then capital returned relative to free cash flow, then
balance-sheet impact, then sustained ROIC:

1. **Insufficiency gate**: diluted-share growth unavailable or buyback effectiveness `INSUFFICIENT_DATA`
   → `INSUFFICIENT_DATA`.
2. **Dilution path** (share rose): `OWNER_UNFRIENDLY` when SBC burden is high or the balance sheet
   deteriorated; otherwise `QUESTIONABLE`.
3. **Effective-reduction path** (share shrank and effectiveness `EFFECTIVE_BUYBACKS`): `QUESTIONABLE`
   when the balance sheet deteriorated (returns funded by worsening leverage); otherwise `OWNER_FRIENDLY`.
4. **Otherwise** (flat share count, or partially-offset or ineffective buybacks): `QUESTIONABLE` when
   effectiveness is `PARTIALLY_OFFSET_BY_DILUTION` or `INEFFECTIVE_BUYBACKS` and SBC burden is high, the
   balance sheet deteriorated, or capital returned materially exceeds free cash flow; `QUESTIONABLE` when
   the balance sheet deteriorated; otherwise `BALANCED`.

High SBC burden is SBC / FCF ≥ `high_sbc_to_fcf` (0.15); capital returned materially above free cash
flow is capital returned / FCF ≥ `capital_returned_over_fcf_material` (1.0). Every contributing signal
emits an ordered driver, including `HIGH_ROIC_CONTEXT` or `LOW_ROIC_CONTEXT`, `RETAINED_FCF_NEGATIVE`,
and `NO_DIVIDEND_PROGRAM` where they apply.

**Rationale**: The rule reads a year by what actually happened to owners: whether shares fell, whether
buybacks were effective net of dilution, how heavy the compensation burden was, whether distributions
outran free cash flow, whether the balance sheet weakened, and whether the business stayed high-return.
It is deterministic, transferable to another conventional operating company, and never a weighted score.

**Alternatives considered**: A weighted numeric score is forbidden; judging management intent or
valuation is out of scope.

## First-pass thresholds

**Decision**: Centralize named thresholds in one immutable `CapitalAllocationThresholds` value with a
module-level default:

| Name                                | Value | Concept                                             |
|-------------------------------------|-------|-----------------------------------------------------|
| `material_share_change`             | 0.01  | Material share-count shrinkage or dilution (±1%)     |
| `high_sbc_to_fcf`                   | 0.15  | High SBC burden (SBC / FCF ≥ 15%)                   |
| `meaningful_repurchase_to_fcf`      | 0.25  | Meaningful repurchase activity (repurchases / FCF ≥ 25%) |
| `capital_returned_over_fcf_material`| 1.00  | Capital returns materially above free cash flow      |

Balance-sheet deterioration reuses the shared trajectory helper (a turn to net debt or a deepening
net-debt position), not a new dollar threshold. `high_roic_level` (0.20) and `material_roic_change`
(0.03) are reused for ROIC context.

**Rationale**: One percent share-count movement distinguishes real buyback or dilution from rounding
(consistent with Feature 2A). Fifteen percent SBC-to-FCF marks a burden a large software owner would
notice. Twenty-five percent repurchases-to-FCF marks a genuine buyback commitment. A capital-returned
ratio at or above one marks returning as much as or more than the business generated. The values are
round, inspectable in one place, avoid false precision, plausible for conventional companies, and not
tuned to make Adobe look favorable.

**Alternatives considered**: Company-specific thresholds tuned to Adobe would overfit; configurable
weights were explicitly excluded.

## Orchestration

**Decision**: `capital_allocation_from_facts` calls the existing `owner_economics_from_facts`,
`capital_efficiency_from_facts`, and `economic_value_from_facts`, and the new reported normalizers, then
aligns by fiscal year and builds classified rows. `build_capital_allocation_rows` accepts already-computed
inputs for offline, deterministic testing. A `capital_allocation_summary` aggregates the multi-year
owner-question answers.

**Rationale**: Delegating retrieval and normalization to the reported layer and Feature 1 and 2A keeps
all network access outside the interpretation layer and keeps it independently testable.

**Alternatives considered**: Fetching inside the interpretation layer would violate the layer boundary.

## Test strategy

**Decision**: Extend `test_reported.py` for the repurchase, SBC, and dividend specs (including the
tolerant absent-dividend path and the SBC fallback), and add `test_capital_allocation.py` using
constructed inputs for the ratios, negative retained FCF, buyback effectiveness across all outcomes, the
classification across owner-friendly, balanced, questionable, and owner-unfriendly cases, the
balance-sheet guardrail, ROIC context, and deterministic ordered drivers. Keep all existing tests,
including after the trajectory refactor.

**Rationale**: Controlled fixtures make every concept, ratio, effectiveness rule, and classification
branch reproducible without network access, and the retained 2A and 2B suites guard the refactor.

**Alternatives considered**: Live-only validation is nondeterministic and cannot reproduce conflicts,
absence, and the guardrail cases.

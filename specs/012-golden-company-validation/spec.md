---
title: "Feature Specification: Full Golden-Company Validation"
description: Validate and harden the complete OwnerLens pipeline across three deliberately different companies with honest partial-coverage semantics
ms.date: 2026-09-03
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-03

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 3C: Full Golden-Company Validation. Validate the complete existing OwnerLens fundamentals and Economic Value Lens across three deliberately different U.S. businesses (ADBE, V, COST) from SEC Company Facts through canonical fundamentals, owner economics, capital efficiency, annual economic-value analysis, multi-year compounding, capital allocation, and company-level economic-value summary, without fabricating missing data or applying Adobe-specific assumptions. Primarily validate, adapt, and harden the existing pipeline; do not introduce new major analytical features."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the Full Pipeline Honestly for Each Golden Company (Priority: P1)

As an OwnerLens user, I want to run each golden company (Adobe, Visa, Costco) through the entire existing pipeline and receive the most complete honest result possible, so that I can trust OwnerLens across genuinely different business models, not just Adobe.

**Why this priority**: End-to-end validation across deliberately diverse companies is the entire purpose of this slice and is the gate before broader universe work.

**Independent Test**: For each company, run canonical fundamentals, owner economics, capital efficiency, capital-allocation facts, annual economic-value snapshots, compounding views, the capital-allocation lens, and the company-level economic-value summary, and verify each layer either produces a result or an explicit honest coverage state, with no fabricated values and no bypassed layer.

**Acceptance Scenarios**:

1. **Given** resolvable SEC Company Facts for a golden company, **When** the full pipeline runs, **Then** each analytical layer produces either a real result or an explicit coverage state, and no layer is skipped to force a company to work.
2. **Given** a company for which some inputs are unavailable, **When** the pipeline runs, **Then** OwnerLens produces the most complete honest result and never fabricates a substitute value to complete a layer.
3. **Given** all three golden companies, **When** each is run, **Then** a deterministic cross-company coverage report classifies every layer per company and gives a reason for every non-full result.

---

### User Story 2 - Propagate Partial Coverage Honestly (Priority: P2)

As an OwnerLens user, I want an unavailable input to disable only the analyses that genuinely depend on it, so that a single missing metric does not collapse an entire company's analysis or get silently replaced.

**Why this priority**: Honest degradation is what separates incomplete data from incorrect data and is essential for any company that is not Adobe-shaped.

**Independent Test**: With Visa's unsupported diluted weighted-average shares, verify that per-share analyses are reported unavailable or insufficient while revenue, free cash flow, capital efficiency, and capital-allocation analyses remain available, and that the company summary states the limitation accurately.

**Acceptance Scenarios**:

1. **Given** a company whose diluted weighted-average shares are unsupported, **When** the pipeline runs, **Then** free-cash-flow-per-share and per-share compounding are reported unavailable or insufficient, and the reason names the unsupported input.
2. **Given** the same company, **When** non-per-share layers run, **Then** revenue, free cash flow, capital efficiency, balance-sheet economics, and capital-allocation reported facts remain available and are not treated as failed.
3. **Given** a structurally absent optional metric (for example, no dividend program), **When** the affected analysis runs, **Then** it still produces a useful result where economically sensible and never treats the absence as a zero.
4. **Given** the company-level summary for a partial-coverage company, **When** it is produced, **Then** it presents available evidence, the unavailable layers, the exact missing or unsupported inputs, and an explicit insufficient-data state rather than a fabricated classification.

---

### User Story 3 - Preserve Adobe as the Full-Coverage Baseline (Priority: P2)

As an OwnerLens maintainer, I want Adobe to remain the unchanged full-coverage golden baseline, so that hardening the pipeline for diverse companies does not silently alter any established Adobe result.

**Why this priority**: Adobe is the validated reference; every regression check depends on it staying identical unless a genuine bug is found and documented.

**Independent Test**: Run Adobe through the full pipeline and verify Feature 1 values, owner economics, capital efficiency, economic-value snapshots, compounding, capital-allocation, the final summary, and provenance all match the pre-slice results.

**Acceptance Scenarios**:

1. **Given** the hardened pipeline, **When** Adobe runs, **Then** every Feature 1 and Feature 2 output and its provenance is unchanged from before this slice.
2. **Given** a change made to accommodate Visa or Costco, **When** Adobe is re-run, **Then** no Adobe classification, value, or coverage state changes as a side effect.
3. **Given** a genuine bug is discovered while validating diverse companies, **When** it is corrected, **Then** the corrected behavior is economically general and the Adobe change is explicitly documented.

---

### User Story 4 - Survive Business-Model Diversity Without Adobe-Shaped Assumptions (Priority: P3)

As an OwnerLens user, I want a low-margin or capital-light company judged on change, per-share growth, capital efficiency, and trajectory rather than on high absolute margins, so that economic-value classifications remain meaningful beyond software businesses.

**Why this priority**: Threshold assumptions calibrated on Adobe could misjudge Costco or Visa; auditing them protects analytical honesty as coverage widens.

**Independent Test**: Verify a low-margin company is not classified as deteriorating merely because its margins are low, a high-margin company is not classified as improving merely because its margins are high, and strong returns on invested capital remain meaningful across margin structures; and confirm every Feature 2 threshold has a documented generality classification.

**Acceptance Scenarios**:

1. **Given** a low-margin, working-capital-heavy company with stable or improving trajectory, **When** economic-value classification runs, **Then** it is not classified as deteriorating solely because of low absolute margins.
2. **Given** a high-margin company with weakening trajectory, **When** classification runs, **Then** it is not classified as improving solely because of high absolute margins.
3. **Given** every existing Feature 2 threshold, **When** the threshold audit is performed, **Then** each threshold is classified as business-model-independent, needing a documented limitation, or requiring future industry-aware handling, and no industry-specific threshold is introduced unless a clearly incorrect generic assumption is demonstrated and corrected generally.

### Edge Cases

- A required per-share denominator is unsupported, making per-share analyses unavailable while other analyses proceed.
- An optional metric is structurally absent (no dividend program) but the containing analysis remains useful.
- A company has too few historical years for multi-year compounding, yielding insufficient-data rather than a fabricated trend.
- A 52/53-week fiscal calendar produces a full year that must be recognized as annual.
- A company's margins are far lower than the software baseline yet its trajectory and capital efficiency are healthy.
- A metric is a genuine reported zero, which must remain distinct from absence, unsupported, or insufficiency.
- A downstream layer would need to bypass an upstream layer to produce a result; this must not happen.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: OwnerLens MUST run each golden company through every existing analytical layer it supports, from canonical fundamentals through the company-level economic-value summary, without bypassing any layer to make a company work.
- **FR-002**: OwnerLens MUST preserve and surface the distinct coverage states already established: available, structurally absent, unsupported, reported zero, and insufficient historical data.
- **FR-003**: A missing or unavailable metric MUST NOT automatically fail an entire company's analysis when downstream analysis can still be performed honestly without it.
- **FR-004**: OwnerLens MUST NOT fabricate a substitute value to complete a layer, and specifically MUST NOT substitute point-in-time shares outstanding for weighted-average diluted shares.
- **FR-005**: OwnerLens MUST provide a small explicit analysis-coverage representation capturing, per company and analytical layer, the available, absent, and unsupported inputs and the resulting available outputs, without introducing a generalized workflow or orchestration engine.
- **FR-006**: Where partial inputs exist, OwnerLens MUST accept them, return explicit insufficient-data classifications where a required input is missing, preserve available evidence, and identify which input prevented fuller analysis.
- **FR-007**: OwnerLens MUST make minimum-data contracts explicit for analyses whose meaning depends on specific inputs (for example, free-cash-flow-per-share requires a trustworthy per-share denominator; return on invested capital requires operating-profit, tax, and invested-capital inputs).
- **FR-008**: OwnerLens MUST fix only the assumptions actually exposed by validating Adobe, Visa, and Costco, using narrow optional handling, explicit insufficient-data states, and small coverage helpers, and MUST NOT preemptively rewrite the economic-value modules into a generic optional-field framework.
- **FR-009**: OwnerLens MUST preserve all existing Adobe Feature 1 and Feature 2 outputs, classifications, and provenance unchanged unless a genuine bug is found, in which case the corrected behavior MUST be economically general and the change documented.
- **FR-010**: For Visa, OwnerLens MUST document what works, what is structurally absent, and what is unsupported, and MUST show how the unsupported diluted-share input propagates into the economic-value layers without treating unrelated metrics as failed.
- **FR-011**: For Costco, OwnerLens MUST correctly handle the 52/53-week fiscal calendar and low-margin, working-capital-heavy economics, and economic-value reasoning MUST rest on change, per-share growth, capital efficiency, and trajectory rather than on high absolute margins.
- **FR-012**: OwnerLens MUST audit every existing economic-value threshold and classify each as business-model-independent, needing a documented limitation, or requiring future industry-aware handling, and MUST NOT introduce industry-specific thresholds unless a clearly incorrect generic assumption is demonstrated and corrected generally.
- **FR-013**: OwnerLens MUST produce a deterministic cross-company coverage report that classifies every analytical layer for each golden company and gives a reason for every non-full result, as a validation report rather than a comparison feature.
- **FR-014**: For each golden company, OwnerLens MUST present the most complete honest result: a compact economic-value summary for full-coverage companies, and available evidence plus unavailable layers, exact missing or unsupported inputs, and an explicit insufficient-data state for partial-coverage companies, with no fabricated classification.
- **FR-015**: Verification MUST cover full-coverage, partial-coverage, absent-metric, business-model-diversity, and regression scenarios using controlled inputs rather than relying exclusively on live SEC availability, with an optional live check for the three golden companies.
- **FR-016**: The feature MUST remain validation and hardening only and MUST NOT add persistence, hosted infrastructure, batch or universe ingestion, scores, screeners, stock comparison, valuation, price data, agents, industry-specific scoring, external normalized-data providers, or attempts to solve every unsupported Visa metric.

### Key Entities

- **Golden Company**: One of the three deliberately different validation companies (Adobe, Visa, Costco), chosen to expose distinct business-model assumptions.
- **Analysis Coverage**: A per-company, per-layer record of available, absent, and unsupported inputs and the resulting available outputs.
- **Coverage State**: The classification of a metric or layer as available, structurally absent, unsupported, reported zero, or insufficient historical data.
- **Minimum-Data Contract**: The explicit set of inputs an analysis requires for its result to be economically meaningful.
- **Cross-Company Coverage Report**: The deterministic validation grid classifying every analytical layer for each golden company with reasons for non-full results.
- **Threshold Audit**: The record classifying each economic-value threshold as business-model-independent, needing a documented limitation, or requiring future industry-aware handling.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three golden companies run through the full pipeline, and every analytical layer yields either a real result or an explicit honest coverage state, with zero fabricated or silently substituted values.
- **SC-002**: Visa's unsupported diluted-share input disables exactly the per-share-dependent analyses (annual per-share classification, per-share compounding, and the per-share portion of the summary) while revenue, free cash flow, capital efficiency, balance-sheet economics, and capital-allocation facts remain available, each with a stated reason.
- **SC-003**: 100% of Adobe Feature 1 and Feature 2 outputs, classifications, and provenance remain unchanged, and every previously passing Adobe test continues to pass.
- **SC-004**: In controlled business-model-diversity scenarios, a low-margin company is never classified as deteriorating solely for low margins, a high-margin company is never classified as improving solely for high margins, and strong returns on invested capital remain recognized across margin structures.
- **SC-005**: 100% of existing economic-value thresholds carry a documented generality classification.
- **SC-006**: The cross-company coverage report is deterministic and reproducible and provides a reason for every non-full cell.
- **SC-007**: The remaining blockers to broader universe ingestion are explicitly documented.
- **SC-008**: All required scenarios are verifiable repeatably without a live SEC request, while an optional live check confirms honest coverage for Adobe, Visa, and Costco.

## Assumptions

- Company identity resolution and canonical metric normalization are already generalized (prior slices); this slice consumes their outputs and validates the downstream pipeline.
- The distinct coverage states (available, structurally absent, unsupported, reported zero, insufficient historical data) already exist and are reused rather than redefined.
- Visa's diluted weighted-average shares remain unsupported from the current SEC source; solving that limitation is explicitly out of scope for this slice.
- The 52/53-week full-year handling already implemented is validated here, not rebuilt.
- Thresholds are audited for business-model independence and are not tuned to make companies look attractive.
- Feature 2 economic-value logic reasons primarily about change, per-share growth, capital efficiency, and trajectory rather than absolute margin levels.
- The cross-company report and company-level outputs are validation artifacts, not a stock-comparison or scoring feature.
- Live SEC availability is outside OwnerLens control, so repeatable verification uses controlled inputs and treats live access as an optional honest-coverage check.

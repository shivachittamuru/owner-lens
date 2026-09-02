---
title: "Feature Specification: Company-Level Economic Value Summary"
description: Synthesize the annual, compounding, and capital-allocation lenses into one deterministic company-level owner conclusion
ms.date: 2026-09-02
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 2D: Company-Level Economic Value Summary."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Synthesize One Company-Level Owner Conclusion (Priority: P1)

As an OwnerLens user, I want the annual economic-value snapshot, the multi-year compounding view, and the capital-allocation lens synthesized into one concise company-level conclusion so that I can understand, at a glance, how the business's economic value per ownership unit has been developing.

**Why this priority**: The single synthesized conclusion is the capstone of Feature 2 and the object every other capability attaches to; without it there is no company-level summary.

**Independent Test**: Provide the already-produced Feature 2A, 2B, and 2C outputs and verify one summary is produced that carries the component classifications, an overall classification, ordered driver categories, and a compact evidence set, each drawn from existing outputs with no new financial facts.

**Acceptance Scenarios**:

1. **Given** the annual snapshot, compounding view, and capital-allocation outputs for a company, **When** the summary is produced, **Then** one company-level summary is returned carrying the ticker, latest fiscal year, the component classifications, and an overall classification.
2. **Given** the component outputs, **When** the summary is produced, **Then** it carries a compact evidence set drawn from existing outputs and does not duplicate every underlying metric.
3. **Given** the summary, **When** it is inspected, **Then** it exposes ordered positive, watch, and negative driver categories that are deduplicated and traceable to the component outputs.

---

### User Story 2 - Classify Overall Economic Value by a Documented Hierarchy (Priority: P1)

As an OwnerLens user, I want the overall classification produced by a documented priority hierarchy rather than an average of the component verdicts so that durable multi-year economics outweigh a single strong or weak year.

**Why this priority**: The synthesis rule is the core learning objective; a mapping or average of component classifications would hide the owner-economics reasoning and let one year dominate.

**Independent Test**: Provide crafted component sets representing strongly improving, improving, stable, deteriorating, and strongly deteriorating economics, and verify each produces the expected overall classification from the documented hierarchy, not from an average.

**Acceptance Scenarios**:

1. **Given** improving annual economics, strong long-term compounding, owner-friendly capital allocation, and high stable ROIC, **When** the overall classification is produced, **Then** it is strongly improving.
2. **Given** improving latest-year economics but declining multi-year FCF-per-share and deteriorating ROIC, **When** the overall classification is produced, **Then** one strong year does not override the weak long-term economics.
3. **Given** strong long-term compounding, a temporarily weak latest year, still-high ROIC, and a strong balance sheet, **When** the overall classification is produced, **Then** it is not automatically deteriorating.
4. **Given** identical component inputs classified twice, **When** the overall classification and drivers are compared, **Then** they are identical every time.

---

### User Story 3 - Prefer Durable Economics and Handle Current-vs-Long-Term Tension (Priority: P1)

As an OwnerLens user, I want the summary to explicitly reconcile disagreement between recent and long-term results so that I can distinguish an established compounding history from a recent trend change.

**Why this priority**: Distinguishing durable trends from one-year noise is the central intuition the capstone teaches and the reason it is not a simple mapping.

**Independent Test**: Provide component sets where recent and long-term results disagree in each direction and verify the summary surfaces the appropriate tension driver without overreacting.

**Acceptance Scenarios**:

1. **Given** strong long-term compounding with a weak latest year, **When** the summary is produced, **Then** it surfaces a recent-slowdown signal rather than immediately classifying the business as deteriorating.
2. **Given** weak long-term economics with a strong latest year, **When** the summary is produced, **Then** it surfaces an early-improvement-not-yet-proven signal rather than immediately classifying the business as improving.
3. **Given** recent and long-term results that both agree, **When** the summary is produced, **Then** the agreement reinforces the improving or deteriorating classification accordingly.

---

### User Story 4 - Distinguish Watch Signals from Verdict-Changing Guardrails (Priority: P1)

As an OwnerLens user, I want economically relevant warnings surfaced as watch signals without changing the verdict unless they cross a documented severity threshold so that the summary does not overreact to every warning.

**Why this priority**: Distinguishing a warning from thesis-breaking deterioration keeps the conclusion trustworthy and is a key learning objective.

**Independent Test**: Provide component sets with a high SBC burden, capital returns above free cash flow, deepening net debt, and collapsing ROIC, and verify only the documented severe signals downgrade the classification while the rest appear as watch drivers.

**Acceptance Scenarios**:

1. **Given** a high SBC burden while the diluted share count is still shrinking materially, **When** the summary is produced, **Then** the SBC burden is a watch driver and does not by itself downgrade the classification.
2. **Given** capital returned above free cash flow while the company remains net-cash positive, **When** the summary is produced, **Then** it is a watch driver and does not by itself downgrade the classification.
3. **Given** persistent deepening net debt or a sustained ROIC collapse, **When** the summary is produced, **Then** the guardrail downgrades the overall classification.

---

### User Story 5 - Read a Compact Owner-Oriented Summary for Adobe (Priority: P3)

As an OwnerLens user, I want a compact human-readable company-level Economic Value Lens for Adobe so that I can validate the synthesis against a real company end to end.

**Why this priority**: The live validation demonstrates the capstone and confirms the deterministic synthesis behaves sensibly on real data, but it depends on the preceding stories.

**Independent Test**: Produce the summary for Adobe and confirm it shows the component classifications, the overall classification, the core evidence, and the positive, watch, and negative drivers, answering the owner questions in compact form.

**Acceptance Scenarios**:

1. **Given** Adobe's Feature 2A, 2B, and 2C outputs, **When** the compact summary is produced, **Then** it shows the latest annual classification, the recent and long-term compounding classifications, the capital-allocation classification, and the overall classification.
2. **Given** the summary, **When** it is inspected, **Then** it shows the core evidence metrics and the ordered positive, watch, and negative drivers.
3. **Given** the summary, **When** it is read, **Then** it answers whether the per-share economic engine is improving, whether that improvement is durable, whether capital allocation helps owners, whether the balance sheet supports the strategy, and what the most important warning signs are, without requiring raw financial tables.

### Edge Cases

* One or more component outputs are insufficient-data, so the overall summary must be insufficient-data or classify conservatively.
* The recent compounding view is unavailable because history is too short, so the summary omits it gracefully.
* A single strong latest year coincides with weak multi-year compounding and deteriorating ROIC.
* Strong long-term compounding coincides with a temporarily weak latest year while ROIC stays high and the balance sheet is strong.
* High per-share growth coincides with weak aggregate free cash flow and heavy dilution or worsening leverage.
* Multiple component layers emit related signals that must be deduplicated into one driver.
* A watch signal and a guardrail signal are both present, and only the guardrail changes the verdict.
* Recent and long-term results disagree in either direction.
* All components agree strongly positive, or all agree strongly negative.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST produce one deterministic company-level economic-value summary that carries the ticker, the latest fiscal year, the latest annual classification, the long-term compounding classification, the recent compounding classification where available, the latest capital-allocation classification, the overall classification, ordered positive, watch, and negative drivers, and a compact evidence set.
* **FR-002**: OwnerLens MUST derive every field of the summary from existing Feature 1 and Feature 2 outputs and MUST NOT add new SEC financial facts, make SEC calls, perform financial-statement normalization, duplicate Feature 1 calculations, or reimplement Feature 2 component logic.
* **FR-003**: OwnerLens MUST classify the overall economic value as exactly one of strongly improving, improving, stable, deteriorating, strongly deteriorating, or insufficient-data.
* **FR-004**: The overall classification MUST be produced by an explicit, documented priority hierarchy and MUST NOT be a mapping or numeric or weighted average of the component classifications, a 0-to-100 score, hidden points, black-box scoring, configurable scoring weights, or model-generated prose.
* **FR-005**: The classification hierarchy MUST prioritize evidence in a documented order covering multi-year FCF-per-share compounding, recent annual per-share economic direction, ROIC quality and trajectory, capital-allocation effectiveness, share-count direction, free-cash-flow and margin quality, balance-sheet trajectory, and material warning signals, and MUST prefer durable multi-year economics over a single strong or weak year.
* **FR-006**: OwnerLens MUST establish a long-term compounding base verdict, adjust it by the latest annual direction, apply a capital-allocation quality modifier, and apply severe quality and balance-sheet guardrails, in a documented order.
* **FR-007**: OwnerLens MUST distinguish watch signals from verdict-changing guardrail signals: a watch signal is economically relevant but does not by itself change the overall classification, while a guardrail signal is severe enough to downgrade it, and the summary MUST NOT overreact to every warning.
* **FR-008**: OwnerLens MUST treat a high SBC burden while the share count is still shrinking materially, and capital returns above free cash flow while the company remains net-cash positive, as watch signals, and MUST treat persistent deepening net debt and sustained ROIC collapse as verdict-changing guardrails, per documented severity thresholds.
* **FR-009**: OwnerLens MUST explicitly reconcile recent-versus-long-term disagreement, surfacing a recent-slowdown signal when long-term economics are strong but the latest year is weak, an early-improvement-not-yet-proven signal when long-term economics are weak but the latest year is strong, and reinforcing the verdict when recent and long-term results agree.
* **FR-010**: OwnerLens MUST produce ordered positive, watch, and negative driver categories that are deterministic, deduplicated when multiple component layers emit related signals, and traceable to the component outputs, and MUST NOT use free-form prose as the source of truth.
* **FR-011**: OwnerLens MUST carry a compact evidence set drawn from existing outputs, including the latest FCF-per-share growth, the long-term FCF-per-share CAGR, the recent FCF-per-share CAGR where available, the diluted-share CAGR, the latest ROIC, the long-term ROIC change, the latest net cash or net debt, the latest SBC over free cash flow, a buyback-effectiveness indicator, and the latest capital returned over free cash flow, and MUST NOT duplicate every underlying metric.
* **FR-012**: OwnerLens MUST classify the overall summary as insufficient-data, or classify conservatively, when the component outputs required by the documented rule are unavailable, and MUST omit the recent compounding classification gracefully when its history is too short.
* **FR-013**: The overall classification and all drivers MUST be deterministic, so identical component inputs always produce the identical classification and the identical ordered drivers.
* **FR-014**: OwnerLens MUST implement the synthesis as a separate composition layer that consumes existing Feature 2 objects, preferring composition over inheritance or framework-style abstractions, and MUST NOT introduce a rules-engine or scoring framework.
* **FR-015**: OwnerLens MUST be able to produce a compact human-readable company-level Economic Value Lens for Adobe showing the component classifications, the overall classification, the core evidence, and the positive, watch, and negative drivers, understandable without raw financial tables.
* **FR-016**: The feature MUST preserve all existing Feature 1 (Slice 1A through 1E), Feature 2A, 2B, and 2C behavior and regression tests.
* **FR-017**: The feature MUST remain limited to ADBE and to the company-level synthesis, and MUST NOT introduce intrinsic valuation, stock price, expected return, scenario analysis, a quality, growth, valuation, or 0-to-100 economic-value score, screening, cross-company comparison, portfolio aggregation, agents, LLM-written conclusions, or Azure infrastructure.

### Key Entities

* **Economic Value Summary**: The company-level record carrying the ticker, latest fiscal year, the component classifications, the overall classification, the ordered driver categories, and the compact evidence set.
* **Overall Economic Value Classification**: The deterministic company-level verdict, one of strongly improving, improving, stable, deteriorating, strongly deteriorating, or insufficient-data.
* **Component Classification Set**: The latest annual, recent compounding, long-term compounding, and latest capital-allocation classifications consumed from Feature 2A, 2B, and 2C.
* **Driver Category**: An ordered, deduplicated set of named positive, watch, or negative reason codes traceable to the component outputs.
* **Watch Signal**: An economically relevant reason code that does not by itself change the overall classification.
* **Guardrail Signal**: A severe reason code that downgrades the overall classification when it crosses a documented severity threshold.
* **Tension Signal**: A reason code reconciling recent-versus-long-term disagreement, such as recent slowdown or early improvement not yet proven.
* **Evidence Set**: The compact set of headline metrics drawn from existing outputs supporting the summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid set of component outputs, exactly one company-level summary is produced, carrying the component classifications, the overall classification, the ordered driver categories, and the compact evidence set.
* **SC-002**: In 100% of controlled cases representing strongly improving, improving, stable, deteriorating, and strongly deteriorating economics, the overall classification matches the intended verdict from the documented hierarchy.
* **SC-003**: In 100% of controlled cases where a single strong latest year coincides with weak multi-year compounding and deteriorating ROIC, the overall classification is not improving.
* **SC-004**: In 100% of controlled cases with strong long-term compounding, a temporarily weak latest year, high ROIC, and a strong balance sheet, the overall classification is not deteriorating and a recent-slowdown driver is surfaced.
* **SC-005**: In 100% of controlled cases, a high SBC burden with a materially shrinking share count and capital returns above free cash flow while net-cash positive appear as watch drivers and do not downgrade the classification, while deepening net debt and sustained ROIC collapse do downgrade it.
* **SC-006**: In 100% of controlled cases where multiple component layers emit related signals, the drivers are deduplicated into one ordered entry per signal.
* **SC-007**: For identical component inputs, the overall classification and the ordered positive, watch, and negative drivers are identical across repeated runs in 100% of cases.
* **SC-008**: In 100% of controlled cases where a required component output is unavailable, the summary is insufficient-data or classifies conservatively, and the recent compounding classification is omitted gracefully when history is too short.
* **SC-009**: The compact Adobe Economic Value Lens is produced from existing outputs and answers whether the per-share engine is improving, whether it is durable, whether capital allocation helps owners, whether the balance sheet supports the strategy, and what the key warnings are, without raw financial tables.
* **SC-010**: The synthesis layer performs no external calls, and the Adobe summary is produced from already-retrieved data in under 2 seconds.
* **SC-011**: All existing Feature 1, Feature 2A, 2B, and 2C tests continue to pass unchanged.
* **SC-012**: Review confirms the feature adds only the company-level synthesis for ADBE and introduces no out-of-scope valuation, scoring, screening, cross-company, portfolio, agent, or infrastructure behavior.

## Assumptions

* The Feature 2A annual economic-value snapshots, the Feature 2B compounding views (recent and long-term), and the Feature 2C capital-allocation rows are available as trustworthy inputs and are consumed as-is.
* The synthesis layer reads these existing outputs and performs no SEC retrieval, normalization, or recomputation of component logic.
* "Latest" refers to the most recent completed fiscal year available across the component outputs, and the recent compounding view may be unavailable when history is too short.
* The evidence set is a compact selection of existing metrics, not a re-derivation, chosen to support the verdict without duplicating every underlying value.
* The overall classification is coarse by design to avoid false precision, and it is never a numeric or weighted score.
* Reason codes and drivers are deterministic and testable; exact code names may evolve but their behavior is fixed for given inputs.
* Watch-versus-guardrail severity thresholds are documented first-pass values, deliberately conservative so the summary does not overreact, and consistent with the component-level thresholds already established in Feature 2.
* The summary makes no valuation, intrinsic-value, or future-durability judgment; it summarizes observed economic-value development only.

## Dependencies

* The Feature 2A annual economic-value snapshots and their classifications and drivers.
* The Feature 2B recent and long-term compounding views and their classifications, CAGRs, and drivers.
* The Feature 2C capital-allocation rows and their classifications, buyback effectiveness, and drivers.
* The Feature 1 and Feature 2 outputs that supply the compact evidence metrics (FCF-per-share growth and CAGR, diluted-share CAGR, ROIC and its change, net cash or net debt, SBC over free cash flow, and capital returned over free cash flow).

## Scope Boundaries

The feature includes only the ADBE company-level synthesis built from existing Feature 2A, 2B, and 2C outputs; a deterministic overall classification produced by a documented priority hierarchy that prefers durable multi-year economics; an explicit long-term base, latest-year adjustment, capital-allocation modifier, and severe guardrails; an explicit distinction between watch signals and verdict-changing guardrails; explicit reconciliation of recent-versus-long-term tension; ordered, deduplicated, traceable positive, watch, and negative drivers; a compact evidence set drawn from existing outputs; a composition layer consuming Feature 2 objects; and a compact human-readable Adobe summary.

The feature excludes intrinsic valuation, stock price, expected return, bear/base/bull scenarios, a quality score, a growth score, a valuation score, a 0-to-100 economic-value score, weighted-average or hidden scoring, screening, cross-company comparison, portfolio aggregation, agents, LLM-written investment conclusions, Azure or other hosted infrastructure, and multi-company validation.

---
title: "Feature Specification: Capital Allocation Lens"
description: Normalize Adobe capital-allocation facts and interpret how management deployed generated cash for per-share owners
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 2C: Capital Allocation Lens."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize Adobe's Capital-Allocation Facts (Priority: P1)

As an OwnerLens user, I want Adobe's share-repurchase cash outflows, cash dividends paid, and stock-based compensation normalized as canonical fiscal-year facts so that OwnerLens has the trustworthy reported inputs needed to explain capital allocation.

**Why this priority**: These reported facts are the foundation for every derived capital-allocation metric; without them there is no capital-allocation lens.

**Independent Test**: Provide a controlled Adobe Company Facts payload with full-year, interim, and repeated observations for each concept, then verify one canonical fiscal-year observation per recent fiscal year for each fact, with full provenance, and explicit failure on unresolved conflicts.

**Acceptance Scenarios**:

1. **Given** a raw Adobe Company Facts payload with full-year observations for repurchases, dividends paid, and stock-based compensation, **When** normalization runs, **Then** each fact returns one canonical annual observation for each of approximately the latest five completed fiscal years.
2. **Given** interim and full-year observations for the same concept, **When** normalization runs, **Then** only the full-year observation is selected and interim observations are excluded.
3. **Given** a later filing that repeats a prior fiscal year's value as a comparative, **When** normalization runs, **Then** each fiscal year appears exactly once with earliest-filed provenance retained.
4. **Given** two conflicting distinct values for the same fiscal year that the rules cannot disambiguate, **When** normalization runs, **Then** it fails explicitly and identifies the unresolved fiscal year.

---

### User Story 2 - Preserve Reported-Fact Meaning and Absence Explicitly (Priority: P1)

As an OwnerLens user, I want each capital-allocation fact to carry its documented economic meaning and to distinguish a reported zero from an absent concept so that I never see a fabricated value.

**Why this priority**: Capital-allocation interpretation is only trustworthy if the underlying facts mean exactly what they claim and missing data is never silently zero-filled.

**Independent Test**: Provide payloads where a concept is present with a zero value and where the concept is entirely absent, and verify the two cases are represented distinctly, and that repurchase spending is taken from the reported cash outflow rather than inferred from share-count or treasury-stock changes.

**Acceptance Scenarios**:

1. **Given** a repurchase cash-outflow observation, **When** it is normalized, **Then** its canonical meaning is the cash spent purchasing the company's own common shares during the fiscal year, taken from the reported concept and not inferred from changes in share count or treasury stock.
2. **Given** a fiscal year where a concept reports an explicit zero, **When** it is normalized, **Then** the value is preserved as zero and distinguished from an absent concept.
3. **Given** a fiscal year where a concept is absent, **When** normalization runs, **Then** the fact is represented as unavailable rather than fabricated as zero.
4. **Given** the dividends concept, **When** it is normalized, **Then** it reflects cash dividends actually paid to common shareholders and not declared, per-share, or accrued-but-unpaid dividend metadata.

---

### User Story 3 - Derive Capital-Allocation Metrics (Priority: P1)

As an OwnerLens user, I want repurchase, dividend, SBC, capital-returned, and retained-FCF metrics derived per fiscal year so that I can see how the cash the business generated was deployed.

**Why this priority**: These derived metrics are the quantitative core of the lens and feed every interpretation.

**Independent Test**: Provide aligned free cash flow and canonical capital-allocation facts, then verify each derived metric equals its documented formula where inputs exist and is omitted where they do not, including a negative retained-FCF result when distributions exceed free cash flow.

**Acceptance Scenarios**:

1. **Given** a fiscal year with free cash flow and the capital-allocation facts, **When** metrics are derived, **Then** repurchases over free cash flow, dividends over free cash flow, SBC over free cash flow, capital returned, capital returned over free cash flow, and retained free cash flow equal their documented formulas.
2. **Given** a fiscal year where capital returned exceeds free cash flow, **When** retained free cash flow is derived, **Then** the result is negative and preserved rather than clamped to zero.
3. **Given** a fiscal year missing a required input, **When** metrics are derived, **Then** the affected metric is omitted explicitly rather than computed from a substituted zero.
4. **Given** the derived metrics, **When** they are inspected, **Then** conventional free cash flow and the SBC burden are both shown, and free cash flow is not silently redefined to subtract SBC.

---

### User Story 4 - Interpret Buyback Effectiveness (Priority: P1)

As an OwnerLens user, I want repurchase spending compared against the actual change in diluted share count so that I can tell whether buybacks genuinely reduced my ownership dilution or were offset by issuance.

**Why this priority**: Distinguishing repurchase spending from real share-count reduction is the central insight of the slice.

**Independent Test**: Provide crafted years combining repurchase spending levels with share-count outcomes, then verify each yields the expected buyback-effectiveness interpretation from centralized thresholds.

**Acceptance Scenarios**:

1. **Given** meaningful repurchase spending and a meaningful diluted-share-count decline, **When** buyback effectiveness is interpreted, **Then** it is classified as effective.
2. **Given** significant repurchase spending and a roughly flat diluted share count, **When** it is interpreted, **Then** it is classified as substantially offset by dilution.
3. **Given** significant repurchase spending and a rising diluted share count, **When** it is interpreted, **Then** it is classified as ineffective from a per-share ownership perspective.
4. **Given** minimal repurchase spending and a rising diluted share count, **When** it is interpreted, **Then** it is classified as net dilution.
5. **Given** minimal repurchase activity and a roughly flat share count, **When** it is interpreted, **Then** it is classified as no meaningful buyback activity, and a year lacking the required inputs is insufficient-data.

---

### User Story 5 - Classify Capital Allocation with Transparent Drivers (Priority: P1)

As an OwnerLens user, I want each fiscal year classified as owner-friendly, balanced, questionable, owner-unfriendly, or insufficient-data, with explicit ordered drivers, so that I can inspect the observable capital-allocation outcome rather than accept an opaque verdict.

**Why this priority**: The interpretable classification is the headline outcome and the core learning objective of the slice.

**Independent Test**: Provide crafted years representing owner-friendly, balanced, questionable, and owner-unfriendly capital allocation, then verify each produces the expected classification and a deterministic ordered set of named drivers.

**Acceptance Scenarios**:

1. **Given** strong free cash flow with a meaningful share-count reduction, buybacks overcoming SBC dilution, a healthy balance sheet, and high ROIC, **When** the year is classified, **Then** it is owner-friendly and the drivers name the responsible signals.
2. **Given** very large repurchase spending with little share-count reduction, a high SBC burden, and a weakening balance sheet, **When** the year is classified, **Then** it is questionable and a driver surfaces the ineffective buybacks and SBC burden.
3. **Given** material dilution, a high SBC burden, and large capital returns funded by materially worsening leverage, **When** the year is classified, **Then** it is owner-unfriendly.
4. **Given** moderate distributions, manageable dilution, a stable balance sheet, and no strong positive or negative signal, **When** the year is classified, **Then** it is balanced.
5. **Given** identical inputs classified twice, **When** the drivers are compared, **Then** the classification and the ordered drivers are identical every time.

---

### User Story 6 - Interpret Distributions in Balance-Sheet and ROIC Context (Priority: P2)

As an OwnerLens user, I want capital returns interpreted against the balance-sheet trajectory and ROIC context so that a company is not penalized for drawing down excess cash while remaining strong, and is flagged when distributions are funded by worsening leverage.

**Why this priority**: Context prevents naive penalties and naive praise, keeping the capital-allocation verdict economically honest.

**Independent Test**: Provide a year that draws down surplus cash while remaining net-cash positive and a year that deepens net debt to fund distributions, and verify only the latter is treated as a balance-sheet deterioration; verify ROIC context is surfaced without claiming retained cash earned that ROIC.

**Acceptance Scenarios**:

1. **Given** a year whose cash declines while the company remains financially strong, **When** the balance sheet is interpreted, **Then** it is not treated as a deterioration.
2. **Given** a year that materially increases or deepens net debt to fund distributions, **When** the balance sheet is interpreted, **Then** it is treated as a deterioration, reusing the Feature 2A and 2B balance-sheet trajectory logic rather than a separate leverage framework.
3. **Given** the year's ROIC level and direction, **When** the retained-capital context is surfaced, **Then** it is expressed as high or low ROIC context and improving or deteriorating ROIC, without claiming retained free cash flow earned that ROIC and without computing a return on retained free cash flow.

---

### User Story 7 - Review the Adobe Capital-Allocation View (Priority: P3)

As an OwnerLens user, I want a compact per-year Adobe capital-allocation view and a multi-year summary so that I can validate the lens against a real company end to end.

**Why this priority**: The live validation demonstrates the slice and confirms the deterministic layer behaves sensibly on real data, but it depends on the preceding stories.

**Independent Test**: Produce the view for Adobe across approximately the latest five completed fiscal years and confirm each row shows the reported facts, derived metrics, buyback effectiveness, and classification with ordered drivers, and that a multi-year summary answers the owner questions.

**Acceptance Scenarios**:

1. **Given** Adobe's normalized facts and metrics, **When** the per-year view is produced, **Then** it shows free cash flow, repurchases, repurchases over free cash flow, dividends, SBC, SBC over free cash flow, capital returned, capital returned over free cash flow, retained free cash flow, diluted-share growth, buyback effectiveness, net cash or net debt, ROIC, and the capital-allocation classification for each year.
2. **Given** any classified year, **When** it is inspected, **Then** its ordered drivers are displayed.
3. **Given** the supported period, **When** the multi-year summary is produced, **Then** it answers how much free cash flow was generated, how much went to repurchases and dividends, how large SBC was relative to free cash flow, whether the diluted share count shrank, whether repurchases overcame dilution, whether the balance sheet remained healthy, and whether ROIC remained attractive.

### Edge Cases

* A capital-allocation concept is absent for the whole period, so the metric must be unavailable, not zero.
* A concept reports an explicit zero for a fiscal year, which must be distinguished from an absent concept.
* Adobe does not materially pay dividends during the supported period, so absence is preserved explicitly.
* Multiple candidate concepts overlap for repurchases, so double counting must be avoided.
* Capital returned exceeds free cash flow, producing a negative retained free cash flow that must be preserved.
* Heavy repurchase spending coincides with a flat or rising diluted share count because SBC or other issuance offsets it.
* Cash declines because surplus cash was returned while the company remains net-cash positive.
* Net debt deepens to fund distributions.
* Free cash flow is unavailable for a fiscal year, so ratio metrics cannot be formed.
* A repeated comparative value or a genuine restatement conflict appears for a capital-allocation concept.
* SBC expense does not map one-for-one to diluted-share dilution.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST normalize canonical annual series for common-stock repurchase cash outflows, cash dividends paid to common shareholders, and stock-based compensation expense from Adobe's raw SEC Company Facts, targeting approximately the latest five completed fiscal years.
* **FR-002**: OwnerLens MUST identify Adobe's actual SEC XBRL concepts for each new fact through research before defining canonical mappings, MUST use deterministic concept selection, and MUST NOT hard-code Adobe values.
* **FR-003**: OwnerLens MUST reuse the existing annual duration-normalization machinery for these full-year facts where applicable, deriving each observation's fiscal year from the economic period-end date rather than the raw XBRL fiscal-year field.
* **FR-004**: OwnerLens MUST produce at most one canonical annual observation per fiscal year per fact, collapse identical repeated comparatives while retaining earliest-filed provenance, and fail with a typed ambiguity error when distinct values for one fiscal year cannot be resolved by the existing explicit rules.
* **FR-005**: OwnerLens MUST preserve full provenance for every selected capital-allocation observation, including SEC concept, unit, fiscal year, fiscal period, form, filing date, accession, and value.
* **FR-006**: OwnerLens MUST define the canonical repurchase meaning as cash spent purchasing the company's own common shares during the fiscal year, MUST document whether the value is reported as a positive expenditure magnitude and how overlapping concepts avoid double counting, and MUST NOT infer repurchase spending from changes in treasury stock or share count.
* **FR-007**: OwnerLens MUST normalize cash dividends actually paid to common shareholders and MUST NOT substitute declared dividends, dividend-per-share metadata, or accrued-but-unpaid dividends; when Adobe does not materially pay dividends in the supported period, OwnerLens MUST preserve that absence explicitly rather than fabricating zero values.
* **FR-008**: OwnerLens MUST normalize reported stock-based compensation expense, document the selected concept and whether it represents total company SBC, treat SBC as an owner cost and dilution-pressure signal, and MUST NOT subtract SBC from free cash flow or redefine free cash flow in this slice.
* **FR-009**: OwnerLens MUST distinguish, as far as the data reliably allows, a reported zero from no applicable activity from unavailable or ambiguous data, and MUST preserve an explicit unavailable value and classify conservatively when the distinction cannot be made reliably.
* **FR-010**: OwnerLens MUST derive, per fiscal year where inputs exist, repurchases over free cash flow, dividends over free cash flow, SBC over free cash flow, capital returned as repurchases plus dividends, capital returned over free cash flow, and retained free cash flow as free cash flow minus repurchases minus dividends.
* **FR-011**: OwnerLens MUST treat retained free cash flow as an interpretive accounting residual, MUST NOT claim every retained dollar was economically reinvested, and MUST preserve a negative retained free cash flow when capital returned exceeds free cash flow rather than clamping it to zero.
* **FR-012**: OwnerLens MUST reuse the existing free cash flow, operating cash flow, CapEx, diluted-share, share-count-growth, FCF-per-share, net cash or net debt, and ROIC outputs rather than recomputing them.
* **FR-013**: OwnerLens MUST derive a deterministic buyback-effectiveness interpretation that compares repurchase spending against the actual change in diluted share count, distinguishing at least effective buybacks, buybacks substantially offset by dilution, ineffective buybacks, net dilution, no meaningful buyback activity, and insufficient-data, and MUST NOT attempt to judge whether repurchases occurred below intrinsic value.
* **FR-014**: OwnerLens MUST use the actual diluted-share-count change as the primary ownership outcome and MUST NOT assume SBC expense maps one-for-one to share dilution; SBC over free cash flow provides context on the economic size of the compensation burden.
* **FR-015**: OwnerLens MUST classify each fiscal year's capital allocation as exactly one of owner-friendly, balanced, questionable, owner-unfriendly, or insufficient-data, summarizing observable outcomes rather than management intent.
* **FR-016**: The classification MUST be produced by explicit, documented deterministic rules prioritizing the actual per-share ownership outcome, repurchase effectiveness, SBC burden, capital returned relative to free cash flow, balance-sheet impact, and sustained ROIC or quality of retained capital, and MUST NOT introduce a 0-to-100 capital-allocation score or configurable scoring weights.
* **FR-017**: Each classification and each buyback-effectiveness interpretation MUST include an ordered set of explicit, named drivers, and MUST be deterministic so identical inputs always produce the identical result and the identical ordered drivers.
* **FR-018**: OwnerLens MUST interpret capital returns in balance-sheet context, MUST NOT penalize a company merely for a cash decline, MUST distinguish drawing down excess cash while remaining financially strong from materially increasing or deepening net debt to fund distributions, and MUST reuse the Feature 2A and 2B balance-sheet trajectory logic rather than introduce a separate leverage framework.
* **FR-019**: OwnerLens MUST surface ROIC context for retained capital as high or low ROIC context and improving or deteriorating ROIC, MUST NOT claim retained free cash flow earned the company-wide ROIC, and MUST NOT compute a return on retained free cash flow.
* **FR-020**: OwnerLens MUST keep two clear layers: reported capital-allocation fact normalization from SEC Company Facts, and a capital-allocation interpretation layer that consumes existing OwnerLens facts and metrics plus the new canonical facts; the interpretation layer MUST NOT make SEC calls directly.
* **FR-021**: OwnerLens MUST centralize the thresholds for material share-count shrinkage, material dilution, high SBC over free cash flow, meaningful repurchase activity over free cash flow, capital returns materially above free cash flow, and meaningful balance-sheet deterioration as named, documented values in one place, easy to inspect, avoiding false precision, and not tuned to make Adobe classify favorably.
* **FR-022**: OwnerLens MUST implement the interpretation as small deterministic functions and MUST NOT introduce a generic rules-engine framework, configurable scoring weights, investment-recommendation logic, LLM reasoning, or valuation dependencies.
* **FR-023**: OwnerLens MUST be able to produce a compact per-year Adobe capital-allocation view and a multi-year summary covering approximately the latest five completed fiscal years, showing the reported facts, derived metrics, buyback effectiveness, net cash or net debt, ROIC, the classification, and the ordered drivers.
* **FR-024**: The feature MUST preserve all existing Feature 1 (Slice 1A through 1E), Feature 2A, and Feature 2B behavior and regression tests.
* **FR-025**: The feature MUST remain limited to ADBE and to capital-allocation normalization and interpretation, and MUST NOT introduce repurchase-price-versus-value, total shareholder return, stock price, valuation, expected return, scenario analysis, acquisition ROI or accounting decomposition, goodwill analysis, debt issuance or repayment decomposition beyond existing balance-sheet context, incremental ROIC, scoring, screening, portfolio aggregation, agents, or Azure infrastructure. Acquisition cash spending is out of scope unless research finds a clean, unambiguous, economically interpretable concept.

### Key Entities

* **Capital-Allocation Concept Selection**: The documented preference order and qualifying criteria for each new reported concept, using full-year duration semantics.
* **Reported Capital-Allocation Observation**: One canonical annual value for repurchases, dividends paid, or SBC, with complete SEC provenance and its unit.
* **Repurchase Definition**: The explicit rule mapping Adobe's repurchase concept or concepts to cash spent buying common shares, avoiding double counting.
* **Dividend Definition**: The explicit rule selecting cash dividends actually paid, excluding declared, per-share, and accrued-but-unpaid metadata.
* **SBC Definition**: The explicit rule selecting reported stock-based compensation expense and whether it is total company SBC.
* **Derived Capital-Allocation Metric**: A calculated value such as repurchases over free cash flow, capital returned, capital returned over free cash flow, retained free cash flow, or SBC over free cash flow, marked as derived and referencing its inputs.
* **Buyback Effectiveness**: The deterministic interpretation relating repurchase spending to the actual diluted-share-count change.
* **Capital-Allocation Classification**: The deterministic per-year verdict, one of owner-friendly, balanced, questionable, owner-unfriendly, or insufficient-data.
* **Capital-Allocation Driver (Reason Code)**: A named, deterministic explanation contributing to a buyback-effectiveness interpretation or a capital-allocation classification.
* **Capital-Allocation Thresholds**: The centralized, named boundaries for share-count movement, SBC burden, repurchase activity, capital returns relative to free cash flow, and balance-sheet deterioration.
* **Capital-Allocation View and Summary**: The per-fiscal-year alignment for display and the multi-year owner-question summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid Adobe payload, each new reported fact returns one annual observation per completed fiscal year for approximately the latest five years, with no fiscal year duplicated.
* **SC-002**: In 100% of controlled cases containing interim or repeated comparative observations, no interim observation appears and each fiscal year is represented once with earliest-filed provenance.
* **SC-003**: In 100% of controlled missing-concept and explicit-zero cases, an absent concept is represented as unavailable and a reported zero is preserved distinctly, with no fabricated zero.
* **SC-004**: In 100% of controlled cases, repurchase spending is taken from the reported cash-outflow concept and never inferred from share-count or treasury-stock changes, and dividends reflect cash actually paid.
* **SC-005**: For every fiscal year with the required inputs, repurchases over free cash flow, dividends over free cash flow, SBC over free cash flow, capital returned, capital returned over free cash flow, and retained free cash flow equal their documented formulas, and each is omitted when a required input is unavailable.
* **SC-006**: In 100% of controlled cases where capital returned exceeds free cash flow, retained free cash flow is negative and preserved rather than clamped to zero.
* **SC-007**: In 100% of controlled buyback cases, the effectiveness interpretation matches the intended outcome from the centralized thresholds, using the actual diluted-share-count change as the primary ownership signal.
* **SC-008**: In 100% of controlled cases representing owner-friendly, balanced, questionable, and owner-unfriendly capital allocation, the classification matches the intended verdict.
* **SC-009**: In 100% of controlled cases, a cash decline while remaining financially strong is not treated as a balance-sheet deterioration, while deepening net debt to fund distributions is, using the reused Feature 2A and 2B trajectory logic.
* **SC-010**: For identical inputs, the classification, the buyback-effectiveness interpretation, and the ordered drivers are identical across repeated runs in 100% of cases.
* **SC-011**: The compact Adobe view and the multi-year summary are produced for approximately the latest five completed fiscal years, and the summary answers each owner question.
* **SC-012**: The interpretation layer performs no external calls, and the Adobe view is produced from already-retrieved data in under 2 seconds.
* **SC-013**: All existing Feature 1, Feature 2A, and Feature 2B tests continue to pass unchanged.
* **SC-014**: Review confirms the feature adds only capital-allocation normalization and interpretation for ADBE and introduces no out-of-scope valuation, scoring, acquisition-decomposition, screening, portfolio, agent, or infrastructure behavior.

## Assumptions

* The Feature 1 fundamentals and derived metrics, the Feature 2A annual snapshots, and the Feature 2B compounding view are available as trustworthy inputs and are consumed as-is.
* The interpretation layer reads existing OwnerLens outputs and the new canonical capital-allocation facts and performs no SEC retrieval or re-normalization.
* Adobe's actual repurchase, dividend, and SBC concepts are verified through research against live data before implementation, and canonical mappings are documented.
* Repurchase cash outflow is reported as a positive expenditure magnitude in the selected concept, and overlapping concepts are reconciled to avoid double counting; the actual reporting sign and concept are confirmed in research.
* "Approximately the latest five completed fiscal years" means up to five displayed years, and fewer when fewer completed years exist.
* Free cash flow, diluted shares, share-count growth, net cash or net debt, and ROIC come from the existing Feature 1 and Feature 2A outputs and are not recomputed here.
* The initial thresholds for share-count movement, SBC burden, repurchase activity, capital returns relative to free cash flow, and balance-sheet deterioration are documented first-pass values, deliberately imprecise, plausible for conventional companies, and not tuned to Adobe.
* Reason codes and drivers are deterministic and testable; exact code names may evolve but their behavior is fixed for given inputs.
* The capital-allocation classification summarizes observable outcomes, not management intent, and makes no valuation or intrinsic-value judgment.
* Economically valid negatives, such as negative retained free cash flow or net debt, are valid inputs and are not treated as malformed data.

## Dependencies

* The Feature 1 SEC Company Facts retrieval and annual duration normalization that supply the raw payload and the reuse machinery.
* The Feature 1 free cash flow, operating cash flow, CapEx, diluted-share, FCF-per-share, net cash or net debt, and ROIC outputs.
* The Feature 2A annual economic-value snapshots and balance-sheet trajectory logic, and the Feature 2B compounding view.
* Adobe's SEC US-GAAP concepts for common-stock repurchases, cash dividends paid, and stock-based compensation, and the XBRL period, unit, form, and accession metadata present in the payload.

## Scope Boundaries

The feature includes only ADBE normalization of common-stock repurchase cash outflows, cash dividends paid, and stock-based compensation; the explicit reported-fact meanings with absence and reported-zero distinctions; derivation of repurchases, dividends, and SBC over free cash flow, capital returned and its ratio, and retained free cash flow including negative results; a deterministic buyback-effectiveness interpretation from repurchase spending versus actual diluted-share-count change; a deterministic capital-allocation classification with ordered drivers; balance-sheet-context and ROIC-context interpretation reusing the Feature 2A and 2B trajectory logic; centralized named thresholds; the two-layer split of reported facts and interpretation with no SEC calls in the interpretation layer; and a compact per-year Adobe view with a multi-year owner-question summary.

The feature excludes repurchase-price-versus-intrinsic-value analysis, total shareholder return, stock price, valuation multiples, expected return, scenario analysis, acquisition ROI, acquisition-accounting or goodwill decomposition, debt issuance or repayment decomposition beyond existing balance-sheet context, incremental ROIC, return on retained free cash flow, a 0-to-100 capital-allocation score, configurable scoring weights, a generic rules-engine framework, investment-recommendation logic, screening, portfolio aggregation, multi-company support, agents, and Azure or other hosted infrastructure. Acquisition cash spending is excluded unless research finds a clean, unambiguous, economically interpretable concept.

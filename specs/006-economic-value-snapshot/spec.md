---
title: "Feature Specification: Annual Economic Value Snapshot"
description: Summarize each Adobe fiscal year's owner-oriented economics with a deterministic, transparent classification
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 2A: Annual Economic Value Snapshot."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Summarize Each Fiscal Year as an Economic Value Snapshot (Priority: P1)

As an OwnerLens user, I want each completed Adobe fiscal year summarized into a compact snapshot of owner-oriented signals so that I can see at a glance whether the year's per-share economics were strong, flat, or weak without re-reading every underlying metric.

**Why this priority**: The per-year snapshot is the headline outcome of the slice and the object every other capability attaches to. Without it there is no economic-value lens.

**Independent Test**: Provide the already-normalized Adobe fundamentals and derived metrics for a set of fiscal years, then verify that each completed fiscal year yields one snapshot carrying the expected owner-oriented level and change signals, each drawn from an existing input rather than recomputed from SEC facts.

**Acceptance Scenarios**:

1. **Given** normalized fundamentals and derived metrics for a set of completed fiscal years, **When** the snapshot view is produced, **Then** each fiscal year yields exactly one economic-value snapshot.
2. **Given** a fiscal year with all required inputs, **When** its snapshot is produced, **Then** it exposes the owner-oriented level signals (operating margin, FCF margin, ROIC, net cash or net debt) and change signals (revenue growth, operating-margin change, FCF growth, FCF-margin change, diluted-share growth, FCF per share, FCF-per-share growth, ROIC change).
3. **Given** the snapshot fields, **When** they are inspected, **Then** level signals and change signals remain conceptually distinct and no level is blended with a change into a single generic number.

---

### User Story 2 - Classify the Year with Transparent, Deterministic Drivers (Priority: P1)

As an OwnerLens user, I want each fiscal year classified as improving, stable, deteriorating, or insufficient-data, together with the explicit drivers behind that classification, so that I can trust and inspect the judgment rather than accept an opaque score.

**Why this priority**: The interpretable classification is the core learning objective of the slice; a classification without transparent reasons would violate the project's fact-versus-interpretation and traceability principles.

**Independent Test**: Provide crafted single-year inputs representing clearly improving, clearly deteriorating, and roughly stable economics, then verify each produces the expected classification and a deterministic set of named drivers explaining it.

**Acceptance Scenarios**:

1. **Given** a fiscal year whose per-share economics clearly strengthened, **When** it is classified, **Then** the classification is improving and the drivers name the positive signals responsible.
2. **Given** a fiscal year whose per-share economics clearly weakened, **When** it is classified, **Then** the classification is deteriorating and the drivers name the negative signals responsible.
3. **Given** a fiscal year whose signals are roughly unchanged, **When** it is classified, **Then** the classification is stable and the drivers reflect the lack of material movement.
4. **Given** identical inputs classified twice, **When** the drivers are compared, **Then** the classification and the ordered drivers are identical every time.

---

### User Story 3 - Weight Per-Share Economics Over Aggregate Growth (Priority: P1)

As an OwnerLens user, I want the classification to prioritize per-share economics over aggregate company growth so that a year is judged by what actually accrued to an owner rather than by headline size.

**Why this priority**: Distinguishing business growth from per-share economic growth is the central intuition the slice teaches and the reason a naive aggregate-growth reading is misleading.

**Independent Test**: Provide a year where aggregate free cash flow grows while free cash flow per share falls because of dilution, and a year where aggregate free cash flow is flat while per-share free cash flow rises because of share shrinkage, then verify the classification follows the per-share direction, not the aggregate direction.

**Acceptance Scenarios**:

1. **Given** a year with rising aggregate free cash flow but falling free cash flow per share driven by rising share count, **When** it is classified, **Then** the result reflects the per-share deterioration rather than the aggregate growth, and a driver identifies the dilution.
2. **Given** a year with flat aggregate free cash flow but rising free cash flow per share driven by a declining share count, **When** it is classified, **Then** the result reflects the per-share improvement, and a driver identifies the share-count decline.
3. **Given** a year with strong free cash flow per share growth but sharply deteriorating capital efficiency or materially worsening leverage, **When** it is classified, **Then** the result is not automatically improving, and a driver flags the offsetting deterioration.

---

### User Story 4 - Handle Missing and Insufficient Prior-Year Data Explicitly (Priority: P2)

As an OwnerLens user, I want years that lack the minimum comparison information to be marked insufficient-data instead of guessed, so that the earliest year and any year with a missing required input never produce a fabricated verdict.

**Why this priority**: Explicit unavailable semantics preserve financial integrity as interpretation is layered on top of trusted facts, consistent with the constitution's fail-loudly principle.

**Independent Test**: Provide the earliest displayed year with no prior year available, and separately a year missing an individual required metric, then verify each yields insufficient-data with unavailable change signals rather than substituted zeros.

**Acceptance Scenarios**:

1. **Given** the earliest displayed fiscal year with no prior-year baseline, **When** its snapshot is produced, **Then** comparison-based change signals are marked unavailable and the classification is insufficient-data.
2. **Given** a fiscal year missing an individual metric required by the classification rule, **When** it is classified, **Then** the result is insufficient-data and the missing input is not replaced by zero.
3. **Given** any unavailable change metric, **When** the snapshot is produced, **Then** it is represented as an explicit unavailable value and never as zero.

---

### User Story 5 - Inspect and Reuse Centralized, Named Thresholds (Priority: P2)

As an OwnerLens user, I want the boundaries between materially positive, roughly stable, and materially negative movements to be centralized, named, and documented so that I can inspect and later adjust the judgment without hunting through logic.

**Why this priority**: Named thresholds make the deterministic rules auditable and adjustable, and prevent false precision or Adobe-specific overfitting.

**Independent Test**: Locate the documented threshold definitions, then verify every classification boundary references a named threshold and that inputs just inside and just outside a boundary produce the expected side of the classification.

**Acceptance Scenarios**:

1. **Given** the threshold definitions, **When** they are inspected, **Then** each concept (materially positive growth, roughly stable, materially negative growth, margin expansion or contraction, capital-efficiency improvement or deterioration) is named and documented in one place.
2. **Given** an input value just above a materiality boundary and another just below it, **When** each is classified, **Then** the two land on the expected opposite sides of that boundary.

---

### User Story 6 - Review a Compact Owner-Oriented View for Adobe (Priority: P3)

As an OwnerLens user, I want a compact per-year view of Adobe's latest completed fiscal years with the owner-oriented signals, classification, and drivers so that I can validate the lens against a real company end to end.

**Why this priority**: The live validation view demonstrates the slice and confirms the deterministic layer behaves sensibly on real data, but it depends on the preceding stories.

**Independent Test**: Produce the view for Adobe across approximately the latest five completed fiscal years and confirm each row shows the owner-oriented signals and classification, with the earliest year correctly marked insufficient-data and per-year drivers displayed.

**Acceptance Scenarios**:

1. **Given** Adobe's normalized fundamentals and derived metrics, **When** the compact view is produced, **Then** it shows approximately the latest five completed fiscal years with revenue growth, operating-margin change, FCF growth, FCF-per-share growth, share-count growth, ROIC, ROIC change, net cash or net debt, and the classification for each year.
2. **Given** the compact view, **When** the earliest displayed year is inspected, **Then** it shows insufficient-data because comparison metrics require a prior year.
3. **Given** any classified year in the view, **When** it is inspected, **Then** its structured drivers are displayed and explain the classification.

### Edge Cases

* The earliest displayed fiscal year has no prior year, so every change-based signal is unavailable and the year is insufficient-data.
* Aggregate free cash flow rises while free cash flow per share falls because of dilution.
* Aggregate free cash flow is flat or falling while free cash flow per share rises because of share-count decline.
* Free cash flow per share growth is strong but capital efficiency collapses in the same year.
* Free cash flow per share growth is strong but leverage worsens materially (net cash turns to net debt or net debt deepens).
* Operating margin and free-cash-flow margin move in opposite directions in the same year.
* A single required input (for example ROIC, free cash flow per share, or a prior-year value) is missing for one year but present for adjacent years.
* A change signal is exactly at a materiality threshold boundary.
* A per-share value is available but the prior-year per-share value is not, so per-share growth is unavailable while the level is present.
* Two signals of opposite sign are both material, producing a mixed year that must resolve deterministically rather than arbitrarily.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST produce, for each completed Adobe fiscal year available from the existing normalized fundamentals and derived metrics, exactly one annual economic-value snapshot.
* **FR-002**: OwnerLens MUST derive every snapshot field from existing Feature 1 outputs and MUST NOT re-normalize SEC facts or introduce new external financial data unless a required existing metric is unavailable.
* **FR-003**: OwnerLens MUST NOT perform any SEC API call or other network access within the economic-value classification layer.
* **FR-004**: Each snapshot MUST include the fiscal year and the owner-oriented signals covering revenue growth, operating margin, operating-margin change, FCF growth, FCF margin, FCF-margin change, diluted-share growth, FCF per share, FCF-per-share growth, ROIC, ROIC change, and net cash or net debt.
* **FR-005**: OwnerLens MUST keep level signals (such as operating margin, FCF margin, ROIC, and net cash or net debt) conceptually distinct from change signals (such as revenue growth, FCF growth, FCF-per-share growth, share-count growth, margin change, and ROIC change), and MUST NOT blend a level and a change into a single generic number.
* **FR-006**: OwnerLens MUST classify each fiscal year as exactly one of improving, stable, deteriorating, or insufficient-data.
* **FR-007**: The classification MUST be produced by explicit, documented deterministic rules rather than an opaque or numeric composite score, and MUST NOT introduce a 0-to-100 economic-value score in this slice.
* **FR-008**: The classification rules MUST prioritize signals in a documented order that weights per-share economics above aggregate company growth, considering at least FCF-per-share growth, ROIC change and sustained ROIC level, operating-margin and FCF-margin direction, share-count change, revenue and aggregate FCF growth, and balance-sheet improvement or deterioration.
* **FR-009**: OwnerLens MUST NOT automatically classify a year as improving when strong FCF-per-share growth coincides with materially deteriorating capital efficiency or materially worsening leverage; such offsetting deterioration MUST be handled explicitly.
* **FR-010**: Each classification MUST include an ordered set of explicit, named drivers (reason codes or structured drivers) that identify why the year received its classification.
* **FR-011**: The classification and its drivers MUST be deterministic, so identical inputs always produce the identical classification and the identical ordered drivers.
* **FR-012**: OwnerLens MUST classify a year as insufficient-data when the minimum comparison information required by the documented rule is unavailable, including the earliest displayed year that lacks a prior-year baseline.
* **FR-013**: OwnerLens MUST represent every unavailable metric with explicit unavailable semantics and MUST NOT substitute zero for a missing change metric or any other missing input.
* **FR-014**: OwnerLens MUST centralize the thresholds that separate materially positive growth, roughly stable, and materially negative growth, as well as margin expansion or contraction and capital-efficiency improvement or deterioration, as named, documented values in one place.
* **FR-015**: The thresholds MUST be easy to inspect and change, MUST avoid false precision, and MUST NOT be tuned to make Adobe's history appear favorable.
* **FR-016**: OwnerLens MUST NOT introduce configurable scoring weights in this slice.
* **FR-017**: The economic-value interpretation layer MUST remain separate from the raw normalization and metric-calculation layers, consuming their outputs rather than re-implementing them.
* **FR-018**: OwnerLens MUST implement the interpretation as small composable functions rather than a rules-engine framework.
* **FR-019**: The classification rules MUST be economically intuitive and MUST NOT be overfit to Adobe's specific historical outcomes, so they can eventually apply to another conventional operating company.
* **FR-020**: OwnerLens MUST be able to produce a compact per-year view for Adobe covering approximately the latest five completed fiscal years, showing the owner-oriented signals, the classification, and the structured drivers for each year, with the earliest year correctly marked insufficient-data when comparison metrics are unavailable.
* **FR-021**: The feature MUST preserve all existing Feature 1 (Slice 1A through 1E) behavior and regression tests.
* **FR-022**: The feature MUST remain limited to ADBE and to the annual economic-value snapshot and classification, and MUST NOT introduce multi-year trend classification, valuation, scoring, screening, portfolio aggregation, agents, or Azure infrastructure.

### Key Entities

* **Economic Value Snapshot**: The per-fiscal-year record of owner-oriented signals, distinguishing level signals from change signals, plus the year's classification and drivers.
* **Level Signal**: A point-in-time economic characteristic of the year such as operating margin, FCF margin, ROIC, or net cash or net debt.
* **Change Signal**: A year-over-year movement such as revenue growth, FCF growth, FCF-per-share growth, share-count growth, operating-margin change, FCF-margin change, or ROIC change.
* **Economic Value Classification**: The deterministic verdict for the year, one of improving, stable, deteriorating, or insufficient-data.
* **Driver (Reason Code)**: A named, deterministic explanation contributing to the classification, such as a strong per-share growth signal, a share-count decline, capital-efficiency expansion, or an offsetting deterioration.
* **Classification Thresholds**: The centralized, named boundaries that define materially positive, roughly stable, and materially negative movements and the margin and capital-efficiency direction cutoffs.
* **Compact Owner-Oriented View**: The per-year presentation of the snapshots, classifications, and drivers for approximately Adobe's latest five completed fiscal years.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid set of Adobe normalized inputs, exactly one economic-value snapshot is produced per completed fiscal year, with no fiscal year duplicated or omitted.
* **SC-002**: In 100% of snapshots, level signals and change signals are separately identifiable, and no field blends a level with a change.
* **SC-003**: In 100% of controlled cases representing clearly improving, clearly deteriorating, and roughly stable economics, the classification matches the intended verdict.
* **SC-004**: In 100% of controlled cases where aggregate free cash flow and per-share free cash flow diverge, the classification follows the per-share direction and a driver identifies the share-count effect.
* **SC-005**: In 100% of controlled cases combining strong per-share growth with material capital-efficiency or leverage deterioration, the year is not classified improving without a driver flagging the deterioration.
* **SC-006**: In 100% of controlled cases lacking the minimum required comparison information, including the earliest displayed year, the classification is insufficient-data and no missing input is replaced by zero.
* **SC-007**: For identical inputs, the classification and the ordered drivers are identical across repeated runs in 100% of cases.
* **SC-008**: Every classification boundary references a named, centrally documented threshold, and inputs just inside and just outside each boundary land on the expected side in 100% of controlled boundary cases.
* **SC-009**: The compact Adobe view presents approximately the latest five completed fiscal years with the owner-oriented signals, classification, and drivers, and the earliest year shows insufficient-data when comparison metrics require a prior year.
* **SC-010**: The economic-value layer performs no external calls, and the compact Adobe view is produced from already-retrieved data in under 2 seconds.
* **SC-011**: All existing Feature 1 (Slice 1A through 1E) tests continue to pass unchanged.
* **SC-012**: Review confirms the feature adds only the annual economic-value snapshot and classification for ADBE and introduces no out-of-scope multi-year trend, valuation, scoring, screening, portfolio, agent, or infrastructure behavior.

## Assumptions

* The normalized fundamentals and derived metrics from Feature 1 (revenue, operating income and margin, net income, operating cash flow, CapEx, free cash flow and margin, diluted weighted-average shares, FCF per share, growth metrics, cash and short-term investments, total debt, net cash or net debt, total assets and equity, ROA, ROE, invested capital, NOPAT, and ROIC) are available as trustworthy inputs and are consumed as-is.
* The economic-value layer reads these existing outputs and performs no SEC retrieval or re-normalization.
* "Approximately the latest five completed fiscal years" means up to five displayed years, and fewer when fewer completed years exist.
* A meaningful year-over-year comparison requires the relevant prior-year value; when it is absent, the dependent change signal is unavailable rather than zero.
* Per-share economics are weighted more heavily than aggregate company growth in interpretation, per the documented signal priority.
* The initial thresholds for material growth, stability, margin direction, and capital-efficiency direction are chosen to be economically intuitive first-pass values, documented with rationale in research, deliberately imprecise, and not tuned to Adobe's outcomes.
* Reason codes and drivers are deterministic and testable; the exact code names may evolve but their behavior is fixed for given inputs.
* Classification is an interpretation layer clearly distinct from the underlying facts and metrics, consistent with the constitution's separation of deterministic facts from judgment.
* Economically valid negative values (for example negative net cash, negative growth) are valid inputs and are not treated as malformed data.

## Dependencies

* The Feature 1 normalized fundamentals and derived metrics that supply every snapshot input, including revenue, operating income and margin, free cash flow and margin, diluted shares, FCF per share and its growth, share-count growth, net cash or net debt, and ROIC and its change.
* The existing raw SEC Company Facts retrieval and annual normalization that Feature 1 already provides; this feature depends on their outputs only, not on their internals.
* The documented signal-priority order and first-pass thresholds established during research and planning before implementation.

## Scope Boundaries

The feature includes only the ADBE annual economic-value snapshot built from existing Feature 1 outputs; the explicit separation of level signals from change signals; a deterministic classification of each fiscal year as improving, stable, deteriorating, or insufficient-data; ordered, named drivers explaining each classification; per-share weighting above aggregate growth; explicit handling of years where strong per-share growth coincides with capital-efficiency or leverage deterioration; centralized, named, documented thresholds; explicit unavailable semantics for missing inputs and the earliest year; small composable interpretation functions kept separate from normalization and metric calculation; and a compact per-year Adobe validation view with drivers.

The feature excludes three-year and five-year CAGR, multi-year trend classification, incremental ROIC, stock price, valuation, market capitalization, expected return, bear/base/bull scenarios, buyback dollars, dividends, stock-based-compensation analysis, capital-allocation decomposition, a 0-to-100 economic-value score, configurable scoring weights, a rules-engine framework, screening, portfolio aggregation, multi-company support, agents, LLMs, prompts, databases, vector stores, and Azure or other hosted infrastructure.

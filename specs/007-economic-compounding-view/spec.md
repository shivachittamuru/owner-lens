---
title: "Feature Specification: Multi-Year Economic Compounding View"
description: Summarize approximately 3-year and 5-year per-share economic compounding for Adobe with a deterministic, transparent classification
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 2B: Multi-Year Economic Compounding View."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Summarize a Multi-Year Compounding Period (Priority: P1)

As an OwnerLens user, I want a compact multi-year view that summarizes how fast Adobe's economics compounded per share over a requested period so that I can judge long-run owner outcomes rather than a single year.

**Why this priority**: The multi-year compounding view is the headline outcome of the slice and the object every other capability attaches to. Without it there is no long-run economic lens.

**Independent Test**: Provide the already-normalized Adobe fundamentals and the annual economic-value snapshots for a set of fiscal years, request a period, and verify one compounding view is produced that carries the period bounds, the compounding rates, the start-to-end quality changes, the balance-sheet trajectory, and the annual-classification counts, each derived from existing inputs.

**Acceptance Scenarios**:

1. **Given** the normalized fundamentals and annual snapshots for a set of completed fiscal years, **When** a multi-year period is requested, **Then** one compounding view is produced for that period with its start fiscal year, end fiscal year, and interval count.
2. **Given** a period with the required endpoints, **When** the view is produced, **Then** it exposes revenue CAGR, aggregate free-cash-flow CAGR, free-cash-flow-per-share CAGR, diluted-share CAGR, the start and end and change of operating margin, free-cash-flow margin, ROIC, and net cash or net debt, and the counts of annual snapshots classified improving, stable, deteriorating, and insufficient-data.
3. **Given** the compounding rates and the start-to-end quality changes, **When** they are inspected, **Then** compounding rates (period growth) and level changes (start versus end) remain conceptually distinct.

---

### User Story 2 - Compute CAGR Correctly Over Fiscal-Year Intervals (Priority: P1)

As an OwnerLens user, I want every compounding rate computed with the standard CAGR formula over the correct number of fiscal-year intervals so that the compounding rates are mathematically honest.

**Why this priority**: A CAGR that uses the wrong exponent or fabricates a rate for an invalid case would silently corrupt the entire view and mislead the owner.

**Independent Test**: Provide endpoint values for a known number of fiscal-year intervals and verify each CAGR equals the standard formula using the interval count, and that missing, zero-beginning, negative-beginning, and sign-changing cases yield an explicit unavailable result rather than a fabricated number.

**Acceptance Scenarios**:

1. **Given** a five-observation series from the earliest to the latest fiscal year, **When** a CAGR is computed, **Then** the exponent denominator is the four fiscal-year intervals, not the five observations.
2. **Given** a valid positive beginning and ending value over a known interval count, **When** a CAGR is computed, **Then** it equals the ending value divided by the beginning value, raised to one over the interval count, minus one.
3. **Given** a missing beginning or ending value, a zero beginning value, a negative beginning value, or a sign change that makes standard CAGR inappropriate, **When** a CAGR is computed, **Then** the result is explicitly unavailable and no rate is fabricated.

---

### User Story 3 - Classify Multi-Year Compounding with Transparent Drivers (Priority: P1)

As an OwnerLens user, I want each period classified as strongly compounding, compounding, stable, deteriorating, or insufficient-data, together with the explicit drivers behind that classification, so that I can trust and inspect the long-run judgment rather than accept an opaque score.

**Why this priority**: The interpretable multi-year classification is the core learning objective of the slice; a classification without transparent reasons would violate the project's fact-versus-interpretation and traceability principles.

**Independent Test**: Provide crafted periods representing strongly compounding, moderately compounding, stable, and deteriorating economics, then verify each produces the expected classification and a deterministic ordered set of named drivers explaining it.

**Acceptance Scenarios**:

1. **Given** a period with strong free-cash-flow-per-share compounding, sustained high ROIC, and stable or improving margins, **When** it is classified, **Then** the classification is strongly compounding and the drivers name the responsible signals.
2. **Given** a period where revenue grows but free cash flow per share stagnates and ROIC falls, **When** it is classified, **Then** the classification is not strongly compounding and the drivers surface the offsetting weakness.
3. **Given** a period where free-cash-flow-per-share CAGR falls and ROIC declines, **When** it is classified, **Then** the classification is deteriorating even though revenue growth is positive.
4. **Given** identical inputs classified twice, **When** the drivers are compared, **Then** the classification and the ordered drivers are identical every time.

---

### User Story 4 - Weight Per-Share Compounding and Surface Its Sources (Priority: P1)

As an OwnerLens user, I want the classification to treat free-cash-flow-per-share CAGR as the primary measure of per-share compounding and to surface when that per-share result was driven mainly by share-count changes so that I understand the true source of the compounding.

**Why this priority**: Distinguishing aggregate business growth from per-share compounding, and seeing how buybacks or dilution shaped it, is the central intuition the slice teaches.

**Independent Test**: Provide a period where aggregate free cash flow declines materially while free-cash-flow-per-share CAGR is high because of aggressive share-count reduction, and a period where aggregate growth is strong but material dilution erodes the per-share result, then verify the classification surfaces the share-count effect rather than blindly rewarding or penalizing the headline.

**Acceptance Scenarios**:

1. **Given** a period with high free-cash-flow-per-share CAGR produced primarily by aggressive share-count reduction while aggregate free cash flow falls materially, **When** it is classified, **Then** the share-count-driven source and the aggregate decline are surfaced as drivers rather than the period being classified as excellent without qualification.
2. **Given** a period with strong aggregate growth accompanied by material dilution, **When** it is classified, **Then** the result is tempered and a driver identifies the dilution.
3. **Given** a period where aggregate free cash flow grows modestly but share reduction produces substantially better free-cash-flow-per-share growth, **When** it is classified, **Then** the owner-favorable per-share result and the share-count contribution are both surfaced.

---

### User Story 5 - Choose Deterministic Periods from Available Fiscal Years (Priority: P2)

As an OwnerLens user, I want the recent approximately three-year period and the longest supported approximately five-year period selected deterministically from the available canonical fiscal years so that I can compare recent momentum against longer-run economics without assuming a fixed history length.

**Why this priority**: Deterministic period selection makes the view reproducible and lets the user distinguish recent momentum from long-duration performance, but it depends on the core view and CAGR machinery.

**Independent Test**: Provide payloads with exactly five, more than five, and fewer than the required fiscal years, and verify the three-year and five-year period endpoints are chosen deterministically from canonical fiscal years and that an unsupported period yields an explicit insufficient-history result.

**Acceptance Scenarios**:

1. **Given** at least the required number of canonical fiscal years, **When** the recent three-year and longest five-year periods are requested, **Then** each period's start and end fiscal years are selected deterministically from the available canonical fiscal years.
2. **Given** fewer canonical fiscal years than a requested period needs, **When** that period is requested, **Then** the view reports insufficient history explicitly rather than fabricating endpoints.
3. **Given** the same payload requested twice, **When** the periods are selected, **Then** the endpoints are identical every time.

---

### User Story 6 - Reconcile Annual Consistency with the Multi-Year Verdict (Priority: P2)

As an OwnerLens user, I want the counts of the annual economic-value classifications within the period included in the view so that I can see whether the multi-year verdict rests on consistent annual improvement or on mixed annual economics.

**Why this priority**: Annual-consistency context makes the multi-year classification trustworthy and teaches that a period verdict is not merely an average of annual verdicts.

**Independent Test**: Provide a set of annual snapshots spanning the period and verify the view reports the number of years classified improving, stable, deteriorating, and insufficient-data, and that the multi-year classification is derived from period economics rather than by averaging the annual classifications.

**Acceptance Scenarios**:

1. **Given** the annual snapshots covering the period, **When** the view is produced, **Then** it reports the count of years classified improving, stable, deteriorating, and insufficient-data.
2. **Given** a period whose annual classifications are mixed, **When** the multi-year classification is produced, **Then** it is determined by the documented period rules and a driver reflects the annual consistency or its absence, not a simple average of annual verdicts.

---

### User Story 7 - Review the Compact Adobe Compounding View (Priority: P3)

As an OwnerLens user, I want a compact human-readable compounding view for Adobe over both the recent three-year and the longest five-year periods so that I can validate the lens against a real company end to end.

**Why this priority**: The live validation view demonstrates the slice and confirms the deterministic layer behaves sensibly on real data, but it depends on the preceding stories.

**Independent Test**: Produce the view for Adobe over the recent three-year and longest five-year periods and confirm each shows the compounding rates, the start-to-end quality changes, the balance-sheet trajectory, the annual-classification counts, the classification, and the ordered drivers.

**Acceptance Scenarios**:

1. **Given** Adobe's normalized fundamentals and annual snapshots, **When** the compact compounding view is produced for the recent three-year period, **Then** it shows revenue, free-cash-flow, free-cash-flow-per-share, and diluted-share CAGR, the start-to-end operating margin, FCF margin, ROIC, and net cash or net debt, the annual-classification counts, the classification, and the drivers.
2. **Given** sufficient history, **When** both the recent three-year and longest five-year views are produced, **Then** the user can compare recent momentum against longer-run economics.
3. **Given** a period lacking sufficient history, **When** the view is produced, **Then** it reports insufficient history rather than a fabricated result.

### Edge Cases

* A requested period needs more fiscal years than the canonical history provides.
* A CAGR endpoint value is missing at the start or the end of the period.
* A beginning value is zero, so the standard CAGR ratio is undefined.
* A beginning value is negative, or the value changes sign across the period, so a standard CAGR is economically or mathematically inappropriate.
* Free-cash-flow-per-share CAGR is high only because the share count shrank aggressively while aggregate free cash flow fell materially.
* Aggregate free cash flow grows strongly while material dilution erodes the per-share result.
* Revenue compounds while free cash flow per share stagnates and ROIC falls.
* The earliest year in the period is itself an insufficient-data annual snapshot.
* The annual classifications within the period are mixed rather than consistent.
* A three-year and a five-year period disagree because recent momentum differs from the longer-run trajectory.
* Net cash turns to net debt, or net debt deepens, across the period.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST produce, for a requested multi-year period, one deterministic compounding view carrying the start fiscal year, the end fiscal year, and the number of fiscal-year intervals.
* **FR-002**: OwnerLens MUST derive every field of the compounding view from existing Feature 1 fundamentals and Feature 2A annual snapshots and MUST NOT retrieve or re-normalize SEC facts, duplicate Feature 1 calculations, or introduce new external financial concepts.
* **FR-003**: OwnerLens MUST NOT perform any SEC API call or other network access within the compounding layer.
* **FR-004**: The compounding view MUST include revenue CAGR, aggregate free-cash-flow CAGR, free-cash-flow-per-share CAGR, and diluted-share CAGR.
* **FR-005**: The compounding view MUST include the start value, end value, and change for operating margin, free-cash-flow margin, ROIC, and net cash or net debt.
* **FR-006**: The compounding view MUST include the counts of annual economic-value snapshots within the period classified improving, stable, deteriorating, and insufficient-data.
* **FR-007**: OwnerLens MUST compute every CAGR with the standard formula, the ending value divided by the beginning value raised to one over the number of fiscal-year intervals, minus one, and MUST use the interval count and never the observation count as the exponent denominator.
* **FR-008**: OwnerLens MUST return an explicit unavailable CAGR, without fabricating a value, when a beginning or ending value is missing, the beginning value is zero, the beginning value is negative, or the value changes sign in a way that makes a standard CAGR economically or mathematically inappropriate.
* **FR-009**: OwnerLens MUST treat free-cash-flow-per-share CAGR as the primary measure of per-share economic compounding and MUST NOT claim it equals intrinsic-value CAGR.
* **FR-010**: OwnerLens MUST classify each period as exactly one of strongly compounding, compounding, stable, deteriorating, or insufficient-data.
* **FR-011**: The classification MUST be produced by explicit, documented deterministic rules rather than an opaque or weighted numeric score, and MUST NOT introduce a 0-to-100 score or configurable scoring weights.
* **FR-012**: The classification rules MUST prioritize signals in a documented order covering free-cash-flow-per-share CAGR, aggregate free-cash-flow CAGR relative to free-cash-flow-per-share CAGR, sustained or improving ROIC, operating-margin and free-cash-flow-margin direction, share-count CAGR, balance-sheet trajectory, and the consistency of the annual economic-value classifications.
* **FR-013**: OwnerLens MUST summarize multi-year economics through the documented period rules and MUST NOT derive the multi-year classification by averaging the annual Feature 2A classifications.
* **FR-014**: OwnerLens MUST NOT classify a period as strongly compounding when high free-cash-flow-per-share CAGR is produced primarily by aggressive share-count reduction while aggregate free cash flow falls materially; such a case MUST be surfaced explicitly.
* **FR-015**: OwnerLens MUST temper the classification of a period with strong aggregate growth accompanied by material dilution, and MUST classify a period with falling free-cash-flow-per-share CAGR and declining ROIC as deteriorating even when revenue growth is positive.
* **FR-016**: Each classification MUST include an ordered set of explicit, named drivers that identify why the period received its classification, including drivers for the strength of per-share compounding, the aggregate-versus-per-share relationship, share-count reduction or dilution, ROIC level and direction, margin direction, balance-sheet trajectory, and annual consistency.
* **FR-017**: The classification and its drivers MUST be deterministic, so identical inputs always produce the identical classification and the identical ordered drivers.
* **FR-018**: OwnerLens MUST classify a period as insufficient-data when the minimum information required by the documented rule, including the required CAGR endpoints, is unavailable.
* **FR-019**: OwnerLens MUST select the recent approximately three-year period and the longest supported approximately five-year period deterministically from the available canonical fiscal years, MUST NOT assume a fixed number of observations exists, and MUST report insufficient history explicitly when a requested period needs more fiscal years than are available.
* **FR-020**: OwnerLens MUST keep multi-year compounding concepts distinct from the annual snapshot concept, so the annual snapshot answers what happened in one year and the compounding view answers what compounded over a period.
* **FR-021**: OwnerLens MUST centralize the thresholds that separate strong, healthy, roughly flat, and declining per-share compounding, as well as meaningful margin change, meaningful ROIC change, and meaningful dilution or share shrinkage, as named, documented values in one place, easy to inspect and change, avoiding false precision, and not tuned to make Adobe classify favorably.
* **FR-022**: OwnerLens MUST implement the compounding layer as small deterministic functions for CAGR, start-to-end deltas, annual-classification counts, driver generation, and classification, and MUST NOT introduce a generic analytics framework, a rules-engine framework, or a scoring-and-weights framework.
* **FR-023**: OwnerLens MUST be able to produce a compact human-readable compounding view for Adobe over both the recent three-year and the longest five-year periods, showing the compounding rates, the start-to-end quality changes, the balance-sheet trajectory, the annual-classification counts, the classification, and the drivers.
* **FR-024**: The feature MUST preserve all existing Feature 1 (Slice 1A through 1E) and Feature 2A annual-snapshot behavior and regression tests.
* **FR-025**: The feature MUST remain limited to ADBE and to the multi-year compounding view and classification, and MUST NOT introduce capital-allocation dollar decomposition, repurchase or dividend or stock-based-compensation analysis, organic-versus-inorganic decomposition, incremental ROIC, intrinsic value, valuation, stock price, expected return, scenario analysis, scoring, screening, portfolio aggregation, agents, or Azure infrastructure.

### Key Entities

* **Economic Compounding View**: The per-period record of compounding rates, start-to-end quality changes, balance-sheet trajectory, annual-classification counts, the classification, and the ordered drivers.
* **Compounding Rate**: A period growth rate computed as a CAGR over the fiscal-year intervals, such as revenue CAGR, aggregate free-cash-flow CAGR, free-cash-flow-per-share CAGR, or diluted-share CAGR.
* **Start-to-End Quality Change**: The start value, end value, and difference of a level metric across the period, such as operating margin, free-cash-flow margin, ROIC, or net cash or net debt.
* **Annual Consistency Context**: The counts of annual economic-value snapshots within the period by classification.
* **Compounding Classification**: The deterministic period verdict, one of strongly compounding, compounding, stable, deteriorating, or insufficient-data.
* **Compounding Driver (Reason Code)**: A named, deterministic explanation contributing to the classification, such as strong per-share compounding, share-count reduction, material dilution, sustained high ROIC, or mixed annual economics.
* **Period Selection**: The deterministic choice of a period's start and end fiscal years from the available canonical fiscal years, including the recent three-year and longest five-year periods and the insufficient-history outcome.
* **Compounding Thresholds**: The centralized, named boundaries that define strong, healthy, roughly flat, and declining per-share compounding and the meaningful margin, ROIC, and share-count movements.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid set of Adobe inputs, exactly one compounding view is produced per requested period, carrying the correct start fiscal year, end fiscal year, and interval count.
* **SC-002**: In 100% of controlled cases, each CAGR equals the standard formula computed over the fiscal-year interval count, and a five-year span uses four intervals as the exponent denominator.
* **SC-003**: In 100% of controlled missing-endpoint, zero-beginning, negative-beginning, and sign-changing cases, the CAGR is explicitly unavailable and no rate is fabricated.
* **SC-004**: In 100% of controlled cases representing strongly compounding, moderately compounding, stable, and deteriorating economics, the classification matches the intended verdict.
* **SC-005**: In 100% of controlled cases where high free-cash-flow-per-share CAGR is driven by share-count reduction while aggregate free cash flow falls materially, the period is not classified strongly compounding and a driver surfaces the aggregate decline and share-count source.
* **SC-006**: In 100% of controlled cases combining strong aggregate growth with material dilution, the classification is tempered and a driver identifies the dilution.
* **SC-007**: In 100% of controlled cases with falling free-cash-flow-per-share CAGR and declining ROIC, the period is classified deteriorating even when revenue growth is positive.
* **SC-008**: For identical inputs, the classification and the ordered drivers are identical across repeated runs in 100% of cases.
* **SC-009**: In 100% of controlled cases lacking the required CAGR endpoints or sufficient history, the period reports insufficient-data or insufficient history explicitly rather than a fabricated result.
* **SC-010**: The view reports the counts of annual snapshots classified improving, stable, deteriorating, and insufficient-data for the period, and the multi-year classification is not a simple average of those annual classifications.
* **SC-011**: The compact Adobe view is produced for both the recent three-year and longest five-year periods, letting a user compare recent momentum against longer-run economics.
* **SC-012**: The compounding layer performs no external calls, and each Adobe compounding view is produced from already-retrieved data in under 2 seconds.
* **SC-013**: All existing Feature 1 (Slice 1A through 1E) and Feature 2A annual-snapshot tests continue to pass unchanged.
* **SC-014**: Review confirms the feature adds only the multi-year compounding view and classification for ADBE and introduces no out-of-scope decomposition, valuation, scoring, screening, portfolio, agent, or infrastructure behavior.

## Assumptions

* The Feature 1 fundamentals and derived metrics and the Feature 2A annual economic-value snapshots are available as trustworthy inputs and are consumed as-is.
* The compounding layer reads these existing outputs and performs no SEC retrieval or re-normalization.
* "Approximately a three-year period" and "approximately a five-year period" mean periods anchored on the available canonical fiscal years, with fewer years used when fewer exist and an explicit insufficient-history outcome when a period cannot be formed.
* The number of fiscal-year intervals for a CAGR is the count of year-over-year steps between the start and end observations, which is one fewer than the number of observations in the span.
* Free-cash-flow-per-share CAGR is the primary per-share compounding measure and is a major observable contributor to owner economic-value growth, not a claim of intrinsic-value CAGR.
* The initial thresholds for strong, healthy, flat, and declining compounding, meaningful margin and ROIC change, and meaningful dilution or share shrinkage are chosen to be economically intuitive first-pass values, documented with rationale in research, deliberately imprecise, plausible for conventional mature operating companies, and not tuned to Adobe's outcomes.
* Reason codes and drivers are deterministic and testable; the exact code names may evolve but their behavior is fixed for given inputs.
* The compounding classification is an interpretation layer clearly distinct from the underlying facts, metrics, and annual snapshots.
* Economically valid negatives, such as net debt or a declining rate, are valid inputs and are not treated as malformed data.

## Dependencies

* The Feature 1 normalized fundamentals and derived metrics that supply the CAGR endpoints and start-to-end level values, including revenue, free cash flow, free cash flow per share, diluted shares, operating margin, free-cash-flow margin, ROIC, and net cash or net debt.
* The Feature 2A annual economic-value snapshots that supply the annual classifications counted for the period.
* The existing raw SEC Company Facts retrieval and annual normalization that Feature 1 already provides; this feature depends on their outputs only, not on their internals.
* The documented signal-priority order and first-pass thresholds established during research and planning before implementation.

## Scope Boundaries

The feature includes only the ADBE multi-year economic compounding view built from existing Feature 1 metrics and Feature 2A annual snapshots; deterministic CAGR over fiscal-year intervals with explicit invalid-case handling; start-to-end quality and balance-sheet deltas; annual-classification counts; deterministic selection of the recent three-year and longest five-year periods with an explicit insufficient-history outcome; a deterministic classification of each period as strongly compounding, compounding, stable, deteriorating, or insufficient-data; ordered, named drivers surfacing per-share compounding strength, the aggregate-versus-per-share relationship, share-count reduction or dilution, ROIC level and direction, margin direction, balance-sheet trajectory, and annual consistency; centralized, named, documented thresholds; small deterministic functions kept distinct from the annual layer; and a compact per-period Adobe validation view over both periods.

The feature excludes capital-allocation dollar decomposition, repurchase spending, dividends, stock-based-compensation analysis, organic-versus-inorganic growth decomposition, incremental ROIC, intrinsic value, valuation multiples, stock price, expected return, bear/base/bull scenarios, a 0-to-100 score, configurable scoring weights, a generic analytics or rules-engine framework, screening, portfolio aggregation, multi-company support, agents, and Azure or other hosted infrastructure.

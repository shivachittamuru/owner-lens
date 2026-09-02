---
title: "Feature Specification: Adobe Core Owner Economics"
description: Normalize Adobe cash-generation and per-share facts and derive owner-economics metrics
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 1D: Adobe Core Owner Economics."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize Adobe's Core Cash-Generation and Per-Share Facts (Priority: P1)

As an OwnerLens user, I want Adobe's net income, operating cash flow, capital expenditures, and diluted weighted-average shares normalized into canonical annual series so that OwnerLens has the reported facts required to evaluate owner economics.

**Why this priority**: These four reported facts are the foundation for every derived owner-economics metric in this slice.

**Independent Test**: Provide a controlled Adobe Company Facts payload with annual, quarterly, and repeated observations for each concept, then verify one canonical full-year observation per recent fiscal year for each metric, with full provenance.

**Acceptance Scenarios**:

1. **Given** a raw Adobe Company Facts payload with full-year observations for each new concept, **When** normalization runs, **Then** each metric returns one canonical annual observation for each of approximately the latest five completed fiscal years.
2. **Given** annual and quarterly or year-to-date observations for a concept, **When** normalization runs, **Then** only full fiscal-year observations are selected and partial-period observations are excluded.
3. **Given** a later filing that repeats a prior fiscal year's value as a comparative, **When** normalization runs, **Then** each fiscal year appears exactly once and no year is duplicated.

---

### User Story 2 - Derive Owner-Economics Metrics (Priority: P1)

As an OwnerLens user, I want net margin, free cash flow, FCF margin, FCF per diluted share, and the annual growth rates derived deterministically so that I can see how the underlying business is compounding.

**Why this priority**: The derived owner-economics view is the headline outcome of the slice.

**Independent Test**: Provide aligned canonical inputs, then verify each derived metric equals its documented formula for every fiscal year where the required inputs exist, and is omitted where they do not.

**Acceptance Scenarios**:

1. **Given** a fiscal year with the required inputs, **When** metrics are derived, **Then** net margin, free cash flow, FCF margin, and FCF per diluted share equal their documented formulas and reference their inputs.
2. **Given** adjacent completed fiscal years, **When** growth is derived, **Then** annual FCF growth, FCF-per-share growth, and diluted-share growth compare the two years, and growth is omitted where a valid prior-year comparison does not exist.
3. **Given** a fiscal year whose revenue or diluted shares is zero or missing, **When** metrics are derived, **Then** the affected ratio is omitted explicitly and no invented, infinite, or undefined value is produced.

---

### User Story 3 - Correct Capital Expenditure and Diluted-Share Semantics (Priority: P1)

As an OwnerLens user, I want capital expenditures normalized to a positive expenditure amount and diluted weighted-average shares used for per-share economics so that free cash flow and per-share figures are financially correct.

**Why this priority**: Sign and share-concept mistakes silently corrupt free cash flow and per-share economics, defeating the purpose of the slice.

**Independent Test**: Using controlled payloads that reflect Adobe's actual CapEx sign and share concept, verify that free cash flow equals operating cash flow minus a positive CapEx amount and that the share value is weighted-average diluted shares, not point-in-time shares outstanding.

**Acceptance Scenarios**:

1. **Given** Adobe's reported capital expenditure facts, **When** CapEx is normalized, **Then** it is a canonical positive expenditure amount such that free cash flow equals operating cash flow minus CapEx.
2. **Given** Adobe's reported diluted weighted-average share facts, **When** shares are normalized, **Then** the canonical value represents weighted-average diluted shares for the fiscal year with units handled explicitly, not point-in-time shares outstanding.

---

### User Story 4 - Preserve Provenance and Fact-versus-Metric Distinction (Priority: P2)

As an OwnerLens user, I want every reported fact to carry full SEC provenance and every derived metric to be clearly marked as calculated so that the owner-economics view remains auditable.

**Why this priority**: Traceability and the fact-versus-metric distinction are governance obligations that keep a multi-metric view trustworthy.

**Independent Test**: Inspect a reported observation and confirm full provenance; inspect a derived metric and confirm it is distinguishable and references its inputs.

**Acceptance Scenarios**:

1. **Given** a normalized reported fact, **When** it is inspected, **Then** it exposes SEC concept, unit, period start and end dates, fiscal year, fiscal period, form, filing date, accession number, and value.
2. **Given** a derived metric, **When** it is inspected, **Then** it is distinguishable from a reported fact and references the fiscal year and inputs used to derive it.

---

### User Story 5 - Fail Explicitly on Ambiguous or Missing Facts (Priority: P3)

As an OwnerLens user, I want normalization to fail clearly when a reported fact cannot be determined unambiguously so that I never receive an invented or silently chosen value.

**Why this priority**: Explicit failure preserves financial integrity as the metric set grows.

**Independent Test**: Supply payloads with a missing concept and with conflicting distinct values for the same fiscal year, then verify each produces an explicit typed failure.

**Acceptance Scenarios**:

1. **Given** a payload with no recognized concept for a required reported fact, **When** normalization runs, **Then** it fails explicitly and produces no observation for that fact.
2. **Given** two conflicting full-year values for the same fiscal year that the rules cannot disambiguate, **When** normalization runs, **Then** it fails explicitly and identifies the unresolved fiscal year.

### Edge Cases

* A required concept is tagged differently across years, or more than one candidate concept is present.
* Capital expenditures are reported as a negative cash-flow amount in the source and must be normalized to positive.
* Diluted weighted-average shares are reported in a share unit that requires explicit scale handling.
* Point-in-time shares outstanding exist alongside weighted-average diluted shares and must not be substituted.
* Net income or free cash flow is negative in a fiscal year, which is economically valid.
* Revenue or diluted shares is zero for a year, so a ratio must be omitted.
* A metric is missing the earliest year, so its first available growth rate cannot be computed.
* Different metrics cover different sets of years, so alignment must be by economic fiscal year.
* A full-year period deviates slightly from 365 days because of a 52-to-53 week fiscal calendar.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST normalize canonical annual series for net income, operating cash flow, capital expenditures, and diluted weighted-average shares from Adobe's raw SEC Company Facts.
* **FR-002**: OwnerLens MUST reuse the existing canonical revenue and operating-income series rather than reimplementing them.
* **FR-003**: OwnerLens MUST identify each new reported concept using an explicit, documented preference order grounded in the concepts Adobe actually reports.
* **FR-004**: OwnerLens MUST NOT mix concepts within a single canonical series unless documented research proves mixing is necessary and financially correct.
* **FR-005**: OwnerLens MUST select only full fiscal-year observations and MUST exclude quarterly and year-to-date partial-period observations using explicit, testable period semantics.
* **FR-006**: OwnerLens MUST derive each observation's canonical fiscal year from the economic period end date and MUST NOT trust the raw XBRL `fy` field.
* **FR-007**: OwnerLens MUST preserve Adobe's 52-to-53 week fiscal-year behavior when identifying full-year periods.
* **FR-008**: OwnerLens MUST produce at most one canonical annual observation per fiscal year per metric and MUST target approximately the latest five completed fiscal years, returning fewer when fewer exist.
* **FR-009**: OwnerLens MUST collapse identical comparative observations deterministically while retaining original provenance, and MUST fail with a typed ambiguity error when distinct values for one fiscal year cannot be resolved by the existing explicit rules.
* **FR-010**: OwnerLens MUST NOT implement a general restatement policy silently.
* **FR-011**: OwnerLens MUST verify Adobe's actual capital expenditure source facts and MUST normalize capital expenditures into a canonical positive expenditure amount such that free cash flow equals operating cash flow minus capital expenditures.
* **FR-012**: OwnerLens MUST document whether the source capital expenditure value is presented as a positive or negative cash amount and MUST NOT rely on an unverified sign assumption.
* **FR-013**: OwnerLens MUST normalize diluted weighted-average shares used for the fiscal year's per-share economics, MUST handle the source unit and scale explicitly, and MUST NOT substitute point-in-time shares outstanding.
* **FR-014**: OwnerLens MUST preserve full provenance for every normalized reported fact, including SEC concept, unit, period start date, period end date, fiscal year, fiscal period, form, filing date, accession number, and value.
* **FR-015**: OwnerLens MUST derive net margin, free cash flow, FCF margin, and FCF per diluted share deterministically in application code from aligned canonical inputs, and MUST NOT source any derived metric externally when the underlying facts exist.
* **FR-016**: OwnerLens MUST derive net margin as net income divided by revenue, free cash flow as operating cash flow minus capital expenditures, FCF margin as free cash flow divided by revenue, and FCF per diluted share as free cash flow divided by diluted weighted-average shares.
* **FR-017**: OwnerLens MUST derive annual FCF growth, FCF-per-share growth, and diluted-share growth by comparing adjacent canonical completed fiscal years, and MUST omit a growth value where a valid prior-year comparison does not exist.
* **FR-018**: OwnerLens MUST align all reported and derived metrics by canonical economic fiscal year.
* **FR-019**: OwnerLens MUST handle missing or zero denominators explicitly and MUST NOT emit an invented, infinite, or undefined value.
* **FR-020**: OwnerLens MUST treat economically valid negative values, such as negative net income or free cash flow, as valid and MUST NOT treat them as malformed data.
* **FR-021**: OwnerLens MUST keep reported facts and derived metrics conceptually distinct so a consumer can tell a filed fact from a calculated metric.
* **FR-022**: OwnerLens MUST reuse the existing annual normalization primitive where its current semantics genuinely apply and MUST extend shared logic only when a concrete difference discovered in this slice requires it, without building a generalized financial-statement framework.
* **FR-023**: The feature MUST preserve all existing Slice 1A through 1C behavior and tests.
* **FR-024**: The feature MUST remain limited to ADBE and to the listed reported facts and derived owner-economics metrics, and MUST NOT add out-of-scope balance-sheet, capital-allocation, valuation, scoring, or multi-company behavior.

### Key Entities

* **Reported Fact Concept Selection**: The documented preference order and qualifying criteria for each new reported concept (net income, operating cash flow, capital expenditures, diluted weighted-average shares).
* **Annual Reported Observation**: One canonical full fiscal-year reported value with complete SEC provenance, including its unit.
* **Capital Expenditure Normalization**: The rule that converts the source capital expenditure fact into a canonical positive expenditure amount, with documented source sign.
* **Diluted Share Normalization**: The rule that selects weighted-average diluted shares and handles the source unit and scale.
* **Derived Owner-Economics Metric**: A calculated annual value such as net margin, free cash flow, FCF margin, or FCF per diluted share, marked as derived and referencing its inputs.
* **Annual Growth Metric**: A calculated year-over-year change for free cash flow, FCF per share, or diluted shares, omitted where no valid prior-year comparison exists.
* **Aligned Owner-Economics View**: The per-fiscal-year alignment of all reported facts and derived metrics for display and inspection.
* **Normalization Failure**: An explicit unsuccessful outcome identifying a missing concept or an unresolved fiscal-year conflict.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid Adobe payload, each new reported metric returns one observation per completed fiscal year for approximately the latest five years, with no fiscal year duplicated.
* **SC-002**: In 100% of controlled cases containing quarterly or year-to-date observations, no partial-period observation appears in any canonical series.
* **SC-003**: In 100% of controlled cases containing repeated comparative values, each fiscal year is represented exactly once with original provenance retained.
* **SC-004**: In 100% of controlled cases, free cash flow equals operating cash flow minus a positive capital expenditure amount, confirming correct CapEx sign normalization.
* **SC-005**: In 100% of controlled cases, the diluted-share value represents weighted-average diluted shares with units handled explicitly, and never point-in-time shares outstanding.
* **SC-006**: For every fiscal year with the required inputs, net margin, free cash flow, FCF margin, and FCF per diluted share equal their documented formulas, and each is omitted when a required input is missing or a denominator is zero.
* **SC-007**: Every annual growth value compares adjacent completed fiscal years, and growth is omitted for any year lacking a valid prior-year comparison.
* **SC-008**: A reviewer can reconcile 100% of reported observations to their source filing using the preserved provenance and can distinguish every derived metric as calculated.
* **SC-009**: In 100% of controlled missing-concept and unresolved-conflict cases, normalization fails explicitly and returns no invented or partial value.
* **SC-010**: All existing Slice 1A through 1C tests continue to pass unchanged.
* **SC-011**: The aligned owner-economics view for a valid payload is produced in under 2 seconds with no external calls during normalization or derivation.
* **SC-012**: Review confirms the feature adds only the listed reported facts and derived metrics for ADBE and introduces no out-of-scope balance-sheet, capital-allocation, valuation, scoring, multi-company, or generalized-framework behavior.

## Assumptions

* The raw Company Facts payload is the same unmodified structure produced by the Slice 1 SEC retrieval and consumed by the Slice 1B and 1C normalization.
* Adobe reports net income, operating cash flow, and capital expenditures in US dollars, and diluted weighted-average shares in a share unit whose scale is handled explicitly.
* A full fiscal-year observation is one whose reporting period spans an entire fiscal year, allowing for a 52-to-53 week fiscal calendar tolerance rather than exactly 365 days.
* Full-year observations are identified by full-year period semantics, not by recency of filing.
* "Approximately the latest five completed fiscal years" means up to five, and fewer when the payload provides fewer completed years.
* Identical repeated comparative values collapse to one observation; genuinely conflicting distinct values that the rules cannot disambiguate are a failure.
* Capital expenditures normalize to a positive expenditure amount, with the actual source sign verified through research before implementation.
* Diluted weighted-average shares, not shares outstanding, are used for per-share economics.
* Derived metrics are calculated in application code and are never sourced from an external precomputed value when the underlying facts exist.
* Negative net income or free cash flow is economically valid; only missing inputs or zero denominators suppress a dependent ratio.
* Normalization and derivation operate only on already-retrieved data and perform no network access.

## Dependencies

* The Slice 1 SEC Company Facts retrieval that supplies the raw payload and its provenance fields.
* The Slice 1B revenue and Slice 1C operating-income normalization and the shared annual normalization primitive that this slice reuses.
* Adobe's SEC US-GAAP concepts for net income, operating cash flow, capital expenditures, and diluted weighted-average shares, and the XBRL period, unit, form, and accession metadata present in the payload.

## Scope Boundaries

The feature includes only ADBE normalization of net income, operating cash flow, capital expenditures, and diluted weighted-average shares; reuse of canonical revenue and operating income; capital-expenditure sign normalization; diluted-share unit and semantic handling; deterministic derivation of net margin, free cash flow, FCF margin, FCF per diluted share, and the three adjacent-year growth metrics; economic-fiscal-year alignment; provenance preservation; the fact-versus-metric distinction; explicit failure and explicit omission behavior; and any small shared primitive change justified by a concrete difference discovered here.

The feature excludes cash and short-term investments, debt, total assets, total equity, return on invested capital, return on equity, invested capital, stock-based-compensation analysis, dividends, repurchases, capital-allocation scoring, valuation multiples, quarterly or trailing-twelve-month calculations, databases, Azure infrastructure, AI or agent integration, multi-company support, screening, stock scores, and any generalized financial-statement normalization framework.

---
title: "Feature Specification: Adobe Operating Income and Margin"
description: Normalize Adobe annual operating income and derive operating margin from canonical series
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 1C: normalize Adobe annual operating income and derive operating margin from canonical annual revenue and operating income."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce Adobe's Canonical Annual Operating Income Series (Priority: P1)

As an OwnerLens user, I want Adobe's raw SEC Company Facts turned into one canonical annual operating income observation per recent fiscal year so that OwnerLens covers a second income-statement metric with the same trustworthiness as revenue.

**Why this priority**: Operating income is the new reported fact this slice adds, and it is the prerequisite for the derived operating margin.

**Independent Test**: Provide a controlled Adobe Company Facts payload containing annual, quarterly, and repeated operating-income observations, then verify that exactly one full-year observation is produced for each recent completed fiscal year with correct values and provenance.

**Acceptance Scenarios**:

1. **Given** a raw Adobe Company Facts payload with full-year operating-income observations, **When** operating-income normalization runs, **Then** the result contains one canonical annual observation for each of approximately the latest five completed fiscal years.
2. **Given** annual and quarterly or year-to-date operating-income observations for the same concept, **When** normalization runs, **Then** only full fiscal-year observations are selected and partial-period observations are excluded.
3. **Given** a later filing that repeats a prior fiscal year's operating income as a comparative value, **When** normalization runs, **Then** each fiscal year appears exactly once and no year is duplicated.

---

### User Story 2 - Derive Annual Operating Margin (Priority: P1)

As an OwnerLens user, I want operating margin computed deterministically from canonical revenue and canonical operating income so that I get a derived ratio I can trust and trace to its two reported inputs.

**Why this priority**: The derived margin is the headline outcome of the slice and demonstrates separating reported facts from calculated metrics.

**Independent Test**: Provide aligned canonical revenue and operating-income series, then verify operating margin equals operating income divided by revenue for each fiscal year where both inputs exist, and is absent where either input is missing.

**Acceptance Scenarios**:

1. **Given** a fiscal year with both canonical revenue and canonical operating income, **When** operating margin is computed, **Then** the margin equals operating income divided by revenue for that year and identifies its two source observations.
2. **Given** a fiscal year with operating income but no canonical revenue, **When** operating margin is computed, **Then** no margin is produced for that year and the omission is explicit rather than silent.
3. **Given** a fiscal year whose canonical revenue is zero, **When** operating margin is computed, **Then** the operation handles the zero divisor explicitly and does not emit an invented or infinite margin.

---

### User Story 3 - Preserve Provenance and Fact-versus-Metric Distinction (Priority: P2)

As an OwnerLens user, I want each reported operating-income observation to carry full SEC provenance and each operating margin to be clearly marked as derived so that I never confuse a filed fact with a calculated ratio.

**Why this priority**: Traceability and the fact-versus-metric distinction are core governance obligations and make the two-metric result auditable.

**Independent Test**: Inspect an operating-income observation and confirm it exposes SEC concept, unit, period dates, fiscal year, fiscal period, form, filing date, accession number, and value; inspect a margin and confirm it is identified as derived and references its inputs.

**Acceptance Scenarios**:

1. **Given** a selected operating-income observation, **When** it is inspected, **Then** it exposes the originating SEC concept, unit, period start and end dates, fiscal year, fiscal period, form, filing date, accession number, and reported value.
2. **Given** a computed operating margin, **When** it is inspected, **Then** it is distinguishable from a reported fact and references the fiscal year, revenue input, and operating-income input used to derive it.

---

### User Story 4 - Fail Explicitly on Ambiguous or Missing Operating Income (Priority: P3)

As an OwnerLens user, I want operating-income normalization to fail clearly when it cannot be determined unambiguously so that I never receive an invented or silently chosen value.

**Why this priority**: Explicit failure preserves financial integrity as the metric set grows.

**Independent Test**: Supply payloads with no recognized operating-income concept, and with conflicting distinct values for the same fiscal year, then verify each produces an explicit typed failure rather than a value.

**Acceptance Scenarios**:

1. **Given** a payload with no recognized operating-income concept, **When** normalization runs, **Then** it fails explicitly and produces no operating-income observation.
2. **Given** two conflicting full-year operating-income values for the same fiscal year that the rules cannot disambiguate, **When** normalization runs, **Then** it fails explicitly and identifies the unresolved fiscal year.

### Edge Cases

* Operating income is reported under a different concept than expected, or the tagging changes across years.
* A prior fiscal year's operating income is repeated as a comparative figure in later filings.
* Full-year and quarterly operating-income observations share the same concept and unit.
* A fiscal-year duration deviates slightly from 365 days because of a 52-to-53 week fiscal calendar.
* Revenue exists for a year but operating income does not, or the reverse.
* Canonical revenue for a year is zero.
* Operating income is negative, producing a negative but valid margin.
* Fewer than five completed fiscal years of operating income exist in the payload.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST accept a raw SEC Company Facts payload for ADBE and produce a canonical annual operating income series from it.
* **FR-002**: OwnerLens MUST identify the operating-income concept using an explicit, documented preference order grounded in the concepts Adobe actually reports.
* **FR-003**: OwnerLens MUST NOT mix values from multiple operating-income concepts within one canonical series unless documented research demonstrates that doing so is required and safe.
* **FR-004**: OwnerLens MUST select only full fiscal-year operating-income observations and MUST exclude quarterly and year-to-date partial-period observations using explicit, testable period semantics.
* **FR-005**: OwnerLens MUST derive each observation's canonical fiscal year from the economic period end date and MUST NOT trust the raw XBRL `fy` field, consistent with the revenue slice.
* **FR-006**: OwnerLens MUST preserve Adobe's 52-to-53 week fiscal-year behavior when identifying full-year periods.
* **FR-007**: OwnerLens MUST produce at most one canonical annual operating-income observation per fiscal year and MUST target approximately the latest five completed fiscal years, returning fewer when fewer exist.
* **FR-008**: OwnerLens MUST collapse identical comparative operating-income observations deterministically and MUST fail with a typed ambiguity error when distinct values for one fiscal year cannot be resolved by the existing explicit rules.
* **FR-009**: OwnerLens MUST preserve full provenance for every selected operating-income observation, including SEC concept, unit, period start date, period end date, fiscal year, fiscal period, form, filing date, accession number, and reported value.
* **FR-010**: OwnerLens MUST reuse the existing canonical revenue normalization behavior rather than reimplementing revenue.
* **FR-011**: OwnerLens MUST align the operating-income and revenue series by economic fiscal year using consistent fiscal-year semantics.
* **FR-012**: OwnerLens MUST calculate operating margin as operating income divided by revenue in deterministic application code and MUST NOT retrieve or trust any precomputed operating-margin value from an external source.
* **FR-013**: OwnerLens MUST produce operating margin only for fiscal years where both canonical revenue and canonical operating income exist, and MUST omit the margin explicitly for other years.
* **FR-014**: OwnerLens MUST handle zero or missing revenue explicitly and MUST NOT emit an invented, infinite, or undefined margin.
* **FR-015**: OwnerLens MUST keep reported financial facts and derived metrics conceptually distinct so a consumer can tell a filed operating-income fact from a calculated margin.
* **FR-016**: OwnerLens MUST refactor shared normalization logic only where Slice 1C demonstrates concrete duplication with the revenue slice, and MUST NOT introduce a generalized financial-statement framework for speculative future metrics.
* **FR-017**: The feature MUST preserve all existing company-identity, raw-retrieval, and revenue-normalization behavior and their tests.
* **FR-018**: The feature MUST remain limited to ADBE and to operating income and operating margin; it MUST NOT add other metrics, scoring, valuation, persistence, or multi-company support.

### Key Entities

* **Operating Income Concept Selection**: The documented operating-income concept preference order and the criteria that qualify a concept as Adobe's annual operating income source.
* **Annual Operating Income Observation**: One canonical full fiscal-year operating-income value with complete SEC provenance.
* **Canonical Annual Operating Income Series**: The ordered set of operating-income observations, at most one per fiscal year, for the targeted recent fiscal years.
* **Operating Margin**: A derived annual ratio of operating income to revenue for a fiscal year, marked as calculated and referencing its two reported inputs.
* **Aligned Annual Metrics**: The per-fiscal-year alignment of canonical revenue, canonical operating income, and derived operating margin.
* **Normalization Failure**: An explicit unsuccessful outcome identifying whether the cause was a missing operating-income concept or an unresolved fiscal-year conflict.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid Adobe payload, operating-income normalization returns one observation per completed fiscal year for approximately the latest five years, with no fiscal year duplicated.
* **SC-002**: In 100% of controlled cases containing quarterly or year-to-date operating-income observations, no partial-period observation appears in the canonical series.
* **SC-003**: In 100% of controlled cases containing repeated comparative values, each fiscal year is represented exactly once through the documented deduplication rules.
* **SC-004**: For every fiscal year with both inputs, operating margin equals operating income divided by revenue, and no margin is produced when either input is missing or when revenue is zero.
* **SC-005**: A reviewer can reconcile 100% of operating-income observations to their source filing using the preserved concept, unit, period dates, fiscal year, fiscal period, form, filing date, and accession number, and can distinguish every margin as derived.
* **SC-006**: In 100% of controlled missing-concept and unresolved-conflict cases, operating-income normalization fails explicitly and returns no invented or partial value.
* **SC-007**: All existing Slice 1A and Slice 1B tests continue to pass unchanged.
* **SC-008**: The aligned two-metric result for a valid payload is produced in under 2 seconds with no external calls during normalization.
* **SC-009**: Review confirms the feature affects only ADBE operating income and operating margin and introduces no other metric, scoring, valuation, or persistence behavior, and no generalized metric framework.

## Assumptions

* The raw Company Facts payload is the same unmodified structure produced by the Slice 1 SEC retrieval and consumed by the Slice 1B revenue normalization.
* Adobe reports operating income in US dollars, and USD is the target unit for the canonical series, consistent with revenue.
* A full fiscal-year observation is one whose reporting period spans an entire fiscal year, allowing for a normal 52-to-53 week fiscal calendar tolerance rather than an exact 365 days.
* Full-year observations are identified by full-year period semantics, not by recency of filing, consistent with the revenue slice.
* "Approximately the latest five completed fiscal years" means up to five, and fewer when the payload provides fewer completed years.
* Identical repeated comparative values collapse to one observation; genuinely conflicting distinct values for a year that the rules cannot disambiguate are a failure.
* Operating margin is a derived metric computed in application code and is never sourced from an external precomputed value.
* Negative operating income yields a valid negative margin; only missing or zero revenue suppresses the margin.
* Normalization operates only on already-retrieved data and performs no network access.

## Dependencies

* The Slice 1 SEC Company Facts retrieval that supplies the raw payload and its provenance fields.
* The Slice 1B canonical revenue normalization that this slice reuses and aligns against.
* The SEC US-GAAP operating-income concepts and XBRL period, form, and accession metadata present in the payload.

## Scope Boundaries

The feature includes only Adobe operating-income concept selection, full fiscal-year observation identification, deterministic duplicate resolution, canonical operating-income series construction, provenance preservation, reuse of existing revenue normalization, economic-fiscal-year alignment of revenue and operating income, deterministic operating-margin calculation with explicit missing and zero-revenue handling, the fact-versus-metric distinction, and any small shared normalization primitive justified by concrete duplication.

The feature excludes gross profit, net income, operating cash flow, capital expenditures, free cash flow, share count, return on invested capital, scoring, generic support for all financial metrics, databases, Azure services, caching, AI or agent integration, valuation, multi-company support, any restatement policy beyond the established conservative ambiguity behavior, and any generalized financial-statement normalization framework.

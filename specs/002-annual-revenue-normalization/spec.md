---
title: "Feature Specification: Adobe Annual Revenue Normalization"
description: Produce a canonical annual revenue series for Adobe from raw SEC Company Facts
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 1B: normalize Adobe annual revenue from the raw SEC Company Facts payload."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce Adobe's Canonical Annual Revenue Series (Priority: P1)

As an OwnerLens user, I want Adobe's raw SEC Company Facts turned into one canonical annual revenue observation per recent fiscal year so that I can trust a clean annual revenue series before broader financial normalization exists.

**Why this priority**: This journey delivers the slice's core value and the learning objective of mapping SEC XBRL observations into a trustworthy canonical annual series.

**Independent Test**: Provide a controlled Adobe Company Facts payload containing annual, quarterly, and repeated observations, then verify that exactly one annual revenue observation is produced for each recent completed fiscal year with correct values.

**Acceptance Scenarios**:

1. **Given** a raw Adobe Company Facts payload with full-year 10-K revenue observations, **When** annual revenue normalization runs, **Then** the result contains one canonical annual observation for each of approximately the latest five completed fiscal years.
2. **Given** annual and quarterly or year-to-date observations for the same concept, **When** normalization runs, **Then** only full fiscal-year observations are selected and quarterly or partial-period observations are excluded.
3. **Given** a later 10-K that repeats a prior fiscal year's revenue as a comparative value, **When** normalization runs, **Then** each fiscal year appears exactly once and no year is duplicated.

---

### User Story 2 - Preserve Provenance for Every Observation (Priority: P2)

As an OwnerLens user, I want each canonical revenue observation to carry its full SEC provenance so that I can reconcile every value back to its source filing.

**Why this priority**: Traceability is required by OwnerLens governance and lets users verify the series rather than trust it blindly.

**Independent Test**: Inspect each produced observation and confirm it exposes the SEC concept, unit, start and end dates, fiscal year, fiscal period, form, filing date, accession number, and value drawn from the source payload.

**Acceptance Scenarios**:

1. **Given** a selected annual observation, **When** the result is inspected, **Then** it exposes the originating SEC concept, unit, period start and end dates, fiscal year, fiscal period, form, filing date, accession number, and reported value.
2. **Given** two source observations for one fiscal year that differ only by filing, **When** one is selected deterministically, **Then** the retained observation's provenance identifies the specific filing it came from.

---

### User Story 3 - Fail Explicitly on Ambiguous or Missing Revenue (Priority: P3)

As an OwnerLens user, I want normalization to fail clearly when annual revenue cannot be determined unambiguously so that I never receive an invented or silently chosen value.

**Why this priority**: Explicit failure enforces the fail-loudly principle and protects the integrity of the canonical series.

**Independent Test**: Supply payloads with no usable revenue concept, and with conflicting values for the same fiscal year that cannot be resolved by the selection rules, then verify each produces an explicit failure rather than a value.

**Acceptance Scenarios**:

1. **Given** a payload with no recognized US-GAAP revenue concept, **When** normalization runs, **Then** it fails explicitly and produces no revenue observation.
2. **Given** two conflicting full-year values for the same fiscal year that the selection rules cannot disambiguate, **When** normalization runs, **Then** it fails explicitly and identifies the unresolved fiscal year.
3. **Given** a payload where only quarterly observations exist for a fiscal year, **When** normalization runs, **Then** that year yields no annual observation and, if no year can be produced, the operation fails explicitly.

### Edge Cases

* Multiple US-GAAP revenue concepts appear across years as Adobe's tagging changes over time.
* The same fiscal year is reported in both an original 10-K and an amended filing.
* A prior fiscal year is repeated as a comparative figure in later annual filings.
* Full-year and quarterly observations share the same concept and unit.
* A fiscal-year duration deviates slightly from 365 days because of a 52-to-53 week fiscal calendar.
* Fewer than five completed fiscal years of revenue exist in the payload.
* Observations exist in a non-USD unit alongside USD.
* Two selectable observations for one year report different values.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST accept a raw SEC Company Facts payload for ADBE and produce a canonical annual revenue series from it.
* **FR-002**: OwnerLens MUST identify the appropriate US-GAAP revenue concept or concepts within the payload using an explicit, documented preference order.
* **FR-003**: OwnerLens MUST select only full fiscal-year observations and MUST exclude quarterly and year-to-date partial-period observations.
* **FR-004**: OwnerLens MUST distinguish annual observations from non-annual observations using explicit fiscal-period semantics rather than choosing the most recently filed value.
* **FR-005**: OwnerLens MUST produce at most one canonical annual revenue observation per fiscal year.
* **FR-006**: OwnerLens MUST target approximately the latest five completed fiscal years and MUST return fewer when the payload contains fewer completed fiscal years.
* **FR-007**: OwnerLens MUST resolve duplicate or repeated observations for a fiscal year deterministically using explicit, documented tie-breaking rules.
* **FR-008**: OwnerLens MUST preserve provenance for every selected observation, including SEC concept, unit, period start date, period end date, fiscal year, fiscal period, form, filing date, accession number, and reported value.
* **FR-009**: OwnerLens MUST select revenue observations reported in a single consistent currency unit and MUST NOT combine differing units into one series.
* **FR-010**: OwnerLens MUST fail explicitly when no recognized revenue concept is present, when a targeted fiscal year has conflicting values the rules cannot disambiguate, or when no annual observation can be determined.
* **FR-011**: OwnerLens MUST NOT invent, estimate, interpolate, or aggregate revenue values, and MUST NOT return a partial or silently chosen result after an unresolved ambiguity.
* **FR-012**: The selection and tie-breaking rules MUST be explicit and testable using controlled Company Facts payloads.
* **FR-013**: OwnerLens MUST treat the produced series as derived facts whose provenance links back to the specific source observations.
* **FR-014**: The feature MUST remain limited to ADBE and revenue; it MUST NOT normalize other metrics or generalize across all financial-statement concepts.

### Key Entities

* **Revenue Concept Selection**: The documented US-GAAP revenue concept preference order and the criteria that qualify a concept as Adobe's annual revenue source.
* **Annual Revenue Observation**: One canonical full fiscal-year revenue value with its complete SEC provenance.
* **Canonical Annual Revenue Series**: The ordered set of annual revenue observations, at most one per fiscal year, for the targeted recent fiscal years.
* **Normalization Failure**: An explicit unsuccessful outcome identifying whether the cause was a missing revenue concept, an unresolved fiscal-year conflict, or an inability to determine any annual observation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid Adobe payload, normalization returns one annual revenue observation per completed fiscal year for approximately the latest five years, with no fiscal year duplicated.
* **SC-002**: In 100% of controlled cases containing quarterly or year-to-date observations, no partial-period observation appears in the canonical series.
* **SC-003**: In 100% of controlled cases containing repeated prior-year comparative values or amended filings, each fiscal year is represented exactly once through the documented tie-breaking rules.
* **SC-004**: A reviewer can reconcile 100% of produced observations to their source filing using the preserved concept, unit, period dates, fiscal year, fiscal period, form, filing date, and accession number.
* **SC-005**: In 100% of controlled missing-concept and unresolved-conflict cases, normalization fails explicitly and returns no invented or partial value.
* **SC-006**: The full canonical annual series for a valid payload is produced in under 2 seconds without any external calls during normalization.
* **SC-007**: Review confirms the feature affects only ADBE revenue and introduces no other metric, scoring, persistence, or valuation behavior.

## Assumptions

* The raw Company Facts payload is the same unmodified structure produced by the Slice 1 SEC retrieval.
* Adobe reports revenue in US dollars, and USD is the target unit for the canonical series.
* A full fiscal-year observation is one whose reporting period spans an entire fiscal year, allowing for a normal 52-to-53 week fiscal calendar tolerance rather than an exact 365 days.
* Annual observations are identified by full-year fiscal-period semantics and 10-K form context, not by recency of filing.
* "Approximately the latest five completed fiscal years" means up to five, and fewer when the payload provides fewer completed years.
* When multiple filings report the same fiscal year with the same value, they are treated as one observation; genuinely conflicting values for a year that the rules cannot disambiguate are a failure.
* Normalization operates only on already-retrieved data and performs no network access.

## Dependencies

* The Slice 1 SEC Company Facts retrieval that supplies the raw payload and its provenance fields.
* The SEC US-GAAP revenue concepts and XBRL period, form, and accession metadata present in the payload.

## Scope Boundaries

The feature includes only Adobe revenue-concept selection, full fiscal-year observation identification, deterministic duplicate resolution, canonical annual series construction, provenance preservation, and explicit failure behavior.

The feature excludes operating income, cash flow, free cash flow, shares, scoring, databases, Azure services, AI or agent integration, generic financial-statement normalization across all metrics, valuation, and any support for tickers other than ADBE.

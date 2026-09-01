---
title: "Feature Specification: SEC Company Facts Retrieval"
description: Resolve Adobe's SEC identity and retrieve its raw Company Facts filing data
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement the first OwnerLens vertical slice: SEC company identity resolution and raw Company Facts retrieval for Adobe (ADBE)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Retrieve Adobe Company Facts (Priority: P1)

As an OwnerLens user, I want to request SEC Company Facts for ADBE so that I can inspect Adobe's authoritative raw filing data before financial normalization is introduced.

**Why this priority**: This journey establishes the complete SEC data-access path and delivers the learning objective of the first vertical slice.

**Independent Test**: Request ADBE with controlled SEC mapping and Company Facts responses, then verify that Adobe's identity and the complete, unnormalized Company Facts payload are available.

**Acceptance Scenarios**:

1. **Given** the SEC company mapping contains ADBE and the Company Facts source returns a valid Adobe payload, **When** a user requests ADBE, **Then** the result identifies Adobe by ticker, company name, and CIK and includes the complete raw Company Facts payload.
2. **Given** a valid Adobe Company Facts payload, **When** the result is inspected, **Then** facts, units, periods, filing references, and source concepts remain as supplied by the SEC without financial metric extraction, normalization, scoring, or inference.
3. **Given** the mapping source uses a case-insensitive representation of the requested ticker, **When** a user requests `adbe`, **Then** it resolves to the same Adobe identity as `ADBE`.

---

### User Story 2 - Resolve Adobe's SEC Identity (Priority: P2)

As an OwnerLens user, I want ADBE resolved through an SEC-supported company mapping so that the identity is authoritative and the CIK is not an invented or embedded business value.

**Why this priority**: Reliable identity resolution is required before any company filing data can be requested or trusted.

**Independent Test**: Supply a controlled SEC company mapping containing Adobe, request ADBE, and verify the returned ticker, company name, and CIK match the mapping.

**Acceptance Scenarios**:

1. **Given** an SEC-supported mapping entry for ADBE, **When** identity resolution is requested, **Then** the returned identity contains the mapping's ticker, company name, and CIK.
2. **Given** a mapping with no ADBE entry, **When** identity resolution is requested, **Then** the request fails explicitly and no identity or Company Facts data is invented.
3. **Given** a malformed mapping response, **When** identity resolution is requested, **Then** the request fails explicitly with a reason that distinguishes invalid source data from an absent ticker.

---

### User Story 3 - Understand Retrieval Failures (Priority: P3)

As an OwnerLens user, I want clear failures when SEC data cannot be obtained or trusted so that I never mistake missing, malformed, or partial data for verified financial facts.

**Why this priority**: Explicit failure behavior enforces OwnerLens's financial-integrity principle and makes external-data problems diagnosable.

**Independent Test**: Simulate network failures, unsuccessful source responses, and malformed Company Facts payloads, then verify that each request fails explicitly without returning a successful partial result.

**Acceptance Scenarios**:

1. **Given** the SEC mapping or Company Facts source cannot be reached, **When** ADBE is requested, **Then** the operation fails with a clear external-access error and does not return partial Company Facts data.
2. **Given** either SEC source returns an unsuccessful response, **When** ADBE is requested, **Then** the operation fails with source and response context sufficient to identify the failed stage.
3. **Given** the Company Facts response is malformed or lacks required company identity and facts structure, **When** ADBE is requested, **Then** the operation fails validation and does not present the response as verified Company Facts.

### Edge Cases

* The requested ticker uses lowercase or surrounding whitespace.
* The mapping is valid but does not contain ADBE.
* The mapping contains duplicate or conflicting ADBE identities.
* The mapping provides a CIK that needs leading-zero formatting for SEC retrieval.
* Adobe resolves successfully, but Company Facts retrieval fails.
* The SEC response is empty, not valid JSON, or has an unexpected top-level structure.
* The Company Facts identity conflicts with the resolved identity.
* The Company Facts payload contains no reported facts while remaining structurally valid.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST accept ADBE as the only supported company ticker for this feature and MUST explicitly reject an unsupported ticker.
* **FR-002**: OwnerLens MUST resolve ADBE through an SEC-supported company ticker or company mapping source.
* **FR-003**: OwnerLens MUST derive Adobe's CIK from the mapping response rather than embed the CIK as a business-logic constant.
* **FR-004**: OwnerLens MUST expose the resolved company identity with ticker, company name, and CIK.
* **FR-005**: OwnerLens MUST use the resolved CIK to request Adobe's Company Facts data from the SEC EDGAR source.
* **FR-006**: OwnerLens MUST identify itself appropriately to the SEC on every external request in accordance with SEC request requirements.
* **FR-007**: OwnerLens MUST expose the complete valid Company Facts JSON payload without extracting, renaming, aggregating, normalizing, scoring, estimating, or inferring financial metrics.
* **FR-008**: OwnerLens MUST preserve source-provided provenance within the raw payload, including concepts, units, periods, filing references, and accession identifiers when present.
* **FR-009**: OwnerLens MUST validate that mapping data includes an unambiguous ADBE identity with a usable ticker, company name, and CIK before requesting Company Facts.
* **FR-010**: OwnerLens MUST validate that Company Facts data is valid JSON, has the required Company Facts structure, and identifies the same company resolved from the mapping.
* **FR-011**: OwnerLens MUST fail explicitly when the ticker cannot be resolved, a source cannot be reached, a source returns an unsuccessful response, or a response is malformed or inconsistent.
* **FR-012**: OwnerLens MUST NOT return invented identity values, a fabricated financial fact, or a successful partial Company Facts result after any failure.
* **FR-013**: Verification MUST cover identity resolution, Company Facts request construction, payload validation, and failure behavior using controlled external responses rather than relying exclusively on live SEC availability.
* **FR-014**: The feature MUST remain limited to company identity and raw Company Facts retrieval; financial extraction, normalization, concept mapping, persistence, caching, hosted infrastructure, scores, and AI behavior are excluded.

### Key Entities

* **Company Identity**: The SEC-resolved organization, identified by ticker, company name, and CIK.
* **SEC Company Mapping**: The SEC-supported source that associates ADBE with Adobe's identity and CIK.
* **Raw Company Facts**: The complete SEC-supplied Company Facts JSON for the resolved CIK, including company metadata and source-reported facts without OwnerLens financial transformations.
* **Retrieval Failure**: An explicit unsuccessful outcome identifying whether resolution, external access, source response, payload validation, or identity consistency failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: In all controlled valid-response scenarios, requesting ADBE returns one identity containing ticker, company name, and CIK plus one complete Company Facts payload.
* **SC-002**: In 100% of controlled missing-mapping, network-failure, unsuccessful-response, malformed-response, and identity-conflict scenarios, the request fails explicitly without invented or partial successful values.
* **SC-003**: A reviewer can trace 100% of returned raw facts to the source-provided concepts, units, periods, and filing references present in the retrieved payload.
* **SC-004**: A user can complete the ADBE retrieval and begin inspecting Adobe's raw facts within 10 seconds under normal SEC availability and network conditions.
* **SC-005**: All required acceptance scenarios can be verified repeatedly without depending on a live SEC request, while one optional live check can confirm compatibility with the current SEC source.
* **SC-006**: Review confirms zero financial metric extraction, normalization, scoring, estimation, or AI-generated financial values in this feature.

## Assumptions

* The SEC-supported ticker or company mapping remains the authority for associating ADBE with Adobe's CIK.
* Ticker input is compared without case sensitivity and ignores surrounding whitespace.
* A conflicting duplicate ADBE mapping is considered malformed and causes explicit failure.
* A structurally valid Company Facts payload with no reported facts may be returned unchanged; OwnerLens does not infer missing facts.
* Live SEC availability is outside OwnerLens control, so repeatable verification uses representative controlled responses and treats live access as an optional compatibility check.
* The SEC's published fair-access and request-identification requirements apply to all retrievals.

## Dependencies

* Availability and continued compatibility of the SEC-supported company mapping source.
* Availability and continued compatibility of the SEC EDGAR Company Facts source.
* A configured application identity suitable for the SEC request User-Agent requirement.

## Scope Boundaries

The feature includes only ADBE identity resolution, Adobe Company Facts retrieval, raw-payload preservation, basic identity exposure, source-compliant request identification, validation, and explicit failure behavior.

The feature excludes financial metric extraction, fiscal-period normalization, XBRL concept mapping, databases, caching, Azure services, broad ticker support, financial scores, AI or agent integration, and user-interface design beyond a minimal validation path.

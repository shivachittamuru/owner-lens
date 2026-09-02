---
title: "Feature Specification: Generalize Company Identity and SEC Ticker Resolution"
description: Resolve any SEC-mapped U.S. ticker to a canonical company identity and retrieve its raw Company Facts
ms.date: 2026-09-02
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 3A: Generalize Company Identity and SEC Ticker Resolution. Remove the remaining ADBE-only company-identity constraints and make OwnerLens capable of resolving arbitrary U.S.-listed companies present in the SEC ticker mapping. Generalize company identity and raw SEC Company Facts retrieval only; do not yet generalize financial metric normalization across companies."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolve Any SEC-Mapped Ticker (Priority: P1)

As an OwnerLens user, I want to request any U.S.-listed company that the SEC ticker mapping recognizes so that I can resolve its authoritative SEC identity and inspect its raw Company Facts without being limited to Adobe.

**Why this priority**: Removing the single-company constraint at the SEC access layer is the entire purpose of this slice and unlocks every later multi-company capability.

**Independent Test**: Supply a controlled SEC mapping containing several companies, request a mapped ticker such as `V` or `COST`, and verify that the correct canonical identity and the complete unnormalized Company Facts payload are returned.

**Acceptance Scenarios**:

1. **Given** the SEC company mapping contains an entry for the requested ticker and the Company Facts source returns a valid payload for its CIK, **When** a user requests that ticker, **Then** the result identifies the company by canonical ticker, company name, and ten-digit CIK and includes the complete raw Company Facts payload.
2. **Given** a mapped ticker supplied in lowercase or with surrounding whitespace, **When** a user requests it, **Then** it resolves to the same canonical identity as its uppercase, trimmed form.
3. **Given** a valid Company Facts payload for a resolved company, **When** the result is inspected, **Then** facts, namespaces, units, periods, and filing references remain exactly as supplied by the SEC without financial metric extraction, normalization, scoring, or inference.
4. **Given** the SEC mapping contains Visa and Costco alongside Adobe, **When** a user requests `ADBE`, then `V`, then `COST`, **Then** each request resolves the matching company and retrieves that company's own Company Facts payload.

---

### User Story 2 - Preserve Adobe Behavior as a Regression Case (Priority: P2)

As an OwnerLens maintainer, I want Adobe's existing identity resolution and raw retrieval behavior to remain unchanged so that generalizing to multiple companies does not regress any established Feature 1 or Feature 2 outputs.

**Why this priority**: The existing Adobe pipeline is the reference implementation and validated baseline; multi-company support must not alter it.

**Independent Test**: Request ADBE through the generalized path with the same controlled Adobe responses used before this slice, and verify the resolved identity and raw payload semantics are identical to the prior behavior.

**Acceptance Scenarios**:

1. **Given** the generalized resolution path, **When** a user requests ADBE, **Then** the resolved identity contains Adobe's ticker, company name, and CIK exactly as before.
2. **Given** Adobe's raw Company Facts payload, **When** it is retrieved through the generalized path, **Then** the raw payload is preserved unchanged and remains suitable for the existing Adobe normalization and economic-value flows.
3. **Given** the existing SEC-client verification suite, **When** the generalization is applied, **Then** every previously passing Adobe check continues to pass.

---

### User Story 3 - Distinguish Resolution and Retrieval Failures (Priority: P3)

As an OwnerLens user, I want each way a lookup can fail to be reported as a distinct, explicit failure so that I never mistake a malformed ticker, an unmapped company, an unreachable source, or an inconsistent payload for verified data.

**Why this priority**: Explicit typed failures enforce OwnerLens's financial-integrity principle and keep external-data problems diagnosable as company coverage widens.

**Independent Test**: Simulate malformed ticker input, an unmapped ticker, an unavailable mapping, unavailable Company Facts, a malformed response, and an identity mismatch, then verify each produces its own explicit failure and never a partial success.

**Acceptance Scenarios**:

1. **Given** an empty or whitespace-only ticker, **When** a user requests it, **Then** the request fails as malformed input distinctly from an unmapped ticker.
2. **Given** a well-formed ticker that is absent from the SEC mapping, **When** a user requests it, **Then** the request fails explicitly as "not present in mapping" and no identity is invented.
3. **Given** the SEC mapping source cannot be reached or returns an unsuccessful or malformed response, **When** a user requests any ticker, **Then** the request fails with a reason that distinguishes an unavailable or malformed source from an absent ticker.
4. **Given** a resolved identity but Company Facts that are unreachable, malformed, or identify a different CIK than resolved, **When** a user requests that ticker, **Then** the request fails explicitly and does not return a partial company object or present the payload as verified.

### Edge Cases

- The requested ticker uses lowercase, mixed case, or surrounding whitespace.
- The mapping is valid but contains no entry for the requested ticker.
- The mapping contains duplicate or conflicting entries for the same ticker.
- The mapping provides a CIK that needs leading-zero formatting for SEC retrieval.
- The mapping entry lacks a usable company name or a valid CIK.
- A company resolves successfully, but its Company Facts retrieval fails.
- The SEC response is empty, not valid JSON, or has an unexpected top-level structure.
- The Company Facts CIK does not match the resolved identity's CIK.
- The Company Facts payload is structurally valid but reports no facts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: OwnerLens MUST resolve any ticker present in the SEC-supported company ticker mapping to that company's canonical identity, rather than accepting Adobe alone.
- **FR-002**: OwnerLens MUST NOT maintain a manual allow-list of supported tickers and MUST NOT embed any company's CIK as a business-logic constant.
- **FR-003**: OwnerLens MUST accept ticker input case-insensitively and ignore surrounding whitespace, canonicalizing the ticker to a single consistent form (uppercase).
- **FR-004**: OwnerLens MUST derive each company's CIK dynamically from the SEC mapping and format it as the SEC-required ten-digit, zero-padded value for Company Facts requests.
- **FR-005**: OwnerLens MUST expose a canonical company identity containing at least the canonical ticker, company name, and CIK; additional fields such as exchange or security title MAY be included only when directly supplied by the mapping and MUST NOT be inferred or fabricated.
- **FR-006**: OwnerLens MUST use the resolved CIK to retrieve the company's raw Company Facts from the SEC EDGAR Company Facts source.
- **FR-007**: OwnerLens MUST identify itself to the SEC on every external request in accordance with SEC request requirements.
- **FR-008**: OwnerLens MUST expose the complete valid Company Facts JSON payload unchanged, without extracting, renaming, aggregating, normalizing, scoring, estimating, or inferring financial metrics.
- **FR-009**: OwnerLens MUST validate that a mapping match yields exactly one unambiguous identity with a usable ticker, company name, and CIK before requesting Company Facts, and MUST fail explicitly on duplicate or conflicting entries.
- **FR-010**: OwnerLens MUST verify that the returned Company Facts identify the same CIK as the resolved identity and MUST confirm the expected top-level Company Facts structure before treating the payload as trusted.
- **FR-011**: OwnerLens MUST report distinct, typed, explicit failures for each of these conditions: malformed ticker input, ticker absent from the mapping, mapping source unavailable, Company Facts source unavailable, malformed SEC response, and company identity mismatch.
- **FR-012**: OwnerLens MUST NOT return an invented identity, a fabricated fact, or a partial company object after any resolution or retrieval failure.
- **FR-013**: OwnerLens MUST preserve Adobe's existing identity resolution and raw retrieval semantics unchanged, keeping every previously passing Adobe verification valid and leaving Adobe normalized fundamentals and economic-value outputs unaffected.
- **FR-014**: OwnerLens MUST limit this feature to company identity resolution and raw Company Facts retrieval; financial metric normalization, company-specific concept mappings, generic financial-statement logic, scoring, persistence, caching, hosted infrastructure, and AI behavior are excluded.
- **FR-015**: The command-line validation path MUST resolve each requested ticker and display at minimum the canonical ticker, company name, ten-digit CIK, the top-level Company Facts keys, and the namespaces available in the facts payload, without adding financial-analysis tables for newly supported companies.
- **FR-016**: Verification MUST cover ticker canonicalization, resolution of Adobe and additional companies, unmapped and malformed inputs, source-unavailability and malformed-response handling, identity-mismatch detection, and raw-payload preservation using controlled responses rather than relying exclusively on live SEC availability.

### Key Entities

- **Canonical Company Identity**: The SEC-resolved organization, identified by a canonical ticker, company name, and ten-digit CIK, with optional mapping-supplied fields such as exchange or security title.
- **SEC Company Ticker Mapping**: The SEC-supported source that associates tickers with company names and CIKs for arbitrary U.S.-listed companies.
- **Raw Company Facts**: The complete SEC-supplied Company Facts JSON for a resolved CIK, including company metadata and source-reported facts, exposed without OwnerLens financial transformations.
- **Resolution Failure**: An explicit, typed unsuccessful outcome identifying which stage failed — malformed input, absent ticker, unavailable mapping, unavailable facts, malformed response, or identity mismatch.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In controlled valid-response scenarios, requesting each of ADBE, V, and COST returns one canonical identity with ticker, company name, and ten-digit CIK plus one complete Company Facts payload for the matching company.
- **SC-002**: In 100% of controlled malformed-input, unmapped-ticker, unavailable-mapping, unavailable-facts, malformed-response, and identity-mismatch scenarios, the request fails explicitly with a distinct failure type and returns no partial or invented result.
- **SC-003**: A user can request a mapped ticker in any casing or with surrounding whitespace and receive the same canonical identity in 100% of cases.
- **SC-004**: Adobe's identity resolution and raw payload remain byte-for-byte equivalent to the pre-slice behavior, and 100% of previously passing Adobe verifications continue to pass.
- **SC-005**: A reviewer can trace 100% of returned raw facts to the source-provided concepts, units, periods, and filing references present in the retrieved payload, with zero financial metric extraction, normalization, or scoring introduced by this feature.
- **SC-006**: All required acceptance scenarios can be verified repeatedly without a live SEC request, while an optional live check confirms that ADBE, V, and COST resolve and retrieve raw facts against the current SEC source.
- **SC-007**: A user can complete resolution and begin inspecting a company's raw facts within 10 seconds under normal SEC availability and network conditions.

## Assumptions

- The SEC-supported company ticker mapping (for example, `company_tickers.json`) remains the authority for associating tickers with company names and CIKs.
- Ticker input is compared without case sensitivity and with surrounding whitespace ignored; the canonical form is uppercase.
- Duplicate or conflicting mapping entries for one ticker are treated as malformed and cause explicit failure rather than an arbitrary pick.
- A structurally valid Company Facts payload with no reported facts may be returned unchanged; OwnerLens does not infer missing facts.
- Fetching the SEC ticker mapping per client or session invocation is acceptable in this slice; no persistent caching or database is introduced. If the current implementation already reuses the mapping safely within one client instance, that behavior is preserved.
- The synchronous SEC access model is retained unless concrete evidence requires a change; no asynchronous concurrency, retry framework, provider registry, or other speculative architecture is introduced.
- Live SEC availability is outside OwnerLens control, so repeatable verification uses representative controlled responses and treats live access as an optional compatibility check.
- The SEC's published fair-access and request-identification requirements apply to all retrievals.

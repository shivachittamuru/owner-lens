---
title: "Feature Specification: Generalize Financial Metric Normalization Across Companies"
description: Represent canonical OwnerLens financial metrics consistently across multiple companies with transparent, traceable concept mappings
ms.date: 2026-09-02
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 3B: Generalize Financial Metric Normalization Across Companies. Remove Adobe-only restrictions from OwnerLens financial normalization and establish a trustworthy canonical metric-definition layer that can support multiple conventional U.S. operating companies. Initial validation companies: ADBE, V, COST. Generalize Feature 1 normalization; leave Feature 2 interpretation unchanged."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize Core Financials for Multiple Companies (Priority: P1)

As an OwnerLens user, I want the core annual financial metrics normalized consistently for any conventional U.S. operating company whose facts OwnerLens can resolve, so that I can build the same owner-economics and capital-efficiency inputs for companies beyond Adobe.

**Why this priority**: Removing the Adobe-only normalization gate and defining canonical, company-independent metric meanings is the core purpose of this slice and unlocks every later multi-company capability.

**Independent Test**: Provide controlled Company Facts for ADBE, V, and COST, request the core canonical metrics, and verify each metric returns the correct canonical annual series with the expected meaning and unit, or an explicit unsupported result, without any ticker allow-list.

**Acceptance Scenarios**:

1. **Given** resolvable Company Facts for a validation company, **When** a user requests a canonical metric such as revenue or operating cash flow, **Then** OwnerLens returns the canonical annual series with correct fiscal-year derivation, unit, and provenance, regardless of which company was requested.
2. **Given** the three validation companies, **When** a user requests the core metric set (revenue, operating income, net income, operating cash flow, capital expenditures, diluted weighted-average shares, cash, debt, total assets, total equity, and the tax inputs needed for NOPAT/ROIC where supported), **Then** each metric is either successfully normalized with canonical meaning or explicitly reported as unsupported with a documented reason.
3. **Given** a company for which a required metric's canonical representation cannot be determined, **When** the metric is requested, **Then** OwnerLens reports it as unsupported and never substitutes a fabricated or zero value.

---

### User Story 2 - Map Differing Source Concepts Transparently (Priority: P2)

As an OwnerLens user, I want each canonical metric to record which underlying source concept and company produced it, so that consistent economic meaning across companies never hides the fact that different companies report through different source concepts.

**Why this priority**: Different companies express the same economic concept through different SEC XBRL tags; transparent, per-metric overrides with preserved provenance are what make cross-company normalization trustworthy rather than a set of hidden hacks.

**Independent Test**: For a company whose valid representation differs from the default concept preference, request the affected metric and verify the returned observation preserves the actual selected source concept and identifies the company-specific mapping used.

**Acceptance Scenarios**:

1. **Given** a company whose default concept preference does not yield the correct canonical meaning, **When** the metric is normalized, **Then** an explicit, documented company-specific mapping is applied and the result records the actual source concept selected.
2. **Given** any normalized observation, **When** a user inspects it, **Then** the canonical metric name, the actual source concept, the company, and the source filing context are all distinguishable.
3. **Given** the set of company-specific mappings, **When** a reviewer audits them, **Then** every mapping is explicit, minimal, scoped to one canonical metric, and traceable to observed SEC facts rather than inferred from company name or industry.

---

### User Story 3 - Preserve Adobe Behavior as a Regression Baseline (Priority: P2)

As an OwnerLens maintainer, I want Adobe's existing normalized series, owner-economics, capital-efficiency, and capital-allocation outputs to remain identical, so that generalizing normalization does not silently change any established result.

**Why this priority**: Adobe is the validated reference implementation; the generalized metric layer must not alter which Adobe concepts are selected or any downstream Feature 1 or Feature 2 output.

**Independent Test**: Run the existing Adobe normalization and economic-value paths through the generalized layer and verify every previously passing result and value is unchanged.

**Acceptance Scenarios**:

1. **Given** the generalized metric layer, **When** Adobe's core metrics are normalized, **Then** the selected source concepts, values, fiscal years, and provenance match the pre-slice results exactly.
2. **Given** Adobe's downstream owner-economics, capital-efficiency, capital-allocation, and economic-value outputs, **When** they are recomputed through the generalized layer, **Then** every value is unchanged.
3. **Given** the existing Adobe verification suite, **When** the generalization is applied, **Then** every previously passing check continues to pass, unless a previously incorrect Adobe result is discovered and explicitly documented.

---

### User Story 4 - Distinguish Applicable, Non-Applicable, and Unsupported Metrics (Priority: P3)

As an OwnerLens user, I want a clear distinction between a metric that is successfully normalized, a metric that is economically non-applicable to a company, and a metric that OwnerLens cannot yet represent reliably, so that I never mistake absence or uncertainty for a real value.

**Why this priority**: Across companies, structural absence (for example, no dividend program) and unreliable representation (for example, conflicting debt concepts) are different outcomes, and conflating either with zero would corrupt downstream economics.

**Independent Test**: Craft companies with a structurally absent concept and with conflicting concepts, then verify the first yields an explicit absent result and the second yields an explicit unsupported failure, neither producing a fabricated value.

**Acceptance Scenarios**:

1. **Given** a company that structurally lacks a concept such as a dividend program, **When** that metric is requested, **Then** OwnerLens reports it as absent or non-applicable rather than zero.
2. **Given** a company whose facts present conflicting or irreconcilable representations of a metric, **When** that metric is requested, **Then** OwnerLens fails explicitly or reports the metric as unsupported and does not guess a value.
3. **Given** a balance sheet that exposes financial assets not equivalent to corporate excess cash, **When** cash plus short-term investments is normalized, **Then** OwnerLens does not broaden the canonical meaning to absorb those assets, and instead applies a narrow justified mapping or reports the limitation.

### Edge Cases

- A company reports the same economic concept under a different source concept than the default preference.
- A company reports revenue or operating income through a concept whose name is similar but whose economic meaning differs.
- A company's balance sheet includes financial or settlement assets that must not be counted as corporate short-term investments.
- A company's debt is presented through concepts that risk double counting a current portion already included in a broader debt concept.
- A metric is structurally absent because the company does not engage in that activity.
- Multiple conflicting representations of a metric cannot be reconciled.
- A source concept exists but reports in an unexpected unit or sign.
- A required tax input for NOPAT/ROIC is missing for one company but present for others.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: OwnerLens MUST define canonical, company-independent financial metric definitions for the metrics it currently uses, each describing the intended economic concept, expected fact kind (duration or instant), expected unit, an ordered default source-concept preference, and any simple canonical sign semantics.
- **FR-002**: OwnerLens MUST remove the Adobe-only normalization gate so normalization accepts any company identity for which a trustworthy canonical representation of the requested metric can be resolved.
- **FR-003**: OwnerLens MUST NOT replace the Adobe restriction with a manual allow-list of tickers; the validation companies are golden targets, not a hard-coded supported universe.
- **FR-004**: "Unsupported" MUST mean OwnerLens cannot currently determine a trustworthy canonical representation of the requested metric for the company, and MUST NOT mean the ticker was not added to a list.
- **FR-005**: OwnerLens MUST support narrow, explicit, per-company concept overrides scoped to a single canonical metric, applied only when a company's valid representation differs from the default preference.
- **FR-006**: Every company-specific override MUST be explicit, minimal, documented, deterministic, and traceable to observed SEC facts rather than inferred from company name or industry.
- **FR-007**: OwnerLens MUST avoid ticker-specific conditionals scattered through normalization logic; company-specific mappings MUST be expressed as declarative data associated with the canonical metric.
- **FR-008**: OwnerLens MUST preserve the existing separate normalization paths for duration facts and instant facts and MUST NOT merge them into a single generic selector.
- **FR-009**: OwnerLens MUST preserve existing normalization semantics: economic fiscal-year derivation from the period end, full-year filtering, 52/53-week handling, repeated-comparative deduplication, explicit ambiguity failures, and unit validation.
- **FR-010**: Every normalized observation MUST preserve the actual selected source concept together with the canonical metric name, the company, and the source filing context, so canonicalization never hides which concept was used.
- **FR-011**: OwnerLens MUST distinguish a successfully normalized metric, an economically non-applicable or structurally absent metric, and a metric it cannot yet represent reliably, and MUST NOT silently interpret absence or conflict as zero.
- **FR-012**: OwnerLens MUST NOT broaden a canonical metric definition solely because a source concept has a similar name; economic meaning MUST take precedence over tag-name similarity.
- **FR-013**: OwnerLens MUST preserve the canonical cash-plus-short-term-investments meaning as corporate liquid cash and short-term investments, and MUST NOT absorb financial assets that are not equivalent to excess corporate cash; where the definition cannot be represented consistently, it MUST apply a narrow justified override or report the limitation rather than broaden incorrectly.
- **FR-014**: OwnerLens MUST preserve the canonical debt meaning as interest-bearing current debt plus interest-bearing long-term debt, MUST NOT count accounts payable, general current liabilities, settlement obligations, or other non-debt operating liabilities, and MUST avoid double counting a current portion already included in a broader debt concept.
- **FR-015**: OwnerLens MUST provide a canonical metric request path that does not require downstream callers to know source concept names; callers request canonical OwnerLens metrics and receive canonical results.
- **FR-016**: OwnerLens MUST preserve all existing Adobe normalized series, owner-economics, capital-efficiency, capital-allocation, and Feature 2 outputs unchanged, and the generalized registry MUST NOT change which Adobe concepts are selected, unless a previously incorrect Adobe result is discovered and explicitly documented.
- **FR-017**: OwnerLens MUST document, before finalizing the design, a concise per-metric compatibility matrix across ADBE, V, and COST recording which source concept exists, which concept is selected, whether the default works, whether an override is needed, and any absence, unit, or sign differences.
- **FR-018**: The feature MUST limit itself to generalizing Feature 1 normalization; it MUST NOT change Feature 2 interpretation, add persistence, hosted infrastructure, agents, scoring, screeners, comparison interfaces, external configuration formats, generic taxonomy ingestion, or international-accounting support.
- **FR-019**: Verification MUST cover metric resolution, multi-company normalization, semantics, and Adobe regression using controlled facts rather than relying exclusively on live SEC availability.

### Key Entities

- **Canonical Metric Definition**: A company-independent description of an economic concept OwnerLens uses, including its name, fact kind (duration or instant), expected unit, ordered default source-concept preference, and any canonical sign semantics.
- **Company-Specific Override**: An explicit, minimal mapping that, for one company and one canonical metric, replaces or refines the default source-concept preference, traceable to observed SEC facts.
- **Normalized Observation**: A canonical annual value that retains provenance — canonical metric name, actual source concept, company, unit, fiscal year, and source filing context.
- **Metric Coverage Outcome**: The per-company, per-metric result classifying a metric as successfully normalized, non-applicable or structurally absent, or unsupported with a documented reason.
- **Compatibility Matrix**: The documented cross-company record of which source concepts exist and are selected for each canonical metric across the validation companies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For each of ADBE, V, and COST, every metric in the core set is either successfully normalized with correct canonical meaning and a traceable source concept, or explicitly reported as unsupported with a documented reason — with zero fabricated or silently zeroed values.
- **SC-002**: 100% of Adobe normalized series, owner-economics, capital-efficiency, capital-allocation, and Feature 2 outputs remain unchanged, and every previously passing Adobe verification continues to pass.
- **SC-003**: 100% of company-specific overrides are individually documented and traceable to observed SEC facts, and no ticker-specific conditional appears scattered through normalization logic.
- **SC-004**: 100% of normalized observations expose the actual selected source concept alongside the canonical metric name, so a reviewer can distinguish canonical meaning from source concept for every value.
- **SC-005**: A concise compatibility matrix covering the core metrics across all three validation companies is available and identifies, for each metric, whether the default concept works and whether an override is used.
- **SC-006**: In all controlled non-applicable and conflicting-representation scenarios, OwnerLens reports absence or unsupported explicitly in 100% of cases and never returns a guessed value.
- **SC-007**: All required verification can be performed repeatably without a live SEC request, while an optional live check confirms coverage for ADBE, V, and COST against the current SEC source.

## Assumptions

- The three validation companies are conventional U.S. operating companies used as golden targets; the mechanism must generalize beyond them without hard-coding them as the supported universe.
- Company identity resolution and raw Company Facts retrieval are already generalized (prior slice); this slice consumes resolved raw facts and does not change identity resolution.
- Feature 2 economic-value interpretation is unchanged in this slice and will be validated comprehensively across companies in a later slice.
- Canonical metric definitions exist only for metrics OwnerLens currently uses; no general accounting ontology is introduced.
- A small declarative Python data structure for canonical definitions and overrides is sufficient; no plugin system, provider registry, inheritance hierarchy, configuration database, or external rules format is introduced.
- Live SEC research on ADBE, V, and COST informs concept selection and overrides before the design is finalized; mappings are never guessed from company names or industry.
- Where a metric cannot yet be represented correctly for one validation company, the slice surfaces it explicitly and documents the gap rather than weakening the canonical definition.
- The SEC's published fair-access and request-identification requirements apply to any live validation.

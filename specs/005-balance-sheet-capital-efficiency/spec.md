---
title: "Feature Specification: Adobe Balance Sheet and Capital Efficiency"
description: Normalize Adobe fiscal-year-end balance-sheet facts and derive capital-efficiency metrics
ms.date: 2026-09-01
ms.topic: reference
---

**Feature Branch**: `main`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 1E: Adobe Balance Sheet and Capital Efficiency."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize Adobe's Fiscal-Year-End Balance-Sheet Facts (Priority: P1)

As an OwnerLens user, I want Adobe's cash, short-term investments, total debt, total assets, and total stockholders' equity normalized as fiscal-year-end instant observations so that OwnerLens has the point-in-time facts required for capital-efficiency analysis.

**Why this priority**: These instant balance-sheet facts are the foundation for every derived capital-efficiency metric and introduce the instant-versus-duration distinction.

**Independent Test**: Provide a controlled Adobe Company Facts payload with instant year-end, quarterly, and repeated observations for each concept, then verify one canonical fiscal-year-end observation per recent fiscal year for each fact, with full provenance.

**Acceptance Scenarios**:

1. **Given** a raw Adobe Company Facts payload with fiscal-year-end instant observations for each balance-sheet concept, **When** normalization runs, **Then** each fact returns one canonical year-end observation for each of approximately the latest five completed fiscal years.
2. **Given** instant observations at both interim quarter ends and the fiscal-year end for the same concept, **When** normalization runs, **Then** only the fiscal-year-end observation is selected and interim observations are excluded.
3. **Given** a later filing that repeats a prior fiscal-year-end value as a comparative, **When** normalization runs, **Then** each fiscal-year-end appears exactly once and no year is duplicated.

---

### User Story 2 - Distinguish Instant Facts from Duration Facts (Priority: P1)

As an OwnerLens user, I want balance-sheet instant facts handled by explicit end-date semantics separate from duration facts so that point-in-time and period facts are never conflated.

**Why this priority**: Applying duration selection rules to instant facts would silently select the wrong observations and corrupt every downstream metric.

**Independent Test**: Provide a payload mixing instant year-end facts and duration facts, then verify instant normalization selects by period-end date without a duration window and duration normalization is unaffected.

**Acceptance Scenarios**:

1. **Given** an instant balance-sheet fact with no start date, **When** instant normalization runs, **Then** it is selected by its fiscal-period-end date rather than by a period duration.
2. **Given** duration income and cash-flow facts, **When** balance-sheet normalization runs, **Then** those duration facts are not selected as balance-sheet observations, and the existing duration normalization continues to work unchanged.

---

### User Story 3 - Derive Capital-Efficiency Metrics (Priority: P1)

As an OwnerLens user, I want cash plus short-term investments, net cash or net debt, ROA, ROE, invested capital, NOPAT, and ROIC derived deterministically so that I get OwnerLens's first trustworthy view of how efficiently the business uses capital.

**Why this priority**: The capital-efficiency view is the headline outcome of the slice.

**Independent Test**: Provide aligned canonical balance-sheet and income inputs, then verify each derived metric equals its documented formula for every fiscal year where the required inputs exist, and is omitted where they do not.

**Acceptance Scenarios**:

1. **Given** a fiscal year with the required inputs, **When** metrics are derived, **Then** cash plus short-term investments, net cash or net debt, ROA, ROE, invested capital, NOPAT, and ROIC equal their documented formulas and reference their inputs.
2. **Given** a fiscal year that requires a beginning balance for an average-balance denominator, **When** the prior fiscal-year-end balance is unavailable, **Then** the affected average-based metric is omitted for that year rather than substituting the ending balance.
3. **Given** a fiscal year whose average total equity or average invested capital is zero, **When** metrics are derived, **Then** the affected ratio is omitted explicitly and no invented, infinite, or undefined value is produced.

---

### User Story 4 - Preserve Provenance and Fact-versus-Metric Distinction (Priority: P2)

As an OwnerLens user, I want every reported balance-sheet observation to carry full SEC provenance and every derived capital-efficiency metric to be clearly marked as calculated so that the view remains auditable.

**Why this priority**: Traceability and the fact-versus-metric distinction keep a multi-input capital-efficiency view trustworthy.

**Independent Test**: Inspect a balance-sheet observation and confirm full provenance including the instant period-end date; inspect a derived metric and confirm it is distinguishable and references its inputs.

**Acceptance Scenarios**:

1. **Given** a normalized balance-sheet observation, **When** it is inspected, **Then** it exposes SEC concept, unit, fiscal-period-end date, fiscal year, fiscal period, form, filing date, accession number, and value.
2. **Given** a derived capital-efficiency metric, **When** it is inspected, **Then** it is distinguishable from a reported fact and references the fiscal year and inputs used to derive it.

---

### User Story 5 - Fail Explicitly on Ambiguous or Missing Facts (Priority: P3)

As an OwnerLens user, I want balance-sheet normalization to fail clearly when a fact cannot be determined unambiguously so that I never receive an invented or silently chosen value.

**Why this priority**: Explicit failure preserves financial integrity as the metric set grows into the balance sheet.

**Independent Test**: Supply payloads with a missing concept and with conflicting distinct values for the same fiscal-year-end, then verify each produces an explicit typed failure.

**Acceptance Scenarios**:

1. **Given** a payload with no recognized concept for a required balance-sheet fact, **When** normalization runs, **Then** it fails explicitly and produces no observation for that fact.
2. **Given** two conflicting fiscal-year-end values for the same fiscal year that the rules cannot disambiguate, **When** normalization runs, **Then** it fails explicitly and identifies the unresolved fiscal year.

### Edge Cases

* Adobe reports cash and short-term investments as separate concepts, so combining them must avoid double counting.
* Total debt must be assembled from current and non-current components, and unrelated liabilities must be excluded.
* A balance-sheet concept is tagged differently across years, or more than one candidate concept is present.
* The same fiscal-year-end value is repeated as a comparative in later filings.
* A fiscal-year-end value is restated to a different value in a later filing, creating a genuine conflict.
* The earliest displayed year lacks a prior fiscal-year-end baseline for an average-balance denominator.
* Total equity is zero or negative in a fiscal year.
* Pretax income or income tax expense is missing, so the effective tax rate cannot be derived.
* An interim quarter-end instant observation shares the concept with the fiscal-year-end observation.
* A fiscal-year-end date reflects a 52-to-53 week fiscal calendar.

## Requirements *(mandatory)*

### Functional Requirements

* **FR-001**: OwnerLens MUST normalize canonical fiscal-year-end series for cash and cash equivalents, short-term investments where applicable, total debt, total assets, and total stockholders' equity from Adobe's raw SEC Company Facts.
* **FR-002**: OwnerLens MUST treat balance-sheet facts as instant observations and MUST select them using explicit fiscal-period-end-date semantics rather than duration-window rules.
* **FR-003**: OwnerLens MUST keep instant balance-sheet normalization distinct from the existing duration-based annual normalization, and MUST NOT merge them into a single engine that obscures the accounting distinction.
* **FR-004**: OwnerLens MUST prefer fiscal-year-end observations associated with annual 10-K reporting and MUST exclude interim quarter-end observations.
* **FR-005**: OwnerLens MUST derive each observation's canonical fiscal year from the economic period-end date and MUST NOT trust the raw XBRL `fy` field.
* **FR-006**: OwnerLens MUST produce at most one canonical fiscal-year-end observation per fiscal year per balance-sheet fact and MUST target approximately the latest five completed fiscal years, returning fewer when fewer exist.
* **FR-007**: OwnerLens MUST collapse identical repeated comparative observations deterministically while retaining earliest-filed provenance, and MUST fail with a typed ambiguity error when distinct values for one fiscal-year-end cannot be resolved by the existing explicit rules.
* **FR-008**: OwnerLens MUST NOT implement a broad restatement policy silently.
* **FR-009**: OwnerLens MUST identify Adobe's actual concepts for cash and short-term investments, MUST define canonical cash plus short-term investments explicitly, and MUST avoid double counting when a combined concept and separate concepts are both present.
* **FR-010**: OwnerLens MUST define total debt explicitly from Adobe's current and non-current debt concepts, MUST compute it deterministically when assembled from multiple components while preserving the provenance of every input, and MUST exclude unrelated liabilities.
* **FR-011**: OwnerLens MUST preserve full provenance for every selected balance-sheet observation, including SEC concept, unit, fiscal-period-end date, fiscal year, fiscal period, form, filing date, accession number, and value.
* **FR-012**: OwnerLens MUST reuse the existing canonical operating-income and net-income series rather than reimplementing them.
* **FR-013**: OwnerLens MUST derive cash plus short-term investments and net cash or net debt deterministically, where net cash or net debt is cash plus short-term investments minus total debt.
* **FR-014**: OwnerLens MUST derive return on assets as net income divided by average total assets, where average total assets is the mean of the beginning and ending fiscal-year-end balances, and MUST omit ROA for a year whose beginning balance is unavailable rather than substituting ending assets.
* **FR-015**: OwnerLens MUST derive return on equity as net income divided by average total equity, where average total equity is the mean of the beginning and ending fiscal-year-end balances, and MUST handle zero or negative equity explicitly with documented behavior.
* **FR-016**: OwnerLens MUST derive invested capital using a documented, reproducible initial definition appropriate for Adobe, MUST document the treatment of excess cash rather than assuming all cash is excess, and MUST preserve the definition in research.
* **FR-017**: OwnerLens MUST derive NOPAT as operating income multiplied by one minus a normalized tax rate, using a documented, simplest-defensible initial tax-rate approach, preferring a reported effective tax rate from income tax expense divided by pretax income when valid.
* **FR-018**: OwnerLens MUST derive return on invested capital as NOPAT divided by average invested capital, using the mean of beginning and ending fiscal-year-end invested capital when available, and MUST NOT use ending invested capital alone unless research explicitly justifies that simplification.
* **FR-019**: OwnerLens MAY fetch one additional historical fiscal-year-end balance as a calculation-only baseline for average denominators while displaying only the latest five years.
* **FR-020**: OwnerLens MUST handle missing or zero denominators explicitly across all derived metrics and MUST NOT emit an invented, infinite, or undefined value.
* **FR-021**: OwnerLens MUST treat economically valid negative values as valid and MUST NOT treat them as malformed data.
* **FR-022**: OwnerLens MUST keep reported balance-sheet facts and derived capital-efficiency metrics conceptually distinct so a consumer can tell a filed fact from a calculated metric.
* **FR-023**: OwnerLens MUST introduce only the smallest reusable primitive needed for fiscal-year-end instant facts, justified by concrete duplication across cash, debt, assets, and equity, and MUST NOT build a generalized accounting ontology.
* **FR-024**: The feature MUST preserve all existing Slice 1A through 1D behavior and tests.
* **FR-025**: The feature MUST remain limited to ADBE and to the listed balance-sheet facts and capital-efficiency metrics, and MUST NOT add out-of-scope adjustments, scoring, valuation, or multi-company behavior.

### Key Entities

* **Balance-Sheet Concept Selection**: The documented preference order and qualifying criteria for each balance-sheet concept, using instant fiscal-year-end semantics.
* **Instant Fiscal-Year-End Observation**: One canonical point-in-time balance-sheet value at a fiscal-year-end date, with complete SEC provenance and its unit.
* **Cash Position Definition**: The explicit rule combining cash and short-term investments without double counting.
* **Total Debt Definition**: The explicit rule assembling total debt from current and non-current components with preserved input provenance.
* **Invested Capital Definition**: The documented initial definition of invested capital, including excess-cash treatment.
* **Tax-Rate Definition**: The documented initial effective-tax-rate approach used for NOPAT.
* **Derived Capital-Efficiency Metric**: A calculated value such as net cash, ROA, ROE, invested capital, NOPAT, or ROIC, marked as derived and referencing its inputs.
* **Baseline Balance**: One additional historical fiscal-year-end balance retained only to compute average denominators, not displayed.
* **Aligned Capital-Efficiency View**: The per-fiscal-year alignment of balance-sheet facts and derived metrics for display and inspection.
* **Normalization Failure**: An explicit unsuccessful outcome identifying a missing concept or an unresolved fiscal-year-end conflict.

## Success Criteria *(mandatory)*

### Measurable Outcomes

* **SC-001**: For a valid Adobe payload, each balance-sheet fact returns one fiscal-year-end observation per completed fiscal year for approximately the latest five years, with no fiscal year duplicated.
* **SC-002**: In 100% of controlled cases containing interim quarter-end observations, no interim observation appears in any fiscal-year-end series.
* **SC-003**: In 100% of controlled cases containing repeated comparative fiscal-year-end values, each fiscal year is represented exactly once with earliest-filed provenance retained.
* **SC-004**: In 100% of controlled cases, cash plus short-term investments avoids double counting and total debt equals the documented sum of its components.
* **SC-005**: For every fiscal year with the required inputs, ROA, ROE, invested capital, NOPAT, and ROIC equal their documented formulas, and each is omitted when a required input, beginning baseline, or non-zero denominator is unavailable.
* **SC-006**: In 100% of controlled earliest-year cases lacking a prior fiscal-year-end baseline, average-based metrics are omitted rather than computed from ending balances alone.
* **SC-007**: A reviewer can reconcile 100% of balance-sheet observations to their source filing using the preserved provenance, including the instant period-end date, and can distinguish every derived metric as calculated.
* **SC-008**: In 100% of controlled missing-concept and unresolved-conflict cases, normalization fails explicitly and returns no invented or partial value.
* **SC-009**: All existing Slice 1A through 1D tests continue to pass unchanged.
* **SC-010**: The aligned capital-efficiency view for a valid payload is produced in under 2 seconds with no external calls during normalization or derivation.
* **SC-011**: Review confirms the feature adds only the listed balance-sheet facts and capital-efficiency metrics for ADBE and introduces no out-of-scope adjustment, scoring, valuation, multi-company, or generalized-ontology behavior.

## Assumptions

* The raw Company Facts payload is the same unmodified structure produced by the Slice 1 SEC retrieval and consumed by the prior slices.
* Adobe reports balance-sheet facts in US dollars at fiscal-year-end instant dates.
* A fiscal-year-end observation is an instant fact whose period-end date is the company's fiscal year end, identified without a duration window.
* Fiscal-year-end observations are identified by economic period-end semantics and annual 10-K context, not by recency of filing.
* "Approximately the latest five completed fiscal years" means up to five displayed years, and fewer when the payload provides fewer completed years.
* One additional prior fiscal-year-end balance may be retained solely to compute average denominators for the earliest displayed year.
* Identical repeated comparative values collapse to one observation; genuinely conflicting distinct values that the rules cannot disambiguate are a failure.
* Cash and short-term investments are combined per an explicit definition that avoids double counting; the actual Adobe concepts are verified through research before implementation.
* Total debt is defined explicitly from Adobe's debt components; unrelated liabilities are excluded.
* The initial invested-capital definition, excess-cash treatment, and effective-tax-rate approach are documented in research and kept intentionally simple.
* Derived metrics are calculated in application code and are never sourced from an external precomputed value when the underlying facts exist.
* Negative net cash, negative equity where reported, and other economically valid negatives are valid; only missing inputs or zero denominators suppress a dependent metric.
* Normalization and derivation operate only on already-retrieved data and perform no network access.

## Dependencies

* The Slice 1 SEC Company Facts retrieval that supplies the raw payload and its provenance fields.
* The Slice 1C operating-income and Slice 1D net-income normalization that this slice reuses.
* The shared annual normalization primitives that this slice extends for instant facts.
* Adobe's SEC US-GAAP concepts for cash, short-term investments, debt components, total assets, total stockholders' equity, income tax expense, and pretax income, and the XBRL period, unit, form, and accession metadata present in the payload.

## Scope Boundaries

The feature includes only ADBE normalization of fiscal-year-end cash, short-term investments, total debt, total assets, and total stockholders' equity; the explicit instant-versus-duration distinction; reuse of canonical operating income and net income; explicit cash-position and total-debt definitions; deterministic derivation of net cash or net debt, ROA, ROE, invested capital, NOPAT, and ROIC with documented denominator, excess-cash, and tax-rate conventions; an optional single baseline year for average denominators; economic-fiscal-year alignment; provenance preservation; the fact-versus-metric distinction; explicit failure and explicit omission behavior; and the smallest instant-fact primitive justified by concrete duplication.

The feature excludes incremental ROIC, goodwill-adjusted ROIC, tangible invested capital, working-capital decomposition, lease-adjusted invested capital, acquisition-accounting adjustments, capital-allocation scoring, stock-based-compensation analysis, repurchases and dividends, valuation multiples, quarterly or trailing-twelve-month calculations, databases, Azure infrastructure, AI or agent integration, multi-company support, screening, and any generalized accounting ontology.

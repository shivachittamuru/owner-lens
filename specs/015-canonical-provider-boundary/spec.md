# Feature Specification: Canonical Provider Boundary (Slice 5A)

**Feature Branch**: `015-canonical-provider-boundary`

**Created**: 2026-10-05

**Status**: Implemented

**Input**: User description: "Implement OwnerLens Slice 5A, the canonical provider boundary. Decouple all downstream OwnerLens financial logic from raw SEC Company Facts by introducing a provider-neutral canonical financial history, populated by an SEC adapter, and consumed by every deterministic OwnerLens calculation. Preserve SEC baseline behavior and provenance exactly. No FMP yet."

## Overview

Today every OwnerLens analytical layer (owner economics, capital efficiency, capital allocation,
annual economic value, compounding, economic summary, and coverage) reads raw SEC Company Facts
directly and resolves SEC XBRL concepts itself. This slice inserts one boundary between data
providers and OwnerLens economics:

```text
providers (SEC today; FMP in Slice 5B)
   ↓  provider adapter / mapper
canonical financial history (provider-neutral, provenance-preserving)
   ↓
OwnerLens deterministic logic
```

The slice changes where facts come from, not what the economics mean. Every existing financial
definition, classification, threshold, coverage state, and persisted output stays identical.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - SEC facts become a canonical financial history (Priority: P1)

An OwnerLens maintainer supplies raw SEC Company Facts for a company and receives a canonical
financial history: a typed, immutable set of reported annual facts keyed by OwnerLens metric name
and fiscal year. Each fact records its value, unit, fiscal year, period start and end where
applicable, the provider (`sec`), the provider field (the SEC concept that produced it), and
filing metadata such as form, filed date, and accession.

**Why this priority**: Every later story depends on this boundary existing. Without a canonical
history populated from SEC, downstream code has nothing provider-neutral to consume, and Slice 5B
has nothing to plug FMP into.

**Independent Test**: Map the recorded ADBE, V, and COST Company Facts fixtures into canonical
history and compare every canonical fact against the value and provenance produced by the existing
SEC normalizers for the same metric and year.

**Acceptance Scenarios**:

1. **Given** recorded ADBE Company Facts, **When** they are mapped to canonical history, **Then**
   each supported metric present in the existing normalized output appears as a canonical fact with
   an identical value, unit, fiscal year, and period dates.
2. **Given** a canonical revenue fact for ADBE fiscal year 2025, **When** its provenance is
   inspected, **Then** it reports provider `sec`, the SEC concept that the existing revenue
   normalizer selected, and that observation's form, filed date, and accession.
3. **Given** Company Facts in which a metric is unsupported for the filer (for example Visa
   diluted weighted-average shares), **When** they are mapped, **Then** the canonical history marks
   that metric as unsupported rather than containing a fabricated or substituted value.
4. **Given** Company Facts with conflicting distinct full-year values for one metric and year,
   **When** they are mapped, **Then** the same ambiguity error the SEC normalizer raises today
   surfaces; no value is chosen silently.

---

### User Story 2 - Feature 1 calculations consume canonical history (Priority: P1)

A maintainer computes owner economics and capital efficiency from a canonical financial history
instead of raw SEC JSON. Results match today's SEC-derived results for the golden companies.

**Why this priority**: Owner economics and capital efficiency are the foundation for every
Feature 2 layer. Moving them across the boundary proves the canonical model carries everything
OwnerLens economics need.

**Independent Test**: Build a canonical history directly from hand-constructed canonical facts
(no SEC payload and no SEC concept names), compute owner economics and capital efficiency, and
verify hand-calculated FCF, FCF/share, margins, growth, and ROIC. Separately, confirm that ADBE, V,
and COST outputs computed through the canonical path equal the existing SEC-path outputs within
existing test tolerances.

**Acceptance Scenarios**:

1. **Given** a canonical history for ADBE, **When** owner economics are computed from it, **Then**
   each row's revenue, operating income, net income, operating cash flow, capex, diluted shares,
   free cash flow, FCF/share, margins, and growth equal the existing SEC-path row for that year.
2. **Given** a canonical history for ADBE, **When** capital efficiency is computed from it,
   **Then** ROIC and every supporting balance-sheet and tax value equal the existing SEC-path row.
3. **Given** a canonical history assembled from synthetic facts whose provider is not `sec`,
   **When** owner economics and capital efficiency are computed, **Then** they succeed using the
   same definitions, proving the calculation does not depend on SEC concept names.
4. **Given** a canonical history where diluted shares are unsupported (Visa), **When** owner
   economics are computed, **Then** per-share fields are unavailable and every non-per-share
   metric is still derived, exactly as today.

---

### User Story 3 - Feature 2 layers and coverage consume canonical history (Priority: P2)

A maintainer produces capital allocation, annual economic value, compounding, the economic value
summary, and the golden-company coverage report from canonical history. Classifications, drivers,
and coverage states match today's results.

**Why this priority**: Feature 2 outputs are the user-facing judgment layer. Moving them completes
the success criterion that no downstream logic depends on raw SEC data.

**Independent Test**: For each golden company, compare every Feature 2 classification, driver
list, and coverage state produced through canonical history with the existing SEC-path output.

**Acceptance Scenarios**:

1. **Given** canonical histories for ADBE, V, and COST, **When** capital allocation, annual
   economic value, compounding, and the economic summary are computed, **Then** every
   classification and driver equals the existing SEC-path output.
2. **Given** existing MSFT, CRM, and NOW fixtures covered by tests, **When** coverage is produced
   through canonical history, **Then** every input coverage state (available, structurally absent,
   unsupported) and every layer state (available, partial, insufficient data, unavailable) and its
   reason equal the existing results.
3. **Given** any input that fails loudly today, **When** the same input passes through the
   canonical path, **Then** the same typed failure surfaces.

---

### User Story 4 - Learn the boundary from a notebook and architecture docs (Priority: P3)

A reader opens a runnable notebook that walks from SEC raw facts, to canonical facts with their
provenance, to OwnerLens economics, and reads updated architecture documentation showing the
provider → canonical → deterministic logic layering.

**Why this priority**: The constitution requires an educational notebook for meaningful new
concepts. The canonical boundary is the concept Slice 5B builds on, so it must be explained, but it
delivers no new economics.

**Independent Test**: Execute the notebook top to bottom using the same SEC retrieval convention as
notebooks 01 through 09, confirm it records the retrieval context, and confirm the architecture
documentation contains the layered diagram.

**Acceptance Scenarios**:

1. **Given** ADBE Company Facts retrieved from SEC, **When** `12_canonical_provider_boundary.ipynb`
   runs end to end, **Then** it displays raw SEC facts, the resulting canonical facts with provider
   and provider field, and owner economics computed from canonical history.
2. **Given** the architecture documentation, **When** a reader looks for the data-flow diagram,
   **Then** it shows providers above canonical facts above OwnerLens deterministic logic and states
   that provider-specific concepts stay above the canonical boundary.

---

### Edge Cases

- A metric is supported by a filer but has no observation for one fiscal year: the canonical
  history has no fact for that year, and downstream behavior equals today's missing-year behavior.
- A metric is structurally absent for a filer (for example, no short-term investments or no
  dividends): the canonical history distinguishes this from unsupported exactly as coverage does
  today.
- A metric is unsupported (no recognized provider field): the canonical history records the
  metric as unsupported with a reason; no zero or substitute value appears.
- Conflicting distinct full-year values exist for one metric and year: the existing ambiguity
  failure surfaces at or before the canonical boundary.
- Period-duration metrics (revenue, cash flow) carry period start and end; instant metrics
  (cash, debt, assets, equity) carry the instant date without a fabricated start date.
- Sign conventions (for example capex, repurchases, and dividends reported as outflows) are
  preserved as today; downstream definitions continue to apply the same absolute-value handling.
- The `max_years` window and ticker canonicalization behave identically through the canonical path.
- Persisted ingestion output and record formats are unchanged; if persistence consumes normalized
  facts, its stored provenance remains identical.

## Requirements *(mandatory)*

### Functional Requirements

#### Canonical model

- **FR-001**: The system MUST define a provider-neutral, immutable canonical fact that records the
  OwnerLens metric name, value, unit, fiscal year, fiscal period, period end, period start where
  the metric is a duration, provider identifier, provider field or source concept, and filing or
  source metadata (form, filed date, accession when available).
- **FR-002**: The system MUST define an immutable canonical financial history that holds, for one
  company, canonical facts grouped by metric and fiscal year, plus the coverage status of each
  supported metric (available, structurally absent, or unsupported with a reason).
- **FR-003**: The canonical metric vocabulary MUST be limited to metrics OwnerLens already
  consumes: revenue, operating income, pretax income, income tax expense, net income, operating
  cash flow, capital expenditures, stock-based compensation, repurchases, dividends paid, cash,
  short-term investments, current debt, long-term debt, total assets, total equity, and diluted
  weighted-average shares. No other metrics or generic accounting schema MUST be added.
- **FR-004**: Canonical metric names MUST be provider-neutral OwnerLens names and MUST NOT be SEC
  XBRL concept names.

#### SEC adapter

- **FR-005**: The system MUST provide an SEC adapter that converts raw SEC Company Facts into a
  canonical financial history by reusing the existing SEC normalizers and period-selection logic.
- **FR-006**: The SEC adapter MUST NOT change any SEC normalization rule, concept preference order,
  annual-period selection, duplicate handling, ambiguity detection, or instant selection.
- **FR-007**: Every canonical fact produced by the SEC adapter MUST record provider `sec`, the SEC
  concept that produced it as the provider field, and that observation's form, filed date, and
  accession.
- **FR-008**: The SEC adapter MUST translate today's unsupported-concept outcomes into explicit
  canonical unsupported status and MUST propagate today's malformed-payload and ambiguity failures
  as typed failures.

#### Downstream refactor

- **FR-009**: Owner economics, capital efficiency, capital allocation, annual economic value,
  compounding, economic summary, and coverage MUST each expose an entry point that accepts a
  canonical financial history.
- **FR-010**: These downstream modules MUST NOT import SEC normalizers, SEC concept tables, or
  SEC-specific helpers, and MUST NOT read raw SEC Company Facts.
- **FR-011**: Downstream calculations MUST NOT branch on provider identity or provider field
  values; provenance is carried through, not interpreted.
- **FR-012**: Existing raw-facts entry points (for example `owner_economics_from_facts`) MAY remain
  as thin compatibility wrappers that map SEC facts to canonical history and delegate to the
  canonical entry point. They MUST NOT duplicate calculation logic.
- **FR-013**: Output rows that today expose reported observations MUST continue to expose each
  input value's provenance, now sourced from the canonical fact.

#### Semantic preservation

- **FR-014**: The FCF definition, FCF/share, ROIC, operating, net, and FCF margins, growth logic,
  capital-allocation rules, buyback effectiveness, economic value and compounding classifications
  and thresholds, economic summary synthesis, and coverage semantics MUST remain unchanged.
- **FR-015**: For ADBE, V, and COST, every Feature 1 metric and Feature 2 classification and driver
  produced through the canonical path MUST equal the current SEC-path output within existing test
  tolerances.
- **FR-016**: Existing MSFT, CRM, and NOW partial, insufficient, unsupported, and fail-loud
  behaviors covered by tests MUST remain unchanged.
- **FR-017**: Persistence and ingestion behavior, stored record formats, and CLI output MUST remain
  unchanged.

#### Verification and documentation

- **FR-018**: Automated tests MUST prove SEC raw data maps to canonical history, provenance
  survives mapping, canonical history produces owner economics, capital efficiency, and Feature 2
  outputs, golden-company outputs are unchanged, partial, unsupported, and insufficient semantics
  are unchanged, and downstream modules do not depend on SEC-specific concepts.
- **FR-019**: A test MUST compute downstream outputs from a canonical history built without any SEC
  payload and with a non-SEC provider identifier.
- **FR-020**: A test or static check MUST fail if a downstream module imports SEC-specific modules
  or references SEC concept names.
- **FR-021**: The full test suite, lint, and static type checks MUST pass.
- **FR-022**: The system MUST include a runnable notebook `12_canonical_provider_boundary.ipynb`
  demonstrating SEC raw facts → canonical facts → OwnerLens economics, using the project's standard
  SEC retrieval and recording the retrieval context (CIK and payload content hash).
- **FR-023**: Architecture documentation MUST show the providers → canonical facts → OwnerLens
  deterministic logic layering and state the boundary rule.

#### Out of scope

- **FR-024**: This slice MUST NOT add FMP or any other provider, API keys, cross-provider
  reconciliation, provider selection, batch ingestion, screening, valuation, probabilistic
  underwriting, Azure infrastructure, or a major package restructuring.

### Key Entities

- **Canonical Fact**: One reported annual value for one OwnerLens metric and fiscal year. Carries
  value, unit, fiscal year and period, period dates, provider, provider field, and filing or source
  metadata. Provider-neutral in name, provider-specific only in provenance.
- **Canonical Financial History**: The complete set of canonical facts for one company, plus the
  coverage status of each supported metric. The only input downstream OwnerLens logic accepts.
- **Canonical Metric**: The fixed OwnerLens vocabulary of supported metrics (FR-003), each with a
  kind (duration or instant) and unit.
- **Provider Adapter (SEC)**: Converts one provider's raw payload into a canonical financial
  history. Owns all provider-specific concepts, tags, and selection rules.
- **Provenance**: The provider, provider field, and filing or source metadata attached to every
  canonical fact and carried into downstream outputs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of existing tests pass without changing their expected financial values,
  classifications, or coverage states.
- **SC-002**: For ADBE, V, and COST, 100% of owner economics, capital efficiency, capital
  allocation, economic value, compounding, and economic summary outputs computed through the
  canonical path equal the previous SEC-path outputs within existing tolerances.
- **SC-003**: Zero downstream analytical modules (the seven listed in FR-009) reference raw SEC
  Company Facts, SEC normalizers, or SEC concept names, verified by an automated check.
- **SC-004**: 100% of canonical facts produced from the golden fixtures carry a provider, provider
  field, unit, fiscal year, and filing metadata that reconcile to the original SEC observation.
- **SC-005**: Every downstream layer produces correct results from a canonical history built with
  a non-SEC provider identifier, demonstrating readiness for a second provider without further
  downstream changes.
- **SC-006**: The canonical boundary notebook runs end to end and records the retrieval context
  needed to reproduce its inputs.

## Assumptions

- The existing SEC normalizers, recorded fixtures, and golden-company tests are the regression
  oracle; no live SEC retrieval is needed for verification.
- Income tax expense is included in the canonical vocabulary because capital efficiency (ROIC)
  already consumes it, even though the request's metric list omitted it.
- Structurally absent versus unsupported distinctions follow the definitions already used by the
  coverage report.
- Compatibility wrappers for raw-facts entry points remain during this slice so existing callers,
  CLI, notebooks, and persistence keep working; their removal is deferred.
- Existing notebooks 01 through 09 are not rewritten; the new notebook uses the requested name
  `12_canonical_provider_boundary.ipynb`.
- Persistence continues to store what it stores today; persisting canonical facts is out of scope.
- The canonical model is limited to annual reported facts, matching current OwnerLens scope.

## Completion Notes

* Before refactoring, 256 existing tests plus the regression baseline passed (257).
* After implementation, `uv run pytest` passes 326 tests: the 256 original tests, unchanged except
  for the series-builder helpers in `tests/test_capital_allocation.py`, plus 70 new tests across
  `test_canonical`, `test_sec_adapter`, `test_canonical_downstream`, `test_canonical_regression`,
  and `test_canonical_boundary`.
* `uv run ruff check .` and `uv run mypy src` report no issues.
* Regenerating `tests/data/canonical_baseline.json` from the refactored code produces a
  byte-identical file, which covers ADBE, V, COST, the missing-current-debt case, and the
  ambiguous-repurchases case.
* Notebook `12_canonical_provider_boundary.ipynb` ran end to end against live SEC data. Notebooks
  02 through 06 and 08 still run unchanged through the compatibility wrappers.
* `margin.py` remains an SEC-side legacy helper outside the boundary check (research R13).

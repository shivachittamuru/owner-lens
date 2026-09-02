---
description: "Task list for Adobe Core Owner Economics (Slice 1D)"
---

# Tasks: Adobe Core Owner Economics

**Input**: Design documents from `specs/004-core-owner-economics/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for every new metric and edge.

**Organization**: Tasks are grouped by user story. Foundational work (the primitive extension and the generic normalizer) blocks all metric work and is done first, matching build steps 1-2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US5)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before changing shared code

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extend the shared annual primitive and add the generic reported-metric normalizer. Build steps 1-2. All metrics depend on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Add a `unit: str = TARGET_UNIT` keyword parameter to `select_annual_series` and thread it through `_qualifying_observations` and `_observation_from_fact` in src/owner_lens/_annual.py
- [X] T003 Add shared generic `ConceptNotFoundError` and `AmbiguousValueError` (subclasses of `AnnualNormalizationError`) in src/owner_lens/_annual.py
- [X] T004 Create `MetricSpec` (metric, concept_preference, unit) and the generic `AnnualSeries` (metric, ticker, concept, unit, observations) in src/owner_lens/reported.py
- [X] T005 Implement `normalize_annual_metric(raw_facts, spec, *, ticker="ADBE", max_years=5)` in src/owner_lens/reported.py, reusing `ensure_supported_ticker`, `us_gaap_concepts`, and `select_annual_series` with the spec unit and shared generic errors
- [X] T006 Add a foundational test in tests/test_reported.py that `normalize_annual_metric` selects by unit (a `shares` metric ignores USD facts and vice versa) and derives the fiscal year from the period end date

**Checkpoint**: The primitive supports configurable units and the generic normalizer works end to end

---

## Phase 3: User Story 1 - Normalize Core Cash-Generation and Per-Share Facts (Priority: P1) 🎯 MVP

**Goal**: Produce canonical annual series for net income, operating cash flow, capital expenditures, and diluted weighted-average shares. Build steps 3-6.

**Independent Test**: Given a controlled payload with annual, quarterly, and repeated observations per concept, each metric returns one canonical full-year observation per recent fiscal year with provenance.

### Implementation for User Story 1

- [X] T007 [US1] Define the metric specs `NET_INCOME`, `OPERATING_CASH_FLOW`, `CAPITAL_EXPENDITURES`, and `DILUTED_SHARES` with their documented concept preference orders and units in src/owner_lens/reported.py
- [X] T008 [US1] Add thin public functions `normalize_net_income`, `normalize_operating_cash_flow`, `normalize_capital_expenditures`, and `normalize_diluted_shares` in src/owner_lens/reported.py
- [X] T009 [US1] Export the reported normalizers, `AnnualSeries`, `MetricSpec`, and the shared generic errors from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T010 [P] [US1] Add concept-selection and happy-path tests (one observation per year, newest first) for net income and operating cash flow in tests/test_reported.py
- [X] T011 [US1] Add annual-vs-quarterly/YTD filtering and comparative-repeat collapse tests for the USD metrics in tests/test_reported.py
- [X] T012 [US1] Add a fewer-than-five-years test and a diluted-shares happy-path test (unit `shares`, weighted-average concept) in tests/test_reported.py

**Checkpoint**: All four reported metrics normalize correctly with provenance

---

## Phase 4: User Story 2 - Derive Owner-Economics Metrics (Priority: P1)

**Goal**: Deterministically derive net margin, free cash flow, FCF margin, FCF per diluted share, and the three adjacent-year growth metrics, aligned by economic fiscal year. Build step 7.

**Independent Test**: Given aligned canonical inputs, each derived metric equals its documented formula where inputs exist and is omitted otherwise.

### Implementation for User Story 2

- [X] T013 [US2] Create `OwnerEconomicsRow` and `compute_owner_economics(...)` in src/owner_lens/owner_economics.py, aligning the six series by economic fiscal year and deriving net margin, free cash flow (`operating_cash_flow - abs(capex)`), FCF margin, and FCF per diluted share with explicit omission on missing inputs or zero denominators
- [X] T014 [US2] Add adjacent-year growth for FCF, FCF per share, and diluted shares in src/owner_lens/owner_economics.py, omitting growth where the immediately prior year is absent or its base value is missing or zero
- [X] T015 [US2] Add `owner_economics_from_facts(raw_facts, *, ticker="ADBE", max_years=5)` in src/owner_lens/owner_economics.py that normalizes all six series then calls `compute_owner_economics`
- [X] T016 [US2] Export `OwnerEconomicsRow`, `compute_owner_economics`, and `owner_economics_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 2

- [X] T017 [P] [US2] Add tests for net margin, free cash flow, FCF margin, and FCF per diluted share against known inputs in tests/test_owner_economics.py
- [X] T018 [US2] Add fiscal-year alignment tests across metrics with differing year coverage in tests/test_owner_economics.py
- [X] T019 [US2] Add adjacent-year growth tests including omission for the earliest year and non-adjacent gaps in tests/test_owner_economics.py

**Checkpoint**: The full owner-economics view is derived correctly from aligned inputs

---

## Phase 5: User Story 3 - Correct CapEx and Diluted-Share Semantics (Priority: P1)

**Goal**: Guarantee CapEx yields a positive expenditure in free cash flow and that diluted shares are weighted-average, not point-in-time. Reinforces build steps 5-7.

**Independent Test**: Free cash flow equals operating cash flow minus a positive CapEx magnitude, and the share series ignores point-in-time shares-outstanding facts.

### Tests for User Story 3

- [X] T020 [P] [US3] Add a CapEx test proving the reported value is preserved and free cash flow uses the positive magnitude (including a defensive negative-source fixture) in tests/test_owner_economics.py
- [X] T021 [US3] Add a diluted-share semantics test proving `WeightedAverageNumberOfDilutedSharesOutstanding` is selected and an instant `CommonStockSharesOutstanding` fixture is ignored in tests/test_reported.py

**Checkpoint**: CapEx sign and diluted-share semantics are verified

---

## Phase 6: User Story 4 - Preserve Provenance and Fact-versus-Metric Distinction (Priority: P2)

**Goal**: Every reported observation carries full provenance and every derived metric is a distinct, calculated type.

**Independent Test**: A reported observation exposes full provenance; a derived row field is clearly not a reported observation.

### Tests for User Story 4

- [X] T022 [P] [US4] Add a provenance test asserting concept, unit, period dates, fiscal year, fiscal period, form, filing date, and accession on operating cash flow, CapEx, and diluted-share observations in tests/test_reported.py
- [X] T023 [US4] Add a test asserting derived fields (margins, FCF, growth) are separate from reported observation types and reference the fiscal year in tests/test_owner_economics.py

**Checkpoint**: Provenance and the fact-versus-metric boundary are verified

---

## Phase 7: User Story 5 - Fail Explicitly on Ambiguous or Missing Facts (Priority: P3)

**Goal**: Missing concepts and unresolved conflicts fail with typed errors for the new metrics.

**Independent Test**: A missing-concept payload and a conflicting-value payload each raise the documented typed error.

### Tests for User Story 5

- [X] T024 [P] [US5] Add missing-concept tests (`ConceptNotFoundError`) and unsupported-ticker/malformed-payload tests for the new metrics in tests/test_reported.py
- [X] T025 [US5] Add a conflicting-value test raising `AmbiguousValueError` naming the fiscal year in tests/test_reported.py

**Checkpoint**: All new failure paths surface explicitly

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Live validation, regression, and quality gates. Build steps 8-9.

- [X] T026 Run the live ADBE owner-economics validation from specs/004-core-owner-economics/quickstart.md and confirm revenue, operating margin, net income, net margin, operating cash flow, CapEx, free cash flow, FCF margin, diluted shares, FCF/share, and the three growth values, with provenance for operating cash flow, CapEx, and diluted shares
- [X] T027 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1C tests still pass
- [X] T028 [P] Update repository memory notes with the Slice 1D module map and the surviving annual-normalization abstraction in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational; delivers the reported facts (MVP)
- **User Story 2 (Phase 4)**: Depends on User Story 1 (needs all six reported series)
- **User Story 3 (Phase 5)**: Depends on User Story 1 and 2 (validates CapEx and share semantics through derivation)
- **User Story 4 (Phase 6)**: Depends on User Story 1 and 2
- **User Story 5 (Phase 7)**: Depends on User Story 1
- **Polish (Phase 8)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`reported.py`, `owner_economics.py`, `__init__.py`, and each test file).
- Tasks marked [P] touch different files and may run in parallel.

### Parallel Opportunities

- T010, T017, T020, T022, and T024 each open work in a different test file boundary and can start once their implementation dependency is met.
- T028 (memory notes) is independent of the code and can run alongside T026-T027.

---

## Implementation Strategy

### MVP scope

User Story 1 (Phase 3) plus its Foundational prerequisites is the MVP: it delivers the four new canonical reported series. User Story 2 turns those into the owner-economics view.

### Incremental delivery

1. Foundational primitive extension and generic normalizer (steps 1-2).
2. Reported facts (steps 3-6) — MVP.
3. Derived owner economics (step 7).
4. Semantics, provenance, and failure verification.
5. Live validation and quality gates (steps 8-9).


---
description: "Task list for Full Golden-Company Validation (Slice 3C)"
---

# Tasks: Full Golden-Company Validation

**Input**: Design documents from `specs/012-golden-company-validation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests full-pipeline, partial-coverage, absent-metric, business-model-diversity, and regression tests.

**Organization**: Tasks are grouped by user story. A single narrow graceful-degradation change plus a small read-only coverage reporter are the foundational mechanism; each story then validates one facet (full pipeline, honest partial coverage, Adobe regression, business-model diversity).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US4)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

## Coverage semantics (preserve, do not conflate)

`AVAILABLE` != `STRUCTURALLY_ABSENT` != `UNSUPPORTED` != reported `0` != `INSUFFICIENT_DATA`. A missing input must not fail an entire company when honest downstream analysis is still possible, and no value may be fabricated or substituted (never point-in-time shares for weighted-average diluted shares).

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before changing the pipeline

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Make the pipeline degrade gracefully for a shares-absent company and add the read-only coverage reporter. This blocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 In src/owner_lens/owner_economics.py, make `owner_economics_from_facts` tolerate unsupported diluted shares: wrap the `normalize_diluted_shares` call in `try/except ConceptNotFoundError` and, on failure, pass an empty `AnnualSeries` (metric `diluted_shares`, empty concept, no observations) to `compute_owner_economics`, so per-share fields become `None` while all non-per-share fields populate; never substitute a fabricated or point-in-time value
- [X] T003 Re-run the live pipeline for a diluted-shares-absent company and, in src/owner_lens/economic_value.py, src/owner_lens/compounding.py, and src/owner_lens/economic_summary.py, add narrow insufficient-data handling ONLY where a real crash on `None` per-share is exposed (do not refactor into a generic optional-field framework); confirm 2A, 2B, 2C, and 2D complete with per-share classifications reported `INSUFFICIENT_DATA`
- [X] T004 Create src/owner_lens/coverage.py with a `MetricCoverage` enum (`AVAILABLE`, `STRUCTURALLY_ABSENT`, `UNSUPPORTED`), a `LayerCoverage` enum (`AVAILABLE`, `PARTIAL`, `INSUFFICIENT_DATA`, `UNAVAILABLE`), a `LayerResult` record (state, reason, blocking_input), and a `CompanyCoverage` dataclass (ticker, inputs map, layers map) per specs/012-golden-company-validation/data-model.md
- [X] T005 Add `company_coverage(raw_facts, *, ticker, max_years=5)` to src/owner_lens/coverage.py that probes each canonical input normalizer (raise -> `UNSUPPORTED`, empty tolerant series -> `STRUCTURALLY_ABSENT`, populated -> `AVAILABLE`) and runs each analytical entry point to record a `LayerResult` with a reason and blocking input for every non-available layer, performing no network access of its own
- [X] T006 Add `format_coverage_report(coverages)` and a company-level output helper to src/owner_lens/coverage.py that renders a deterministic company-by-layer grid with a reason for every non-available cell, and renders the compact Feature 2D summary for full-coverage companies or available-evidence-plus-missing-inputs for partial-coverage companies, with no fabricated classification
- [X] T007 Update src/owner_lens/__init__.py to export the coverage surface (`MetricCoverage`, `LayerCoverage`, `CompanyCoverage`, `company_coverage`, `format_coverage_report`, and the company-output helper), keeping all existing exports

**Checkpoint**: A shares-absent company flows through every layer with honest partial results, and coverage can be computed and reported

---

## Phase 3: User Story 1 - Run the Full Pipeline Honestly for Each Golden Company (Priority: P1) 🎯 MVP

**Goal**: Each golden company runs through every layer producing a real result or an explicit honest coverage state, and a deterministic cross-company report classifies every layer.

**Independent Test**: Given controlled ADBE, V, and COST fixtures, `company_coverage` classifies every layer per company, the report is deterministic, and no layer is bypassed.

### Tests for User Story 1

- [X] T008 [P] [US1] Add tests in tests/test_coverage.py that `company_coverage` classifies each layer for ADBE (all `AVAILABLE`), COST (all `AVAILABLE`), and V (per-share layers non-available, capital efficiency `AVAILABLE`) using the ADBE/V/COST fixtures in tests/_fixtures.py
- [X] T009 [P] [US1] Add tests in tests/test_coverage.py that `format_coverage_report` is deterministic (stable output for the same inputs) and gives a reason naming the blocking input for every non-available cell
- [X] T010 [P] [US1] Add a COST full-pipeline test in tests/test_economic_summary.py asserting COST runs owner economics, capital efficiency, 2A, 2B, 2C, and 2D to completion and produces a non-insufficient overall summary, validating 52/53-week handling and low-margin economics end to end

**Checkpoint**: All three golden companies run through the pipeline with honest per-layer coverage

---

## Phase 4: User Story 2 - Propagate Partial Coverage Honestly (Priority: P2)

**Goal**: Visa's unsupported diluted shares disable only the per-share analyses; every non-per-share layer stays available, and the summary states the limitation.

**Independent Test**: With the Visa fixture, per-share owner-economics, 2A, 2B, and 2D-per-share are insufficient while revenue, FCF, capital efficiency, and capital-allocation facts remain available, each with a stated reason.

### Tests for User Story 2

- [X] T011 [P] [US2] Add a Visa owner-economics partial test in tests/test_owner_economics.py asserting `owner_economics_from_facts` for V returns rows with `diluted_shares`, `fcf_per_share`, `fcf_per_share_growth`, and `diluted_share_growth` all `None`, and populated revenue, operating income, net income, operating cash flow, capital expenditures, free cash flow, and margins
- [X] T012 [P] [US2] Add a 2A partial test in tests/test_economic_value.py asserting Visa snapshots build with per-share classification `INSUFFICIENT_DATA` while non-per-share level and change signals remain populated
- [X] T013 [P] [US2] Add a 2B partial test in tests/test_compounding.py asserting Visa per-share compounding is `INSUFFICIENT_DATA` while revenue and free-cash-flow CAGRs remain available
- [X] T014 [P] [US2] Add a 2C partial test in tests/test_capital_allocation.py asserting Visa buyback effectiveness is `INSUFFICIENT` (no diluted-share change) while repurchases, SBC, dividends, and their FCF ratios remain available
- [X] T015 [P] [US2] Add a 2D partial test in tests/test_economic_summary.py asserting the Visa summary reports an explicit insufficient-per-share state, preserves available evidence, and names unsupported diluted weighted-average shares as the reason, with no fabricated classification
- [X] T016 [US2] Add a coverage-detail test in tests/test_coverage.py asserting Visa records diluted shares `UNSUPPORTED`, short-term investments `STRUCTURALLY_ABSENT`, and capital efficiency `AVAILABLE`, keeping absent, unsupported, and reported-zero distinct

**Checkpoint**: Partial coverage propagates only to per-share-dependent layers and is reported honestly

---

## Phase 5: User Story 3 - Preserve Adobe as the Full-Coverage Baseline (Priority: P2)

**Goal**: Adobe runs every layer to completion with unchanged values, classifications, and provenance.

**Independent Test**: Adobe coverage is all `AVAILABLE` and every existing Adobe Feature 1 and Feature 2 test passes.

### Tests for User Story 3

- [X] T017 [US3] Add an Adobe full-pipeline regression test in tests/test_coverage.py asserting every layer is `AVAILABLE` and the diluted-shares tolerance path is not taken, and confirm the existing Adobe suites (tests/test_owner_economics.py, tests/test_capital_efficiency.py, tests/test_economic_value.py, tests/test_compounding.py, tests/test_capital_allocation.py, tests/test_economic_summary.py) still pass unchanged

**Checkpoint**: Adobe output and provenance are byte-for-byte preserved

---

## Phase 6: User Story 4 - Survive Business-Model Diversity Without Adobe-Shaped Assumptions (Priority: P3)

**Goal**: Classifications rest on change, per-share growth, capital efficiency, and trajectory rather than absolute margins, and every threshold has a documented generality classification.

**Independent Test**: A low-margin healthy-trajectory company is not deteriorating, a high-margin weakening company is not improving, strong ROIC is recognized across margin structures, and the threshold audit is recorded.

### Tests for User Story 4

- [X] T018 [P] [US4] Add business-model-diversity tests in tests/test_economic_value.py using crafted rows: a low-margin company with stable/improving trajectory is not classified `DETERIORATING` solely for low margins, a high-margin company with weakening trajectory is not classified `IMPROVING` solely for high margins, and strong ROIC remains meaningful across margin structures
- [X] T019 [US4] Add a threshold-generality guard test in tests/test_economic_value.py (and reference the audit table in specs/012-golden-company-validation/research.md) asserting the default Feature 2 threshold values are unchanged by this slice, documenting that no threshold was tuned to flatter any company

**Checkpoint**: Economic-value logic survives business-model diversity and the threshold audit is recorded

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole slice, deliver the artifacts, and record learnings

- [X] T020 Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` and confirm all pass
- [X] T021 Produce the live golden-company coverage report by retrieving raw facts once per company and rendering `format_coverage_report` plus each company-level output for ADBE, V, and COST, confirming the honest coverage grid in specs/012-golden-company-validation/quickstart.md (ADBE/COST full, V per-share insufficient) with provenance preserved for available values
- [X] T022 [P] Create notebooks/08_golden_company_validation.ipynb answering the eight guiding questions from the spec (why these three; what generalized cleanly; what Visa broke; what Costco broke; full vs partial coverage; why unsupported beats fabricated; are Feature 2 thresholds business-model independent; remaining assumptions before scaling), keeping cells lint-clean
- [X] T023 [P] Update repository memory notes in /memories/repo/owner-lens.md with the Slice 3C graceful-degradation fix, the coverage reporter, the threshold audit outcome, and the documented universe-ingestion blockers

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories; within it, T002 precedes T003, and T004 precedes T005 precedes T006 precedes T007
- **User Stories (Phase 3-6)**: All depend on Foundational completion
  - US1 (P1) is the MVP; US2, US3 (P2) and US4 (P3) build on the same mechanism
- **Polish (Phase 7)**: Depends on all user stories being complete

### Within Each User Story

- Foundational mechanism before that story's tests
- Story complete before moving to the next priority

### Parallel Opportunities

- US1 tests T008-T010 touch different files/areas and are marked [P]
- US2 tests T011-T015 touch different test files and are marked [P]; T016 shares tests/test_coverage.py with US1 tasks, so run it after those
- Polish T022 (notebook) and T023 (memory) touch different artifacts and are marked [P]

---

## Implementation Strategy

MVP is User Story 1: the graceful-degradation fix, the coverage reporter, and running all three golden companies through the pipeline with an honest per-layer coverage report. User Story 2 proves partial coverage propagates only to per-share-dependent layers, User Story 3 guards the Adobe regression, and User Story 4 confirms business-model diversity and records the threshold audit. The slice is one narrow tolerance change, a small read-only `coverage.py`, minimal exposed insufficient-data handling, expanded tests, and one educational notebook — with Adobe output preserved and no threshold value changed.

---
description: "Task list for Adobe Balance Sheet and Capital Efficiency (Slice 1E)"
---

# Tasks: Adobe Balance Sheet and Capital Efficiency

**Input**: Design documents from `specs/005-balance-sheet-capital-efficiency/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for instant handling, every balance-sheet fact, and every derived metric.

**Organization**: Tasks are grouped by user story. The instant primitive and balance-sheet normalization block all capital-efficiency derivation and are done first, matching the build order.

## Format: `[ID] [P?] [Story?] Description`

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

**Purpose**: Add the instant selection path. All balance-sheet work depends on it. Build step 1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Extract the shared grouping, earliest-filed deduplication, and ambiguity resolution from `select_annual_series` into a reusable helper in src/owner_lens/_annual.py
- [X] T003 Add `select_instant_series(us_gaap, concept_preference, *, max_years, concept_error, ambiguity_error, unit=TARGET_UNIT)` in src/owner_lens/_annual.py that qualifies instant facts (no `start`, `fp == "FY"`, form starts with `10-K`), derives the fiscal year from the period-end date, and sets `period_start == period_end`
- [X] T004 Add a foundational test in tests/test_balance_sheet.py proving an instant fact (no start) is selected by its period-end date, a duration fact (with start) is excluded from instant selection, and the existing duration path is unaffected

**Checkpoint**: The instant primitive works and stays distinct from the duration path

---

## Phase 3: User Story 1 - Normalize Fiscal-Year-End Balance-Sheet Facts (Priority: P1) 🎯 MVP

**Goal**: Produce canonical fiscal-year-end series for cash, short-term investments, current debt, long-term debt, total assets, and total equity. Build step 2.

**Independent Test**: Given a controlled payload with instant year-end, interim, and repeated observations per concept, each fact returns one canonical year-end observation per recent fiscal year with provenance.

### Implementation for User Story 1

- [X] T005 [US1] Create src/owner_lens/balance_sheet.py with `normalize_annual_instant(raw_facts, spec, *, ticker="ADBE", max_years=5)` reusing `MetricSpec`, `AnnualSeries`, `ensure_supported_ticker`, `us_gaap_concepts`, and `select_instant_series`
- [X] T006 [US1] Define the instant metric specs `CASH`, `SHORT_TERM_INVESTMENTS`, `CURRENT_DEBT`, `LONG_TERM_DEBT`, `TOTAL_ASSETS`, and `TOTAL_EQUITY` with their verified concept preferences in src/owner_lens/balance_sheet.py
- [X] T007 [US1] Add the public normalizers `normalize_cash`, `normalize_short_term_investments`, `normalize_current_debt`, `normalize_long_term_debt`, `normalize_total_assets`, and `normalize_total_equity` in src/owner_lens/balance_sheet.py
- [X] T008 [US1] Export the balance-sheet normalizers and specs from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T009 [P] [US1] Add fiscal-year-end selection and happy-path tests (one observation per year, newest first) for total assets and total equity in tests/test_balance_sheet.py
- [X] T010 [US1] Add interim-exclusion and comparative-repeat collapse tests (earliest-filed provenance) for cash and debt in tests/test_balance_sheet.py
- [X] T011 [US1] Add optional-concept tests confirming absent short-term investments and absent current debt are handled, plus a full provenance assertion in tests/test_balance_sheet.py

**Checkpoint**: All six balance-sheet facts normalize correctly with provenance

---

## Phase 4: User Story 3 - Derive Capital-Efficiency Metrics (Priority: P1)

**Goal**: Derive cash plus short-term investments, total debt, net cash or net debt, effective tax rate, NOPAT, invested capital, ROA, ROE, and ROIC. Build steps 3, 4, 5, 6, 7, 8.

**Independent Test**: Given aligned canonical balance-sheet and income inputs, each derived metric equals its documented formula where inputs exist and is omitted otherwise.

### Implementation for User Story 3

- [X] T012 [US3] Add `INCOME_TAX_EXPENSE` and `PRETAX_INCOME` duration metric specs plus `normalize_income_tax_expense` and `normalize_pretax_income` in src/owner_lens/reported.py (build step 4)
- [X] T013 [US3] Create src/owner_lens/capital_efficiency.py with `CapitalEfficiencyRow` and the cash and debt derivations: cash plus short-term investments, total debt (current plus long-term), and net cash or net debt (build step 3)
- [X] T014 [US3] Add the effective tax rate (`income_tax_expense / pretax_income`, omitted on missing or zero pretax) and NOPAT (`operating_income * (1 - rate)`) in src/owner_lens/capital_efficiency.py (build step 5)
- [X] T015 [US3] Add prior-year baseline handling and average-balance helpers, computing ROA and ROE from average total assets and average total equity, omitting a metric when the beginning balance is unavailable or the average is zero (build steps 6, 7)
- [X] T016 [US3] Add invested capital (`total_debt + total_equity - cash_plus_sti`), average invested capital, and ROIC (`nopat / average_invested_capital`) in src/owner_lens/capital_efficiency.py (build step 8)
- [X] T017 [US3] Add `compute_capital_efficiency(...)` and `capital_efficiency_from_facts(...)` that normalize balance-sheet series with one baseline year (`max_years + 1`) and duration series with `max_years`, align by economic fiscal year, and return the latest `display_years` rows in src/owner_lens/capital_efficiency.py
- [X] T018 [US3] Export `CapitalEfficiencyRow`, `compute_capital_efficiency`, and `capital_efficiency_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 3

- [X] T019 [P] [US3] Add cash plus short-term investments (no double counting), total debt aggregation, and net cash or net debt tests in tests/test_capital_efficiency.py
- [X] T020 [US3] Add effective-tax-rate, NOPAT, average-assets, average-equity, invested-capital, ROA, ROE, and ROIC tests against known inputs in tests/test_capital_efficiency.py
- [X] T021 [US3] Add missing prior-year baseline tests confirming average-based metrics are omitted rather than computed from ending balances in tests/test_capital_efficiency.py
- [X] T022 [P] [US3] Add tax-expense and pretax-income duration-spec tests in tests/test_reported.py

**Checkpoint**: The full capital-efficiency view is derived correctly from aligned inputs

---

## Phase 5: User Story 2 - Distinguish Instant Facts from Duration Facts (Priority: P1)

**Goal**: Prove instant and duration normalization stay distinct and correct.

**Independent Test**: A payload mixing instant and duration facts selects each by the correct path without cross-contamination.

### Tests for User Story 2

- [X] T023 [P] [US2] Add a test proving balance-sheet instant selection ignores duration facts sharing a concept name, and duration normalization ignores instant facts, in tests/test_balance_sheet.py

**Checkpoint**: The instant-versus-duration distinction is verified

---

## Phase 6: User Story 4 - Preserve Provenance and Fact-versus-Metric Distinction (Priority: P2)

**Goal**: Reported balance-sheet observations carry full provenance including the instant date; derived metrics are distinct. Build step 9.

**Independent Test**: A balance-sheet observation exposes full provenance; a derived row field is clearly not a reported observation.

### Tests for User Story 4

- [X] T024 [P] [US4] Add a provenance test asserting concept, unit, fiscal-year-end date, fiscal year, fiscal period, form, filing date, and accession on cash, short-term investments, debt, total assets, and total equity, and a total-debt cross-check that preserves both component accessions, in tests/test_capital_efficiency.py
- [X] T025 [US4] Add a test asserting derived fields (net cash, ROA, ROE, ROIC, invested capital, NOPAT) are separate from reported observation types and reference the fiscal year in tests/test_capital_efficiency.py

**Checkpoint**: Provenance and the fact-versus-metric boundary are verified

---

## Phase 7: User Story 5 - Fail Explicitly on Ambiguous or Missing Facts (Priority: P3)

**Goal**: Missing concepts and conflicting fiscal-year-end values fail with typed errors.

**Independent Test**: A missing-concept payload and a conflicting-value payload each raise the documented typed error.

### Tests for User Story 5

- [X] T026 [P] [US5] Add missing-concept (`ConceptNotFoundError`), unsupported-ticker, and malformed-payload tests for the balance-sheet normalizers in tests/test_balance_sheet.py
- [X] T027 [US5] Add a conflicting fiscal-year-end value test raising `AmbiguousValueError` naming the fiscal year in tests/test_balance_sheet.py

**Checkpoint**: All new failure paths surface explicitly

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Live validation, regression, and quality gates. Build step 10.

- [X] T028 Run the live ADBE capital-efficiency validation from specs/005-balance-sheet-capital-efficiency/quickstart.md and confirm cash plus short-term investments, total debt, net cash or net debt, total assets, total equity, ROA, ROE, invested capital, NOPAT, and ROIC, with provenance for cash, short-term investments, debt, total assets, and total equity
- [X] T029 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1D tests still pass
- [X] T030 [P] Update repository memory notes with the Slice 1E module map, the instant-versus-duration primitive split, and the invested-capital and tax-rate definitions in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational; delivers the balance-sheet facts (MVP)
- **User Story 3 (Phase 4)**: Depends on User Story 1 (needs the balance-sheet and income series)
- **User Story 2 (Phase 5)**: Depends on Foundational and User Story 1
- **User Story 4 (Phase 6)**: Depends on User Story 1 and 3
- **User Story 5 (Phase 7)**: Depends on User Story 1
- **Polish (Phase 8)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`balance_sheet.py`, `capital_efficiency.py`, `reported.py`, `__init__.py`, and each test file).
- Tasks marked [P] touch different files and may run in parallel.

### Parallel Opportunities

- T009, T019, T022, T023, T024, and T026 each open a different file boundary and can start once their implementation dependency is met.
- T030 (memory notes) is code-independent and can run alongside T028-T029.

---

## Implementation Strategy

### MVP scope

Foundational (T002-T004) plus User Story 1 (T005-T011) is the MVP: it delivers the six canonical fiscal-year-end balance-sheet series. User Story 3 turns those into the capital-efficiency view.

### Incremental delivery

1. Instant primitive (step 1).
2. Balance-sheet facts (step 2) — MVP.
3. Cash, debt, tax, NOPAT, averages, invested capital, ROA/ROE/ROIC (steps 3-8).
4. Provenance and cross-check, instant-versus-duration, and failure verification (step 9).
5. Live validation and quality gates (step 10).


---
description: "Task list for Multi-Year Economic Compounding View (Slice 2B)"
---

# Tasks: Multi-Year Economic Compounding View

**Input**: Design documents from `specs/007-economic-compounding-view/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for CAGR mechanics, every compounding-interpretation case, period selection, and deterministic driver generation.

**Organization**: Tasks are grouped by user story. The CAGR primitive, period selection, annual counts, and classification are built before view assembly because the assembled view uses all of them.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US7)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before adding the compounding layer

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the shared compounding types every story depends on. Build step 1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create src/owner_lens/compounding.py with the `CompoundingClassification` enum (`STRONGLY_COMPOUNDING`, `COMPOUNDING`, `STABLE`, `DETERIORATING`, `INSUFFICIENT_DATA`) and the `CompoundingDriver` enum covering the reason codes in specs/007-economic-compounding-view/data-model.md
- [X] T003 Add the immutable `CompoundingThresholds` frozen dataclass and the module-level `DEFAULT_COMPOUNDING_THRESHOLDS` instance (`strong_fcf_per_share_cagr=0.15`, `healthy_fcf_per_share_cagr=0.07`, `flat_cagr_band=0.02`, `material_fcf_cagr=0.05`, `material_margin_change=0.02`, `material_roic_change=0.03`, `material_share_cagr=0.01`, `high_roic_level=0.20`) in src/owner_lens/compounding.py
- [X] T004 Add the `EconomicCompoundingView` frozen dataclass with the period bounds, `years`, CAGR, start/end/change, annual-count, `classification`, and `drivers` fields from specs/007-economic-compounding-view/data-model.md in src/owner_lens/compounding.py

**Checkpoint**: The view, classification, driver, and threshold types exist and import cleanly

---

## Phase 3: User Story 2 - Compute CAGR Correctly Over Fiscal-Year Intervals (Priority: P1)

**Goal**: A standard CAGR over the correct interval count with explicit invalid-case handling. Build step 2. Covers workstream 1 (CAGR primitive + invalid cases).

**Independent Test**: Given endpoint values for a known interval count, each CAGR equals the standard formula using the interval count, and missing, zero-beginning, negative-beginning, and sign-changing cases return an explicit unavailable result.

### Implementation for User Story 2

- [X] T005 [US2] Add `cagr(begin, end, years)` returning `(end / begin) ** (1 / years) - 1` only when both endpoints are present, `years` is positive, `begin` is positive, and `end` is positive, and returning `None` otherwise, in src/owner_lens/compounding.py

### Tests for User Story 2

- [X] T006 [P] [US2] Add CAGR mechanics tests proving the interval count (not the observation count) is the exponent denominator and covering positive growth, a flat series, and a decline in tests/test_compounding.py
- [X] T007 [US2] Add CAGR invalid-case tests proving missing endpoints, a zero beginning, a negative beginning, and a sign change return `None` in tests/test_compounding.py

**Checkpoint**: CAGR is mathematically correct and fails explicitly on invalid inputs

---

## Phase 4: User Story 5 - Choose Deterministic Periods from Available Fiscal Years (Priority: P2)

**Goal**: Deterministically select the recent three-year and longest five-year periods from canonical fiscal years. Build step 3. Covers workstream 2 (explicit period/window selection).

**Independent Test**: Given payloads with exactly five, more than five, and fewer fiscal years, the three-year and five-year endpoints are chosen deterministically and an unsupported period reports insufficient history.

### Implementation for User Story 5

- [X] T008 [US5] Add a deterministic period-selection helper in src/owner_lens/compounding.py where `period_years` is the number of fiscal-year intervals (an N-year CAGR spans `FY(end - N)` through `FY(end)`): recent 3-year CAGR uses `end - 3`; the longest available view uses `end - min(5, available_intervals)`; and it signals insufficient history when the requested span cannot be formed

### Tests for User Story 5

- [X] T009 [P] [US5] Add period-selection tests for exactly five, more than five, and fewer than three canonical fiscal years, asserting deterministic endpoints and the explicit insufficient-history outcome, in tests/test_compounding.py

**Checkpoint**: Period endpoints are deterministic and history-aware

---

## Phase 5: User Story 6 - Reconcile Annual Consistency with the Multi-Year Verdict (Priority: P2)

**Goal**: Count the annual Feature 2A classifications within the period. Build step 4. Covers workstream 5 (annual snapshot consistency counts).

**Independent Test**: Given annual snapshots spanning the period, the view reports the counts of improving, stable, deteriorating, and insufficient-data years.

### Implementation for User Story 6

- [X] T010 [US6] Add an annual-classification counting helper in src/owner_lens/compounding.py that tallies `EconomicValueSnapshot.classification` for snapshots whose fiscal year falls within the period into improving, stable, deteriorating, and insufficient-data counts

### Tests for User Story 6

- [X] T011 [P] [US6] Add annual-count tests over a set of snapshots confirming the four counts and that only in-period years are counted in tests/test_compounding.py

**Checkpoint**: Annual-consistency context is available for the period

---

## Phase 6: User Story 3 - Classify Multi-Year Compounding with Transparent Drivers (Priority: P1)

**Goal**: Turn a period's signals into a deterministic classification and ordered named drivers. Build steps 5, 6, 7. Covers workstreams 6 (driver generation) and 7 (classification + guardrails).

**Independent Test**: Given crafted periods representing strongly compounding, moderately compounding, stable, and deteriorating economics, each returns the expected classification and a deterministic ordered driver list.

### Implementation for User Story 3

- [X] T012 [US3] Add the signal-direction helpers (per-share CAGR band, aggregate-FCF-CAGR direction, ROIC change and level, margin-change direction, share-count-CAGR direction, and net-cash trajectory) that read `CompoundingThresholds` in src/owner_lens/compounding.py
- [X] T013 [US3] Add the driver-emission helper producing an ordered `tuple[CompoundingDriver, ...]` in the fixed priority order (per-share, aggregate-versus-per-share, capital efficiency, margins, share count, balance sheet, annual consistency) in src/owner_lens/compounding.py
- [X] T014 [US3] Add `classify_compounding(view, *, thresholds=DEFAULT_COMPOUNDING_THRESHOLDS)` implementing the documented rule: insufficiency gate on `fcf_per_share_cagr`, primary per-share base, one-notch tempering clamped at `STABLE` for the share-count illusion, material dilution, and ROIC deterioration, a deteriorating-base confirmation, and a corroborating-signal tie-break on a stable base, in src/owner_lens/compounding.py

### Tests for User Story 3

- [X] T015 [P] [US3] Add strongly-compounding, moderately-compounding, stable, and deteriorating classification tests asserting the expected classification and ordered drivers on crafted views in tests/test_compounding.py
- [X] T016 [US3] Add a determinism test proving identical inputs yield the identical classification and identical ordered drivers across repeated calls in tests/test_compounding.py

**Checkpoint**: Multi-year classification and drivers are correct, ordered, and deterministic

---

## Phase 7: User Story 4 - Weight Per-Share Compounding and Surface Its Sources (Priority: P1)

**Goal**: Prove the classification treats FCF-per-share CAGR as primary and surfaces share-count-driven results, dilution, and ROIC deterioration.

**Independent Test**: A period with high FCF-per-share CAGR from aggressive share reduction while aggregate FCF falls, and a period with strong aggregate growth plus material dilution, each surface the share-count effect rather than blindly rewarding or penalizing the headline.

### Tests for User Story 4

- [X] T017 [P] [US4] Add a test where high FCF-per-share CAGR is produced by share-count reduction while aggregate FCF falls materially, asserting it is not strongly compounding and emits the aggregate-decline and share-count drivers, in tests/test_compounding.py
- [X] T018 [P] [US4] Add a test where strong aggregate growth with material dilution is tempered and emits the dilution driver in tests/test_compounding.py
- [X] T019 [US4] Add a test where falling FCF-per-share CAGR with declining ROIC is classified deteriorating even though revenue growth is positive, in tests/test_compounding.py
- [X] T020 [US4] Add a test where strong FCF-per-share CAGR with sustained high ROIC and stable or improving margins is classified strongly compounding, in tests/test_compounding.py

**Checkpoint**: Per-share primacy and the multi-year guardrails are verified

---

## Phase 8: User Story 1 - Summarize a Multi-Year Compounding Period (Priority: P1) 🎯 MVP

**Goal**: Assemble one `EconomicCompoundingView` per requested period from Feature 1 metrics and Feature 2A snapshots. Build steps 8, 9. Covers workstreams 3 (view) and 4 (start/end level and delta calculations).

**Independent Test**: Given constructed Feature 1 rows and Feature 2A snapshots, a requested period yields one view carrying the period bounds, interval count, CAGRs, start-to-end level changes, balance-sheet trajectory, and annual counts, with compounding rates and level changes kept distinct.

### Implementation for User Story 1

- [X] T021 [US1] Add the start-to-end level-and-delta helpers deriving operating-margin, FCF-margin, ROIC, and net-cash start, end, and change from the period endpoints in src/owner_lens/compounding.py
- [X] T022 [US1] Add `build_compounding_view(owner_economics, capital_efficiency, snapshots, *, period_years, thresholds=DEFAULT_COMPOUNDING_THRESHOLDS)` that selects the period endpoints, computes revenue, aggregate-FCF, FCF-per-share, and diluted-share CAGR over `years = end - start` intervals, computes the start-to-end deltas, counts the annual classifications, classifies via `classify_compounding`, and returns the view, reporting `INSUFFICIENT_DATA` with `INSUFFICIENT_MULTI_YEAR_HISTORY` when the span is unavailable, in src/owner_lens/compounding.py
- [X] T023 [US1] Add `compounding_view_from_facts(raw_facts, *, ticker="ADBE", period_years, max_years=5, thresholds=...)` and `compounding_views_from_facts(raw_facts, *, ticker="ADBE", max_years=5, thresholds=...)` that delegate to `owner_economics_from_facts`, `capital_efficiency_from_facts`, and `economic_value_from_facts` (no SEC calls in this layer) and build the recent three-year and longest five-year views, in src/owner_lens/compounding.py
- [X] T024 [US1] Export `CompoundingClassification`, `CompoundingDriver`, `CompoundingThresholds`, `DEFAULT_COMPOUNDING_THRESHOLDS`, `EconomicCompoundingView`, `cagr`, `classify_compounding`, `build_compounding_view`, `compounding_view_from_facts`, and `compounding_views_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T025 [P] [US1] Add a test proving a requested period yields one view with the correct period bounds and interval count and with CAGR and level-change fields kept distinct, from constructed Feature 1 rows and Feature 2A snapshots, in tests/test_compounding.py
- [X] T026 [US1] Add tests asserting the view's CAGRs equal the standard formula over the fiscal-year interval count and the start-to-end deltas equal end minus start, in tests/test_compounding.py

**Checkpoint**: One classified compounding view per period is produced from existing outputs with no network access

---

## Phase 9: User Story 7 - Review the Compact Adobe Compounding View (Priority: P3)

**Goal**: Present the recent three-year and longest five-year Adobe compounding views. Covers workstream 8 (formatter/live output).

**Independent Test**: The compact view for Adobe over both periods shows the compounding rates, start-to-end quality changes, balance-sheet trajectory, annual-classification counts, classification, and ordered drivers.

### Implementation for User Story 7

- [X] T027 [US7] Add a `format_compounding_view(view)` helper rendering the compact view (period header with interval count, the four CAGRs, the start-to-end operating margin, FCF margin, ROIC, and net cash or net debt, the annual-classification counts, the classification, and the ordered drivers), and export it from src/owner_lens/__init__.py

### Validation for User Story 7

- [X] T028 [US7] Run the live ADBE validation from specs/007-economic-compounding-view/quickstart.md producing both the recent three-year and longest five-year views and confirming the CAGRs, start-to-end changes, annual counts, classification, and drivers

**Checkpoint**: The compact Adobe compounding views render end to end

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Educational notebook, regression, and quality gates. Covers workstreams 9 (tests) and 10 (notebook).

- [X] T029 Create the educational notebook notebooks/04_adbe_compounding.ipynb answering how fast revenue, total FCF, and FCF per share compounded, how much share-count change contributed, whether margins and ROIC improved, and whether the recent three-year period was stronger than the longer period, keeping cells lint-clean for `ruff`
- [X] T030 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1E and Slice 2A tests still pass
- [X] T031 [P] Update repository memory notes with the final Slice 2B module map, the CAGR interval rule, the classification guardrails, and the named thresholds in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories
- **User Story 2 (Phase 3)**: Depends on Foundational; delivers the CAGR primitive
- **User Story 5 (Phase 4)**: Depends on Foundational; delivers period selection
- **User Story 6 (Phase 5)**: Depends on Foundational; delivers annual counts
- **User Story 3 (Phase 6)**: Depends on Foundational; delivers classification and drivers
- **User Story 4 (Phase 7)**: Depends on User Story 3 (behavior of the classification rule)
- **User Story 1 (Phase 8)**: Depends on User Stories 2, 5, 6, and 3 (assembly uses CAGR, periods, counts, and classification); delivers the view (MVP)
- **User Story 7 (Phase 9)**: Depends on User Story 1 (built views)
- **Polish (Phase 10)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`compounding.py`, `__init__.py`, and `tests/test_compounding.py`).
- Tasks marked [P] touch a different file or an independent test case and may run in parallel once their implementation dependency is met.

### Parallel Opportunities

- T006, T009, T011, T015, T017, T018, and T025 each open an independent test scenario and can start once their implementation dependency is met.
- T031 (memory notes) is code-independent and can run alongside T028-T030.

---

## Implementation Strategy

### MVP scope

Foundational (T002-T004) plus the CAGR primitive (T005), period selection (T008), annual counts (T010), classification (T012-T014), and view assembly (T021-T026) is the MVP: it delivers one deterministic, classified `EconomicCompoundingView` per period with transparent drivers, built entirely from Feature 1 and Feature 2A outputs.

### Incremental delivery

1. Shared types (step 1).
2. CAGR primitive with invalid-case handling (step 2).
3. Period selection and annual counts (steps 3-4).
4. Classification and drivers, then per-share guardrail verification (steps 5-7).
5. View assembly and orchestration (steps 8-9) — MVP.
6. Compact Adobe view and live validation (US7).
7. Educational notebook, regression, and quality gates (polish).

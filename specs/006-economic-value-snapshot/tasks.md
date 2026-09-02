---
description: "Task list for Annual Economic Value Snapshot (Slice 2A)"
---

# Tasks: Annual Economic Value Snapshot

**Input**: Design documents from `specs/006-economic-value-snapshot/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for improving, deteriorating, stable, insufficient-data, per-share-versus-aggregate divergence, guardrail, boundary, and deterministic-driver cases.

**Organization**: Tasks are grouped by user story. The shared types are built first, then classification, then snapshot assembly, matching the build order. Classification (US2) is built before snapshot assembly (US1) because assembly classifies each year.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US6)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before adding the interpretation layer

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the shared interpretation types every story depends on. Build step 1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create src/owner_lens/economic_value.py with the `EconomicValueClassification` enum (`IMPROVING`, `STABLE`, `DETERIORATING`, `INSUFFICIENT_DATA`) and the `EconomicValueDriver` enum covering the reason codes in specs/006-economic-value-snapshot/data-model.md
- [X] T003 Add the immutable `EconomicValueThresholds` frozen dataclass and the module-level `DEFAULT_THRESHOLDS` instance (`material_growth=0.05`, `material_margin_change=0.01`, `material_roic_change=0.02`, `severe_roic_change=0.05`, `material_share_change=0.01`, `high_roic_level=0.20`) in src/owner_lens/economic_value.py
- [X] T004 Add the `EconomicValueSnapshot` frozen dataclass with the `fiscal_year`, LEVEL, CHANGE, `classification`, and `drivers` fields from specs/006-economic-value-snapshot/data-model.md in src/owner_lens/economic_value.py

**Checkpoint**: The snapshot, classification, driver, and threshold types exist and import cleanly

---

## Phase 3: User Story 2 - Classify the Year with Transparent, Deterministic Drivers (Priority: P1)

**Goal**: Turn a snapshot's signals into a deterministic classification and an ordered set of named drivers. Build steps 2, 3, 4. Covers workstreams 4 (driver generation) and 5 (classification logic).

**Independent Test**: Given crafted single-year snapshots representing clearly improving, clearly deteriorating, and roughly stable economics, each returns the expected classification and a deterministic ordered driver list.

### Implementation for User Story 2

- [X] T005 [US2] Add the signal-direction helpers (growth direction, margin-change direction, ROIC-change direction, share-count direction, and net-cash direction with sign-flip handling) that read `EconomicValueThresholds` in src/owner_lens/economic_value.py
- [X] T006 [US2] Add the driver-emission helper that produces an ordered `tuple[EconomicValueDriver, ...]` in the fixed priority order (per-share, capital efficiency, margins, share count and balance sheet, aggregate revenue and FCF) in src/owner_lens/economic_value.py
- [X] T007 [US2] Add `classify_economic_value(snapshot, *, thresholds=DEFAULT_THRESHOLDS)` implementing the documented rule: insufficiency gate on `fcf_per_share_growth`, primary per-share verdict, ROIC and leverage guardrails on an improving base, strong-quality temper on a deteriorating base, and the corroborating-signal tie-break on a stable base, in src/owner_lens/economic_value.py

### Tests for User Story 2

- [X] T008 [P] [US2] Add clearly-improving, clearly-deteriorating, and stable classification tests asserting the expected classification and ordered drivers on crafted snapshots in tests/test_economic_value.py
- [X] T009 [US2] Add a determinism test proving identical inputs yield the identical classification and identical ordered drivers across repeated calls in tests/test_economic_value.py

**Checkpoint**: Classification and drivers are correct, ordered, and deterministic

---

## Phase 4: User Story 1 - Summarize Each Fiscal Year as an Economic Value Snapshot (Priority: P1) 🎯 MVP

**Goal**: Produce exactly one `EconomicValueSnapshot` per completed fiscal year with distinct LEVEL and CHANGE signals sourced from Feature 1. Build steps 5, 6, 7. Covers workstreams 1 (model), 2 (change calculations), and 6 (alignment with Feature 1 rows).

**Independent Test**: Given constructed `OwnerEconomicsRow` and `CapitalEfficiencyRow` sequences, each fiscal year yields one snapshot whose level and change signals are populated from the corresponding Feature 1 values, with no field blending a level and a change.

### Implementation for User Story 1

- [X] T010 [US1] Add the adjacent-year change helpers deriving `revenue_growth`, `operating_margin_change`, `fcf_margin_change`, and `roic_change` from Feature 1 level values, returning `None` (never zero) when the prior-year input is absent, in src/owner_lens/economic_value.py
- [X] T011 [US1] Add `build_economic_value_snapshots(owner_economics, capital_efficiency, *, thresholds=DEFAULT_THRESHOLDS)` that aligns the two row sequences by fiscal year, reuses the Feature 1 `fcf_growth`, `fcf_per_share_growth`, `diluted_share_growth`, and level signals, derives the four adjacent-year changes, assembles one snapshot per year, classifies each via `classify_economic_value`, and returns them newest first, in src/owner_lens/economic_value.py
- [X] T012 [US1] Add `economic_value_from_facts(raw_facts, *, ticker="ADBE", max_years=5, thresholds=DEFAULT_THRESHOLDS)` that delegates to `owner_economics_from_facts` and `capital_efficiency_from_facts` (no SEC calls in this layer) then calls `build_economic_value_snapshots`, in src/owner_lens/economic_value.py
- [X] T013 [US1] Export `EconomicValueClassification`, `EconomicValueDriver`, `EconomicValueThresholds`, `DEFAULT_THRESHOLDS`, `EconomicValueSnapshot`, `classify_economic_value`, `build_economic_value_snapshots`, and `economic_value_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T014 [P] [US1] Add a test proving each fiscal year yields exactly one snapshot with populated LEVEL and CHANGE fields kept distinct, from constructed Feature 1 rows, in tests/test_economic_value.py
- [X] T015 [US1] Add change-derivation tests asserting `revenue_growth`, `operating_margin_change`, `fcf_margin_change`, and `roic_change` equal the adjacent-year deltas of the Feature 1 level values, and that `fcf_growth`, `fcf_per_share_growth`, and `diluted_share_growth` match the reused row values, in tests/test_economic_value.py

**Checkpoint**: One classified snapshot per year is produced from Feature 1 outputs with no network access

---

## Phase 5: User Story 3 - Weight Per-Share Economics Over Aggregate Growth (Priority: P1)

**Goal**: Prove the classification follows per-share economics over aggregate growth and honors the capital-efficiency and leverage guardrails.

**Independent Test**: Given a year with rising aggregate FCF but falling FCF per share, and a year with flat aggregate FCF but rising FCF per share, the classification follows the per-share direction; strong per-share growth with material deterioration does not classify as improving.

### Tests for User Story 3

- [X] T016 [P] [US3] Add a test where rising aggregate FCF but falling FCF per share from dilution does not classify as improving and emits a dilution driver, in tests/test_economic_value.py
- [X] T017 [P] [US3] Add a test where flat aggregate FCF but rising FCF per share from a share-count decline classifies as improving and emits a share-count-decline driver, in tests/test_economic_value.py
- [X] T018 [US3] Add tests where strong FCF-per-share growth with material ROIC contraction, with severe ROIC deterioration, and with a net-cash-to-net-debt sign flip each avoid an `IMPROVING` result and emit the corresponding offset driver, in tests/test_economic_value.py

**Checkpoint**: Per-share primacy and the deterioration guardrails are verified

---

## Phase 6: User Story 4 - Handle Missing and Insufficient Prior-Year Data Explicitly (Priority: P2)

**Goal**: Years lacking the minimum comparison information classify as `INSUFFICIENT_DATA` with explicit unavailable change signals.

**Independent Test**: The earliest displayed year and a year missing an individual required metric each yield `INSUFFICIENT_DATA`, and no missing change is replaced by zero.

### Tests for User Story 4

- [X] T019 [P] [US4] Add a test proving the earliest displayed year yields `INSUFFICIENT_DATA` with `None` change signals and the `INSUFFICIENT_PRIOR_YEAR_DATA` driver, and that no change is substituted with zero, in tests/test_economic_value.py
- [X] T020 [US4] Add a test proving a year missing `fcf_per_share_growth` (or another required input) yields `INSUFFICIENT_DATA` with the missing input represented as `None`, in tests/test_economic_value.py

**Checkpoint**: Missing-data and earliest-year behavior is explicit and never zero-substituted

---

## Phase 7: User Story 5 - Inspect and Reuse Centralized, Named Thresholds (Priority: P2)

**Goal**: Every classification boundary references a centralized named threshold that is inspectable and adjustable. Covers workstream 3 (centralized thresholds).

**Independent Test**: Locate the named thresholds and confirm inputs just inside and just outside each boundary land on the expected side, and that supplying alternate thresholds changes the outcome.

### Implementation for User Story 5

- [X] T021 [US5] Confirm every classification and direction boundary in src/owner_lens/economic_value.py reads a named `EconomicValueThresholds` field with no inline numeric literal, refactoring any stray literal into the thresholds type

### Tests for User Story 5

- [X] T022 [P] [US5] Add boundary tests for `material_growth`, `material_margin_change`, `material_roic_change`, and `material_share_change` proving inputs just inside and just outside each cutoff land on the expected side, in tests/test_economic_value.py
- [X] T023 [US5] Add a test passing a custom `EconomicValueThresholds` and proving the boundary outcome changes accordingly, confirming thresholds are inspectable and adjustable, in tests/test_economic_value.py

**Checkpoint**: Thresholds are centralized, named, and behave at their boundaries

---

## Phase 8: User Story 6 - Review a Compact Owner-Oriented View for Adobe (Priority: P3)

**Goal**: Present approximately the latest five Adobe fiscal years with the owner-oriented signals, classification, and drivers. Covers workstream 7 (CLI/live presentation).

**Independent Test**: The compact view for Adobe shows the owner-oriented columns and classification for approximately five years, the earliest year shows `INSUFFICIENT_DATA`, and per-year drivers are displayed.

### Implementation for User Story 6

- [X] T024 [US6] Add a `format_economic_value_view(snapshots)` helper that renders the compact owner-oriented table (fiscal year, revenue growth, operating-margin change, FCF growth, FCF-per-share growth, share growth, ROIC, ROIC change, net cash or net debt, classification) with the per-year drivers, and export it from src/owner_lens/__init__.py

### Validation for User Story 6

- [X] T025 [US6] Run the live ADBE validation from specs/006-economic-value-snapshot/quickstart.md and confirm approximately five fiscal years newest first, the earliest year `INSUFFICIENT_DATA`, and the structured drivers per year

**Checkpoint**: The compact Adobe economic-value view renders end to end

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Educational notebook, regression, and quality gates. Covers workstreams 8 (tests) and 9 (notebook).

- [X] T026 Create the educational notebook notebooks/03_adbe_economic_value.ipynb demonstrating the LEVEL-versus-CHANGE distinction, the named thresholds, the deterministic classification and drivers, and the compact ADBE view, keeping cells lint-clean for `ruff`
- [X] T027 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1E tests still pass
- [X] T028 [P] Update repository memory notes with the final Slice 2A module map, the classification rule, the named thresholds, and any implementation deltas in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories
- **User Story 2 (Phase 3)**: Depends on Foundational; delivers classification and drivers
- **User Story 1 (Phase 4)**: Depends on Foundational and User Story 2 (snapshot assembly classifies each year); delivers the per-year snapshot (MVP)
- **User Story 3 (Phase 5)**: Depends on User Story 2 (behavior of the classification rule) and constructed snapshots
- **User Story 4 (Phase 6)**: Depends on User Story 1 (built snapshots) and User Story 2 (insufficiency gate)
- **User Story 5 (Phase 7)**: Depends on User Story 2 (thresholds used by classification)
- **User Story 6 (Phase 8)**: Depends on User Story 1 (built snapshots)
- **Polish (Phase 9)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`economic_value.py`, `__init__.py`, and `tests/test_economic_value.py`).
- Tasks marked [P] touch a different file or an independent test case and may run in parallel once their implementation dependency is met.

### Parallel Opportunities

- T008, T014, T016, T017, T019, and T022 each open an independent test scenario and can start once their implementation dependency is met.
- T028 (memory notes) is code-independent and can run alongside T025-T027.

---

## Implementation Strategy

### MVP scope

Foundational (T002-T004) plus User Story 2 (T005-T009) plus User Story 1 (T010-T015) is the MVP: it delivers one deterministic, classified `EconomicValueSnapshot` per fiscal year with transparent drivers, built entirely from Feature 1 outputs.

### Incremental delivery

1. Shared types (step 1).
2. Classification and drivers (steps 2-4) — the interpretation core.
3. Change calculations, alignment, and snapshot assembly (steps 5-7) — MVP.
4. Per-share-weighting, missing-data, and threshold verification (US3, US4, US5).
5. Compact Adobe view and live validation (US6).
6. Educational notebook, regression, and quality gates (polish).

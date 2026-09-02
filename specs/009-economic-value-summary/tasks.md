---
description: "Task list for Company-Level Economic Value Summary (Slice 2D)"
---

# Tasks: Company-Level Economic Value Summary

**Input**: Design documents from `specs/009-economic-value-summary/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for the synthesis hierarchy, tension handling, watch-versus-guardrail distinction, driver deduplication, and determinism.

**Organization**: Tasks are grouped by user story. The shared types and the ordinal hierarchy are built first, then guardrails and tension, then driver aggregation and assembly, matching the build order.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US5)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before adding the synthesis layer

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the shared synthesis types every story depends on. Build step 1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create src/owner_lens/economic_summary.py with the `OverallEconomicValueClassification` enum (`STRONGLY_IMPROVING`, `IMPROVING`, `STABLE`, `DETERIORATING`, `STRONGLY_DETERIORATING`, `INSUFFICIENT_DATA`) and the `SummaryDriver` enum covering the positive, watch, and negative reason codes in specs/009-economic-value-summary/data-model.md
- [X] T003 Add the immutable `EconomicSummaryThresholds` frozen dataclass and the module-level `DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS` instance (`severe_roic_collapse=0.10`, `high_roic_level=0.20`) in src/owner_lens/economic_summary.py
- [X] T004 Add the `EconomicValueSummary` frozen dataclass with the ticker, latest fiscal year, component classifications (recent compounding optional), overall classification, ordered positive/watch/negative driver tuples, and the compact evidence fields from specs/009-economic-value-summary/data-model.md in src/owner_lens/economic_summary.py

**Checkpoint**: The summary, classification, driver, and threshold types exist and import cleanly

---

## Phase 3: User Story 2 - Classify by a Documented Hierarchy (Priority: P1)

**Goal**: Produce the overall verdict from the ordinal hierarchy (long-term base, latest-year adjustment, capital-allocation modifier). Build steps 2-4. Covers workstreams 2, 3, 4.

**Independent Test**: Crafted component sets representing strongly improving, improving, stable, deteriorating, and strongly deteriorating economics yield the expected overall classification from the documented hierarchy, not an average.

### Implementation for User Story 2

- [X] T005 [US2] Add the ordinal scale mapping (STRONGLY_IMPROVING +2 through STRONGLY_DETERIORATING -2) and the long-term compounding base helper (STRONGLY_COMPOUNDING +2, COMPOUNDING +1, STABLE 0, DETERIORATING -1, INSUFFICIENT falls back to the latest annual base) in src/owner_lens/economic_summary.py
- [X] T006 [US2] Add the latest-year adjustment helper that dampens or confirms by at most one notch and never flips a strong base, in src/owner_lens/economic_summary.py
- [X] T007 [US2] Add the capital-allocation modifier helper (OWNER_UNFRIENDLY -1, QUESTIONABLE -1 only when the score is positive, OWNER_FRIENDLY or BALANCED confirm, never lifting above the base) in src/owner_lens/economic_summary.py
- [X] T008 [US2] Compose the base, latest-year adjustment, and capital-allocation modifier into a clamped ordinal score and convert it to the overall classification, with an insufficiency gate when the long-term and latest annual components are both insufficient, in src/owner_lens/economic_summary.py

### Tests for User Story 2

- [X] T009 [P] [US2] Add hierarchy tests for strongly improving, improving, stable, deteriorating, and strongly deteriorating cases, proving STRONGLY_IMPROVING requires long-term STRONGLY_COMPOUNDING and that a single strong year does not override weak long-term economics, plus a determinism check, in tests/test_economic_summary.py

**Checkpoint**: The overall classification follows the documented hierarchy without guardrails

---

## Phase 4: User Story 4 - Watch Signals versus Guardrails (Priority: P1)

**Goal**: Apply severe guardrails that downgrade the score while watch signals do not. Build step 5. Covers workstream 5.

**Independent Test**: A high SBC burden with shrinking shares and capital returns above free cash flow while net-cash positive stay as watch drivers, while deepening net debt and sustained ROIC collapse downgrade the classification.

### Implementation for User Story 4

- [X] T010 [US4] Add the severe guardrails to the classification composition: sustained ROIC collapse (long-term ROIC change at or below `severe_roic_collapse`) and deepening or persistent net debt (latest net debt with a component deterioration driver) force the score down, applied last, in src/owner_lens/economic_summary.py

### Tests for User Story 4

- [X] T011 [P] [US4] Add tests proving a high SBC burden with a shrinking share count and capital returns above free cash flow while net-cash positive are watch drivers that do not downgrade the verdict, while deepening net debt and sustained ROIC collapse do downgrade it, in tests/test_economic_summary.py

**Checkpoint**: Guardrails downgrade the verdict and watch signals do not

---

## Phase 5: User Story 3 - Durable Economics and Tension (Priority: P1)

**Goal**: Reconcile recent-versus-long-term disagreement with explicit tension drivers. Build step 6. Covers workstream 6.

**Independent Test**: Component sets where recent and long-term results disagree in each direction surface the appropriate tension driver without overreacting.

### Implementation for User Story 3

- [X] T012 [US3] Add tension detection emitting `RECENT_SLOWDOWN` when long-term is strong but the latest year is weak and `EARLY_IMPROVEMENT_NOT_YET_PROVEN` when long-term is weak but the latest year is strong, wired into the latest-year adjustment and the watch drivers, in src/owner_lens/economic_summary.py

### Tests for User Story 3

- [X] T013 [P] [US3] Add tests proving strong long-term with a weak latest year is not classified deteriorating and surfaces recent slowdown, weak long-term with a strong latest year surfaces early improvement without declaring improvement, and agreement reinforces the verdict, in tests/test_economic_summary.py

**Checkpoint**: Current-versus-long-term tension is reconciled and durable economics are preferred

---

## Phase 6: User Story 1 - Synthesize One Company Conclusion (Priority: P1) 🎯 MVP

**Goal**: Assemble the summary with ordered deduplicated drivers and the compact evidence set. Build steps 7-9. Covers workstreams 1, 7.

**Independent Test**: Given the component objects, one summary is produced carrying the component classifications, the overall classification, ordered deduplicated positive, watch, and negative drivers, and the compact evidence set.

### Implementation for User Story 1

- [X] T014 [US1] Add the driver-aggregation helper that maps component classifications and drivers into ordered positive, watch, and negative categories and deduplicates so each summary driver appears once, in src/owner_lens/economic_summary.py
- [X] T015 [US1] Add the evidence-set assembly drawing `latest_fcf_per_share_growth`, `long_term_fcf_per_share_cagr`, `recent_fcf_per_share_cagr`, `diluted_share_cagr`, `latest_roic`, `long_term_roic_change`, `latest_net_cash_or_debt`, `latest_sbc_to_fcf`, `latest_capital_returned_to_fcf`, and `buyback_effectiveness` from the component objects, in src/owner_lens/economic_summary.py
- [X] T016 [US1] Add `synthesize_economic_value_summary(ticker, snapshots, recent_view, long_term_view, capital_rows, *, thresholds=DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS)` composing the base, latest-year adjustment, capital-allocation modifier, guardrails, tension, drivers, and evidence into an `EconomicValueSummary`, omitting the recent compounding classification gracefully when unavailable, in src/owner_lens/economic_summary.py
- [X] T017 [US1] Add `economic_value_summary_from_facts(raw_facts, *, ticker="ADBE", max_years=5, thresholds=...)` delegating to `economic_value_from_facts`, `compounding_views_from_facts`, and `capital_allocation_from_facts` (no SEC calls in this layer), then `synthesize_economic_value_summary`, in src/owner_lens/economic_summary.py
- [X] T018 [US1] Export `OverallEconomicValueClassification`, `SummaryDriver`, `EconomicSummaryThresholds`, `DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS`, `EconomicValueSummary`, `synthesize_economic_value_summary`, and `economic_value_summary_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T019 [P] [US1] Add tests proving one summary carries the component classifications, the overall classification, ordered deduplicated drivers, and the evidence set, that the insufficiency gate yields insufficient-data, and that a missing recent view is omitted gracefully, in tests/test_economic_summary.py

**Checkpoint**: One company-level summary is produced from the component objects with no network access

---

## Phase 7: User Story 5 - Compact Adobe Economic Value Lens (Priority: P3)

**Goal**: Present the compact owner-readable Adobe summary. Covers workstream 8 (formatter).

**Independent Test**: The compact Adobe summary shows the component classifications, the overall classification, the core evidence, and the positive, watch, and negative drivers, answering the owner questions without raw financial tables.

### Implementation for User Story 5

- [X] T020 [US5] Add `format_economic_value_summary(summary)` rendering the compact owner-readable lens (component classifications, overall classification, core evidence, and the positive, watch, and negative drivers) and export it from src/owner_lens/__init__.py

### Validation for User Story 5

- [X] T021 [US5] Run the live ADBE validation from specs/009-economic-value-summary/quickstart.md and confirm the compact lens shows the latest annual, recent and long-term compounding, and capital-allocation classifications, the overall classification, the core evidence, and the ordered drivers

**Checkpoint**: The compact Adobe Economic Value Lens renders end to end

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Educational notebook, regression, and quality gates. Covers workstreams 9 (tests) and 10 (notebook).

- [X] T022 Create the educational notebook notebooks/06_adbe_economic_value_summary.ipynb organized around annual economics, multi-year compounding, capital allocation, areas of agreement, areas of tension, the final deterministic summary, and what the summary does not yet tell us (especially valuation and future competitive durability), keeping cells lint-clean for `ruff`
- [X] T023 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1E, 2A, 2B, and 2C tests still pass
- [X] T024 [P] Update repository memory notes with the final Slice 2D module map, the synthesis hierarchy, and the watch-versus-guardrail distinction in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories
- **User Story 2 (Phase 3)**: Depends on Foundational; delivers the ordinal hierarchy
- **User Story 4 (Phase 4)**: Depends on User Story 2; adds severe guardrails
- **User Story 3 (Phase 5)**: Depends on User Story 2; adds tension detection
- **User Story 1 (Phase 6)**: Depends on User Stories 2, 4, and 3; assembles the summary (MVP)
- **User Story 5 (Phase 7)**: Depends on User Story 1 (built summary)
- **Polish (Phase 8)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`economic_summary.py`, `__init__.py`, and `tests/test_economic_summary.py`).
- Tasks marked [P] touch a different file or an independent test case and may run in parallel once their implementation dependency is met.

### Parallel Opportunities

- T009, T011, T013, and T019 each open an independent test scenario and can start once their implementation dependency is met.
- T024 (memory notes) is code-independent and can run alongside T021-T023.

---

## Implementation Strategy

### MVP scope

Foundational (T002-T004) plus the ordinal hierarchy (T005-T008), guardrails (T010), tension (T012), and the driver, evidence, and assembly work (T014-T019) is the MVP: it delivers one deterministic company-level `EconomicValueSummary` with a documented overall classification and transparent drivers, composed from the existing Feature 2 outputs.

### Incremental delivery

1. Shared synthesis types (step 1).
2. Ordinal hierarchy: base, latest-year adjustment, capital-allocation modifier (steps 2-4).
3. Severe guardrails and tension detection (steps 5-6).
4. Driver aggregation, evidence, and assembly (steps 7-9) — MVP.
5. Compact Adobe lens and live validation (US5).
6. Educational notebook, regression, and quality gates (polish).

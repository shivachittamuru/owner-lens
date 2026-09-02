---
description: "Task list for Capital Allocation Lens (Slice 2C)"
---

# Tasks: Capital Allocation Lens

**Input**: Design documents from `specs/008-capital-allocation-lens/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for reported facts, derived metrics, buyback effectiveness, and capital-allocation interpretation.

**Organization**: Tasks are grouped by user story. The shared trajectory helper and interpretation types are built first, then reported facts, then buyback effectiveness and classification, then row assembly, matching the build order.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US7)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before changing shared code

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract the shared trajectory helper and add the interpretation types. Build steps 1-2.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create src/owner_lens/_trajectory.py with a `net_cash_trajectory(start, end, *, material)` helper returning a NamedTuple of direction (+1/-1/0), a sign-flip flag, and a net-debt flag, encoding the shared rule that a turn to net debt or a deepening net-debt position is deterioration while drawing down surplus cash is not
- [X] T003 Refactor src/owner_lens/economic_value.py to use `_trajectory.net_cash_trajectory`, behavior-preserving, and confirm tests/test_economic_value.py passes unchanged
- [X] T004 Refactor src/owner_lens/compounding.py to use `_trajectory.net_cash_trajectory`, behavior-preserving, and confirm tests/test_compounding.py passes unchanged
- [X] T005 Create src/owner_lens/capital_allocation.py with the `BuybackEffectiveness`, `CapitalAllocationClassification`, and `CapitalAllocationDriver` enums covering the values in specs/008-capital-allocation-lens/data-model.md
- [X] T006 Add the immutable `CapitalAllocationThresholds` frozen dataclass and the module-level `DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS` instance (`material_share_change=0.01`, `high_sbc_to_fcf=0.15`, `meaningful_repurchase_to_fcf=0.25`, `capital_returned_over_fcf_material=1.00`, `high_roic_level=0.20`, `material_roic_change=0.03`) in src/owner_lens/capital_allocation.py
- [X] T007 Add the `CapitalAllocationRow` frozen dataclass with the reported, derived, reused, interpretation, and drivers fields from specs/008-capital-allocation-lens/data-model.md in src/owner_lens/capital_allocation.py

**Checkpoint**: The trajectory helper is shared across 2A/2B, and the capital-allocation types exist and import cleanly

---

## Phase 3: User Story 1 - Normalize Capital-Allocation Facts (Priority: P1)

**Goal**: Produce canonical annual series for repurchases and stock-based compensation. Build step 3. Covers workstream 1 (reported specs).

**Independent Test**: Given a controlled payload with full-year, interim, and repeated observations, each fact returns one canonical annual observation per recent fiscal year with provenance, and conflicts fail explicitly.

### Implementation for User Story 1

- [X] T008 [US1] Add the `REPURCHASES` (`PaymentsForRepurchaseOfCommonStock`), `STOCK_BASED_COMPENSATION` (`ShareBasedCompensation`, `AllocatedShareBasedCompensationExpense`), and `DIVIDENDS_PAID` (`PaymentsOfDividendsCommonStock`, `PaymentsOfDividends`) duration metric specs in src/owner_lens/reported.py
- [X] T009 [US1] Add `normalize_repurchases` and `normalize_stock_based_compensation` using the existing `normalize_annual_metric` machinery in src/owner_lens/reported.py
- [X] T010 [US1] Export `normalize_repurchases` and `normalize_stock_based_compensation` from src/owner_lens/__init__.py

### Tests for User Story 1

- [X] T011 [P] [US1] Add repurchase and SBC concept-selection, full-year-filtering, comparative-repeat collapse, ambiguity-failure, and provenance tests in tests/test_reported.py

**Checkpoint**: Repurchases and SBC normalize correctly with provenance and typed failures

---

## Phase 4: User Story 2 - Preserve Meaning and Absence Explicitly (Priority: P1)

**Goal**: Handle the structurally-absent dividend concept tolerantly and distinguish reported zero from absent. Covers workstream 2 (tolerant dividend absence).

**Independent Test**: A payload with no dividend concept yields an absent series, a concept present with zero is preserved distinctly, and repurchases come from the reported cash outflow.

### Implementation for User Story 2

- [X] T012 [US2] Add a tolerant `normalize_dividends_paid` that returns an empty `AnnualSeries` when no dividend concept qualifies (catching `ConceptNotFoundError`) rather than raising, and export it from src/owner_lens/__init__.py

### Tests for User Story 2

- [X] T013 [P] [US2] Add tests proving the dividend normalizer returns an absent series when the concept is missing, a reported zero is preserved distinctly from an absent concept, and repurchases are taken from the reported cash-outflow concept rather than inferred from share-count or treasury-stock changes, in tests/test_reported.py

**Checkpoint**: Dividend absence and the reported-zero-versus-absent distinction are explicit

---

## Phase 5: User Story 4 - Interpret Buyback Effectiveness (Priority: P1)

**Goal**: Compare repurchase spending against the actual diluted-share-count change. Build step 4. Covers workstream 4.

**Independent Test**: Crafted years combining repurchase levels with share-count outcomes yield the expected effectiveness from the centralized thresholds.

### Implementation for User Story 4

- [X] T014 [US4] Add `classify_buyback_effectiveness(*, repurchases, repurchases_over_fcf, diluted_share_growth, thresholds=DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS)` implementing the documented rule (meaningful repurchase activity versus share shrank/flat/rose, with insufficient-data) in src/owner_lens/capital_allocation.py

### Tests for User Story 4

- [X] T015 [P] [US4] Add buyback-effectiveness tests covering effective, partially-offset-by-dilution, ineffective, net-dilution, no-meaningful-activity, and insufficient-data outcomes in tests/test_capital_allocation.py

**Checkpoint**: Buyback effectiveness is derived from the actual share-count change

---

## Phase 6: User Story 5 - Classify Capital Allocation with Transparent Drivers (Priority: P1)

**Goal**: Turn a year's signals into a deterministic classification and ordered named drivers. Build steps 5-6. Covers workstream 6.

**Independent Test**: Crafted years representing owner-friendly, balanced, questionable, and owner-unfriendly allocation yield the expected classification and a deterministic ordered driver list.

### Implementation for User Story 5

- [X] T016 [US5] Add the signal-direction and driver-emission helpers producing an ordered `tuple[CapitalAllocationDriver, ...]` in the fixed priority order (per-share outcome, buyback effectiveness, SBC burden, capital returned versus free cash flow, balance-sheet trajectory, ROIC context, dividend and retained context) in src/owner_lens/capital_allocation.py
- [X] T017 [US5] Add `classify_capital_allocation` implementing the documented priority rule (insufficiency gate, dilution path, effective-reduction path, otherwise) using buyback effectiveness, SBC burden, capital-returned-over-FCF, a balance-sheet-deterioration flag, and ROIC context, in src/owner_lens/capital_allocation.py

### Tests for User Story 5

- [X] T018 [P] [US5] Add owner-friendly, balanced, questionable, and owner-unfriendly classification tests asserting the expected classification and ordered drivers, plus a determinism test, in tests/test_capital_allocation.py

**Checkpoint**: The capital-allocation classification and drivers are correct, ordered, and deterministic

---

## Phase 7: User Story 3 - Derive Capital-Allocation Metrics (Priority: P1) 🎯 MVP

**Goal**: Derive the ratios, capital returned, and retained FCF and assemble one classified row per fiscal year. Build steps 7-9. Covers workstream 3 (derive metrics).

**Independent Test**: Given aligned free cash flow and capital-allocation facts, each derived metric equals its documented formula, retained FCF is negative and preserved when distributions exceed free cash flow, and one classified row is produced per year.

### Implementation for User Story 3

- [X] T019 [US3] Add the derivation helpers for repurchases/FCF, dividends/FCF, SBC/FCF, capital returned (repurchases plus dividends, with dividends zero only under a confirmed no-dividend program), capital returned/FCF, and retained FCF (free cash flow minus repurchases minus dividends, preserving negative, omitting ratios when free cash flow is absent or non-positive) in src/owner_lens/capital_allocation.py
- [X] T020 [US3] Add `build_capital_allocation_rows(owner_economics, capital_efficiency, snapshots, repurchases, stock_based_compensation, dividends_paid, *, thresholds=DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS)` that aligns inputs by fiscal year, derives the metrics, computes the balance-sheet-deterioration flag via `_trajectory.net_cash_trajectory` on adjacent net cash, interprets buyback effectiveness, classifies each year, and returns rows newest first, in src/owner_lens/capital_allocation.py
- [X] T021 [US3] Add `capital_allocation_from_facts(raw_facts, *, ticker="ADBE", max_years=5, thresholds=...)` delegating to `owner_economics_from_facts`, `capital_efficiency_from_facts`, `economic_value_from_facts`, and the new reported normalizers (no SEC calls in this layer), then `build_capital_allocation_rows`, in src/owner_lens/capital_allocation.py
- [X] T022 [US3] Export `BuybackEffectiveness`, `CapitalAllocationClassification`, `CapitalAllocationDriver`, `CapitalAllocationThresholds`, `DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS`, `CapitalAllocationRow`, `classify_buyback_effectiveness`, `build_capital_allocation_rows`, and `capital_allocation_from_facts` from src/owner_lens/__init__.py

### Tests for User Story 3

- [X] T023 [P] [US3] Add tests asserting repurchases/FCF, dividends/FCF, SBC/FCF, capital returned, and capital returned/FCF equal their formulas, retained FCF is negative and preserved when capital returned exceeds free cash flow, ratios are omitted when free cash flow is absent or non-positive, and a `NO_DIVIDEND_PROGRAM` driver is emitted under a confirmed no-dividend program, in tests/test_capital_allocation.py

**Checkpoint**: One classified capital-allocation row per year is produced from existing outputs and the new facts with no network access

---

## Phase 8: User Story 6 - Balance-Sheet and ROIC Context (Priority: P2)

**Goal**: Interpret capital returns against the balance-sheet trajectory and surface ROIC context.

**Independent Test**: A surplus-cash drawdown while remaining net-cash positive is not a deterioration, while deepening net debt is; ROIC context is surfaced without a return-on-retained-FCF claim.

### Tests for User Story 6

- [X] T024 [P] [US6] Add tests proving a cash decline while remaining net-cash positive is not treated as a balance-sheet deterioration while deepening net debt to fund distributions is (via `build_capital_allocation_rows` with adjacent net cash), and that ROIC context emits high or low and improving or deteriorating drivers without computing a return on retained free cash flow, in tests/test_capital_allocation.py

**Checkpoint**: The balance-sheet guardrail and ROIC context are verified and reuse the shared trajectory logic

---

## Phase 9: User Story 7 - Review the Adobe View and Summary (Priority: P3)

**Goal**: Present the compact per-year Adobe view and the multi-year owner-question summary. Covers workstream 8 (live output).

**Independent Test**: The view shows the reported facts, derived metrics, buyback effectiveness, and classification with drivers, and the summary answers the owner questions.

### Implementation for User Story 7

- [X] T025 [US7] Add `format_capital_allocation_view(rows)` and `capital_allocation_summary(rows)` rendering the compact per-year view (free cash flow, repurchases, repurchases/FCF, dividends, SBC, SBC/FCF, capital returned, capital returned/FCF, retained FCF, diluted-share growth, buyback effectiveness, net cash or net debt, ROIC, classification, drivers) and the multi-year owner-question summary, and export both from src/owner_lens/__init__.py

### Validation for User Story 7

- [X] T026 [US7] Run the live ADBE validation from specs/008-capital-allocation-lens/quickstart.md and confirm approximately five fiscal years with free cash flow, repurchases and repurchases/FCF, absent dividends, SBC and SBC/FCF, capital returned and capital returned/FCF, negative retained FCF in the heavy-repurchase years, diluted-share growth, buyback effectiveness, net cash or net debt, ROIC, the classification, ordered drivers, and the multi-year summary

**Checkpoint**: The Adobe capital-allocation view and summary render end to end

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Educational notebook, regression, and quality gates. Covers workstreams 7 (tests) and 9 (notebook).

- [X] T027 Create the educational notebook notebooks/05_adbe_capital_allocation.ipynb organized around the owner questions (cash generated, buyback spending, dividends, SBC relative to free cash flow, whether shares shrank, buyback effectiveness after dilution, whether distributions weakened the balance sheet, whether retained capital operated in a high-ROIC business, and the OwnerLens conclusion), keeping cells lint-clean for `ruff`
- [X] T028 Run the full regression and quality gate: `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`, confirming all prior Slice 1A-1E, 2A, and 2B tests still pass, including after the trajectory refactor
- [X] T029 [P] Update repository memory notes with the final Slice 2C module map, the verified concepts, the trajectory extraction, and any implementation deltas in /memories/repo/owner-lens.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup; BLOCKS all user stories; includes the behavior-preserving 2A/2B refactor
- **User Story 1 (Phase 3)**: Depends on Foundational; delivers the reported facts
- **User Story 2 (Phase 4)**: Depends on User Story 1; delivers the tolerant dividend and absence semantics
- **User Story 4 (Phase 5)**: Depends on Foundational; delivers buyback effectiveness
- **User Story 5 (Phase 6)**: Depends on Foundational and User Story 4; delivers the classification
- **User Story 3 (Phase 7)**: Depends on User Stories 1, 2, 4, and 5 and Foundational; assembles the classified row (MVP)
- **User Story 6 (Phase 8)**: Depends on User Story 3 (built rows and the trajectory flag)
- **User Story 7 (Phase 9)**: Depends on User Story 3 (built rows)
- **Polish (Phase 10)**: Depends on all desired user stories

### Within Each Story

- Same-file tasks run sequentially (`reported.py`, `capital_allocation.py`, `__init__.py`, and each test file).
- Tasks marked [P] touch a different file or an independent test case and may run in parallel once their implementation dependency is met.

### Parallel Opportunities

- T011, T013, T015, T018, T023, and T024 each open an independent test scenario and can start once their implementation dependency is met.
- T029 (memory notes) is code-independent and can run alongside T026-T028.

---

## Implementation Strategy

### MVP scope

Foundational (T002-T007) plus the reported facts (T008-T012), buyback effectiveness (T014), classification (T016-T017), and the derivation and row assembly (T019-T023) is the MVP: it delivers one deterministic, classified `CapitalAllocationRow` per fiscal year with transparent drivers, built from existing outputs and the new facts.

### Incremental delivery

1. Shared trajectory helper and interpretation types (steps 1-2).
2. Reported repurchase, SBC, and tolerant dividend facts (step 3).
3. Buyback effectiveness and the capital-allocation classification (steps 4-6).
4. Derivation, row assembly, and orchestration (steps 7-9) — MVP.
5. Balance-sheet and ROIC context verification (US6).
6. Adobe view, summary, and live validation (US7).
7. Educational notebook, regression, and quality gates (polish).

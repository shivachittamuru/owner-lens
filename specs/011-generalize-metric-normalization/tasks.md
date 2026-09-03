---
description: "Task list for Generalize Financial Metric Normalization Across Companies (Slice 3B)"
---

# Tasks: Generalize Financial Metric Normalization Across Companies

**Input**: Design documents from `specs/011-generalize-metric-normalization/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled tests for metric resolution, multi-company normalization, semantics, and Adobe regression.

**Organization**: Tasks are grouped by user story. A canonical metric registry plus resolver and the removal of the Adobe-only gate are the foundational mechanism; each story then validates one facet (multi-company normalization, transparent overrides, Adobe regression, and the absent/unsupported/zero distinction).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US4)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

## Canonical semantic invariant (encode permanently)

Tests MUST keep these four outcomes distinct and never collapse them:

- **absent by canonical policy** — Visa short-term investments (concept exists in the taxonomy world but is deliberately not absorbed; empty tolerant series)
- **structurally absent** — Adobe dividends (no dividend program; empty tolerant series)
- **unsupported** — Visa diluted weighted-average shares (no trustworthy concept; typed `ConceptNotFound`)
- **reported/economic zero** — a metric such as repurchases actually reported as `0` (a real observation, not absence)

`absent` ≠ `unsupported` ≠ `zero`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before changing shared normalization code

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the canonical metric registry and resolver, remove the Adobe-only gate, and wire the existing normalizers to resolve concepts per ticker. This blocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create src/owner_lens/metrics.py with a `MetricKind` enum (`DURATION`, `INSTANT`), an immutable `CanonicalMetricDefinition(name, kind, unit, default_concepts, overrides)` dataclass, and a module-level registry defining every in-scope metric with the default concept preferences and the V/COST debt and V equity overrides exactly as recorded in specs/011-generalize-metric-normalization/research.md (Adobe carries no overrides)
- [X] T003 Add `resolve_concepts(definition, ticker)` to src/owner_lens/metrics.py returning `definition.overrides.get(canonical_ticker, definition.default_concepts)` after trimming/uppercasing the ticker, with no allow-list, and covering the unknown-metric case by construction (callers pass a definition)
- [X] T004 In src/owner_lens/_annual.py, add a `canonicalize_ticker(ticker)` helper (trim + uppercase, non-empty) and stop using `ensure_supported_ticker` as an allow-list gate in the normalization path; leave `select_annual_series` and `select_instant_series` behavior unchanged
- [X] T005 Wire the duration normalizers to the registry: in src/owner_lens/reported.py, src/owner_lens/revenue.py, and src/owner_lens/operating_income.py, resolve the per-ticker concept preference via `resolve_concepts` and remove the ADBE-only gate, preserving each function name, signature (`ticker` now accepted for any company), and returned `AnnualSeries` shape
- [X] T006 Wire the instant normalizers to the registry: in src/owner_lens/balance_sheet.py, resolve the per-ticker concept preference via `resolve_concepts` for cash, current debt, long-term debt, total assets, total equity, and short-term investments, removing the ADBE-only gate and preserving the instant path
- [X] T007 Update src/owner_lens/__init__.py to export the canonical registry surface (`MetricKind`, `CanonicalMetricDefinition`, `resolve_concepts`, and the metric definitions) and keep all existing normalizer exports

**Checkpoint**: Any ticker resolves its per-metric concept preference; Adobe definitions carry no overrides; the two selectors are unchanged

---

## Phase 3: User Story 1 - Normalize Core Financials for Multiple Companies (Priority: P1) 🎯 MVP

**Goal**: The core canonical duration and instant metrics normalize correctly for ADBE, V, and COST through defaults and overrides, with no ticker allow-list.

**Independent Test**: Given controlled ADBE, V, and COST fixtures, each in-scope metric returns the correct canonical series or an explicit unsupported result, with no fabricated value.

### Implementation for User Story 1

- [X] T008 [US1] Create tests/_fixtures.py with minimal but realistic controlled `us-gaap` Company Facts fixtures for ADBE, V, and COST covering the in-scope concepts (including the V/COST debt concepts, V equity concept, V absent short-term investments, and V absent diluted shares) mirroring specs/011-generalize-metric-normalization/research.md

### Tests for User Story 1

- [X] T009 [P] [US1] Add registry-resolution tests in tests/test_metrics.py: default concept resolution when no override exists, override resolution for V/COST debt and V equity, case/whitespace canonicalization of the ticker, and deterministic repeated resolution
- [X] T010 [P] [US1] Add multi-company duration normalization tests in tests/test_reported.py for ADBE, V, and COST covering revenue-adjacent duration metrics (net income, operating cash flow, capital expenditures, income tax, pretax) resolving to canonical series using the V/COST fixtures
- [X] T011 [P] [US1] Add multi-company revenue and operating-income tests in tests/test_revenue.py and tests/test_operating_income.py confirming V and COST resolve the correct revenue concept (`RevenueFromContractWithCustomerExcludingAssessedTax`) and `OperatingIncomeLoss` via existing preferences
- [X] T012 [P] [US1] Add multi-company instant normalization tests in tests/test_balance_sheet.py for ADBE, V, and COST covering cash, total assets, and total equity (including the V equity override)

**Checkpoint**: Core metrics normalize across all three companies via the registry

---

## Phase 4: User Story 2 - Map Differing Source Concepts Transparently (Priority: P2)

**Goal**: Company-specific overrides are minimal, declarative, and every normalized observation preserves the actual selected source concept.

**Independent Test**: For V and COST, the affected metrics resolve through the documented override and the returned series reports the override concept as provenance.

### Tests for User Story 2

- [X] T013 [US2] Add debt-override tests in tests/test_balance_sheet.py proving V and COST current debt resolves to `LongTermDebtCurrent` and long-term debt resolves to `LongTermDebtNoncurrent`, that total debt equals current plus long-term with no double count, and that non-debt operating liabilities are never selected
- [X] T014 [US2] Add provenance tests in tests/test_metrics.py and tests/test_balance_sheet.py asserting each normalized series exposes the actual selected source concept (including override concepts) alongside the canonical metric name and ticker, so canonical meaning and source concept remain distinguishable
- [X] T015 [US2] Add an override-audit test in tests/test_metrics.py asserting every registry override is declarative data scoped to one `(metric, ticker)` pair and that Adobe appears in no override map

**Checkpoint**: Overrides are transparent, minimal, and fully traceable through provenance

---

## Phase 5: User Story 3 - Preserve Adobe Behavior as a Regression Baseline (Priority: P2)

**Goal**: Adobe's selected concepts, values, and downstream outputs are unchanged.

**Independent Test**: Adobe normalization through the generalized registry selects the same concepts and values as before, and every existing Adobe test passes.

### Tests for User Story 3

- [X] T016 [US3] Add Adobe regression assertions in tests/test_metrics.py that `resolve_concepts` returns Adobe's original default preferences for every in-scope metric (no override path taken for ADBE)
- [X] T017 [US3] Confirm the existing Adobe Feature 1 and Feature 2 suites (tests/test_revenue.py, tests/test_operating_income.py, tests/test_reported.py, tests/test_balance_sheet.py, tests/test_margin.py, tests/test_owner_economics.py, tests/test_capital_efficiency.py, tests/test_economic_value.py, tests/test_compounding.py, tests/test_capital_allocation.py, tests/test_economic_summary.py) still pass unchanged, updating only import or ticker-gate expectations that the generalization intentionally removes

**Checkpoint**: Adobe results are byte-for-byte preserved

---

## Phase 6: User Story 4 - Distinguish Applicable, Non-Applicable, and Unsupported Metrics (Priority: P3)

**Goal**: Absent, unsupported, and reported-zero outcomes are permanently distinct and never fabricated.

**Independent Test**: Crafted companies exercise each outcome and produce the documented distinct result.

### Implementation for User Story 4

- [X] T018 [US4] Make short-term-investments normalization tolerant of a structurally absent concept in src/owner_lens/balance_sheet.py (return an empty `AnnualSeries` on `ConceptNotFound`, mirroring `normalize_dividends_paid`), documenting that Visa's investment securities are deliberately not absorbed as corporate cash

### Tests for User Story 4

- [X] T019 [US4] Add the canonical semantic-invariant tests in tests/test_balance_sheet.py and tests/test_reported.py encoding all four distinct outcomes: Visa short-term investments returns an empty tolerant series (absent by policy); Adobe dividends returns an empty tolerant series (structurally absent); Visa diluted weighted-average shares raises `ConceptNotFound` (unsupported); and a fixture reporting repurchases of `0` returns a real zero observation (reported zero) — asserting absent, unsupported, and zero are never conflated
- [X] T020 [US4] Add a Visa diluted-shares unsupported test in tests/test_reported.py asserting `normalize_diluted_shares` for V raises the typed unsupported failure and never returns a fabricated or derived denominator

**Checkpoint**: The absent ≠ unsupported ≠ zero distinction is permanently encoded in tests

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole slice, deliver the educational artifact, and record learnings

- [X] T021 Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` and confirm all pass
- [X] T022 Produce the live ADBE/V/COST coverage report by retrieving raw facts once per company and normalizing the in-scope metrics, confirming the coverage grid in specs/011-generalize-metric-normalization/quickstart.md (including V diluted-shares `n/a` and V short-term investments tolerant absence) and inspecting provenance for revenue, capital expenditures, and the debt components per company
- [X] T023 [P] Create notebooks/07_multi_company_metric_normalization.ipynb answering the eight guiding questions from the spec (canonical metric; why not one XBRL tag; common vs differing mappings; company override; provenance under canonicalization; unsupported vs guessed value; what Visa and Costco revealed about Adobe-shaped assumptions), keeping cells lint-clean
- [X] T024 [P] Update repository memory notes in /memories/repo/owner-lens.md with the Slice 3B registry, the V/COST overrides, the tolerant-STI and Visa-unsupported-shares findings, and the absent/unsupported/zero invariant

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational completion
  - US1 (P1) is the MVP; US2 and US3 (P2) and US4 (P3) build on the same registry
  - US4 includes the one remaining implementation change (tolerant STI); its tests depend on T018
- **Polish (Phase 7)**: Depends on all user stories being complete

### Within Each User Story

- Fixtures (T008) precede the tests that consume them
- Implementation before that story's tests (US4: T018 before T019)
- Story complete before moving to the next priority

### Parallel Opportunities

- Foundational T005 and T006 both depend on T002-T004 but touch different modules; T005 spans three duration modules and should be done as one coherent change
- US1 test tasks T009-T012 touch different test files and are marked [P]
- Polish T023 (notebook) and T024 (memory) touch different artifacts and are marked [P]

---

## Implementation Strategy

MVP is User Story 1: the canonical registry, resolver, gate removal, and multi-company normalization of the metrics whose defaults or documented overrides succeed. User Story 2 proves override transparency and provenance, User Story 3 guards the Adobe regression, and User Story 4 permanently encodes the absent ≠ unsupported ≠ zero distinction. The slice adds one new module (`metrics.py`), one shared test fixtures module, refactors four normalization modules to resolve concepts per ticker, and delivers one educational notebook — with Adobe selection preserved throughout.

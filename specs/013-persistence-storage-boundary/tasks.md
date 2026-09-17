---
description: "Task list for Persistence Model and Storage Boundary (Slice 4A)"
---

# Tasks: Persistence Model and Storage Boundary

**Input**: Design documents from `specs/013-persistence-storage-boundary/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/persistence-api.md, quickstart.md

**Tests**: Included. The feature specification explicitly requests deterministic local tests (Section 18) for schema, identity, snapshots, reported facts, derived metrics, analysis results, coverage, queries, and regression.

**Organization**: Tasks are grouped by user story. A shared persistence subpackage (errors, records, raw store, schema, adapters) is the foundational mechanism; each story then delivers one independently testable facet — round-trip reproduction (US1), provenance + coverage semantics (US2), and idempotency + history + cross-company retrieval (US3).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, new subpackage in `src/owner_lens/persistence/`, tests in `tests/`, notebooks in `notebooks/`.

## Invariants (preserve, do not violate)

- Persistence stores OwnerLens **outputs** only; no normalization, calculation, or classification lives here, and no financial function performs a hidden write.
- Money/shares are exact `INTEGER`; ratios are `REAL` (approximate — compare with tolerances).
- Coverage states (`AVAILABLE` / `STRUCTURALLY_ABSENT` / `UNSUPPORTED` / `INSUFFICIENT_DATA`) and reported `0` are explicit and never collapsed into SQL `NULL`.
- Every fact/metric/analysis/coverage row references a `source_snapshot`; no single mutable latest row.
- Repeated identical processing is idempotent via natural keys + UPSERT; a newer `calculation_version` / `analysis_rule_version` coexists as a new row.
- Persistence errors are a distinct hierarchy, never transformed into financial errors.
- No financial module imports the `persistence` subpackage.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline and create the subpackage shell.

- [X] T001 Confirm the baseline is green by running `uv run pytest -q`, `uv run ruff check .`, and `uv run mypy src`
- [X] T002 Create the `src/owner_lens/persistence/` package directory with an empty `src/owner_lens/persistence/__init__.py` placeholder (real exports added in T008)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared persistence machinery every user story depends on: error types, record shapes, raw-payload store, the SQLite schema with versioning, and the pure domain→record adapters. This blocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Create `src/owner_lens/persistence/errors.py` defining `PersistenceError(Exception)` and the subclasses `StorageConnectionError`, `SchemaVersionError`, `StorageWriteError`, and `StorageReadError`, wholly separate from `SecError`/`ConceptNotFoundError` (per contracts/persistence-api.md "Error hierarchy")
- [X] T004 [P] Create `src/owner_lens/persistence/records.py` with frozen dataclasses `CompanyRecord`, `SourceSnapshotRecord`, `ReportedFactRecord`, `DerivedMetricRecord`, `AnalysisResultRecord`, `AnalysisDriverRecord`, and `CoverageResultRecord` (fields per data-model.md "Record dataclasses"), plus module constants `SCHEMA_VERSION = 1`, `DEFAULT_CALCULATION_VERSION`, and `DEFAULT_ANALYSIS_RULE_VERSION`; records carry data only and use domain types (`int` money/shares, `float` ratios)
- [X] T005 [P] Create `src/owner_lens/persistence/raw.py` with a `RawSnapshotStore` Protocol (`put(content_hash, payload) -> str`, `get(content_hash) -> bytes`, `exists(content_hash) -> bool`) and a `FilesystemRawSnapshotStore(root: Path)` that stores payloads keyed by content hash under `root` (idempotent `put`, `get` raises `StorageReadError` for an unknown hash), plus a `compute_content_hash(payload: bytes) -> str` helper using SHA-256
- [X] T006 Create `src/owner_lens/persistence/store.py` with `SqliteStore(db_path: Path, *, raw_store: RawSnapshotStore | None = None)` opening the connection (raising `StorageConnectionError` on failure) and an `initialize()` method that creates the 8 tables (`companies`, `source_snapshots`, `reported_facts`, `derived_metrics`, `analysis_results`, `analysis_drivers`, `coverage_results`, `schema_meta`) with the columns, types, and `UNIQUE` constraints in data-model.md using `CREATE TABLE IF NOT EXISTS`, inserts `schema_version` only if absent, raises `SchemaVersionError` on an incompatible stored version, and is a safe no-op on repeat
- [X] T007 Create `src/owner_lens/persistence/adapters.py` with pure, side-effect-free functions converting domain outputs to records: `CompanyIdentity` → `CompanyRecord`; `AnnualObservation` (+ canonical metric name and `fact_kind`) → `ReportedFactRecord`; `OwnerEconomicsRow`/`CapitalEfficiencyRow` fields → `DerivedMetricRecord` (choosing `value_int` for money/shares, `value_real` for ratios); `EconomicValueSnapshot`/`EconomicCompoundingView`/`CapitalAllocationRow`/`EconomicValueSummary` → `AnalysisResultRecord` with ordered `AnalysisDriverRecord`s; `CompanyCoverage` → `CoverageResultRecord`s (input and layer subjects)
- [X] T008 Populate `src/owner_lens/persistence/__init__.py` to export the store, record types, raw-store types, error hierarchy, and adapters; update `src/owner_lens/__init__.py` to re-export `SqliteStore`, the record types, `RawSnapshotStore`/`FilesystemRawSnapshotStore`, and the `PersistenceError` hierarchy, keeping all existing exports and adding no import of persistence into any financial module

**Checkpoint**: The schema initializes and versions cleanly, records and errors exist, raw payloads can be stored by hash, and domain outputs can be converted to records — but nothing is persisted or queried yet.

---

## Phase 3: User Story 1 - Reproduce a company's economic-value analysis from local storage (Priority: P1) 🎯 MVP

**Goal**: Persist a company's identity, snapshot metadata, canonical facts, derived metrics, Feature 2 analysis outputs, and coverage, then reproduce the latest summary and multi-year metric history from a fresh store with values matching the in-memory computation.

**Independent Test**: Persist a full ADBE analysis to a fresh SQLite file, reopen it, and confirm `get_metric_history(ADBE, "fcf_per_share", limit=5)` returns five ordered fiscal years and `get_latest_summary(ADBE)` returns the classification with ordered drivers equal to the in-memory outputs.

- [X] T009 [US1] In `src/owner_lens/persistence/store.py`, implement `save_company(company)` and `save_source_snapshot(snapshot)` using UPSERT on their natural keys (`cik`; `company_id`+provider+type+`content_hash`), storing the raw payload via `raw_store` when provided and recording `raw_object_ref`; raise `StorageWriteError` on failure
- [X] T010 [US1] In `src/owner_lens/persistence/store.py`, implement `save_reported_facts(facts, *, snapshot)` writing long-form rows scoped to the resolved `snapshot_id` with UPSERT on `(snapshot_id, canonical_metric, concept, fiscal_year, period_end)`, storing money/shares as `INTEGER` and preserving canonical metric vs source concept in separate columns
- [X] T011 [US1] In `src/owner_lens/persistence/store.py`, implement `save_derived_metrics(metrics, *, snapshot)` with UPSERT on `(snapshot_id, metric_name, fiscal_year, calculation_version)`, writing exactly one of `value_int` (money/shares) or `value_real` (ratios) per row
- [X] T012 [US1] In `src/owner_lens/persistence/store.py`, implement `save_analysis_result(result, *, snapshot)` with UPSERT on `(snapshot_id, analysis_type, analysis_period, analysis_rule_version)` and insert its ordered `analysis_drivers` rows keyed by `(analysis_result_id, position)`, storing no free-form interpretive text
- [X] T013 [US1] In `src/owner_lens/persistence/store.py`, implement `save_coverage(coverage, *, snapshot)` writing explicit `state` strings with UPSERT on `(snapshot_id, subject_kind, subject)`, never using `NULL` for `state`
- [X] T014 [US1] In `src/owner_lens/persistence/store.py`, implement `get_company(cik)` (returns `CompanyRecord | None`) and `get_metric_history(cik, metric, *, limit=None)` returning derived-metric records ordered by `fiscal_year` (most recent last), limited to the newest `limit` fiscal years, raising `StorageReadError` on query failure and returning empty for an unknown company/metric
- [X] T015 [US1] In `src/owner_lens/persistence/store.py`, implement `get_latest_summary(cik)` returning the most recent `economic_value_summary` `AnalysisResultRecord` for the company with its ordered drivers populated, or `None` if none stored
- [X] T016 [US1] In `tests/test_persistence.py`, add schema tests: database initialization creates `schema_meta` with `schema_version`, repeat `initialize()` is a no-op, and an incompatible stored version raises `SchemaVersionError` (use `tmp_path`)
- [X] T017 [US1] In `tests/test_persistence.py`, add round-trip tests using the ADBE fixture from `tests/_fixtures.py`: convert outputs via adapters, save all layers, reopen the store, and assert retrieved company, facts, derived metrics, analysis, and coverage equal the in-memory outputs (exact equality for `INTEGER`; tolerance for `REAL` ratios)
- [X] T018 [US1] In `tests/test_persistence.py`, add query tests: `get_metric_history(ADBE, "fcf_per_share", limit=5)` returns five fiscal years in order, and `get_latest_summary(ADBE)` returns the classification with drivers in the same order as the in-memory summary

**Checkpoint**: ADBE can be persisted and fully reproduced from a fresh store — the MVP is independently testable and demonstrable.

---

## Phase 4: User Story 2 - Preserve provenance and semantic missing-data states (Priority: P2)

**Goal**: Stored facts retain SEC provenance, and coverage keeps the four distinct states (never NULL/zero), verified for COST provenance and Visa unsupported coverage.

**Independent Test**: Persist COST facts and Visa coverage, then confirm `get_fact_provenance(COST, "revenue", 2025)` returns the source concept and filing identifiers, and `get_company_coverage(VISA)` returns `UNSUPPORTED` for diluted shares while a reported zero stays a `0` fact.

- [X] T019 [US2] In `src/owner_lens/persistence/store.py`, implement `get_fact_provenance(cik, canonical_metric, fiscal_year)` returning the `ReportedFactRecord` including `concept`, `form`, `filed`, `accession`, and its snapshot reference, or `None` if not stored
- [X] T020 [US2] In `src/owner_lens/persistence/store.py`, implement `get_company_coverage(cik)` returning the `CoverageResultRecord`s for the company's latest snapshot, preserving each explicit `state`
- [X] T021 [US2] In `tests/test_persistence.py`, add provenance tests using the COST fixture: persisted FY2025 revenue retrieves its canonical metric `revenue`, its distinct source concept, `form`, `filed`, `accession`, and snapshot reference; assert canonical metric name and source concept are stored in separate fields
- [X] T022 [US2] In `tests/test_persistence.py`, add coverage-semantics tests using the Visa fixture: diluted-shares coverage retrieves as `UNSUPPORTED` with its reason, a Feature 2 per-share layer retrieves as `INSUFFICIENT_DATA`, a genuine reported zero retrieves as a `0` fact, and absent/unsupported are distinct from zero and from each other (no state is `NULL`)

**Checkpoint**: Provenance and all coverage/missing-data distinctions survive a persist-and-retrieve round trip.

---

## Phase 5: User Story 3 - Idempotent re-processing and retained historical snapshots (Priority: P3)

**Goal**: Re-saving identical data creates no duplicates, distinct later snapshots coexist with earlier ones, and a single latest primitive metric can be retrieved across companies.

**Independent Test**: Persist the same ADBE snapshot twice (row counts unchanged), then persist a distinct later ADBE snapshot (both retained and retrievable), and confirm `get_latest_metric_across_companies("roic", [ADBE, V, COST])` returns each company's latest ROIC.

- [X] T023 [US3] In `src/owner_lens/persistence/store.py`, implement `get_latest_metric_across_companies(metric, ciks)` returning a `dict[cik, DerivedMetricRecord]` of each company's latest value for the metric (retrieval only — no comparison, ranking, or scoring)
- [X] T024 [US3] In `tests/test_persistence.py`, add idempotency tests: saving the identical company, snapshot, facts, derived metrics, analysis, and coverage twice leaves all row counts unchanged and existing rows unmodified; content-hash identity resolves the same snapshot
- [X] T025 [US3] In `tests/test_persistence.py`, add history tests: persisting a distinct later ADBE snapshot (different content hash) retains both snapshots and their dependent rows as individually retrievable, and a newer `calculation_version`/`analysis_rule_version` writes a coexisting row rather than overwriting the prior one
- [X] T026 [US3] In `tests/test_persistence.py`, add a cross-company test: persist ADBE, Visa, and Costco derived metrics and assert `get_latest_metric_across_companies("roic", [ADBE, V, COST])` returns each company's latest ROIC with units

**Checkpoint**: Repeated processing is idempotent, history is preserved, and cross-company latest retrieval works.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Failure-semantics coverage, the educational notebook, regression proof, gates, and optional live validation.

- [X] T027 In `tests/test_persistence.py`, add failure-semantics tests: an invalid/unwritable path raises `StorageConnectionError`/`StorageWriteError`, a query failure raises `StorageReadError`, an unknown company returns an explicit empty result, and no persistence failure surfaces as `ConceptNotFoundError` or insufficient-data (FR-019, SC-008)
- [X] T028 [P] Create `notebooks/09_persistence_model.ipynb` covering why OwnerLens needs persistence; facts vs metrics vs analysis outputs; why provenance survives; why absence/unsupported/insufficient are not SQL NULL; historical snapshots vs one mutable latest row; persisting ADBE/V/COST; several owner/investor query views; and how this boundary maps to Azure Blob + PostgreSQL next — keeping cells lint-clean (ruff scans `.ipynb`)
- [X] T029 Confirm regression and boundary integrity: run `uv run pytest -q` (all existing Feature 1–3 tests plus new persistence tests pass) and verify no financial module imports `owner_lens.persistence` (e.g. `grep`), proving financial modules remain storage-independent (SC-007)
- [X] T030 Run the full gate suite `uv run pytest -q`, `uv run ruff check .`, and `uv run mypy src` and resolve any findings
- [ ] T031 Perform the optional live validation from quickstart.md: initialize a local database, persist ADBE/V/COST identities, one snapshot each, canonical facts, derived metrics, and Feature 2 outputs, then query back the five-year ADBE FCF/share history, COST FY2025 revenue provenance, latest ADBE summary, Visa coverage limitations, and latest ROIC across ADBE/V/COST, confirming values match the in-memory OwnerLens outputs (user-run: requires network and `OWNER_LENS_SEC_USER_AGENT`; the same orchestration is validated deterministically in `tests/test_persistence.py` and reproduced in `notebooks/09_persistence_model.ipynb`)

---

## Dependencies & Execution Order

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **User Stories (Phases 3–5)** → **Polish (Phase 6)**.
- **Foundational blocks everything**: T003–T008 must complete before any user-story task. Within Phase 2, T003/T004/T005 are parallel (`errors.py`, `records.py`, `raw.py`); T006 (store schema) depends on T003–T004; T007 (adapters) depends on T004; T008 (exports) depends on T003–T007.
- **US1 (P1)** depends only on Foundational. All write methods (T009–T013) and reads (T014–T015) precede the US1 tests (T016–T018). It is the MVP and can ship alone.
- **US2 (P2)** depends on Foundational and the US1 write methods (facts/coverage must be saved to be read back); its reads (T019–T020) and tests (T021–T022) are otherwise independent of US1 tests.
- **US3 (P3)** depends on Foundational and the US1 write methods (UPSERT idempotency is exercised by re-saving); T023 read precedes T024–T026 tests.
- **Polish (Phase 6)** runs after the targeted stories are in place; T027 depends on the store existing, T029/T030 after all code, T031 last.

## Parallel Execution Examples

- **Phase 2 kickoff**: run T003, T004, and T005 together — they create three independent files (`errors.py`, `records.py`, `raw.py`) with no shared edits.
- **Cross-story**: once Foundational is done and US1 write methods (T009–T013) exist, the US2 read methods (T019–T020) and the US3 read method (T023) touch distinct methods and could be developed in parallel by different contributors, though all live in `store.py` (coordinate edits).
- **Polish**: T028 (notebook) is `[P]` and independent of the test/gate tasks.

Note: all persistence tests live in the single `tests/test_persistence.py`, so test tasks within a phase are sequential (same file), not parallel.

## Implementation Strategy

- **MVP = User Story 1 (Phases 1–3)**: a working local store that persists a full ADBE analysis and reproduces its latest summary and five-year metric history from a fresh session. This alone satisfies the slice's primary question and is independently demonstrable.
- **Incremental delivery**: add US2 (provenance + coverage semantics) and US3 (idempotency + history + cross-company) as separable increments, each with its own tests, without modifying earlier stories.
- **Constitution alignment**: stdlib-only, storage strictly downstream of computation, explicit failure semantics, and a runnable educational notebook — no Azure/ORM/migration scope introduced.

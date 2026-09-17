---
description: "Task list for Persisted Single-Company Ingestion (OwnerLens Slice 4B)"
---

# Tasks: Persisted Single-Company Ingestion

**Input**: Design documents from `specs/014-persisted-single-company-ingestion/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Test tasks ARE included — the spec's Testing section and success criteria (SC-002 … SC-009)
explicitly require deterministic tests for full/partial/idempotent/history/failure-class/CLI behavior.

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (maps to the prioritized user stories in spec.md)
- Every task lists an exact file path.

## Emphases pinned into these tasks (from user input)

- **UNCHANGED** requires the **same content hash AND compatible calculation/analysis versions**, not
  merely the same ticker (T030, T033).
- **PARTIAL** means "ingestion succeeded but analytical coverage is partial" — never "some DB writes
  failed" (T012, T022, T025 vs T027).
- **Retrieval and persistence failures stay actual `FAILED` outcomes**, not coverage states (T023, T026,
  T027).
- **The thin script and the CLI both call the exact same `ingest_company(...)`** implementation — one
  orchestration only (T014, T018, T021).
- **Fresh-process `show`/query validation** is included so this is a durable workflow, not an in-memory
  pipeline (T016, T020, T034).

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`, docs
in `docs/`. Paths below match [plan.md](plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new module and test skeletons the rest of the work fills in.

- [ ] T001 [P] Create `src/owner_lens/ingestion.py` with a module docstring and an empty `__all__` placeholder (no logic yet).
- [ ] T002 [P] Create `src/owner_lens/cli.py` with a module docstring and an empty `__all__` placeholder (no logic yet).
- [ ] T003 [P] Create `tests/test_ingestion.py` importing fixtures via `from _fixtures import ...` (ADBE/V/COST) with a fake `SecClient` helper stub returning fixture payloads.
- [ ] T004 [P] Create `tests/test_cli.py` skeleton that will drive `owner_lens.cli.main(argv=[...])` without touching `sys.argv`.

**Checkpoint**: Empty modules and test files exist; `uv run ruff check .` stays clean.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Value objects and additive store support required by ALL stories. No story can complete
before this phase is done.

- [ ] T005 [P] Define result value objects in `src/owner_lens/ingestion.py`: `IngestionStatus` (COMPLETE/PARTIAL/UNCHANGED/FAILED), `ProcessingStatus` (fetched/processed/partial/failed), `FailureClass` (retrieval/unsupported/insufficient_data/persistence), frozen dataclasses `IngestionItem`, `IngestionFailure`, and `IngestionResult` per [data-model.md](data-model.md). No orchestration logic yet.
- [ ] T006 Add read `source_snapshot_exists(self, cik: str, content_hash: str) -> bool` to `src/owner_lens/persistence/store.py` (read-only; unknown company/hash returns `False`, no error). Add it to the `OwnerLensStore` protocol in the same file.
- [ ] T007 Add a `transaction()` context manager to `src/owner_lens/persistence/store.py` that defers the per-call commits of `save_*` and commits once on clean exit / rolls back and re-raises on exception; existing `save_*` keep auto-commit when used outside a transaction (4A compatibility preserved).
- [ ] T008 [P] Add tests in `tests/test_persistence.py` for the additive store support: `source_snapshot_exists` true/false cases; `transaction()` rollback leaves zero structured rows while a previously committed raw snapshot remains; existing `save_*` behavior unchanged outside a transaction.

**Checkpoint**: Enums, `IngestionResult`, and store extensions exist and are tested; `uv run mypy src`
is clean.

---

## Phase 3: User Story 1 — Ingest a company and persist everything trustworthy (Priority: P1) 🎯 MVP

**Goal**: `owner-lens ingest <TICKER>` resolves identity, retrieves facts, persists raw-first, runs every
supported layer, persists all trustworthy outputs atomically, returns a structured `IngestionResult`,
and the result is retrievable by a fresh process.

**Independent Test**: Ingest ADBE (and COST) with a fake SEC client + temp store; assert raw payload,
company, snapshot, facts, metrics, analyses, and coverage are persisted, status `COMPLETE` /
`processing_status = processed`, and a brand-new store instance over the same paths returns the persisted
summary/coverage.

### Implementation

- [ ] T009 [US1] In `src/owner_lens/ingestion.py`, implement the retrieval + deterministic serialization stage of `ingest_company(ticker, *, sec_client, store, max_years=5, force=False)`: `resolve_company` → `get_company_facts` → `json.dumps(raw_facts, sort_keys=True).encode()` → `compute_content_hash`, building the `CompanyRecord` and `SourceSnapshotRecord` (source_uri via the SEC template, `processing_status` initially `fetched`).
- [ ] T010 [US1] Implement raw-first persistence in `ingest_company`: `store.save_company(...)` then `store.save_source_snapshot(snapshot, raw_payload=payload)` (writes the raw `<CIK>/<hash>.json` file and the snapshot row) — committed before any structured analytical write.
- [ ] T011 [US1] In `ingest_company`, run the supported layers by reusing existing functions (`owner_economics_from_facts`, `capital_efficiency_from_facts`, `economic_value_from_facts`, `compounding_views_from_facts`, `capital_allocation_from_facts`, `economic_value_summary_from_facts`, `company_coverage`) and build records via the existing pure adapters — no financial recomputation, no writes inside calculation functions.
- [ ] T012 [US1] In `ingest_company`, persist structured outputs inside `store.transaction()` (`save_reported_facts`, `save_derived_metrics`, `save_analysis_result`, `save_coverage`), compute the persisted counts, derive status from the coverage picture (all layers `AVAILABLE` → `COMPLETE` + `processing_status = processed`), update the snapshot `processing_status`, and return a fully populated `IngestionResult`.
- [ ] T013 [US1] Re-export the ingestion public types (`ingest_company`, `IngestionResult`, `IngestionStatus`, `ProcessingStatus`, `FailureClass`, `IngestionItem`, `IngestionFailure`) from `src/owner_lens/__init__.py` (keep `__all__` sorted for ruff RUF022).
- [ ] T014 [US1] Implement the `ingest` subcommand in `src/owner_lens/cli.py` using `argparse` subparsers: parse `TICKER`/`--max-years`/`--force`, `load_settings()`, `build_local_store(settings)` + `store.initialize()`, construct `SecClient(settings.sec_user_agent)`, call `ingest_company(...)`, and set the exit code (0 for COMPLETE/PARTIAL/UNCHANGED, 1 for FAILED, 2 for missing/invalid config).
- [ ] T015 [US1] Implement a pure `format_result(result: IngestionResult) -> str` in `src/owner_lens/cli.py` producing the concise report from [contracts/cli.md](contracts/cli.md) (identity, source snapshot + status + processing, persisted counts, per-layer coverage, overall economic value) — never dumping all raw financial values.
- [ ] T016 [US1] Implement the `show <TICKER>` subcommand in `src/owner_lens/cli.py` that reads the latest persisted summary and coverage from the store (`get_latest_summary`, `get_company_coverage`) with no SEC call, printing a clear "not ingested" message + non-zero exit when absent — this is the durable fresh-process read surface.
- [ ] T017 [US1] Add an `inspect <TICKER>` subcommand in `src/owner_lens/cli.py` preserving the pre-4B raw-facts view, and change `owner_lens.main()` in `src/owner_lens/__init__.py` to delegate to `cli.main(argv=None)`.
- [ ] T018 [US1] Refactor `scripts/ingest_company_facts.py` into a thin wrapper that builds dependencies once and loops over tickers calling the SAME `ingest_company(...)` (delete the duplicated orchestration; the script must own no unique business logic).

### Tests

- [ ] T019 [P] [US1] In `tests/test_ingestion.py`, add full-ingestion tests for ADBE and COST: assert raw payload file + company + snapshot + reported facts + derived metrics + analyses + coverage are persisted, `status == COMPLETE`, `processing_status == processed`, and counts are non-zero.
- [ ] T020 [P] [US1] In `tests/test_ingestion.py`, add a fresh-process persistence test: after ingesting, open a brand-new `SqliteStore` over the same db/raw paths and assert `get_latest_summary`/`get_company_coverage` return the persisted results and every fact/metric/analysis row carries a `snapshot_id` (no in-memory dependency).
- [ ] T021 [P] [US1] In `tests/test_cli.py`, test `ingest` for a COMPLETE company: correct formatted output and exit code 0; missing `OWNER_LENS_SEC_USER_AGENT` → exit 2; and assert the script and the CLI both dispatch to the same `ingest_company` (e.g., monkeypatch `owner_lens.ingestion.ingest_company` and confirm both entry points call it).

**Checkpoint**: MVP works — a fully supported company ingests end-to-end and survives a fresh process.

---

## Phase 4: User Story 2 — Honest partial results and distinct failure classes (Priority: P2)

**Goal**: Companies OwnerLens cannot fully analyze ingest as `PARTIAL` (processed, partial coverage) with
explicit unsupported/insufficient items and reasons; retrieval and persistence problems are distinct
`FAILED` outcomes, never coverage states; nothing is fabricated.

**Independent Test**: Ingest Visa → `PARTIAL` with `diluted_shares` unsupported and its reason, unrelated
layers still persisted, no fabricated per-share value; and each of the four failure classes is asserted
distinctly.

### Implementation

- [ ] T022 [US2] In `src/owner_lens/ingestion.py`, derive `unsupported_items`/`warnings` from the `CompanyCoverage` picture (map `UNSUPPORTED` → `FailureClass.unsupported`, `INSUFFICIENT_DATA`/`PARTIAL` layers → `FailureClass.insufficient_data`, carrying each reason/blocking_input), ensure unrelated layers still persist, and set `status = PARTIAL` + `processing_status = partial` when coverage is not full — WITHOUT treating any of this as a hard failure.
- [ ] T023 [US2] In `src/owner_lens/ingestion.py`, translate exceptions into distinct outcomes: any `SecError` → `IngestionResult(status=FAILED, failure=IngestionFailure(kind=retrieval, ...))` with nothing written; any `PersistenceError` during the structured `transaction()` → `status=FAILED`, `failure.kind=persistence`, structured writes rolled back, raw snapshot retained (set/keep `processing_status` `failed`/`fetched`). These are NOT coverage states.
- [ ] T024 [US2] In `src/owner_lens/cli.py`, extend `format_result` to visibly show partial layers and the exact reason for a `PARTIAL` company, and ensure `FAILED` prints the failure class/message and exits 1.

### Tests

- [ ] T025 [P] [US2] In `tests/test_ingestion.py`, add a Visa partial test: `status == PARTIAL`, `processing_status == partial`, an `unsupported_items` entry for `diluted_shares` with reason, independent layers persisted, and no fabricated per-share value — explicitly assert it is NOT `FAILED`.
- [ ] T026 [P] [US2] In `tests/test_ingestion.py`, add a retrieval-failure test: a fake `SecClient` raising `CompanyResolutionError` → `status == FAILED`, `failure.kind == retrieval`, and zero rows written (company/snapshot/facts absent).
- [ ] T027 [P] [US2] In `tests/test_ingestion.py`, add a persistence-failure test: a store stub raising `StorageWriteError` mid-structured-write → `status == FAILED`, `failure.kind == persistence`, structured rows rolled back, raw snapshot + its row retained — confirming a persistence failure is a failure, not a coverage state.
- [ ] T028 [P] [US2] In `tests/test_ingestion.py`, add an insufficient-data test using a thin-history fixture: the affected analysis is reported as an `insufficient_data` item/warning and the ingestion is `PARTIAL`, not `FAILED`.
- [ ] T029 [P] [US2] In `tests/test_cli.py`, test `ingest` for a PARTIAL company (reason shown, exit 0) and for a FAILED company (failure class shown, exit 1).

**Checkpoint**: Honest partial coverage and the four distinct failure classes are proven.

---

## Phase 5: User Story 3 — Idempotent re-ingestion and historical snapshots (Priority: P3)

**Goal**: Re-ingesting identical source content produces `UNCHANGED` with zero duplicate rows and no
recomputation (keyed on content hash AND compatible calc/analysis versions); changed content creates a
new snapshot while retaining all prior snapshots.

**Independent Test**: Ingest a company twice with identical content → second is `UNCHANGED`, no duplicate
rows; ingest again with a changed-content fixture → exactly one additional snapshot, prior snapshots
retained.

### Implementation

- [ ] T030 [US3] In `src/owner_lens/ingestion.py`, add the `UNCHANGED` short-circuit: when `not force` and `store.source_snapshot_exists(identity.cik, content_hash)` is true AND the current calculation/analysis-rule versions are compatible with what is stored, return `IngestionResult(status=UNCHANGED, ...)` with zero persisted counts and no analytical work; `force=True` bypasses the short-circuit and re-runs (relying on `ON CONFLICT DO NOTHING` for non-duplication).
- [ ] T031 [US3] In `src/owner_lens/ingestion.py`, confirm the changed-content path: a different payload yields a new `content_hash` → a new `SourceSnapshotRecord` is saved and prior snapshots for the CIK are untouched (history preserved; no mutable "latest" row).

### Tests

- [ ] T032 [P] [US3] In `tests/test_ingestion.py`, add an idempotency test: ingest identical content twice → second result `UNCHANGED`; assert zero duplicate rows across raw payload file, `source_snapshots`, `reported_facts`, `derived_metrics`, `analysis_results`, `coverage_results`.
- [ ] T033 [P] [US3] In `tests/test_ingestion.py`, add a version-aware UNCHANGED test: same content hash + current calc/rule versions → `UNCHANGED` (document/verify that a differing calculation/analysis version does not spuriously report `UNCHANGED`).
- [ ] T034 [P] [US3] In `tests/test_ingestion.py`, add a history test: ingest a second, changed-content fixture for the same CIK → exactly one additional `source_snapshots` row, and both snapshots (plus their child rows) remain queryable from a fresh store.
- [ ] T035 [P] [US3] In `tests/test_cli.py`, test `ingest --force` re-runs against an already-stored snapshot and remains non-duplicating (row counts unchanged), and that a normal re-ingest reports the unchanged outcome and exits 0.

**Checkpoint**: Idempotency and source history are proven and durable across processes.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Educational notebook, Feature 4 documentation, quality gates, and live validation.

- [ ] T036 [P] Create `notebooks/11_persisted_ingestion.ipynb` (create as valid empty JSON first, then populate): why ingestion ≠ analysis; fetch → persist raw → normalize → analyze → persist; full ADBE; partial Visa; idempotent re-ingest; historical snapshot; an unseen company; gaps before batch. Keep cells lint-clean (ruff scans notebooks).
- [ ] T037 [P] Create Feature 4 documentation under `docs/` covering the 4A persistence model, 4B persisted single-company ingestion, local SQLite/filesystem architecture, idempotency semantics, source-snapshot history, coverage behavior, and the intentional Azure deferral — understandable without conversation history (SC-010).
- [ ] T038 Run and green the quality gates: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`; confirm all pre-existing Feature 1–4A suites remain unchanged (no regressions, FR-022).
- [ ] T039 Live validation (USER-run): `owner-lens ingest ADBE|V|COST`, then re-`ingest ADBE` (expect `UNCHANGED`), then `show ADBE`; then exploration `owner-lens ingest MSFT|CRM` (discovery, not pass/fail) — document what worked/failed and whether any Feature-3 registry override meets all four FR-023 gates before adding it.
- [ ] T040 [P] Update `specs/014-persisted-single-company-ingestion/quickstart.md` with any command/output deltas discovered during T039, and record the exploration findings (MSFT/CRM gaps) inline.

**Checkpoint**: Feature complete, documented, and live-validated.

---

## Dependencies & Execution Order

- **Setup (Phase 1)** → **Foundational (Phase 2)** → **User Stories (Phases 3–5)** → **Polish (Phase 6)**.
- **Foundational blocks everything**: T005 (result types) blocks all `ingest_company` work; T007
  (`transaction()`) blocks T012 (US1 atomic writes); T006 (`source_snapshot_exists`) blocks T030 (US3).
- **US1 (P1)** is the MVP and depends only on Foundational.
- **US2 (P2)** depends on US1's `ingest_company`/CLI existing (extends status/failure handling).
- **US3 (P3)** depends on US1's `ingest_company` and Foundational T006.
- Within `ingestion.py`, T009→T010→T011→T012 are sequential (same function); T013–T018 follow.
- Story order for incremental delivery: US1 → US2 → US3. Each is independently testable at its checkpoint.

## Parallel Execution Examples

- **Setup**: T001, T002, T003, T004 in parallel (distinct files).
- **Foundational**: T005 and T008 can proceed in parallel with the pair T006+T007 (T008 tests them once
  present); T006 and T007 touch the same `store.py` so keep them sequential.
- **US1 tests**: T019, T020, T021 in parallel after T009–T018.
- **US2 tests**: T025, T026, T027, T028, T029 in parallel after T022–T024.
- **US3 tests**: T032, T033, T034, T035 in parallel after T030–T031.
- **Polish**: T036, T037, T040 in parallel; T038 after all code; T039 after T038.

## Implementation Strategy

- **MVP = Phase 1 + Phase 2 + Phase 3 (US1)**: a fully supported company ingests end-to-end, persists all
  layers, and survives a fresh process — deliverable and demonstrable on its own.
- **Increment 2 = US2**: honest partial coverage + the four distinct failure classes.
- **Increment 3 = US3**: idempotency (`UNCHANGED`) and source-snapshot history.
- **Finish with Polish**: notebook, Feature 4 docs, gates, and live/exploration validation.
- One orchestration only: the script and the CLI both call `ingest_company(...)`; never fork the logic.

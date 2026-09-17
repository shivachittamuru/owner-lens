---
title: "Implementation Plan: Persisted Single-Company Ingestion"
description: Technical plan for OwnerLens Slice 4B, an operational ingestion workflow that persists trustworthy single-company outputs locally
ms.date: 2026-09-17
ms.topic: reference
---

**Branch**: `014-persisted-single-company-ingestion` | **Date**: 2026-09-17 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/014-persisted-single-company-ingestion/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Turn the validated local ingestion prototype (`scripts/ingest_company_facts.py`) into a first-class
OwnerLens ingestion workflow. A new application/domain module `src/owner_lens/ingestion.py` exposes a
single reusable `ingest_company(ticker, *, sec_client, store, max_years=5, force=False)` that resolves
one company's SEC identity, retrieves and deterministically serializes its raw Company Facts, persists
the raw payload first, then runs every Feature 1–3 layer the company's data honestly supports, persists
all trustworthy outputs (facts, derived metrics, analyses, coverage) against a single source snapshot,
and returns a deterministic `IngestionResult`. A new `src/owner_lens/cli.py` module owns argument
parsing, settings loading, dependency composition, result formatting, and exit codes for an `ingest`
subcommand (and an optional `show` subcommand); the console entry point `owner-lens` delegates to it.
The existing script becomes a thin wrapper over `ingest_company` so there is exactly one orchestration.

The workflow reuses the Slice 4A local composition unchanged (`build_local_store` → `SqliteStore` over
`FilesystemRawSnapshotStore`) and adds no cloud dependency. Idempotency is driven by the existing
source-snapshot content hash: an identical `(CIK, content_hash)` yields an `UNCHANGED` result with no
duplicate rows and no recomputation; a changed payload creates a new snapshot while retaining prior
snapshots (source history). Ingestion distinguishes four failure classes — retrieval, unsupported
representation, insufficient data, and persistence — and records a meaningful `processing_status`
(`fetched`, `processed`, `partial`, `failed`) on each snapshot. Raw evidence is committed before
structured analytical writes, and the structured writes run inside one transaction so a mid-write
failure never leaves a misleading half-written analytical snapshot. Golden-company semantics are
preserved (ADBE/COST full, V honest partial). An educational notebook
(`11_persisted_ingestion.ipynb`) and Feature 4 documentation complete the slice.

## Technical Context

**Language/Version**: Python 3.12 (project requirement: Python 3.12 or later).

**Primary Dependencies**: Existing only — `httpx` (SEC retrieval, already present), Python
standard-library `argparse`, `json`, `hashlib`, `dataclasses`, `enum`, `datetime`, `pathlib`, and the
existing `python-dotenv`-backed `owner_lens.config`. No new third-party dependency is introduced
(constitution VI). No Azure SDK, no database driver beyond stdlib `sqlite3` (already used by 4A).

**Storage**: Reuse the Slice 4A local composition unchanged — a local SQLite database file
(`data/ownerlens.db` by default) for structured outputs and a local content-addressed filesystem store
(`data/raw/sec/company_facts/<CIK>/<content-hash>.json`) for raw payloads, both built by
`build_local_store(load_settings())`.

**Testing**: `pytest` with deterministic fixtures reusing `tests/_fixtures.py` (ADBE/V/COST) and a
per-test temporary SQLite file plus a fake/stub `SecClient` that returns fixture payloads (no network).
New `tests/test_ingestion.py` covers full ingestion, partial ingestion, idempotency/`UNCHANGED`,
changed-source history, the four failure classes, and transaction rollback. New `tests/test_cli.py`
covers argument parsing, result formatting, and exit codes. Existing suites must remain green.

**Target Platform**: Local Python environments. Ingestion performs exactly one live SEC retrieval per
company when run for real; all automated tests are offline via an injected fake SEC client.

**Project Type**: Single Python library with a console entry point. Adds two modules
(`ingestion.py`, `cli.py`), minimal additive read/transaction support on the existing store, and reuses
the existing persistence subpackage.

**Performance Goals**: Responsive single-company ingestion (one SEC round-trip plus local writes). No
throughput/concurrency target; batch and large-universe ingestion are explicitly out of scope.

**Constraints**: No change to Feature 1–3 financial semantics; no persistence side effects inside
calculation functions (writes stay in the ingestion service and store); no fabricated/coerced values;
retrieval / unsupported / insufficient-data / persistence failures stay distinct; idempotent
re-ingestion of identical content; historical snapshots retained (no mutable latest row); structured
analytical writes are atomic per snapshot; local-first only (no Azure, no external DB/object store, no
batch, no concurrency, no scheduler, no API/UI, no agents).

**Scale/Scope**: Three golden companies (ADBE/V/COST) as regression fixtures plus at least two
exploration companies (e.g., MSFT/CRM) attempted live for gap discovery. New modules:
`src/owner_lens/ingestion.py`, `src/owner_lens/cli.py`; additive store methods; refactored thin
`scripts/ingest_company_facts.py`; new `tests/test_ingestion.py` and `tests/test_cli.py`; notebook
`notebooks/11_persisted_ingestion.ipynb`; Feature 4 documentation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness (I)**: PASS. Ingestion orchestrates already-validated Feature 1–3 layers and
  recomputes nothing new; golden-company semantics are preserved and existing tests stay green. Any
  source-concept override goes through the Feature 3 canonical registry, never through orchestration.
* **Traceability (II)**: PASS. Every persisted fact, metric, and analysis links to one source snapshot
  identified by content hash, source URI, and CIK; raw evidence is stored and referenced. The result
  reports counts and coverage tied to that snapshot.
* **Deterministic computation (III)**: PASS. Ingestion is deterministic orchestration; no AI behavior is
  introduced. Status and coverage are derived from deterministic layer outcomes.
* **Definitions and tests (IV)**: PASS. `IngestionResult`, its status enum, `processing_status` values,
  and idempotency/transaction semantics are documented contracts with focused tests; a notebook
  demonstrates the workflow.
* **Fail loudly (V)**: PASS. Missing/unsupported data becomes explicit coverage and typed failure
  classes; nothing is fabricated. A processed-but-partial company is reported honestly, not as success
  or silent failure.
* **Current-release scope (VI)**: PASS. Only existing dependencies and the 4A local store are used; no
  Azure, no batch, no concurrency, no API/UI. New abstractions (ingestion service, CLI module, store
  transaction/read helpers) each map to a stated requirement.

### Post-Design Evaluation

* **Provider boundary**: PASS. `ingest_company` depends on the `SecClient` retrieval contract and the
  persistence store contract via injection; it adds no new provider knowledge and no taxonomy
  generalization.
* **Minimal contract**: PASS. The service exposes one orchestration function plus a result type; the
  store gains only a snapshot-existence read and a scoped transaction context, both tied to FR-014 and
  FR-017. No generic job/queue/pipeline abstraction is introduced.
* **Local-first delivery**: PASS. Everything runs and is tested locally with SQLite + filesystem and an
  injected fake SEC client; live validation uses the existing single retrieval per company.
* **Reproducibility**: PASS. Tests use fixed ADBE/V/COST fixtures, a temp database, and deterministic
  payload serialization for stable content hashes; idempotency is verified by re-ingesting identical
  content.
* **Failure integrity**: PASS. Persistence failures stay `PersistenceError`-typed and distinct from
  financial `ConceptNotFoundError`/insufficient-data; the ingestion result keeps the four classes
  separate.

No constitutional violations require justification; the Complexity Tracking table is intentionally
omitted.

## Project Structure

### Documentation (this feature)

```text
specs/014-persisted-single-company-ingestion/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── ingestion-service.md
│   └── cli.md
├── checklists/
│   └── requirements.md  # /speckit-specify output
└── tasks.md             # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/owner_lens/
├── ingestion.py         # NEW: ingest_company() + IngestionResult/IngestionStatus/FailureClass/ProcessingStatus
├── cli.py               # NEW: argparse subcommands (ingest, optional show), formatting, exit codes
├── __init__.py          # main() delegates to cli.main(); re-export ingestion public types
├── config.py            # EXISTING (4A local-first): load_settings, build_local_store — reused unchanged
├── sec.py               # EXISTING: SecClient contract consumed by ingestion (injected)
└── persistence/
    ├── store.py         # EXTEND additively: source-snapshot existence read + scoped transaction context
    ├── raw.py           # EXISTING: FilesystemRawSnapshotStore, compute_content_hash — reused unchanged
    ├── adapters.py      # EXISTING: pure domain->record adapters — reused unchanged
    ├── records.py       # EXISTING: SourceSnapshotRecord etc. — reused unchanged
    └── errors.py        # EXISTING: PersistenceError hierarchy — reused unchanged

scripts/
└── ingest_company_facts.py   # REFACTOR: thin wrapper looping over tickers -> ingest_company()

tests/
├── test_ingestion.py    # NEW: full/partial/idempotent/history/failure-classes/transaction
├── test_cli.py          # NEW: arg parsing, formatting, exit codes
├── test_persistence.py  # EXTEND: snapshot-existence read + transaction rollback
└── _fixtures.py         # EXISTING: ADBE/V/COST fixture builders — reused

notebooks/
└── 11_persisted_ingestion.ipynb   # NEW: educational orchestration notebook

docs/
└── (Feature 4 documentation)      # NEW/UPDATED: 4A model + 4B ingestion, idempotency, history, coverage, Azure deferred
```

**Structure Decision**: Single-project Python library. Ingestion orchestration lives in a new
`ingestion.py` at the application/domain boundary (not in `scripts/` and not inside financial modules);
CLI concerns live in a new `cli.py`; the console entry point delegates to `cli.main()`. The existing
4A persistence subpackage and local-config composition are reused, with only additive, requirement-tied
extensions to the store (snapshot-existence read for idempotency; a scoped transaction context for
atomic structured writes).

## Complexity Tracking

No constitutional violations; this section is intentionally omitted.

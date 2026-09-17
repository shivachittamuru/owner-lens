---
title: "Implementation Plan: Persistence Model and Storage Boundary"
description: Technical plan for OwnerLens Slice 4A, a local-first durable persistence layer downstream of deterministic computation
ms.date: 2026-09-04
ms.topic: reference
---

**Branch**: `013-persistence-storage-boundary` | **Date**: 2026-09-04 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/013-persistence-storage-boundary/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Introduce OwnerLens's first persistence layer as a small, self-contained subpackage
(`src/owner_lens/persistence/`) that stores the **outputs** of the existing Feature 1–3 pipeline —
company identity, source-snapshot metadata, canonical reported facts with provenance, deterministic
derived metrics, Feature 2 analysis outputs with ordered drivers, and coverage states — into a local
durable store. Persistence sits strictly downstream of trustworthy computation: it performs no SEC
normalization, no financial calculation, and no classification, and financial functions gain no
hidden write side effects.

The concrete local implementation uses the Python standard-library `sqlite3` module (no new
dependency, honoring constitution VI) with hand-written SQL and SQLite UPSERT for idempotency. Exact
monetary values and share counts (already `int` in the domain) are stored as SQLite `INTEGER` and
round-trip exactly; derived ratios (already Python `float` in the domain) are stored as `REAL`, which
is IEEE-754 floating point — it preserves practical analytical precision, not a bit-perfect decimal
representation, so ratio round-trips are validated with tolerances rather than exact equality.
Coverage states (`AVAILABLE`, `STRUCTURALLY_ABSENT`, `UNSUPPORTED`,
`INSUFFICIENT_DATA`) and genuine reported zero are preserved as explicit values and are never
collapsed into SQL `NULL`. Every persisted fact, metric, and analysis is tied to a source snapshot so
multiple historical snapshots coexist rather than a single mutable latest row. Raw SEC payloads are
referenced (by content hash) and stored on the local filesystem, not embedded in the relational
model, so the design maps cleanly to Azure Blob + PostgreSQL in Slice 4B. A distinct
`PersistenceError` hierarchy keeps database failures from being confused with financial errors. An
educational notebook (`09_persistence_model.ipynb`) demonstrates the boundary end-to-end for
ADBE/V/COST.

## Technical Context

**Language/Version**: Python 3.12 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard-library `sqlite3`, `dataclasses`, `enum`, `hashlib`,
`pathlib`, `datetime`, `json`, and `typing` only. No new third-party dependency is introduced.
SQLAlchemy is explicitly rejected in research.

**Storage**: Local SQLite database file for the relational model (schema created by the store on
initialization); local filesystem directory for raw SEC payloads referenced by content hash. No
hosted database or object store.

**Testing**: `pytest` with deterministic fixtures reusing `tests/_fixtures.py` (ADBE/V/COST) plus a
temporary SQLite file per test (`tmp_path`). New `tests/test_persistence.py` covers schema, identity,
snapshots, reported facts, derived metrics, analysis results, coverage, and the five query use cases;
existing Feature 1–3 suites must remain green.

**Target Platform**: Local Python environments; no network access required for persistence (the
optional live validation reuses the existing single Company Facts retrieval per company).

**Project Type**: Single Python library with a new internal subpackage; existing console entry point
unchanged.

**Performance Goals**: Deterministic local reads/writes for a handful of companies and ~5 fiscal
years each; no throughput target beyond responsive local validation. Batch/large-universe ingestion
is out of scope.

**Constraints**: Persistence-only slice — no change to financial-analysis semantics; no side effects
in calculation functions; no fabricated or coerced values; coverage/absence/unsupported/insufficient
distinctions preserved relationally; no floating-point storage of exact monetary values or share
counts; idempotent repeated processing; historical snapshots preserved; no Azure SDK, no
infrastructure-as-code, no migration framework, no ORM hierarchy, no async, no connection pool.

**Scale/Scope**: Three golden companies (ADBE/V/COST); one new `persistence` subpackage (store,
records, raw payload store, error hierarchy, domain→record adapters); one new test module; one
educational notebook.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness (I)**: PASS. Persistence stores already-validated outputs and recomputes
  nothing; financial semantics are unchanged and existing tests must stay green.
* **Traceability (II)**: PASS. Canonical facts persist their source concept, form, filing date,
  accession, and source-snapshot reference; derived metrics and analyses link back to the company and
  fiscal period; snapshots record source URI and content hash.
* **Deterministic computation (III)**: PASS. Storage is deterministic and additive; no AI behavior is
  introduced and no interpretive free-form text is persisted.
* **Definitions and tests (IV)**: PASS. Persistence record shapes and idempotency keys are documented
  contracts; controlled tests cover round-trip fidelity, provenance, coverage, idempotency, and the
  query use cases; a notebook demonstrates the boundary.
* **Fail loudly (V)**: PASS. A dedicated `PersistenceError` hierarchy surfaces connection, schema,
  write, and read failures explicitly; unavailable values are absence + explicit coverage rows, never
  fabricated or NULL-as-meaning.
* **Current-release scope (VI)**: PASS. Only stdlib `sqlite3` and local filesystem are used; no Azure
  SDK, ORM hierarchy, migration framework, async, or connection pool. Each capability maps to a listed
  query use case.

### Post-Design Evaluation

* **Provider boundary**: PASS. The persistence subpackage depends on OwnerLens domain outputs, not on
  SEC retrieval internals; it adds no provider knowledge.
* **Minimal contract**: PASS. The store exposes domain-oriented save/read operations tied to concrete
  use cases; no generic repository/DAO/CRUD abstraction.
* **Local-first delivery**: PASS. Everything runs and is tested locally with SQLite + filesystem;
  hosted infrastructure is deferred to Slice 4B by design (raw payloads referenced, not embedded).
* **Reproducibility**: PASS. Tests use fixed ADBE/V/COST fixtures and a temp database; content-hash
  snapshot identity makes repeated processing idempotent.
* **Failure integrity**: PASS. Persistence errors are distinct types and are never transformed into
  `ConceptNotFoundError`/insufficient-data semantics.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/013-persistence-storage-boundary/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── persistence-api.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
└── owner_lens/
    └── persistence/
        ├── __init__.py      # NEW: public persistence exports
        ├── errors.py        # NEW: PersistenceError hierarchy (connection/schema/write/read)
        ├── records.py       # NEW: persistence record dataclasses (company, snapshot, fact,
        │                     #      derived metric, analysis result, driver, coverage)
        ├── raw.py           # NEW: RawSnapshotStore protocol + FilesystemRawSnapshotStore
        ├── adapters.py      # NEW: pure domain-output -> record conversion (no writes)
        └── store.py         # NEW: OwnerLensStore protocol + SqliteStore (schema DDL + SQL)

tests/
├── _fixtures.py             # Reused ADBE/V/COST fixtures (extend only if a scenario needs it)
└── test_persistence.py      # NEW: schema, identity, snapshots, facts, metrics, analysis,
                             #      coverage, idempotency, and the five query use cases

notebooks/
└── 09_persistence_model.ipynb  # NEW educational artifact
```

**Structure Decision**: Add one cohesive `persistence` subpackage under the existing single package
rather than touching the financial modules. The subpackage is layered: `errors` and `records` are
leaf modules; `raw` handles the raw-payload boundary; `adapters` converts existing domain dataclasses
(`OwnerEconomicsRow`, `CapitalEfficiencyRow`, `EconomicValueSnapshot`, `EconomicCompoundingView`,
`CapitalAllocationRow`, `EconomicValueSummary`, `CompanyCoverage`, `AnnualObservation`, and
`CompanyIdentity`) into persistence records with no side effects; `store` owns the SQLite schema and
domain-oriented operations. Financial modules are not modified, guaranteeing storage independence and
regression safety. Package-level exports are added in `owner_lens/__init__.py` for the store, records,
and error types.

## Complexity Tracking

No violations or complexity exceptions. The persistence layer uses only the standard library, exposes
domain-oriented operations (not a generic repository), references raw payloads instead of embedding
them, and introduces no ORM, migration framework, async access, or connection pool. Any capability
beyond the documented query use cases is deferred to Slice 4B.

---
title: "Data Model: Persisted Single-Company Ingestion"
description: Phase 1 data model for OwnerLens Slice 4B ingestion result, status/failure enums, and additive store operations
ms.date: 2026-09-17
ms.topic: reference
---

# Data Model — Persisted Single-Company Ingestion (Slice 4B)

This slice introduces **no new persisted tables**. It reuses the Slice 4A relational schema
(`companies`, `source_snapshots`, `reported_facts`, `derived_metrics`, `analysis_results`,
`analysis_drivers`, `coverage_results`, `schema_meta`) and the filesystem raw store unchanged. The new
model elements are (a) an in-memory, deterministic `IngestionResult` value returned by the ingestion
service, (b) small closed enums, and (c) additive read/transaction operations on the existing store.

## New value objects (in `src/owner_lens/ingestion.py`)

### `IngestionStatus` (enum)

| Value       | Meaning                                                                                   |
|-------------|-------------------------------------------------------------------------------------------|
| `COMPLETE`  | Company ingested and every analytical layer is fully available (all layers `AVAILABLE`).  |
| `PARTIAL`   | Company ingested; raw + trustworthy layers persisted, but some layer is unsupported/insufficient. |
| `UNCHANGED` | Source content identical to a stored snapshot; no duplicate rows and no recomputation.     |
| `FAILED`    | Ingestion did not complete because of a retrieval or persistence failure.                  |

State selection is deterministic: `UNCHANGED` short-circuits before layer work; `FAILED` results from a
retrieval or persistence exception; otherwise `COMPLETE` when the coverage picture is full (every layer
state `AVAILABLE`), else `PARTIAL`.

### `ProcessingStatus` (enum) — persisted in `source_snapshots.processing_status`

| Value       | Meaning                                                                        |
|-------------|--------------------------------------------------------------------------------|
| `fetched`   | Raw payload stored and snapshot recorded; structured analysis not completed.   |
| `processed` | All supported layers produced and persisted; full coverage.                    |
| `partial`   | Raw + trustworthy layers persisted; some layers unsupported/insufficient.      |
| `failed`    | A persistence error prevented completing the structured writes.                |

Mapping to `IngestionStatus`: `COMPLETE`→`processed`, `PARTIAL`→`partial`, `FAILED`(persistence)→
`failed` (with the raw snapshot possibly at `fetched`), `UNCHANGED`→(unchanged; existing status retained).

### `FailureClass` (enum)

| Value               | Source                                                                              |
|---------------------|-------------------------------------------------------------------------------------|
| `retrieval`         | Any `SecError` (unresolved ticker, transport, HTTP status, malformed, identity mismatch). |
| `unsupported`       | A required metric OwnerLens cannot safely normalize (coverage `UNSUPPORTED`).        |
| `insufficient_data` | A trustworthy metric exists for too short a history for a specific analysis.         |
| `persistence`       | Any `PersistenceError` (connection, schema, write, read).                            |

`retrieval` and `persistence` are hard failures (`FAILED`). `unsupported` and `insufficient_data` are
soft: they populate `unsupported_items`/`warnings` and drive `PARTIAL`, never aborting unrelated layers.

### `IngestionItem` (value object)

Represents one soft finding for the result surface.

| Field    | Type            | Notes                                                        |
|----------|-----------------|-------------------------------------------------------------|
| `kind`   | `FailureClass`  | `unsupported` or `insufficient_data`.                       |
| `subject`| `str`           | Input or layer name (e.g., `diluted_shares`, `compounding`).|
| `reason` | `str \| None`   | Human-readable reason from the coverage picture.            |

### `IngestionResult` (value object) — returned by `ingest_company`

| Field                     | Type                          | Notes                                                            |
|---------------------------|-------------------------------|------------------------------------------------------------------|
| `company`                 | `CompanyRecord`               | Resolved SEC identity (CIK/ticker/name). Present unless retrieval failed before resolution. |
| `source_snapshot`         | `SourceSnapshotRecord \| None`| The snapshot ingested against; `None` only on pre-snapshot retrieval failure. |
| `status`                  | `IngestionStatus`             | `COMPLETE`/`PARTIAL`/`UNCHANGED`/`FAILED`.                       |
| `processing_status`       | `ProcessingStatus`            | Mirrors what was written to the snapshot row.                    |
| `persisted_fact_count`    | `int`                         | Reported facts written for this snapshot (0 on `UNCHANGED`).     |
| `persisted_metric_count`  | `int`                         | Derived metrics written for this snapshot.                       |
| `analysis_count`          | `int`                         | Analysis results written for this snapshot.                      |
| `coverage`                | `CompanyCoverage \| None`     | The deterministic per-input/per-layer coverage picture.          |
| `warnings`                | `tuple[str, ...]`             | Non-fatal notes (e.g., insufficient-data layers).               |
| `unsupported_items`       | `tuple[IngestionItem, ...]`   | Explicit unsupported/insufficient findings with reasons.         |
| `failure`                 | `IngestionFailure \| None`    | Present only when `status == FAILED`.                            |

No ambiguous success boolean is exposed (FR-006).

### `IngestionFailure` (value object)

| Field     | Type           | Notes                                             |
|-----------|----------------|---------------------------------------------------|
| `kind`    | `FailureClass` | `retrieval` or `persistence`.                     |
| `message` | `str`          | Safe, human-readable summary of the typed error.  |

## Relationships

```text
IngestionResult
  ├─ company            -> CompanyRecord            (persistence.records, existing)
  ├─ source_snapshot    -> SourceSnapshotRecord     (persistence.records, existing)
  ├─ coverage           -> CompanyCoverage          (coverage, existing)
  ├─ unsupported_items  -> IngestionItem[]          (new)
  └─ failure            -> IngestionFailure         (new)

SourceSnapshotRecord (existing) --1:N--> reported_facts / derived_metrics / analysis_results / coverage_results
CompanyRecord (existing)         --1:N--> SourceSnapshotRecord   (history; no mutable "latest" row)
```

## Additive store operations (in `src/owner_lens/persistence/store.py`)

These are strictly additive; existing 4A method signatures and behavior are unchanged.

### `source_snapshot_exists(cik: str, content_hash: str) -> bool`

Returns whether a snapshot row exists for the given CIK and content hash. Backs the `UNCHANGED`
short-circuit (FR-014/FR-016). Read-only; unknown company or hash ⇒ `False` (no error), consistent with
the existing 4A read conventions.

### `transaction()` context manager

Provides a single atomic unit for the four structured `save_*` calls (FR-017). Within the context, the
per-call commits are deferred; on clean exit the store commits once, and on any exception it rolls back
and re-raises (translated to `StorageWriteError` where appropriate). Used outside a transaction, the
existing `save_*` methods keep their current auto-commit behavior, so 4A tests are unaffected.

## Validation & invariants

- **Provenance (SC-006)**: every persisted fact/metric/analysis references exactly one
  `source_snapshot` (enforced by existing schema FKs and unique keys).
- **No fabrication (FR-009)**: unsupported/insufficient metrics yield coverage records and
  `unsupported_items`, never a substituted value; absence = missing row + coverage reason.
- **Idempotency (FR-014)**: `(CIK, provider, type, content_hash)` uniqueness + `ON CONFLICT DO NOTHING`
  guarantees zero duplicate rows on identical re-ingestion; `UNCHANGED` is returned without writes.
- **History (FR-015)**: a changed payload yields a new `content_hash` ⇒ a new snapshot row; prior
  snapshots and their child rows remain.
- **Atomicity (FR-017)**: structured writes for one snapshot are all-or-nothing; raw snapshot may exist
  independently.
- **Exact vs approximate (4A parity)**: money/shares persist as `INTEGER` (exact); ratios persist as
  `REAL` (approximate; validated with tolerances, not equality).
- **Failure separation (FR-011)**: `FailureClass` keeps retrieval / unsupported / insufficient / storage
  distinct; a `PersistenceError` is never surfaced as a financial error and vice versa.

## Golden-company expectations (regression anchors)

| Company | Expected status  | processing_status | Coverage highlight                                              |
|---------|------------------|-------------------|----------------------------------------------------------------|
| ADBE    | `COMPLETE`       | `processed`       | All layers `AVAILABLE`; overall economic value `IMPROVING`.     |
| COST    | `COMPLETE`       | `processed`       | All layers `AVAILABLE`; low-margin retailer not penalized.      |
| V       | `PARTIAL`        | `partial`         | `diluted_shares` `UNSUPPORTED`; owner-economics/compounding partial; reason recorded; nothing fabricated. |

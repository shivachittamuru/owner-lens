---
title: Persistence Public API Contract
description: Library contract for the OwnerLens Slice 4A storage boundary, raw payload store, records, and error hierarchy
ms.date: 2026-09-04
ms.topic: reference
---

## Scope

This slice adds a `persistence` subpackage that stores OwnerLens outputs and reads them back. It
introduces no analytical feature and modifies no financial module. Existing Feature 1–3 entry points
keep their signatures and behavior. The contract below defines the storage boundary, the raw-payload
store, the record types, and the persistence error hierarchy. Concrete names may differ slightly if a
cleaner design emerges during implementation; the behavior is the contract.

## Error hierarchy

```text
PersistenceError(Exception)
├── StorageConnectionError   # cannot open/create/setup the store
├── SchemaVersionError       # stored schema version incompatible with running code
├── StorageWriteError        # a write/save failed
└── StorageReadError         # a read/query failed
```

Contract:

* Persistence errors are wholly separate from `SecError`, `ConceptNotFoundError`,
  `AmbiguousValueError`, and any insufficient-data semantics.
* The store MUST NOT transform a database failure into a financial error, and MUST NOT swallow it.

## Raw snapshot store

```text
class RawSnapshotStore(Protocol):
    def put(self, content_hash: str, payload: bytes) -> str: ...   # returns a raw_object_ref
    def get(self, content_hash: str) -> bytes: ...
    def exists(self, content_hash: str) -> bool: ...

class FilesystemRawSnapshotStore(RawSnapshotStore):
    def __init__(self, root: Path) -> None: ...
```

Contract:

* `put` is idempotent by `content_hash`: storing identical bytes twice yields the same
  `raw_object_ref` and does not duplicate data.
* `get` raises `StorageReadError` if the hash is unknown; `exists` never raises for a missing hash.
* The filesystem implementation writes under `root`, keyed by `content_hash`. A future
  `BlobRawSnapshotStore` can satisfy the same protocol with no relational schema change.
* The relational store references the raw payload by `content_hash`/`raw_object_ref`; it never embeds
  the JSON blob.

## Record types

Frozen dataclasses in `persistence/records.py` carry data only (no behavior), using the same Python
types as the domain (`int` money/shares, `float` ratios). See
[data-model.md](../data-model.md#record-dataclasses-persistencerecordspy) for full field lists:
`CompanyRecord`, `SourceSnapshotRecord`, `ReportedFactRecord`, `DerivedMetricRecord`,
`AnalysisResultRecord`, `AnalysisDriverRecord`, `CoverageResultRecord`.

## Storage boundary

```text
class OwnerLensStore(Protocol):
    # Lifecycle
    def initialize(self) -> None: ...

    # Writes (explicit; never called from financial calculation functions)
    def save_company(self, company: CompanyRecord) -> None: ...
    def save_source_snapshot(self, snapshot: SourceSnapshotRecord) -> None: ...
    def save_reported_facts(self, facts: Sequence[ReportedFactRecord], *,
                            snapshot: SourceSnapshotRecord) -> None: ...
    def save_derived_metrics(self, metrics: Sequence[DerivedMetricRecord], *,
                             snapshot: SourceSnapshotRecord) -> None: ...
    def save_analysis_result(self, result: AnalysisResultRecord, *,
                            snapshot: SourceSnapshotRecord) -> None: ...
    def save_coverage(self, coverage: Sequence[CoverageResultRecord], *,
                     snapshot: SourceSnapshotRecord) -> None: ...

    # Reads (the five query use cases)
    def get_company(self, cik: str) -> CompanyRecord | None: ...
    def get_metric_history(self, cik: str, metric: str, *, limit: int | None = None
                          ) -> tuple[DerivedMetricRecord, ...]: ...
    def get_fact_provenance(self, cik: str, canonical_metric: str, fiscal_year: int
                           ) -> ReportedFactRecord | None: ...
    def get_latest_summary(self, cik: str) -> AnalysisResultRecord | None: ...
    def get_company_coverage(self, cik: str) -> tuple[CoverageResultRecord, ...]: ...
    def get_latest_metric_across_companies(self, metric: str, ciks: Sequence[str]
                                          ) -> dict[str, DerivedMetricRecord]: ...

class SqliteStore(OwnerLensStore):
    def __init__(self, db_path: Path, *, raw_store: RawSnapshotStore | None = None) -> None: ...
```

### Write contract

* `initialize` creates the schema if absent (`CREATE TABLE IF NOT EXISTS`), inserts `schema_version`
  only if absent, and is a safe no-op on repeat. It raises `SchemaVersionError` if an existing store's
  `schema_version` is incompatible.
* Every save is idempotent via the natural keys in [data-model.md](../data-model.md#entity-summary):
  re-saving identical data with the same snapshot creates no duplicate rows and does not mutate
  existing rows (except `companies` current attributes, updated by UPSERT).
* Saves resolve the company by `cik` and the snapshot by content hash; facts/metrics/analysis/coverage
  are scoped to `snapshot.id`, so a new snapshot never overwrites an earlier one.
* Writes MUST occur only through these explicit calls; no financial calculation function performs a
  write. Domain→record conversion happens in `persistence/adapters.py` with no side effects.
* Exact monetary values and share counts persist as `INTEGER` and round-trip exactly, with no silent
  rounding. Derived ratios persist as `REAL` (IEEE-754 floating point): they preserve practical
  analytical precision, **not** a bit-perfect decimal representation, so callers and tests compare
  ratios with tolerances rather than exact decimal equality.
* On any write failure the store raises `StorageWriteError`. A genuine conflicting value under the same
  natural key (distinct from an identical repeat) raises `StorageWriteError` rather than silently
  keeping the last write.

### Read contract

* `get_metric_history` returns derived-metric records for one company and metric ordered by
  `fiscal_year`, most recent last, limited to the newest `limit` fiscal years when given (FR-020).
* `get_fact_provenance` returns the reported fact for a company/metric/fiscal year including
  `concept`, `form`, `filed`, `accession`, and its snapshot linkage (FR-021).
* `get_latest_summary` returns the most recent `economic_value_summary` analysis result for the
  company, with its ordered drivers populated (FR-022).
* `get_company_coverage` returns the coverage rows for the company's latest snapshot, preserving each
  `state` (FR-023).
* `get_latest_metric_across_companies` returns each company's latest value for one metric (FR-024); it
  is retrieval only — no comparison, ranking, or scoring.
* A read for an unknown company/metric returns an explicit empty result (`None`, empty tuple, or empty
  dict), never a fabricated value and never a financial error. On a genuine query failure the store
  raises `StorageReadError`.

## Coverage and missing-data guarantees

* The four coverage states (`AVAILABLE`, `STRUCTURALLY_ABSENT`, `UNSUPPORTED`, `INSUFFICIENT_DATA`)
  plus layer-only `PARTIAL`/`UNAVAILABLE` persist and retrieve as explicit `state` strings and are
  never collapsed into SQL `NULL`.
* A genuine reported zero persists as a `reported_facts` row with `value = 0`, distinct from an absent
  or unsupported metric (which has no fact row and a `coverage_results` reason).
* Visa's unsupported diluted shares retrieve as `UNSUPPORTED`; a Feature 2 insufficient layer retrieves
  as `INSUFFICIENT_DATA`.

## Idempotency and history guarantees

* Re-persisting an identical source snapshot (same content hash) plus its identical facts/metrics/
  analysis/coverage produces zero additional rows.* Persisting a distinct later snapshot for the same company retains both snapshots and all their
  dependent rows; each is individually retrievable.
* Version context: *same company + same source content hash + same calculation/analysis-rule version*
  is an idempotent repeat, while *same source snapshot + a newer calculation or analysis-rule version*
  writes a new derived-metric/analysis-result row that coexists with the prior one (the version is part
  of the natural key). This lets a later ROIC or Feature 2 rule change be recorded without overwriting
  earlier results, distinguishing *data changed* from *logic changed*.

## Package exports

`owner_lens/__init__.py` additionally exports the store, record types, raw-store types, and the
`PersistenceError` hierarchy so callers can `from owner_lens import SqliteStore, ...`. Financial
modules are unchanged and do not import the persistence subpackage.

## Regression contract

Every existing Feature 1–3 output, classification, value, and provenance is preserved, and all
existing tests continue to pass. The persistence subpackage adds no import into any financial module.

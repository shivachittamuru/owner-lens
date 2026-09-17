---
title: "Contract: Ingestion Service"
description: Behavioral contract for owner_lens.ingestion.ingest_company and its additive store support
ms.date: 2026-09-17
ms.topic: reference
---

# Contract — Ingestion Service (`owner_lens.ingestion`)

## Public surface

```python
def ingest_company(
    ticker: str,
    *,
    sec_client: SecClient,
    store: OwnerLensStore,
    max_years: int = 5,
    force: bool = False,
) -> IngestionResult: ...
```

Plus the value types from the data model: `IngestionResult`, `IngestionStatus`, `ProcessingStatus`,
`FailureClass`, `IngestionItem`, `IngestionFailure`. All are re-exported at the `owner_lens` top level.

Dependencies are **injected**: `sec_client` satisfies the existing `SecClient` retrieval contract;
`store` satisfies the existing `OwnerLensStore` protocol. The function opens no network client and reads
no configuration itself — the CLI/script composes those.

## Behavioral contract

### Preconditions

- `ticker` is a non-empty string (whitespace is trimmed; empty ⇒ retrieval failure via
  `MalformedTickerError`).
- `store` has been initialized (`store.initialize()` called) by the caller.
- `max_years >= 1`.

### Sequence (happy path)

1. Resolve identity: `sec_client.resolve_company(ticker)`.
2. Retrieve facts: `sec_client.get_company_facts(identity)`.
3. Serialize deterministically: `json.dumps(raw_facts, sort_keys=True).encode()`; compute
   `content_hash = compute_content_hash(payload)`.
4. Idempotency check: if `not force` and `store.source_snapshot_exists(identity.cik, content_hash)` ⇒
   return `IngestionResult(status=UNCHANGED, ...)` with zero persisted counts and the existing snapshot
   reference; **no writes, no recomputation**.
5. Persist raw-first: `store.save_company(company_record(identity))`; then
   `store.save_source_snapshot(snapshot, raw_payload=payload)` (writes the raw file and the snapshot
   row; `processing_status` initially `fetched`).
6. Run supported layers (reusing existing `*_from_facts` functions and `company_coverage`), producing
   owner-economics, capital-efficiency, economic-value snapshots, compounding views, capital-allocation
   rows, economic summary, and the coverage picture.
7. Persist structured outputs inside `store.transaction()`: reported facts, derived metrics, analysis
   results, coverage.
8. Set final `processing_status` (`processed` if full coverage, else `partial`) and return
   `IngestionResult` with accurate counts, coverage, warnings, and unsupported items.

### Status & processing-status outcomes

| Condition                                              | `status`    | `processing_status` | Writes                          |
|--------------------------------------------------------|-------------|---------------------|---------------------------------|
| All layers `AVAILABLE`                                 | `COMPLETE`  | `processed`         | full set                        |
| Some layer unsupported/insufficient, rest persisted    | `PARTIAL`   | `partial`           | raw + all trustworthy layers    |
| Snapshot already exists, `force` false                 | `UNCHANGED` | (unchanged)         | none                            |
| `SecError` before/at retrieval                         | `FAILED`    | (no snapshot)       | none                            |
| `PersistenceError` during structured writes            | `FAILED`    | `failed`/`fetched`  | raw retained; structured rolled back |

### Idempotency contract (FR-014/FR-015/FR-016)

- Re-ingesting identical content (same CIK + `content_hash`) with `force=False` ⇒ `UNCHANGED`, zero
  duplicate rows across raw payload, snapshot, facts, metrics, analyses, coverage.
- `force=True` re-runs layers; existing `ON CONFLICT DO NOTHING` UPSERTs guarantee no duplicates.
- Changed content ⇒ new `content_hash` ⇒ new snapshot row; all prior snapshots retained.

### Failure contract (FR-011)

- Retrieval errors (`SecError` and subclasses) ⇒ `FAILED`, `failure.kind == retrieval`, nothing written.
- Persistence errors (`PersistenceError` and subclasses) ⇒ `FAILED`, `failure.kind == persistence`, raw
  snapshot may remain, structured writes rolled back.
- Unsupported metric ⇒ coverage `UNSUPPORTED` + `IngestionItem(kind=unsupported, ...)`; does not abort
  unrelated layers; contributes to `PARTIAL`.
- Insufficient history ⇒ coverage `INSUFFICIENT_DATA`/`PARTIAL` + `IngestionItem(kind=insufficient_data,
  ...)` / warning; not a hard failure.

### Postconditions

- On `COMPLETE`/`PARTIAL`: the raw payload, company, snapshot, and all trustworthy layers are persisted
  and retrievable by a fresh process (no in-memory dependency).
- On `UNCHANGED`: store state is byte-for-byte unchanged.
- On `FAILED`: no misleading half-written structured snapshot exists.

### Invariants

- No financial value is fabricated, coerced, or backfilled (FR-009).
- No persistence write occurs inside a financial calculation function; all writes are in `ingest_company`
  via the store (FR-005).
- Golden-company semantics preserved: ADBE/COST ⇒ `COMPLETE`; V ⇒ `PARTIAL` with `diluted_shares`
  unsupported (FR-022).

## Additive store contract (`owner_lens.persistence`)

```python
def source_snapshot_exists(self, cik: str, content_hash: str) -> bool: ...

@contextmanager
def transaction(self) -> Iterator[None]: ...
```

- `source_snapshot_exists`: read-only; returns `False` for unknown company or hash (no error).
- `transaction`: commits once on clean exit; rolls back and re-raises on exception; nesting is not
  required for this slice. Existing `save_*` methods remain valid outside a transaction with their
  current auto-commit behavior (4A compatibility).

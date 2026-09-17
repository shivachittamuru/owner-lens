---
title: "Research: Persisted Single-Company Ingestion"
description: Phase 0 research resolving idempotency, transaction, processing-status, failure-class, CLI, and store-extension decisions for OwnerLens Slice 4B
ms.date: 2026-09-17
ms.topic: reference
---

# Phase 0 Research — Persisted Single-Company Ingestion (Slice 4B)

All decisions below are grounded in the existing Slice 4A persistence code
(`src/owner_lens/persistence/`), the existing SEC retrieval (`src/owner_lens/sec.py`), the local
config composition (`src/owner_lens/config.py`), and the validated prototype
(`scripts/ingest_company_facts.py`). No new dependency is introduced.

## 1. Where the reusable orchestration lives

**Decision**: Add `src/owner_lens/ingestion.py` exposing
`ingest_company(ticker, *, sec_client, store, max_years=5, force=False) -> IngestionResult`. Financial
orchestration moves out of `scripts/` into this module. The script becomes a thin loop that builds
dependencies once and calls `ingest_company` per ticker.

**Rationale**: The constitution requires provider/financial logic to stay out of one-off scripts and
forbids two divergent implementations (FR-004). Dependency injection (`sec_client`, `store`) keeps the
function unit-testable offline with a fake SEC client and a temp SQLite store, mirroring the existing
`tests/test_persistence.py::_persist` pattern.

**Alternatives considered**:
- *Keep logic in the script, import from it* — rejected: a script is not an import boundary; violates
  FR-004 and the provider-boundary constraint.
- *Put orchestration inside the persistence store* — rejected: the store is a storage boundary and must
  not run financial layers (III/V and 4A's no-side-effects rule).

## 2. Idempotency and the skip decision

**Decision**: Idempotency key is the existing `(CIK, source_provider, source_type, content_hash)` unique
constraint on `source_snapshots`. Before doing analytical work, `ingest_company` checks whether a
snapshot already exists for the computed content hash. If it exists and `force` is false, ingestion
returns `UNCHANGED` immediately and performs **no** recomputation and no writes. If `force` is true, it
re-runs the layers and relies on the store's existing `ON CONFLICT DO NOTHING` UPSERTs so no duplicate
rows are created.

**Rationale**: The 4A schema already enforces natural-key uniqueness with `ON CONFLICT DO NOTHING` on
snapshots, facts, metrics, analyses, and coverage, so repeated writes are inherently non-duplicating.
Detecting the existing snapshot up front lets us honor FR-014 (no duplicates, `UNCHANGED` result) and
FR-016 (skip redundant recomputation) cheaply and deterministically. Because derived metrics carry
`calculation_version` and analyses carry `analysis_rule_version` in their unique keys, an unchanged
snapshot at the current versions is already fully present — so "same snapshot ⇒ skip" is equivalent to
"same snapshot + same calc/rule versions" for the current code, and is the simplest correct rule.

**Alternatives considered**:
- *Always recompute and rely only on UPSERT* — rejected: satisfies non-duplication but wastes work and
  cannot cleanly return `UNCHANGED` (FR-016).
- *Track a separate per-version ledger* — rejected: speculative; the snapshot + version keys already
  encode the needed identity (constitution VI).

**New store support required**: a public read to answer "does a snapshot exist for this CIK +
content_hash?" The store currently has a private `_snapshot_id(SourceSnapshotRecord)`. Add a thin public
`source_snapshot_exists(cik, content_hash) -> bool` (or `get_source_snapshot(...) -> SourceSnapshotRecord
| None`). This is additive and tied directly to FR-014/FR-016.

## 3. Transaction semantics for structured writes

**Decision**: Persist in two stages. Stage 1 (raw-first): write the raw payload to the filesystem store
and commit the company row and the source-snapshot row — this records that the source was retrieved and
stored. Stage 2 (structured analytical writes): wrap `save_reported_facts`, `save_derived_metrics`,
`save_analysis_result`, and `save_coverage` in a single transaction so a mid-write failure rolls back
the whole analytical set for that snapshot, leaving no misleading half-written state. On stage-2
failure, set the snapshot `processing_status` to `failed` (or leave `fetched`) and return a `FAILED`
result of class `persistence`, while the raw snapshot and its metadata remain.

**Rationale**: FR-012 (raw-first) and FR-017 (atomic structured writes) require exactly this split. The
existing `SqliteStore` uses one `sqlite3.Connection` and currently commits inside each `save_*`. A small
additive `transaction()` context manager that suppresses the per-call commits and commits/rolls back
once at the boundary gives atomicity without an ORM or a new dependency.

**Alternatives considered**:
- *Single giant transaction over raw + structured* — rejected: would discard the successfully retrieved
  raw evidence on a late failure, violating FR-012.
- *No transaction, per-call commits only* — rejected: a mid-write failure leaves a partial analytical
  snapshot, violating FR-017.
- *Savepoints per layer* — rejected: finer than the requirement; one transaction around the four
  structured writes is the minimal correct unit.

**New store support required**: a `transaction()` context manager (additive) that defers commits for the
structured `save_*` calls and rolls back on exception. The public `save_*` methods keep their current
auto-commit behavior when used outside a transaction, so 4A and its tests are unaffected.

## 4. Processing status vocabulary

**Decision**: Use the existing `source_snapshots.processing_status` TEXT column with a small closed
vocabulary defined as a `ProcessingStatus` enum: `fetched` (raw stored, analysis not yet done or not
completed), `processed` (all supported layers produced and persisted with full coverage), `partial`
(raw stored and trustworthy layers persisted, but some layers are unsupported/insufficient), `failed`
(a persistence error prevented completing the structured writes). The status is written on the snapshot
row and mirrored in the `IngestionResult`.

**Rationale**: FR-013 requires exactly these distinctions; the column already exists in the 4A schema
(currently written as the literal `"processed"` by the prototype), so this is a semantics decision, not
a schema change. Partial-but-trustworthy (e.g., Visa) is `partial`/processed, never `failed` (FR-010).

**Alternatives considered**:
- *Boolean processed flag* — rejected: cannot express partial vs failed (FR-006 forbids ambiguous
  booleans).
- *Free-text status* — rejected: not testable; an enum is a documented contract (IV).

## 5. Failure-class taxonomy and mapping

**Decision**: Model four classes as a `FailureClass` enum: `retrieval`, `unsupported`,
`insufficient_data`, `persistence`. Mapping:
- `retrieval` ← any `SecError` subclass raised by `SecClient` (`CompanyResolutionError`,
  `MalformedTickerError`, `SecTransportError`, `SecResponseError`, `MalformedSecResponseError`,
  `CompanyIdentityMismatchError`). Nothing is written; result is `FAILED`/`retrieval`.
- `unsupported` ← a required metric that raises the Feature-1/3 concept errors
  (`ConceptNotFoundError`/normalization errors) surfaced as coverage `UNSUPPORTED`. This does **not**
  abort unrelated layers; it becomes an `unsupported_items` entry and drives `partial` coverage.
- `insufficient_data` ← a trustworthy metric that exists for too short a history to complete a specific
  analysis (Feature-2 `INSUFFICIENT_DATA`/`PARTIAL` coverage). Recorded in coverage, not a hard failure.
- `persistence` ← any `PersistenceError` subclass from the store; result is `FAILED`/`persistence`.

**Rationale**: FR-011 requires these four to stay distinct. The existing coverage layer
(`company_coverage`) already classifies unsupported vs insufficient vs available per input/layer, so
the ingestion service derives `unsupported`/`insufficient_data` items directly from the coverage picture
rather than reimplementing detection. Retrieval and persistence are exception-driven and mutually
exclusive with a produced coverage picture.

**Alternatives considered**:
- *One generic error list* — rejected: violates FR-011's required separation.
- *Re-probing each normalizer in the ingestion service* — rejected: duplicates `company_coverage`;
  reuse the existing reporter (IV/VI).

## 6. Deriving status and counts from the coverage picture

**Decision**: After the layers run, compute `IngestionStatus` from coverage: if every layer is
`AVAILABLE` (full) ⇒ `COMPLETE` and `processing_status = processed`; if the raw retrieval and at least
the reported facts persisted but some layer is `UNSUPPORTED`/`INSUFFICIENT_DATA`/`PARTIAL` ⇒ `PARTIAL`
and `processing_status = partial`. `UNCHANGED` short-circuits before layer work (§2). `FAILED` results
from retrieval or persistence exceptions. Counts (`persisted_fact_count`, `persisted_metric_count`,
`analysis_count`) are the lengths of the record tuples actually written for this snapshot.

**Rationale**: Reuses the deterministic `CompanyCoverage` already produced by `company_coverage`
(FR-006/FR-008/FR-010). "Full" is defined exactly as the existing `_is_full` helper (all layer states
`AVAILABLE`), so classification stays consistent with Feature 3C.

**Alternatives considered**:
- *Infer completeness from counts alone* — rejected: counts don't distinguish unsupported vs
  structurally-absent; coverage does.

## 7. Overrides and exploration companies

**Decision**: Do not add any company-specific override in this slice unless live exploration of the two
new companies (MSFT, CRM) exposes a genuine SEC taxonomy difference meeting all four gates in FR-023
(clear economic meaning, verified concept, wrong/stale/missing default, canonical semantics preserved).
Any justified override is added to the Feature-3 canonical metric registry (`metrics.py`
`CanonicalMetricDefinition.overrides`), never to the ingestion orchestration. Exploration outcomes
(what worked, what failed, whether an override is justified) are documented, not forced green.

**Rationale**: FR-022/FR-023 and constitution I/VI. The registry already supports per-ticker overrides
that *replace* default concepts; that is the only sanctioned path. The purpose of MSFT/CRM is honest gap
discovery (SC-009), not guaranteed full coverage.

**Alternatives considered**:
- *Pre-emptively add MSFT/CRM overrides* — rejected: speculative and may fabricate coverage (V/VI).

## 8. CLI structure and backward compatibility

**Decision**: Introduce `src/owner_lens/cli.py` using `argparse` subparsers: `ingest <TICKER>
[--max-years N] [--force]` and an optional `show <TICKER>`. The `--force` flag is included because §2
establishes a real need (re-run analytics against an already-stored snapshot); no other operational
flags are added (FR-019). `owner_lens.main()` becomes a thin delegate to `cli.main()`. The current bare
`owner-lens <TICKER>` raw-facts inspector is preserved as an explicit `inspect <TICKER>` subcommand so
no validated behavior is lost while the primary UX becomes `ingest`.

**Rationale**: FR-018/FR-020 require a first-class `ingest` subcommand with concise output and
outcome-based exit codes; argparse subparsers are the stdlib-native way (VI). Keeping the old inspector
under a named subcommand honors "do not discard validated behavior" without maintaining two ingestion
paths.

**Alternatives considered**:
- *Keep `owner-lens <TICKER>` meaning "inspect" and add `ingest` alongside* — rejected: ambiguous
  top-level positional vs subcommand; subcommands are clearer and testable.
- *Third-party CLI framework (click/typer)* — rejected: new dependency for no capability gain (VI).

**Exit codes**: `0` for `COMPLETE`, `PARTIAL`, and `UNCHANGED` (all are honest, non-error outcomes);
non-zero for `FAILED` (retrieval or persistence). Partial coverage is a success exit because the company
was ingested honestly (FR-010).

## 9. Deterministic raw serialization and content hash

**Decision**: Serialize the retrieved facts with `json.dumps(raw_facts, sort_keys=True).encode()` and
hash with the existing `compute_content_hash` (SHA-256). The raw store derives the CIK from the payload
(`_cik_from_payload`) and lays the file out as `<CIK>/<content-hash>.json`.

**Rationale**: This matches the existing 4A raw-store layout and the `tests/test_persistence.py`
serialization, giving stable, reproducible hashes for idempotency (FR-014) and provenance (SC-006).

**Alternatives considered**:
- *Hash the exact HTTP response bytes* — rejected: `SecClient` returns parsed JSON, not raw bytes;
  canonical `sort_keys` serialization is deterministic and already the established convention.

## 10. Documentation and notebook

**Decision**: Add `notebooks/11_persisted_ingestion.ipynb` (why ingestion ≠ analysis; fetch → persist
raw → normalize → analyze → persist; full ADBE; partial Visa; idempotent re-ingest; historical snapshot;
an unseen company; gaps before batch). Add Feature 4 documentation under `docs/` covering the 4A model,
4B ingestion, local SQLite/filesystem architecture, idempotency, source-snapshot history, coverage
behavior, and the intentional Azure deferral.

**Rationale**: Constitution IV requires an educational notebook for meaningful new behavior; FR/SC-010
requires standalone Feature 4 documentation. The notebook must be authored as valid JSON (create empty,
then populate) per prior repo experience.

**Alternatives considered**: none; both are mandated by the constitution and spec.

## Resolved unknowns

All Technical Context items are resolved; there are no remaining `NEEDS CLARIFICATION` markers. New,
strictly-additive store support identified: `source_snapshot_exists`/`get_source_snapshot` read and a
`transaction()` context manager, both tied to FR-014/FR-016/FR-017 and leaving 4A behavior and tests
unchanged.

## Post-implementation refinement — branch tolerance and debt representation (live MSFT/CRM/NOW)

Live validation of three previously unseen companies exposed that a single unsupported normalization
could discard all trustworthy analysis. This section records the research and the resolution.

### Debt-concept research (live SEC Company Facts, recent fiscal-year-end instants)

| Company | Current debt at FY-end | Long-term debt | Notes |
|---------|------------------------|----------------|-------|
| ADBE    | `DebtCurrent` (recent) | `LongTermDebt` (recent) | Default mapping; unchanged. |
| V       | `LongTermDebtCurrent` (override) | `LongTermDebtNoncurrent` (override) | `DebtCurrent` empty; existing override. |
| COST    | `LongTermDebtCurrent` (override) | `LongTermDebtNoncurrent` (override) | Existing override. |
| MSFT    | `LongTermDebtCurrent` (recent); **no `DebtCurrent`** | `LongTermDebtNoncurrent` **and** total `LongTermDebt` | Same split V/COST override to. |
| CRM     | `LongTermDebtCurrent` (recent); **no `DebtCurrent`** | `LongTermDebtNoncurrent` **and** total `LongTermDebt` | Same as MSFT. |
| NOW     | `LongTermDebtCurrent` **stale (ends 2022)** | `LongTermDebt`/`Noncurrent` empty | Genuinely little/no recent debt. |

**Decision (overrides): defer, do not add.** MSFT/CRM use the same `LongTermDebtCurrent` +
`LongTermDebtNoncurrent` partition that V/COST override to, but they *also* report a total
`LongTermDebt`. A generic default preference extension (`current_debt` → add `LongTermDebtCurrent`
fallback) is therefore **not safe**: pairing `LongTermDebtCurrent` with the default `long_term_debt`
concept `LongTermDebt` (which includes the current portion) would **double-count** current maturities.
Only a paired per-company override (both `current_debt` → `LongTermDebtCurrent` and `long_term_debt` →
`LongTermDebtNoncurrent`, mirroring V/COST) would be correct. Per FR-023 and the user's instruction not
to add ticker overrides merely to make ingestion succeed, these overrides are **deferred**; MSFT/CRM
capital-efficiency remains honestly unsupported until a maintainer verifies and adds the paired
overrides through the Feature-3 canonical registry.

### Branch tolerance (the actual fix)

**Decision**: An unsupported normalization in one analytical branch must not discard the independent
branches. Two changes deliver this without weakening any metric:

1. `coverage._layer_coverage` now guards **all six** layer branches with the existing concept-error set
   (previously only `owner_economics` and `capital_efficiency` were guarded; `economic_value`,
   `compounding`, `capital_allocation`, and `economic_summary` assumed capital-efficiency succeeded and
   propagated its failure). Guarded branches degrade to `UNAVAILABLE` with the reason; companies where
   the branches succeed (ADBE/V/COST) are byte-for-byte unchanged.
2. `ingest_company` builds records from whatever branches computed and persists them transactionally.
   Owner-economics facts and derived metrics persist even when capital-efficiency (debt) is unsupported.
   Status is `COMPLETE` when coverage is full, `PARTIAL` when some branch is unsupported/insufficient
   but trustworthy output persisted, and the snapshot is left `partial` (processed) rather than
   `fetched` whenever any trustworthy output was written.

**Result (verified live)**: MSFT and CRM now persist 30 reported facts + 37 derived metrics with
`owner_economics` `AVAILABLE` and the debt-dependent branches explicitly `UNAVAILABLE`; `current_debt`
is surfaced as an unsupported item. No whole-company collapse.

### NOW — genuine data ambiguity (fail-loud, not a mapping gap)

NOW raises `AmbiguousValueError` on **core** metrics — `NetIncomeLoss` FY2021 (`230000000` vs
`230141000`) and diluted shares FY2024 (`208423000` vs `1042113000`). These are conflicting reported
values, not missing concepts. Constitution V (fail loudly; never fabricate) requires OwnerLens to
**refuse** to pick between conflicting values for a core metric, so NOW cannot produce trustworthy owner
economics. Ingestion preserves the raw snapshot and reports NOW honestly as `fetched` / analysis
unavailable. This is the correct outcome, distinct from the MSFT/CRM unsupported-concept case; no
tolerance for ambiguous core metrics was added.

### Scope guardrail

Branch tolerance catches only the known concept-not-found domain exceptions (unsupported inputs). It
does **not** broadly swallow ambiguity, malformed data, or programming errors — those still fail loudly.


---
title: "Research: Persistence Model and Storage Boundary"
description: Phase 0 decisions for OwnerLens Slice 4A local persistence, resolving driver, precision, keys, coverage, and boundaries
ms.date: 2026-09-04
ms.topic: reference
---

## Purpose

Resolve every open question needed to design a local-first persistence layer that stores OwnerLens
outputs without changing financial semantics and without introducing Azure infrastructure. No
`NEEDS CLARIFICATION` markers remained from the specification; the decisions below fix the concrete
choices the plan depends on.

## Decision 1 — Local store: standard-library `sqlite3` (reject SQLAlchemy)

**Decision**: Implement the local store with the Python standard-library `sqlite3` module and
hand-written SQL. Do not add SQLAlchemy or any ORM.

**Rationale**:

* Constitution VI (build only what the release requires): SQLite ships with CPython, so the store
  adds zero third-party dependencies. SQLAlchemy is a large dependency justified only by breadth this
  slice does not have (three companies, ~5 years, a handful of tables).
* The prompt forbids ORM model hierarchies, migration frameworks, connection pools, and async access.
  Plain `sqlite3` with explicit SQL matches those constraints directly; SQLAlchemy's value (ORM,
  unit-of-work, dialect abstraction) is exactly the machinery being excluded.
* Migration friction to PostgreSQL is low because the schema is small and written in portable SQL.
  The relational shape — not the driver — is what carries forward to Slice 4B. Hand-written SQL keeps
  the DDL visible and reviewable, which aids the PostgreSQL port more than a hidden ORM mapping would.
* Idempotency uses SQLite `INSERT ... ON CONFLICT ... DO NOTHING/UPDATE` (UPSERT), available in the
  SQLite bundled with Python 3.12 (SQLite ≥ 3.24, and Python 3.12 bundles ≥ 3.37).

**Alternatives considered**:

* **SQLAlchemy Core (no ORM)**: still a new dependency; its portability abstraction is unnecessary for
  a single local dialect in this slice. Rejected on constitution VI.
* **SQLAlchemy ORM**: directly conflicts with the "no ORM model hierarchies" constraint. Rejected.
* **A document store / JSON file**: loses relational query power needed by the five query use cases
  and the long-form provenance requirement. Rejected.

## Decision 2 — Numeric precision: `INTEGER` for money/shares, `REAL` for derived ratios

**Decision**: Store exact monetary values and share counts (which are Python `int` in the domain,
e.g. `AnnualObservation.value`, `OwnerEconomicsRow.free_cash_flow`) as SQLite `INTEGER`. Store derived
ratios and growth rates (which are Python `float` in the domain, e.g. `operating_margin`,
`fcf_per_share`, `roic`) as SQLite `REAL`. Store fiscal years as `INTEGER`, dates as ISO-8601 `TEXT`,
enums and identifiers as `TEXT`.

**Rationale**:

* SQLite `INTEGER` is a signed 64-bit value (max ≈ 9.22e18). The largest OwnerLens monetary values are
  company revenues in the hundreds of billions (≈ 1e12) and share counts in the billions (≈ 1e10),
  both far inside the 64-bit range, so no monetary value is silently truncated or rounded (FR-017).
* The domain already represents money and shares as exact `int`; `INTEGER` preserves them exactly. No
  `Decimal`/`NUMERIC` layer is needed because there is no fractional currency in the canonical facts.
* The domain already represents ratios as Python `float` (IEEE-754 double), and SQLite `REAL` is also
  an IEEE-754 double, so persisting a ratio introduces no additional error beyond the float the
  analysis layer already produced. `REAL` is nonetheless floating point, **not** exact decimal
  storage: it preserves practical analytical precision, not a bit-perfect decimal representation of
  the ratio. Ratio round-trips are therefore validated with **tolerances**, not exact decimal
  equality. Introducing a `Decimal`/`TEXT` representation would diverge from the float the
  deterministic layer computed and add complexity this slice does not need. The contract wording is:
  *ratios preserve practical analytical precision, not bit-perfect decimal representation.*
* Percentages are stored as the fraction the domain uses (e.g. `0.616` for 61.6% ROIC), documented in
  the data model, not multiplied to a percent during persistence. Only exact monetary values and
  share counts require precise storage, and those never use `REAL` (they use `INTEGER`).

**Alternatives considered**:

* **`Decimal`/`TEXT` for ratios**: would diverge from the float the analysis layer produced and
  complicate exact-match validation. Rejected; ratios are inherently derived floats.
* **`REAL` for monetary values**: rejected outright by FR-017 (no float storage for exact money/share
  values) and would lose precision for large integers.

**Bound documented**: the 64-bit `INTEGER` ceiling (≈ 9.22e18) is recorded as a known limit; no
supported canonical fact approaches it. If a future value could exceed it, it would be stored as a
scaled integer or `TEXT` decimal, but that is out of scope now.

## Decision 3 — Identity and idempotency keys

**Decision**: Use deterministic natural keys enforced by SQLite `UNIQUE` constraints, with UPSERT on
conflict so identical repeats are no-ops (FR-016):

| Entity | Natural / uniqueness key |
|--------|--------------------------|
| `companies` | `cik` (primary identity; ticker/name are mutable attributes) |
| `source_snapshots` | (`cik`, `source_provider`, `source_type`, `content_hash`) |
| `reported_facts` | (`snapshot_id`, `canonical_metric`, `concept`, `fiscal_year`, `period_end`) |
| `derived_metrics` | (`snapshot_id`, `metric_name`, `fiscal_year`, `calculation_version`) |
| `analysis_results` | (`snapshot_id`, `analysis_type`, `analysis_period`, `analysis_rule_version`) |
| `analysis_drivers` | (`analysis_result_id`, `position`) |
| `coverage_results` | (`snapshot_id`, `subject_kind`, `subject`) |

**Rationale**:

* `cik` is the strongest current SEC entity identifier (FR-005); anchoring identity on it lets ticker
  and company name change over time without ambiguity. Ticker/name are stored as current attributes on
  the company row and updated by UPSERT.
* `content_hash` (SHA-256 of the raw Company Facts payload) makes a snapshot self-identifying:
  re-processing the identical payload resolves to the same snapshot row, so repeated ingestion is
  idempotent (SC-004). Distinct payloads produce distinct snapshots, preserving history.
* Scoping facts/metrics/analysis/coverage by `snapshot_id` guarantees that a later snapshot never
  overwrites an earlier one (FR-015) while keeping repeats within one snapshot idempotent.

**Version-context invariant** (distinguishing *data changed* from *logic changed*): because
`calculation_version` and `analysis_rule_version` are part of the `derived_metrics` and
`analysis_results` natural keys, the following holds:

```text
same company + same source content hash + same calculation/analysis-rule version
    -> idempotent repeat (UPSERT no-op)

same source snapshot + newer calculation/analysis-rule version
    -> a new derived-metric / analysis-result row that coexists with the prior one
```

This lets a later change to a ROIC definition or a Feature 2 rule set produce a new analytical result
over the *same* underlying data without overwriting the earlier result, so the store can later tell
whether a classification changed because the data changed (new `snapshot_id`) or because the logic
changed (new version).
* An integer surrogate primary key (`INTEGER PRIMARY KEY`) is used per table for cheap foreign keys,
  with the natural key expressed as a separate `UNIQUE` constraint. This is a uniqueness strategy, not
  a distributed idempotency framework (FR-016).

**Alternatives considered**:

* **Ticker as company identity**: rejected; tickers change and are reused, making history ambiguous.
* **Content-addressed hashing of every fact/metric row**: unnecessary; the composite natural keys are
  simpler and sufficient for local idempotency.

## Decision 4 — Coverage and missing-data representation (never NULL-as-meaning)

**Decision**: Persist coverage as explicit `TEXT` state values in a dedicated `coverage_results`
table, storing the exact enum names already used by `coverage.py` (`AVAILABLE`,
`STRUCTURALLY_ABSENT`, `UNSUPPORTED`) and Feature 2 (`INSUFFICIENT_DATA`). An unavailable fact or
metric is represented by the **absence of a row** in `reported_facts`/`derived_metrics`, with the
reason recorded in `coverage_results`; a genuine reported zero is a present `reported_facts` row with
`value = 0`.

**Rationale**:

* FR-014 forbids collapsing coverage distinctions into SQL `NULL`. Storing the enum name as text keeps
  `UNSUPPORTED` (Visa diluted shares), `STRUCTURALLY_ABSENT` (Adobe dividends), and `INSUFFICIENT_DATA`
  (per-share Feature 2 layers) distinct and queryable.
* Reported zero must stay a real observation (SC-003): modeling absence as "missing row" and zero as
  "row with 0" keeps them unambiguous, because a `NULL`/missing value never means "the company
  reported zero."
* `coverage_results.subject_kind` distinguishes input-metric coverage (`MetricCoverage`) from layer
  coverage (`LayerCoverage`), matching the two-level `CompanyCoverage` structure (`inputs` and
  `layers`). `reason` and `blocking_input` mirror `LayerResult`.
* SQL `NULL` remains permitted only for genuinely optional storage fields (e.g. `period_start` for
  instant facts, an absent `raw_object_ref`), never as the business meaning of unavailability.

**Alternatives considered**:

* **A nullable value column meaning "unavailable"**: rejected; conflates unsupported, structurally
  absent, insufficient, and reported-zero.
* **A boolean `is_available` flag**: rejected; cannot express the four distinct states.

## Decision 5 — Raw payload boundary: filesystem, referenced by content hash

**Decision**: Store the full raw SEC Company Facts JSON on the local filesystem via a
`FilesystemRawSnapshotStore`, keyed by content hash, behind a small `RawSnapshotStore` protocol. The
relational `source_snapshots` row stores the `content_hash`, a `source_uri`/logical identifier, and an
optional `raw_object_ref` (the local path or key) — never the JSON blob itself.

**Rationale**:

* FR-007 and Section 12 require the relational model to reference raw snapshots rather than embed
  them, and to anticipate raw payloads moving to Azure Blob Storage in Slice 4B. A `RawSnapshotStore`
  protocol with a filesystem implementation now lets a `BlobRawSnapshotStore` drop in later with no
  relational schema change — the row already references by hash/key.
* Content-hash addressing makes raw storage idempotent and lets snapshot metadata be reconciled to the
  exact bytes analyzed (FR-006).
* The store is introduced only because concrete local validation persists at least one snapshot per
  company; it is minimal (put/get/exists by hash), not a general object-store abstraction.

**Alternatives considered**:

* **Embed raw JSON in a relational column**: rejected by FR-007; bloats the relational store and
  fights the Blob migration.
* **No raw storage at all**: acceptable per the spec, but storing by hash on disk cheaply satisfies
  "can the raw source be located later?" and exercises the Slice 4B seam.

## Decision 6 — Persistence error hierarchy (distinct from financial errors)

**Decision**: Introduce a `PersistenceError(Exception)` base with four subclasses:
`StorageConnectionError` (open/setup failure), `SchemaVersionError` (stored schema version
incompatible with the running code), `StorageWriteError`, and `StorageReadError`. These are wholly
separate from `SecError`, `ConceptNotFoundError`, `AmbiguousValueError`, and any insufficient-data
semantics.

**Rationale**:

* FR-019 requires persistence failures to surface through their own categories and never be
  transformed into financial-domain errors. A distinct base type lets callers catch persistence
  problems without touching financial error handling and vice versa (SC-008).
* `SchemaVersionError` gives the store an explicit, loud response to a version mismatch (Edge Cases)
  rather than reading data under wrong assumptions.

**Alternatives considered**:

* **Reusing built-in `sqlite3.Error`**: rejected; leaks the driver and gives callers no OwnerLens-level
  categorization.
* **Folding persistence errors into `SecError`**: rejected; violates the separation FR-019 demands.

## Decision 7 — Schema and definition versioning (minimum viable)

**Decision**: Create a `schema_meta` key/value table populated on initialization with `schema_version`
(integer, starting at 1). Record `calculation_version` on `derived_metrics` and `analysis_rule_version`
on `analysis_results` as `TEXT` columns, defaulting to a constant version string for this slice. No
migration framework.

**Rationale**:

* FR-018 asks for the minimum mechanism that prevents treating metric/classification definitions as
  timeless. A single `schema_version` plus per-row definition-version columns records "which rules
  produced this value" without building migrations.
* Because `calculation_version`/`analysis_rule_version` are part of the derived-metric and
  analysis-result natural keys (Decision 3), a later ROIC or Feature 2 rule change produces a *new*
  row that coexists with the prior result over the same data, rather than overwriting it — the
  minimum needed to later distinguish *data changed* from *logic changed*.
* On open, the store compares the stored `schema_version` to the code's expected version and raises
  `SchemaVersionError` on mismatch, satisfying the version-incompatibility edge case.
* Re-initialization is a safe no-op (`CREATE TABLE IF NOT EXISTS`; insert schema version only if
  absent), satisfying the repeat-initialization scenario (US1 AS-1).

**Alternatives considered**:

* **A migrations framework (Alembic/yoyo)**: rejected by scope (Section 21) and constitution VI.
* **No versioning**: rejected; would pretend definitions are timeless (FR-018).

## Decision 8 — Write semantics and the domain→record boundary

**Decision**: Keep all financial functions pure (no writes). Provide a pure `adapters.py` that
converts existing domain dataclasses into persistence records, and an explicit `store` API the caller
invokes (e.g. `store.save_reported_facts(...)`, `store.save_analysis_result(...)`). Orchestration
lives in the caller/notebook, not inside calculation functions.

**Rationale**:

* FR-002 and Section 16 forbid hidden database writes inside computation. Converting outputs to records
  in a side-effect-free adapter, then saving via an explicit store call, keeps the calculation layer
  storage-independent (SC-007) and makes the write point obvious and testable.
* Adapters depend on the domain types but not vice versa, so no financial module imports persistence —
  guaranteeing the dependency direction and regression safety.

**Alternatives considered**:

* **`*_from_facts` functions writing to a store**: rejected; introduces side effects into pure
  computation and couples financial code to storage.
* **Active-record records that save themselves**: rejected; reintroduces ORM-style coupling.

## Decision 9 — Query surface (domain-oriented, not generic CRUD)

**Decision**: Expose exactly the read operations the five use cases require:
`get_company`, `get_metric_history(cik, metric, limit)`, `get_fact_provenance(cik, metric,
fiscal_year)`, `get_latest_summary(cik)`, `get_company_coverage(cik)`, and
`get_latest_metric_across_companies(metric, ciks)`. Missing data returns an explicit empty result
(e.g. empty tuple / `None`), never a fabricated value or a financial error.

**Rationale**:

* FR-020–FR-024 enumerate the concrete queries; naming them as domain operations avoids a generic
  `Repository[T]`/`GenericCrudService` (FR-003) and keeps the surface honest to current needs.
* The cross-company latest-metric read (FR-024) is the only forward-looking operation and is limited to
  retrieval — no comparison, scoring, or screening is built (Section 14, out of scope).
* Returning an explicit empty result for unknown company/metric matches the Edge Cases and keeps
  persistence "absence" distinct from financial "insufficient data."

**Alternatives considered**:

* **Generic repository/query builder**: rejected by FR-003.
* **Returning `None` conflated with unsupported**: rejected; the store reports "not stored," while
  coverage tables carry the financial reason a value is unavailable.

## Summary of resolved unknowns

| Question | Resolution |
|----------|------------|
| `sqlite3` vs SQLAlchemy | Standard-library `sqlite3`, hand-written SQL, UPSERT (Decision 1) |
| Numeric storage types | `INTEGER` money/shares (exact), `REAL` derived ratios (approximate, tolerance-tested), `TEXT` dates/enums (Decision 2) |
| Idempotency keys | `cik`; snapshot content hash; composite natural keys + UPSERT (Decision 3) |
| Coverage representation | Explicit `TEXT` state table; absence + reason; zero is a real row (Decision 4) |
| Raw payload | Filesystem `RawSnapshotStore`, referenced by hash; Blob-ready seam (Decision 5) |
| Error semantics | `PersistenceError` hierarchy distinct from financial errors (Decision 6) |
| Versioning | `schema_meta` + per-row `calculation_version`/`analysis_rule_version`; newer version coexists; no migrations (Decision 7) |
| Write semantics | Pure adapters + explicit `store.save_*`; no side effects in calc (Decision 8) |
| Query surface | Named domain reads for the five use cases; no generic CRUD (Decision 9) |

All Technical Context unknowns are resolved; no `NEEDS CLARIFICATION` remains.

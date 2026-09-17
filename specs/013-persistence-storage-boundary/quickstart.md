---
title: "Quickstart: Persistence Model and Storage Boundary"
description: Runnable validation guide proving OwnerLens Slice 4A stores and queries ADBE/V/COST outputs locally
ms.date: 2026-09-04
ms.topic: reference
---

## Purpose

Validate that the local persistence layer stores OwnerLens outputs faithfully and answers the five
target queries, that provenance and coverage semantics survive persistence, that repeated processing
is idempotent, and that no financial module changed. This guide references the
[contract](contracts/persistence-api.md) and [data model](data-model.md) rather than restating
implementation.

## Prerequisites

* Python 3.12 with the project synced: `uv sync`
* Existing Feature 1–3 code and `tests/_fixtures.py` (ADBE/V/COST) present
* For the optional live check only: `OWNER_LENS_SEC_USER_AGENT` set (e.g. `"OwnerLens admin@example.com"`)

## Gate commands

Run all three before and after implementation; all must pass.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## Scenario 1 — Schema initialization is safe and versioned (US1)

1. Create a `SqliteStore` on a temporary path and call `initialize()`.
2. Confirm `schema_meta` contains `schema_version`.
3. Call `initialize()` again on the same file.

Expected: the second call is a no-op — no error, no duplicated tables or version rows. A store whose
stored `schema_version` is incompatible raises `SchemaVersionError`.

## Scenario 2 — Persist a full ADBE analysis and reproduce it (US1)

1. From the ADBE fixture, produce in-memory outputs with existing code
   (`owner_economics_from_facts`, `capital_efficiency_from_facts`, `economic_value_from_facts`,
   `compounding_views_from_facts`, `capital_allocation_from_facts`,
   `economic_value_summary_from_facts`, `company_coverage`).
2. Convert them with `persistence.adapters.*` (no side effects) into records.
3. Save via `save_company`, `save_source_snapshot`, `save_reported_facts`, `save_derived_metrics`,
   `save_analysis_result`, `save_coverage`.
4. In a fresh `SqliteStore` on the same file, read back.

Expected: every retrieved value matches the in-memory output (SC-001) — exact equality for monetary
and share-count integers, and equality within a small tolerance for `REAL` ratios (which are IEEE-754
floating point, not exact decimals). Specifically:

* `get_metric_history("0000796343", "fcf_per_share", limit=5)` returns five fiscal years in order.
* `get_latest_summary("0000796343")` returns the ADBE Economic Value Summary classification with its
  ordered drivers matching the in-memory summary (US1 AS-4).

## Scenario 3 — Provenance survives persistence (US2)

1. Persist COST facts (fixture) including FY2025 revenue.
2. Call `get_fact_provenance("0000909832", "revenue", 2025)`.

Expected: the record exposes the canonical metric `revenue`, the distinct source `concept`
(e.g. `RevenueFromContractWithCustomerExcludingAssessedTax`), `form`, `filed`, `accession`, and the
producing snapshot reference (SC-002, FR-021).

## Scenario 4 — Coverage semantics are not NULL (US2)

1. Persist Visa outputs and coverage (fixture).
2. Call `get_company_coverage("0001403161")`.

Expected:

* Diluted-shares coverage `state` is `UNSUPPORTED` with its reason, not a missing field (SC-003).
* A Feature 2 per-share layer persists as `INSUFFICIENT_DATA`.
* Any genuine reported zero (e.g. a zero-repurchase year where applicable) round-trips as a
  `reported_facts` value of `0`, distinct from absent/unsupported.

## Scenario 5 — Idempotency and historical snapshots (US3)

1. Persist the same ADBE snapshot and its records twice; count rows after each write.
2. Persist a distinct later ADBE snapshot (different content hash) and re-read.

Expected: the second identical write adds zero rows (SC-004); the distinct snapshot coexists with the
first, and both snapshots' facts/metrics/analysis are individually retrievable (US3 AS-2).

## Scenario 6 — Cross-company latest primitive (US3)

1. Persist ADBE, Visa, and Costco derived metrics.
2. Call `get_latest_metric_across_companies("roic", ["0000796343", "0001403161", "0000909832"])`.

Expected: each company's latest ROIC value with units (FR-024); retrieval only, no comparison or score.

## Scenario 7 — Failure semantics are distinct (edge cases)

1. Point a store at an unwritable/invalid path.
2. Attempt a read for an unknown company.

Expected: setup/write failures raise `StorageConnectionError`/`StorageWriteError`; a query failure
raises `StorageReadError`; an unknown company returns an explicit empty result. No persistence failure
is reported as `ConceptNotFoundError` or insufficient-data (SC-008, FR-019).

## Scenario 8 — Regression (all features)

Run `uv run pytest -q`. Expected: every existing Feature 1–3 test passes unchanged, confirming
financial modules remain storage-independent (SC-007). No financial module imports the persistence
subpackage.

## Optional live validation

Using live ADBE/V/COST retrieval (existing `SecClient`), reproduce the manual sequence in the feature
spec Section 19: initialize a local database, persist identities, at least one snapshot per company,
canonical facts, derived metrics, and Feature 2 outputs, then query back:

* five-year ADBE FCF/share history,
* COST FY2025 revenue with provenance,
* latest ADBE Economic Value Summary,
* Visa coverage limitations,
* latest ROIC across ADBE/V/COST,

confirming persisted values match the in-memory OwnerLens outputs.

## Educational notebook

`notebooks/09_persistence_model.ipynb` walks through why OwnerLens needs persistence; facts vs metrics
vs analysis outputs; why provenance survives; why absence/unsupported/insufficient are not SQL NULL;
historical snapshots vs one mutable latest row; persisting ADBE/V/COST; several owner/investor query
views; and how this boundary maps to Azure Blob + PostgreSQL next. Keep cells lint-clean (ruff scans
`.ipynb`).

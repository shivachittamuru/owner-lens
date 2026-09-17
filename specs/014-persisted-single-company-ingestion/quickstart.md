---
title: "Quickstart: Persisted Single-Company Ingestion"
description: Runnable validation guide for OwnerLens Slice 4B ingestion
ms.date: 2026-09-17
ms.topic: quickstart
---

# Quickstart — Persisted Single-Company Ingestion (Slice 4B)

This guide validates the feature end-to-end. It assumes the Slice 4A local persistence is in place and
`OWNER_LENS_SEC_USER_AGENT` is configured (in `.env` or the environment). See
[contracts/ingestion-service.md](contracts/ingestion-service.md) and [contracts/cli.md](contracts/cli.md)
for the exact behavioral and command contracts, and [data-model.md](data-model.md) for the result shape.

## Prerequisites

- Python 3.12 with `uv`.
- `OWNER_LENS_SEC_USER_AGENT` set to an SEC User-Agent identifying the app and an admin contact.
- Network access for the live steps (automated tests are offline).

## Quality gates (must stay green)

```pwsh
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## Scenario 1 — Full ingestion (Adobe), User Story 1 / SC-002

```pwsh
uv run owner-lens ingest ADBE
```

Expected: status resolves to a complete outcome; the report shows all layers `FULL`, overall economic
value `IMPROVING`, and non-zero persisted counts. On disk: `data/ownerlens.db` and
`data/raw/sec/company_facts/0000796343/<hash>.json` exist. Exit code `0`.

## Scenario 2 — Honest partial ingestion (Visa), User Story 2 / SC-003

```pwsh
uv run owner-lens ingest V
```

Expected: status is partial (processed with partial coverage), not failed. The coverage block shows the
unsupported `diluted_shares` input and the partial layers with the reason
`weighted-average diluted shares unsupported`. No per-share value is fabricated. Exit code `0`.

## Scenario 3 — Costco full ingestion (regression anchor)

```pwsh
uv run owner-lens ingest COST
```

Expected: complete outcome; the low-margin retailer is not penalized; overall economic value classified
honestly. Exit code `0`.

## Scenario 4 — Idempotent re-ingestion, User Story 3 / SC-004

```pwsh
uv run owner-lens ingest ADBE   # run again immediately
```

Expected: status `UNCHANGED`; the report indicates the snapshot already exists; zero new rows are
written. Verify with a row count before/after (facts, metrics, analyses, snapshots all unchanged).
Exit code `0`.

## Scenario 5 — Historical snapshot on changed content, SC-005

Simulated in tests by feeding a second fixture payload with different content (new `content_hash`) for
the same CIK. Expected: exactly one additional `source_snapshots` row is created and every earlier
snapshot remains retrievable. (Live SEC content changes only across filings, so this is validated via
the fixture-driven test rather than a live command.)

## Scenario 6 — Fresh-process persistence, SC-002 / SC-006

After Scenario 1–3, start a brand-new Python process and query the store directly:

```pwsh
uv run python -c "import sqlite3; c=sqlite3.connect('data/ownerlens.db'); print(c.execute('select ticker from companies order by ticker').fetchall()); print('facts:', c.execute('select count(*) from reported_facts').fetchone()[0])"
```

Expected: ADBE/V/COST present and facts retrievable — results depend only on storage, not on any
in-memory object. Provenance: every fact/metric/analysis row carries a `snapshot_id`.

## Scenario 7 — Failure classes, SC-007

Validated via `tests/test_ingestion.py` (offline), each asserting a distinct outcome:

- **Retrieval**: fake SEC client raises `CompanyResolutionError` ⇒ `FAILED`, `failure.kind == retrieval`,
  nothing written.
- **Unsupported**: Visa fixture ⇒ `PARTIAL` with an `unsupported` item for `diluted_shares`.
- **Insufficient data**: a thin-history fixture ⇒ coverage `INSUFFICIENT_DATA` item / warning, not a hard
  failure.
- **Persistence**: a store stub raising `StorageWriteError` mid-structured-write ⇒ `FAILED`,
  `failure.kind == persistence`, structured writes rolled back, raw snapshot retained.

## Scenario 8 — Exploration companies (discovery, not pass/fail), SC-009

```pwsh
uv run owner-lens ingest MSFT
uv run owner-lens ingest CRM
```

Expected: each runs safely and returns an honest coverage report. Full coverage is **not** required; the
goal is to surface the next normalization gaps. Document what worked, what failed, and whether any
Feature-3 registry override is genuinely justified (do not add an override merely for a green check).

## Scenario 9 — Optional inspection

```pwsh
uv run owner-lens show ADBE
```

Expected (if implemented): the latest persisted summary and coverage for Adobe, read from storage with
no SEC call.

## CLI regression

```pwsh
uv run owner-lens ingest ADBE --max-years 7
uv run owner-lens inspect ADBE
```

Expected: `--max-years` is honored; `inspect` preserves the pre-4B raw-facts view. Argument parsing,
formatting, and exit codes are covered by `tests/test_cli.py`.

## Educational notebook

Run `notebooks/11_persisted_ingestion.ipynb` top to bottom: ingestion vs analysis, full ADBE, partial
Visa, idempotent re-ingest, historical snapshot behavior, an unseen company, and the gaps that must
close before batch ingestion. The notebook must be lint-clean (ruff scans notebooks).

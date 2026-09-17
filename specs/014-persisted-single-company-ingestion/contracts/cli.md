---
title: "Contract: Command-Line Interface"
description: Command schema, output, and exit-code contract for owner-lens ingest/show/inspect
ms.date: 2026-09-17
ms.topic: reference
---

# Contract — Command-Line Interface (`owner_lens.cli`)

The console entry point `owner-lens` (defined in `pyproject.toml` as `owner_lens:main`) delegates to
`owner_lens.cli.main(argv=None)`. Commands are `argparse` subcommands.

## Commands

### `owner-lens ingest <TICKER> [--max-years N] [--force]`

Primary command. Loads settings (`load_settings()`), builds the local store
(`build_local_store(settings)`, then `store.initialize()`), constructs a `SecClient` from the
configured SEC User-Agent, calls `ingest_company(ticker, sec_client=..., store=..., max_years=N,
force=...)`, prints a concise report, and exits with an outcome-based code.

| Argument / option | Default | Meaning                                                        |
|-------------------|---------|----------------------------------------------------------------|
| `TICKER`          | —       | SEC-resolvable ticker (required).                              |
| `--max-years N`   | `5`     | Fiscal years of history to analyze (`N >= 1`).                 |
| `--force`         | `false` | Re-run analytics against an already-stored snapshot; still non-duplicating. |

No other operational flags are added in this slice (FR-019).

### `owner-lens show <TICKER>` *(optional, FR-021)*

Reads the latest persisted summary and coverage for a company from the store and prints them. No SEC
call, no writes. If the company is not in the store, prints a clear "not ingested" message and exits
non-zero. This command must not grow into a broad query interface.

### `owner-lens inspect <TICKER>`

Preserves the pre-4B raw-facts inspector (identity + top-level keys + namespaces + sample concepts) as
an explicit subcommand so no validated behavior is lost.

## Preconditions & configuration

- `OWNER_LENS_SEC_USER_AGENT` MUST be set (via environment or `.env`); if missing, `ingest`/`inspect`
  print an actionable message and exit `2`.
- Local storage paths come from settings (`OWNER_LENS_DB_PATH`, `OWNER_LENS_RAW_DATA_PATH`) with the 4A
  defaults.

## Output contract (`ingest`)

Concise, owner/developer-friendly; MUST NOT dump all raw financial values (FR-020). Includes company
identity, source snapshot + status, persisted counts, per-layer coverage, and overall economic value.
A partially supported company MUST visibly show partial coverage and the exact reason. Illustrative
shape:

```text
ADBE — Adobe Inc.
CIK: 0000796343

Source:
  SEC Company Facts
  snapshot: a83f… (status: new | unchanged)
  processing: processed | partial | failed

Persistence:
  reported facts:   48
  derived metrics:  67
  analyses:         14

Coverage:
  Owner Economics:      FULL
  Capital Efficiency:   FULL
  Economic Value:       FULL
  Compounding:          FULL
  Capital Allocation:   FULL
  Economic Summary:     FULL

Overall Economic Value:
  IMPROVING
```

For Visa, the coverage block shows the partial layers and the reason
(`weighted-average diluted shares unsupported`), and no per-share value is fabricated.

## Exit-code contract

| Outcome (`IngestionStatus`)          | Exit code |
|--------------------------------------|-----------|
| `COMPLETE`                           | `0`       |
| `PARTIAL`                            | `0`       |
| `UNCHANGED`                          | `0`       |
| `FAILED` (retrieval or persistence)  | `1`       |
| Missing/invalid configuration        | `2`       |

Partial coverage exits `0` because the company was ingested honestly (FR-010). `show` exits `0` on a
found company, non-zero when the company has not been ingested. `inspect` mirrors the prior behavior
(`1` on `SecError`, `2` on usage/config error).

## Determinism & testability

- `cli.main(argv)` accepts an explicit argument vector so tests can drive it without `sys.argv`.
- Formatting is a pure function of `IngestionResult`, tested directly with fixture results (no I/O).
- Tests inject a fake `SecClient` and a temp store, asserting exit codes and formatted output for
  `COMPLETE`, `PARTIAL`, `UNCHANGED`, and `FAILED`.

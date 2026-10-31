---
title: "Feature 8A2: FMP Premium Evidence"
description: "Persist versioned annual and quarterly FMP statements, EOD prices, and analyst expectations."
ms.topic: reference
keywords:
  - FMP
  - evidence
  - S&P 500
  - analyst estimates
---

## Scope

Feature 8A2 extends `refresh-sp500` to acquire FMP statement, EOD price, and
analyst-estimate evidence for securities in the latest persisted S&P 500
membership snapshot. The workflow retains raw responses, endpoint parameters,
retrieval times, content hashes, and per-dataset refresh status.

Annual and quarterly statements are persisted separately. Only annual FMP
statements are adapted into the FMP-specific canonical annual history used by
future underwriting. Quarterly statements remain raw, period-tagged evidence
and do not enter current annual economics or Feature 7 screening. SEC Company
Facts remains isolated and authoritative for SEC-filed accounting evidence.

Analyst estimates are stored as `EXPECTATION`, with target period, low, average,
high, and analyst counts when provided. Each retrieval time is versioned, even
when the raw estimate payload is unchanged. Earlier expectation snapshots
remain available. No unsupported endpoint or missing response is represented
as complete coverage.

## Refresh workflow

Configure `OWNER_LENS_FMP_API_KEY`. Refresh the complete persisted membership
snapshot and its evidence:

```powershell
uv run owner-lens refresh-sp500
```

For manual validation, limit evidence acquisition to current members while the
complete constituent snapshot is still refreshed:

```powershell
uv run owner-lens refresh-sp500 --tickers ADBE MSFT COST NVDA GOOG GOOGL
```

Use `--force` to bypass persisted freshness windows:

```powershell
uv run owner-lens refresh-sp500 --tickers ADBE --force
```

By default, annual and quarterly statements are reused for 30 days, and EOD
price and estimate evidence is reused for 24 hours. Successful evidence is
read from the configured content-addressed raw store during normal navigation.
The workflow does not contact FMP for a dataset with fresh persisted evidence.
Authentication failures stop the run; exhausted rate limits also stop the run
after the client retry policy, leaving later dataset states safe to resume.
Other per-dataset failures remain explicit while independent datasets continue.

Inspect persisted per-dataset state without network access:

```powershell
uv run owner-lens evidence-status
uv run owner-lens evidence-status --tickers ADBE MSFT COST NVDA GOOG GOOGL
```

## FMP datasets

| Evidence | Stable endpoint | Request window |
|----------|----------------|----------------|
| Annual income statement | `/stable/income-statement` | `period=annual`, `limit=15` |
| Annual balance sheet | `/stable/balance-sheet-statement` | `period=annual`, `limit=15` |
| Annual cash flow statement | `/stable/cash-flow-statement` | `period=annual`, `limit=15` |
| Quarterly income statement | `/stable/income-statement` | `period=quarter`, `limit=8` |
| Quarterly balance sheet | `/stable/balance-sheet-statement` | `period=quarter`, `limit=8` |
| Quarterly cash flow statement | `/stable/cash-flow-statement` | `period=quarter`, `limit=8` |
| Recent EOD prices | `/stable/historical-price-eod/light` | Recent bounded date range; newest validated close persisted |
| Annual analyst estimates | `/stable/analyst-estimates` | `period=annual`, `page=0`, `limit=3` |
| Quarterly analyst estimates | `/stable/analyst-estimates` | `period=quarter`, `page=0`, `limit=4` |

The estimate endpoint is entitlement-dependent. A plan restriction marks that
dataset `UNSUPPORTED` rather than failing the remaining refresh. A missing
target period or malformed response remains explicit.

## Persistence

SQLite schema version 3 adds FMP evidence snapshots, annual canonical histories
and metric coverage, latest EOD prices, and time-stamped estimate rows. Each
raw response is linked by content hash to the configured raw snapshot store.
Security identity remains `security_id`; symbol is a provider identifier, and
CIK remains an optional, non-unique issuer link. No FMP value is inserted into
SEC tables.

The offline coverage command summarizes `PENDING`, `RUNNING`, `SUCCEEDED`,
`PARTIAL`, `FAILED`, and `UNSUPPORTED` states by dataset. A failed annual
statement refresh can retain a prior successfully persisted evidence snapshot;
the failure state still records that the latest attempt did not complete.

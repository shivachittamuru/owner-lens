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
| Historical price pilot | `/stable/historical-price-eod/full` | Up to three years; TYL, ADSK, and NVDA only |
| Current profile metadata | `/stable/profile` | Current security identity metadata for the pilot |
| Stock splits | `/stable/splits` | Raw split-event response for the pilot |
| Annual analyst estimates | `/stable/analyst-estimates` | `period=annual`, `page=0`, `limit=3` |
| Quarterly analyst estimates | `/stable/analyst-estimates` | `period=quarter`, `page=0`, `limit=4` |

The estimate endpoint is entitlement-dependent. A plan restriction marks that
dataset `UNSUPPORTED` rather than failing the remaining refresh. A missing
target period or malformed response remains explicit.

## Historical price pilot

The pilot command persists `historical-price-eod/full`, `profile`, and `splits`
responses as separate FMP evidence snapshots for TYL, ADSK, and NVDA. Each
historical price observation links to its full-history source snapshot. Currency
remains unknown on each price row, and its adjustment basis remains
`UNVERIFIED`. Current profile currency and exchange are not projected onto
historical bars. The pilot does not alter the existing latest EOD price,
screening, or underwriting records, and Workbench navigation does not invoke it.

Create a disposable database and raw-snapshot copy before running the live
pilot. The following PowerShell sequence resolves the configured local paths,
uses SQLite's backup API for a consistent database copy, and copies the raw
snapshot directory:

```powershell
$configured = uv run python -c "import json; from owner_lens.config import load_settings; s = load_settings(); print(json.dumps({'db': s.db_path, 'raw': s.raw_data_path}))" | ConvertFrom-Json
$sourceDb = (Resolve-Path -LiteralPath $configured.db).Path
$sourceRaw = (Resolve-Path -LiteralPath $configured.raw).Path
$pilotRoot = Join-Path (Get-Location) ("data\historical-price-pilot-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $pilotRoot | Out-Null
$pilotDb = Join-Path $pilotRoot "ownerlens.db"
$pilotRaw = Join-Path $pilotRoot "raw"
uv run python -c "import sqlite3,sys; source = sqlite3.connect(sys.argv[1]); target = sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()" $sourceDb $pilotDb
New-Item -ItemType Directory -Path $pilotRaw | Out-Null
Get-ChildItem -LiteralPath $sourceRaw -Force | Copy-Item -Destination $pilotRaw -Recurse
```

Capture a pre-pilot fingerprint of existing latest prices and frozen TYL/ADSK
underwritings, then run only the three-symbol command:

```powershell
$fingerprint = @'
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print(json.dumps({
    "latest_eod": c.execute(
        "SELECT security_id, snapshot_id, market_date, close, source_field, currency "
        "FROM fmp_eod_prices ORDER BY security_id"
    ).fetchall(),
    "underwritings": c.execute(
        "SELECT ticker, version, created_at, as_of_date, content_hash "
        "FROM underwriting_records WHERE ticker IN ('TYL','ADSK') "
        "ORDER BY ticker, version"
    ).fetchall(),
}, sort_keys=True))
'@
$before = uv run python -c $fingerprint $pilotDb
uv run owner-lens historical-price-pilot --db $pilotDb --raw-data $pilotRaw --from 2023-10-30 --to 2026-10-30 --confirm-disposable-store
$after = uv run python -c $fingerprint $pilotDb
if (Compare-Object $before $after) { throw "Latest prices or frozen underwritings changed." }
```

The pilot prints per-symbol observation counts, date bounds, snapshot IDs and
SHA-256 hashes, matched overlaps with existing light-price evidence, and
reported split events. A symbol with no observations is reported unsupported.
An overlap mismatch is reported as a conflict and returns a nonzero exit code.

Check unique-date counts, NVDA's prices around the split, and linked evidence
metadata in the disposable database:

```powershell
$verification = @'
import json, sqlite3, sys
from pathlib import Path
from owner_lens.persistence import FilesystemRawSnapshotStore
c = sqlite3.connect(sys.argv[1])
print("counts:", c.execute(
    "SELECT s.symbol, COUNT(DISTINCT p.market_date), MIN(p.market_date), "
    "MAX(p.market_date) FROM fmp_historical_prices p "
    "JOIN securities s USING (security_id) GROUP BY s.symbol ORDER BY s.symbol"
).fetchall())
print("total unique:", c.execute(
    "SELECT COUNT(*) FROM (SELECT DISTINCT security_id, market_date "
    "FROM fmp_historical_prices)"
).fetchone()[0])
print("NVDA split window:", c.execute(
    "SELECT p.market_date,p.price,p.currency,p.adjustment_basis "
    "FROM fmp_historical_prices p JOIN securities s USING (security_id) "
    "WHERE s.symbol='NVDA' AND p.market_date BETWEEN '2024-06-07' "
    "AND '2024-06-11' ORDER BY p.market_date"
).fetchall())
print("snapshot provenance:", c.execute(
    "SELECT s.symbol,e.dataset,e.source_endpoint,e.fetched_at,e.content_hash "
    "FROM fmp_evidence_snapshots e JOIN securities s USING (security_id) "
    "WHERE e.dataset IN ('historical_price','profile','splits') "
    "AND s.symbol IN ('TYL','ADSK','NVDA') "
    "ORDER BY s.symbol,e.dataset,e.fetched_at"
).fetchall())
raw = FilesystemRawSnapshotStore(Path(sys.argv[2]))
metadata = c.execute(
    "SELECT s.symbol,e.dataset,e.content_hash FROM fmp_evidence_snapshots e "
    "JOIN securities s USING (security_id) WHERE e.dataset IN ('profile','splits') "
    "AND s.symbol IN ('TYL','ADSK','NVDA') ORDER BY s.symbol,e.dataset"
).fetchall()
[print(symbol, dataset, [{
    key: row.get(key) for key in (
        "symbol", "cik", "currency", "exchangeShortName",
        "date", "numerator", "denominator"
    )
} for row in json.loads(raw.get(content_hash))])
 for symbol, dataset, content_hash in metadata]
'@
uv run python -c $verification $pilotDb $pilotRaw
```

List each comparison with the existing light endpoint's raw rows, including any
date or value discrepancy:

```powershell
$overlapCheck = @'
import json, sqlite3, sys
from pathlib import Path
from owner_lens.persistence import FilesystemRawSnapshotStore
c = sqlite3.connect(sys.argv[1])
raw = FilesystemRawSnapshotStore(Path(sys.argv[2]))
snapshots = c.execute(
    "SELECT s.symbol,s.security_id,e.content_hash FROM fmp_evidence_snapshots e "
    "JOIN securities s USING (security_id) WHERE e.dataset='eod_price' "
    "AND s.symbol IN ('TYL','ADSK','NVDA') AND e.snapshot_id=("
    "SELECT old.snapshot_id FROM fmp_evidence_snapshots old "
    "WHERE old.security_id=e.security_id AND old.dataset='eod_price' "
    "ORDER BY old.fetched_at DESC,old.snapshot_id DESC LIMIT 1) "
    "ORDER BY s.symbol"
).fetchall()
for symbol, security_id, content_hash in snapshots:
    old_rows = json.loads(raw.get(content_hash))
    old_prices = {
        row["date"]: row.get("price", row.get("close")) for row in old_rows
    }
    new_rows = c.execute(
        "SELECT market_date,price FROM fmp_historical_prices WHERE security_id=? "
        "AND snapshot_id=(SELECT snapshot_id FROM fmp_evidence_snapshots "
        "WHERE security_id=? AND dataset='historical_price' "
        "ORDER BY fetched_at DESC,snapshot_id DESC LIMIT 1)",
        (security_id, security_id),
    ).fetchall()
    comparisons = [
        (market_date, old_prices[market_date], price, old_prices[market_date] == price)
        for market_date, price in new_rows if market_date in old_prices
    ]
    print(symbol, comparisons)
'@
uv run python -c $overlapCheck $pilotDb $pilotRaw
```

Open the existing Investment View against the pilot copy to confirm the saved
TYL v1 and ADSK v1 hurdle displays remain unchanged:

```powershell
$env:OWNER_LENS_RAW_DATA_PATH = $pilotRaw
uv run owner-lens workbench --db $pilotDb --provider fmp
```

The expected result is about 754 unique dates per symbol and 2,262 total for
the probe's October 30, 2026 endpoint. Inspect all overlaps, not just the count.
NVDA split continuity is observational evidence only; it does not establish a
price adjustment factor for financial ratios. Revisions from a later pilot are
stored as separate snapshot-linked observations rather than overwriting rows,
and disagreements with saved EOD or prior historical observations are reported.

## Persistence

SQLite schema version 14 adds dated historical price observations alongside FMP
evidence snapshots, annual canonical histories and metric coverage, latest EOD
prices, and time-stamped estimate rows. Historical price rows link to their
source snapshot, which retains the endpoint, request parameters, retrieval time,
content hash, and raw object reference. Each raw response is linked by content
hash to the configured raw snapshot store.
Security identity remains `security_id`; symbol is a provider identifier, and
CIK remains an optional, non-unique issuer link. No FMP value is inserted into
SEC tables.

The offline coverage command summarizes `PENDING`, `RUNNING`, `SUCCEEDED`,
`PARTIAL`, `FAILED`, and `UNSUPPORTED` states by dataset. A failed annual
statement refresh can retain a prior successfully persisted evidence snapshot;
the failure state still records that the latest attempt did not complete.

Legacy `annual_statements`, `quarterly_statements`, and `analyst_estimates`
aggregate rows are resolved from their component states on read, without
refetching evidence or changing stored refresh state. Any failed child makes
the aggregate `FAILED`; otherwise an active child makes it `RUNNING`. All
succeeded, unsupported, or pending children retain that respective status.
Other combinations are `PARTIAL`, with missing children treated as pending.
Individual state reads, state lists, and offline coverage counts use the same
resolution rule.

---
title: "Feature 8A1: Versioned S&P 500 Universe"
description: "FMP-backed S&P 500 membership snapshots and resumable refresh state."
ms.topic: reference
keywords:
  - FMP
  - S&P 500
  - universe
  - refresh
---

## Scope

Feature 8A1 adds the FMP S&P 500 constituent endpoint as a versioned universe
source. It stores raw response provenance, immutable membership snapshots,
stable internal security IDs, and pending dataset refresh state. It does not
ingest financial statements, prices, or estimates, and it does not change
screening or the workbench.

SEC remains authoritative for filed accounting facts. FMP membership metadata
does not become financial truth, and a CIK is an optional, non-unique issuer
link rather than the identity of a security. Separate share classes such as
GOOG and GOOGL remain distinct securities.

## Refresh

Configure `OWNER_LENS_FMP_API_KEY`, then run:

```powershell
uv run owner-lens refresh-sp500
```

The command fetches `/stable/sp500-constituent`, validates the full response
without requiring exactly 500 rows, stores a content-addressed raw payload, and
adds a snapshot when the response content is new. Repeating an unchanged
response reuses its snapshot. Existing snapshots and security refresh states
remain available after later refreshes.

Use a bounded ticker list to initialize future dataset refresh state only for
those current members. The complete membership response is still validated and
persisted:

```powershell
uv run owner-lens refresh-sp500 --tickers ADBE GOOG GOOGL MSFT COST
```

Authentication, plan restriction, rate limit, transport, malformed-response,
and persistence errors are reported as failures. Transient transport errors,
HTTP 429, and selected 5xx responses receive bounded retries. A rerun after an
interruption is safe: committed membership is content-addressed and
idempotent, while pending state is preserved.

## Persisted identity and provenance

`security_id` is the internal security identity. The current symbol is a
mutable provider identifier; it is not used as issuer identity. CIK is stored
without a uniqueness constraint, so multiple listed share classes may refer to
one issuer. Every membership row keeps its symbol, name, optional CIK, sector,
and subsector for that snapshot.

Universe snapshots record the provider, observation time, endpoint URI,
content hash, and raw-object reference. The raw payload remains in the
configured content-addressed raw store. SQLite schema version 2 adds these
universe and refresh-state tables while preserving the existing SEC company
and financial-evidence tables.

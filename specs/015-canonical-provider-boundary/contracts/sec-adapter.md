---
title: "Contract: SEC Adapter"
description: Contract for owner_lens.sec_adapter, which maps raw SEC Company Facts into a canonical financial history
ms.date: 2026-10-05
ms.topic: reference
---

## Module

`owner_lens.sec_adapter`. This is the only module that knows both the SEC normalizers and the
canonical model.

## Public names

```python
SEC_PROVIDER: Final = "sec"

def canonical_history_from_sec(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> CanonicalFinancialHistory: ...
```

The `ticker` and `max_years` defaults match the existing `*_from_facts` defaults.

## Behavior

1. Canonicalizes `ticker` first. An empty ticker raises `ValueError` immediately.
2. Calls the existing SEC normalizers unchanged, one per canonical metric, using the window rules
   in [data-model.md](../data-model.md#sec-mapping-owned-by-sec_adapterpy): `max_years` for
   duration metrics, `max_years + 1` for instant metrics.
3. Converts each resulting `AnnualObservation` to a `CanonicalFact`:
   * `provider = "sec"`
   * `provider_field = observation.concept`
   * `form`, `filed`, `accession`, `value`, `unit`, `fiscal_year`, `fiscal_period`, and
     `period_end` are copied.
   * `period_start` is copied for duration metrics and set to `None` for instant metrics.
4. Assigns each metric's status:
   * The normalizer returned observations: `AVAILABLE`.
   * A tolerant normalizer (dividends, short-term investments) returned an empty series:
     `STRUCTURALLY_ABSENT`.
   * A concept-not-found error: `UNSUPPORTED`, with `reason = str(error)` and `error = error`.
   * An ambiguous or malformed error: `INVALID`, with `reason = str(error)` and `error = error`.
5. Never raises for a per-metric normalization failure. Such failures are stored and surface only
   when a downstream entry point requires that metric.
6. Performs no network access and does not mutate `raw_facts`.

## Non-goals

* No change to concept preferences, per-company overrides, period selection, duplicate handling,
  or ambiguity detection.
* No provider selection, no reconciliation, no FMP.

---
title: "Quickstart: Canonical Provider Boundary"
description: Validation scenarios proving OwnerLens Slice 5A routes all downstream logic through a provider-neutral canonical history
ms.date: 2026-10-05
ms.topic: how-to
---

## Prerequisites

* Python 3.12 or later and `uv`.
* The repository is synced with `uv sync`.
* `SEC_USER_AGENT` is set (in `.env` or the environment). Only the notebook needs it; every test
  runs offline.

## 1. Capture the regression baseline before refactoring

Run this once, on the pre-refactor code, to record today's outputs:

```powershell
uv run python tests/test_canonical_regression.py --update-baseline
uv run pytest tests/test_canonical_regression.py
```

Expected result: `tests/data/canonical_baseline.json` is written, and the test passes against
unchanged code. Commit the baseline before touching downstream modules. See research
[R11](research.md#r11-regression-oracle).

## 2. Validate the canonical model and SEC adapter

```powershell
uv run pytest tests/test_canonical.py tests/test_sec_adapter.py
```

Expected results:

* For ADBE, V, and COST, every canonical fact equals the SEC normalizer observation for the same
  metric and year. Its `provider` is `sec`, and its `provider_field` is the selected concept.
* V `diluted_shares` is `UNSUPPORTED`. ADBE `dividends_paid` and V `short_term_investments` are
  `STRUCTURALLY_ABSENT`.
* A conflicting repurchases value yields `repurchases` as `INVALID`. `require("repurchases")`
  raises `AmbiguousValueError` with the original message. Owner economics still succeeds.
* Instant facts have `period_start is None`, and duration facts have a start date.

## 3. Validate downstream consumption and preserved semantics

```powershell
uv run pytest tests/test_canonical_downstream.py tests/test_canonical_regression.py
```

Expected results:

* Each `*_from_history` result equals the matching `*_from_facts` result for ADBE, V, and COST.
* A history built with `provider="test"` and no SEC payload produces correct hand-calculated owner
  economics, capital efficiency, and Feature 2 classifications.
* The regression baseline matches exactly: persisted records, formatted views, and
  exception type and message per layer.

## 4. Validate the architecture boundary

```powershell
uv run pytest tests/test_canonical_boundary.py
```

Expected results:

* None of the seven downstream modules imports a SEC module other than the single allowed
  `sec_adapter` wrapper import.
* None of them contains a SEC concept string.
* Every `*_from_history` function accepts `CanonicalFinancialHistory`.

## 5. Full quality gates

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected result: all three commands pass with zero failures, and every existing test passes with
its assertions unchanged.

## 6. Notebook walkthrough

Open `notebooks/12_canonical_provider_boundary.ipynb` and run all cells. Expected output:

1. Retrieval context: ADBE CIK and the payload content hash.
2. One raw SEC concept's annual facts.
3. Canonical facts showing metric, value, fiscal year, provider `sec`, provider field, and accession.
4. Metric status tables for ADBE and V.
5. Owner economics computed by `owner_economics_from_history`.
6. A synthetic `provider="test"` history producing owner economics without any SEC data.

## 7. Production path smoke check (optional, live)

```powershell
uv run owner-lens ingest ADBE
```

Expected result: the same `IngestionStatus` and persisted counts as before this slice.

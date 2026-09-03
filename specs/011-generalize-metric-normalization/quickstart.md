---
title: Generalize Metric Normalization Quickstart
description: Validation guide for multi-company canonical metric normalization across ADBE, V, and COST
ms.date: 2026-09-02
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* Internet access only for the optional live coverage check
* A declared SEC User-Agent such as `OwnerLens admin@example.com` for the optional live check

Review the [public API contract](contracts/public-api.md), [data model](data-model.md), and the
compatibility matrix in [research.md](research.md) before validating behavior.

## Install the project environment

```powershell
uv sync
```

## Run deterministic validation

Run the default test suite. These tests use controlled ADBE, V, and COST fact fixtures and do not
require live SEC access:

```powershell
uv run pytest
```

Expected outcome:

* Registry resolution returns the default preference when no override exists, the override preference
  when one exists, deterministic ordering for repeated calls, and a clear failure for an unknown
  metric.
* For ADBE, V, and COST fixtures, the in-scope duration and instant metrics normalize with correct
  canonical meaning and unit, or fail explicitly where documented.
* Debt for V and COST resolves through `LongTermDebtCurrent` and `LongTermDebtNoncurrent` with no
  double count; Adobe debt is unchanged.
* Visa short-term investments resolves as a tolerant-absent empty series, and Visa diluted
  weighted-average shares fails explicitly as unsupported.
* Every normalized series reports the actual selected source concept as provenance.
* Every previously passing Adobe Feature 1 and Feature 2 assertion still passes.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the multi-company flow

Use controlled fact fixtures for ADBE, V, and COST that mirror the concepts recorded in
[research.md](research.md). For each company confirm:

* Revenue, operating income, net income, operating cash flow, capital expenditures, income tax, and
  pretax income normalize as canonical duration series with provenance.
* Cash, total assets, total equity, current debt, and long-term debt normalize as canonical instant
  series, with the documented V and COST debt and V equity overrides applied.
* Capital-expenditures sign behavior is preserved as in Feature 1.
* Absent and unsupported metrics (Visa short-term investments; Visa diluted shares) are surfaced
  explicitly and never as a fabricated or zero value.

## Confirm the Adobe regression

Confirm that Adobe's normalized series and downstream owner-economics, capital-efficiency,
capital-allocation, and economic-value outputs are unchanged, and that the generalized registry
selects the same Adobe concepts as before.

## Run the optional live coverage check

Configure a real administrative contact before making SEC requests.

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
```

Then, for ADBE, V, and COST, retrieve raw facts once per company and normalize the in-scope metrics,
producing a concise coverage report similar to:

```text
Metric            ADBE   V      COST
Revenue           ok     ok     ok
Operating Income  ok     ok     ok
Net Income        ok     ok     ok
OCF               ok     ok     ok
CapEx             ok     ok     ok
Diluted Shares    ok     n/a    ok
Cash              ok     ok     ok
Debt              ok     ok     ok
Assets            ok     ok     ok
Equity            ok     ok     ok
Tax Inputs        ok     ok     ok
```

Where `n/a` denotes an explicitly unsupported or non-applicable metric (Visa diluted shares; and, for
short-term investments, Visa's tolerant absence). Inspect provenance for at least revenue, capital
expenditures, and the debt components for each company to confirm identical canonical meanings arise
from different SEC concepts without losing traceability.

The live check is manual because SEC availability and filing data change independently of OwnerLens.
Keep it outside the default automated suite and do not run it repeatedly or concurrently.

## Educational notebook

Run `notebooks/07_multi_company_metric_normalization.ipynb` to walk through what a canonical metric
is, why the same economic concept maps to different SEC concepts across ADBE, V, and COST, where
overrides are required, how provenance is preserved, and why an explicit unsupported metric is
better than a guessed value.

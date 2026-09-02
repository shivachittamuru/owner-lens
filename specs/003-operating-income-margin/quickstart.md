---
title: Adobe Operating Income and Margin Quickstart
description: Validation guide for the ADBE operating income and operating margin slice
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for normalization, alignment, margin, or their tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New tests use controlled in-memory Company Facts fixtures and make no
network calls, and all existing Slice 1A and 1B tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* Operating-income normalization yields one observation per fiscal year for up to the latest five years, newest first.
* Quarterly and year-to-date observations never appear in the operating-income series.
* Identical comparative repeats collapse to one observation per year with earliest-filed provenance.
* Missing-concept and conflicting-value fixtures raise explicit typed failures.
* Revenue and operating income align by economic fiscal year.
* Operating margin equals operating income divided by revenue only where both inputs exist and revenue is non-zero.
* Existing Slice 1A and 1B tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the successful ADBE alignment

Using a controlled Adobe-shaped payload with revenue and operating income, confirm:

* Each operating-income observation uses a single concept and derives its fiscal year from the period end date.
* The aligned rows pair revenue and operating income by the same economic fiscal year.
* Each computed margin references its revenue and operating-income inputs and is distinguishable from a reported fact.
* Values are preserved exactly, with no rounding or aggregation of the reported inputs.

## Validate failures and edges

Run focused tests for the terminal failures and derived-metric edges in the [data model](data-model.md):

```powershell
uv run pytest -k "concept or ambiguous or malformed or unsupported or margin or zero or missing or align"
```

Expected outcome: every failure scenario raises its documented typed error, and every missing-input
or zero-revenue year omits the margin explicitly rather than emitting an invented, infinite, or
undefined value.

## Run the optional live end-to-end check

Normalization and derivation are offline. To validate against current Adobe data, retrieve the raw
payload through Slice 1, then normalize, align, and derive in one Python session:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, normalize_annual_revenue, normalize_annual_operating_income, align_annual_metrics; c=SecClient('OwnerLens admin@example.com'); raw=c.retrieve_company_facts('ADBE').raw_facts; rev=normalize_annual_revenue(raw); oi=normalize_annual_operating_income(raw); rows=align_annual_metrics(rev, oi); [print(r.fiscal_year, r.revenue.value if r.revenue else None, r.operating_income.value if r.operating_income else None, round(r.operating_margin.value, 4) if r.operating_margin else None) for r in rows]"
```

Expected outcome under normal SEC availability: up to five recent fiscal years print newest first
with revenue, operating income, and operating margin. Inspect one operating-income observation's
provenance to confirm concept, period, form, filing date, and accession. This live check stays
outside the default suite because SEC data changes independently of OwnerLens.

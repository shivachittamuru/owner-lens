---
title: Adobe Annual Revenue Normalization Quickstart
description: Validation guide for the ADBE annual revenue normalization slice
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for normalization or its tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the default test suite. These tests use controlled in-memory Company Facts fixtures and make no
network calls:

```powershell
uv run pytest
```

Expected outcome:

* The happy-path fixture yields one observation per fiscal year for up to the latest five years, newest first.
* Quarterly and year-to-date observations never appear in the series.
* Identical comparative repeats and amended-filing repeats collapse to one observation per year.
* Each observation exposes its concept, unit, derived fiscal year, fiscal period, period dates, form, filing date, accession, and exact value.
* Missing-concept and conflicting-value fixtures raise explicit typed failures.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the successful ADBE series

Using a controlled Adobe-shaped payload, confirm the resolved series:

* Uses a single revenue concept for every observation.
* Derives each fiscal year from the period end date rather than the raw `fy` field.
* Orders observations by fiscal year descending and contains at most one per year.
* Preserves values exactly, with no rounding, rescaling, interpolation, or aggregation.

## Validate failures

Run focused tests for each terminal failure category described in the [data model](data-model.md):

```powershell
uv run pytest -k "missing or ambiguous or malformed or unsupported"
```

Expected outcome: every scenario raises its documented typed failure and none returns an empty or
partial series.

## Run the optional live end-to-end check

Normalization itself is offline. To validate against current Adobe data, retrieve the raw payload
through Slice 1, then normalize it in one Python session:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, normalize_annual_revenue; c=SecClient('OwnerLens admin@example.com'); r=c.retrieve_company_facts('ADBE'); s=normalize_annual_revenue(r.raw_facts); [print(o.fiscal_year, o.value, o.concept, o.accession) for o in s.observations]"
```

Expected outcome under normal SEC availability: up to five recent fiscal years print newest first
with their exact reported revenue values and source accession numbers. This live check stays outside
the default suite because SEC data changes independently of OwnerLens.

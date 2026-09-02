---
title: Adobe Core Owner Economics Quickstart
description: Validation guide for the ADBE owner-economics slice
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for normalization, derivation, or their tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New tests use controlled in-memory Company Facts fixtures and make no
network calls, and all existing Slice 1A through 1C tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* Each new reported metric yields one observation per fiscal year for up to the latest five years, newest first.
* The diluted-share series selects the weighted-average diluted concept in the `shares` unit, not point-in-time shares outstanding.
* Quarterly and year-to-date observations never appear in any canonical series.
* Identical comparative repeats collapse to one observation per year with earliest-filed provenance.
* Missing-concept and conflicting-value fixtures raise explicit typed failures.
* Free cash flow equals operating cash flow minus a positive capital expenditure amount.
* Net margin, FCF margin, and FCF per diluted share match their formulas and are omitted on missing inputs or zero denominators.
* Adjacent-year growth is computed only between consecutive fiscal years and omitted for the earliest year.
* Existing Slice 1A through 1C tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate CapEx and diluted-share semantics

Using controlled Adobe-shaped payloads, confirm:

* The reported CapEx observation preserves the source value, and derived free cash flow uses the positive magnitude.
* The diluted-share observation carries the `shares` unit and represents the weighted-average diluted count for the fiscal year.
* Substituting a point-in-time shares-outstanding fixture does not change the selected diluted-share series.

## Validate failures and edges

Run focused tests for the terminal failures and derived-metric edges in the [data model](data-model.md):

```powershell
uv run pytest -k "concept or ambiguous or malformed or unsupported or capex or shares or margin or fcf or growth or zero or missing or align"
```

Expected outcome: every failure scenario raises its documented typed error, and every missing-input,
zero-denominator, or earliest-year case omits the dependent metric explicitly rather than emitting an
invented, infinite, or undefined value.

## Run the optional live end-to-end check

Normalization and derivation are offline. To validate against current Adobe data, retrieve the raw
payload through Slice 1, then build the owner-economics view in one Python session:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, owner_economics_from_facts; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; rows=owner_economics_from_facts(raw); [print(r.fiscal_year, r.free_cash_flow, round(r.fcf_margin, 4) if r.fcf_margin is not None else None, round(r.fcf_per_share, 2) if r.fcf_per_share is not None else None) for r in rows]"
```

Expected outcome under normal SEC availability: up to five recent fiscal years print newest first
with free cash flow, FCF margin, and FCF per diluted share. Inspect provenance for the operating cash
flow, capital expenditures, and diluted-share observations to confirm concept, unit, period, form,
filing date, and accession. This live check stays outside the default suite because SEC data changes
independently of OwnerLens.

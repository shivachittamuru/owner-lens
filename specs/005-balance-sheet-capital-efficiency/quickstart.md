---
title: Adobe Balance Sheet and Capital Efficiency Quickstart
description: Validation guide for the ADBE balance-sheet and capital-efficiency slice
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
network calls, and all existing Slice 1A through 1D tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* Each balance-sheet fact yields one fiscal-year-end observation per fiscal year for up to the latest five years, newest first.
* Instant facts are selected by period-end date, and duration facts are never selected as balance-sheet observations.
* Interim quarter-end observations never appear in any fiscal-year-end series.
* Identical comparative repeats collapse to one observation per year with earliest-filed provenance.
* Missing-concept and conflicting-value fixtures raise explicit typed failures.
* Cash plus short-term investments avoids double counting, and total debt equals current debt plus long-term debt.
* ROA, ROE, and ROIC use average balances and are omitted when a beginning-year baseline is unavailable.
* NOPAT uses the reported effective tax rate, and ROIC is omitted when pretax income is missing or zero.
* Existing Slice 1A through 1D tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate instant-versus-duration handling

Using controlled payloads, confirm:

* A balance-sheet instant fact with no start date is selected by its fiscal-year-end date.
* A duration fact with a start date is not selected by the instant path, and the existing duration normalization still works.
* A prior fiscal-year-end value repeated across later filings collapses to the earliest-filed observation.

## Validate capital-efficiency derivations

Confirm against known inputs:

* Cash plus short-term investments equals cash plus short-term investments, and net cash equals that minus total debt.
* Average total assets and average total equity equal the mean of beginning and ending balances.
* Invested capital equals total debt plus total equity minus cash plus short-term investments.
* NOPAT equals operating income times one minus the effective tax rate.
* ROA, ROE, and ROIC equal their documented formulas and are omitted for the earliest year lacking a baseline.

## Validate failures and edges

Run focused tests for the terminal failures and derived-metric edges in the [data model](data-model.md):

```powershell
uv run pytest -k "instant or concept or ambiguous or malformed or unsupported or cash or debt or asset or equity or average or invested or tax or nopat or roa or roe or roic or baseline or zero or missing"
```

Expected outcome: every failure scenario raises its documented typed error, and every missing-input,
missing-baseline, or zero-denominator case omits the dependent metric explicitly rather than emitting
an invented, infinite, or undefined value.

## Run the optional live end-to-end check

Normalization and derivation are offline. To validate against current Adobe data, retrieve the raw
payload through Slice 1, then build the capital-efficiency view in one Python session:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, capital_efficiency_from_facts; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; rows=capital_efficiency_from_facts(raw); [print(r.fiscal_year, r.net_cash, r.total_debt, round(r.roe, 4) if r.roe is not None else None, round(r.roic, 4) if r.roic is not None else None) for r in rows]"
```

Expected outcome under normal SEC availability: up to five recent fiscal years print newest first
with net cash or net debt, total debt, ROE, and ROIC. Inspect provenance for the cash, short-term
investments, current debt, long-term debt, total assets, and total equity observations to confirm
concept, unit, fiscal-year-end date, form, filing date, and accession. This live check stays outside
the default suite because SEC data changes independently of OwnerLens.

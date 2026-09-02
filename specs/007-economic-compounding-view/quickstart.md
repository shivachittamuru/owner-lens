---
title: Multi-Year Economic Compounding View Quickstart
description: Validation guide for the ADBE deterministic multi-year compounding interpretation layer
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for compounding-view construction, classification, or their tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New tests construct in-memory `OwnerEconomicsRow`, `CapitalEfficiencyRow`, and
`EconomicValueSnapshot` fixtures directly and make no network calls, and all existing Slice 1A through
1E and Slice 2A tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* Each requested period yields one `EconomicCompoundingView` with the correct start fiscal year, end fiscal year, and interval count.
* Each CAGR equals the standard formula over the fiscal-year interval count, and a five-year span (FY2021 through FY2025) uses four intervals as the exponent denominator.
* Missing-endpoint, zero-beginning, negative-beginning, and sign-changing CAGR inputs return an explicit unavailable result rather than a fabricated rate.
* Compounding rates and start-to-end level changes are separately populated, and no field blends them.
* Strongly compounding, moderately compounding, stable, and deteriorating fixtures produce the expected classification.
* High FCF-per-share CAGR driven by share-count reduction while aggregate FCF falls materially is not classified strongly compounding, and drivers surface the aggregate decline and share-count source.
* Strong aggregate growth with material dilution is tempered, and falling FCF-per-share CAGR with declining ROIC is classified deteriorating.
* The recent three-year and longest five-year periods are selected deterministically, and an unsupported period reports insufficient history.
* The view reports the counts of annual snapshots classified improving, stable, deteriorating, and insufficient-data, and the multi-year classification is not a simple average of them.
* Existing Slice 1A through 1E and Slice 2A tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the CAGR mechanics

Using known endpoints, confirm against the [data model](data-model.md):

* A five-year span from FY2021 through FY2025 uses four intervals: `cagr(begin, end, 4)`.
* Positive growth, a flat series, and a decline each return the expected rate.
* Missing endpoints, a zero beginning, a negative beginning, and a sign change return `None`.

## Validate the compounding classification and drivers

Confirm against known inputs and the [data model](data-model.md):

* The insufficiency gate returns `INSUFFICIENT_DATA` whenever `fcf_per_share_cagr` is absent.
* The primary base follows the `strong` and `healthy` FCF-per-share CAGR thresholds and the flat band.
* The share-count-driven illusion, material dilution, and ROIC deterioration each temper the base by one notch, clamped at `STABLE`.
* A deteriorating base with declining ROIC stays deteriorating; a stable base resolves by corroborating secondary signals.
* Drivers are emitted in the fixed priority order defined in the [data model](data-model.md).

## Validate period selection and missing-data edges

Run focused tests for the period and invalid-input cases:

```powershell
uv run pytest -k "cagr or interval or period or strong or moderate or stable or deteriorating or dilution or shrink or roic or margin or balance or mixed or insufficient or boundary or driver"
```

Expected outcome: every invalid-CAGR and insufficient-history case surfaces explicitly, and each period
is selected deterministically from the canonical fiscal years.

## Run the optional live end-to-end check

Compounding-view construction and classification are offline. To validate against current Adobe data,
build the views in one Python session; retrieval and normalization happen inside the Feature 1 and
Feature 2A entry points, not in the compounding layer:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, compounding_views_from_facts, format_compounding_view; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; three, five = compounding_views_from_facts(raw); print(format_compounding_view(three)); print(); print(format_compounding_view(five))"
```

Expected outcome under normal SEC availability: the recent three-year and longest five-year Adobe
compounding views print with revenue, aggregate FCF, FCF-per-share, and diluted-share CAGR, the
start-to-end operating margin, FCF margin, ROIC, and net cash or net debt, the annual-classification
counts, the classification, and the ordered drivers, letting a reader compare recent momentum against
the longer-run economics. This live check stays outside the default suite because SEC data changes
independently of OwnerLens.

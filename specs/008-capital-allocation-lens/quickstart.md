---
title: Capital Allocation Lens Quickstart
description: Validation guide for the ADBE capital-allocation facts and interpretation layer
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for interpretation or its tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New reported-fact tests use controlled in-memory Company Facts fixtures, new
interpretation tests construct inputs directly, and all existing Slice 1A through 1E, 2A, and 2B tests
must still pass, including after the shared trajectory refactor:

```powershell
uv run pytest
```

Expected outcome:

* Repurchases, SBC, and dividends normalize with full-year selection, comparative-repeat collapse, and typed ambiguity failure.
* The repurchase value is the reported cash outflow, never inferred from share-count or treasury-stock changes.
* SBC selects the preferred concept, and the dividend normalizer returns an absent series because Adobe reports no dividend concept.
* A reported zero, a confidently-absent concept, and unavailable data are distinguished, with no fabricated zero.
* Repurchases/FCF, dividends/FCF, SBC/FCF, capital returned, capital returned/FCF, and retained FCF equal their documented formulas, and retained FCF is negative and preserved when capital returned exceeds free cash flow.
* Buyback effectiveness matches the intended outcome across effective, partially-offset, ineffective, net-dilution, no-activity, and insufficient-data cases, using the actual diluted-share-count change.
* Owner-friendly, balanced, questionable, and owner-unfriendly cases classify as intended with deterministic ordered drivers.
* Drawing down surplus cash while remaining net-cash positive is not a balance-sheet deterioration, while deepening net debt is, using the reused trajectory logic.
* Existing Slice 1A through 1E, 2A, and 2B tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the reported facts

Using controlled payloads, confirm against the [data model](data-model.md):

* Each fact returns one full-year observation per fiscal year with full provenance, newest first.
* Interim and repeated comparative observations are excluded or collapsed to the earliest-filed observation.
* A missing repurchase or SBC concept raises `ConceptNotFoundError`; a missing dividend concept returns an empty series.

## Validate the derived metrics and interpretation

Confirm against known inputs and the [data model](data-model.md):

* Retained FCF equals free cash flow minus repurchases minus dividends, and a negative result is preserved.
* Capital returned equals repurchases plus dividends, with dividends contributing zero only under a confirmed no-dividend program and a `NO_DIVIDEND_PROGRAM` driver.
* Buyback effectiveness and the classification follow the documented rules and thresholds, and identical inputs produce identical ordered drivers.
* ROIC context is surfaced without a return-on-retained-FCF calculation.

## Validate failures and edges

Run focused tests for the terminal failures and interpretation edges:

```powershell
uv run pytest -k "repurchase or dividend or sbc or retained or buyback or effective or dilution or owner or balanced or questionable or leverage or roic or driver or ambiguous or absent"
```

Expected outcome: every failure raises its documented typed error, and every missing-input, absent-concept, or negative-residual case is handled explicitly rather than fabricated.

## Run the optional live end-to-end check

Interpretation is offline. To validate against current Adobe data, build the view and summary in one
Python session; retrieval and normalization happen inside the reported and Feature 1 and 2A entry
points, not in the interpretation layer:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, capital_allocation_from_facts, format_capital_allocation_view, capital_allocation_summary; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; rows=capital_allocation_from_facts(raw); print(format_capital_allocation_view(rows)); print(); print(capital_allocation_summary(rows))"
```

Expected outcome under normal SEC availability: approximately five fiscal years print newest first with
free cash flow, repurchases and repurchases/FCF, dividends (none), SBC and SBC/FCF, capital returned and
capital returned/FCF, retained FCF (negative in the heavy-repurchase years), diluted-share growth,
buyback effectiveness, net cash or net debt, ROIC, the classification, and ordered drivers, followed by
a multi-year summary answering the owner questions. This live check stays outside the default suite
because SEC data changes independently of OwnerLens.

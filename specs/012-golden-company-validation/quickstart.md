---
title: Golden-Company Validation Quickstart
description: Validation guide for the full pipeline and honest partial coverage across ADBE, V, and COST
ms.date: 2026-09-03
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* Internet access only for the optional live coverage check
* A declared SEC User-Agent such as `OwnerLens admin@example.com` for the optional live check

Review the [public API contract](contracts/public-api.md), [data model](data-model.md), and the live
pipeline audit and threshold audit in [research.md](research.md) before validating behavior.

## Install the project environment

```powershell
uv sync
```

## Run deterministic validation

Run the default test suite. These tests use controlled ADBE, V, and COST fixtures and do not require
live SEC access:

```powershell
uv run pytest
```

Expected outcome:

* ADBE and COST run through every layer to completion.
* Visa's owner economics and Feature 2 layers complete, with per-share fields `None` and per-share
  classifications `INSUFFICIENT_DATA`, while revenue, free cash flow, capital efficiency, and
  capital-allocation reported facts remain available.
* Coverage states are distinct: available, structurally absent, unsupported, reported zero, and
  insufficient are never conflated.
* A low-margin healthy-trajectory company is not classified deteriorating; a high-margin weakening
  company is not classified improving; strong ROIC is recognized across margin structures.
* The cross-company coverage report is deterministic with a reason for every non-available cell.
* Every existing Adobe Feature 1 and Feature 2 assertion still passes.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate honest partial coverage (Visa)

Confirm that with Visa's unsupported diluted weighted-average shares:

* `owner_economics_from_facts` completes with `None` per-share fields and populated non-per-share
  fields (no fabricated denominator, no point-in-time substitute).
* `economic_value_from_facts`, `compounding_views_from_facts`, `capital_allocation_from_facts`, and
  `economic_value_summary_from_facts` complete, with per-share-dependent classifications reported
  `INSUFFICIENT_DATA` and the reason naming unsupported diluted shares.
* `company_coverage` records diluted shares as `UNSUPPORTED`, short-term investments as
  `STRUCTURALLY_ABSENT`, and capital efficiency as `AVAILABLE`.

## Confirm the Adobe regression

Confirm Adobe runs every layer to completion with unchanged values, classifications, and provenance,
and that the diluted-shares tolerance path is never taken for Adobe.

## Run the optional live coverage report

Configure a real administrative contact before making SEC requests:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
```

Then produce the cross-company coverage report and per-company output for ADBE, V, and COST. Expected
shape:

```text
Company  Fundamentals  OwnerEcon  CapEff  AnnualEV  Compounding  CapAlloc  EVSummary
ADBE     FULL          FULL       FULL    FULL      FULL         FULL      FULL
V        PARTIAL       PARTIAL    FULL    INSUFF    INSUFF       PARTIAL   INSUFF
COST     FULL          FULL       FULL    FULL      FULL         FULL      FULL
```

Every non-full cell for Visa must name unsupported diluted weighted-average shares as the reason. For
all available normalized values, provenance (the actual selected source concept) is preserved.

Judge success not by whether every cell is full, but by whether every available, absent, unsupported,
and insufficient result is economically honest.

## Educational notebook

Run `notebooks/08_golden_company_validation.ipynb` to walk through why these three companies were
chosen, what generalized cleanly, what Visa and Costco exposed, full versus partial analytical
coverage, why unsupported is better than fabricated, whether the Feature 2 thresholds are
business-model independent, and the remaining assumptions to solve before scaling the universe.

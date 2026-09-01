---
title: SEC Company Facts Retrieval Quickstart
description: Validation guide for the ADBE SEC identity and raw Company Facts vertical slice
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* Internet access only for the optional live validation
* A declared SEC User-Agent containing the application identity and administrative contact, such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root, synchronize locked project and development dependencies:

```powershell
uv sync
```

## Run deterministic validation

Run the default test suite. These tests use controlled SEC responses and do not require live SEC access:

```powershell
uv run pytest
```

Expected outcome:

* All identity-resolution and Company Facts tests pass.
* Requests target the SEC mapping and ten-digit-CIK Company Facts locations.
* Both requests carry the configured declared User-Agent.
* The returned raw payload equals the controlled source payload.
* Missing mappings, ambiguous mappings, transport failures, unsuccessful statuses, malformed payloads, and CIK conflicts raise explicit failures.

Run static checks after the test suite:

```powershell
uv run ruff check .
uv run mypy src tests
```

Expected outcome: all checks complete without errors.

## Validate the successful ADBE flow

Use a controlled mapping containing one ADBE record and a controlled Company Facts object containing Adobe's matching CIK, `entityName`, and representative `facts` descendants.

Confirm the completed result:

* Exposes ticker `ADBE`, the SEC conformed company name, and a ten-digit CIK.
* Requests Company Facts with the same ten-digit CIK.
* Preserves every supplied field and nested value in the raw object.
* Performs no revenue extraction, concept mapping, period normalization, scoring, or inference.

## Validate failures

Run focused tests for each terminal failure category described in the [data model](data-model.md):

```powershell
uv run pytest -k "unsupported or resolution or transport or status or malformed or mismatch"
```

Expected outcome: every scenario raises its documented typed failure and no scenario returns an empty, invented, or partial successful result.

## Run the optional live smoke check

Configure a real administrative contact before making SEC requests. Do not commit personal contact details or use a generic browser User-Agent.

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run owner-lens ADBE
```

Expected outcome under normal SEC availability: the command reports Adobe's ticker, SEC conformed name, and ten-digit CIK and confirms retrieval of a raw Company Facts object. The validation path must not print or transform financial metrics.

The live check is manual because SEC availability and filing data change independently of OwnerLens. Keep it outside the default automated suite and do not run it repeatedly or concurrently.

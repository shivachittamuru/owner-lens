---
title: Generalize Company Identity Quickstart
description: Validation guide for multi-company SEC identity resolution and raw Company Facts retrieval
ms.date: 2026-09-02
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* Internet access only for the optional live validation
* A declared SEC User-Agent containing the application identity and administrative contact, such as
  `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before
validating behavior.

## Install the project environment

From the repository root, synchronize locked project and development dependencies:

```powershell
uv sync
```

## Run deterministic validation

Run the default test suite. These tests use controlled multi-company SEC responses and do not
require live SEC access:

```powershell
uv run pytest
```

Expected outcome:

* ADBE, V, COST, and an additional arbitrary mapped ticker each resolve to their own identity.
* Lowercase, uppercase, and whitespace-padded tickers resolve to the same canonical identity.
* Requests target the SEC mapping and ten-digit-CIK Company Facts locations with the configured
  declared User-Agent.
* Each returned raw payload equals the controlled source payload for the matching company.
* Empty and whitespace-only input fails as malformed input without network access.
* Unmapped tickers, ambiguous entries, transport failures, unsuccessful statuses, malformed
  payloads, and CIK conflicts raise their explicit typed failures.
* Every previously passing Adobe assertion still passes.

Run static checks after the test suite:

```powershell
uv run ruff check .
uv run mypy src tests
```

Expected outcome: all checks complete without errors.

## Validate the successful multi-company flow

Use a controlled mapping containing ADBE, V, COST, and one additional record, each with a matching
controlled Company Facts object carrying the same CIK, a non-empty `entityName`, and representative
`facts` descendants.

For each of ADBE, V, and COST confirm the completed result:

* Exposes the canonical ticker, the SEC conformed company name, and a ten-digit CIK.
* Requests Company Facts with that company's own ten-digit CIK.
* Preserves every supplied field and nested value in the raw object.
* Performs no revenue extraction, concept mapping, period normalization, scoring, or inference.

## Validate failures

Run focused tests for each terminal failure category described in the [data model](data-model.md):

```powershell
uv run pytest -k "malformed or resolution or transport or status or mismatch or unknown"
```

Expected outcome: every scenario raises its documented typed failure and no scenario returns an
empty, invented, or partial successful result. In particular, empty input raises
`MalformedTickerError` without network access, and a well-formed unmapped ticker raises
`CompanyResolutionError` after the mapping fetch.

## Confirm the normalization scope boundary

Confirm that financial normalization remains Adobe-only in this slice: requesting a non-ADBE ticker
through `normalize_annual_revenue` or another normalizer still raises the normalization-layer
`UnsupportedTickerError`. This proves identity resolution generalized without generalizing metric
normalization, which is deferred to Slice 3B.

## Run the optional live smoke check

Configure a real administrative contact before making SEC requests. Do not commit personal contact
details or use a generic browser User-Agent.

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run owner-lens ADBE
uv run owner-lens V
uv run owner-lens COST
```

Expected outcome under normal SEC availability: each command reports the company's ticker, SEC
conformed name, and ten-digit CIK, and lists the top-level Company Facts keys and available facts
namespaces. Conceptually, ADBE resolves to Adobe Inc. (CIK 0000796343), V resolves to Visa Inc.,
and COST resolves to Costco Wholesale Corporation, each with a valid raw Company Facts payload whose
namespaces can be inspected. The validation path must not print or transform financial metrics.

The live check is manual because SEC availability and filing data change independently of OwnerLens.
Keep it outside the default automated suite and do not run it repeatedly or concurrently.

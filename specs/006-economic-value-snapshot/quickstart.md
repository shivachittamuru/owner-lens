---
title: Annual Economic Value Snapshot Quickstart
description: Validation guide for the ADBE deterministic owner-economics interpretation layer
ms.date: 2026-09-01
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for snapshot construction, classification, or their tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New tests construct in-memory `OwnerEconomicsRow` and `CapitalEfficiencyRow`
fixtures directly and make no network calls, and all existing Slice 1A through 1E tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* Each completed fiscal year in the window yields exactly one `EconomicValueSnapshot`.
* LEVEL signals (operating margin, FCF margin, ROIC, net cash or net debt) and CHANGE signals (revenue growth, margin changes, FCF growth, FCF-per-share growth, share growth, ROIC change) are separately populated, and no field blends a level with a change.
* Clearly improving, clearly deteriorating, and stable fixtures produce `IMPROVING`, `DETERIORATING`, and `STABLE` respectively.
* A year with rising aggregate FCF but falling FCF per share from dilution classifies by the per-share direction, with a dilution driver.
* A year with flat aggregate FCF but rising FCF per share from a share-count decline classifies by the per-share improvement, with a share-count-decline driver.
* Strong FCF-per-share growth with material or severe ROIC deterioration, or with a net-cash-to-net-debt sign flip, does not classify as `IMPROVING`, and an offset driver is emitted.
* The earliest displayed year and any year missing FCF-per-share growth classify as `INSUFFICIENT_DATA` with the insufficiency driver, and no missing change is replaced by zero.
* Boundary fixtures just inside and just outside each named threshold land on the expected side.
* Identical inputs produce identical classifications and identical ordered drivers across runs.
* Existing Slice 1A through 1E tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the level-versus-change separation

Using constructed rows, confirm:

* Each snapshot exposes the LEVEL fields and CHANGE fields as distinct named values.
* `operating_margin_change`, `fcf_margin_change`, and `roic_change` equal the adjacent-year differences of the corresponding Feature 1 level values, expressed in percentage points.
* `fcf_growth`, `fcf_per_share_growth`, and `diluted_share_growth` match the Feature 1 row values directly.

## Validate the deterministic classification and drivers

Confirm against known inputs and the [data model](data-model.md):

* The insufficiency gate returns `INSUFFICIENT_DATA` whenever `fcf_per_share_growth` is absent.
* The primary per-share verdict follows the `material_growth` threshold on `fcf_per_share_growth`.
* An improving base is downgraded to `STABLE` or `DETERIORATING` under the ROIC and leverage guardrails, and a deteriorating base is tempered to `STABLE` only under the documented strong-quality offset.
* A stable base resolves to `IMPROVING` or `DETERIORATING` only when at least two corroborating secondary signals agree, and to `STABLE` otherwise.
* Drivers are emitted in the fixed priority order defined in the [data model](data-model.md).

## Validate missing-data and boundary edges

Run focused tests for the insufficiency, guardrail, and boundary cases:

```powershell
uv run pytest -k "improving or deteriorating or stable or insufficient or dilution or buyback or guardrail or roic or margin or leverage or boundary or driver or per_share"
```

Expected outcome: every missing-input and earliest-year case yields `INSUFFICIENT_DATA` with explicit
unavailable change signals, every guardrail case avoids an unwarranted `IMPROVING`, and every boundary
case falls on the documented side of its named threshold.

## Run the optional live end-to-end check

Snapshot construction and classification are offline. To validate against current Adobe data, build the
economic-value view in one Python session; retrieval and normalization happen inside the Feature 1
entry points, not in the interpretation layer:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import economic_value_from_facts, SecClient; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; rows=economic_value_from_facts(raw); [print(r.fiscal_year, round(r.revenue_growth,4) if r.revenue_growth is not None else None, round(r.fcf_per_share_growth,4) if r.fcf_per_share_growth is not None else None, round(r.roic,4) if r.roic is not None else None, r.classification.name, [d.name for d in r.drivers]) for r in rows]"
```

Expected outcome under normal SEC availability: approximately the latest five fiscal years print newest
first with revenue growth, FCF-per-share growth, ROIC, the classification, and the structured drivers.
The earliest displayed year prints `INSUFFICIENT_DATA` because its change signals require a prior year.
This live check stays outside the default suite because SEC data changes independently of OwnerLens.

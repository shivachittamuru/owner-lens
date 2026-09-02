---
title: Company-Level Economic Value Summary Quickstart
description: Validation guide for the ADBE deterministic company-level economic-value synthesis
ms.date: 2026-09-02
ms.topic: tutorial
---

## Prerequisites

* Python 3.12 or later
* The `uv` package manager
* No network access is required for synthesis or its tests
* For the optional live end-to-end check, a declared SEC User-Agent such as `OwnerLens admin@example.com`

Review the [public API contract](contracts/public-api.md) and [data model](data-model.md) before validating behavior.

## Install the project environment

From the repository root:

```powershell
uv sync
```

## Run deterministic validation

Run the full test suite. New synthesis tests construct in-memory component objects directly and make no
network calls, and all existing Slice 1A through 1E, 2A, 2B, and 2C tests must still pass:

```powershell
uv run pytest
```

Expected outcome:

* One company-level summary is produced carrying the component classifications, the overall classification, the ordered drivers, and the compact evidence set.
* The overall classification follows the documented hierarchy: a long-term base, a bounded latest-year adjustment, a capital-allocation modifier, and severe guardrails, never an average or score.
* `STRONGLY_IMPROVING` is produced only when long-term compounding is strong; a single strong year never manufactures it.
* Strong long-term compounding with a weak latest year surfaces a recent-slowdown driver and is not classified deteriorating; weak long-term with a strong latest year surfaces early-improvement-not-yet-proven.
* A high SBC burden with a shrinking share count, and capital returns above free cash flow while net-cash positive, appear as watch drivers and do not downgrade the verdict; deepening net debt and sustained ROIC collapse do downgrade it.
* Drivers are ordered, deduplicated, and traceable, and identical inputs produce identical output.
* An insufficient long-term and latest annual pair yields insufficient-data, and a missing recent view is omitted gracefully.
* Existing Slice 1A through 1E, 2A, 2B, and 2C tests pass unchanged.

Run static checks:

```powershell
uv run ruff check .
uv run mypy src
```

Expected outcome: all checks complete without errors.

## Validate the hierarchy and tension handling

Using constructed component objects, confirm against the [data model](data-model.md):

* The long-term compounding classification sets the base and the positive ceiling.
* The latest-year adjustment dampens or confirms by at most one notch and never flips a strong base.
* Owner-unfriendly capital allocation lowers the score; owner-friendly confirms without lifting above the base.
* Sustained ROIC collapse and deepening net debt force the score down; watch signals do not.
* Recent-versus-long-term disagreement emits the correct tension driver.

## Validate driver synthesis

Confirm the positive, watch, and negative drivers are ordered by the fixed priority, deduplicated across
component layers, and each traceable to a component classification or driver, per the [data model](data-model.md).

## Run the optional live end-to-end check

Synthesis is offline. To validate against current Adobe data, build the summary in one Python session;
retrieval and computation happen inside the Feature 1 and Feature 2 entry points, not in the synthesis
layer:

```powershell
$env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
uv run python -c "from owner_lens import SecClient, economic_value_summary_from_facts, format_economic_value_summary; raw=SecClient('OwnerLens admin@example.com').retrieve_company_facts('ADBE').raw_facts; print(format_economic_value_summary(economic_value_summary_from_facts(raw)))"
```

Expected outcome under normal SEC availability: one compact Adobe Economic Value Lens prints with the
latest annual, recent compounding, long-term compounding, and capital-allocation classifications, the
overall classification, the core evidence (FCF/share CAGR, share-count CAGR, ROIC, net cash or net debt),
and the ordered positive, watch, and negative drivers, answering whether the per-share engine is
improving, whether it is durable, whether capital allocation helps owners, whether the balance sheet
supports the strategy, and what the key warnings are. This live check stays outside the default suite
because SEC data changes independently of OwnerLens.

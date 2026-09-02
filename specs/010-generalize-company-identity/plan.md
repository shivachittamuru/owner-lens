---
title: "Implementation Plan: Generalize Company Identity and SEC Ticker Resolution"
description: Technical plan for resolving any SEC-mapped ticker to a canonical identity and retrieving its raw Company Facts
ms.date: 2026-09-02
ms.topic: reference
---

**Branch**: `010-generalize-company-identity` | **Date**: 2026-09-02 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/010-generalize-company-identity/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Generalize the existing SEC access layer so `SecClient` resolves any ticker present in the SEC
`company_tickers.json` mapping, not only ADBE. Remove the single-ticker allow-list gate and the
`SUPPORTED_TICKER` constant from `sec.py`, add a distinct malformed-ticker-input failure, and keep
the already-generic mapping match, ten-digit CIK formatting, Company Facts retrieval, and
CIK-match validation unchanged. Financial normalization stays Adobe-only in this slice: the
separate `_annual.ensure_supported_ticker` ADBE gate that guards `revenue`, `operating_income`,
`reported`, and `balance_sheet` is intentionally left in place and is generalized later in Slice 3B.
The console entry point already prints canonical identity plus raw Company Facts structure, so it
works for any resolved ticker once the gate is removed. No caching, persistence, async, retries,
provider registry, or other speculative abstraction is added.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: `httpx` 0.28 or later for synchronous HTTP; Python standard-library
dataclasses and typing for contracts. No new dependency is introduced.

**Storage**: N/A; each invocation retrieves current SEC data and retains nothing locally

**Testing**: `pytest` with `httpx.MockTransport` for deterministic multi-company HTTP behavior;
optional live SEC smoke check for ADBE, V, and COST excluded from the default suite

**Target Platform**: Local Python environments with outbound HTTPS access

**Project Type**: Small Python library with the existing minimal console entry point available for
manual validation

**Performance Goals**: Complete one mapping-and-facts retrieval for any supported ticker within
10 seconds under normal SEC and network conditions

**Constraints**: Synchronous execution; exactly two sequential SEC requests on the success path
(mapping then Company Facts); declared User-Agent on every request; no more than the SEC limit of
10 requests per second; no retries, caching, persistence, financial normalization, partial
success, or fabricated values

**Scale/Scope**: Any ticker in `company_tickers.json`; live-validated for ADBE, V, and COST. One
edited SEC client module, no new module, reused identity and result value objects, and expanded
focused unit tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness (I)**: PASS. The slice returns source data unchanged and performs no
  financial calculation; widening company coverage does not touch metric logic.
* **Traceability (II)**: PASS. The complete Company Facts payload retains SEC concepts, units,
  periods, forms, filing dates, frames, and accession identifiers for every resolved company.
* **Deterministic computation (III)**: PASS. Ticker canonicalization, mapping selection, CIK
  formatting, and validation are deterministic and contain no AI behavior.
* **Definitions and tests (IV)**: PASS. No financial metric is introduced. Controlled tests cover
  Adobe plus additional companies, canonicalization, unmapped and malformed input, source
  failures, and identity mismatch.
* **Fail loudly (V)**: PASS. Distinct typed failures replace the removed allow-list rejection; no
  fallback, inference, fabricated value, or partial success is introduced.
* **Current-release scope (VI)**: PASS. Only the constraints needed for arbitrary resolution are
  removed. No provider interface, repository, factory, registry, cache, database, async model, or
  retry framework is added. Normalization remains Adobe-only until a concrete Slice 3B requirement.

### Post-Design Evaluation

* **Provider boundary**: PASS. SEC mapping and retrieval stay together in one SEC-specific module,
  outside financial metric logic, which remains Adobe-scoped in `_annual`.
* **Minimal contract**: PASS. The public contract still exposes only identity resolution and raw
  Company Facts retrieval; the only surface change is replacing the obsolete allow-list error with a
  malformed-ticker-input error.
* **Local-first delivery**: PASS. The feature runs and tests locally without hosted infrastructure.
* **Reproducibility**: PASS. Unit tests use fixed multi-company SEC payloads and assert source URL,
  CIK formatting, headers, validation, and payload equality; live access stays an optional check.
* **Failure integrity**: PASS. The contract defines explicit malformed-input, resolution,
  transport, HTTP-status, malformed-data, and identity-mismatch failures.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
└── owner_lens/
    ├── __init__.py      # Reconcile SEC error exports; console entry point unchanged in behavior
    └── sec.py           # Generalize resolve_company; drop allow-list; add malformed-ticker error

tests/
└── test_sec.py          # Multi-company success plus expanded failure and canonicalization scenarios
```

**Structure Decision**: Retain the existing single-package layout and edit the existing `sec.py`
module in place; no new module is warranted because the mapping match, CIK formatting, retrieval,
and validation already generalize. The `CompanyIdentity` and `CompanyFactsResult` value objects are
reused unchanged. `__init__.py` swaps the obsolete `UnsupportedTickerError` export for a new
`MalformedTickerError`. Normalization modules (`revenue`, `operating_income`, `reported`,
`balance_sheet`) and their `_annual` ADBE gate are deliberately untouched.

## Complexity Tracking

No violations or complexity exceptions.

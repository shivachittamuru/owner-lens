---
title: "Implementation Plan: SEC Company Facts Retrieval"
description: Technical plan for resolving Adobe's SEC identity and retrieving raw Company Facts
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/001-sec-company-facts/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Implement one synchronous SEC module that accepts ADBE, downloads the SEC's
`company_tickers.json` mapping, resolves Adobe's identity and CIK, formats the CIK to ten digits,
and retrieves the corresponding Company Facts JSON. Use the project's existing synchronous
`httpx` dependency, require a declared application-and-contact User-Agent, preserve the parsed raw
payload without financial transformations, and expose explicit typed failures. Avoid provider
interfaces, persistence, caching, retries, metric models, and speculative abstractions.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: `httpx` 0.28 or later for synchronous HTTP; Python standard-library
dataclasses and typing for contracts

**Storage**: N/A; each invocation retrieves current SEC data and retains nothing locally

**Testing**: `pytest` with `httpx.MockTransport` for deterministic HTTP behavior; optional live SEC
smoke check excluded from the default test suite

**Target Platform**: Local Python environments with outbound HTTPS access

**Project Type**: Small Python library with the existing minimal console entry point available for
manual validation

**Performance Goals**: Complete one ADBE mapping-and-facts retrieval within 10 seconds under normal
SEC and network conditions

**Constraints**: Synchronous execution; exactly two sequential SEC requests on the success path;
declared User-Agent on both; no more than the SEC limit of 10 requests per second; no retries,
caching, persistence, financial normalization, partial success, or fabricated values

**Scale/Scope**: ADBE only; one public SEC client module, one identity value object, one retrieval
result, and focused unit tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. The design returns source data unchanged and performs no
  financial calculations.
* **Traceability**: PASS. The complete Company Facts payload retains SEC concepts, units, periods,
  forms, filing dates, frames, and accession identifiers supplied by the source.
* **Deterministic computation**: PASS. Ticker normalization, mapping selection, CIK formatting, and
  validation are deterministic and contain no AI behavior.
* **Definitions and tests**: PASS. No financial metric is introduced. Controlled tests cover valid,
  missing, malformed, conflicting, and external-failure cases.
* **Fail loudly**: PASS. Typed failures replace fallback, inference, fabricated values, and partial
  success.
* **Current-release scope**: PASS. One SEC-specific module serves the active ADBE slice. No generic
  provider interface, database, cache, hosted service, or future-facing abstraction is introduced.

### Post-Design Evaluation

* **Provider boundary**: PASS. SEC mapping and retrieval stay together in one SEC-specific module,
  outside future financial metric logic.
* **Minimal contract**: PASS. The public contract exposes only identity resolution and raw Company
  Facts retrieval required by this slice.
* **Local-first delivery**: PASS. The feature runs and tests locally without hosted infrastructure.
* **Reproducibility**: PASS. Unit tests use fixed representative SEC payloads and assert source URL,
  CIK formatting, headers, validation, and payload equality.
* **Failure integrity**: PASS. The contract defines explicit unsupported-ticker, resolution,
  transport, HTTP-status, malformed-data, and identity-mismatch failures.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/001-sec-company-facts/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── public-api.md    # Phase 1 library contract
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
└── owner_lens/
    ├── __init__.py      # Existing package entry point and intentional public exports
    └── sec.py           # SEC client, values, validation, and typed failures

tests/
└── test_sec.py          # Controlled success and failure scenarios
```

**Structure Decision**: Retain the existing single-package layout and add one cohesive SEC module
plus one focused test module. Values and exceptions remain in `sec.py` because separating models,
transport, mapping, and validation would create abstractions with only one current consumer.

## Complexity Tracking

No violations or complexity exceptions.

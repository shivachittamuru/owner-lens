---
title: "Implementation Plan: Adobe Annual Revenue Normalization"
description: Technical plan for deriving a canonical annual revenue series from raw SEC Company Facts
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/002-annual-revenue-normalization/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Add one deterministic, offline normalization module that consumes the raw Adobe Company Facts
payload from Slice 1 and produces a canonical annual revenue series. Select a single US-GAAP
revenue concept by documented preference order, keep only full fiscal-year USD observations,
derive each observation's fiscal year from its period end date, collapse identical comparative
repeats deterministically, and expose full provenance per observation. Fail explicitly when no
revenue concept is usable or when a fiscal year has genuinely conflicting values. Introduce no
network access, persistence, other metrics, or generic normalization.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, datetime, typing). No new
runtime dependency; the existing `httpx` retrieval from Slice 1 supplies the input payload upstream.

**Storage**: N/A; normalization is a pure in-memory transformation over a supplied payload.

**Testing**: `pytest` with controlled in-memory Company Facts fixtures. No network access in tests.

**Target Platform**: Local Python environments; no external calls during normalization.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the full series for a valid payload in under 2 seconds with no
external calls.

**Constraints**: Deterministic and offline; single revenue concept per series; USD only; fiscal year
derived from period end date, not the raw XBRL `fy`; no invention, estimation, interpolation, or
aggregation; explicit failure on missing concept or unresolved conflict; no partial success.

**Scale/Scope**: ADBE and revenue only; approximately the latest five completed fiscal years; one
normalization module, its value types and failures, and focused unit tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. One revenue metric with an explicit, documented definition and
  selection rules; correctness prioritized over breadth.
* **Traceability**: PASS. Each observation preserves SEC concept, unit, period dates, fiscal year,
  fiscal period, form, filing date, accession number, and value linking back to a source fact.
* **Deterministic computation**: PASS. Concept selection, full-year filtering, fiscal-year
  derivation, and tie-breaking are deterministic and contain no AI behavior.
* **Definitions and tests**: PASS. Revenue definition, period semantics, and tie-breaking are
  documented and covered by tests for duplicates, quarterly versus annual, comparatives, and
  missing or ambiguous data. An educational notebook is deferred to when the concept stabilizes and
  is recorded as a follow-up, not introduced speculatively.
* **Fail loudly**: PASS. Typed failures replace any silent selection, fallback, or invented value.
* **Current-release scope**: PASS. ADBE revenue only; no other metric, provider, persistence, or
  infrastructure is added.

### Post-Design Evaluation

* **Provider boundary**: PASS. Normalization consumes an already-retrieved payload and stays
  separate from SEC transport in `sec.py`.
* **Minimal contract**: PASS. The public contract exposes only annual revenue normalization for the
  supplied payload.
* **Local-first delivery**: PASS. Runs and tests entirely locally without network access.
* **Reproducibility**: PASS. Unit tests use fixed in-memory fixtures modeled on the real Adobe fact
  shape and assert exact selected values and provenance.
* **Failure integrity**: PASS. Missing-concept and unresolved-conflict paths raise explicit typed
  errors and return nothing partial.

> Notebook follow-up: an educational revenue notebook is intentionally deferred, not skipped. It is
> recorded here as the required artifact for when this concept is demonstrated to users. No
> constitutional violation requires justification.

## Project Structure

### Documentation (this feature)

```text
specs/002-annual-revenue-normalization/
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
    ├── __init__.py      # Existing package exports; adds revenue exports
    ├── sec.py           # Existing SEC retrieval (Slice 1); unchanged
    └── revenue.py       # Annual revenue selection, values, and typed failures

tests/
├── test_sec.py          # Existing Slice 1 tests
└── test_revenue.py      # Controlled duplicate, quarterly, comparative, and failure cases
```

**Structure Decision**: Add one cohesive `revenue.py` module beside `sec.py`. Value types, the
selection rules, and failures live together because they have a single current consumer. No
provider interface, strategy abstraction, or shared normalization framework is introduced; that
would anticipate metrics still out of scope.

## Complexity Tracking

No violations or complexity exceptions.

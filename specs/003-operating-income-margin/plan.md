---
title: "Implementation Plan: Adobe Operating Income and Margin"
description: Technical plan for normalizing Adobe operating income and deriving operating margin
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/003-operating-income-margin/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Add a second normalized income-statement metric and one derived ratio. Extract the annual selection
behavior that Slice 1B and this slice concretely share into one small internal primitive, then build
operating-income normalization and revenue normalization on top of it. Compute operating margin in
deterministic application code from the two aligned canonical series, keep reported facts distinct
from the derived margin, and handle missing or zero revenue explicitly. Introduce no generalized
financial-statement framework and no network access during normalization.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, datetime, typing). No new
runtime dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1.

**Storage**: N/A; normalization and margin derivation are pure in-memory transformations.

**Testing**: `pytest` with controlled in-memory Company Facts fixtures. All existing Slice 1A and 1B
tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during normalization or derivation.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the aligned two-metric result for a valid payload in under 2 seconds
with no external calls.

**Constraints**: Deterministic and offline; single concept per canonical series; USD only; fiscal
year derived from period end date, not the raw XBRL `fy`; 52-to-53 week full-year tolerance; explicit
typed failures on missing concept and unresolved conflict; margin computed in code, never sourced;
missing or zero revenue suppresses margin explicitly; reported facts and derived margin stay distinct;
shared code extracted only for demonstrated duplication.

**Scale/Scope**: ADBE only; operating income plus operating margin; approximately the latest five
completed fiscal years; one shared primitive module, one new operating-income module, one derived
margin module, a refactor of the revenue module, and focused unit tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. Operating income has an explicit documented concept and selection
  rule; margin has an explicit formula. Correctness is prioritized over breadth.
* **Traceability**: PASS. Each operating-income observation preserves full SEC provenance, and each
  margin references the fiscal year and its two reported inputs.
* **Deterministic computation**: PASS. Selection, fiscal-year derivation, dedup, alignment, and the
  margin division are deterministic with no AI behavior.
* **Definitions and tests**: PASS. Operating-income definition, period semantics, margin formula, and
  zero and missing revenue behavior are documented and covered by tests. The educational revenue
  notebook exists; a margin extension to it is a recorded follow-up, not speculative work now.
* **Fail loudly**: PASS. Missing-concept and conflicting-value paths raise typed errors; margin is
  omitted explicitly when inputs are missing or revenue is zero, never invented or infinite.
* **Current-release scope**: PASS. Only operating income and margin for ADBE are added.

### Post-Design Evaluation

* **Provider boundary**: PASS. Normalization and derivation consume an already-retrieved payload and
  stay separate from SEC transport in `sec.py`.
* **Minimal contract**: PASS. The public surface adds operating-income normalization, margin
  derivation, and metric alignment for the supplied payload, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally without network access.
* **Reproducibility**: PASS. Unit tests use fixed fixtures modeled on the real Adobe fact shape and
  assert exact selected values, alignment, provenance, and margins.
* **Failure integrity**: PASS. All new failure paths surface explicitly with no partial or fabricated
  values, and existing Slice 1A/1B behavior and tests are preserved.

### Shared-code extraction justification

Live inspection shows `OperatingIncomeLoss` has the same fact shape and the same `fy`
comparative-repeat behavior as `Revenues`. The following logic is byte-for-byte identical between the
two metrics and is therefore extracted into one small internal primitive: full fiscal-year filtering
(USD, `fp == FY`, 350-380 day duration), fiscal-year derivation from the period end date,
comparative deduplication with earliest-filed provenance, canonical observation provenance, and the
preference-ordered concept selection loop. Only the concept preference list and the metric-specific
typed error classes differ, so those remain per metric and are injected into the shared engine. No
generalized financial-statement framework is introduced; the primitive is limited to what two
concrete metrics already duplicate.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/003-operating-income-margin/
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
    ├── __init__.py          # Package exports; adds operating-income and margin exports
    ├── sec.py               # Slice 1 retrieval; unchanged
    ├── _annual.py           # New internal primitive: shared annual selection engine
    ├── revenue.py           # Refactored to build on _annual; public API preserved
    ├── operating_income.py  # New: annual operating-income normalization
    └── margin.py            # New: derived operating margin and metric alignment

tests/
├── test_sec.py              # Existing Slice 1A tests; unchanged
├── test_revenue.py          # Existing Slice 1B tests; unchanged and still passing
├── test_operating_income.py # New: concept, full-year, comparatives, ambiguity, missing
└── test_margin.py           # New: alignment, margin math, missing and zero revenue
```

**Structure Decision**: Introduce one internal `_annual.py` primitive that owns the duplicated
annual selection behavior, and keep concept preference lists and typed errors in the metric modules.
Refactor `revenue.py` to consume the primitive while preserving its public names and tests. Add
`operating_income.py` for the new reported metric and `margin.py` for the derived ratio, keeping the
reported-fact and derived-metric types distinct. A shared reported-observation type lives in
`_annual.py`; the derived `OperatingMargin` type is deliberately separate to preserve the
fact-versus-metric boundary.

## Complexity Tracking

No violations or complexity exceptions. The one new abstraction (`_annual.py`) is justified by
demonstrated duplication between two concrete metrics, not by speculative future need.

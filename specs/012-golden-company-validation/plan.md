---
title: "Implementation Plan: Full Golden-Company Validation"
description: Technical plan for validating and hardening the OwnerLens pipeline across ADBE, V, and COST with honest partial coverage
ms.date: 2026-09-03
ms.topic: reference
---

**Branch**: `012-golden-company-validation` | **Date**: 2026-09-03 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/012-golden-company-validation/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Validate the full existing pipeline (Feature 1 + Feature 2A/2B/2C/2D) across three deliberately
different companies and harden it for honest partial coverage. A live pipeline audit shows the
entire break for Visa is a single choke point: `owner_economics_from_facts` calls
`normalize_diluted_shares` unconditionally, which raises `ConceptNotFoundError` because Visa tags no
weighted-average diluted-share concept, and every Feature 2 aggregator funnels through owner
economics. ADBE and COST already run all six layers to completion (both classify `IMPROVING`),
confirming the thresholds are not Adobe-only.

The fix is narrow: `owner_economics_from_facts` tolerates an unsupported diluted-share series
(catch `ConceptNotFoundError`, substitute an empty `AnnualSeries` — unavailable, never fabricated,
and never point-in-time shares). `compute_owner_economics` already yields `None` per-share fields
when shares are missing, so Visa flows through owner economics, 2A, 2B, 2C, and 2D with per-share
analyses reported insufficient while revenue, free cash flow, capital efficiency, and
capital-allocation evidence remain available. Downstream layers gain only the minimum insufficient-
data handling that live re-validation actually exposes. A small read-only `coverage.py` helper
produces the deterministic cross-company coverage report and company-level output. Every Feature 2
threshold is audited for business-model independence in research.md. Adobe output is unchanged
(the tolerance path never triggers for Adobe). No workflow engine, persistence, scoring, or new
analytical feature is introduced.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard-library dataclasses, enum, and typing; existing `httpx`
only for the optional live validation. No new dependency is introduced.

**Storage**: N/A; the pipeline consumes resolved raw facts and retains nothing

**Testing**: `pytest` with controlled ADBE/V/COST fixtures (reusing the Slice 3B `tests/_fixtures.py`)
for full-coverage, partial-coverage, absent-metric, and business-model-diversity scenarios; optional
live honest-coverage check excluded from the default suite

**Target Platform**: Local Python environments with outbound HTTPS access for optional live checks

**Project Type**: Small Python library with the existing console entry point available for manual
validation

**Performance Goals**: Deterministic offline analysis; no additional network calls beyond the
existing single Company Facts retrieval per company

**Constraints**: Validation and hardening only; no bypassing a layer; no fabricated or substituted
values (specifically no point-in-time shares for weighted-average diluted shares); Adobe output
unchanged; narrow optional handling and small coverage helpers rather than a generic framework

**Scale/Scope**: Three golden companies; one narrow tolerance change plus minimum exposed
insufficient-data handling; one new read-only `coverage.py`; a documented threshold audit; new and
extended tests; one educational notebook

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness (I)**: PASS. The slice validates the pipeline against genuinely different
  businesses and hardens it to degrade honestly; no definition is weakened to force a result.
* **Traceability (II)**: PASS. Available values keep their provenance; the coverage report names the
  exact input that blocks each unavailable layer.
* **Deterministic computation (III)**: PASS. The tolerance path, coverage helper, and report are
  deterministic; no AI behavior is introduced.
* **Definitions and tests (IV)**: PASS. Minimum-data contracts are made explicit; controlled tests
  cover partial coverage, absent metrics, business-model diversity, and regression; a notebook
  demonstrates the semantics.
* **Fail loudly (V)**: PASS. Unsupported and insufficient outcomes are explicit; the diluted-share
  tolerance substitutes an empty (unavailable) series, never a fabricated or point-in-time value.
* **Current-release scope (VI)**: PASS. Only the assumptions actually exposed by ADBE/V/COST are
  fixed. A small read-only coverage helper is added; no workflow engine, persistence, scoring, or
  new analytical feature.

### Post-Design Evaluation

* **Provider boundary**: PASS. Coverage logic reads existing outputs; it adds no provider knowledge
  and no orchestration abstraction.
* **Minimal contract**: PASS. The tolerance change is one `except` at the owner-economics boundary;
  the coverage helper exposes only per-company/per-layer states and reasons.
* **Local-first delivery**: PASS. Everything runs and tests locally; live checks stay optional.
* **Reproducibility**: PASS. Tests reuse fixed ADBE/V/COST fixtures; the coverage report is
  deterministic.
* **Failure integrity**: PASS. Partial coverage yields explicit insufficient-data states with
  reasons; Adobe results are unchanged.

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
    ├── owner_economics.py   # NARROW: tolerate unsupported diluted shares (empty series, not fabricated)
    ├── economic_value.py    # Only if live re-validation exposes a crash on None per-share
    ├── compounding.py       # Only if live re-validation exposes a crash on None per-share
    ├── economic_summary.py  # Only if synthesis needs explicit insufficient-per-share handling
    └── coverage.py          # NEW: read-only per-company input + per-layer coverage and report

tests/
├── _fixtures.py             # Reused ADBE/V/COST fixtures (Slice 3B); extend if a scenario needs it
├── test_coverage.py         # NEW: coverage states, deterministic report, company-level output
├── test_owner_economics.py  # Extend: Visa partial (per-share None, other metrics present)
├── test_economic_value.py   # Extend: partial propagation + business-model-diversity classification
├── test_compounding.py      # Extend: unavailable per-share compounding is insufficient
└── test_economic_summary.py # Extend: partial-coverage summary is honest insufficient-data

notebooks/
└── 08_golden_company_validation.ipynb  # NEW educational artifact
```

**Structure Decision**: Keep the single-package layout. The behavioral change is one narrow
tolerance at the owner-economics boundary plus only the downstream insufficient-data handling that
live re-validation actually exposes. Add one cohesive read-only `coverage.py` for the coverage
representation, cross-company report, and company-level output. The threshold audit is documented in
research.md; no threshold values change unless a genuine, economically general bug is found.

## Complexity Tracking

No violations or complexity exceptions. The coverage helper is a small read-only reporter, not an
orchestration framework, and the pipeline change is a single narrow tolerance justified by the live
audit in research.md.

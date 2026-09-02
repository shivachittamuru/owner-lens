---
title: "Implementation Plan: Company-Level Economic Value Summary"
description: Technical plan for a deterministic synthesis layer over the Feature 2A, 2B, and 2C outputs
ms.date: 2026-09-02
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-02 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/009-economic-value-summary/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Build the Feature 2 capstone: one deterministic company-level `EconomicValueSummary` synthesized from
the existing Feature 2A annual snapshots, the Feature 2B recent and long-term compounding views, and the
Feature 2C capital-allocation rows. The overall classification (`STRONGLY_IMPROVING`, `IMPROVING`,
`STABLE`, `DETERIORATING`, `STRONGLY_DETERIORATING`, `INSUFFICIENT_DATA`) is produced by a documented
priority hierarchy on a small ordinal scale: an insufficiency gate, a long-term compounding base that
anchors the ceiling, a latest-year confirm-or-dampen adjustment that reconciles recent-versus-long-term
tension, a capital-allocation modifier, and severe quality and balance-sheet guardrails, never a
mapping, average, weighted score, or 0-to-100 score. Economically relevant warnings are surfaced as
watch drivers that do not change the verdict unless they cross a documented severity threshold, at which
point they become guardrails. The summary carries ordered, deduplicated, traceable positive, watch, and
negative drivers and a compact evidence set drawn from existing outputs. The synthesis layer makes no
SEC calls, performs no normalization, duplicates no Feature 1 calculation, and reimplements no Feature 2
logic; it composes existing objects. All Feature 1, 2A, 2B, and 2C behavior and tests are preserved.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, enum, typing). No new runtime
dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1, invoked only by the
Feature 1 and 2A/2B/2C entry points, never by the synthesis layer.

**Storage**: N/A; the summary is a pure in-memory synthesis of already-computed component objects.

**Testing**: `pytest` with controlled in-memory component objects (annual snapshots, compounding views,
and capital-allocation rows) constructed directly. All existing Slice 1A through 1E, 2A, 2B, and 2C
tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during synthesis.

**Performance Goals**: Produce the Adobe summary in under 2 seconds, with the only network access being
the existing Feature 1 retrieval outside the synthesis layer.

**Constraints**: Deterministic and offline; the layer consumes existing Feature 2A, 2B, and 2C objects
and adds no SEC facts, makes no SEC calls, performs no normalization, duplicates no Feature 1
calculation, and reimplements no Feature 2 component logic; the overall classification is a documented
priority hierarchy on a small ordinal scale, never a mapping, numeric or weighted average, hidden
points, black-box or configurable score, or model-generated prose; long-term compounding anchors the
positive ceiling so durable multi-year economics outweigh a single strong or weak year; watch signals
are distinguished from verdict-changing guardrails and the summary does not overreact to every warning;
recent-versus-long-term disagreement is reconciled with explicit tension drivers; drivers are ordered,
deduplicated, and traceable to component outputs; the evidence set is a compact selection, not a
re-derivation; insufficient or short-history inputs resolve conservatively and gracefully; composition
is preferred over inheritance or framework-style abstractions.

**Scale/Scope**: ADBE only; one new `economic_summary.py` synthesis module (summary type, overall
classification enum, driver enum, a small thresholds type, the synthesis function, an orchestration
entry point, and a compact formatter); one new test module; one educational notebook; no changes to
Feature 1 or Feature 2 modules beyond adding package exports.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. The layer performs no normalization or metric calculation; it composes
  verified Feature 2 classifications, drivers, and a small evidence set into a coarse verdict.
* **Traceability**: PASS. Every summary field references its source component, and every driver is
  traceable to a component classification or driver; the evidence set is drawn from existing outputs.
* **Deterministic computation**: PASS. The ordinal hierarchy, guardrails, and driver synthesis are pure
  deterministic functions with no AI, randomness, or hidden state; identical inputs yield identical
  results and ordered drivers.
* **Definitions and tests**: PASS. Every base, adjustment, modifier, guardrail, threshold, and driver
  mapping is documented and unit-tested. A meaningful new concept (company-level synthesis) adds an
  educational notebook.
* **Fail loudly**: PASS. Insufficient components resolve to insufficient-data or a conservative verdict;
  the recent compounding view is omitted gracefully when history is too short.
* **Current-release scope**: PASS. Only the company-level synthesis for ADBE is added; no valuation,
  scoring, screening, cross-company, portfolio, agent, or infrastructure work.

### Post-Design Evaluation

* **Provider boundary**: PASS. The synthesis layer sits above Feature 2 and never touches SEC transport;
  `economic_value_summary_from_facts` delegates all retrieval and computation to the existing entry points.
* **Minimal contract**: PASS. The public surface adds one summary type, one classification enum, one
  driver enum, one thresholds type with a default, the synthesis function, the orchestration entry point,
  and the formatter, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally; synthesis tests need no network and no
  SEC fixtures.
* **Reproducibility**: PASS. Unit tests construct component objects directly and assert exact overall
  classifications and ordered drivers for the durable-first, tension, watch, and guardrail cases.
* **Failure integrity**: PASS. All insufficient and short-history paths resolve explicitly, and all
  existing Slice 1A through 1E, 2A, 2B, and 2C behavior and tests are preserved.

### Composition justification

The capstone is a new concern distinct from every component layer: it reads their classifications,
drivers, and a small evidence set and produces a coarse company-level verdict. It introduces no new
provider capability, no new external data, and no reimplementation of component logic. It composes
existing objects rather than subclassing or wrapping them in a framework, keeping the boundary between
economic-value analysis and any future business-quality or valuation layer explicit. No constitutional
violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/009-economic-value-summary/
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
    ├── __init__.py            # Package exports; adds economic-summary exports
    ├── sec.py                 # Slice 1A retrieval; unchanged
    ├── economic_value.py      # Slice 2A; consumed, unchanged
    ├── compounding.py         # Slice 2B; consumed, unchanged
    ├── capital_allocation.py  # Slice 2C; consumed, unchanged
    └── economic_summary.py    # New: company-level synthesis, classification, drivers, orchestration

tests/
├── test_economic_value.py     # Existing; unchanged
├── test_compounding.py        # Existing; unchanged
├── test_capital_allocation.py # Existing; unchanged
└── test_economic_summary.py   # New: hierarchy, tension, watch vs guardrail, dedup, formatter

notebooks/
└── 06_adbe_economic_value_summary.ipynb  # New: educational notebook for the capstone synthesis
```

**Structure Decision**: Add a single `economic_summary.py` module that consumes the existing
`EconomicValueSnapshot`, `EconomicCompoundingView`, and `CapitalAllocationRow` objects. It reads the
latest annual snapshot, the recent and long-term compounding views, and the latest capital-allocation
row, maps their classifications and drivers onto an ordinal hierarchy with severe guardrails, synthesizes
ordered deduplicated drivers and a compact evidence set, and renders a compact summary. Feature 1 and
Feature 2 modules are consumed unchanged; only `__init__.py` gains exports. An educational notebook
demonstrates the capstone per the constitution.

## Complexity Tracking

No violations or complexity exceptions. The feature adds one composition module, one classification enum,
one driver enum, one small thresholds type, and one summary type, all tied to the current requirement,
with no rules-engine framework, no configurable weights, and no numeric composite score.

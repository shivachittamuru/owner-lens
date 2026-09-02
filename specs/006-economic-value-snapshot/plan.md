---
title: "Implementation Plan: Annual Economic Value Snapshot"
description: Technical plan for a deterministic per-fiscal-year owner-economics interpretation layer over Feature 1
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/006-economic-value-snapshot/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Add OwnerLens's first interpretation layer on top of the trusted Feature 1 fundamentals and derived
metrics. For each completed Adobe fiscal year, build a compact `EconomicValueSnapshot` that separates
LEVEL signals (operating margin, FCF margin, ROIC, net cash or net debt) from CHANGE signals (revenue
growth, operating-margin change, FCF growth, FCF-margin change, diluted-share growth, FCF per share,
FCF-per-share growth, ROIC change), then classify the year as `IMPROVING`, `STABLE`, `DETERIORATING`,
or `INSUFFICIENT_DATA` using explicit, documented deterministic rules that weight per-share economics
above aggregate growth and include capital-efficiency and leverage guardrails. Every classification
carries ordered, named drivers (reason codes) so the verdict is transparent and testable. The layer
consumes the existing `OwnerEconomicsRow` and `CapitalEfficiencyRow` outputs, computes only the few
adjacent-year change metrics not already present from those aligned level values, performs no SEC
retrieval or re-normalization, uses centralized named thresholds (no configurable weights, no 0-to-100
score), and stays a separate module built from small composable functions. All Feature 1 behavior and
tests are preserved.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, enum, typing). No new runtime
dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1, invoked only by
Feature 1 code, never by the interpretation layer.

**Storage**: N/A; classification is a pure in-memory transformation of already-computed metrics.

**Testing**: `pytest` with controlled in-memory `OwnerEconomicsRow` and `CapitalEfficiencyRow`
fixtures constructed directly (no SEC payloads required for the interpretation tests). All existing
Slice 1A through 1E tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during snapshot construction or
classification.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the compact Adobe economic-value view for a valid payload in under 2
seconds, with the only network access being the existing Feature 1 retrieval outside this layer.

**Constraints**: Deterministic and offline; interpretation consumes Feature 1 outputs and never
re-normalizes SEC facts or calls the SEC API; LEVEL and CHANGE signals kept conceptually distinct;
classification produced by documented explicit rules, not an opaque or numeric composite score and not
a 0-to-100 score; per-share economics weighted above aggregate growth with explicit capital-efficiency
and leverage guardrails so strong FCF-per-share growth never auto-classifies as improving amid
material deterioration; thresholds centralized, named, documented, imprecise-by-design, and not tuned
to Adobe; no configurable scoring weights; missing inputs and the earliest year without a prior use
explicit unavailable semantics (never zero-substituted) and resolve to `INSUFFICIENT_DATA`; small
composable functions rather than a rules-engine framework; economically intuitive rules not overfit to
Adobe so they can apply to another conventional operating company.

**Scale/Scope**: ADBE only; one new `economic_value.py` module (snapshot type, classification enum,
driver/reason-code enum, centralized thresholds, small classification and change-derivation helpers,
and orchestration from facts); approximately the latest five completed fiscal years with the earliest
displayed year correctly `INSUFFICIENT_DATA`; one new test module; one educational notebook; no changes
to Feature 1 normalization or metric-calculation modules beyond adding package exports.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. The layer performs no normalization; it consumes Feature 1's
  verified facts and metrics and derives only documented adjacent-year changes. Classification rules
  are explicit and economically intuitive, not curve-fit to Adobe.
* **Traceability**: PASS. Each snapshot references its fiscal year and carries the concrete signal
  values and ordered named drivers that produced its classification, so a reader can see exactly why a
  year was judged as it was.
* **Deterministic computation**: PASS. Change derivation, thresholding, and classification are pure
  deterministic functions with no AI, randomness, or hidden state; identical inputs yield identical
  classifications and ordered drivers.
* **Definitions and tests**: PASS. Every signal direction, threshold, guardrail, and classification
  branch is documented and unit-tested. A meaningful new concept (economic-value classification) adds
  an educational notebook.
* **Fail loudly**: PASS. Missing inputs and the earliest year use explicit `None`/unavailable
  semantics and produce `INSUFFICIENT_DATA`; zero is never substituted for a missing change.
* **Current-release scope**: PASS. Only the annual snapshot and classification for ADBE are added; no
  multi-year trend, valuation, scoring, screening, portfolio, agent, or infrastructure work.

### Post-Design Evaluation

* **Provider boundary**: PASS. The interpretation layer sits above Feature 1 and never touches SEC
  transport; `economic_value_from_facts` delegates all retrieval and normalization to existing
  Feature 1 entry points.
* **Minimal contract**: PASS. The public surface adds one snapshot type, one classification enum, one
  driver enum, one thresholds type with a default instance, and three functions, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally; interpretation tests need no
  network and no SEC fixtures.
* **Reproducibility**: PASS. Unit tests construct Feature 1 row fixtures directly and assert exact
  classifications and ordered drivers for improving, deteriorating, stable, mixed, per-share-versus-
  aggregate divergence, guardrail, boundary, and insufficient-data cases.
* **Failure integrity**: PASS. All missing-data paths surface `INSUFFICIENT_DATA` explicitly, and all
  existing Slice 1A through 1E behavior and tests are preserved.

### Interpretation-layer separation justification

The classification layer is a new concern distinct from normalization (`sec.py`, `_annual.py`,
`revenue.py`, `operating_income.py`, `reported.py`, `balance_sheet.py`) and metric calculation
(`margin.py`, `owner_economics.py`, `capital_efficiency.py`). It reads the aligned `OwnerEconomicsRow`
and `CapitalEfficiencyRow` outputs, so it introduces no new provider capability and no new external
data. The few change metrics it needs that Feature 1 does not already expose (revenue growth,
operating-margin change, FCF-margin change, ROIC change) are simple adjacent-year deltas of Feature 1
level values, not re-derived from SEC facts. Thresholds are centralized in one named, inspectable
place; there are no configurable weights and no numeric composite score. The rules are small composable
functions, not a rules-engine framework. No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/006-economic-value-snapshot/
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
    ├── __init__.py            # Package exports; adds economic-value exports
    ├── sec.py                 # Slice 1A retrieval; unchanged
    ├── _annual.py             # Shared primitive; unchanged
    ├── revenue.py             # Slice 1B; unchanged
    ├── operating_income.py    # Slice 1C; unchanged
    ├── margin.py              # Slice 1C; unchanged
    ├── reported.py            # Slice 1D; unchanged
    ├── owner_economics.py     # Slice 1D; consumed, unchanged
    ├── balance_sheet.py       # Slice 1E; unchanged
    ├── capital_efficiency.py  # Slice 1E; consumed, unchanged
    └── economic_value.py      # New: snapshot, classification, drivers, thresholds, orchestration

tests/
├── test_sec.py                # Existing; unchanged
├── test_revenue.py            # Existing; unchanged
├── test_operating_income.py   # Existing; unchanged
├── test_margin.py             # Existing; unchanged
├── test_reported.py           # Existing; unchanged
├── test_owner_economics.py    # Existing; unchanged
├── test_balance_sheet.py      # Existing; unchanged
├── test_capital_efficiency.py # Existing; unchanged
└── test_economic_value.py     # New: signals, thresholds, guardrails, drivers, classification, alignment

notebooks/
└── 03_adbe_economic_value.ipynb  # New: educational notebook for the economic-value lens
```

**Structure Decision**: Add a single `economic_value.py` module that consumes the existing
`OwnerEconomicsRow` and `CapitalEfficiencyRow` outputs. It aligns them by fiscal year, derives the four
adjacent-year change metrics not already present, assembles each `EconomicValueSnapshot`, and applies a
deterministic, documented classification built from small composable direction and guardrail helpers
with centralized named thresholds. Feature 1 modules are consumed unchanged; only `__init__.py` gains
exports. An educational notebook demonstrates the concept per the constitution.

## Complexity Tracking

No violations or complexity exceptions. The feature adds one interpretation module, one thresholds
type, one classification enum, one driver enum, and one snapshot type, all justified by the current
requirement, with no rules-engine framework, no configurable weights, and no numeric composite score.

---
title: "Implementation Plan: Multi-Year Economic Compounding View"
description: Technical plan for a deterministic multi-year per-share compounding interpretation layer over Feature 1 and Feature 2A
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/007-economic-compounding-view/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Extend the annual economic-value lens into a multi-year one. For a requested period, build a
deterministic `EconomicCompoundingView` that reports the compounding rates (revenue, aggregate free
cash flow, free cash flow per share, and diluted-share CAGR), the start-to-end quality and
balance-sheet changes (operating margin, FCF margin, ROIC, net cash or net debt), and the counts of
the annual Feature 2A classifications within the period. Compute every CAGR with the standard formula
over the correct number of fiscal-year intervals (one fewer than the observation count), returning an
explicit unavailable result for missing endpoints, zero or negative beginnings, and sign changes.
Classify each period as `STRONGLY_COMPOUNDING`, `COMPOUNDING`, `STABLE`, `DETERIORATING`, or
`INSUFFICIENT_DATA` with explicit, documented rules that treat FCF-per-share CAGR as the primary
per-share compounding measure, surface when a per-share result is share-count-driven, temper material
dilution and ROIC deterioration, and attach ordered named drivers. Select the recent three-year and
longest five-year periods deterministically from the available canonical fiscal years. The layer
consumes Feature 1 metrics and Feature 2A snapshots, performs no SEC retrieval, uses centralized named
thresholds (no configurable weights, no numeric score), and is built from small deterministic
functions. All Feature 1 and Feature 2A behavior and tests are preserved.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, enum, typing, math). No new
runtime dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1, invoked
only by Feature 1 code, never by the compounding layer.

**Storage**: N/A; the compounding view is a pure in-memory transformation of already-computed metrics
and snapshots.

**Testing**: `pytest` with controlled in-memory `OwnerEconomicsRow`, `CapitalEfficiencyRow`, and
`EconomicValueSnapshot` fixtures constructed directly (no SEC payloads required). All existing Slice
1A through 1E and Slice 2A tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during view construction or
classification.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce each Adobe compounding view for a valid payload in under 2 seconds, with
the only network access being the existing Feature 1 retrieval outside this layer.

**Constraints**: Deterministic and offline; the layer consumes Feature 1 metrics and Feature 2A
snapshots and never re-normalizes SEC facts, duplicates Feature 1 calculations, or calls the SEC API;
CAGR uses the fiscal-year interval count (observations minus one) as the exponent denominator and never
the observation count; invalid CAGR inputs (missing endpoint, zero or negative beginning, sign change,
non-positive ending) yield explicit unavailable results, never a fabricated rate; compounding rates
(period growth) are kept distinct from start-to-end level changes; the classification is produced by
documented explicit rules, not an opaque, weighted, or 0-to-100 score, and is never an average of the
annual classifications; FCF-per-share CAGR is the primary per-share measure and is not equated with
intrinsic-value CAGR; share-count-driven per-share results, material dilution, and ROIC deterioration
are surfaced and temper the verdict; periods are selected deterministically from canonical fiscal years
with an explicit insufficient-history outcome and no assumption that five observations exist; thresholds
are centralized, named, documented, imprecise-by-design, plausible for conventional mature companies,
and not tuned to Adobe; small deterministic functions rather than a generic analytics, rules-engine, or
scoring framework.

**Scale/Scope**: ADBE only; one new `compounding.py` module (view type, classification enum,
driver/reason-code enum, centralized thresholds, CAGR and delta helpers, deterministic period
selection, annual-classification counting, driver generation, classification, orchestration from
facts, and a compact formatter); the recent three-year and longest five-year periods; one new test
module; one educational notebook; no changes to Feature 1 or Feature 2A modules beyond adding package
exports.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. The layer performs no normalization; it consumes Feature 1 metrics
  and Feature 2A snapshots and computes only CAGR, start-to-end deltas, and counts. CAGR uses the
  correct interval count and explicit invalid-case handling.
* **Traceability**: PASS. Each view references its period bounds and carries the concrete compounding
  rates, level changes, annual counts, and ordered named drivers that produced its classification.
* **Deterministic computation**: PASS. CAGR, deltas, period selection, counting, and classification
  are pure deterministic functions with no AI, randomness, or hidden state; identical inputs yield
  identical classifications and ordered drivers.
* **Definitions and tests**: PASS. The CAGR definition, every threshold, guardrail, and classification
  branch is documented and unit-tested. A meaningful new concept (multi-year compounding) adds an
  educational notebook.
* **Fail loudly**: PASS. Invalid CAGR inputs and insufficient history use explicit unavailable and
  `INSUFFICIENT_DATA` semantics; no rate or endpoint is fabricated.
* **Current-release scope**: PASS. Only the multi-year compounding view and classification for ADBE are
  added; no decomposition, valuation, scoring, screening, portfolio, agent, or infrastructure work.

### Post-Design Evaluation

* **Provider boundary**: PASS. The compounding layer sits above Feature 1 and Feature 2A and never
  touches SEC transport; `compounding_view_from_facts` delegates all retrieval and normalization to
  existing Feature 1 and Feature 2A entry points.
* **Minimal contract**: PASS. The public surface adds one view type, one classification enum, one
  driver enum, one thresholds type with a default instance, the CAGR helper, and the build, orchestrate,
  and format functions, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally; interpretation tests need no network
  and no SEC fixtures.
* **Reproducibility**: PASS. Unit tests construct Feature 1 rows and Feature 2A snapshots directly and
  assert exact CAGRs, classifications, and ordered drivers for the CAGR mechanics and every
  compounding-interpretation case.
* **Failure integrity**: PASS. All invalid-CAGR and insufficient-history paths surface explicitly, and
  all existing Slice 1A through 1E and Slice 2A behavior and tests are preserved.

### Interpretation-layer separation justification

The compounding layer is a new concern distinct from normalization, metric calculation, and the annual
interpretation layer. It reads the aligned `OwnerEconomicsRow` and `CapitalEfficiencyRow` metrics and
the `EconomicValueSnapshot` annual verdicts, so it introduces no new provider capability and no new
external data. It duplicates no Feature 1 calculation: revenue, free cash flow, FCF per share, diluted
shares, margins, ROIC, and net cash are read from existing outputs, and only period-level CAGR, deltas,
and counts are derived here. Thresholds are centralized in one named, inspectable place; there are no
configurable weights and no numeric composite score, and the multi-year verdict is never an average of
the annual verdicts. The rules are small deterministic functions, not a framework. No constitutional
violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/007-economic-compounding-view/
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
    ├── __init__.py            # Package exports; adds compounding exports
    ├── sec.py                 # Slice 1A retrieval; unchanged
    ├── _annual.py             # Shared primitive; unchanged
    ├── revenue.py             # Slice 1B; unchanged
    ├── operating_income.py    # Slice 1C; unchanged
    ├── margin.py              # Slice 1C; unchanged
    ├── reported.py            # Slice 1D; unchanged
    ├── owner_economics.py     # Slice 1D; consumed, unchanged
    ├── balance_sheet.py       # Slice 1E; unchanged
    ├── capital_efficiency.py  # Slice 1E; consumed, unchanged
    ├── economic_value.py      # Slice 2A; consumed, unchanged
    └── compounding.py         # New: view, classification, drivers, thresholds, CAGR, orchestration

tests/
├── test_sec.py                # Existing; unchanged
├── test_revenue.py            # Existing; unchanged
├── test_operating_income.py   # Existing; unchanged
├── test_margin.py             # Existing; unchanged
├── test_reported.py           # Existing; unchanged
├── test_owner_economics.py    # Existing; unchanged
├── test_balance_sheet.py      # Existing; unchanged
├── test_capital_efficiency.py # Existing; unchanged
├── test_economic_value.py     # Existing; unchanged
└── test_compounding.py        # New: CAGR mechanics, deltas, counts, drivers, classification, periods

notebooks/
└── 04_adbe_compounding.ipynb  # New: educational notebook for the multi-year compounding lens
```

**Structure Decision**: Add a single `compounding.py` module that consumes the existing
`OwnerEconomicsRow`, `CapitalEfficiencyRow`, and `EconomicValueSnapshot` outputs. It selects a period's
endpoints deterministically from the canonical fiscal years, computes CAGRs over the interval count,
computes start-to-end deltas, counts the annual classifications in the period, and applies a
deterministic documented classification built from small composable helpers with centralized named
thresholds. Feature 1 and Feature 2A modules are consumed unchanged; only `__init__.py` gains exports.
An educational notebook demonstrates the concept per the constitution.

## Complexity Tracking

No violations or complexity exceptions. The feature adds one interpretation module, one thresholds type,
one classification enum, one driver enum, and one view type, all justified by the current requirement,
with no analytics framework, no rules-engine framework, no configurable weights, and no numeric
composite score.

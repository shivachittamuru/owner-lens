---
title: "Implementation Plan: Adobe Core Owner Economics"
description: Technical plan for normalizing Adobe cash-generation facts and deriving owner economics
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/004-core-owner-economics/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Extend OwnerLens into core owner economics. Normalize four new reported facts from Adobe's raw SEC
Company Facts (net income, operating cash flow, capital expenditures, diluted weighted-average
shares), reuse the canonical revenue and operating-income series, then deterministically derive net
margin, free cash flow, FCF margin, FCF per diluted share, and adjacent-year growth for FCF, FCF per
share, and diluted shares. Reuse the shared `_annual` primitive, extending it minimally for a
non-USD unit (shares). Keep reported facts distinct from derived metrics, verify CapEx sign and
diluted-share semantics against live data, and introduce no network access during normalization and
no generalized financial-statement framework.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, datetime, typing). No new
runtime dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1.

**Storage**: N/A; normalization and derivation are pure in-memory transformations.

**Testing**: `pytest` with controlled in-memory Company Facts fixtures. All existing Slice 1A through
1C tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during normalization or derivation.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the aligned owner-economics view for a valid payload in under 2
seconds with no external calls.

**Constraints**: Deterministic and offline; single concept per canonical series; explicit unit per
metric (USD for value facts, shares for diluted shares); fiscal year derived from period end date,
not the raw XBRL `fy`; 52-to-53 week full-year tolerance; typed failures on missing concept and
unresolved conflict; CapEx canonicalized to a positive expenditure amount; weighted-average diluted
shares, never point-in-time shares outstanding; derived metrics computed in code, never sourced;
missing inputs and zero denominators omit dependent metrics explicitly; negative economic values are
valid; shared logic extended only for concrete differences discovered here.

**Scale/Scope**: ADBE only; four new reported metrics plus derived owner economics; approximately the
latest five completed fiscal years; a minimal `_annual` extension, one generic reported-metric
module, one owner-economics derivation module, and focused unit tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. Each reported concept has a documented, live-verified selection
  rule; each derived metric has an explicit formula; CapEx sign and diluted-share semantics are
  verified against Adobe's actual facts.
* **Traceability**: PASS. Every reported observation preserves full SEC provenance including unit,
  and every derived metric references its fiscal year and inputs.
* **Deterministic computation**: PASS. Selection, fiscal-year derivation, dedup, alignment, and all
  derivations are deterministic with no AI behavior.
* **Definitions and tests**: PASS. Concept orders, period semantics, formulas, CapEx sign, and
  share semantics are documented and covered by tests. An educational owner-economics notebook is a
  recorded follow-up, not speculative work now.
* **Fail loudly**: PASS. Missing-concept and conflicting-value paths raise typed errors; dependent
  metrics are omitted explicitly on missing inputs or zero denominators, never invented or infinite.
* **Current-release scope**: PASS. Only the listed reported facts and derived owner-economics metrics
  for ADBE are added.

### Post-Design Evaluation

* **Provider boundary**: PASS. Normalization and derivation consume an already-retrieved payload and
  stay separate from SEC transport in `sec.py`.
* **Minimal contract**: PASS. The public surface adds the four reported normalizers and the
  owner-economics view, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally without network access.
* **Reproducibility**: PASS. Unit tests use fixed fixtures modeled on the verified Adobe fact shapes
  and assert exact values, alignment, provenance, and derived metrics.
* **Failure integrity**: PASS. All new failure paths surface explicitly, and existing Slice 1A
  through 1C behavior and tests are preserved.

### Shared-code extension justification

Live inspection confirmed net income, operating cash flow, and capital expenditures share the exact
USD duration-fact shape already handled by `_annual`. The one concrete difference is diluted
weighted-average shares, reported in the `shares` unit rather than USD. Therefore `_annual` gains a
single `unit` parameter (default USD); no other engine change is required. The repeated per-metric
wrapper pattern from Slices 1B and 1C would duplicate across four more metrics, so this slice
introduces one generic reported-metric normalizer driven by a small metric specification. Revenue and
operating income keep their existing modules and public error types unchanged to preserve their
tests; the generic form is documented as the pattern they can converge to later without behavior
change. No generalized financial-statement framework is introduced.

## Project Structure

### Documentation (this feature)

```text
specs/004-core-owner-economics/
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
    ├── __init__.py           # Package exports; adds reported and owner-economics exports
    ├── sec.py                # Slice 1 retrieval; unchanged
    ├── _annual.py            # Shared primitive; gains a single `unit` parameter
    ├── revenue.py            # Slice 1B; unchanged
    ├── operating_income.py   # Slice 1C; unchanged
    ├── margin.py             # Slice 1C two-metric view; unchanged
    ├── reported.py           # New: generic reported-metric normalizer + four metric specs
    └── owner_economics.py    # New: derived owner-economics metrics, growth, and alignment

tests/
├── test_sec.py               # Existing; unchanged
├── test_revenue.py           # Existing; unchanged
├── test_operating_income.py  # Existing; unchanged
├── test_margin.py            # Existing; unchanged
├── test_reported.py          # New: concept, unit, full-year, comparatives, ambiguity, CapEx, shares
└── test_owner_economics.py   # New: alignment, net margin, FCF, FCF margin, FCF/share, growth, edges
```

**Structure Decision**: Extend `_annual.py` with one `unit` parameter, add a single generic
`reported.py` normalizer driven by per-metric specifications (concept preference, unit), and add
`owner_economics.py` for derivation, growth, and alignment. This avoids four near-identical wrapper
modules and demonstrates the annual-normalization abstraction that survives across several metrics.
Revenue, operating income, and their margin view remain untouched to preserve prior tests. Reported
observations preserve source provenance; CapEx is canonicalized to a positive magnitude at the point
of free-cash-flow derivation, keeping the reported fact's stored value faithful to the source.

## Complexity Tracking

No violations or complexity exceptions. The `_annual` change is a single additive `unit` parameter,
and the generic reported-metric normalizer is introduced only after six concrete metrics demonstrate
the wrapper duplication, satisfying the refactor-on-demonstrated-need rule.

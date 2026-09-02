---
title: "Implementation Plan: Adobe Balance Sheet and Capital Efficiency"
description: Technical plan for instant balance-sheet normalization and capital-efficiency metrics
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/005-balance-sheet-capital-efficiency/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Extend OwnerLens from duration facts into point-in-time balance-sheet facts, then derive a first
capital-efficiency view. Normalize fiscal-year-end instant observations for cash, short-term
investments, current debt, long-term debt, total assets, and total stockholders' equity, using an
explicit instant primitive kept separate from the duration primitive. Reuse the canonical operating
income and net income series and add duration income-tax-expense and pretax-income series for the
tax rate. Deterministically derive cash plus short-term investments, net cash or net debt, ROA, ROE,
invested capital, NOPAT, and ROIC, using average balances with a single calculation-only baseline
year. Keep reported facts distinct from derived metrics, verify every concept against live data, and
introduce no network access during normalization and no generalized accounting ontology.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, datetime, typing). No new
runtime dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1.

**Storage**: N/A; normalization and derivation are pure in-memory transformations.

**Testing**: `pytest` with controlled in-memory Company Facts fixtures. All existing Slice 1A through
1D tests are preserved and must continue to pass. No network access in tests.

**Target Platform**: Local Python environments; no external calls during normalization or derivation.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the aligned capital-efficiency view for a valid payload in under 2
seconds with no external calls.

**Constraints**: Deterministic and offline; instant facts selected by fiscal-period-end semantics
with no duration window and kept distinct from duration normalization; single concept per canonical
series except total debt, which is an explicit deterministic sum of documented components with
preserved input provenance; fiscal year derived from the period-end date, not the raw XBRL `fy`;
typed failures on missing concept and unresolved conflict; average-balance denominators with one
baseline year and explicit omission when a beginning balance is unavailable; zero or negative
denominators omit dependent metrics explicitly; derived metrics computed in code, never sourced;
negative economic values valid; instant primitive introduced only for demonstrated duplication.

**Scale/Scope**: ADBE only; five reported balance-sheet facts plus derived capital efficiency;
approximately the latest five completed fiscal years with one calculation-only baseline year; one
instant primitive, one balance-sheet module, one capital-efficiency module, two added duration specs,
and focused unit tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. Each concept is live-verified; the instant-versus-duration
  distinction is explicit; cash, debt, invested capital, tax rate, NOPAT, and the average-balance
  denominators have documented definitions.
* **Traceability**: PASS. Every reported balance-sheet observation preserves full provenance
  including its instant period-end date, and total debt preserves the provenance of both components.
* **Deterministic computation**: PASS. Instant selection, fiscal-year derivation, dedup, alignment,
  and all derivations are deterministic with no AI behavior.
* **Definitions and tests**: PASS. Instant selection, cash and debt definitions, invested capital,
  tax rate, NOPAT, and each ratio are documented and covered by tests. A capital-efficiency
  educational notebook is a recorded follow-up, not speculative work now.
* **Fail loudly**: PASS. Missing-concept and conflicting-value paths raise typed errors; dependent
  metrics are omitted explicitly on missing inputs, missing baselines, or zero denominators.
* **Current-release scope**: PASS. Only the listed balance-sheet facts and capital-efficiency metrics
  for ADBE are added.

### Post-Design Evaluation

* **Provider boundary**: PASS. Normalization and derivation consume an already-retrieved payload and
  stay separate from SEC transport in `sec.py`.
* **Minimal contract**: PASS. The public surface adds the balance-sheet normalizers and the
  capital-efficiency view, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally without network access.
* **Reproducibility**: PASS. Unit tests use fixed fixtures modeled on the verified Adobe instant and
  duration shapes and assert exact values, alignment, provenance, and derived metrics.
* **Failure integrity**: PASS. All new failure paths surface explicitly, and existing Slice 1A
  through 1D behavior and tests are preserved.

### Instant-primitive justification

Live inspection shows cash, short-term investments, current debt, long-term debt, total assets, and
total stockholders' equity are all instant facts with no start date, identical fiscal-year-end
selection needs, and the same `fy` comparative-repeat behavior. Six concepts duplicating this logic
justify one small instant primitive. It shares the deduplication, fiscal-year derivation, and
resolution helpers with the duration primitive but keeps a distinct qualifier (no start date, annual
fiscal-period end, 10-K context) so the accounting distinction stays explicit. Duration and instant
normalization remain two clearly named selection paths rather than one merged engine. No generalized
accounting ontology is introduced.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/005-balance-sheet-capital-efficiency/
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
    ├── __init__.py            # Package exports; adds balance-sheet and capital-efficiency exports
    ├── sec.py                 # Slice 1 retrieval; unchanged
    ├── _annual.py             # Shared primitive; gains a distinct instant selection path
    ├── revenue.py             # Slice 1B; unchanged
    ├── operating_income.py    # Slice 1C; unchanged
    ├── margin.py              # Slice 1C; unchanged
    ├── reported.py            # Slice 1D; adds income-tax-expense and pretax-income duration specs
    ├── owner_economics.py     # Slice 1D; unchanged
    ├── balance_sheet.py       # New: fiscal-year-end instant normalization and specs
    └── capital_efficiency.py  # New: derived capital-efficiency metrics, averages, and alignment

tests/
├── test_sec.py                # Existing; unchanged
├── test_revenue.py            # Existing; unchanged
├── test_operating_income.py   # Existing; unchanged
├── test_margin.py             # Existing; unchanged
├── test_reported.py           # Existing; extended for tax and pretax specs
├── test_owner_economics.py    # Existing; unchanged
├── test_balance_sheet.py      # New: instant vs duration, year-end selection, comparatives, ambiguity
└── test_capital_efficiency.py # New: cash, debt, averages, invested capital, tax, NOPAT, ROA/ROE/ROIC
```

**Structure Decision**: Add a distinct instant selection path in `_annual.py` that shares the
deduplication and resolution helpers with the duration path, a `balance_sheet.py` module for
fiscal-year-end instant normalization, and a `capital_efficiency.py` module for derivation. Reuse the
Slice 1D duration normalizer for income tax expense and pretax income. Total debt and all
capital-efficiency metrics are derived values kept distinct from reported observations; total debt
preserves the provenance of its components.

## Complexity Tracking

No violations or complexity exceptions. The instant primitive is a second explicit selection path
justified by six duplicating concepts, and total debt is the only multi-component reported value,
computed deterministically with preserved provenance.

---
title: "Implementation Plan: Capital Allocation Lens"
description: Technical plan for normalizing Adobe capital-allocation facts and a deterministic capital-allocation interpretation layer
ms.date: 2026-09-01
ms.topic: reference
---

**Branch**: `main` | **Date**: 2026-09-01 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/008-capital-allocation-lens/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Explain how Adobe deployed the cash it generated and whether those decisions helped per-share owners.
Two layers. First, normalize three new reported facts from SEC Company Facts using the existing annual
duration machinery: common-stock repurchase cash outflow (`PaymentsForRepurchaseOfCommonStock`),
stock-based compensation (`ShareBasedCompensation`, fallback `AllocatedShareBasedCompensationExpense`),
and cash dividends paid (`PaymentsOfDividendsCommonStock` / `PaymentsOfDividends`) — which Adobe does
not report, so the dividend normalizer tolerantly returns an absent series rather than raising. Second,
a deterministic interpretation layer consumes the existing Feature 1 free cash flow, diluted shares,
share-count growth, net cash or net debt, and ROIC, the Feature 2A annual snapshots, and the new facts
to derive per-year repurchases/FCF, dividends/FCF, SBC/FCF, capital returned, capital returned/FCF, and
retained FCF (preserving negative results), a `BuybackEffectiveness` interpretation that compares
repurchase spending against the actual diluted-share-count change, and a `CapitalAllocationClassification`
(owner-friendly, balanced, questionable, owner-unfriendly, insufficient-data) with ordered named drivers.
Balance-sheet context reuses a shared net-cash trajectory helper extracted from Feature 2A and 2B, and
ROIC is surfaced as context only. Thresholds are centralized and named; no numeric score, no weights,
no SEC calls in the interpretation layer. All Feature 1, 2A, and 2B behavior and tests are preserved.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard library only (dataclasses, enum, typing). No new runtime
dependency. Upstream retrieval still uses the existing `httpx` client from Slice 1, invoked only by the
reported-fact layer, never by the interpretation layer.

**Storage**: N/A; interpretation is a pure in-memory transformation of already-computed facts and metrics.

**Testing**: `pytest` with controlled in-memory Company Facts fixtures for the reported facts, and
constructed Feature 1 rows, Feature 2A snapshots, and capital-allocation facts for the interpretation.
All existing Slice 1A through 1E, 2A, and 2B tests are preserved and must continue to pass. No network
access in tests.

**Target Platform**: Local Python environments; no external calls during interpretation.

**Project Type**: Small Python library extending the existing `owner_lens` package.

**Performance Goals**: Produce the Adobe capital-allocation view and summary in under 2 seconds, with
the only network access being the existing Feature 1 retrieval outside the interpretation layer.

**Constraints**: Deterministic and offline interpretation; the reported layer normalizes three new
full-year duration facts with live-verified concepts, deterministic selection, earliest-filed
comparative dedup, typed ambiguity failure, and full provenance, deriving the fiscal year from the
period-end date; repurchases are taken from the reported cash-outflow concept and never inferred from
share-count or treasury-stock changes; dividends reflect cash actually paid and their structural
absence for Adobe is preserved (the dividend normalizer returns an absent series rather than raising);
SBC is shown as a burden signal and is never subtracted from free cash flow; a reported zero, a
confidently-absent concept (no applicable activity), and unavailable data are distinguished, with
explicit unavailable values and conservative classification when the distinction is unreliable;
retained FCF is an interpretive residual preserved when negative; buyback effectiveness uses the actual
diluted-share-count change as the primary ownership outcome and never assumes SBC maps one-for-one to
dilution; the capital-allocation classification is a documented rule summarizing observable outcomes,
not a numeric score or weighted sum, and not a management-intent or valuation judgment; balance-sheet
context reuses a shared net-cash trajectory helper (drawing down surplus cash is not deterioration;
deepening or turning to net debt is); ROIC is context only with no return-on-retained-FCF; thresholds
are centralized, named, documented, imprecise-by-design, and not tuned to Adobe.

**Scale/Scope**: ADBE only; three new reported specs and normalizers added to `reported.py` (one
tolerant for the absent dividend concept); one new `capital_allocation.py` interpretation module
(row type, buyback-effectiveness enum, classification enum, driver enum, centralized thresholds,
derivations, interpretations, orchestration, formatter, and multi-year summary); one shared internal
net-cash trajectory helper extracted from Feature 2A and 2B and reused by all three interpretation
slices; approximately the latest five completed fiscal years; one new test module plus extensions to
`test_reported.py`; and one educational notebook.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness**: PASS. The three new concepts are live-verified against Adobe's Company
  Facts; the repurchase, dividend, and SBC meanings are documented; the interpretation reuses verified
  Feature 1 and 2A outputs.
* **Traceability**: PASS. Every reported observation preserves full provenance, and each derived metric
  and classification references its fiscal year, inputs, and ordered named drivers.
* **Deterministic computation**: PASS. Normalization, derivation, thresholding, buyback effectiveness,
  and classification are pure deterministic functions with no AI, randomness, or hidden state.
* **Definitions and tests**: PASS. Each concept mapping, ratio, effectiveness rule, threshold, and
  classification branch is documented and unit-tested. A meaningful new concept (capital allocation)
  adds an educational notebook.
* **Fail loudly**: PASS. Ambiguous conflicts raise typed errors; absent concepts, reported zeros, and
  unavailable data are distinguished; missing inputs omit metrics explicitly and classify conservatively.
* **Current-release scope**: PASS. Only capital-allocation normalization and interpretation for ADBE
  are added; no valuation, scoring, acquisition decomposition, screening, portfolio, agent, or
  infrastructure work.

### Post-Design Evaluation

* **Provider boundary**: PASS. Normalization stays in the reported layer over an already-retrieved
  payload; the interpretation layer makes no SEC calls and delegates retrieval to Feature 1 and 2A.
* **Minimal contract**: PASS. The public surface adds three reported normalizers, one row type, two
  interpretation enums, one driver enum, one thresholds type, and the build, orchestrate, format, and
  summary functions, and nothing broader.
* **Local-first delivery**: PASS. Runs and tests entirely locally; interpretation tests need no network.
* **Reproducibility**: PASS. Reported-fact tests use fixed fixtures modeled on the verified Adobe
  shapes; interpretation tests construct inputs directly and assert exact metrics, effectiveness,
  classifications, and ordered drivers.
* **Failure integrity**: PASS. All new failure and unavailable paths surface explicitly, and all
  existing Slice 1A through 1E, 2A, and 2B behavior and tests are preserved, including after the
  shared net-cash trajectory helper is extracted.

### Shared-helper justification

Feature 2A and Feature 2B each carry a private net-cash trajectory rule (a direction plus a
sign-flip and net-debt flag distinguishing surplus-cash drawdown from genuine leverage deterioration).
Feature 2C needs the identical rule for its balance-sheet guardrail. Three concrete consumers of the
same logic justify extracting one small internal helper and refactoring Feature 2A and 2B to use it,
behavior-preserving and guarded by their existing tests. No separate leverage framework is introduced.

No constitutional violations require justification.

## Project Structure

### Documentation (this feature)

```text
specs/008-capital-allocation-lens/
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
    ├── __init__.py            # Package exports; adds capital-allocation exports
    ├── sec.py                 # Slice 1A retrieval; unchanged
    ├── _annual.py             # Shared primitive; unchanged
    ├── _trajectory.py         # New: shared net-cash trajectory helper (extracted from 2A/2B)
    ├── revenue.py             # Slice 1B; unchanged
    ├── operating_income.py    # Slice 1C; unchanged
    ├── margin.py              # Slice 1C; unchanged
    ├── reported.py            # Slice 1D; adds repurchase, SBC, and dividend duration specs
    ├── owner_economics.py     # Slice 1D; consumed, unchanged
    ├── balance_sheet.py       # Slice 1E; unchanged
    ├── capital_efficiency.py  # Slice 1E; consumed, unchanged
    ├── economic_value.py      # Slice 2A; refactored to use _trajectory; behavior preserved
    ├── compounding.py         # Slice 2B; refactored to use _trajectory; behavior preserved
    └── capital_allocation.py  # New: capital-allocation derivations, interpretation, orchestration

tests/
├── test_sec.py                # Existing; unchanged
├── test_revenue.py            # Existing; unchanged
├── test_operating_income.py   # Existing; unchanged
├── test_margin.py             # Existing; unchanged
├── test_reported.py           # Existing; extended for repurchase, SBC, and dividend specs
├── test_owner_economics.py    # Existing; unchanged
├── test_balance_sheet.py      # Existing; unchanged
├── test_capital_efficiency.py # Existing; unchanged
├── test_economic_value.py     # Existing; unchanged (behavior preserved after refactor)
├── test_compounding.py        # Existing; unchanged (behavior preserved after refactor)
└── test_capital_allocation.py # New: facts, ratios, retained FCF, buyback effectiveness, classification

notebooks/
└── 05_adbe_capital_allocation.ipynb  # New: educational notebook for the capital-allocation lens
```

**Structure Decision**: Add the three new reported duration specs and normalizers to `reported.py`
(the established home of generic reported duration facts), with a tolerant dividend normalizer that
returns an absent series because Adobe reports no dividend concept. Extract the shared net-cash
trajectory rule into a small internal `_trajectory.py` and refactor Feature 2A and 2B to use it,
justified by three concrete consumers and guarded by existing tests. Add a `capital_allocation.py`
interpretation module that consumes existing Feature 1 and 2A outputs plus the new facts and makes no
SEC calls. Feature 1, 2A, and 2B behavior is preserved; only `__init__.py` gains exports. An
educational notebook demonstrates the concept per the constitution.

## Complexity Tracking

No violations or complexity exceptions. The feature adds three reported specs, one interpretation
module, one shared trajectory helper (justified by three consumers), and the associated types, all tied
to the current requirement, with no rules-engine framework, no configurable weights, and no numeric
composite score.

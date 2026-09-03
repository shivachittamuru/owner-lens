---
title: "Implementation Plan: Generalize Financial Metric Normalization Across Companies"
description: Technical plan for a canonical metric-definition layer with per-company overrides that generalizes Feature 1 normalization
ms.date: 2026-09-02
ms.topic: reference
---

**Branch**: `011-generalize-metric-normalization` | **Date**: 2026-09-02 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/011-generalize-metric-normalization/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Introduce a small canonical metric-definition registry that records, per canonical metric, its fact
kind (duration or instant), expected unit, an ordered default source-concept preference, and an
optional per-company override. A single resolver turns a canonical metric plus a ticker into the
concrete concept preference consumed by the existing `select_annual_series` (duration) and
`select_instant_series` (instant) primitives. The Adobe-only `ensure_supported_ticker` gate is
removed from the normalization path; "unsupported" becomes the natural typed `ConceptNotFound`
outcome when no trustworthy concept resolves, never a fabricated value. Adobe's default concept
selections are preserved exactly, so all Feature 1 and Feature 2 Adobe outputs are unchanged.

Live SEC research on ADBE, V, and COST drives a minimal, documented override set: V and COST current
debt uses `LongTermDebtCurrent` and long-term debt uses `LongTermDebtNoncurrent` (Adobe keeps
`DebtCurrent` + `LongTermDebt`); V equity uses
`StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`; short-term investments
becomes tolerant-absent (V reports no `ShortTermInvestments` concept and its investment securities
are deliberately not absorbed as corporate cash); and V weighted-average diluted shares is
explicitly UNSUPPORTED because Visa tags no such us-gaap concept. Every normalized observation keeps
its actual selected source concept as provenance. An educational notebook explains the canonical vs
source-concept distinction. No plugin system, provider registry, database, external config, or
Feature 2 change is introduced.

## Technical Context

**Language/Version**: Python 3.12.11 (project requirement: Python 3.12 or later)

**Primary Dependencies**: Python standard-library dataclasses and typing for the registry;
existing `httpx` only for the optional live validation. No new dependency is introduced.

**Storage**: N/A; canonical definitions and overrides are in-code declarative data; each invocation
consumes resolved raw facts and retains nothing

**Testing**: `pytest` with controlled ADBE, V, and COST fact fixtures for metric resolution and
multi-company normalization; optional live SEC coverage check excluded from the default suite

**Target Platform**: Local Python environments with outbound HTTPS access for optional live checks

**Project Type**: Small Python library with the existing console entry point available for manual
validation

**Performance Goals**: Deterministic offline normalization; no additional network calls beyond the
existing single Company Facts retrieval per company

**Constraints**: Duration and instant selection paths remain separate; Adobe concept selection is
unchanged; overrides are declarative, minimal, and traceable to observed SEC facts; no fabricated or
silently zeroed values; no persistence, caching, config formats, agents, or scoring

**Scale/Scope**: Canonical definitions only for metrics OwnerLens currently uses (11 duration, 6
instant); golden validation across ADBE, V, and COST; one new registry module, refactors to four
normalization modules, new and extended tests, and one educational notebook

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **Financial correctness (I)**: PASS. Canonical definitions and overrides are grounded in live SEC
  facts; no definition is broadened to force a company to fit, and unrepresentable metrics are
  surfaced explicitly rather than approximated.
* **Traceability (II)**: PASS. Every observation retains the actual selected source concept, unit,
  fiscal year, and filing provenance, so canonicalization never hides which concept was used.
* **Deterministic computation (III)**: PASS. Resolution and normalization are deterministic
  data-driven lookups with no AI behavior.
* **Definitions and tests (IV)**: PASS. Each canonical metric has an explicit documented definition;
  controlled multi-company tests cover resolution, normalization, semantics, and Adobe regression; a
  new educational notebook demonstrates the concept.
* **Fail loudly (V)**: PASS. Missing or conflicting concepts yield typed failures or documented
  tolerant-absence; no value is fabricated or silently zeroed.
* **Current-release scope (VI)**: PASS. The registry covers only metrics OwnerLens already uses; a
  small declarative structure replaces the ADBE gate. No plugin system, provider registry,
  inheritance, database, external config, or ontology is added.

### Post-Design Evaluation

* **Provider boundary**: PASS. Company-specific concept knowledge is confined to the declarative
  registry, outside the deterministic selection primitives and downstream metric logic.
* **Minimal contract**: PASS. Callers request canonical OwnerLens metrics; the source-concept
  mapping is internal and exposed only as provenance.
* **Local-first delivery**: PASS. Everything runs and tests locally; live checks stay optional.
* **Reproducibility**: PASS. Tests use fixed ADBE, V, and COST fixtures; the compatibility matrix is
  recorded in research.md from live facts.
* **Failure integrity**: PASS. Unsupported, absent, and conflicting outcomes are explicit and typed;
  Adobe selections are unchanged.

No constitutional violations require justification. The per-company overrides are the minimum
required for correctness and are individually traceable to observed SEC facts (see research.md).

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
    ├── metrics.py           # NEW: CanonicalMetricDefinition registry + per-company overrides + resolver
    ├── _annual.py           # Drop ADBE-only ensure_supported_ticker gate from the normalization path
    ├── reported.py          # Resolve duration concept preference per ticker via the registry
    ├── balance_sheet.py     # Resolve instant concept preference per ticker; tolerant-absent short-term investments
    ├── revenue.py           # Resolve revenue concept preference per ticker via the registry
    └── operating_income.py  # Resolve operating-income concept preference per ticker via the registry

tests/
├── test_metrics.py          # NEW: resolution, overrides, unknown metric, deterministic ordering
├── test_reported.py         # Extend: V and COST duration normalization + provenance
├── test_balance_sheet.py    # Extend: V and COST instant normalization, debt override, tolerant STI
├── test_revenue.py          # Extend: V and COST revenue concept selection
└── test_operating_income.py # Extend: V and COST operating income

notebooks/
└── 07_multi_company_metric_normalization.ipynb  # NEW educational artifact
```

**Structure Decision**: Add one cohesive `metrics.py` registry as the single auditable home for
canonical definitions and per-company overrides, and have the existing thin normalization modules
resolve their concept preference through it per ticker. The two selection primitives in `_annual`
stay separate and unchanged in behavior; only the ADBE allow-list gate is removed from the
normalization entry points. Adobe definitions carry no overrides, so Adobe selection is byte-for-byte
preserved.

## Complexity Tracking

No violations or complexity exceptions. Per-company overrides are declarative data, not architectural
abstractions, and each is justified by observed SEC facts in research.md.

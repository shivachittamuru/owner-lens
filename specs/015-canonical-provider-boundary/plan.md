---
title: "Implementation Plan: Canonical Provider Boundary"
description: Technical plan for OwnerLens Slice 5A, which routes all downstream financial logic through a provider-neutral canonical financial history populated by an SEC adapter
ms.date: 2026-10-05
ms.topic: reference
---

**Branch**: `015-canonical-provider-boundary` | **Date**: 2026-10-05 | **Spec**: [Feature specification](spec.md)

**Input**: Feature specification from `specs/015-canonical-provider-boundary/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Insert a provider-neutral boundary between SEC normalization and OwnerLens economics.

* **Canonical model**: A new module, `src/owner_lens/canonical.py`, defines immutable
  `CanonicalFact`, `CanonicalSeries`, and `CanonicalFinancialHistory` types. It covers the
  17-metric vocabulary that OwnerLens already uses, per-metric `MetricStatus` (`AVAILABLE`,
  `STRUCTURALLY_ABSENT`, `UNSUPPORTED`, `INVALID`), and a small provider-neutral error hierarchy.
* **SEC adapter**: A new module, `src/owner_lens/sec_adapter.py`, exposes
  `canonical_history_from_sec(raw_facts, *, ticker, max_years)`. It reuses the existing SEC
  normalizers unchanged, copies provenance into each fact (`provider="sec"`, the concept as
  `provider_field`, plus form, filed date, and accession), and stores per-metric failures instead
  of raising them. Each downstream layer therefore fails lazily, exactly as it does today.
* **Downstream modules**: The seven analytical modules each gain a `*_from_history(history)` entry
  point. Their kernels are retyped to `CanonicalSeries`. The existing `*_from_facts` functions stay
  as thin wrappers: map with the SEC adapter, then delegate.
* **Error compatibility**: The existing SEC error classes gain canonical base classes through
  additive inheritance. Re-raised errors keep their concrete types and messages, while downstream
  code catches only canonical types.
* **Ingestion**: `ingest_company` builds the history once. Persistence adapters read
  `provider_field` instead of `concept`, so the persisted records are byte-identical.
* **Regression oracle**: A characterization baseline is captured from the current code before the
  refactor. An AST-based boundary test stops SEC dependencies from leaking back downstream.
* **Docs**: A notebook (`12_canonical_provider_boundary.ipynb`) and Feature 5 documentation explain
  the layering.

## Technical Context

**Language/Version**: Python 3.12 or later (project requirement).

**Primary Dependencies**: Existing only. The new code uses only the standard library: `dataclasses`,
`enum`, `datetime`, `collections.abc`, `typing`, and `ast` in tests. No new third-party dependency
is added (constitution VI).

**Storage**: Unchanged. The Slice 4A and 4B SQLite and filesystem stores are reused, and record
types and schema do not change. Only the pure domain-to-record adapter reads a renamed field.

**Testing**: `pytest` with the existing deterministic fixtures in `tests/_fixtures.py`
(`adbe_facts`, `visa_facts`, `costco_facts`) and fixture variants for the MSFT/CRM-style
missing-current-debt case and a lazy-ambiguity case. New test modules:

* `test_canonical.py`
* `test_sec_adapter.py`
* `test_canonical_downstream.py`
* `test_canonical_regression.py`, with its committed baseline JSON
* `test_canonical_boundary.py`

Existing tests stay green with unchanged assertions. Only the series-builder helpers in
`test_capital_allocation.py` migrate to `CanonicalSeries` (research R9).

**Target Platform**: Local Python environments. All tests run offline. Only the notebook uses live
SEC retrieval, following the existing notebook convention.

**Project Type**: Single Python library with a console entry point.

**Performance Goals**: No regression. Ingestion now normalizes the payload once instead of once per
layer, which is a small improvement but not a goal.

**Constraints**:

* Financial semantics do not change. This covers FCF, FCF per share, ROIC, margins, growth,
  capital-allocation rules, classifications, thresholds, and coverage.
* Exception types, messages, and first-failure ordering are preserved.
* Persisted records are byte-identical.
* No SEC concept names or SEC imports in downstream calculation code, other than the single
  documented wrapper import.
* No FMP, no provider selection, no reconciliation, no package reorganization, no Azure.

**Scale/Scope**:

* New source modules (2): `canonical.py`, `sec_adapter.py`.
* Modified downstream modules (7): `owner_economics.py`, `capital_efficiency.py`,
  `capital_allocation.py`, `economic_value.py`, `compounding.py`, `economic_summary.py`,
  `coverage.py`.
* Modified SEC modules, additive changes only (4): `_annual.py`, `revenue.py`,
  `operating_income.py`, and `metrics.py` (re-export of `MetricKind`).
* Modified orchestration and persistence (3): `ingestion.py`, `persistence/adapters.py`,
  `__init__.py` exports.
* Tests: 5 new modules, 1 test helper migration.
* Docs: 1 notebook and 2 documentation files.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Evaluation

* **I. Financial correctness**: PASS. No definition changes. A characterization baseline captured
  before refactoring makes "unchanged outputs" verifiable exactly, not just within a tolerance.
* **II. Traceability**: PASS. Every canonical fact carries the provider, the provider field (source
  concept), form, filed date, accession, unit, fiscal period, and fiscal year. Persisted provenance
  is unchanged.
* **III. Deterministic computation**: PASS. The change is purely deterministic, and no AI is
  involved.
* **IV. Definitions and tests as contracts**: PASS. The canonical vocabulary, statuses, and
  `require` semantics are documented contracts with focused tests. A notebook demonstrates the new
  boundary concept.
* **V. Fail loudly**: PASS. Unsupported and invalid metrics carry typed errors that are re-raised
  verbatim when needed. Absence is never coerced to zero. `build()` rejects metrics whose status is
  undeclared.
* **VI. Build only what is required**: PASS with justification. The boundary is an explicit
  current-release requirement (Slice 5A), and the next slice (5B) is its first additional consumer.
  The design adds no provider registry, selection logic, or generic schema. Provenance fields stay
  required, as SEC supplies them. Relaxing them is deferred to 5B.

### Post-Design Evaluation

* **Provider-specific mapping outside metric logic**: PASS. All SEC knowledge (concepts, overrides,
  windows, absence policy) lives in `sec_adapter.py` and the existing SEC normalizers. The AST
  boundary test enforces this.
* **Minimal provider contract**: PASS. One function, `canonical_history_from_sec`, and one result
  type. No abstract provider base class is introduced.
* **Dependencies and layers have a current consumer**: PASS. `canonical.py` is consumed by all seven
  downstream modules, ingestion, and persistence adapters. `sec_adapter.py` is consumed by the
  wrappers and ingestion.
* **Reproducibility**: PASS. Tests use fixed fixtures and a committed baseline. The notebook records
  the CIK and payload content hash.
* **Documented exception**: The `*_from_facts` wrappers keep one SEC-side import in each downstream
  module (see Complexity Tracking). This is bounded and has a removal condition.

## Project Structure

### Documentation (this feature)

```text
specs/015-canonical-provider-boundary/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── canonical-model.md
│   ├── sec-adapter.md
│   └── downstream-entry-points.md
├── checklists/
│   └── requirements.md  # /speckit-specify output
└── tasks.md             # /speckit-tasks output (NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/owner_lens/
├── canonical.py           # NEW: CanonicalFact/Series/FinancialHistory, MetricStatus, MetricKind, vocabulary, errors
├── sec_adapter.py         # NEW: canonical_history_from_sec() — SEC normalizers -> canonical history
├── owner_economics.py     # MODIFY: owner_economics_from_history; kernel typed on CanonicalSeries; wrapper delegates
├── capital_efficiency.py  # MODIFY: capital_efficiency_from_history; kernel retyped; wrapper delegates
├── economic_value.py      # MODIFY: economic_value_from_history; wrapper delegates
├── compounding.py         # MODIFY: compounding_view(s)_from_history; wrappers delegate
├── capital_allocation.py  # MODIFY: capital_allocation_from_history; dividend absence via MetricStatus
├── economic_summary.py    # MODIFY: economic_value_summary_from_history; wrapper keeps literal ticker
├── coverage.py            # MODIFY: company_coverage/output_from_history; inputs from statuses; catch MetricUnsupportedError
├── _annual.py             # MODIFY (additive): error classes gain canonical bases
├── revenue.py             # MODIFY (additive): error classes gain canonical bases
├── operating_income.py    # MODIFY (additive): error classes gain canonical bases
├── metrics.py             # MODIFY (additive): re-export MetricKind from canonical
├── ingestion.py           # MODIFY: build history once; call *_from_history
├── __init__.py            # MODIFY: export canonical types, adapter, *_from_history functions
├── margin.py              # UNCHANGED (SEC-side legacy helper, research R13)
└── persistence/
    └── adapters.py        # MODIFY: read CanonicalFact; concept=fact.provider_field (records unchanged)

tests/
├── test_canonical.py              # NEW: model validation, status/require semantics, build()
├── test_sec_adapter.py            # NEW: SEC -> canonical equivalence, provenance, statuses, lazy errors
├── test_canonical_downstream.py   # NEW: *_from_history parity and synthetic non-SEC histories
├── test_canonical_regression.py   # NEW: characterization test against committed baseline
├── test_canonical_boundary.py     # NEW: AST import/concept-literal/signature checks
├── data/canonical_baseline.json   # NEW: captured before refactor
└── test_capital_allocation.py     # MODIFY: series-builder helpers only (assertions unchanged)

notebooks/
└── 12_canonical_provider_boundary.ipynb   # NEW

docs/feature_docs/
└── feature_05_canonical_provider_boundary.md   # NEW: layering diagram + boundary rule
README.md                                       # MODIFY: short Architecture section linking to Feature 5 doc
```

**Structure Decision**: Keep the single flat `owner_lens` package. Add two flat modules: the
canonical model and the SEC adapter. FMP in Slice 5B becomes a sibling `fmp_adapter.py` that
produces the same `CanonicalFinancialHistory`. No package is moved or renamed.

## Implementation Sequencing

1. **Baseline first**: Add `test_canonical_regression.py` and capture
   `tests/data/canonical_baseline.json` from the unchanged code (research R11).
2. **Canonical model**: Add `canonical.py` and `test_canonical.py`.
3. **SEC errors**: Make the additive base-class changes in `_annual.py`, `revenue.py`, and
   `operating_income.py`. Re-export `MetricKind` from `metrics.py`.
4. **SEC adapter**: Add `sec_adapter.py` and `test_sec_adapter.py`.
5. **Downstream, in dependency order**: owner economics, then capital efficiency, then economic
   value, then compounding, then capital allocation, then economic summary, then coverage. Each
   step adds `*_from_history` and turns the existing wrapper into a delegate. Run the regression
   test after each module.
6. **Wiring**: Update the persistence adapter field read, ingestion's single-history path, and the
   `__init__` exports.
7. **Boundary and parity tests**: Add `test_canonical_boundary.py` and
   `test_canonical_downstream.py`.
8. **Docs**: Add the notebook, the Feature 5 doc, and the README section.
9. **Gates**: Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Each downstream module keeps one import of `owner_lens.sec_adapter` for its legacy `*_from_facts` wrapper. This is a documented exception to the boundary rule. | Existing callers depend on the `*_from_facts` signatures: tests, notebooks 01 through 09, and public package exports. Breaking them would violate "existing tests stay green" and widen the slice. | Moving the wrappers to a separate module would change import paths used by tests and notebooks. Deleting them now would force broad caller churn in a boundary-only slice. **Removal condition**: delete the wrappers once all callers use `*_from_history`, no later than the slice that introduces provider selection. The boundary test allows only this single import and forbids its use outside the wrappers. |

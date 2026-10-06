---
title: "Research: Canonical Provider Boundary"
description: Phase 0 decisions for OwnerLens Slice 5A, the provider-neutral canonical financial history and SEC adapter
ms.date: 2026-10-05
ms.topic: reference
---

## Context

Every downstream analytical module calls SEC normalizers directly from its `*_from_facts` entry
point. Each entry point re-normalizes the raw payload, and failures surface lazily per metric: an
ambiguous repurchases fact breaks capital allocation, but owner economics still succeeds. Coverage
and ingestion catch concept-not-found errors to classify layers, and coverage reasons are produced
by `str(exc)` and persisted. Several tests use `pytest.raises(ConceptNotFoundError)` against
wrapper entry points. These behaviors constrain the design below.

## R1. Location and shape of the canonical model

* **Decision**: Add one module, `src/owner_lens/canonical.py`, containing `CanonicalFact`,
  `CanonicalSeries`, `CanonicalFinancialHistory`, `MetricStatus`, `MetricKind`, the fixed
  17-metric vocabulary, and the canonical error hierarchy. All types are frozen dataclasses or enums.
* **Rationale**: One small module holds the whole boundary contract. A flat module avoids a package
  reorganization (constitution VI and the spec's out-of-scope rule).
* **Alternatives considered**: A `providers/` subpackage (rejected: reorganization with a single
  current consumer). Extending `metrics.py` (rejected: that module holds SEC concept preferences and
  per-company overrides, which are SEC-specific).

## R2. Canonical metric vocabulary

* **Decision**: The vocabulary is the 17 names already used by `metrics.py`, coverage, and
  persistence: `revenue`, `operating_income`, `net_income`, `operating_cash_flow`,
  `capital_expenditures`, `diluted_shares`, `income_tax_expense`, `pretax_income`, `repurchases`,
  `stock_based_compensation`, `dividends_paid`, `cash`, `short_term_investments`, `current_debt`,
  `long_term_debt`, `total_assets`, `total_equity`. Each name has a kind (duration or instant) and
  a unit (`USD` or `shares`).
* **Rationale**: These names already appear as `canonical_metric` in persisted records and as
  coverage input names, so reusing them keeps persistence and coverage output byte-identical.
  `income_tax_expense` is included because ROIC needs it.
* **Alternatives considered**: New names such as `capex` or `sbc` (rejected: would change persisted
  `canonical_metric` values and coverage keys).
* **Follow-on**: `MetricKind` moves to `canonical.py`, and `metrics.py` re-exports it so existing
  imports keep working.

## R3. Fact provenance fields

* **Decision**: `CanonicalFact` is flat: `metric`, `value`, `unit`, `fiscal_year`, `fiscal_period`,
  `period_end`, `period_start` (`None` for instant facts), `provider`, `provider_field`, `form`,
  `filed`, `accession`. In 5A, `form`, `filed`, and `accession` are required.
* **Rationale**: SEC always supplies these values, and `ReportedFactRecord` stores them as
  non-null columns. Making them optional now would generalize for a hypothetical provider
  (constitution VI) and would force a persistence change that FR-017 forbids. Slice 5B owns any
  relaxation, together with its persistence impact.
* **Rationale for `period_start = None` on instants**: The SEC primitive sets start equal to end
  for instant observations. A canonical fact should not report a start date for a point in time
  (spec edge case). Persistence already writes `period_start = None` for instant facts, so
  persisted output does not change.
* **Alternatives considered**: A nested `FactProvenance` object (rejected for 5A: adds indirection
  without a current consumer). An alias property named `concept` (rejected: it would keep SEC
  vocabulary in the canonical type).

## R4. Per-metric status and lazy failure semantics

* **Decision**: Each metric in the history is a `CanonicalSeries` with a `MetricStatus`:
  * `AVAILABLE`: the series has at least one fact.
  * `STRUCTURALLY_ABSENT`: there are no facts, and the provider judged the absence economically
    meaningful (no dividend program, no short-term investments).
  * `UNSUPPORTED`: the provider has no trusted field for this metric. The series carries a reason
    and the provider's typed error.
  * `INVALID`: the provider data for this metric was malformed or ambiguous. The series carries the
    provider's typed error.

  The SEC adapter maps every metric and catches per-metric normalization errors instead of raising
  them. Downstream code reads a series through `history.require(metric)`, which re-raises the stored
  error for `UNSUPPORTED` and `INVALID`. `history.require(metric, allow_unsupported=True)` returns an
  empty series for `UNSUPPORTED` (used for diluted shares) and still raises for `INVALID`.
* **Rationale**: This keeps today's lazy, per-layer failure behavior. Each entry point fails only
  when a metric it needs is unusable, with the same exception type and message as today. Raising
  eagerly during mapping would make owner economics fail whenever any unrelated metric is
  ambiguous, which is a behavior change.
* **Ordering rule**: Each `*_from_history` entry point requires metrics in the same order as
  today's `*_from_facts` normalizer calls. When several metrics are unusable, the error that
  surfaces first is therefore unchanged.
* **Re-raise hygiene**: Stored errors are raised with `error.with_traceback(None)`, so repeated
  access does not accumulate traceback frames.
* **Alternatives considered**: Eager failure (rejected: changes semantics). Optional values inside
  facts (rejected: it is ambiguous whether a value is absent or unsupported).

## R5. Provider-neutral error hierarchy without breaking existing `except` clauses

* **Decision**: `canonical.py` defines `CanonicalDataError` with two subclasses:
  `MetricUnsupportedError` and `MetricInvalidError`. The existing SEC error classes gain a
  canonical base class through additive multiple inheritance:
  * `_annual.ConceptNotFoundError`, `RevenueConceptNotFoundError`, and
    `OperatingIncomeConceptNotFoundError` also inherit from `MetricUnsupportedError`.
  * `_annual.AmbiguousValueError`, `_annual.MalformedFactsError`, `AmbiguousRevenueError`, and
    `AmbiguousOperatingIncomeError` also inherit from `MetricInvalidError`.

  Downstream coverage catches `MetricUnsupportedError`, the provider-neutral equivalent of today's
  `_CONCEPT_ERRORS` tuple.
* **Rationale**: Re-raised errors keep their concrete SEC type, so `pytest.raises(ConceptNotFoundError)`
  and the existing ingestion `except` tuples still match. Downstream modules catch only canonical
  types. The added base classes do not change any existing class's identity, message, or existing
  bases.
* **Alternatives considered**: Translating SEC errors into new canonical errors (rejected: breaks
  existing tests and the ingestion classification). Storing only reason strings (rejected: loses the
  typed failure that constitution V requires).

## R6. Coverage reasons containing SEC concept names

* **Decision**: Error messages stay unchanged, and coverage continues to use `str(exc)` as the layer
  reason.
* **Rationale**: Reasons are persisted as `CoverageResultRecord.reason`. FR-017 requires persisted
  output to stay unchanged. Downstream code treats the message as opaque provider provenance and
  never parses or branches on it, which satisfies FR-011.

## R7. Annual window and the capital-efficiency baseline year

* **Decision**: `CanonicalFinancialHistory` records `max_years`. The SEC adapter maps duration
  metrics with `max_years` and instant metrics with `max_years + 1`, which is exactly what
  `capital_efficiency_from_facts` does today. `capital_efficiency_from_history` uses
  `history.max_years` as `display_years`.
* **Rationale**: Ambiguity is checked only inside the window, so mapping all years would raise for
  conflicts in older years that are ignored today. Keeping the window at the adapter preserves
  current behavior exactly.
* **Coverage nuance**: Today coverage probes instant inputs with `max_years`, not `max_years + 1`.
  Metric selection does not depend on the window, so `AVAILABLE`, `STRUCTURALLY_ABSENT`, and
  `UNSUPPORTED` do not change. The only possible difference is an ambiguity in the extra baseline
  year. Today that same ambiguity already makes `company_coverage` raise, when it evaluates the
  capital-efficiency layer, with the same exception type and message. The outcome is equivalent.

## R8. Downstream entry points and compatibility wrappers

* **Decision**: Each downstream module gains a `*_from_history` entry point that accepts only a
  `CanonicalFinancialHistory`:
  * `owner_economics_from_history`
  * `capital_efficiency_from_history`
  * `economic_value_from_history`
  * `compounding_view_from_history`
  * `compounding_views_from_history`
  * `capital_allocation_from_history`
  * `economic_value_summary_from_history`
  * `company_coverage_from_history`
  * `company_output_from_history`

  Kernels keep their names: `compute_owner_economics`, `compute_capital_efficiency`,
  `build_capital_allocation_rows`, `build_economic_value_snapshots`, `build_compounding_view`, and
  `synthesize_economic_value_summary`. Their reported-input parameters change type to
  `CanonicalSeries`. Existing `*_from_facts` functions remain as thin wrappers: build the history
  with the SEC adapter, then delegate.
* **Rationale**: The `_from_history` suffix mirrors `_from_facts`, which makes call sites easy to
  migrate and avoids clashing with module names (for example `owner_economics.owner_economics`).
  Keeping the wrappers preserves every caller, including tests, notebooks 01 through 09, and
  public package exports.
* **Wrapper ticker fidelity**: `economic_value_summary_from_facts` passes the caller's literal
  `ticker` to `synthesize_economic_value_summary`, exactly as today. The `_from_history` variant
  uses `history.ticker`, which is canonical uppercase.
* **Wrapper SEC dependency (documented exception)**: A wrapper must import the SEC adapter. The
  boundary test allows exactly one SEC-side import in each downstream module:
  `from owner_lens.sec_adapter import canonical_history_from_sec`. No downstream module may import
  `_annual`, `reported`, `balance_sheet`, `revenue`, `operating_income`, `metrics`, or `sec`.
  Removal condition: the wrappers are deleted once every caller uses `*_from_history`. That is
  planned no later than the slice that makes provider selection a caller concern.

## R9. Kernel input naming and existing kernel tests

* **Decision**: `CanonicalSeries` exposes its facts as `observations: tuple[CanonicalFact, ...]`.
* **Rationale**: The owner-economics and capital-efficiency kernels read only `.observations`,
  `.fiscal_year`, and `.value`. Existing kernel tests pass SEC `AnnualSeries` objects with
  `# type: ignore[arg-type]`, so they keep passing without edits. The capital-allocation kernel
  currently infers "no dividend program" from `dividends_paid.concept == ""`, which is an SEC
  sentinel. It switches to `dividends_paid.status is MetricStatus.STRUCTURALLY_ABSENT`. Only the
  series-builder helpers in `tests/test_capital_allocation.py` migrate to `CanonicalSeries`, and
  none of its assertions change.
* **Alternatives considered**: Naming the field `facts` (rejected: forces edits to two more test
  files for naming alone).

## R10. Ingestion and persistence

* **Decision**: `ingest_company` builds the history once with `canonical_history_from_sec` and
  calls the `*_from_history` entry points. Its `_CONCEPT_ERRORS` tuple stays unchanged.
  `persistence/adapters.py` reads `CanonicalFact` and writes `concept=fact.provider_field`.
  The record types and the SQLite schema do not change.
* **Rationale**: The production path now crosses the canonical boundary, the payload is normalized
  once instead of seven times, and persisted records stay identical.
* **Out of scope**: Storing `provider` as a new column. Every fact is `sec` in 5A, and FR-017 forbids
  format changes.

## R11. Regression oracle

* **Decision**: Before changing downstream code, add a characterization test,
  `tests/test_canonical_regression.py`, with a committed baseline at
  `tests/data/canonical_baseline.json`. The baseline is captured from the current code for these
  scenarios:
  * ADBE, V, and COST fixtures.
  * An ADBE variant without `DebtCurrent`, the MSFT/CRM-style partial case.
  * An ADBE variant with a conflicting repurchases value, a lazy-ambiguity case.

  For each scenario the baseline records:
  * Persistence records produced by the pure adapters with a fixed `computed_at`: reported facts,
    derived metrics, analyses, and coverage.
  * The formatted text from each layer's `format_*` function.
  * For each layer entry point, either its result or the exception type and message it raises.
* **Rationale**: Persistence records are unchanged types that cover provenance, exact derived
  values, classifications, drivers, coverage states, and reasons. The formatted views cover
  layer-level ratios. This makes FR-015 and FR-016 mechanically verifiable. JSON stores floats with
  `repr`, so the comparison is exact.
* **Alternatives considered**: Comparing old and new paths side by side in one test run (rejected:
  the old path does not exist after refactoring).

## R12. Boundary enforcement test

* **Decision**: `tests/test_canonical_boundary.py` parses the seven downstream modules with `ast`
  and checks four things:
  1. Imports come only from the standard library, `owner_lens.canonical`, `owner_lens._trajectory`,
     the other downstream modules, and the single allowed `owner_lens.sec_adapter` import.
  2. No string literal in those modules equals an SEC concept named in any `metrics.py` definition,
     default or override.
  3. Every `*_from_history` function has a single positional parameter annotated
     `CanonicalFinancialHistory`.
  4. Each downstream output can be computed from a history built with `provider="test"` and no SEC
     payload.
* **Rationale**: Covers FR-010, FR-011, FR-019, FR-020, and SC-003 with a fast, deterministic test.

## R13. Legacy `margin.py`

* **Decision**: `margin.py` (Slice 1C `align_annual_metrics` and `operating_margins`) is left
  unchanged and outside the boundary check.
* **Rationale**: None of the seven analytical layers consumes it. It operates on SEC
  revenue and operating-income series and is effectively an SEC-side display helper superseded by
  `OwnerEconomicsRow.operating_margin`. Migrating it is not required for 5A. A follow-up note goes in
  the Feature 5 documentation.

## R14. Notebook and documentation

* **Decision**: Add `notebooks/12_canonical_provider_boundary.ipynb`. Like notebooks 01 through 09,
  it retrieves ADBE with `SecClient` and `SEC_USER_AGENT`, and it prints the CIK and payload content
  hash as retrieval context. It shows:
  * Raw SEC facts for one concept.
  * The resulting canonical facts with provenance.
  * Metric statuses for ADBE and V.
  * `owner_economics_from_history` output.
  * A synthetic non-SEC history producing the same economics.

  Add `docs/feature_docs/feature_05_canonical_provider_boundary.md` with the
  providers → canonical facts → deterministic logic diagram and the boundary rule. Add a short
  Architecture section to `README.md` that links to it.
* **Rationale**: Follows the existing notebook convention and the constitution's notebook and
  documentation gates.

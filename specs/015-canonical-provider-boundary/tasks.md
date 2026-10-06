---
description: "Task list for Canonical Provider Boundary (OwnerLens Slice 5A)"
---

# Tasks: Canonical Provider Boundary

**Input**: Design documents from `specs/015-canonical-provider-boundary/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Tasks include tests because spec section 8 and FR-018 through FR-021 require them: SEC
to canonical mapping, provenance, downstream parity, golden-company equivalence, semantics for
partial, unsupported, and insufficient data, and the boundary check.

**Organization**: Tasks are grouped by user story. US1 and US2 are both P1; US2 depends on the
US1 adapter for SEC parity checks, but its synthetic-history tests do not.

## Format: `[ID] [P?] [Story] Description`

* **[P]**: Can run in parallel because it touches different files and has no dependency on an
  incomplete task.
* **[Story]**: US1 to US4, mapping to the prioritized user stories in spec.md.
* Every task names an exact file path.

## Invariants every task must respect

* **No semantic change**: Do not alter FCF, FCF per share, ROIC, margins, growth,
  capital-allocation rules, thresholds, classifications, coverage semantics, or persisted record
  formats (FR-014 to FR-017).
* **Do not edit SEC normalization rules**: Changes to `_annual.py`, `revenue.py`,
  `operating_income.py`, and `metrics.py` are additive only (research R5, R2).
* **Lazy per-metric failure**: The adapter stores errors per metric. Downstream code re-raises the
  stored error object only when it requires that metric. It requires metrics in today's
  normalizer-call order (research R4,
  [downstream-entry-points.md](contracts/downstream-entry-points.md)).
* **Existing test assertions are never edited**: The only allowed test edit is migrating the
  series-builder helpers in `tests/test_capital_allocation.py` (research R9).
* **Regression baseline**: Run `uv run pytest tests/test_canonical_regression.py` after every
  downstream-module task. It must stay green.

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`,
docs in `docs/feature_docs/`. Tests import fixtures with `from _fixtures import ...`.

---

## Phase 1: Setup (Regression Baseline)

**Purpose**: Freeze today's SEC-derived behavior as the regression oracle **before** changing any
source module (research R11).

- [X] T001 Create `tests/test_canonical_regression.py` with:
  * Scenario builders for ADBE (`adbe_facts`), V (`visa_facts`), and COST (`costco_facts`).
  * `adbe_without_current_debt`: delete `facts["facts"]["us-gaap"]["DebtCurrent"]`, the
    MSFT/CRM-style case.
  * `adbe_ambiguous_repurchases`: add a second FY repurchases fact for the latest year with a
    different `val` and a later `filed` date.

  For each scenario, `capture(raw_facts, ticker) -> dict` records:
  * Each entry point (`owner_economics_from_facts`, `capital_efficiency_from_facts`,
    `economic_value_from_facts`, `compounding_views_from_facts`, `capital_allocation_from_facts`,
    `economic_value_summary_from_facts`, `company_coverage`) as either `{"ok": ...}` or
    `{"error": [type(exc).__name__, str(exc)]}`.
  * Records from `owner_lens.persistence.adapters`: `reported_fact_records`,
    `derived_metric_records`, `analysis_result_records`, and `coverage_result_records`. Use
    `cik="0000000000"` and `computed_at="2026-01-01T00:00:00+00:00"`, and serialize them with
    `dataclasses.asdict`.
  * Formatted strings from `format_economic_value_view`, `format_compounding_view`,
    `format_capital_allocation_view`, `format_economic_value_summary`, `format_coverage_report`,
    and `company_output`, where computable.

  Serialize enums as `.value` and dates with `isoformat()`. Add
  `if __name__ == "__main__" and "--update-baseline" in sys.argv` to write
  `tests/data/canonical_baseline.json` (sorted keys, indent 2). The test function loads the JSON
  and asserts `capture(...) == baseline[scenario]` for every scenario.
- [X] T002 Create `tests/data/` and generate `tests/data/canonical_baseline.json` by running
  `uv run python tests/test_canonical_regression.py --update-baseline` on the **unmodified**
  source.
- [X] T003 Run `uv run pytest` and confirm the full existing suite plus
  `tests/test_canonical_regression.py` pass on unmodified source. Record the pass count in the
  T050 completion notes.

**Checkpoint**: Baseline committed. Every later task must keep it green.

---

## Phase 2: Foundational (Canonical Model and Error Bases)

**Purpose**: The provider-neutral types every story consumes. No story can start until this phase
is complete.

- [X] T004 Create `src/owner_lens/canonical.py` per [data-model.md](data-model.md) and
  [canonical-model.md](contracts/canonical-model.md). It must import nothing from `owner_lens`.
  Contents:
  * `MetricKind` (`DURATION`, `INSTANT`).
  * `CanonicalMetricSpec(name, kind, unit)`.
  * `CANONICAL_METRICS`: the 17 metrics in vocabulary order.
  * `metric_spec(name)`.
  * `MetricStatus`: `AVAILABLE`, `STRUCTURALLY_ABSENT`, `UNSUPPORTED`, `INVALID`.
  * `CanonicalDataError`, `MetricUnsupportedError`, `MetricInvalidError`.
- [X] T005 Add the frozen dataclass `CanonicalFact` to `src/owner_lens/canonical.py`. Its
  `__post_init__` validation covers: vocabulary membership, unit equal to the spec's unit,
  `period_start` required and earlier than `period_end` for duration metrics, `period_start is None`
  for instant metrics, and non-empty `provider` and `provider_field`.
- [X] T006 Add the frozen dataclass `CanonicalSeries(metric, unit, status, observations=(),
  reason=None, error=None)` to `src/owner_lens/canonical.py`. Validation:
  * Every observation's metric matches the series metric.
  * Fiscal years are unique and in descending order.
  * Status invariants: `AVAILABLE` has at least one fact. Every other status has none.
    `UNSUPPORTED` requires a reason. `INVALID` requires a reason and an error. `AVAILABLE` and
    `STRUCTURALLY_ABSENT` have `error is None`.
- [X] T007 Add the frozen dataclass `CanonicalFinancialHistory(ticker, max_years, series)` to
  `src/owner_lens/canonical.py`. It includes:
  * Validation: non-empty uppercase ticker, `max_years >= 1`, and exactly one series per
    vocabulary metric in vocabulary order.
  * `series_for`, `statuses`, and `providers`.
  * `require(metric, *, allow_unsupported=False)`. It raises
    `stored_error.with_traceback(None)` for `INVALID`. For `UNSUPPORTED` it raises the stored error,
    or `MetricUnsupportedError(reason)` when none is stored; with `allow_unsupported=True` it
    returns the empty series instead.
  * The classmethod `build(*, ticker, max_years, facts, structurally_absent=(), unsupported=None)`.
    It sorts facts newest first and raises `ValueError` for any metric with no facts that is not
    declared absent or unsupported.
- [X] T008 [P] Create `tests/test_canonical.py` covering:
  * Each `CanonicalFact` validation failure.
  * The duration-versus-instant `period_start` rule.
  * `CanonicalSeries` status invariants.
  * History completeness and ordering validation.
  * `require` for every status, including `allow_unsupported`.
  * The identity of a re-raised stored error (`exc is stored`) and its unchanged message.
  * `build()` rejecting an undeclared metric with no facts.
  * `providers()`.
  * Frozen instances (assigning a field raises `FrozenInstanceError`).
- [X] T009 [P] In `src/owner_lens/_annual.py`, additively add canonical bases. Do not change
  messages, names, or the existing base `AnnualNormalizationError`.
  * `ConceptNotFoundError(AnnualNormalizationError, MetricUnsupportedError)`
  * `AmbiguousValueError(AnnualNormalizationError, MetricInvalidError)`
  * `MalformedFactsError(AnnualNormalizationError, MetricInvalidError)`
- [X] T010 [P] In `src/owner_lens/revenue.py`, additively add canonical bases:
  `RevenueConceptNotFoundError(RevenueNormalizationError, MetricUnsupportedError)` and
  `AmbiguousRevenueError(RevenueNormalizationError, MetricInvalidError)`.
- [X] T011 [P] In `src/owner_lens/operating_income.py`, additively add canonical bases:
  `OperatingIncomeConceptNotFoundError(..., MetricUnsupportedError)` and
  `AmbiguousOperatingIncomeError(..., MetricInvalidError)`.
- [X] T012 [P] In `src/owner_lens/metrics.py`, replace the local `MetricKind` enum with
  `from owner_lens.canonical import MetricKind`, keep it in `__all__`, and confirm that
  `MetricKind.DURATION.value == "duration"` still holds.
- [X] T013 Run `uv run pytest tests/test_canonical.py tests/test_metrics.py tests/test_revenue.py
  tests/test_operating_income.py tests/test_reported.py tests/test_balance_sheet.py
  tests/test_canonical_regression.py` and `uv run mypy src`. All must pass.

**Checkpoint**: The canonical model exists, the SEC errors are catchable as canonical errors, and
nothing downstream has changed yet.

---

## Phase 3: User Story 1 - SEC facts become a canonical financial history (Priority: P1) 🎯 MVP

**Goal**: `canonical_history_from_sec` converts raw Company Facts into a complete, provenance-rich
`CanonicalFinancialHistory` with per-metric status, reusing the SEC normalizers unchanged.

**Independent Test**: Map the ADBE, V, and COST fixtures. Every canonical fact must equal the SEC
normalizer observation for the same metric and year, including its provenance. Statuses and lazy
errors must match the spec.

### Tests for User Story 1

- [X] T014 [P] [US1] Create `tests/test_sec_adapter.py`. For ADBE, V, and COST, assert that every
  `AVAILABLE` metric's facts equal the matching normalizer output field by field: `value`, `unit`,
  `fiscal_year`, `fiscal_period`, `period_end`, `form`, `filed`, `accession`, and
  `provider_field == obs.concept`. Also assert `provider == "sec"`, and that `period_start` equals
  `obs.period_start` for duration metrics and is `None` for instant metrics. Use the same windows
  as the adapter: `max_years` for duration metrics, `max_years + 1` for instant metrics.
- [X] T015 [P] [US1] In `tests/test_sec_adapter.py`, add status and provenance tests:
  * ADBE revenue FY2025 has `provider_field` equal to the concept the revenue normalizer selected,
    and the matching accession.
  * V `diluted_shares` is `UNSUPPORTED`; its `error` is a `ConceptNotFoundError` and its reason is
    `str(error)`.
  * ADBE `dividends_paid` and V `short_term_investments` are `STRUCTURALLY_ABSENT`.
  * V `current_debt` and `long_term_debt` have `provider_field` values `LongTermDebtCurrent` and
    `LongTermDebtNoncurrent`.
  * `history.max_years == 5`, and instant series hold up to 6 years.
- [X] T016 [P] [US1] In `tests/test_sec_adapter.py`, add failure-semantics tests:
  * Ambiguous repurchases makes `repurchases` `INVALID`. Mapping does not raise, and
    `require("repurchases")` raises `AmbiguousValueError` with the normalizer's exact message.
  * A payload with no `us-gaap` makes every metric `INVALID` with `MalformedFactsError`.
  * An empty ticker raises `ValueError` eagerly.
  * `raw_facts` is not mutated (compare with a `copy.deepcopy` taken before mapping).

### Implementation for User Story 1

- [X] T017 [US1] Create `src/owner_lens/sec_adapter.py` per [sec-adapter.md](contracts/sec-adapter.md)
  and the SEC mapping table in [data-model.md](data-model.md). It defines:
  * `SEC_PROVIDER = "sec"`.
  * An ordered mapping table of `(metric, normalizer, window_offset)` in vocabulary order. The
    window offset is 0 for duration metrics and 1 for instant metrics.
  * `_to_fact(metric, kind, obs) -> CanonicalFact`.
  * `canonical_history_from_sec(raw_facts, *, ticker=DEFAULT_TICKER, max_years=DEFAULT_MAX_YEARS)`,
    which calls `canonicalize_ticker` first.

  For each metric, map the normalizer result to a status:
  * Observations present: `AVAILABLE`.
  * An empty series from a tolerant normalizer: `STRUCTURALLY_ABSENT`.
  * `ConceptNotFoundError`, `RevenueConceptNotFoundError`, or
    `OperatingIncomeConceptNotFoundError`: `UNSUPPORTED`, with `reason=str(exc)` and `error=exc`.
  * `AmbiguousValueError`, `AmbiguousRevenueError`, `AmbiguousOperatingIncomeError`, or
    `MalformedFactsError`: `INVALID`, with `reason=str(exc)` and `error=exc`.
- [X] T018 [US1] Run `uv run pytest tests/test_sec_adapter.py tests/test_canonical_regression.py`
  and `uv run mypy src`. All must pass.

**Checkpoint**: SEC data now crosses into canonical form with intact provenance. Downstream code is
still untouched, which makes this a demonstrable MVP.

---

## Phase 4: User Story 2 - Feature 1 calculations consume canonical history (Priority: P1)

**Goal**: Owner economics and capital efficiency are computed from `CanonicalFinancialHistory`.
Their `*_from_facts` functions become thin wrappers, and persisted facts stay identical.

**Independent Test**: A synthetic history with `provider="test"` and no SEC payload yields
hand-calculated FCF, FCF per share, margins, growth, and ROIC. The ADBE, V, and COST canonical
path equals the baseline.

### Tests for User Story 2

- [X] T019 [P] [US2] Create `tests/test_canonical_downstream.py` with a helper
  `synthetic_history()` built with `CanonicalFinancialHistory.build(...)` from `CanonicalFact`s whose
  `provider="test"` (provider fields such as `"test.revenue"`). It holds two fiscal years (2024 and 2025) of every
  duration metric and three year-ends (2023 to 2025) of every instant metric. Use round numbers so
  FCF, FCF per share, operating, net, and FCF margins, FCF growth, effective tax rate, NOPAT,
  invested capital, and ROIC can be computed by hand. Mark `dividends_paid` as structurally absent.
- [X] T020 [P] [US2] In `tests/test_canonical_downstream.py`, add these tests:
  * `owner_economics_from_history(synthetic_history())` returns the hand-computed values.
  * The returned row facts carry `provider == "test"`.
  * Marking `diluted_shares` unsupported yields `fcf_per_share is None` while all other metrics are
    still derived.
  * `capital_efficiency_from_history(synthetic_history())` returns the hand-computed ROIC and
    supporting values.
  * Marking `current_debt` unsupported raises `MetricUnsupportedError`.
- [X] T021 [P] [US2] In `tests/test_canonical_downstream.py`, add parity tests for ADBE, V, and
  COST: `owner_economics_from_history(canonical_history_from_sec(f, ticker=t))` equals
  `owner_economics_from_facts(f, ticker=t)`, and likewise for capital efficiency. Compare with `==`
  on row tuples.

### Implementation for User Story 2

- [X] T022 [US2] Refactor `src/owner_lens/owner_economics.py`:
  * Remove the imports from `_annual`, `reported`, `revenue`, and `operating_income`.
  * Retype the `OwnerEconomicsRow` fact fields to `CanonicalFact | None`.
  * Retype the `compute_owner_economics` series parameters to `CanonicalSeries`, leaving the body's
    arithmetic unchanged.
  * Add `owner_economics_from_history(history)`. It requires `diluted_shares` with
    `allow_unsupported=True`, then requires `revenue`, `operating_income`, `net_income`,
    `operating_cash_flow`, and `capital_expenditures`, in that order.
  * Rewrite `owner_economics_from_facts` as
    `owner_economics_from_history(canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years))`.
  * Update the module docstring and `__all__`.
- [X] T023 [US2] Refactor `src/owner_lens/capital_efficiency.py`:
  * Remove the imports from `_annual`, `balance_sheet`, `operating_income`, and `reported`.
  * Retype the `CapitalEfficiencyRow` fact fields to `CanonicalFact | None`.
  * Retype the `compute_capital_efficiency` series parameters to `CanonicalSeries`.
  * Add `capital_efficiency_from_history(history)`. It requires `operating_income`, `net_income`,
    `income_tax_expense`, `pretax_income`, `cash`, `short_term_investments`, `current_debt`,
    `long_term_debt`, `total_assets`, and `total_equity`, in that order, and passes
    `display_years=history.max_years`.
  * Rewrite `capital_efficiency_from_facts` as a delegate wrapper.
  * Update `__all__`.
- [X] T024 [US2] Update `src/owner_lens/persistence/adapters.py`. Replace the `AnnualObservation`
  import with `CanonicalFact`, and in `_fact_record` set `concept=fact.provider_field`. Keep
  `period_start` as `None` for instant facts, and leave the record fields unchanged.
- [X] T025 [US2] Run `uv run pytest tests/test_owner_economics.py tests/test_capital_efficiency.py
  tests/test_persistence.py tests/test_canonical_downstream.py tests/test_canonical_regression.py`
  and `uv run mypy src`. All must pass, with no edits to existing assertions.

**Checkpoint**: Feature 1 runs on canonical history, and persisted provenance is byte-identical.

---

## Phase 5: User Story 3 - Feature 2 layers and coverage consume canonical history (Priority: P2)

**Goal**: Economic value, compounding, capital allocation, the economic summary, coverage, and
ingestion all run on canonical history. No downstream module depends on SEC code, apart from the
documented wrapper import.

**Independent Test**: For every regression scenario, Feature 2 classifications, drivers, and
coverage states equal the baseline, and the AST boundary test passes.

### Tests for User Story 3

- [X] T026 [P] [US3] In `tests/test_canonical_downstream.py`, add parity tests for ADBE, V, and
  COST covering `economic_value_from_history`, `compounding_views_from_history`,
  `capital_allocation_from_history`, `economic_value_summary_from_history`, and
  `company_coverage_from_history`. Each must equal the matching `*_from_facts` or
  `company_coverage` result.
- [X] T027 [P] [US3] In `tests/test_canonical_downstream.py`, add synthetic-history Feature 2
  tests:
  * `capital_allocation_from_history` treats a structurally absent `dividends_paid` as "no dividend
    program" (effective dividends 0, `capital_returned == repurchases`).
  * `company_coverage_from_history` maps statuses to `MetricCoverage` one-to-one.
  * An unsupported `diluted_shares` gives an `owner_economics` layer of `PARTIAL` with the
    diluted-shares reason.
  * An `INVALID` metric makes `company_coverage_from_history` raise the stored error.
- [X] T028 [P] [US3] Create `tests/test_canonical_boundary.py`. Use `ast` to parse
  `owner_economics.py`, `capital_efficiency.py`, `economic_value.py`, `compounding.py`,
  `capital_allocation.py`, `economic_summary.py`, and `coverage.py` under `src/owner_lens/`, then
  assert:
  1. Only these `owner_lens` imports appear: `canonical`, `_trajectory`, the seven downstream
     modules, and exactly `from owner_lens.sec_adapter import canonical_history_from_sec`.
  2. `canonical_history_from_sec` is referenced only inside functions whose names end in
     `_from_facts` or are `company_coverage` or `company_output`.
  3. No string constant equals any concept in any `metrics.py` definition, including
     `default_concepts` and every `overrides` value. Collect these by iterating the module's
     `CanonicalMetricDefinition` instances.
  4. Each `*_from_history` function's first parameter is annotated `CanonicalFinancialHistory`.

### Implementation for User Story 3

- [X] T029 [US3] Refactor `src/owner_lens/economic_value.py`:
  * Add `economic_value_from_history(history, *, thresholds=DEFAULT_THRESHOLDS)`, which calls
    `owner_economics_from_history`, then `capital_efficiency_from_history`, then
    `build_economic_value_snapshots`.
  * Make `economic_value_from_facts` a delegate wrapper.
  * Update `__all__`.
- [X] T030 [US3] Refactor `src/owner_lens/compounding.py`:
  * Add `compounding_view_from_history(history, *, period_years, thresholds=...)` and
    `compounding_views_from_history(history, *, thresholds=...)`. Compute owner rows, then capital
    rows, then snapshots from history, preserving the existing recent and long-term period
    selection logic.
  * Make both `*_from_facts` functions delegate wrappers.
  * Update `__all__`.
- [X] T031 [US3] Refactor `src/owner_lens/capital_allocation.py`:
  * Remove the `reported` import.
  * Retype `build_capital_allocation_rows` so `repurchases`, `stock_based_compensation`, and
    `dividends_paid` are `CanonicalSeries`. `_by_year_value` reads `.observations`.
  * Replace `no_dividend_program = dividends_paid.concept == "" and not dividends_paid.observations`
    with `no_dividend_program = dividends_paid.status is MetricStatus.STRUCTURALLY_ABSENT`.
  * Add `capital_allocation_from_history(history, *, thresholds=...)`. It computes owner,
    capital, and snapshots, then requires `repurchases`, `stock_based_compensation`, and
    `dividends_paid`, in that order.
  * Make `capital_allocation_from_facts` a delegate wrapper.
  * Update `__all__`.
- [X] T032 [US3] Migrate only the series-builder helpers in `tests/test_capital_allocation.py`,
  around the current `AnnualObservation` and `AnnualSeries` builders near lines 30 to 60:
  * Build `CanonicalFact` and `CanonicalSeries` with the same values.
  * A helper that previously used `concept=""` with no observations now builds a
    `STRUCTURALLY_ABSENT` series.
  * Remove the `_annual` and `reported` imports if they become unused.
  * Do not change any assertion or expected value.
- [X] T033 [US3] Refactor `src/owner_lens/economic_summary.py`:
  * Add `economic_value_summary_from_history(history, *, thresholds=...)`. It builds snapshots,
    then compounding views, then capital-allocation rows from history, and calls
    `synthesize_economic_value_summary(history.ticker, ...)`.
  * Rewrite `economic_value_summary_from_facts` to build the history once, compute the same
    components with the `*_from_history` functions, and call
    `synthesize_economic_value_summary(ticker, ...)` with the caller's literal ticker.
  * Update `__all__`.
- [X] T034 [US3] Refactor `src/owner_lens/coverage.py`:
  * Remove all SEC imports.
  * Replace `_INPUTS`/`_probe_input` with status mapping over `history.statuses()`, in vocabulary
    order. `INVALID` is handled by calling `history.require(metric)`, which re-raises.
  * Replace `_CONCEPT_ERRORS` with `MetricUnsupportedError`.
  * Add `company_coverage_from_history(history)`. Its layer probes call the `*_from_history`
    functions in the existing `LAYER_ORDER` and keep the reason, `blocking_input`, and
    PARTIAL/INSUFFICIENT_DATA rules unchanged.
  * Add `company_output_from_history(coverage, history)`.
  * Keep `company_coverage(raw_facts, *, ticker, max_years)` and `company_output(...)` as delegate
    wrappers. `company_output` must render the summary with the caller's literal ticker, for
    example by using `economic_value_summary_from_facts`.
- [X] T035 [US3] Update `src/owner_lens/ingestion.py` so that, after raw-first persistence, it
  builds `history = canonical_history_from_sec(raw_facts, ticker=resolved_ticker,
  max_years=max_years)` once and calls the `*_from_history` functions in the same order. Keep the
  existing `_CONCEPT_ERRORS` tuple and the per-branch `try`/`except` degradation unchanged.
- [X] T036 [US3] Update `src/owner_lens/__init__.py` to export:
  * `CanonicalFact`, `CanonicalSeries`, `CanonicalFinancialHistory`, `MetricStatus`,
    `CanonicalDataError`, `MetricUnsupportedError`, `MetricInvalidError`, and `CANONICAL_METRICS`.
  * `canonical_history_from_sec` and `SEC_PROVIDER`.
  * Every `*_from_history` function.

  Preserve all existing exports.
- [X] T037 [US3] Run `uv run pytest tests/test_economic_value.py tests/test_compounding.py
  tests/test_capital_allocation.py tests/test_economic_summary.py tests/test_coverage.py
  tests/test_ingestion.py tests/test_canonical_downstream.py tests/test_canonical_boundary.py
  tests/test_canonical_regression.py` and `uv run mypy src`. All must pass.

**Checkpoint**: The whole downstream stack is provider-neutral and verified against the baseline
and the boundary test.

---

## Phase 6: User Story 4 - Learn the boundary from a notebook and docs (Priority: P3)

**Goal**: Readers can see SEC raw facts become canonical facts and then OwnerLens economics, and
can read the layered architecture.

**Independent Test**: The notebook runs top to bottom and prints the retrieval context. The docs
contain the providers → canonical facts → OwnerLens deterministic logic diagram.

- [X] T038 [P] [US4] Create `notebooks/12_canonical_provider_boundary.ipynb` following the setup of
  notebooks 08 and 09 (`SecClient(USER_AGENT)` from the `SEC_USER_AGENT` env or `load_settings`).
  Sections:
  1. Retrieve ADBE and print the CIK and `compute_content_hash` of the payload.
  2. Show raw annual FY facts for the selected revenue concept.
  3. Build `canonical_history_from_sec` and tabulate revenue canonical facts: metric, fiscal year,
     value, provider, provider field, form, filed date, accession.
  4. Show the metric status table for ADBE and for V (retrieve V too).
  5. Show `owner_economics_from_history` output.
  6. Build a synthetic `provider="test"` history and show owner economics computed with no SEC
     data.
  7. Write a short closing markdown note on the boundary rule and the Slice 5B outlook.
- [X] T039 [P] [US4] Create `docs/feature_docs/feature_05_canonical_provider_boundary.md` with:
  * Purpose.
  * The layered diagram (providers, then the SEC adapter, then `CanonicalFinancialHistory`, then
    the deterministic OwnerLens logic).
  * The canonical vocabulary and statuses.
  * Provenance fields.
  * Lazy failure semantics.
  * The boundary rule and its enforcement test.
  * The compatibility-wrapper exception and its removal condition.
  * The `margin.py` follow-up note (research R13).
  * What 5A deliberately did not build.
  * The Slice 5B outlook.

  Follow the style of the existing feature docs.
- [X] T040 [P] [US4] Add a short `## Architecture` section to `README.md` with the
  providers → canonical facts → OwnerLens deterministic logic diagram and a link to
  `docs/feature_docs/feature_05_canonical_provider_boundary.md`.
- [X] T041 [US4] Execute `notebooks/12_canonical_provider_boundary.ipynb` end to end with
  `SEC_USER_AGENT` set, confirm every cell runs without error, and save the outputs.

**Checkpoint**: The educational and architecture artifacts are complete.

---

## Phase 7: Polish and Cross-Cutting Concerns

- [X] T042 [P] Review the docstrings of the seven downstream modules for stale "normalize from
  payload" wording, and state that the `*_from_facts` functions are compatibility wrappers. Files:
  `src/owner_lens/owner_economics.py`, `capital_efficiency.py`, `economic_value.py`,
  `compounding.py`, `capital_allocation.py`, `economic_summary.py`, `coverage.py`.
- [X] T043 [P] Confirm that `src/owner_lens/canonical.py` and `src/owner_lens/sec_adapter.py` have
  module docstrings that explain the boundary and the R4 lazy-failure rationale, with no
  unnecessary comments.
- [X] T044 Run `uv run ruff check .` and fix any findings in the touched files.
- [X] T045 Run `uv run mypy src` and fix any findings without `type: ignore` in `src`.
- [X] T046 Run the full `uv run pytest`. Every pre-existing test plus the five new test modules
  must pass, and the pass count must be at least the T003 count plus the new tests.
- [X] T047 Run `git --no-pager diff --stat -- tests/` and confirm that the only modified
  pre-existing test file is `tests/test_capital_allocation.py`, with helper-only changes.
- [X] T048 Walk through every step of [quickstart.md](quickstart.md), adjusting commands if the
  implementation differs. Step 7 (live ingest) is optional.
- [X] T049 [P] Optionally run notebooks 02 through 06 and 08 to confirm that the
  `*_from_facts` wrappers keep them working unchanged.
- [X] T050 Update the spec status in `specs/015-canonical-provider-boundary/spec.md` to
  `Implemented` and record the gate results (pytest count, ruff, mypy) in the completion notes.

---

## Dependencies and Execution Order

### Phase dependencies

* **Setup (Phase 1)**: No dependencies. Must finish before any `src` change.
* **Foundational (Phase 2)**: Depends on Phase 1. Blocks all user stories.
* **US1 (Phase 3)**: Depends on Phase 2.
* **US2 (Phase 4)**: Depends on Phase 2 for synthetic tests (T019 and T020). The parity tests and
  wrappers (T021 to T023) depend on US1's T017.
* **US3 (Phase 5)**: Depends on US2, because Feature 2 layers compose owner economics and capital
  efficiency.
* **US4 (Phase 6)**: Depends on US1 and US2, which the notebook uses. The docs (T039, T040) can
  start after Phase 2.
* **Polish (Phase 7)**: Depends on all stories.

### Within-story order

* Write the tests first. They fail until implementation lands, except for the regression baseline,
  which must stay green throughout.
* Within US3, refactor in strict dependency order: T029, T030, T031 and T032 together, T033,
  T034, T035, then T036.

### Parallel opportunities

* T008 to T012 touch different files and can run in parallel after T004 to T007.
* T014 to T016 in US1 share one file, so write them together. They can run in parallel with T017.
* T019 to T021 in US2 can run in parallel with T022 and T023 (different files).
* T026 to T028 in US3 can run in parallel with each other and with T029.
* T038 to T040 in US4 can all run in parallel.
* T042, T043, and T049 in Polish can run in parallel.

### Parallel example: User Story 3

```text
Task: "T026 parity tests in tests/test_canonical_downstream.py"
Task: "T028 AST boundary test in tests/test_canonical_boundary.py"
Task: "T029 economic_value_from_history in src/owner_lens/economic_value.py"
```

## Implementation Strategy

### MVP (User Story 1)

Phases 1 to 3 freeze the baseline, add the canonical model, and map SEC data into canonical
history with provenance. Nothing downstream changes yet, so the risk is minimal. Validate with
`tests/test_sec_adapter.py`.

### Incremental delivery

1. Complete US1 (MVP). The canonical history is demonstrable.
2. Complete US2. Feature 1 runs on canonical history, and persistence is unchanged.
3. Complete US3. All of Feature 2, coverage, and ingestion run on canonical history, and the
   boundary is enforced.
4. Complete US4. The notebook and architecture docs are in place.
5. Polish and run all gates.

### Rollback safety

Each downstream module refactor is isolated and verified against the baseline before the next one
begins. If the baseline diverges, revert that module only and investigate before continuing
(constitution I: differences must be explained, not dismissed).

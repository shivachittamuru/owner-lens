# Feature 5 — Provider Boundary

## Purpose

Through Feature 4, every OwnerLens analytical layer read raw SEC Company Facts directly. Owner economics, capital efficiency, capital allocation, economic value, compounding, the summary, and coverage each called SEC normalizers and resolved XBRL concepts themselves.

That coupling blocks a second data provider. Feature 5 separates **where facts come from** from **what OwnerLens does with them**.

---

# Slice 5A — Canonical Provider Boundary

## Goal

Decouple all downstream OwnerLens financial logic from raw SEC Company Facts without changing a single economic definition.

```text
providers (SEC today; FMP in Slice 5B)
   ↓  provider adapter / mapper
CanonicalFinancialHistory
   (provider-neutral facts + provenance + per-metric status)
   ↓
OwnerLens deterministic logic
   (owner economics, capital efficiency, Feature 2, coverage)
```

## The boundary rule

> Downstream OwnerLens financial logic must not depend on SEC XBRL concept names or raw SEC JSON.

SEC-specific knowledge lives **above** the canonical boundary:

- concept preference orders and per-company overrides (`metrics.py`),
- full-year and fiscal-year-end instant selection, comparative deduplication, and ambiguity detection (`_annual.py` and the SEC normalizers),
- the mapping from SEC observations to canonical facts (`sec_adapter.py`).

Everything below the boundary consumes only `owner_lens.canonical`.

The rule is enforced by `tests/test_canonical_boundary.py`, an AST check over the seven analytical modules. It fails if a module imports an SEC module, contains an SEC concept string, or exposes a `*_from_history` entry point that accepts anything other than a canonical history.

---

## Canonical model

`src/owner_lens/canonical.py` is small and immutable.

### Vocabulary

Seventeen metrics, exactly those OwnerLens already consumes:

```text
duration: revenue, operating_income, net_income, operating_cash_flow,
          capital_expenditures, diluted_shares, income_tax_expense,
          pretax_income, repurchases, stock_based_compensation, dividends_paid
instant:  cash, short_term_investments, current_debt, long_term_debt,
          total_assets, total_equity
```

These names already appear in persisted records and coverage reports, so persistence output stays byte-identical. No generic accounting schema was introduced.

### CanonicalFact

One reported annual value with its provenance:

```text
metric:          revenue
value:           23,769,000,000
unit:            USD
fiscal_year:     2025
period:          2024-11-30 → 2025-11-28
provider:        sec
provider_field:  Revenues
form / filed:    10-K / 2026-01-15
accession:       0000796343-26-000003
```

The metric name is OwnerLens vocabulary. The SEC concept survives only as provenance in `provider_field`. Instant facts carry no fabricated period start.

### Metric status

Every metric in a history carries an explicit status:

| Status                | Meaning                                                  |
|-----------------------|----------------------------------------------------------|
| `AVAILABLE`           | Trusted canonical facts exist                            |
| `STRUCTURALLY_ABSENT` | Absence is economically meaningful (no dividend program) |
| `UNSUPPORTED`         | No trusted provider field (Visa diluted shares)          |
| `INVALID`             | Provider data is malformed or ambiguous                  |

These extend the Feature 3 missing-data semantic model unchanged: absence is never coerced to zero.

### Lazy failure

Provider failures are **stored on the metric**, not raised during mapping. A calculation fails only when it *requires* an unusable metric, and it raises the provider's original typed error with its original message.

This preserves an important existing behavior: an ambiguous repurchases fact blocks capital allocation and the summary, while owner economics, capital efficiency, economic value, and compounding still succeed.

---

## SEC as a provider adapter

`canonical_history_from_sec(raw_facts, *, ticker, max_years)` reuses every SEC normalizer unchanged and emits a complete `CanonicalFinancialHistory`.

- Duration metrics use the requested `max_years` window.
- Instant metrics carry one extra fiscal-year-end, the baseline capital efficiency has always used for average-balance denominators.
- Concept-not-found becomes `UNSUPPORTED`; ambiguity or malformed data becomes `INVALID`; tolerant absences (dividends, short-term investments) become `STRUCTURALLY_ABSENT`.

The existing SEC error classes gained canonical base classes (`MetricUnsupportedError`, `MetricInvalidError`) additively, so existing `except` clauses and tests keep working while downstream code catches only canonical types.

---

## Downstream entry points

Each analytical module gained a `*_from_history` entry point:

```text
owner_economics_from_history(history)
capital_efficiency_from_history(history)
economic_value_from_history(history)
compounding_view_from_history(history, period_years=...)
compounding_views_from_history(history)
capital_allocation_from_history(history)
economic_value_summary_from_history(history)
company_coverage_from_history(history)
company_output_from_history(coverage, history)
```

Ingestion now maps the SEC payload **once** and runs every layer from the same canonical history.

### Compatibility wrappers

The original `*_from_facts` functions (and `company_coverage` / `company_output`) remain as thin wrappers: SEC payload → `canonical_history_from_sec` → `*_from_history`. They keep notebooks 01–09 and existing callers working.

> [!NOTE]
> The wrappers are a documented, temporary exception to the boundary rule: each downstream module may import exactly one SEC-side symbol, `canonical_history_from_sec`, and only wrapper functions may use it. Remove the wrappers once all callers use `*_from_history`, no later than the slice that introduces provider selection.

---

## Preserving the SEC baseline

Before any downstream module changed, a characterization baseline (`tests/data/canonical_baseline.json`) recorded today's outputs for ADBE, V, COST, an ADBE variant without current debt (the MSFT/CRM pattern), and an ADBE variant with an ambiguous repurchases restatement. For each scenario it records:

- every layer's result, or its exception type and message,
- every persistence record (reported facts with provenance, derived metrics, analyses, coverage),
- every formatted view.

The refactored code reproduces it exactly. Additional tests prove:

- SEC → canonical facts equal the SEC normalizer observations field by field,
- provenance survives mapping,
- every `*_from_history` entry point matches its legacy wrapper for the golden companies,
- a synthetic history with `provider="test"` and no SEC payload produces hand-calculated owner economics, ROIC, capital allocation, and coverage.

---

## Educational Notebook

Slice 5A added:

- `12_canonical_provider_boundary.ipynb`

It walks ADBE from raw SEC facts → canonical facts with provenance → owner economics, compares ADBE and Visa metric statuses, and computes the same economics from a hand-built non-SEC history.

---

## Known follow-up

`margin.py` (the Slice 1C `align_annual_metrics` / `operating_margins` helper) still operates on SEC revenue and operating-income series. No analytical layer consumes it, and `OwnerEconomicsRow.operating_margin` supersedes it, so it was left unchanged and outside the boundary check. Migrate or retire it in a later slice.

---

## What Slice 5A Deliberately Did Not Build

- FMP or any second provider,
- API keys,
- cross-provider reconciliation,
- provider selection logic,
- batch ingestion,
- screening, valuation, or probabilistic underwriting,
- Azure infrastructure,
- package restructuring,
- a `provider` column in persistence (every persisted fact is still SEC).

---

## Slice 5B Outlook

An FMP adapter will produce the same `CanonicalFinancialHistory` with `provider="fmp"` and its own `provider_field` values. No downstream calculation needs to change. Slice 5B decides whether filing metadata (`form`, `filed`, `accession`) must become optional for non-SEC providers, together with the matching persistence impact.

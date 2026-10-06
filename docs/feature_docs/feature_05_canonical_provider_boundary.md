# Feature 5 — Provider Boundary

## Purpose

Through Feature 4, every OwnerLens analytical layer read raw SEC Company Facts directly. Owner economics, capital efficiency, capital allocation, economic value, compounding, the summary, and coverage each called SEC normalizers and resolved XBRL concepts themselves.

That coupling blocks a second data provider. Feature 5 separates **where facts come from** from **what OwnerLens does with them**.

## Feature 5 Architecture

```text
SEC Company Facts ─→ SecClient ─→ sec_adapter ─┐
                                               ├─→ CanonicalFinancialHistory
FMP statements    ─→ FmpClient ─→ fmp_adapter ─┘   (provider-neutral facts + provenance
                                                     + per-metric status)
                                                          ↓
                                    OwnerLens deterministic logic
                                    (owner economics, capital efficiency,
                                     Feature 2, coverage)
```

SEC remains the default and the regression/audit provider. FMP (Slice 5B) is an optional second provider. Both feed the same canonical boundary, and nothing below it knows which provider produced a fact except through provenance.

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

Slice 5B (below) delivered this: an FMP adapter produces the same `CanonicalFinancialHistory` with `provider="fmp"`, and no downstream calculation changed.

---

# Slice 5B — FMP Provider Adapter

## Goal

Add FMP (Financial Modeling Prep) as a second fundamentals provider that maps normalized FMP annual statements into the existing `CanonicalFinancialHistory`, without changing any OwnerLens economic logic.

```text
FMP API → FmpClient → fmp_adapter → CanonicalFinancialHistory → existing OwnerLens calculations
```

## Configuration

`OWNER_LENS_FMP_API_KEY` is read from the environment or the local `.env` file into `OwnerLensSettings.fmp_api_key`. The key is excluded from the settings `repr`, redacted from every error message and recorded source URL, and never hard-coded. `require_fmp_api_key(settings)` raises a clear `FmpConfigurationError` when FMP is requested without a key.

## FmpClient

`src/owner_lens/fmp.py` is a small synchronous `httpx` client, parallel to `SecClient`. It calls only three FMP `stable` endpoints: `income-statement`, `balance-sheet-statement`, and `cash-flow-statement`. Each call uses `period=annual` and a configurable `limit`. The profile endpoint is not needed: each statement row already carries its symbol, CIK, period end, filing date, and currency.

Failures are typed so callers can distinguish them:

| Error                       | Cause                                                       |
|-----------------------------|-------------------------------------------------------------|
| `FmpConfigurationError`     | Missing or blank API key                                    |
| `FmpAuthenticationError`    | HTTP 401/403 (key rejected)                                 |
| `FmpPlanRestrictionError`   | HTTP 402 (symbol or parameter outside the subscription)     |
| `FmpRateLimitError`         | HTTP 429                                                    |
| `FmpResponseError`          | Other HTTP failure, or an `Error Message` body              |
| `FmpTransportError`         | Network or timeout failure                                  |
| `MalformedFmpResponseError` | Non-JSON, wrong shape, symbol mismatch, non-FY period, bad date |
| `FmpSymbolNotFoundError`    | Empty statement list                                        |

## Mapping FMP to canonical facts

`canonical_history_from_fmp(statements, *, max_years=5)` maps exactly one FMP field to each of the 17 existing canonical metrics. No canonical metric was added.

| Canonical metric           | FMP statement | FMP field                                |
|----------------------------|---------------|------------------------------------------|
| `revenue`                  | income        | `revenue`                                |
| `operating_income`         | income        | `operatingIncome`                        |
| `net_income`               | income        | `netIncome`                              |
| `pretax_income`            | income        | `incomeBeforeTax`                        |
| `income_tax_expense`       | income        | `incomeTaxExpense`                       |
| `diluted_shares`           | income        | `weightedAverageShsOutDil`               |
| `operating_cash_flow`      | cash flow     | `netCashProvidedByOperatingActivities`   |
| `capital_expenditures`     | cash flow     | `investmentsInPropertyPlantAndEquipment` |
| `stock_based_compensation` | cash flow     | `stockBasedCompensation`                 |
| `repurchases`              | cash flow     | `commonStockRepurchased`                 |
| `dividends_paid`           | cash flow     | `commonDividendsPaid`                    |
| `cash`                     | balance sheet | `cashAndCashEquivalents`                 |
| `short_term_investments`   | balance sheet | `shortTermInvestments`                   |
| `current_debt`             | balance sheet | `shortTermDebt`                          |
| `long_term_debt`           | balance sheet | `longTermDebt`                           |
| `total_assets`             | balance sheet | `totalAssets`                            |
| `total_equity`             | balance sheet | `totalStockholdersEquity`                |

FMP's precomputed `freeCashFlow`, `ebitda`, `netDebt`, `totalDebt`, ratios, margins, and growth are never mapped. OwnerLens still calculates FCF, FCF per share, margins, ROIC, growth, capital-allocation ratios, and every classification itself. Those FMP values may be used later for reconciliation only.

### As-reported line items over standardized variants

FMP exposes some line items twice. Live ADBE data showed the variants can disagree. For FY2021, `capitalExpenditure` is 330M while `investmentsInPropertyPlantAndEquipment` is 348M, and `operatingCashFlow` is 7,223M while `netCashProvidedByOperatingActivities` is 7,230M. The second value of each pair matches the 10-K, so the adapter maps the as-reported line item and ignores the standardized variant. A first design that cross-checked the two variants marked them `INVALID` and blocked every layer; it was replaced.

### Sign convention

The canonical convention, made explicit in `CanonicalFact`, is that cash outflows (capital expenditures, repurchases, dividends) are positive magnitudes. SEC already reports them that way. FMP reports them as negative numbers, so the adapter negates them. A positive FMP outflow has an ambiguous sign and is `INVALID`.

### Missing-data semantics

FMP fills unreported line items with zero, so a zero is not automatically trusted:

| FMP data                                                        | Canonical result                    |
|-----------------------------------------------------------------|-------------------------------------|
| Field absent from every row                                     | `UNSUPPORTED`                       |
| `null` in a year                                                | No fact for that year (never zero)  |
| Zero revenue, diluted shares, or total assets                   | Not a value; that year is omitted   |
| Dividends or short-term investments zero in every year          | `STRUCTURALLY_ABSENT`               |
| Non-numeric value, conflicting duplicate fiscal year, positive outflow, non-USD currency | `INVALID`  |

## Provenance and the minimal model adjustment

Each FMP-backed `CanonicalFact` records `provider="fmp"`, the original FMP field name as `provider_field`, the fiscal year (calendar year of FMP's `date`, the canonical rule), the period end, and `filed` from FMP's `filingDate`.

FMP supplies no period start date, filing form, or accession. Rather than fabricating them, Slice 5B made the minimum provider-neutral change to `CanonicalFact`: `period_start` may be `None` for duration facts, and `form`, `filed`, and `accession` may be `None`. SEC still populates every field, and the SEC characterization baseline remains byte-identical.

The persisted reported-fact schema still requires form, filing date, and accession. Persisting a fact without them raises `MissingProvenanceError` instead of writing placeholders. Ingestion remains SEC-only.

## Free-tier constraints

* `limit` must be 5 or less. With five fiscal years, the earliest year has no prior balance sheet, so its ROIC, ROA, and ROE are honestly `None`.
* Some symbols are outside the free plan. CRM and NOW return HTTP 402, surfaced as `FmpPlanRestrictionError`. The plan was not upgraded.

## Live validation (free tier)

| Company | FMP retrieval                  | Canonical history                           | OwnerLens layers |
|---------|--------------------------------|---------------------------------------------|------------------|
| ADBE    | Succeeded                      | FY2021–FY2025; dividends structurally absent | 6/6 available    |
| V       | Succeeded                      | FY2021–FY2025                               | 6/6 available    |
| COST    | Succeeded                      | FY2022–FY2026                               | 6/6 available    |
| MSFT    | Succeeded                      | FY2022–FY2026                               | 6/6 available    |
| CRM     | `FmpPlanRestrictionError` (402) | Not produced                                | n/a              |
| NOW     | `FmpPlanRestrictionError` (402) | Not produced                                | n/a              |

ADBE FY2025 FCF (9,852M) and FCF per share (23.07) match the SEC-backed values.

> [!NOTE]
> Provider differences are visible but deliberately not reconciled. FMP supplies Visa diluted shares and short-term investments, which SEC Company Facts treat as unsupported and absent by policy, and FMP's ADBE FY2024 FCF (7,824M) differs from SEC's (7,873M). SEC-versus-FMP reconciliation is Slice 5C.

## Tests

Mocked FMP responses (`tests/_fmp_fixtures.py`, mirroring the ADBE SEC fixture) cover:

* statement mapping for the income statement, balance sheet, and cash-flow statement,
* provenance,
* status assignment for missing, null, and zero values,
* `INVALID` for malformed, conflicting, or mis-signed data,
* typed client errors with key redaction,
* configuration failure when the key is missing,
* every existing OwnerLens layer running on FMP-backed history without SEC data.

A determinism check confirms that identical reported values from SEC and FMP produce identical OwnerLens outputs. All SEC tests, including the characterization baseline, remain green.

## Educational Notebook

Slice 5B added:

- `13_fmp_provider_adapter.ipynb`

It walks ADBE from the raw FMP response → canonical facts with provenance → existing OwnerLens calculations, then runs the six-company free-tier validation.

## What Slice 5B Deliberately Did Not Build

- SEC/FMP reconciliation (Slice 5C),
- switching FMP to the default provider,
- provider fallback or selection logic,
- persistence or ingestion of FMP-backed facts,
- batch ingestion, scoring, screening, valuation, probabilistic underwriting, or Azure.

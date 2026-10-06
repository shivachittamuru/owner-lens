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

### Local raw-response cache

To avoid spending free-tier API calls on repeated development and Slice 5C reconciliation runs, `FmpClient` caches successful raw responses by default under `data/raw/fmp/`, which is gitignored:

```text
data/raw/fmp/income-statement/ADBE.annual.limit5.json
data/raw/fmp/balance-sheet-statement/ADBE.annual.limit5.json
data/raw/fmp/cash-flow-statement/ADBE.annual.limit5.json
```

* A cache hit deserializes and validates the stored raw JSON, with no network call.
* A cache miss calls FMP and saves the raw body only after the response passes validation. HTTP errors, 402 plan restrictions, 429 rate limits, error messages, empty lists, and malformed JSON are never cached.
* The file name includes the period and `limit`, so requests that change the response never collide.
* Entries never expire. `refresh=True` bypasses the read, calls FMP, and overwrites the entry only if the new response is valid. `cache=None` disables caching.
* A cached entry that is unreadable or fails validation is treated as a miss, refetched, and overwritten.
* The cache stores response bodies only, never the API key. It lives entirely inside the FMP client, so the adapter, the canonical history, and OwnerLens calculations cannot tell cached data from fresh data.

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

---

# Slice 5C — Dual-Source Reconciliation

## Goal

Compare SEC-backed and FMP-backed `CanonicalFinancialHistory` for the same companies and years, explain every difference, and decide with evidence whether FMP is trustworthy enough to become the primary operational provider.

```text
SEC Company Facts (live) ─→ sec_adapter ─┐
                                         ├─→ reconcile_histories ─→ fact rows + derived rows + verdict
FMP (local cache only)   ─→ fmp_adapter ─┘
```

Slice 5C compares and gathers evidence only. SEC normalization, FMP mapping, Feature 1 and 2 economics, the persistence schema, and ingestion defaults are unchanged, and no provider switch happens.

## Reconciliation layer

`src/owner_lens/reconciliation.py` is provider-neutral: it imports only the canonical model and the downstream `*_from_history` functions, which `tests/test_canonical_boundary.py` enforces. `reconcile_histories(sec, fmp, *, explanations)` compares facts by `(ticker, metric, fiscal_year)` and returns a `ReconciliationReport` with fact rows, derived-output rows, a summary, and a verdict. `format_reconciliation_report` renders:

```text
Metric | FY | SEC | FMP | Difference | Status | Category | Reason   (+ provenance for material rows)
```

### Statuses

| Status                | Meaning                                                                                     |
|-----------------------|---------------------------------------------------------------------------------------------|
| `MATCH`               | Both values present and exactly equal                                                       |
| `WITHIN_TOLERANCE`    | Difference within rounding tolerance only (at most $0.5M, or 0.5M shares)                   |
| `REVIEW`              | Difference exceeds rounding tolerance and no explanation is documented                      |
| `EXPLAINED`           | Difference exceeds tolerance and a documented `KnownDiscrepancy` explains it; still visible |
| `SEC_ONLY`/`FMP_ONLY` | Only one provider has a value (window timing, unsupported, or an in-window gap)             |
| `SEMANTIC_DIFFERENCE` | One side is structurally absent by policy while the other reports a value                   |
| `UNCOMPARABLE`        | Invalid provider data, or period ends more than 7 days apart                                |

### Comparison rules

* Tolerance covers **rounding only**. Filings report in millions, so differences of at most $500,000 or 500,000 shares are `WITHIN_TOLERANCE` with category `ROUNDING`. No relative band exists, and any larger difference stays `REVIEW` until explained.
* Both facts must share the canonical fiscal year, and their period ends must be within 7 days of each other (52/53-week calendars).
* A year outside the other provider's available span is `PERIOD_TIMING` and immaterial; a missing year inside the span is a material `SOURCE_DISCREPANCY`.
* `UNSUPPORTED` against `AVAILABLE` is a material one-sided row and never a substitution. `STRUCTURALLY_ABSENT` against `AVAILABLE` is a `SEMANTIC_DIFFERENCE`. `INVALID` on either side is `UNCOMPARABLE`.

### Discrepancy categories

`ROUNDING`, `PERIOD_TIMING`, `PROVIDER_NORMALIZATION`, `SEC_CONCEPT_SELECTION`, `SOURCE_DISCREPANCY`, `POLICY_DIFFERENCE`, `UNSUPPORTED`, and `INVALID`.

### The audit trail: `KNOWN_DISCREPANCIES`

`src/owner_lens/known_discrepancies.py` holds every investigated difference as data: ticker, metric, fiscal year, category, explanation, evidence (concepts, field names, filings, accessions), and `fmp_trusted`, which records whether FMP's value is acceptable as an OwnerLens fact. Explanations apply only to rows that still differ. An explanation that no longer matches any difference is reported as **stale** and blocks eligibility, so the audit trail cannot silently mask a future change.

### Derived-output comparison

OwnerLens recomputes FCF, FCF per share, operating and FCF margins, net cash, invested capital, ROIC, the annual economic-value classification, and the overall summary classification from each history. FMP's own `freeCashFlow` and ratios are never compared as truth. Every derived difference is traced to the fact rows among its inputs, including prior years for ROIC and the annual classification:

* A difference caused only by rounding inputs is `WITHIN_TOLERANCE`.
* A difference caused by accounted-for rows is `EXPLAINED`.
* Any other difference is `REVIEW`.
* A layer that one provider cannot compute is `UNCOMPARABLE` and reported as *unassessed*, never assumed equal.

## Acceptance criteria: can FMP become primary?

| Verdict                                | Definition                                                                                              |
|----------------------------------------|---------------------------------------------------------------------------------------------------------|
| `ELIGIBLE`                             | No material differences: only matches, rounding, and window timing                                      |
| `ELIGIBLE_WITH_EXPLAINED_DIFFERENCES`  | Material differences exist; each is understood, documented, and leaves every core fact trustworthy      |
| `NOT_ELIGIBLE`                         | At least one material unresolved difference, a stale explanation, or a core fact FMP cannot be trusted for |

Core metrics: revenue, operating income, net income, pretax income, income tax expense, operating cash flow, capital expenditures, cash, total assets, total equity, current debt, and long-term debt. The standard requires:

* core canonical facts reconcile or are explained,
* every material difference is categorized with evidence,
* there are no silent substitutions,
* owner-economics outputs agree or trace to explained facts,
* unsupported differences stay explicit.

## Results (live SEC 2026-10-06, cached FMP free tier)

| Ticker | Compared | Match | Rounding | Review | Explained | SEC only | FMP only | Semantic | Verdict |
|--------|---------:|------:|---------:|-------:|----------:|---------:|---------:|---------:|---------|
| ADBE   | 80 | 76 | 3 | 0 | 2 | 6  | 0  | 0 | `NOT_ELIGIBLE` |
| V      | 75 | 73 | 0 | 0 | 2 | 5  | 5  | 5 | `NOT_ELIGIBLE` |
| COST   | 68 | 67 | 0 | 0 | 1 | 23 | 17 | 0 | `NOT_ELIGIBLE` |
| MSFT   | 85 | 80 | 0 | 0 | 5 | 6  | 0  | 0 | `ELIGIBLE_WITH_EXPLAINED_DIFFERENCES` |

Every compared fact either matches, rounds, or is explained. No `REVIEW` rows and no stale explanations remain.

### Explained cases

| Company | Difference | Category | FMP trusted? |
|---------|------------|----------|--------------|
| ADBE FY2024 capex | SEC 183M (both 10-Ks) vs FMP 232M. FMP reclassified investing flows (+51M in other investing). This is the **entire** FCF gap: SEC 7,873M vs FMP 7,824M. Operating cash flow matches. | Provider normalization | No (core) |
| ADBE FY2024 SBC | SEC 1,833M vs FMP 1,881M; no filed line item matches FMP | Provider normalization | No |
| ADBE diluted shares FY2022–FY2024 | 0.1–0.3M differences | Rounding | n/a |
| V diluted shares | SEC unsupported (multi-class, no undimensioned concept); FMP as-converted 1,966M, with diluted equal to basic in FY2022–FY2023 | Unsupported | No |
| V short-term investments | SEC structurally absent by OwnerLens policy; FMP 1,833M. Changes Visa net cash and ROIC. | Policy difference | Yes |
| V FY2025 cash | SEC 17,164M filed vs FMP 20,154M (neither the filed nor the restricted-inclusive total) | Provider normalization | No (core) |
| V FY2025 repurchases | SEC 18,316M filed vs FMP 13,389M (~4.9B moved to other financing) | Provider normalization | No |
| COST FY2025 current debt | SEC 75M vs FMP 361M = 75M + 286M current leases, in this year only | Provider normalization | No (core) |
| COST FY2026 | FMP only: period ended 2026-08-30, FMP filing date 2026-09-24, no FY2026 10-K at the SEC yet | Period timing | Pre-10-K data |
| MSFT FY2024 current debt | After the debt-override fix: SEC `LongTermDebtCurrent` 2,249M omits 6,693M of filed `CommercialPaper`; FMP `shortTermDebt` 8,942M is complete. Other years carry no commercial paper and match. *(Closed in Slice 6D: SEC now composes 8,942M and the row is a `MATCH`.)* | SEC concept selection | Yes |
| MSFT short-term investments | FMP 6–12M below the filed amount every year | Provider normalization | No (non-core) |

### OwnerLens outputs

* **ADBE:** FCF and FCF per share differ only in FY2024, traced to capex. ROIC and every classification match.
* **V:** FCF matches. ROIC differs every year, traced to the short-term-investments policy and FMP's FY2025 cash. SEC cannot classify Visa's per-share economics (unsupported diluted shares) and FMP can, so the classifications differ for a documented reason.
* **COST:** FCF and FCF per share match in every compared year. FY2025 ROIC differs slightly (lease-inclusive short-term debt). The overall classification differs (`IMPROVING` vs `STRONGLY_IMPROVING`) because FMP's latest year is the pre-10-K FY2026.
* **MSFT:** owner economics and every annual classification match exactly. ROIC agrees to within 0.01 percentage points in FY2023 and FY2026; FY2024–FY2025 ROIC differs by 0.5–0.8 points, traced to the FY2024 commercial paper (SEC side) and FMP's short-term-investments offsets. The overall classification differs (`STRONGLY_DETERIORATING` vs `DETERIORATING`) only because SEC carries one more balance-sheet year (window timing).

## Follow-up: Microsoft SEC debt mapping (fixed)

The 5C evidence showed the SEC default `LongTermDebt` concept is the **total** including the current portion for Microsoft, and that Microsoft reports no `DebtCurrent`. MSFT now uses the same `LongTermDebtCurrent`/`LongTermDebtNoncurrent` replacement override as Visa and Costco, added through the Feature 3 metric registry with no ticker logic in calculations. *(Slice 6D removed the current-debt half of all three overrides, and Slice 6E the long-term-debt half: both now resolve through shared policy, so V, COST, and MSFT carry no debt override at all.)*

| MSFT (SEC path)        | Before                                   | After                                        |
|------------------------|------------------------------------------|----------------------------------------------|
| Current debt           | `UNSUPPORTED` (no `DebtCurrent`)         | `LongTermDebtCurrent`: 9,227M FY2026, 2,999M FY2025 *(FY2024 became 8,942M in Slice 6D)* |
| Long-term debt         | `LongTermDebt` 40,294M FY2026 (total)     | `LongTermDebtNoncurrent` 31,067M FY2026        |
| Total debt FY2026      | not computable                           | 40,294M = 9,227M + 31,067M (49,521M if double counted) |
| ROIC FY2026 / FY2025   | not computable                           | 35.9% / 40.0%                                |
| Feature 2 layers       | capital efficiency onward `UNAVAILABLE`  | all six layers `AVAILABLE`; overall `STRONGLY_DETERIORATING` |

ADBE, V, and COST outputs are unchanged (characterization baseline byte-identical). CRM and NOW SEC behavior is unchanged. Both still fail loudly on ambiguous FY2021 restatements (`LongTermDebt` for CRM, `NetIncomeLoss` for NOW). *(Slice 6C later resolved NOW's case as an exact re-rounding to millions; CRM's is a genuine revision and still fails.)* A regression test proves MSFT-style tagging yields `total debt = LongTermDebtCurrent + LongTermDebtNoncurrent`, never `+ LongTermDebt`, and that the override does not leak to other tickers.

Re-running reconciliation retired both former MSFT explanations: they went stale, which is how the audit trail is meant to behave. It also exposed a residual SEC gap, FY2024 commercial paper (see the table above). The single-concept registry could not sum `LongTermDebtCurrent + CommercialPaper`, so that remained a documented follow-up rather than a broadened fix. *(Slice 6D closed it: the metric registry now supports an explicit additive composition, so SEC reports the complete 8,942M and the explanation above was retired as stale.)*

The re-run also exposed a flaw in the audit trail itself. The year-wildcard "MSFT current debt is unsupported" explanation silently absorbed the new 6,693M value difference. Explanations are now category-compatible: an `UNSUPPORTED` explanation applies only to unsupported rows, and a `POLICY_DIFFERENCE` explanation only to semantic differences. An explanation whose premise no longer holds goes stale instead of masking a new discrepancy.

## Provider policy

Three policies were evaluated against the 5C evidence (live SEC, cached FMP, ADBE/V/COST/MSFT):

**A. FMP primary, SEC audit.** Rejected. FMP deviates from a *filed core fact* in three of four companies: ADBE FY2024 capex (232M vs 183M filed, the entire 49M FCF gap), Visa FY2025 cash (20,154M vs 17,164M), and Costco FY2025 current debt (lease liabilities included in one year only). Visa FY2025 buybacks (13,389M vs 18,316M) would also distort capital allocation. These normalizations change FCF, net cash, ROIC, and capital-allocation ratios silently, and they recur in recent fiscal years, not just in old ones. An SEC audit after the fact would flag them but not prevent them from becoming primary outputs.

**C. Metric-by-metric mixed sourcing.** Rejected. FMP's errors are not confined to particular metrics; they are year-specific deviations inside otherwise-matching series (Visa cash matches FY2021–FY2024 and deviates in FY2025). A per-metric source choice therefore cannot isolate them. A per-company, per-year source choice would mean every company needs the reconciliation table maintained before it can be trusted. That is complexity without a trust gain. Mixed sourcing would also combine provider conventions inside one calculation, for example SEC debt with FMP cash, which breaks the single-provenance-per-history property that makes outputs auditable.

**B. SEC primary, FMP secondary for reconciliation.** **Recommended.** SEC values are the filed facts, and with the MSFT fix the SEC path now runs every layer for all four companies. The remaining SEC gaps are explicit, never silent: Visa diluted shares are `UNSUPPORTED`, and Microsoft FY2024 commercial paper is omitted (documented; *closed in Slice 6D*). FMP's real advantages are coverage, such as Visa's as-converted diluted shares and MSFT's complete FY2024 current debt, and timeliness, such as Costco FY2026 before the 10-K. Those are kept as reconciliation evidence and as candidates for targeted SEC-path improvements, not as substituted values. This is the simplest trustworthy policy: one provider per history, filed values as truth, and a second provider that detects drift.

Revisit the policy only when a re-run of `scripts/reconcile_providers.py` shows no untrusted core FMP facts. At that point the corresponding explanations go stale and force review.

## Running it

```powershell
uv run python scripts/reconcile_providers.py                  # ADBE V COST MSFT, FMP cache only
uv run python scripts/reconcile_providers.py ADBE --show-all
```

The script retrieves SEC live, stores the raw payload by content hash under the local raw-snapshot root, and records the CIK and hash. It reads FMP only from `data/raw/fmp/`; a cache miss fails clearly unless `--allow-fmp-fetch` is passed. Re-running makes no FMP API calls.

## Educational Notebook

Slice 5C added:

- `14_dual_source_reconciliation.ipynb`

It covers the cross-company summary, the ADBE FCF trace, the Visa and Costco cases with provenance, the derived-output comparison, and the eligibility verdicts. It refuses any FMP network access.

## What Slice 5C Deliberately Did Not Build

- a provider switch, selection, or fallback logic,
- fixes to FMP mapping, or SEC concept fixes beyond the evidence-verified MSFT debt override (the MSFT FY2024 commercial-paper gap remains a follow-up),
- persistence of reconciliation results or schema changes,
- an FMP plan upgrade (CRM and NOW remain blocked on the free tier),
- batch ingestion, scoring, screening, valuation, or Azure.

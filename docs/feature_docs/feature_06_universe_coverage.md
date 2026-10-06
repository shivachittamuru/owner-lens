# Feature 6 — Universe Expansion and Coverage Scaling

## Purpose

Features 1–5 validated OwnerLens's SEC-first canonical pipeline on four to six companies. Feature 6 asks whether the same pipeline holds up across a broader universe, and what to improve next if it does not.

---

# Slice 6A — Coverage Discovery

## Goal

Run the existing pipeline, unchanged, across a broader set of conventional U.S. operating companies. Measure full, partial, and failed coverage, identify the canonical metrics that block it, and classify why, before designing the next normalization improvement.

6A is discovery. It adds **no ticker overrides** and makes **no normalization changes**. The one exception is a clear general bug the survey exposed (see "Fixed during 6A").

## Universe

24 companies across ten industries:

| Group | Tickers |
|---|---|
| Existing anchors | ADBE, V, COST, MSFT, CRM, NOW |
| Software and internet | META, AMZN, NVDA, ORCL, INTU |
| Consumer | NKE, LULU, CMG, PG, KO, HD, LOW |
| Industrials | CAT, DE (stress tests: captive finance arms) |
| Healthcare | UNH (stress test: insurance-like balance sheet), PFE |
| Energy | XOM, CVX |

Banks, insurers, REITs, and asset managers are excluded; they need separate economic models.

## How the survey works

```text
ticker ─→ ingest_company (dedicated data/universe_6a.db, shared raw-snapshot store)
            └─ stored raw snapshot ─→ canonical_history_from_sec
                                        ├─ per-metric status + diagnosis (read-only candidate catalog)
                                        └─ per-layer probe of all six analytical layers
                                               ↓
                     UniverseReport: company view, metric view, pattern view, JSON export
```

* `src/owner_lens/universe.py` holds the survey, diagnosis, aggregation, and formatting. It is SEC-side, above the canonical boundary.
* `scripts/survey_universe.py` runs a live survey (`ingest_company` into `data/universe_6a.db`). `--from-store` replays it offline from the stored snapshots. The working `data/ownerlens.db` is never touched.
* Existing coverage re-raises an `INVALID` metric by design, so a company with one ambiguous restatement produces no coverage picture. The survey therefore probes each layer directly and records one state per layer:
  * `AVAILABLE`
  * `PARTIAL`
  * `INSUFFICIENT_DATA`
  * `UNAVAILABLE`: an unsupported input
  * `BLOCKED`: an invalid input
  * `ERROR`: an unexpected exception, which suggests an OwnerLens bug

  Coverage semantics are unchanged.
* `FULL` means all six layers are available **and** no metric is silently stale.

### Diagnosis categories

| Category | Meaning |
|---|---|
| `MISSING_CONCEPT` | No preferred or catalog concept has a recent annual value |
| `STALE_CONCEPT` | The preferred concept has annual history but nothing recent, including **silently stale** `AVAILABLE` series |
| `ALTERNATIVE_CONCEPT` | Exactly one catalog alternative has recent values; an override candidate, recorded and never applied |
| `COMPOSITE_CANDIDATE` | Two or more non-zero component concepts are needed, or the selected concept excludes a non-zero component (value-level) |
| `AMBIGUOUS_DUPLICATE` | Conflicting full-year values, sub-classified as `PRECISION`, `STOCK_SPLIT`, or `VALUE_CHANGE` |
| `PERIOD_ISSUE` | A concept is present without annual 10-K facts, or fiscal years are missing or have gaps |
| `BUSINESS_STRUCTURE` | Industry-specific concepts replace the canonical ones |
| `LIKELY_BUG` | An unexpected exception in a layer or in ingestion |

## Results

Survey of 2026-10-06 (live SEC, replayed offline):

| Outcome | Companies | Share |
|---|---:|---:|
| `FULL` | 3 (ADBE, COST, MSFT) | 12% |
| `PARTIAL` | 12 | 50% |
| `FAILED` (no owner economics) | 9 (NOW, META, AMZN, NVDA, NKE, CMG, PFE, XOM, CVX) | 38% |

### Metric view (selected)

| Metric | Available | Unsupported | Invalid | Companies blocked | Dominant diagnosis |
|---|---:|---:|---:|---:|---|
| current_debt | 12 | 12 | 0 | 9 | composite / alternative / missing |
| diluted_shares | 18 | 2 | 4 | 5 | ambiguous duplicate (stock split) |
| operating_income | 20 | 4 | 0 | 4 | missing concept |
| long_term_debt | 15 | 6 | 3 | 3 | mixed |
| revenue | 22 | 1 | 1 | 2 | stale / period |

### Patterns

* **Silent staleness (the most important finding).** 14 `AVAILABLE` metrics in 10 companies come from SEC concepts the company stopped reporting years ago. Examples: NVDA revenue (FY2018–FY2022), AMZN capital expenditures (FY2012–FY2016), CAT net income (FY2007–FY2010), and PG long-term debt (FY2011–FY2015). The selector takes the first preferred concept with *any* annual history and has no recency check. Fiscal-year alignment keeps these values out of recent rows, so outputs degrade to missing values rather than wrong numbers, but coverage still reports the metric as available.
* **Ambiguous duplicates are restatements, not data errors.** The survey found 14 conflicting full-year values. All 12 classified as ambiguous duplicates are mechanical restatements:
  * 8 precision re-roundings: thousands versus millions, such as NOW `230,000,000` versus `230,141,000`;
  * 4 stock-split restatements of diluted shares: AMZN 20:1, NVDA 10:1, CMG 50:1, NOW 5:1.

  The other 2 are genuine value changes (PG cash and PFE revenue). Both sit inside stale concepts, so they are diagnosed as `STALE_CONCEPT`.

  Most sit in the oldest window year (the restated baseline).
* **Current debt is a taxonomy pattern, not a set of quirks.** Three alternatives each recur in 3–4 companies: `ShortTermBorrowings`, `LongTermDebtAndCapitalLeaseObligationsCurrent`, and `LongTermDebtCurrent`. In companies with no short-term debt (NOW, META, CMG), the concept is simply absent.
* **Composite metrics are needed only for current debt.** There are 5 cases. Three are unsupported: AMZN and NKE (`LongTermDebtCurrent + ShortTermBorrowings`) and KO (`CommercialPaper + OtherShortTermBorrowings`). Two are value-level understatements: MSFT FY2024 commercial paper (6,693M) and COST FY2021–FY2022 other short-term borrowings.
* **Operating income is missing by business structure.** Energy companies (XOM, CVX), PFE, and NKE do not tag `OperatingIncomeLoss`.
* **XOM is a period/identity case.** SEC now maps the ticker to the new successor registrant *ExxonMobil Holdings Corp*, which has only 10-Q filings and therefore no annual facts yet.

### Fixed during 6A

`ingest_company` degraded gracefully on ambiguity only for the shared annual-normalization errors. An ambiguous **revenue** restatement (PFE FY2021) raised `AmbiguousRevenueError` and crashed ingestion. Ingestion now also catches the provider-neutral `CanonicalDataError` base, so PFE degrades explicitly instead of crashing. This is a general bug fix with a regression test (`test_ambiguous_revenue_restatement_degrades_instead_of_crashing`). It changes no semantics for other companies.

## Acceptance answers

1. **Full coverage:** 3 of 24 companies (12%).
2. **Partial versus failed:** 12 partial (50%) and 9 failed (38%).
3. **Top blocking metrics:** current debt (9 companies), diluted shares (5), operating income (4), long-term debt (3), and revenue (2).
4. **Quirks or patterns:** mostly **recurring taxonomy patterns**. Three current-debt alternatives recur in 3 or more companies. All 12 ambiguous duplicates follow two mechanical restatement kinds. Staleness recurs in 10 companies. Only six candidate concepts are single-company quirks.
5. **Composite metrics:** 5 company cases, all current debt; 2 of them are value-level understatements of an `AVAILABLE` metric.
6. **SEC-first at 100+ companies:** **yes, if the next improvements are general rules rather than per-ticker overrides.** The blockers cluster into a few policies, and the cost is two SEC requests per company. Continuing to add per-ticker overrides would not scale: 21 of 24 companies fall short of `FULL`, and 19 of them have at least one blocking input.
7. **Biggest next improvement**, ranked by companies fully unblocked (what-if over diagnoses, `UniverseReport.unblocked_by`):

| Improvement | Companies unblocked alone | Cumulative |
|---|---:|---:|
| A. Current-debt policy: ordered fallbacks, composite sum, explicit "no current debt reported" absence | 2 | — |
| B. Restatement-aware ambiguity: tolerate precision re-rounding, split-adjust shares | 2 | A + B: 8 |
| C. Recency-aware concept selection with catalog fallback | 5 | A + B + C: 12 |
| Long-term-debt alternatives (on top of A + B + C) | — | 14 |

**Recommendation:** make **recency-aware concept selection** the next normalization slice. It is the only improvement that fixes a *correctness* gap: silent staleness in 10 companies that coverage cannot see today. It also unblocks the most companies on its own (5). Pair it with the **current-debt policy** and **restatement-aware ambiguity** as general, tested rules. Together they move 12 of the 19 blocked companies to unblocked, with no per-ticker overrides. Operating-income derivation (energy and pharma) and the XOM successor registrant remain separate decisions.

## Running it

```powershell
uv run python scripts/survey_universe.py                 # live: 24 companies, data/universe_6a.db
uv run python scripts/survey_universe.py --from-store    # offline replay from stored snapshots
uv run python scripts/survey_universe.py NKE LULU        # a subset
```

The JSON report (`data/universe_6a_report.json`), the survey database, and the raw snapshots are local runtime data and are gitignored.

## Educational Notebook

- `15_universe_coverage.ipynb`: an offline replay covering the company, metric, and pattern views, silent staleness, the improvement what-ifs, and the acceptance answers.

## What Slice 6A Deliberately Did Not Build

- ticker overrides or normalization changes for the gaps found (recorded only),
- composite metrics, recency-aware selection, or new ambiguity policies (measured only),
- banks, insurers, REITs, or asset managers,
- screeners, scores, valuation, FMP-primary ingestion, batch scheduling, or probabilistic underwriting.

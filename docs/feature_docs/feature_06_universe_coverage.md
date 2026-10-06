# Feature 6 — Universe Expansion and Coverage Scaling

## Purpose

Features 1–5 validated OwnerLens's SEC-first canonical pipeline on four to six companies. Feature 6 asks whether the same pipeline holds up across a broader universe, and what to improve next if it does not.

**Status: closed.** Slice 6A measured coverage; 6B, 6C, 6D, and 6E each removed one general class of normalization error. Full coverage went from 3 to 7 of 24 companies, and the per-company override registry shrank from five entries to one. The closeout recommendation at the end of this document is to **stop normalization and proceed upward**, with the accepted limitation that unsupported companies stay explicit rather than being silently approximated.

| Slice | Change | `FULL` |
|---|---|---:|
| 6A | Coverage discovery (no behavior change) | 3 |
| 6B | Recency-aware concept selection | 3 |
| 6C | Restatement- and split-aware conflict resolution | 4 |
| 6D | Current-debt normalization and composition | 5 |
| 6E | Canonical alternative-concept policy | **7** |

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
| `STALE_CONCEPT` | The preferred concept has annual history but nothing recent. In 6A this included **silently stale** `AVAILABLE` series; since 6B a stale concept is never selected, so the finding is always `UNSUPPORTED` |
| `ALTERNATIVE_CONCEPT` | Exactly one catalog alternative has recent values; an override candidate, recorded and never applied |
| `COMPOSITE_CANDIDATE` | Two or more non-zero component concepts are needed, or the selected concept excludes a non-zero component (value-level). Slice 6D implemented the only measured case (current debt), so this now reports nothing |
| `COMPOSITION_BLOCKED` | The registry declares a composition the company's tagging makes unsafe, because a concept bundles economics the metric excludes (Slice 6D) |
| `AMBIGUOUS_DUPLICATE` | Conflicting full-year values, sub-classified as `PRECISION`, `STOCK_SPLIT`, or `VALUE_CHANGE`. Since 6C the normalizer resolves re-roundings and evidenced splits, so remaining cases are normally `VALUE_CHANGE` |
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

* **Silent staleness (the most important finding).** 14 `AVAILABLE` metrics in 10 companies come from SEC concepts the company stopped reporting years ago. Examples: NVDA revenue (FY2018–FY2022), AMZN capital expenditures (FY2012–FY2016), CAT net income (FY2007–FY2010), and PG long-term debt (FY2011–FY2015). The selector takes the first preferred concept with *any* annual history and has no recency check. Fiscal-year alignment keeps these values out of recent rows, so outputs degrade to missing values rather than wrong numbers, but coverage still reports the metric as available. *(Fixed in Slice 6B.)*
* **Ambiguous duplicates are restatements, not data errors.** The survey found 14 conflicting full-year values. All 12 classified as ambiguous duplicates are mechanical restatements:
  * 8 precision re-roundings: thousands versus millions, such as NOW `230,000,000` versus `230,141,000`;
  * 4 stock-split restatements of diluted shares: AMZN 20:1, NVDA 10:1, CMG 50:1, NOW 5:1.

  The other 2 are genuine value changes (PG cash and PFE revenue). Both sit inside stale concepts, so they are diagnosed as `STALE_CONCEPT`.

  Most sit in the oldest window year (the restated baseline).

  *Correction from Slice 6C:* 6A's "precision" label used a 1% heuristic. The exact re-rounding rule shows that only the four NOW cases are re-roundings. CRM and INTU long-term debt, META capital expenditures, and PFE cash are genuine revisions that happen to be under 1%.
* **Current debt is a taxonomy pattern, not a set of quirks.** Three alternatives each recur in 3–4 companies: `ShortTermBorrowings`, `LongTermDebtAndCapitalLeaseObligationsCurrent`, and `LongTermDebtCurrent`. In companies with no short-term debt (NOW, META, CMG), the concept is simply absent. *(Addressed in Slice 6D.)*
* **Composite metrics are needed only for current debt.** There are 5 cases. Three are unsupported: AMZN and NKE (`LongTermDebtCurrent + ShortTermBorrowings`) and KO (`CommercialPaper + OtherShortTermBorrowings`). Two are value-level understatements: MSFT FY2024 commercial paper (6,693M) and COST FY2021–FY2022 other short-term borrowings. *(All implemented in Slice 6D.)*
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

- `15_universe_coverage.ipynb`: an offline replay covering the company, metric, and pattern views; silent staleness (fixed in 6B); resolved restatement and stock-split conflicts with provenance (6C); the improvement what-ifs; and the acceptance answers.

## What Slice 6A Deliberately Did Not Build

- ticker overrides or normalization changes for the gaps found (recorded only),
- composite metrics, recency-aware selection, or new ambiguity policies (measured only),
- banks, insurers, REITs, or asset managers,
- screeners, scores, valuation, FMP-primary ingestion, batch scheduling, or probabilistic underwriting.

---

# Slice 6B — Recency-Aware SEC Concept Selection

## Goal

Close the correctness gap 6A found. The selector took the first preferred SEC concept with *any* annual history, so a concept the company stopped using years ago could count as an available current metric. A stale concept must not count as available.

## The rule

Selection still walks the concept preference list in order. In `_annual.py`, a concept is **eligible** only if it covers the company's latest fiscal year:

1. **Company reference.** `latest_annual_period_end` returns the newest period end of any full-year (350–380 day) `FY` duration fact filed on a 10-K-family form, across the whole us-gaap payload. It is derived from the company's own filings, never from today's date.
2. **Current concept.** A concept is current when its newest qualifying observation (duration or instant, as before) ends within `RECENCY_TOLERANCE_DAYS = 31` days of the reference. The tolerance absorbs 52/53-week calendar drift. It is far shorter than a fiscal year, so a concept whose last value is a prior fiscal year is stale.
3. **Selection.** The first current concept in preference order wins. Stale concepts are skipped *before* their years are resolved, so a restatement conflict inside abandoned history can no longer block a metric.
4. **No current concept.** The metric's existing unsupported error is raised. The message lists each stale concept with its last period end and the company reference. Stale history is never returned.
5. **Older-year gaps are not penalized.** Only the newest year must be covered. A concept that legitimately starts recently is current.
6. **No reference.** If the payload has no 10-K full-year duration fact (for example XOM's successor registrant, with only 10-Q filings), no recency filter is applied.

The rule runs inside the shared `select_annual_series` and `select_instant_series`, so it covers all 17 SEC metrics. **Per-company overrides stay authoritative.** They replace the preference tuple before the rule runs, so a current override always wins, and a stale override becomes unsupported rather than falling back to the default concepts.

**Tolerant-of-absence metrics** (dividends paid, short-term investments) keep `STRUCTURALLY_ABSENT` for a concept the company *never* reported. A concept reported only in stale years is now `UNSUPPORTED`, not absent, because the item may have been retagged. PFE `ShortTermInvestments`, last reported FY2019 while Pfizer still holds billions in investments, would otherwise have silently read as "no short-term investments".

No ticker overrides were added. No composite metrics, restatement handling, or operating-income policy was introduced.

## Preserved behavior

* The SEC characterization baseline (`tests/data/canonical_baseline.json`) is **byte-identical**. Error wording is unchanged when no stale concept is involved.
* On the 6A snapshots (identical content hashes), ADBE, V, COST, and MSFT show no change in any metric's concept, status, or years, nor in any layer state.
* The Slice 5C reconciliation verdicts are unchanged: ADBE, V, and COST `NOT_ELIGIBLE`; MSFT `ELIGIBLE_WITH_EXPLAINED_DIFFERENCES`.

## Survey: before versus after

Same 24 companies, same stored SEC snapshots:

| | 6A (before) | 6B (after) |
|---|---:|---:|
| `FULL` | 3 | 3 |
| `PARTIAL` | 12 | 10 |
| `FAILED` | 9 | 11 |
| Silently stale `AVAILABLE` metrics | **14 in 10 companies** | **0** |
| `STALE_CONCEPT` findings | 18 (14 available, 4 invalid) | 14 (all unsupported) |
| Companies with a blocking input | 19 | 20 |

**Current fallbacks now selected automatically** (preference-list fallback, no overrides):

| Company | Metric | 6A (stale) | 6B (current) |
|---|---|---|---|
| NVDA | revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, ends FY2022 | `Revenues`, through FY2026 |
| NVDA | capital expenditures | `PaymentsToAcquirePropertyPlantAndEquipment`, ends FY2012 | `PaymentsToAcquireProductiveAssets`, through FY2026 |
| AMZN | capital expenditures | `PaymentsToAcquirePropertyPlantAndEquipment`, ends FY2016 | `PaymentsToAcquireProductiveAssets`, through FY2025 |

**Stale metrics that are now explicit `UNSUPPORTED`** (no current concept in the preference list): CAT net income (ends FY2010), ORCL pretax income (FY2018) and long-term debt (FY2022), INTU current debt (FY2021), LULU cash (FY2019), PG long-term debt (FY2015), UNH total equity (FY2014), PFE long-term debt (FY2020) and short-term investments (FY2019), and CVX cash (FY2023) and long-term debt (FY2021).

**Status changes, and why none is a regression:**

* **CAT and DE: `PARTIAL` to `FAILED`.** CAT's owner economics ran on net income that ends in FY2010. DE's `OperatingIncomeLoss` ends in FY2024 and is absent from its FY2025 10-K. Both outputs looked available but did not cover the current year.
* **ORCL: capital efficiency, economic value, capital allocation, and summary `AVAILABLE` to `UNAVAILABLE`.** They were computed on long-term debt ending FY2022 and pretax income ending FY2018.
* **INTU and PG: layers `BLOCKED` to `UNAVAILABLE`; KO long-term debt and NKE short-term investments `INVALID` to `UNSUPPORTED`.** Their invalid inputs were restatement conflicts inside *stale* concepts. The real reason is now visible: the concept is no longer reported.
* **New pattern, "discontinued activity line".** AMZN and PFE repurchases: `PaymentsForRepurchaseOfCommonStock` was reported as 0 for FY2023–FY2024 and then dropped from the FY2025 10-K. The latest year cannot be inferred to be zero without a policy, so the metric is `UNSUPPORTED`. This is a 6C candidate.
* **PFE revenue** is now correctly diagnosed `AMBIGUOUS_DUPLICATE` (value change). The FY2023 conflict is in the current `Revenues` concept. The survey's former "conflict in a stale concept" branch could no longer be reached and was removed.

No golden-company output changed. No `LIKELY_BUG` or `ERROR` appeared.

**Why no company reached `FULL`:** 6A's "recency-aware fallback unblocks 5" what-if counted *catalog* alternatives that are not in the preference lists, such as `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`, `ProfitLoss`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, and `LongTermDebtNoncurrent`. Adopting them changes a metric's definition (restricted cash, noncontrolling interest, lease obligations), so it is a concept-policy decision, not a recency rule. 6B makes the recency gap honest and selects current fallbacks that already exist in the preference lists. NVDA and AMZN gained current revenue and capex but remain blocked by stock-split restatements of diluted shares.

## Remaining blockers for 6C

Top blocking metrics after 6B: current debt (8 companies), diluted shares (5), operating income (5), cash (2), net income (2), and revenue (2).

What-if over the post-6B diagnoses (`UniverseReport.unblocked_by`, 20 blocked companies):

| Improvement | Unblocked alone | Cumulative |
|---|---:|---:|
| A. Current-debt policy (fallbacks, composite sum, explicit absence) | 2 (HD, LOW) | — |
| B. Restatement-aware ambiguity (precision re-rounding, stock-split shares) | 1 (NVDA) | A + B: 6 |
| C. Catalog concept policy (restricted cash, NCI equity, `ProfitLoss`, `LongTermDebtNoncurrent`) | 5 (PG, HD, LOW, CAT, UNH) | A + B + C: 11 |
| Long-term-debt alternatives (on top of A + B + C) | — | 12 |

Separate decisions remain:

* operating-income derivation (NKE, PFE, CVX, XOM, DE);
* the discontinued-activity-line policy (AMZN and PFE repurchases);
* the XOM successor registrant.

## Tests

`tests/test_recency_selection.py` (24 tests) covers:

* the company reference (10-K full-year only; quarterly, partial, and 8-K facts ignored; no calendar dependence);
* the drift tolerance;
* the selection rules:
  * a current preferred concept is kept;
  * a stale preferred concept falls back;
  * preference order is preserved among current concepts;
  * all-stale concepts are unsupported;
  * older-year gaps are tolerated;
  * there is no filter without a reference;
* duration and instant paths;
* tolerant metrics: never reported means absent, stale-only means unsupported;
* overrides: a current override wins, and a stale override never falls back; the MSFT debt pair is unchanged;
* the 6A patterns (NVDA revenue, AMZN capex, CAT net income);
* the golden fixtures, which select only current concepts.

The two 6A survey tests that asserted silent staleness now assert the corrected behavior.

## What Slice 6B Deliberately Did Not Build

- ticker overrides or catalog concepts added to preference lists,
- composite debt metrics,
- stock-split or restatement conflict resolution,
- an operating-income policy or a discontinued-activity-line policy.

---

# Slice 6C — Restatement and Stock-Split-Aware Conflict Resolution

## Goal

When one fiscal year has several distinct reported values for the selected SEC concept, the normalizer used to fail loudly every time. 6A and 6B showed that many of these conflicts are mechanical: precision re-roundings and stock-split restatements. 6C resolves those deterministically and keeps every genuine or uncertain conflict a loud failure.

## The rules

The rules live in the shared `_annual._resolve_series` and `_resolve_year`, so they apply to every SEC metric. 6B recency-aware selection runs first and is unchanged.

**Precision re-rounding (any unit).** Distinct values for a year resolve only if exactly one value has the fewest trailing zeros (the most precise one), and every other value equals it rounded half away from zero to 10^3, 10^4, 10^5, or 10^6, within the precision its own trailing zeros express. The most precise value is kept, with the provenance of the earliest filing that reported it. There is no percentage band. The largest difference ever absorbed is half a million, and only when the coarse value is exactly the rounded precise one. Two values at the same precision are a genuine revision, however close: CRM long-term debt is 2,690M versus 2,677M, a 0.5% gap, and still fails.

**Stock split (share units only).** A year's conflict is evidence of a forward split when all of the following hold:

* the values form a pre-split group and a post-split group with an integer ratio from 2 to 100;
* the pre-split value equals the post-split value divided by the ratio, exactly or as a re-rounding under the precision rule;
* every pre-split report was filed before every post-split report.

Evidence from several years for the same split is merged into the narrowest filing interval. Each observation is then put on the latest basis:

* an observation filed on or before a split's last pre-split report is multiplied by that split's ratio, cumulatively across splits (for example ×40 for NVDA's 4:1 then 10:1);
* an observation filed between the last pre-split and the first post-split report has an unknown basis, and the year fails;
* within each year, the value on the most recent basis wins, and every other observation must agree with it after adjustment.

**Fail loudly otherwise.** The existing ambiguity error, with unchanged wording, is raised for:

* genuine revisions;
* reverse or fractional splits (for example 3:2);
* split timing that contradicts the filing order;
* contradictory split evidence (overlapping intervals with different ratios disables split recognition entirely);
* any value that does not reconcile after adjustment.

## Provenance

Each resolved fact carries a provider-neutral `ConflictResolution` on `CanonicalFact.resolution`:

* `kind`: `PRECISION` or `STOCK_SPLIT`;
* `reported_value`: the value exactly as filed in the fact's own accession;
* `split_factor`: the factor applied (1 when the value was filed verbatim);
* `superseded`: every other distinct reported value, with its form, filing date, accession, and basis factor.

Nothing is discarded silently. Unresolved and conflict-free years carry no resolution and are byte-identical to before.

The persistence schema is unchanged. A **split-adjusted** value was not filed verbatim in its source accession, so its `reported_facts.concept` states the adjustment. For example:

```text
WeightedAverageNumberOfDilutedSharesOutstanding [split-adjusted x10 from reported 2535000000]
```

Verbatim values, including precision-resolved and restated post-split values, keep the plain concept name.

The survey's restatement labels now use the same exact classifier (`classify_conflict_values`) instead of 6A's 1% heuristic. Each metric finding lists its resolved conflicts, and the pattern view and JSON report count them.

## Preserved behavior

* The SEC characterization baseline is **byte-identical**. ADBE, V, COST, and MSFT have no conflicting values, so none of their facts carries a resolution.
* No metric or layer changed for ADBE, V, COST, or MSFT on the stored snapshots. The 5C reconciliation verdicts are unchanged.
* 6B recency selection, debt mappings, the operating-income policy, FMP logic, and economic formulas are untouched.

## Survey: before versus after

Same 24 companies, same stored SEC snapshots (no content-hash change):

| | 6B (before) | 6C (after) |
|---|---:|---:|
| `FULL` | 3 | **4** (+NVDA) |
| `PARTIAL` | 10 | 13 |
| `FAILED` | 11 | **7** |
| `AMBIGUOUS_DUPLICATE` findings | 13 | **5** (all genuine `VALUE_CHANGE`) |
| Conflicts resolved (company, metric, year) | 0 | 15 (4 precision, 11 split) |
| Companies with a blocking input | 20 | 19 |

**Resolved conflicts:**

* NOW: FY2021 net income and FY2020 cash, total assets, and equity (re-rounded thousands to millions). 5:1 split diluted shares, FY2021–FY2022 adjusted ×5.
* NVDA: 10:1 split diluted shares, FY2022 adjusted ×10.
* CMG: 50:1 split diluted shares, FY2021 adjusted ×50.
* AMZN: 20:1 split diluted shares, FY2021 `515,000,000` (millions) reconciled to the restated `10,296,000,000`.

Each adjusted share series is continuous on the post-split basis. NVDA, for example, runs FY2022 25.35B, FY2023 25.07B, FY2024 24.94B, FY2025 24.80B, and FY2026 24.51B.

**Companies newly unblocked:**

* **NVDA** reaches `FULL`. All six layers are available.
* **NOW, AMZN, and CMG** move from `FAILED` to `PARTIAL`. Owner economics now runs, and each is next blocked by current debt.

**Still failing loudly (genuine revisions):**

* CRM FY2021 long-term debt (2,690M versus 2,677M);
* INTU FY2021 long-term debt (2,048M versus 2,034M);
* META FY2021–FY2023 capital expenditures (for example 27,266M versus 27,045M);
* PFE FY2022–FY2023 revenue (for example 58,496M versus 59,553M);
* PFE FY2020 cash (1,784M versus 1,786M).

No unexpected regression and no `LIKELY_BUG` appeared. NVDA, AMZN, CMG, and NOW ingest and persist through `ingest_company`; NVDA ingests `COMPLETE`.

## Remaining blockers

Top blocking metrics after 6C: current debt (9 companies), operating income (5), cash (2), revenue (2), and then capital expenditures, diluted shares, long-term debt, net income, and pretax income (1 each).

What-if over the post-6C diagnoses (19 blocked companies):

| Improvement | Unblocked alone | Cumulative |
|---|---:|---:|
| A. Current-debt policy (fallbacks, composite sum, explicit absence) | 3 (CMG, HD, LOW) | — |
| C. Catalog concept policy (restricted cash, NCI equity, `ProfitLoss`, `LongTermDebtNoncurrent`) | 5 (PG, HD, LOW, CAT, UNH) | A + C: 7 |

The current-debt policy is now the largest single blocker; it blocks 9 companies. Separate decisions remain:

* a policy for genuine revisions (for example "latest restated value with superseded provenance"), which would unblock CRM, INTU, META, and PFE;
* operating-income derivation (NKE, PFE, CVX, XOM, DE);
* the discontinued-activity line (AMZN and PFE repurchases);
* the XOM successor registrant.

## Tests

`tests/test_conflict_resolution.py` (28 tests) covers:

* Precision:
  * NOW-pattern re-rounding resolves to the precise original filing with superseded provenance;
  * a later, more precise value also resolves;
  * untouched years carry no resolution.
* Genuine and unknown conflicts still fail:
  * CRM-, META-, and PFE-style revisions;
  * re-rounding beyond millions or to tens;
  * zero versus non-zero.
* Splits:
  * NVDA-pattern restated value, plus the pre-split-only year adjusted ×10 with as-filed provenance;
  * AMZN split combined with re-rounding;
  * the CMG 50:1 and NOW 5:1 ratios;
  * cumulative ×40 across two splits;
  * owner economics on the adjusted basis.
* Unrecognized share conflicts still fail:
  * a reverse split;
  * contradictory timing;
  * a 3:2 split;
  * a near-ratio that is not a split;
  * an observation filed between the pre- and post-split reports;
  * contradictory split evidence;
  * split logic applied to a currency metric.
* Persistence annotation of split-adjusted facts.
* The ADBE, V, and COST golden fixtures carry no resolutions.

The survey tests now assert that precision and split conflicts resolve, while a genuine baseline-year revision still blocks.

## What Slice 6C Deliberately Did Not Build

- a policy for genuine revisions (they still fail loudly),
- reverse or fractional split handling,
- composite debt, catalog-concept adoption, or an operating-income policy,
- persistence schema changes.

---

# Slice 6D — Current-Debt Normalization and Composition

## Goal

Current debt was the largest recurring SEC blocker: 9 of 24 companies. 6A showed three patterns behind it — an alternative concept, several components that must be summed, and genuinely absent borrowings — and 6D resolves all three with general registry policy rather than per-company overrides.

## The policy

`CanonicalMetricDefinition` gained an optional `MetricComposition`, so a metric can declare how it resolves beyond a single concept. Current debt is the only metric that declares one. The resolution ladder in the shared instant normalizer is:

1. **A total concept wins.** `DebtCurrent` already includes every component, so it is preferred and never summed. This is the double-counting guard. Adobe reports `DebtCurrent` 1,499M and `LongTermDebtCurrent` 1,500M for the same FY2024 balance; the total wins and the two are never added.
2. **Otherwise compose the components** reported at each fiscal-year end, in policy order: `LongTermDebtCurrent`, `CommercialPaper`, `ShortTermBorrowings`, `OtherShortTermBorrowings`. A component reported as zero contributes nothing and is not recorded, so a year with one real component stays byte-identical to a plain single-concept selection.
3. **Otherwise, if the company's own totals prove absence**, the metric is `STRUCTURALLY_ABSENT`.
4. **Otherwise** the existing unsupported or invalid semantics apply.

Per-company current-debt overrides were deleted: V, COST, and MSFT now resolve through the shared policy, as do CRM, INTU, NKE, AMZN, and CAT.

### What is deliberately not a component

Lease liabilities are not borrowings. `OperatingLeaseLiabilityCurrent`, `FinanceLeaseLiabilityCurrent`, and `CapitalLeaseObligationsCurrent` are never summed. The Slice 5C Costco reconciliation, where FMP's FY2025 current debt silently included 286M of lease liabilities, is the standing warning against widening the metric.

Concepts that *restate* part of the current portion rather than adding to it are also excluded: `ConvertibleDebtCurrent`, `NotesPayableCurrent`, `LinesOfCreditCurrent`, and `SecuredDebtCurrent`. Salesforce reports `ConvertibleDebtCurrent` equal to its entire `LongTermDebtCurrent` (4,000M), so summing them would double count.

`LongTermDebtAndCapitalLeaseObligationsCurrent` is marked **unsafe**: it bundles the current portion of debt with capital leases and cannot be split. A non-zero value refuses composition for that company rather than understating current debt (by composing only commercial paper) or widening it (by adopting the bundle). HD, KO, and LOW stay explicitly unsupported for this reason.

### Structural absence

Absence is never inferred from a missing tag. It is proven from the company's own reported totals: current debt equals `LongTermDebt` minus `LongTermDebtNoncurrent`, so at the latest fiscal-year end a reported `LongTermDebt` that **equals `LongTermDebtNoncurrent`** (all debt is noncurrent) or **is zero** (no debt at all) proves there is nothing to report. META (58,744M noncurrent, nothing current) and CMG (no debt) qualify. NOW and LULU report no debt totals at all, so their current debt stays `UNSUPPORTED` — honest, not assumed absent. No reported zero is ever fabricated; a filed zero remains an `AVAILABLE` zero.

Downstream, a structurally absent current debt contributes nothing to total debt, exactly as an absent short-term-investments series already did for Visa.

## Provenance

A composed `CanonicalFact` carries `components`: every contributing concept with its own value, form, filing date, and accession. The fact's own value must equal the sum (enforced in `__post_init__`), and a single-source fact carries no components at all.

**Persistence limitation (documented, not redesigned).** `reported_facts` stores one concept, form, filing date, and accession per row, so structured composition metadata lives on the canonical model. The stored `concept` string names every component and value, for example:

```text
LongTermDebtCurrent 2249000000 + CommercialPaper 6693000000
```

The row's form, filing date, and accession are the first contributing component's. Changing the schema would require a version bump that invalidates existing databases, which is out of scope for this slice.

## Preserved behavior

* The SEC characterization baseline changed in **one synthetic scenario and only in an error string**: `ADBE_NO_CURRENT_DEBT` now reports `Tried: DebtCurrent, LongTermDebtCurrent, CommercialPaper, ShortTermBorrowings, OtherShortTermBorrowings` instead of `Tried: DebtCurrent`. No value in any scenario changed, and ADBE, V, and COST fixture outputs are untouched.
* MSFT changed **only FY2024**, as intended. FY2026, FY2025, FY2023, FY2022, and FY2021 keep single-source `LongTermDebtCurrent` provenance.
* 6B recency and 6C conflict resolution apply to each component before summing.
* FMP mapping, economic formulas, and the persistence schema are unchanged.

### The one live correction beyond MSFT

**COST FY2021 and FY2022 current debt changed**, correcting the value-level understatement 6A had recorded:

| Year | Before | After | Composition |
|---|---:|---:|---|
| FY2022 | 73M | **161M** | `LongTermDebtCurrent` 73M + `OtherShortTermBorrowings` 88M |
| FY2021 | 799M | **840M** | `LongTermDebtCurrent` 799M + `OtherShortTermBorrowings` 41M |

These are genuine Costco short-term borrowings that the single-concept path omitted; 6A listed them as a known gap. The effect is small (FY2022 ROIC 0.4033, invested capital 16,238M) but real, and excluding `OtherShortTermBorrowings` purely to freeze a golden number would have fitted the rule to the fixture. The COST test fixtures carry only `LongTermDebtCurrent`, so the characterization baseline is unaffected.

### MSFT FY2024, confirmed by the second provider

| | Before | After |
|---|---:|---:|
| Current debt FY2024 | 2,249M | **8,942M** |
| Total debt FY2024 | 44,937M | **51,630M** |
| ROIC FY2024 | 0.4627 | 0.4627 |

Reconciliation independently confirms the composed value: the MSFT FY2024 current-debt row moved from `EXPLAINED` to `MATCH` (MATCH 80 to 81), because SEC now reports the same 8,942M that FMP always did. The Slice 5C `KnownDiscrepancy` for it went stale and was retired, exactly as that audit trail intends. MSFT's verdict stays `ELIGIBLE_WITH_EXPLAINED_DIFFERENCES`; ADBE, V, and COST stay `NOT_ELIGIBLE`.

Reconciliation also surfaced the mirror image of the Costco lease case: FMP's `shortTermDebt` **omits** Costco's other short-term borrowings in FY2021 and FY2022 while **adding** lease liabilities in FY2025. A new `KnownDiscrepancy` records it with evidence.

## Survey: before versus after

Same 24 companies, same stored SEC snapshots (no content-hash change):

| | 6C (before) | 6D (after) |
|---|---:|---:|
| `FULL` | 4 | **5** (+CMG) |
| `PARTIAL` | 13 | 12 |
| `FAILED` | 7 | 7 |
| Companies blocked by current debt | **9** | **4** |
| Current debt `AVAILABLE` | 11 | **16** |
| Current debt `UNSUPPORTED` | 13 | **6** |
| Current debt `STRUCTURALLY_ABSENT` | 0 | **2** |
| Companies with a blocking input | 19 | 18 |

**Patterns solved:**

| Pattern | Companies | Resolution |
|---|---|---|
| Alternative concept (no `DebtCurrent`) | V, COST, MSFT, CRM, INTU, CAT | Component policy, no override |
| Components that must be summed | MSFT (commercial paper), AMZN and NKE (short-term borrowings), COST (other short-term borrowings) | Composition |
| Genuinely no current borrowings | META, CMG | Proven structural absence |

**Companies newly unblocked for current debt:** CRM, META, AMZN, INTU, and CMG. CMG reaches `FULL`. META and AMZN gain capital efficiency, and AMZN also gains economic value. For CRM and INTU the blocker moves to their genuine FY2021 `LongTermDebt` restatement, which 6C correctly refuses to resolve, so they remain `PARTIAL`.

**Remaining current-debt exceptions (4):**

* **HD, KO, LOW** — `LongTermDebtAndCapitalLeaseObligationsCurrent` is non-zero, so composition is refused (`COMPOSITION_BLOCKED`). Resolving these needs a decision about splitting debt from capital leases, not a mapping change.
* **NOW** — reports no current-borrowing concept and no debt totals, so absence cannot be proven. ServiceNow most likely has no current borrowings, but the payload does not say so.
* LULU is the same shape as NOW; it is already blocked by `cash`.

**No unexpected regression.** No golden company changed, no `LIKELY_BUG` or `ERROR` appeared, and the 24 content hashes are identical.

## Remaining blockers

Top blocking metrics after 6D: operating income (5 companies), current debt (4), long-term debt (3), cash (2), and revenue (2).

What-if over the post-6D diagnoses (18 blocked companies):

| Improvement | Unblocked alone | Cumulative |
|---|---:|---:|
| Catalog concept policy (restricted cash, NCI equity, `ProfitLoss`, `LongTermDebtNoncurrent`) | 3 (PG, CAT, UNH) | — |
| Long-term-debt alternatives and restatements | 2 (CRM, INTU) | with catalog: 5 |
| A policy for genuine revisions | 3 (CRM, META, INTU) | all three: 6 |
| Remaining current debt (debt/lease split) | 2 (HD, LOW) | — |
| Operating-income derivation | 0 alone (NKE, PFE, CVX, XOM, DE need other fixes too) | — |

Current debt is no longer the top blocker; **operating income** is.

## Tests

`tests/test_current_debt_composition.py` (30 tests) covers the ten required cases:

* single-concept current debt (total, and each single component);
* two-component composition with per-component provenance;
* the MSFT FY2024 commercial-paper case, including that other years stay single-source, and its flow into capital efficiency;
* no double counting: a reported total wins over its components (the ADBE 1,499/1,500 case), and restating concepts such as `ConvertibleDebtCurrent` are never summed;
* structural absence proven two ways, its downstream effect, and the two ways it must not be inferred;
* lease liabilities never added (three concepts), a lease-only company, and the unsafe bundle refusing composition (plus a zero bundle not refusing);
* recency and conflict resolution on components: a stale component set, a stale component still contributing to older years, a precision restatement resolved before summing, and a genuine conflict still failing;
* persistence provenance for composed and single-source facts;
* ADBE, V, and COST unchanged, and metrics without a composition policy unaffected.

The survey's composite-candidate registry is now empty (the pattern it measured is implemented) and a `COMPOSITION_BLOCKED` diagnosis reports the unsafe-bundle companies.

## What Slice 6D Deliberately Did Not Build

- splitting debt from capital leases in a bundled concept (HD, KO, LOW),
- inferring absence from a missing tag,
- a generic expression engine: the registry declares one optional additive composition, not arbitrary formulas,
- structured composition columns in the persistence schema,
- catalog-concept adoption, operating-income policy, or any change to FMP mapping or economic formulas.

---

# Slice 6E — Canonical Alternative-Concept Policy

## Goal

Decide, on evidence, whether the recurring SEC alternatives the 6A–6D survey surfaced are economically equivalent to the canonical metrics. Adopt only the genuinely equivalent ones, and record the rest so a later reader can see they were evaluated and rejected rather than overlooked.

## The register

`ALTERNATIVE_CONCEPT_POLICY` in `metrics.py` holds one `AlternativeConcept` per evaluated concept, each with a verdict, a rationale, and measured evidence from the 24-company snapshots. A test asserts that only `SAFE_EQUIVALENT` concepts appear in any preference list, so a concept cannot be adopted later without changing its recorded verdict.

| Concept | Metric | Verdict | Why |
|---|---|---|---|
| `LongTermDebtNoncurrent` | long-term debt | **SAFE_EQUIVALENT** | It states the canonical metric exactly |
| `ProfitLoss` | net income | SEMANTICALLY_DIFFERENT | Includes noncontrolling interests |
| `NetIncomeLossAvailableToCommonStockholdersBasic` | net income | SEMANTICALLY_DIFFERENT | Net of preferred dividends |
| `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` | total equity | CONTEXT_DEPENDENT | Right for ROIC, wrong for ROE |
| `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` | cash | SEMANTICALLY_DIFFERENT | Restricted cash is not owner cash |

### Adopted: `LongTermDebtNoncurrent`

The canonical `long_term_debt` metric is **noncurrent** debt: total debt is `current_debt` plus this series, so the two must not overlap. `LongTermDebtNoncurrent` says exactly that. `LongTermDebt` is ambiguous — some filers use it for the balance-sheet long-term line, others for the total including the current portion.

**This was a live correctness bug.** Since Slice 6D composed current debt for far more companies, pairing it with a `LongTermDebt` total double counted:

| Company | `LongTermDebt` | = Noncurrent | + Current |
|---|---:|---:|---:|
| MSFT FY2026 | 40,294M | 31,067M | 9,227M |
| CRM FY2026 | 14,439M | 10,439M | 4,000M |
| NVDA FY2026 | 8,468M | 7,469M | 999M |
| INTU FY2026 | 7,669M | 6,420M | 1,249M |
| NKE FY2026 | 7,942M | 5,942M | 2,000M |
| KO FY2023 | 37,507M | 35,547M | 1,960M |

NVIDIA — which 6C had promoted to `FULL` — was reporting total debt of **9,467M against a filed 8,468M**, a 999M double count flowing into invested capital and ROIC. Preferring the explicit concept fixes it, and NVDA's FY2026 total debt now equals the filed total exactly. CRM (14,439M) and INTU (7,669M) likewise reconcile to their filed totals to the dollar.

Adopting it also **removed the last debt overrides**: V, COST, and MSFT no longer need a per-company long-term-debt entry. Only Visa's equity override remains in the whole registry.

Filers that report no noncurrent concept (ADBE, HD, LOW) keep `LongTermDebt` unchanged, and 6B recency still governs the order, so a stale noncurrent concept falls back to a current total.

### Rejected: `ProfitLoss` and `NetIncomeLossAvailableToCommonStockholdersBasic`

`ProfitLoss` is consolidated profit **including** noncontrolling interests. OwnerLens net income is what the owners of the parent earn, and it drives FCF per share, margins, ROE, and the Feature 2 classifications. UNH FY2025 `ProfitLoss` is 12,807M against `NetIncomeLoss` 12,056M — **6.2% higher**; CVX, PG, and KO differ too, and DE's is *lower*. Substituting it would credit owners with income they do not own.

`NetIncomeLossAvailableToCommonStockholdersBasic` is net income after preferred dividends: ORCL 16,984M vs 17,087M, PG 15,754M vs 16,046M. It matches only for filers with no preferred stock.

**Consequence, accepted:** CAT's `NetIncomeLoss` is stale (last FY2010) and both alternatives are semantically different, so CAT stays `FAILED`. That is the correct answer, not a gap to paper over.

### Context-dependent: equity including noncontrolling interests

This is the one genuinely two-sided case. ROIC's numerator (NOPAT, from operating income) is **consolidated**, so equity including noncontrolling interests is the consistent denominator. ROE's numerator is **parent** net income, so parent equity is the consistent denominator. OwnerLens uses a single `total_equity` series for both, so no single choice is right for every filer.

Noncontrolling interest as a share of equity: UNH 6.0%, KO 6.1%, CVX 3.0%, PG 0.4%. At those levels the choice visibly moves ROE. The concept is therefore **not adopted generally**. Visa keeps its documented override because it reports no other equity concept and carries no noncontrolling interest at all, so for Visa the two are identical.

**Consequence, accepted:** PG, CAT, and UNH stay `PARTIAL`. Resolving them properly means either deriving parent equity (equity including NCI minus `MinorityInterest`) or holding two equity series — a change to the economics, not to normalization, and out of scope here.

### Rejected: restricted-cash-inclusive cash

Restricted cash is not available to owners, and OwnerLens cash feeds net cash and invested capital. The broader concept is **96% larger** for INTU (9,216M vs 4,705M — customer funds) and **46% larger** for Visa (24,987M vs 17,164M); AMZN and META differ by 3.3B each. Adopting it would overstate excess cash and understate invested capital. LULU, PG, and CVX therefore stay blocked on cash.

## Survey: before versus after

Same 24 companies, same stored SEC snapshots (no content-hash change):

| | 6D (before) | 6E (after) |
|---|---:|---:|
| `FULL` | 5 | **7** (+CRM, +INTU) |
| `PARTIAL` | 12 | 10 |
| `FAILED` | 7 | 7 |
| Companies with a blocking input | 18 | **16** |
| Long-term debt blocking | 3 | **0** |

**Newly unblocked:** CRM and INTU reach `FULL`. Their long-term debt had been `INVALID` because the genuine FY2021 restatement 6C refuses to resolve sits in the `LongTermDebt` total; the noncurrent concept they also file is cleanly reported, so reading the correct concept resolves it legitimately rather than by relaxing 6C. PG, CAT, UNH, and PFE gained long-term debt, though each remains blocked by another metric.

**Silently corrected:** NVDA, AMZN, NKE, META, CRM, INTU, and KO switched to the noncurrent concept. NVDA and AMZN had been double counting; the rest were blocked or unchanged in value.

**No unexpected regression.** ADBE, V, COST, and MSFT are unchanged, the characterization baseline is byte-identical, and the 5C reconciliation verdicts are unchanged (MSFT `ELIGIBLE_WITH_EXPLAINED_DIFFERENCES`, the rest `NOT_ELIGIBLE`). One cosmetic diagnosis shift: META's noncurrent series includes a stray FY2013 zero, so the survey flags `PERIOD_ISSUE` on an otherwise correct series; META is failed on capital expenditures regardless.

## Remaining blockers

| Metric | Companies | Nature |
|---|---:|---|
| operating income | 5 | NKE, PFE, CVX, XOM do not tag `OperatingIncomeLoss`; DE reports insurance-style concepts |
| current debt | 4 | HD, KO, LOW need a debt/lease split; NOW cannot prove absence |
| cash | 2 | PG, LULU report only the restricted-cash-inclusive concept |
| revenue | 2 | PFE genuine restatement; XOM successor registrant |

The rest are single-company: META capital expenditures (genuine restatement), AMZN repurchases (discontinued line), ORCL pretax income, CAT net income, UNH equity.

# Feature 6 closeout

## Recommendation: **A. Stop normalization and proceed upward**

Four normalization slices (6B recency, 6C restatements, 6D composition, 6E alternatives) moved full coverage from 3 to 7 of 24 and, more importantly, removed three classes of silent error: stale concepts masquerading as current, mechanical restatements failing as if genuine, and debt double counting. The override registry **shrank** from five company entries to one across 6D and 6E.

What remains does not justify another foundational slice:

* **No remaining issue is both broad and a correctness risk.** Every blocker is explicit. Nothing is silently approximated: the survey's silent-staleness count is zero, no rejected concept can be selected, and the composition and absence rules refuse rather than guess.
* **The largest remaining group, operating income (5 companies), is not a normalization problem.** It needs a derivation (revenue minus operating costs, or a segment roll-up) with real accounting judgment per industry — exactly the "large accounting-specific complexity" that disqualifies option B.
* **The next-largest, current debt for HD, KO, and LOW, needs an economic decision** about separating capital leases from debt, not a mapping. It affects 3 companies.
* **The rest are single-company quirks** or genuine source revisions that OwnerLens is right to refuse.

A fifth slice would buy a handful of companies at the cost of accounting-specific machinery, against a codebase whose failures are already explicit and auditable.

## Accepted limitation

> Unsupported companies remain explicit and are excluded or manually reviewed rather than silently approximated.

Concretely: a company that cannot produce a metric reports `UNSUPPORTED`, `INVALID`, or a proven `STRUCTURALLY_ABSENT`, with the reason and the concepts tried attached. Downstream layers degrade to `PARTIAL` or refuse to run rather than substituting a near-enough concept or a fabricated zero. Screening and valuation work must therefore treat the universe as **7 fully covered, 10 partially covered, and 7 excluded** of 24, and must not silently drop the distinction.

## Final coverage state

| | Count | Share |
|---|---:|---:|
| `FULL` | 7 (ADBE, COST, MSFT, CRM, NVDA, INTU, CMG) | 29% |
| `PARTIAL` | 10 | 42% |
| `FAILED` | 7 | 29% |

Against the 6A baseline: `FULL` 3 to 7, silent staleness 14 metrics to 0, ambiguous conflicts 13 to 3, current-debt blockers 9 to 4, long-term-debt blockers 3 to 0, and company overrides 5 to 1.

## Tests

`tests/test_alternative_concepts.py` (22 tests) covers, for the adopted concept: preference, no override needed, the double-count fix measured end to end, fallback for filers without it, 6B recency, 6C conflict handling, and 6D composition unchanged. For every rejected or context-dependent concept there is a regression test proving it is **not** silently adopted, including when it is the only concept available. Register-level tests assert every entry carries a verdict and evidence, and that no non-adopted concept appears in any preference list.

## What Slice 6E Deliberately Did Not Build

- a generic semantic ontology or concept-similarity engine,
- operating-income derivation,
- debt/lease separation,
- a policy for genuine restatements,
- parent-equity derivation or a second equity series,
- financial-company models.

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
| `STALE_CONCEPT` | The preferred concept has annual history but nothing recent. In 6A this included **silently stale** `AVAILABLE` series; since 6B a stale concept is never selected, so the finding is always `UNSUPPORTED` |
| `ALTERNATIVE_CONCEPT` | Exactly one catalog alternative has recent values; an override candidate, recorded and never applied |
| `COMPOSITE_CANDIDATE` | Two or more non-zero component concepts are needed, or the selected concept excludes a non-zero component (value-level) |
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

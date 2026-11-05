# OwnerLens v2 / M1 — Discovery Audit (Copilot Ready)

**Status:** Authorized next task is **diagnostic, read-only research**, not an implementation slice.  
**Scope:** Existing persisted FMP S&P 500 evidence + Feature 7 economic screen + adjacent Company/Feature 8/9A context.  
**Success:** Diagnose the largest *investment research opportunity* gaps and recommend exactly one small validated next improvement.

## 1. Mission and non-goals

OwnerLens v1 has completed core financial evidence, owner economics, six-dimensional coverage-aware screening, authoring v2, scenario underwriting, challenger, and cross-company comparisons. Five product cleanups were completed. Investor's primary workflow: **Discover → Understand → Underwrite → Challenge → Compare**.

The immediate objective is to improve the **quality and efficiency of research attention**, not to add shiny product features. We need to know whether the screen mostly finds established high-quality companies while missing improving, financially resilient, undervalued or otherwise asymmetric situations, and how to better separate fragility from uncertainty.

**Do NOT modify code, database, schema, source snapshots, FMP membership, seed test data, rankings, investment records, or UI during this audit.** Do not fetch latest live API data unless the investor explicitly requests a subsequent separate refresh. Work from the persisted store and clear data-vintage notes.

## 2. Read first

Repository files (actual paths/content take precedence; adapt if moved):

- `docs/PRODUCT_CONTEXT.md` and `docs/ROADMAP_V2.md`
- `docs/INVESTMENT_DECISION_PLAYBOOK.md` and `docs/DECISIONS_AND_BACKLOG.md`
- `README.md`, historical `ROADMAP.md`, `docs/PRD.md`
- `docs/feature_docs/feature_07_opportunity_screening.md`
- `docs/feature_docs/feature_08a3_universe_workbench.md`
- `docs/feature_docs/feature_09a_opportunity_comparison.md`
- Actual Feature 7 screening modules, FMP annual canonical adapter/storage, Company/Workbench projections, tests; inspect implementation instead of trusting older docs verbatim.

Be careful: older `README.md` and some docs may preserve pre-cleanup UX descriptions. Report observed implementation/current persisted values as distinct from docs and user anecdotes.

## 3. The questions the audit must answer

### A. Where does the existing funnel send attention?

- Count persisted FMP members, actual eligible/screened companies and FULL/PARTIAL/FAILED coverage, with source-as-of date, fiscal years and market dates where available.
- Top 20–30 under current rule-table ranking: ticker, company, sector/industry if known, priority, setup type, coverage, six dimension bands, score only where comparable, most relevant reasons and limiting factor.
- Group counts by priority/setup/coverage and show sector/industry concentration if available.
- Distinguish stable cash compounders from recovery/improvement candidates. Identify what the current ranking optimizes implicitly.
- Show why 5–10 tempting *non-top-ranked* names were excluded or ranked below top cohorts; they need not be investment buys.
- Do not infer absence from a missing provider record; label not evaluated.

### B. What does it systematically miss?

Investigate **false-negative candidate mechanisms**, not a handpicked list of beloved tickers:

- Businesses with historically mediocre compounding but improving current economics.
- Businesses with recent negative FCF due to heavy investment but plausible future positive cash conversion, while recognizing real financing fragility.
- Companies whose price fell substantially despite stable fundamentals (if reliable price history supports this; otherwise explicitly unavailable).
- High-ROIC businesses with transient margin compression or share count distortion.
- Mid-cap asymmetric ideas that the S&P 500 universe **cannot contain by design**; report as external coverage limitation, not a Feature 7 false negative.
- Data-coverage/industry exclusions (finance, insurance, REITs, special accounting), old/partial source periods, missing leverage metrics.

For each example, explain the exact current gate, bucket, band, source observation and plausible counterargument. Never claim the stock is undervalued without deeper valuation evidence.

### C. Does Feature 7 distinguish fragility from uncertainty adequately?

Inventory **existing** survival gates and balance-sheet/capital allocation bands first:

- 2 years of non-positive FCF
- net debt with non-positive FCF
- net debt above 6x latest FCF
- ROIC below 5% without sustained improvement
- diluted share CAGR >=5%
- balance sheet band, net-cash cushion flags, SBC/FCF and buyback funding rules

Test whether existing logic catches obvious financial traps *without* excluding economically resilient but uncertain companies. Identify metrics actually available for refinancing, interest cover, liquidity, capex/reinvestment and dilution. If maturities/interest coverage are absent, mark **NOT_SUPPORTED** and do not fabricate.

Provide a compact table for each potential fragility signal:
`Existing handling | Available facts | False-negative/false-positive examples | Missing data | Proposed scope (if any)`.

Do not duplicate a survival gate or invent an additive broad risk score.

### D. Is there enough price data to identify possible valuation dislocations?

Feature 7 today excludes price by design. Inventory FMP stored EOD price fields, dated pricing history (if any), quarterly evidence and market expectations:

- Exact date and temporal coverage for price vs fiscal-year owner economics.
- Whether price-to-normalized-FCF, FCF yield or similar first-pass *candidate* signals can be calculated reliably, and for what subset.
- What adjustment is needed for cyclical/negative or anomalous FCF, heavy capex, diluted share counts and net debt.
- Whether industrial operating companies vs banks, insurers and REITs can be compared on proposed metric.
- Why any candidate signal is **not** an intrinsic-value estimate or Buy classification.

Report **data-not-ready** if evidence is too weak. Do not assume a price trend exists simply because one EOD price is stored.

### E. What will universe expansion solve or not solve?

Document FMP cohort current company count and degree of complete coverage. Distinguish missing *opportunity discovery* due to lack of midcaps from weak *prioritization logic* within current companies. Estimate scope for a future **100–200 mid-cap pilot** (provider coverage, sector comparability, licensing/network, tests, latency, cache/store), but **do not implement ingestion or expand now**.

## 4. Run only read-only diagnostics

Examples (adapt to actual local CLI capabilities):

```powershell
uv run owner-lens screen --provider fmp
uv run owner-lens screen --provider fmp --detail
uv run owner-lens show ADBE
```

Inspect existing CLI JSON or persisted reports if needed. Avoid changes to investment records; avoid editing files, adding migrations or running `refresh-sp500` in this audit. If diagnostics create *derived reports*, put them in a clearly identified temporary/out-of-repo location or report to terminal and confirm the persisted database was not changed.

Run script-based numerical inspection only when necessary, using existing deterministic service functions; document each query's provenance and period. If current source state is missing or unavailable, report limitations instead of guessing.

## 5. Deliverables

### Deliverable 1 — Baseline screener audit

A short executive diagnosis plus tables for top candidates, cohorts, coverage, gate frequencies, and recurring economic/industry characteristics. Every ticker claim supported by actual persisted facts or labeled investor qualitative hypothesis.

### Deliverable 2 — False negative/false positive case studies

At least 5 useful counterexamples: companies that top-queue ranking may overrate or overlook. Explain **why** the existing rule behaves as it does and what evidence would resolve the issue. Include false-positive concern: a high-quality company can be expensive and unworthy of immediate underwriting at current price.

### Deliverable 3 — Fragility and uncertainty gap map

Existing safeguards, genuinely missing detectable signals, and where only human business-model judgment can supply information. State limitations of the existing 9A `MORE_FRAGILE` flag: only local one-variable sensitivity, not fundamental survival fragility.

### Deliverable 4 — Price/valuation-readiness assessment

What data is available, what candidate dislocation lens might be feasible, which companies/industries would be incomparable and how staleness must appear. No recommendation of cheapness without transparent definition.

### Deliverable 5 — Three candidate next slices, ranked by value/effort

For each:

| Field | Required answer |
|---|---|
| Research failure corrected | Current concrete missed/rejected/overrated candidate mechanism |
| Hypothesis | What measurable investor attention outcome will improve? |
| Minimal code surface | Existing services/files to reuse and likely small modifications |
| Invariants | No imputation, no revised historical underwriting, no mixed-price-date confusion |
| Counterexamples | What could go wrong/which cases should remain unchanged? |
| Tests | Unit regression plus local persisted FMP validation cases |
| Cost | Approximate implementation complexity (low/medium/high, no fictional hour precision) |
| Recommendation | Is this the one smallest first slice worth doing? |

**Select exactly one recommended first slice**, but do not implement it. Note if the most useful first outcome is a non-code research/process change.

### Deliverable 6 — Manual investor validation plan

How the owner can inspect 5–10 candidate names, manually rate research usefulness, and evaluate whether the predicted benefit actually occurred. Include date-bound sources and examples of what would falsify the proposed improvement.

## 6. Acceptance criteria and gotchas

- Must use *actual* persisted FMP evidence; if unavailable, say so and limit conclusions to code-level diagnosis.
- No look-ahead or cherry-picking based on future stock returns.
- Distinguish missing data from bad economics and true risks from generalized uncertainty.
- Show existing survival gates before suggesting new flags.
- Include price caveats and current-vs-frozen distinction.
- Do not use present screener rank as ground truth for the proposed improved rank.
- Do not invent a single universal best-stock score or automatic buy decision.
- Do not propose a React migration, new autonomous agents, cloud deployment, schema migrations or 2,000-company ingestion as part of this task.
- Do not re-underwrite any company, save new judgments or fabricate investment records.
- Explicitly label *observed facts*, *calculations*, *qualitative interpretations*, and *proposed hypotheses*.

## 7. How to report back to ChatGPT

Return an audit summary with: actual DB evidence dates, company counts and bucket distribution; 10–20 concrete examples; ranking/gating false-positive and false-negative findings; fragility/data gap table; price-readiness; three bounded next experiments; a single proposed first slice with tests. Include links to relevant code and report files if created outside persistent source/data.

**Stop after the audit.** Let investor+ChatGPT challenge the diagnosis and agree on one measured development step.

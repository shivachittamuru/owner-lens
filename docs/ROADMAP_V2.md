# OwnerLens v2 — Discovery-First Roadmap

**Draft strategy as of:** 2026-11-03  
**Precondition:** v1 stable baseline documented; do not label `v2.0.0` until a real research-value milestone is achieved.  
**Primary goal:** Improve opportunity discovery, qualification and comparison—not feature count.

## 0. Product north star and decision hierarchy

> **Maximize investment decision value per unit of user effort.**

**Primary loop:** Discover → Understand → Underwrite → Challenge → Compare.

**Secondary (later):** Portfolio-aware allocation/construction.  
**Longitudinal (later still):** Monitor → Learn → edge measurement.

### What success means

The near-term question is not “Can we compute more metrics?” It is:

> Given an investable universe and a finite research budget, can OwnerLens reliably put the most *worthwhile-to-investigate* companies in front of the investor, explain why, protect against obvious fragility, and enable reproducible cross-company underwriting?

Make two decisions distinct:

1. **Research attention:** which company merits the next 1–2 hours? Can be answered provisionally before intrinsic-value underwriting.
2. **Capital attractiveness:** which vetted opportunity plausibly clears the investor's expected-return hurdle at the observed price, with acceptable downside, resilience, uncertainty and evidence? Requires deeper work.

**The screen is a discovery queue, not a buy list.** Strong businesses may be overvalued; cheap-looking businesses may be fragile; missing data is neither safe nor unsafe.

## 1. Baseline evidence and core design

Feature 7 already screens persisted FMP S&P 500 histories on six interpretable bands with survival gates and coverage ceilings. The source is `src/owner_lens/screening*` and canonical documentation `docs/feature_docs/feature_07_opportunity_screening.md`; exact module paths must be confirmed in the local checkout. It intentionally excludes price and intrinsic value. Feature 8 provides actual scenario-based conditional economics after investor-authored assumptions; Feature 9A compares exact saved underwritings.

The primary strategic gap is **quality-oriented screening vs opportunity-oriented research prioritization**. This is where v2 must prove added value. Other gaps: financial-fragility nuance, uncaptured business model fragility, alternative ways to win, sensitivity to *correlated* shocks, missing screening signals for improving economics, and broader mid-cap coverage.

Not every gap deserves a feature. Audit the data and top candidates first.

## 2. Roadmap with decision gates

### Milestone M0 — Freeze v1; establish a clean handoff (no new investment features)

**Tasks**
- Full `pytest`, Ruff, mypy, git cleanliness; validate read-only discovery/underwriting/compare happy paths with the local FMP persisted store.
- Identify any unvalidated advanced paths and explicitly label them fixture-tested or deferred. Do **not** backfill fake decisions/events.
- Preserve a backup of the investment SQLite DB outside Git; tag the exact tested commit `v1.0.0` if not already tagged; avoid rewrite of existing tags.
- Commit handoff docs, code/test state and human-readable limitations together or in clearly labeled commits; determine exact tag boundary intentionally.
- Start fresh `OwnerLens-v2` conversation with the documents in this package.

**Exit:** reproducible baseline commit/tag and local validation results recorded. No claim of “fully live validated” for unused 9C/9D/Feature10 paths.

### Milestone M1 — Discovery Audit (read-only; **immediate next step**)

**Question:** What is our current S&P 500 screener *really* prioritizing, and which interesting opportunities does it systematically overlook?

**Work:**
1. Inspect actual stored FMP universe and the Feature 7 pipeline; report source dates, membership, coverage and exact gates/bands.
2. Produce top-20/30 ranked companies with explicit reasons and gating; inspect a separate set of rejected/low-priority/coverage-limited names, including plausible improving or temporarily pressured situations.
3. Evaluate whether top rankings are mostly already-recognized historical compounders; identify potential false negatives and why they are missed.
4. Break down **financial fragility** signals already captured vs not captured; distinguish metric absence, weak business economics, and potentially temporary negative FCF due to reinvestment.
5. Map available price/market and quarterly/expectation data; identify what could support a *candidate* dislocation flag without claiming intrinsic value.
6. Compare the effort of a better research queue inside 500 names versus scaling to 1,000–2,000 immediately.
7. Recommend exactly **one smallest high-value experiment**, with falsifiable prediction and benchmark.

**No writes to immutable records; no schema/provider/UX redesign; no implementation in the audit.** Specific task in `DISCOVERY_AUDIT_BRIEF.md`.

**Exit:** an evidence-backed diagnosis, top candidate case studies, 1–3 candidate improvements ranked by expected research value and cost, and an agreed first slice. Research usefulness, not merely screen reproducibility.

### Milestone M2 — Discovery Intelligence v2 (hypothesis-driven slices, not one monolith)

**Candidate slices, to select only after M1**

**M2-A: Distinct discovery lanes.** Make `DURABLE_COMPOUNDER` and `POTENTIAL_ASYMMETRIC_SETUP` functionally useful research views, not new buy labels. Keep current Feature 7 setup type where possible. Candidate lane should include improving economics with a survivable financial position, not reward fundamental collapse.

**M2-B: Explicit financial fragility flags.** Audit/reuse existing gates first. Candidates include refinancing and maturities (only if evidenced), debt/FCF and interest cover, persistent burn plus reinvestment burden, liquidity runway, share dilution dependency and reliance on external finance. Distinguish flag severity, persistence, temporal context, missingness and industry caveats. Financial data cannot establish moat erosion or multi-year capital availability without extra evidence.

**M2-C: Price-aware research candidate flags.** Consider current price vs supported *historical* owner economics such as normalized FCF yield, per-share cash conversion, debt-adjusted valuation or depressed valuation against stable fundamentals. Label as **valuation dislocation worth underwriting**, not intrinsic-value discount. Avoid mechanically favoring temporarily inflated FCF, high capital intensity underreported by FCF, cyclical peak profits, asset-light vs heavy accounting distortions, or stale prices. Compare cohort-specific metrics when necessary. No invented forward growth.

**M2-D: Improvement vs established quality.** Detect credible improving capital efficiency, per-share economics, cash generation or margin direction without equating rebound from negative denominator with 5,000% sustainable growth. Keep evidence-source and period-window comparability explicit.

**M2-E: Research queue UX.** A compact, sortable, explainable top-10 with evidence, unknowns, fragility reasons, optional candidate dislocation, and next question. Only after the logic is useful. No new app/framework.

**Safety/semantics:** research-priority candidate labels separate from Feature 8 valuation/classification; existing Feature 7 rules do not silently change under historical stored snapshots; version new outputs as needed and test deterministic ordering; preserve same-company/sector and coverage comparability limits. Do not turn a score into a recommendation.

**Exit for each slice:** measurable improvement on a reviewed benchmark, no loss of previously important candidates without grounded reason, and an investor-controlled inspection of the result using real FMP data.

### Milestone M3 — Underwriting Robustness & Cross-Company Judgment

**Question:** Of the shortlist that survived investigation, which opportunities offer the strongest *conditional expected returns relative to downside and fragility*, and where is the investor's edge?

Candidate scoped improvements:
- Add **risk structure** to company judgment: uncertainty, financial/business fragility, dependency concentration, multiple independent ways to win, permanent impairment path. This is an evidence-plus-judgment projection, not an unsupported deterministic “moat probability.”
- Compute base-case **hurdle breakpoints**: what revenue CAGR / year5 FCF margin / share count / terminal equity-FCF multiple would reduce expected or Base return below the explicit hurdle? Use existing assumptions and deterministic mechanics.
- Add *correlated stress* scenario, e.g. growth down + FCF margin compression + lower multiple + financing pressure, without pretending independent one-variable sensitivities measure total fragility. Investor specifies coherent stress; code calculates.
- Strengthen Feature 8 challenger: identify fragile dependency stacks, thesis-critical assumptions, conditional valuation vs genuine edge, disconfirming evidence. No automatic qualitative truth claims.
- Improve 9A cross-opportunity presentation: expected return, hurdle spread, Bear CAGR, loss scenarios, evidence strength vs presence, business quality, fragility, pricing dates and uncertainty. Keep tradeoffs explicit and no opaque master score.

**Distinction:** Feature 9A currently flags `MORE_FRAGILE` based on **max local CAGR perturbation**; this is *not* comprehensive enterprise/business fragility. Preserve definition; any broader concept needs its own transparent name and logic.

**Exit:** analyze several actual underwritten companies (e.g. ADBE/NOW/MSFT/GOOGL/META/UBER where matching stored versions exist) and show an analyst can explain not only which modeled return is higher, but why one thesis has a stronger floor and more independent ways to win. No claim of outperformance from scenarios alone.

### Milestone M4 — Bounded Company Universe Expansion

**Question:** Does adding mid-caps yield *new qualified opportunities* that the S&P 500 misses, after accounting for poorer coverage, liquidity and financial resilience?

- Only after the current funnel is demonstrably useful, experiment with a **bounded 100–200 additional-company cohort** (not 2,000 as a first step).
- Review universe definition/membership, survivorship bias, exchanges, dual classes, provider coverage/licensing, currencies, financials/REITs vs industrial operating company comparability, liquidity and capitalization constraints; do not silently compare dissimilar sectors on inappropriate ratios.
- Keep FMP operating provider; preserve SEC reconciliation/audit path. Do not multiply data calls or cached snapshots without a reason.
- Measure incremental unique qualified candidates, percentage missing/invalid, screen false positives/negatives and runtime/storage cost.
- Expand to 1,000–2,000 only if the cohort improves the research funnel materially.

**Exit:** demonstrably valuable new qualified businesses; no deterioration in evidence integrity and acceptable maintenance cost.

### Later: Priority 2 — Portfolio-aware allocation and construction

Reuse, do not replace, existing 9B/9C infrastructure. Only after discovery+underwriting are worth doing regularly:
- Actual holdings/cash exposures and as-of verification (no shadow-to-actual inference).
- Position sizing based on risk/downside budgets, max single name/sector/thesis exposure, liquidity reserves and evidence confidence.
- Recognize concentration in common economic drivers, not ticker count alone. Compare correlation and tail dependencies only with transparent, sufficient data; correlations can change in stress.
- Explore diversified asymmetric bets and all-weather *concepts* without making unsupported claims of a robust optimized portfolio, precise correlations or certain downside.
- Portfolio snapshot/policy lifecycle and provenance become worth building when frequently used; no automatic trades.

### Later: Priority 3 — Monitor, Learn, Edge

Keep Feature 9D and 10 foundations stable. Real earnings changes, approved decisions and mature outcomes create a reason to improve these workflows, not the other way around.

- **Deferred but specific:** selected-condition-derived 9D JSON template to avoid `condition_id` conflicts, with compatible predicate metadata, exact referenced underwriting and optional ChatGPT export. Never loosen validation or invent observations. Build only when real monitoring starts.
- Better 9C portfolio source/provenance lifecycle only when live holdings entered.
- Calibration/mistakes/attribution/Feature 11 only with mature, meaningful sample; don't manufacture synthetic longitudinal user data.

## 3. Release philosophy: hill-climbing instead of big-bang v2

**`v1.0.0`** = tested stable baseline as of actual selected commit, not a claim that every feature has been live exercised.  
**v2 development** = branch-per-small-slice on current main; no permanent divergence or duplicated Workbench.  
**`v2.0.0`** = a meaningful *validated investment-discovery* experience, not merely the new documents or research audit.

Per slice:

```
OBSERVE failure/limitation
  → formulate an investment-facing HYPOTHESIS and predicted measurable improvement
  → establish reproducible BASELINE cases
  → implement one smallest CHANGE
  → test correctness and preserved boundaries
  → investor runs LIVE validation on real FMP evidence
  → KEEP / REVISE / REVERT
```

**Prompt Copilot at each slice to state in advance**: existing behavior, proposed new observable behavior, success metric, misuse risk, files touched, and manual validation. No broad refactoring alongside new logic. `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`, `git diff --check`, plus local user exercise. Separate regression pass from investment usefulness.

## 4. Research-value measurement

Define a small **manually reviewed evaluation set** from the persisted universe. Date-stamp inputs and the investor's judgment criteria; do not contaminate with future information. Avoid optimizing criteria after seeing desired ticker rankings without recording the change.

| Measurement | Interpretation / safeguard |
|---|---|
| **Qualified-yield@10** | Share of first ten research candidates that survive a short factual/business/valuation triage to deserve deeper work; label judgments explicitly |
| **Time to qualified candidate** | Minutes spent from top-of-queue to “underwrite/watch/reject,” measured in actual use |
| **Coverage and unsupported rate** | Fraction with enough evidence for each dimension/price signal, stratified by sector and size |
| **Flagged fragile candidates** | How often flagged company has genuinely material potential impairment; track false positives too |
| **Missed candidates / seeded challenge set** | Named businesses the queue failed to surface, with date-appropriate reasons, without post-hoc cherry-picking |
| **Candidate variety** | Strong compounders vs resilient asymmetric/improving situations; not a quota for speculative names |
| **Ranking stability** | Small innocuous evidence differences do not wholly change priorities; genuine new economics may |
| **Readability and follow-through** | Can investor articulate in 30–60 seconds why each candidate surfaced and what to verify next? |
| **Underwriting conversion** | Fraction meriting full Authoring-v2 work; not every worthwhile research candidate must clear a 12% hurdle |

No metric alone proves an investing edge. Do not optimize “positive model returns” by assuming optimistic probabilities. **Counterexamples matter** as much as headline top-10 quality.

## 5. Key strategic tradeoffs decided / open

| Topic | Default direction | Reconsider when |
|---|---|---|
| S&P 500 (~500) vs 2,000 companies | Improve within current universe first | Audit identifies genuinely missed mid-cap upside; candidate cohort confirms |
| Fragility | Extend existing gates with grounded signals | Data shows false positives/negatives and a safer precise rule |
| Valuation in screening | Separate price-aware *candidate* signal, not full intrinsic value | Reliable normalized evidence, date and sector adjustment exist |
| Automatic stock ranking | Explainable research attention; no black-box buy score | No planned switch without robust out-of-sample evidence |
| React | Keep Streamlit + Python services | Repeated essential UI tasks can't be done without severe friction, API/product needs justify cost |
| New v2 Workbench | Evolve existing app progressively | A separate frontend has demonstrated ROI, not simply aesthetics |
| Learn Mode | Contextual terms + tooltip/glossary | After Discover/Company/Compare data presentations stabilize |
| Monitoring/learning | Preserve, don't build | Real recurring decisions/events and mature outcome history justify it |
| Agents/cloud | Deferred | Clear operational failure or requirement that deterministic/offline cannot meet |

## 6. Existing Workbench direction — not an immediate ticket

Future conceptual navigation: **Discover | Company | Compare | Portfolio | More** (advanced monitoring/learning/data quality). Underwriting and challenger belong naturally within Company. Avoid creating `workbench_v2` or a React rewrite now. Preserve all 1–10 capabilities via progressive disclosure. Make actual research results easier to read before changing routing.

## 7. Implementation milestones are proposals, not automatic commitments

**Do not ask Copilot to build all of M2–M4.** The authorized immediate next task is **M1 read-only Discovery Audit**. Decide the first actual code slice only after reviewing the audit with ChatGPT and the investor. The investor may change the roadmap based on observed usefulness.

See `DISCOVERY_AUDIT_BRIEF.md` for the detailed kickoff task.

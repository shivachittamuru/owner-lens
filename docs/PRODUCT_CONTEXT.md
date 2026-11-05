# OwnerLens — Product Context, v1 Baseline and v2 Operating Principles

**Updated:** November 3, 2026  
**Audience:** Owner/investor, ChatGPT (investment/research partner), GitHub Copilot (implementation partner)  
**Repository:** `shivachittamuru/owner-lens`  
**Status:** Handoff document; not a claim of release/tag completion.

## 1. Why OwnerLens exists

The project's highest-value objective is **to identify, understand, evaluate, and compare attractive long-term investment opportunities—and eventually deploy capital intelligently**. The point is not to replicate Stock Unlock, maximize the number of agentic features, or build a generic financial-data platform.

> **The most important outcome is discovering opportunities worth investigating, then identifying which genuinely deserve the investor's attention and capital.**
>
> ChatGPT is already helpful with company-specific analysis. OwnerLens's differentiated value is **systematic discovery, evidence-based prioritization, and consistent cross-company comparisons**.

The scarce resource is the investor's *time and attention*, followed by risk-bearing capital. Judge product changes by **investment decision value per unit of investor effort**. An especially useful near-term operating question:

> Does OwnerLens make it more likely that the *next company researched for two hours* was worth those two hours?

Ultimate aspiration: improve investment judgment, capital allocation, and the odds of long-term outperformance. These outcomes cannot be guaranteed or inferred from a short-lived screener benchmark.

### Primary workflow, v2

**Discover → Understand → Underwrite → Challenge → Compare**

The full eventual lifecycle remains **Discover → Understand → Underwrite → Allocate → Monitor → Learn**, but Allocate is priority 2, while Monitor/Learn are long-horizon capabilities rather than reasons to create activity today.

### Default investment philosophy

- Typical underwriting horizon: **5+ years**; default required expected return **~12% annualized** unless the particular underwriting explicitly uses another hurdle.
- **Strong floor + multiple ways to win + time on one's side.**
- Order of analysis: **business quality → balance-sheet resilience → optionality → valuation → leverage last**.
- Distinguish *uncertainty* (wide outcome distribution) from *fragility* (dependence on favorable conditions and potential permanent impairment).
- Price matters: a superb business is not automatically an attractive stock. High expected returns that depend on implausible terminal multiples or one heroic assumption need challenge.
- Do not deploy idle capital for the sake of staying invested. A well-supported WATCH/PASS is a valid outcome.
- Probabilistic Bear/Base/Bull math is a discipline for comparing beliefs, not precise prediction or a substitute for identifying an edge.

## 2. Division of responsibilities

| Layer | Owner | Meaning / boundary |
|---|---|---|
| **FACT** | OwnerLens from persisted sourced evidence | Filed or provider-reported financials, dated market price, identities, with provenance and explicit gaps |
| **EXPECTATION** | OwnerLens from captured consensus | Analyst estimates/market expectations, **not** investor forecasts or intrinsic value |
| **ASSUMPTION** | Investor, assisted by ChatGPT | Bear/Base/Bull revenue CAGR, FCF margins, share count, terminal equity-FCF multiple |
| **JUDGMENT** | Investor, assisted by ChatGPT | Business thesis, probabilities, variant view, required return, evidence interpretation, decision and sizing intent |
| **CALCULATION** | Deterministic Python OwnerLens | Owner economics, historical ratios, valuations, expected returns, constraints, comparisons, rule-based challenger |

Authoritative domain rules: the current repository's code and contracts, especially `docs/feature_docs/feature_08f1_underwriting_contract.md`. An LLM must **never quietly rewrite financial facts, plug missing input values, assign investor-approved probabilities, or make decisions/trades**. ChatGPT contributes business understanding, alternative hypotheses, forward-looking judgment, challenge, explanations, and authoring JSON; the investor explicitly approves.

Keep sourced **FACT** distinct from **CALCULATION**-derived historical metrics. Keep disagreement with analyst expectations (**variant**) distinct from evidence of investment **edge**.

## 3. Current architecture and workflow

```text
SEC structured filings ──┐
                         ├─> provider adapters ─> canonical histories (+ provenance)
FMP Premium statements ──┘                                  |
                                                          v
                             deterministic owner economics / capital efficiency
                                                          |
                                                  Economic Value Lens
                                                          |
                              Feature 7 coverage-aware opportunity screening
                                                          |
                       Streamlit Workbench / CLI / notebooks (persisted data)
                                                          |
                         Company Copy Research Context -> ChatGPT research
                                                          |
                             Feature 8 Authoring v2 JSON, investor approves
                                                          |
                deterministic 5Y scenarios / expected CAGR / variant / challenger
                                                          |
                         Feature 9A exact-frozen-underwriting comparison
                                                          |
                 (optional later) decision, sizing, monitoring and calibration
```

**Runtime:** Python 3.12+, `uv`, a `src/owner_lens` package, local SQLite with immutable/frozen objects where specified, Streamlit Workbench, CLI, typed app/domain services, `pytest`/Ruff/mypy. `OWNER_LENS_DB_PATH` selects the local store; provider-specific stores and annual evidence are separated. The Workbench reads **persisted data**; opening or navigating it must not cause SEC/FMP network refresh. Use CLI refresh/ingest separately.

**Provider roles:** SEC is the authoritative filed-facts reference and reconciliation/provenance pathway. FMP Premium is the practical broad-universe normalized operating source for the S&P 500; use `--provider fmp` for ordinary FMP-backed screening. Do not casually delete SEC normalization or treat FMP as identical to SEC. The old README may still call SEC the default; that is the documented CLI behavior, not an investor-facing product-priority decision. Future FMP-as-default UX is deferred.

**Key operational commands (verify in local checkout):**

```powershell
uv run owner-lens workbench --provider fmp
uv run owner-lens screen --provider fmp
uv run owner-lens screen ADBE MSFT --detail
uv run owner-lens show ADBE
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 --json # replace versions
uv run owner-lens refresh-sp500                   # provider refresh, not Workbench navigation
uv run pytest -q
uv run ruff check .
uv run mypy src
```

**Source/reference pointers:** `README.md`, historical `ROADMAP.md`, `docs/PRD.md`, `docs/feature_docs/feature_05_canonical_provider_boundary.md`, `feature_06_universe_coverage.md`, `feature_07_opportunity_screening.md`, `feature_07d_workbench.md`, `feature_08a3_universe_workbench.md`, `feature_08f1_underwriting_contract.md`, `feature_08f4_underwriting_authoring.md`, `feature_09a_opportunity_comparison.md`, `feature_09c_portfolio_sizing.md`, `feature_09d_what_changed.md`, and tests. The source code and latest feature docs take precedence over older prose.

## 4. What v1 actually provides

### Features 1–6: financial evidence foundation

- SEC identity/Company Facts and deterministically normalized annual histories. Provenance, fiscal-period duration rules, split/restatement treatment, explicit concept selection and unsupported states.
- Owner economics: revenue, operating income/margin, net income, operating cash flow, CapEx (positive expense), FCF and FCF/share, diluted shares and per-share compounding.
- Balance sheet and capital efficiency: cash, short-term investments, debt, invested capital, ROIC, leverage, capital efficiency guardrails.
- Economic Value Lens: direction and durability of cash economics, ROIC, per-share value creation, capital allocation, compounding and coverage limitations.
- Provider-agnostic canonical fact boundary, SEC/FMP reconciliation; 24-company SEC survey historical foundation; persisted FMP S&P 500 universe (~503 securities in Nov 2026 owner reports).
- No missing numeric item becomes zero; statuses such as `AVAILABLE`, `UNSUPPORTED`, `INVALID`, `STRUCTURALLY_ABSENT`, `NOT_EVALUABLE` are first-class.

### Feature 7: deterministic screening

Six dimensions: **business quality, capital efficiency, per-share compounding, balance-sheet strength, capital allocation, economic momentum**. Bands `STRONG` / `ADEQUATE` / `WEAK` / `POOR` / `NOT_EVALUABLE`. Coverage `FULL` / `PARTIAL` / `FAILED` and a coverage ceiling; reasoned priority `HIGH_PRIORITY` / `WORTH_UNDERWRITING` / `WATCH` / `LOW_PRIORITY` / `INSUFFICIENT_DATA`; setup `COMPOUNDER` / `POTENTIAL_ASYMMETRIC_SETUP` / `NEITHER`.

Existing **survival gates** already cover: 2 years persistent cash burn; net debt without positive FCF; net debt above 6x latest FCF; ROIC persistently below 5% without meaningful improvement; and persistent share dilution of 5%+ yearly. These should be audited and extended only if warranted, **not reimplemented** as a second fragility model.

The documented `screening_score` is an integer sum of up to six coarse bands; it orders *within a bucket* after coverage, not a universal valuation score; scores are not comparable across coverage classes. Low absolute margins are intentionally not scored across industries: a high-turnover business may be economically excellent at a 3% FCF margin. Falling ROIC with still-high ROIC level is not automatically proof of collapse.

**Critical limitation:** Feature 7 has **no stock price, valuation multiple, intrinsic value or expected return**. It prioritizes interesting *business economics* rather than attractive *securities at current prices*. This is a deliberate v1 boundary and the core v2 discovery gap.

### Feature 8: probabilistic underwriting

- Canonical **Authoring v2** JSON with assumptions and judgments only; company identity, starting financial state, price/date, evidence and expectations come from OwnerLens.
- Exactly 3 scenarios (Bear, Base, Bull), typically 5Y revenue CAGR, year-5 FCF margin, share CAGR, terminal **equity FCF** multiple; separate probabilities summing to one; 12% investor hurdle by default/explicit record.
- Deterministic year-5 FCF/share/terminal value/share and scenario CAGR; **expected terminal value is probability-weighted across terminal share values** and expected CAGR derives from that expected terminal value over the frozen price. **Never average scenario CAGRs as the expected return**.
- Variant perception compares investor Base expectations with captured market expectations; requires reasoning about genuine disagreements, not merely differences in numbers.
- Local sensitivity and a bounded deterministic/rules-only challenger. Challenger statuses/questions are advisory, not a validated independent adversarial analyst.
- Preserve frozen identities, evidence cutoffs, immutable versions and explicit analysis stage retry without creating new versions.

**Operational ChatGPT loop (live validated):** Company → Copy Research Context → ChatGPT business-specific analysis / judgment → complete Authoring-v2 JSON → Workbench Paste JSON → Validate & Preview → **Commit & Analyze** → Investment View. Historical finance rebuild is unnecessary when OwnerLens supplied it.

**Authoring contract pitfalls:** `variant_rationales` entries require driver, text, category and optional references. Supporting/disconfirming evidence entries use `references`, not `sources`. Thesis dependencies/breakers use `sources`. Reference objects support `title`, `uri`, `observed_at`, `note`; **not** a `date` field. Never invent missing reference verification or unsupported schema fields. Validate current schema before generating JSON.

### Feature 9: comparison and deliberate actions

- **9A:** exact immutable completed-underwriting comparisons of 2–5 companies. Current UI auto-selects latest *fully analyzed eligible* version with historical override and exact-version Company handoff. Display frozen price/date and individual hurdle. Deterministic pairwise flags include higher expected return, better Bear result, stronger documented variant, local sensitivity, evidence presence, business quality, tradeoff or conservative dominance; no magic aggregate investment score.
- **9B:** immutable investor-approved decisions, alternatives and optional independent $100 shadow counterfactuals. WATCH/PASS is not a holding; records are not proof of a trade.
- **9C:** explicitly approved portfolio snapshots, sizing policies, deterministic policy ceilings, exposures and downside budgets. No hidden portfolio context, execution, optimizer or auto-position creation. Cleanup 4 links comparison -> evaluate allocation -> record decision inline; missing/stale portfolio context remains explicit.
- **9D:** manual, exact-underwriting-linked change events, structured exact-match predicates, user approval classifications `NOISE` / `EVIDENCE` / `THESIS_UPDATE` / `THESIS_BREAK`; immutable event and separate approval; monitoring summary and re-underwriting handoff. No scheduled extraction or automatic thesis revision.

### Feature 10: longitudinal learning foundation

- **10A** immutable outcome observations, respecting interim/terminal distinction and no-look-ahead rules.
- **10B** sample-guarded forecast calibration (fewer than 5 eligible = insufficient, 5–19 = early signal, 20+ = reportable), terminal-region Brier only for eligible unambiguous outcomes. Never fabricate skill from small samples.
- **10C** approved mistake taxonomy and UNRESOLVED state; unapproved candidate diagnoses are not facts.
- **10D** process/forecast/decision/sizing/outcome attribution without presuming causality or inferring skill/luck.

**Current investor priority:** 9B–10D are secondary and should accrue genuine longitudinal history only when needed. Feature 11 Personal Edge is deferred until sufficient meaningful history exists.

## 5. Five product cleanups — completed in code, differing live validation

| Cleanup | What changed | Immediate demonstrated value and caveat |
|---|---|---|
| **1: JSON-first underwriting** | Paste/validate/preview, one `Commit & Analyze`, idempotent stage retry | User reported real NOW underwriting reduced from minutes/manual CLI to ~10 seconds. **High immediate ROI.** |
| **2: Investment View** | Compact one-place scenario/expected CAGR, hurdle, thesis, key risks, variant and challenger | Real Workbench screenshot validated; readable enough to use, minor prose density and labels pending. |
| **3: Opportunity Comparison** | Search/select 2–5 names, latest eligible versions, frozen dates/hurdles, pairwise explanations, exact Company handoff | User found insightful and valuable; tradeoff prose dense. Reported 1,674 tests; no full live verification claimed. |
| **4: Compare→Allocate→Decide** | Exact handoff, reuse saved policy/snapshot with freshness/provenance acknowledgment, inline investor-approved decision | Real META:1 ADD decision recorded with alternatives GOOGL:2, MSFT:2, ORCL:1; broader portfolio sizing behavior not independently live validated. 17 new tests reported. |
| **5: Monitor→Evidence→Approve** | Company-linked monitoring; paste JSON/preview/record+approve; safe retry; exact context for re-underwriting | 1,725 tests reported, 26 new monitoring tests. **No live validation** reported. Generic example JSON caused condition mismatches in attempted usage. |

**Important lesson:** Cleanups 1–3 are immediately helpful; 4–5 may become useful as actual decisions and events accumulate but are *not* immediate development priorities. Their remaining pain includes input/schema setup. Do not “fix” 4–5 simply to exercise them.

## 6. Known friction and current state—not to lose

- User observed 9D validation error **“JSON condition conflicts with the selected frozen condition.”** Root cause class: pasted example condition ID does not match the exact Workbench-selected frozen condition. Numeric predicate comparison also requires exact observable/unit/cadence/source-family definition. **Safeguard working as designed; user workflow missing context-generated JSON.** Defer a selected-condition-aware 9D template generator until genuine event usage, never relax matching to fix a test fixture.
- Streamlit/PyArrow warning was fixed at presentation layer: previously numeric `cashAndCashEquivalents` mixed with literal `"N/A"`; now nullable numeric DataFrames and styling. Focused tests and static checks reported passed.
- Separate Streamlit `provider` widget warning from simultaneous selectbox default and Session State assignment was diagnosed and a small Copilot fix suggested. **Its actual completion was not confirmed by user in this thread.** Verify before marking resolved.
- Cosmetic backlog: dense comparison reasoning, narrow reading width, duplicate challenger question, friendly human-readable enum labels, concise tooltip/glossary Learn Mode, provider UX simplification. None supersede discovery quality.
- Repo `README.md` and historical `ROADMAP.md` retain old commands/UX descriptions in some sections. Treat this handoff as strategy, the latest code and contracts as implementation truth; reconcile documentation only when necessary.
- GitHub files retrieved here reflect default branch, not the user's uninspected local Windows worktree. Never assume local branch clean, all commits pushed, tag exists, or the locally configured DB contents.

## 7. Architectural non-negotiables

1. Domain calculations and screening gates stay deterministic, versioned, testable Python—never delegated to Streamlit or an LLM.
2. Canonical facts retain provider provenance; FMP operating coverage does not erase SEC lineage. Source cutoffs and no-look-ahead matter.
3. Missing/unsupported metrics stay explicit (`UNKNOWN` is not healthy, unsafe, zero or no risk).
4. Immutable underwriting identity = stable ticker/security, UUID, version, hash; no editing frozen assumptions or backfilling frozen context. Historical scenarios use frozen price/date even when stale.
5. Research attention (Feature 7) ≠ investment attractiveness (Feature 8) ≠ portfolio suitability (9C) ≠ investor decision (9B) ≠ actual execution.
6. Candidate evidence/conditions are not investor-approved interpretations. No automatic decisions, trades, risk policy generation or autopilot monitoring.
7. No new infrastructure just because it is technically interesting: agents, retrieval stacks, cloud runtime, agent harness, ML ranker, React rewrite, unneeded schema extension, portfolio optimizer are opt-in only when proven valuable.
8. A missing price or non-comparable business model must not produce a confident “cheap” classification.
9. Users should primarily interact with **Discover, Company, Compare**; preserve advanced features but progressively disclose them rather than duplicate apps.
10. Each slice yields observable user-investment value, not only passing unit tests.

## 8. Who does what in v2

**Owner/investor:** runs FMP refresh and local Workbench; provides real-world checks; approves forward assumptions, probabilities, decisions, risk limits; compares usefulness of shortlist; decides when to allocate and when to use monitoring.

**ChatGPT:** strategic thought partner; assess business models and reinvestment, independently challenge narratives, author valid underwriting v2 JSON from *exact copied context*, analyze fragility vs uncertainty, audit Copilot output and suggest bounded next slices. No implied direct access to unpublished local database.

**GitHub Copilot:** inspects code and persisted data locally, implements narrow approved changes using existing services, runs offline tests/Ruff/mypy, prepares human-run live validation steps, reports changed files/assumptions. Default model Auto + Standard unless stronger reasoning is clearly justified.

## 9. v2 definition of success

- Discover 5–10 potentially interesting *research candidates* with defensible, comparable reasons and explicit financial fragility/coverage.
- Show a systematic path to high-quality compounders **and** credible asymmetric/improving businesses; avoid purely historical quality bias.
- Reduce wasted time investigating traps or uninteresting valuations; preserve surprising candidates rather than filter all uncertainty away.
- Shortlist leads to repeatable understanding, feature-8 underwriting, challenge and 9A comparison; never claim screener candidates are bargains without price-aware analysis.
- Compare useful research attention and conditional capital opportunity separately; no unexplained universal “best stock” score.
- Eventually use real portfolio context to select uncorrelated bets with downside-budget constraints—but do not build that before the discovery funnel produces valuable candidates.

See `ROADMAP_V2.md`, `INVESTMENT_DECISION_PLAYBOOK.md`, and `DISCOVERY_AUDIT_BRIEF.md` for operational plans.

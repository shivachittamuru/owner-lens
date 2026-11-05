# OwnerLens — Strategic Decisions, Architectural Guardrails and Deferred Backlog

**As of:** November 3, 2026  
**Purpose:** Avoid re-litigating settled questions and avoid implementing known lower-priority improvements prematurely. Items here are decisions or recommendations from the recent product strategy conversations; actual code status must be validated locally.

## 1. The accepted strategic decisions

| ID | Decision | Why / implication |
|---|---|---|
| D01 | **Focus primary v2 workflow on Discover → Understand → Underwrite → Challenge → Compare.** | Most immediate investment-research value; user has found first three cleanups useful |
| D02 | **Preserve eventual Discover → Understand → Underwrite → Allocate → Monitor → Learn.** | Deliberate allocation is priority 2; longitudinal monitoring/learning become useful with genuine data |
| D03 | **Maximize investment decision value per unit of effort.** | Selection criterion for features and UI work, not implementation sophistication |
| D04 | **First run a Discovery Audit, not a new implementation.** | Need current ranking failure modes, data coverage and false negatives before feature design |
| D05 | **Improve discovery within current FMP S&P 500 before extending to 1,000–2,000.** | More names cannot fix a low-quality research queue; revisit using a bounded mid-cap cohort |
| D06 | **Preserve Feature 7's current business-quality screening as the economic foundation.** | Deterministic, coverage-aware, explainable with existing survival gates |
| D07 | **Separate uncertainty from fragility.** | Volatility / forecast uncertainty alone should not exclude asymmetric opportunities; permanent impairment matters more |
| D08 | **Add financial fragility explanations/flags before making harsher gates.** | Missing inputs and temporary reinvestment must not be silently labeled dangerous or healthy |
| D09 | **Treat valuation dislocation as candidate research attention, not proven intrinsic-value discount.** | Feature 7 today excludes price; integrating price requires carefully dated, normalized evidence |
| D10 | **No opaque universal stock recommendation score.** | Use transparent business/return/downside/evidence axes, especially when tradeoffs and missingness exist |
| D11 | **Tag a locally validated v1 baseline, then hill-climb in small separately testable slices.** | Reproducibility and rollback; reserve v2 release label for actual discovery milestone |
| D12 | **Start a fresh `OwnerLens-v2` thread with context docs.** | Source of truth in repo, not indefinite chat history or incomplete memory |
| D13 | **Evolve existing Streamlit Workbench, not a second v2 Workbench.** | Existing Python/domain and app services have value; don't duplicate frontends/state or finance calculations |
| D14 | **Defer React until UX needs justify backend API + frontend migration.** | Not a trivial swap; focus on decision intelligence before presentation technology |
| D15 | **Keep advanced Features 9D/10, but stop developing them just to make them busy.** | They need genuine longitudinal decisions and outcomes; fake data undermines trust |
| D16 | **Keep ChatGPT judgment and OwnerLens computation distinct.** | Source facts/expectations vs assumptions/probabilities vs calculations vs approval remain auditable |
| D17 | **The default investor hurdle is ~12% annualized and horizon 5+ years.** | Record explicit per-underwriting differences; never normalize historical comparisons without disclosure |
| D18 | **Evolve research UI through progressive disclosure.** | Future Discover/Company/Compare/Portfolio/More conceptual layout; no global navigation redesign yet |
| D19 | **Every slice needs a predicted investment-research improvement plus real-user validation.** | Regression tests alone cannot show a better shortlist |
| D20 | **No premature agents, cloud deployments, performance tuning or portfolio optimizers.** | Build only to solve demonstrable problems |

## 2. How the product got here: five UX cleanups

### Cleanup 1: Single-action underwriting

Previous manual JSON-field editor, multiple CLI stages and repeated interactions replaced with JSON Paste → Validate + Preview → Commit & Analyze, exact-version retry and review. Real NOW test reportedly ~10 seconds instead of minutes. **Core insight:** automate deterministic mechanical work; preserve investor authorship.

### Cleanup 2: Company Investment View

Latest *fully analyzed* version, frozen price/date, probability/assumption table, expected return/hurdle/spread, thesis dependencies/breakers, variant, sensitivity, challenger. Human-readable summary before advanced provenance. High immediate investor utility. Backlog: overly wide prose, tiny text, duplicate question, enum labels.

### Cleanup 3: Opportunity Comparison

Search 2–5 businesses, latest eligible versions without manual `TICKER:VERSION`, exact handoff, preserved frozen identities, 9A pairwise tradeoffs. Immediately insightful; dense formatting. **Takeaway:** not every tradeoff is reducible to one winning stock.

### Cleanup 4: Comparison → allocation → decision

Inline handoff preserves exact versions and alternatives; loads saved portfolio/policy with dates and mandatory provenance confirmation; 9C sizing is policy ceiling, not recommended allocation; manual 9B decision persists separately. User's real META ADD record demonstrates decision capture and alternative reasons, but portfolio/policy lifecycle and live sizing remain lower-priority. Avoid making “ADD” imply execution. WATCH/PASS should not need synthetic portfolio inputs.

### Cleanup 5: Company Monitor

Single evidence validation/approval flow, exact condition pinned, retry-safe immutable records, re-underwrite handoff to Cleanup 1. Tested extensively but no live validation. Sample 9D JSON caused `condition_id` mismatch with selected frozen condition; exact matching is an important safeguard, but workflow still has authoring friction. Use real events before further optimization.

## 3. Current backlog — deliberately ordered by investor value, not engineering interest

### A. Active, immediate

| Item | Trigger / scope | Do not include |
|---|---|---|
| A1. **Read-only Discovery Audit** | Current FMP S&P 500 candidate ranking, false negatives, existing fragility gates, price evidence inventory | Changes to formulas, UI, provider, schema |
| A2. One bounded research-queue experiment | Only after audit: e.g. clear downside flags / improving business lane / price dislocation candidate | All discovery ideas at once, opaque score |
| A3. Test quality of research attention | Top-10 qualification and challenge set with real source-period data | Claims of future stock performance |

### B. Conditional, after the audit

| Item | Why potentially useful | Prerequisite |
|---|---|---|
| B1. Financial fragility risk flags | Catch leverage/refinancing, permanent burn, dilution dependencies before deep work | Metric availability and backtested case review |
| B2. Improving/turnaround screening lane | Avoid quality-only bias and surface temporary dislocations | Credible economic improvements and survivability |
| B3. Price-aware dislocation candidate screen | Connect business quality to *possible* current investment opportunity | Dated price, normalized cash economics, sector guards |
| B4. Company-level `risk_structure` | Clear uncertainty vs fragility vs dependency concentration vs ways to win | Explicit human/evidence boundary and a real underwriting use case |
| B5. Hurdle-breakpoints and correlated stress | Assess fragile assumption stacks and permanent impairment risk | Feature 8 analysis gap demonstrated by existing companies |
| B6. Comparative readability | Put expected CAGR/hurdle/bear/quality/risk up front; short pairwise explanations | Confirm UX friction recurs in actual analyses |
| B7. Bounded 100–200 mid-cap pilot | Test incremental research value vs 500-name universe | Working and measured shortlist in current universe |

### C. Deferred polish, reasonable eventually

- **Contextual Learn Mode / glossary:** short in-place explanations for screen priority, setup, coverage, ROIC, FCF/share, terminal equity FCF multiple, expected CAGR, hurdle spread, local sensitivity, variant, challenger, unsupported states; format “what it means / how to use / what not to infer.” Registry of terms versioned and reused across views. No intrusive inline walls of text. Optional deeper glossary once UX stable.
- **Investment View polish:** better long-text reading width, slightly larger type, deduplicate first challenger question, friendly display labels for `WORTH_UNDERWRITING`, `NO_IDENTIFIABLE_VARIANT_VIEW`, `OFFLINE_RULE_REVIEW_REQUIRED`, etc.; persisted canonical machine codes unchanged.
- **Comparison density:** upfront expected CAGR, hurdle, spread, Bear result, business quality; shorter pairwise prose, clear frozen dates, human-friendly badges. The `0%` modeled terminal-loss probability **does not** mean risk-free.
- **Provider experience:** FMP operational default, SEC as technical/advanced provenance selector; do not delete SEC code or duplicate data semantics. Fix sidebar Session State/default warning separately if still present.
- **Navigation:** consider Discover / Company / Compare / Portfolio / More as a progressive, single Streamlit app, not `workbench_v2`.
- **Docs:** thorough page how-to guides after high-value UX stabilizes; avoid large documentation rewrites each slice.
- **Obsolete UI helper deletion:** remove unreachable old underwriting-form helpers only if verified unused and simplifying; not needed during discovery audit.
- **Performance profiling:** discover current real bottlenecks before caching/index/pagination work for large underwriting histories or >1,000 companies.

### D. Deferred until actual portfolio or monitoring activity

- **9C portfolio provenance/policy lifecycle:** explicit actual-vs-fixture provenance, historical snapshots, policy versions, cross-session approval recovery, current holdings/cash verifications. Never silently treat latest snapshot as actual or current.
- **9D context-generated JSON templates:** selected frozen dependency/breaker → valid event skeleton, with exact `condition_id`, underwriting identity, observable/unit/cadence/source-family where available; ChatGPT only fills *new verified observation* and interpretation. Prevents actual reported `JSON condition conflicts with the selected frozen condition`. **Do not loosen exact validation**.
- **9D event-template assistance / uncommitted draft recovery:** only after real monitoring events are common; no agents or scheduled extraction before need.
- **9D baseline semantics:** new completed underwriting starts a new since-underwriting summary scope, old evidence remains immutable; consider carryover communication only if real workflow reveals gap.
- **Feature 10 learning/Feature 11 Personal Edge:** wait for real mature forecast, decision, sizing and outcome history; never claim measurable skill from short/few outcomes.
- **Portfolio construction:** position sizing, correlation/tail dependence and all-weather scenarios as a second-stage value proposition; only use supported actual holdings and explicit risk policy, not shadow positions.

### E. Technical hygiene—fix only when observed

- PyArrow mixed numeric/`N/A` warning was fixed in presentation, per owner's report (49 focused tests and static analysis).
- Streamlit provider selectbox warning (default value + same-key Session State) **was diagnosed; completion not verified**. If recurrence, do a small single-source-of-truth fix without mixing in provider redesign.
- Ensure source docs don't claim old form/editor workflow where Cleanup 1 replaced it. Revise relevant references only as needed for discoverability.
- Preserve exact input identities and no hidden network calls in Workbench page navigation.

## 4. Things deliberately not in the near-term roadmap

1. New autonomous agents for company discovery, thesis review, trade execution or portfolio orchestration.
2. New data provider abstraction where canonical FMP/SEC already works.
3. Expand SEC concept normalization for dozens of edge cases without concrete coverage returns.
4. Feature 11 edge, skills/luck measurement or backfilled decisions to make statistics look mature.
5. Cloud architecture, deployment, Kubernetes, RAG, vector DB or MCP integrations merely because of professional interest.
6. Separate React client or extra Streamlit v2 instance.
7. A single opaque “top buy” score; hidden human weights; automatic Bear/Base/Bull judgment and probability assignment.
8. Real capital allocation from hypothetical shadow portfolio state.
9. Silently rescore immutable underwritings using current prices or revised company narratives.
10. Full 2,000-company ingestion and performance optimization before demonstrating discovery usefulness.

## 5. Portfolio and learning risk boundaries

- No user chat transcript is proof of **current holdings, cash, cost basis, execution or policy**. Use investor-verified dated snapshots.
- Never equate `Record Decision` with a trade.
- Never infer actual portfolio from Feature 9B shadow entries; each shadow is independent `$100` counterfactual.
- Missing 9C portfolio/policy data is a valid missing-context outcome; WATCH/PASS still possible.
- A 9D candidate classifier does not approve anything. Evidence source metadata is an assertion of provenance, not independent source verification.
- Feature 10 outcome != decision quality, and process/research failures are not automatically skill, luck or causal explanations.

## 6. What to bring into a fresh v2 conversation

Keep the following distinct:

**Stable product charter:** `PRODUCT_CONTEXT.md`.  
**Development targets and gates:** `ROADMAP_V2.md`.  
**Investor reasoning model:** `INVESTMENT_DECISION_PLAYBOOK.md`.  
**Deferred decisions and risks:** this file.  
**Task spec:** `DISCOVERY_AUDIT_BRIEF.md`.  
**Local release state:** user's actual `git status`, test results, current tag SHA, store-as-of and live validation notes—not guessed from ChatGPT.

When uncertainty exists, ask Copilot for a **read-only inspection** of the exact relevant source code and local stored data; do not invent results from historical docs.

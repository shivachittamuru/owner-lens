# OwnerLens-v2 — Reusable ChatGPT Working Prompt

**Use:** Paste the *New-conversation bootstrap* below into a new ChatGPT thread named **OwnerLens-v2**. Attach the documents in this handoff package or link to the committed repo files. The new thread should not assume access to unpushed Windows local files, local SQLite records, or the exact present repository branch.

---

## New-conversation bootstrap — copy from here

I am continuing development of **OwnerLens**, my local-first, Python-based investment research and decision intelligence system.

**Repository:** https://github.com/shivachittamuru/owner-lens  
**Project:** OwnerLens-v2  
**Current status:** Features 1–10 and five product cleanups completed according to prior implementation reports; v1 freeze status and actual tag SHA will be supplied from my local Git. We are beginning a discovery-first product-improvement phase, NOT redesigning the entire system.

Please read and treat the following repo documents as the working context, in priority order:

1. `docs/PRODUCT_CONTEXT.md` — vision, philosophy, technical architecture, features, exact economic/authoring boundaries, known live-validation gaps.
2. `docs/DECISIONS_AND_BACKLOG.md` — settled product decisions, deferred features, UX and monitoring limitations.
3. `docs/ROADMAP_V2.md` — milestones M0–M4, decision gates, research-value criteria.
4. `docs/INVESTMENT_DECISION_PLAYBOOK.md` — investment reasoning, uncertainty vs fragility, economic value and research/capital distinction.
5. `docs/DISCOVERY_AUDIT_BRIEF.md` — the **immediate first task** (read-only, no code changes).
6. `docs/V1_RELEASE_CHECKLIST.md` — local baseline/release state, if relevant.

**North star:** Maximize investment decision value per unit of investor effort. OwnerLens's differentiated value is finding companies worth researching, providing deterministic trustworthy economics, and consistently comparing underwritten opportunities—not automating investment judgment or becoming a generic AI-agent/financial-data project.

**Primary v2 workflow:** **Discover → Understand → Underwrite → Challenge → Compare**. Next priority after success: portfolio-aware capital allocation and potentially resilient/uncorrelated portfolio construction using verified real holdings. Monitoring, calibration, mistakes and edge measurement remain long-horizon and do not warrant synthetic activity.

**Investment approach:** Typically 5+ years, explicit ~12% annualized hurdle (may differ by frozen underwriting), strong floor + multiple independent ways to win + time on my side, Quality → Balance Sheet → Optionality → Valuation → Leverage last. Distinguish *uncertainty* (range of outcomes) from *fragility* (permanent-impairment and dependency risk). Financial fragility may be screened with evidence; business-model fragility requires explicit judgment. Avoid letting exciting narratives overwhelm cash economics, valuation discipline or downside.

**Non-negotiable analysis categories:** FACT and EXPECTATION (persisted sourced evidence) → ASSUMPTION/JUDGMENT (explicitly investor-authored) → CALCULATION (OwnerLens deterministic engine). No missing-to-zero, price-date substitution, source fabrication, automatic probabilities, immutable-record rewrites, fake trade decisions, silent confidence, unsupported scores or model-produced financial facts. Preserve exact underwriting IDs/versions/hashes and frozen prices/dates. Research attention ≠ intrinsic value ≠ capital attractiveness ≠ portfolio fit ≠ actual execution.

**Existing strengths:** FMP-backed S&P 500 (~500 companies as of last owner report), SEC filed-evidence/reconciliation, six-dimensional Feature 7 screen, Economic Value Lens, Feature 8 probabilistic Authoring-v2 JSON + rules-only challenger, Feature 9A exact-version comparison, existing Streamlit UX. The first three product cleanups deliver immediate value; 9B/9C and 9D/10 are available but currently not main usage.

**Current strategic questions:** Which opportunities are being overlooked by our quality-oriented screener? Can we separate resilience from fragility and discover improving or temporarily mispriced businesses with a defensible research queue? What price-aware *candidate* signals are valid given FMP data? When should we pilot 100–200 mid-caps rather than immediately expanding to 2,000? How do we improve Feature 8 robustness and comparison after discovery quality is proven?

**Development style:** One hypothesis-driven hill-climbing slice at a time: observe → hypothesize → predict measurable improvement → baseline → smallest change → regression and provenance checks → my manual live validation → keep/revise/revert. Prefer existing Python services/Streamlit, not React/new Workbench/agents/cloud. Do not make me re-run historical normalization or retype data OwnerLens already captures. I use GitHub Copilot (typically Auto + Standard) to implement code and I personally run live validation. For every implementation prompt, include exact boundaries and validation checks, but **do not generate code until we decide on the right slice**.

**Your role:** Be a skeptical investment-research partner and engineering/product architect. Challenge my assumptions and the project's outputs. Distinguish repo-verified state from owner-reported local behavior and unvalidated suggestions. Provide focused, investment-useful reasoning and Copilot-ready prompts when requested. Do not fabricate current FMP universe results, company prices or locally saved portfolios. Where relevant, consult actual code/feature docs and make source dates explicit.

**First objective now:** Help me finalize any remaining v1 baseline verification, then run/review the **read-only Discovery Audit** from `docs/DISCOVERY_AUDIT_BRIEF.md` using Copilot in the real local repository. We will choose the smallest first v2 discovery experiment only after studying the findings. Do **not** start by implementing a fragility score, new screener, React rewrite or universe expansion.

My actual local baseline state is: `<paste git SHA, tag, tests, provider/store vintage and read-only smoke notes here; unknown until checked>`.

Please begin by giving a concise confirmation of the **product priorities, the single highest-value next step, and what evidence you need from the read-only audit**. Avoid proposing a large implementation until we've seen the actual screening evidence.

---

## Reusable implementation-request protocol (use later, not at kickoff)

When we have selected a specific v2 slice, I will ask you to prepare a Copilot task. Use this structure:

```text
OBJECTIVE
One investor-facing question; one measurable hypothesis.

CURRENT BASELINE
Observed actual persisted FMP/Feature 7/8 results and known limitations.

SCOPE
Smallest set of changes; specific services/components to inspect and reuse.

SEMANTICS
Existing data categories, exact versions, missingness, source cutoffs, no automatic buy/sell.

COUNTEREXAMPLES
False positives, false negatives, sector comparability and correlated risks.

TESTS
Focused deterministic cases plus full pytest/Ruff/mypy/diff checks.

MANUAL VALIDATION
One clear real-company, read-only or controlled-written workflow the investor runs.

COMPLETION REPORT
What changed, predicted vs observed research improvement, failures, and one deferred follow-up.
```

Use Copilot Auto + Standard by default; flag only when a complex architectural or ambiguous model-design change needs stronger effort. Do not use expensive models for routine lint/format/refactor.

## Reusable company-analysis protocol (use after discovery)

1. Start from **OwnerLens Copy Research Context**; its FACT/CALC are the accounting spine, consensus EXPECTATION is not a forecast.
2. Explain the business in accessible language: revenue drivers, margin drivers, reinvestment, why it wins, AI/disruption/competitive risks, 3–5 intrinsic-value variables.
3. Separate temporary from structural developments, uncertainty from fragility, and independent from correlated upside paths.
4. Create reasonable Bear/Base/Bull investor ASSUMPTION/JUDGMENT distributions with explicit provenance and probabilities, not management optimism or fabricated facts.
5. Produce **strictly valid current Authoring v2 JSON** only when requested. For example, `variant_rationales` requires driver/text/category; `supporting_evidence` and `disconfirming_evidence` use `references`; thesis conditions use `sources`; reference objects only title/uri/observed_at/note.
6. Let OwnerLens calculate scenario values, weighted terminal expected value and expected CAGR vs frozen hurdle. Then challenge correlation, downside, multiple sensitivity, variant vs actual edge, and compare exact underwriting versions.
7. Ask “Would I spend more time researching this? What invalidates the thesis? What evidence could change my mind?” Avoid buy/sell instructions without verified current pricing and portfolio context.

## Avoid these previously encountered traps

- Generic 9D fixture event JSON is **not compatible** with any arbitrary frozen condition. Exact `condition_id`, source family and metric/cadence requirements remain a safeguard. Context-derived templates are deferred until real monitoring usage warrants them.
- The current 9A `MORE_FRAGILE` is **local model sensitivity only** and is not a broad enterprise fragility verdict.
- Feature 7 quality ranking uses **no valuation price**; it cannot honestly claim a bargain.
- A strong FCF margin one year or high growth from a negative base may be misleading. Do not normalize unsupported facts.
- “No measured loss in the modeled scenarios” does not mean no real permanent-loss risk.
- The last reported 1,725 passing tests were from Cleanup 5; rerun and report the actual v1 release result.
- GitHub remote docs may lag the owner's local checkout; user-reported fixes may be unpushed.

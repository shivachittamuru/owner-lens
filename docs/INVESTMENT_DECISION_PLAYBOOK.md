# OwnerLens v2 — Investment Research and Decision Playbook

**Purpose:** Preserve the investing *reasoning* behind the product. This is not a new algorithm or a stock recommendation. It is the framework ChatGPT should use when evaluating screener design, company analyses, and comparative underwritings.

## 1. North star: strong floor, many ways to win, time on our side

A good company, a good investment opportunity and a good portfolio position are **three distinct claims**.

- A **good company** can earn durable high returns on reinvested capital and compound per-share owner value.
- A **good opportunity** adds a price and probabilistic outcome distribution: enough prospective expected return relative to a required hurdle, downside and evidence confidence.
- A **good portfolio addition** also accounts for existing exposure, concentration, liquidity, timing, common factors and downside budget.

OwnerLens v2 prioritizes finding *worthwhile research opportunities* before formal capital allocation. It must not discard an economically interesting business just because a first-pass price heuristic appears unappealing; a WATCH is valuable. Nor should it promote a seemingly cheap stock without a credible, survivable business.

## 2. The two-stage opportunity funnel

### Stage A — Discovery (screening / research attention)

Inputs: persisted FMP annual financials, their provenance, existing deterministic ratios and bands, and optionally price-aware candidate signals if validated. Outputs: **attention priority**, evidence availability, reasons, risk flags, what to verify next.

Example research questions:
- Does the business have an enduring economic engine? How cash-generative and reinvestment-efficient is it?
- Are per-share earnings/cash flows compounding, or only aggregate revenue and SBC-funded capital deployment?
- Is the balance sheet able to absorb multiple poor years?
- Is performance temporarily depressed or structurally deteriorating? What evidence separates those?
- Might the current valuation be pricing in overly pessimistic expectations? This is a **candidate question** until underwritten.
- What must be verified to avoid wasting a full underwriting session?

### Stage B — Underwriting (capital attractiveness)

Inputs: specific business model, competitors, economic drivers, expectations, observed price/date, explicit Bear/Base/Bull beliefs, probabilities, hurdle and challenge. Outputs: expected terminal value/share/CAGR, scenario downside, hurdle spread, fragility/uncertainty, evidence issues, alternatives and a reasoned investment choice. **Investor owns probabilities, approval and final position decision.**

**Hard separation:** a high Feature 7 screening bucket is not evidence of a stock discount; a positive Feature 8 modeled return is not necessarily a trustworthy risk-adjusted opportunity; a Feature 9A pairwise advantage is not a universal buy recommendation.

## 3. Uncertainty vs fragility — the key conceptual distinction

> **Uncertainty is not the enemy. Fragility is.**

**Uncertainty**: the plausible distribution is wide; the future path is hard to forecast. It may be *beneficial* to an investor when there is strong protection against permanent loss and multiple upside paths.

**Fragility**: business survival, per-share owner economics or thesis return is dependent on specific favorable conditions; failure of one condition causes disproportionate or permanent capital impairment. A business can look steady in normal periods but be brittle under stress.

| Risk structure | Interpretation | Research treatment |
|---|---|---|
| Low uncertainty / low fragility | Durable economics; potentially predictable compounder | Understand valuation and price paid; quality can be expensive |
| High uncertainty / low fragility | Wide upside possibilities but financial survivability and flexibility | **Important asymmetric setup** worth investigating |
| Low uncertainty / high fragility | Smooth near-term business with dangerous funding, leverage, concentration or margin-of-safety structure | Investigate latent tail dependencies, not just volatility |
| High uncertainty / high fragility | Many outcomes and significant impairment path | Treat as speculative/high risk; require exceptional price/edge if ever considered |

Do not equate accounting volatility, stock volatility, high capex, or an early negative FCF period automatically with fragility; check *funding, persistence, optionality, capital intensity, and cash conversion*. Conversely, recent positive cash flow does not prove financial robustness when debt maturities are near.

### Company-level `risk_structure` concept (not implemented today)

If an actual product gap warrants it, add a **separate, interpretable projection** with:

1. **Uncertainty:** width and source of possible outcomes, including what is unresolved vs unknown.
2. **Fragility:** need for favorable financing, growth, margins, pricing, market access, regulatory conditions or execution to survive.
3. **Dependency concentration:** how much of the thesis depends on one variable, counterparty, product, regulation or exit multiple; identify correlated dependencies.
4. **Ways to win:** multiple economically distinct growth, pricing, mix, operating-leverage, retention, reinvestment or optionality paths. Counting variations of the same AI monetization bet as independent ways is not honest.
5. **Permanent impairment:** the causal path to distressed financing, dilution, bankruptcy, permanent moat loss, adverse regulatory economics, or structurally sub-hurdle shareholder returns.

Evidence and investor judgment should be labeled. Do not convert qualitative risk into a fake precise probability or embed it in a black-box total score.

### Screener-level financial fragility (first candidate increment)

Audit current Feature 7 survival gates and coverage before proposing more. Potential **additive risk flags**:

| Candidate flag | What to look for | Caveat |
|---|---|---|
| Refinancing dependence | Debt maturity wall, interest costs, liquidity headroom | Only if dated debt terms are actually available |
| Persistent weak FCF plus heavy reinvestment | Cash burn and capex burden sustained without financing cushion | Growth investment may be productive; avoid one-year false positives |
| Dilution dependence | Share growth and SBC-to-FCF over time | Share count can reflect acquisitions or recapitalization; inspect cause |
| Thin cash cushion / weak interest cover | Positive or negative liquidity after plausible downturn | Provider data may not expose reliable interest expense or facilities |
| Capital-market-dependent business plan | Expansion requires capital raising / expensive external funding | Some business types naturally finance inventory/receivables; industry-specific |
| Financially fragile despite recent growth | Expansion in reported earnings but eroding cash conversion | Aggregate financial metrics may hide economic structure |

Missing fields must resolve to **UNKNOWN / NOT_EVALUABLE**, not “safe” or automatically “fragile.” Use flags first, not universal exclusions. Retain the possibility of asymmetric special situations that require case-by-case deeper analysis rather than prematurely filtering every weak FCF name.

### Company stress tests (later, after evidence)

**Break-even-to-hurdle robustness:** solve which decline in revenue CAGR, FCF margin, share count or terminal multiple would reduce Base or weighted expected returns below the investor's saved hurdle. Show inputs, method and caveats.

**Correlated stress:** jointly lower growth, reduce margin, increase reinvestment/leverage pressure and contract terminal multiple. This may reveal thesis dependence hidden by existing *one-variable-at-a-time* sensitivities. Do not report a historical statistical joint probability without supporting data.

**Independence test:** “three ways to win” is fragile if all require the same AI demand assumption or capital financing condition.

**Survival test:** Can the business reach year five without forced dilution, distressed asset sales or a broken competitive position if the Bear assumptions materialize?

## 4. Distinguish temporary impairment from structural damage

This distinction is particularly useful in mid-cycle downturns and when screening overlooked businesses. Require causal explanations:

| Evidence pattern | Could suggest temporary pressure | Could suggest structural impairment |
|---|---|---|
| Declining growth | Industry cycle, procurement pause, timing | Share loss, product substitution, exhausted TAM |
| FCF compression | Transitory buildout, working capital, temporary capex | Permanently higher capital intensity, weak unit economics |
| Falling margins | Mix/FX/sales investment | Weakening pricing power, customer disintermediation |
| Depressed valuation | Overreaction to known risk | Correct repricing of durable lower economics |
| High customer/segment concentration | Strong distribution contract | Single-point-of-failure / counterparty bargaining power |

Do not decide from a single metric; evaluate multi-year trend, incremental ROIC, cash conversion, competitive economics, debt and reinvestment needs. A historical good business can degrade structurally; a weak reported metric can mask improvement. Mark unresolved where evidence is insufficient.

## 5. Proposed discovery lanes

### Lane 1 — Durable compounders

High-quality businesses with positive multi-year FCF, stable/effective capital returns, strong ROIC, durable per-share economics, financial resilience, and multiple growth/reinvestment paths. Research question: **When is the price reasonable enough?** Recognize highly followed quality businesses may offer low forward returns at expensive prices.

### Lane 2 — Potential asymmetry and improvement

Resilient/improving business with temporary economic or sentiment dislocation, enough financial flexibility to survive and several plausible positive outcomes. Research question: **Are the problems temporary, and is the observed price too pessimistic?** Require demonstrated survival and avoid rewarding permanent burn, dilutive financing or purely narrative optionality. Economic value improvement may be more useful than historical band excellence.

### Lane 3 — Known fragility or insufficient evidence (review queue, not automatic wastebasket)

Highly levered, persistent cash-burning or incomplete financial-data cases. Prioritize only if a concrete special-situation thesis justifies deeper work; otherwise reduce attention. Keep unknown as unknown. Do not equate low priority with permanent avoidance or assume a specific price could never compensate.

Existing Feature 7 setup types are the starting point. Do not invent duplicate classifications without documented missing use case.

## 6. Make price aware without pretending to know intrinsic value

A low P/E or a high FCF yield is not automatically cheap. Proposed future price-aware candidate signals require:

- A clearly dated *current price* from the provider, not a silently refreshed frozen underwriting price.
- A financially valid numerator (e.g., normalized FCF), with seasonality, nonrecurring gains, working capital, capex cycle, and cyclicality guarded.
- Net debt and diluted share information where used; understand enterprise vs equity economics and FCF definition.
- Sector/business-model comparability and explicit data freshness.
- An “interesting dislocation / requires underwriting” label, **not** an implied discount to intrinsic value.
- Human research before treating cheapness as a capital allocation advantage.

Prefer a short explainable composite of *signals* or multiple independent columns rather than a hidden weighted alpha score. A business with low liquidity/cash conversion but low P/E should surface its risk beside the apparent discount.

## 7. ChatGPT-assisted company understanding

Once OwnerLens identifies a candidate, copy its actual Research Context and ask ChatGPT to explain, succinctly and in plain language:

1. How does the business **actually make money**? Customer, product/workflow, pricing unit, revenue engine.
2. What drives revenue: units/users/volumes, price/take rate, retention, mix, utilization, geography?
3. What drives margin and cash conversion, including stock compensation and working-capital structure?
4. What determines **reinvestment needs**, capital intensity and marginal ROIC?
5. What creates a moat and what could bypass/disintermediate it over 5–10 years?
6. What are the 3–5 variables that dominate intrinsic value and which are correlated?
7. What is the **strong floor**, what are the **independent ways to win**, and what could permanently break the company?
8. What must be true for Bear/Base/Bull; what source evidence supports and challenges each?
9. What does the *market appear to expect* (distinct from what we assume) and what variant/edge might exist?
10. What are the most valuable unanswered questions and fastest disconfirming evidence to seek?

Examples of variable decomposition (not factual opinions on current valuations):

- Visa: payment volume → cross-border mix → effective yield → operating leverage → capital returns.
- Salesforce: seats/workloads → pricing/retention → margins → SBC/dilution → AI substitution/monetization.
- Novo Nordisk: patients → treatment price/mix → GLP-1 share → manufacturing → pipeline/reimbursement.
- Qualcomm: device units/content → licensing economics → non-phone diversification → margin/royalty sustainability → competitive technology transitions.

Use real sourced data and current evidence when user asks for retrieval. For a pasted OwnerLens context with no external retrieval requested, make no fabricated source updates; label new qualitative assumptions transparently.

## 8. Scenario underwriting and edge

### Required structure

Bear/Base/Bull each carry: revenue growth, terminal FCF margin, share growth/dilution, terminal *equity FCF* multiple, and qualitative causal narrative. Weights total exactly 100%; investor must approve probabilities. The **price and horizon are frozen** and shown with dates. OwnerLens computes share value and compounded annual outcome.

**Expected CAGR formula** (where \(T\) is 5 years, \(V_i\) scenario terminal equity value/share, \(p_i\) probabilities, \(P_0\) frozen price):

```
expected_terminal_value_per_share = Σ (p_i × V_i)
expected_CAGR = (expected_terminal_value_per_share / P_0) ** (1 / T) - 1
hurdle_spread = expected_CAGR - required_return
```

Do not compute expected CAGR as Σ(p_i × CAGR_i): nonlinear aggregation changes the meaning.

### Challenge the valuation before feeling conviction

- **Assumption dependence:** Is the price justified only if high growth *and* high margins *and* rich exit multiple coexist?
- **Base plausibility:** Is Base realistically distinct from management aspirations or market consensus?
- **Bear realism:** Does Bear include survival costs, persistent dilution, leverage and competitive pressure?
- **Terminal multiple discipline:** Is the terminal multiple supported by the business's probable reinvestment needs and FCF durability?
- **Evidence falsifiability:** What future reported facts would change each key belief?
- **Uncertainty vs fragility:** Is this a wide but protected outcome, or a binary fragile dependency?
- **Edge:** Is there a specific market misconception, source advantage, analytical method, patience advantage or structural investor constraint? “Company is good” alone is not edge.
- **Sizing:** What permanent impairment and portfolio correlation could occur? This is later investor judgment, not automatic from the model CAGR.

### Fragility-sensitive position judgment (later)

Uncertainty may justify smaller initial sizing and broader outcome ranges. **Fragility may justify demanding more margin of safety, a stricter cap or passing altogether**, because the modeled favorable expected value may be unreachable if financing or viability fails. Do not assume individual Bear scenarios exhaust tails.

## 9. Compare and rank responsibly

**Two different lists:**

1. **Research queue:** screen candidates by documented economic signals, coverage, possible dislocation and fragile/unknown risks. It ranks *attention*, not stock attractiveness.
2. **Underwritten comparison:** 9A compares only exact completed frozen versions, with individual hurdle, market date, expected CAGR, Bear/Base/Bull, quality, variant evidence, local sensitivity, missingness and pairwise tradeoffs. It can explain which company has stronger modeled economics, but deliberately avoids declaring an overall capital winner when evidence conflicts.

**Do not collapse** business quality, expected return, uncertainty, fragility, valuation, evidence confidence and portfolio exposure into one unjustified score. Offer transparent axes and user-controlled filters. Comparisons should say “Company A has stronger Bear downside; Company B stronger modeled expected return, with larger terminal-multiple sensitivity,” not “B wins.”

For different saved price dates, do not imply contemporary buying opportunities: note that fresh price-aware evaluation may be necessary before actual cash allocation.

### Existing 9A flags and their limitations

- `HIGHER_EXPECTED_RETURN`: purely five-year modeled CAGR comparison.
- `BETTER_DOWNSIDE_PROTECTION`: higher Bear CAGR; **not** proof of all possible losses.
- `STRONGER_VARIANT_VIEW`: documented meaningful driver disagreement, **not** proof investor is right.
- `MORE_FRAGILE`: larger max local one-at-a-time CAGR perturbation, **not** comprehensive business fragility.
- `WEAKER_EVIDENCE`: missing evidence category, **not** independent assessment of persuasive truth.
- `HIGHER_BUSINESS_QUALITY`: ordinal Feature 7 band from frozen context.
- `DOMINATED` and `TRADEOFF`: conservative, contextual pairwise descriptions; dominance requires full comparable core and veto checks.

## 10. Examples and pitfalls from prior OwnerLens work

**ORCL:** cloud revenue excitement can mask capital-intensive buildout, debt and weak/negative normalized FCF. OwnerLens should not let a growth story force an attractive classification before per-share owner economics justify it; but must also examine whether a conservative model excludes a legitimately valuable growth transition. **Fragility is not the same as uncertainty.**

**ADBE:** AI has both substitution and monetization paths; per-share capital allocation and workflow durability matter. An attractive expected CAGR (historical user model) is a *conditional* conclusion, sensitive to long-run revenue/FCF margins and exit multiple; no universal guaranteed edge.

**GOOGL/MSFT/NFLX:** applying the same accounting and return formula can challenge intuitive enthusiasm. Historic comparative discussions showed valuations and hurdle conclusions changing materially when using OwnerLens's frozen price, FCF/share, capital intensity and consistent scenarios. The lesson is method discipline, not that any dated expected return is current.

**UBER:** transition to strong FCF can make it worth underwriting while share dilution, net debt and autonomy disintermediation remain structural uncertainties. Not every growth or ROIC number maps directly to resilient FCF/share ownership economics.

All examples are **historical research situations, not current recommendations**. Their facts/prices are as-of their archived underwritings or conversations and may have changed.

## 11. Personal research guardrails

- Never create fictitious evidence, holdings, portfolio limits, observations or completed monitoring events to satisfy a workflow.
- The default 12% hurdle is a minimum decision discipline, not an algorithm that makes every value >12% a BUY.
- Avoid behavioral noise: price declines without thesis change are not necessarily reasons to act; cash is a valid option.
- Prefer a small, high-quality queue of carefully explained candidates over an overwhelming ranked catalogue.
- Call out *why the world might be different* and what breaks the thesis, not just the upside scenario.
- Reserve 9B/9C/9D/10 for real decisions and eventual measurement; do not spend development cycles fabricating operational activity.

**End state:** OwnerLens should produce repeatable, auditable analysis while leaving investors with *better questions, fewer avoidable traps and clearer choices*.

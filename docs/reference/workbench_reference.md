---
title: "OwnerLens Workbench Reference Guide"
description: "Offline screening, immutable underwriting authoring and research-context workflows."
---

## Purpose

The OwnerLens workbench is the local, offline interface for understanding what the deterministic OwnerLens engine already knows.

Its job is to answer:

> **Where should I spend my next hour of research, and what does the evidence say so far?**

It is **not** a stock picker. Feature 7 directs research attention; Feature 8
shows deterministic scenario valuations and expected return from explicit
investor beliefs and a frozen price. Neither produces a buy/sell recommendation
or determines position size.

```text
Persisted SEC / FMP evidence
        ↓
Canonical financial history
        ↓
Owner economics + Economic Value Lens
        ↓
Feature 7 opportunity screening
        ↓
Workbench
        ↓
Deeper underwriting
```

Feature 7 answers **where to look**. Feature 8 underwriting assesses
**whether the opportunity is attractive at its frozen price under approved beliefs**.

## Launch

```powershell
uv run owner-lens workbench --provider fmp
```

Normal navigation reads persisted evidence only. It does not call SEC or FMP.

## Opportunity Comparison

Select **Opportunity Comparison** to compare 2-5 completed immutable Feature 8
versions. Choose exact `TICKER:VERSION` entries; nothing defaults to latest.
The read-only table follows return, Bear downside/asymmetry, evidence, variant,
sensitivity, business quality/setup and unresolved challenger questions.
Research attention and conditional capital attractiveness are separate outputs.
Pairwise flags explain tradeoffs or conservative dominance without an aggregate
score or allocation recommendation.

Missing frozen Feature 7 context remains missing; current screening is not
substituted. Excluded incomplete versions show explicit reasons. Expand each
opportunity for research questions and download reproducible JSON. The page
does not edit underwritings or retrieve new evidence. See
[Feature 9A](../feature_docs/feature_09a_opportunity_comparison.md) for the rules
and equivalent offline CLI commands.

## Portfolio Context and Position Sizing

Select **Portfolio Context / Position Sizing** to create or select an immutable
manual holdings snapshot, select an exact completed underwriting version, and
enter an explicit sizing policy. The policy has no prefilled limits. Review the
current weights, frozen underwriting economics, downside-budget ceilings,
evidence-quality cap, concentration constraints and incremental room.

The target interval begins at zero: no allocation is mandatory. Missing cash,
sector coverage or manual tags blocks additional deployment rather than implying
available room. An above-range holding is flagged without instructing a trim.
Review is a preview; checking the explicit-save box creates a new immutable
analysis. Saved analyses are read-only and downloadable.

An optional exact decision includes its frozen comparison/alternatives as context,
not positions. WATCH/PASS `ACTUAL_CHOICE` shadow entries never establish holdings.
This page neither creates a decision nor executes a trade. See
[Feature 9C](../feature_docs/feature_09c_portfolio_sizing.md) for schemas, equations,
conservative quality caps and manual validation commands.

## Decisions and Shadow Portfolio

Open **Decisions** directly, use **Company > Underwriting > Record decision for
this underwriting version**, or carry an exact comparison with **Opportunity
Comparison > Record a decision from this comparison**. Select the exact version,
enter an action and required investor judgment, explain considered alternatives,
and explicitly save. Every save appends a new immutable decision; existing
underwritings and decisions remain unchanged. History and JSON downloads are
separate and read-only.

Shadow creation is an explicit opt-in. **Shadow Portfolio** shows frozen starts
for the focal opportunity, selected alternatives and an optional S&P 500
placeholder. Each is an independent hypothetical $100 comparison, not a
portfolio weight or execution. No current prices, P&L or outcome-quality
judgments are shown. Missing benchmark prices remain explicit. See
[Feature 9B](../feature_docs/feature_09b_decision_shadow.md) for roles, schemas,
time safeguards and offline PowerShell commands.

# Pages

## 1. Overview

Use Overview to understand the research universe at a glance:

- securities tracked;
- `FULL` / `PARTIAL` / `FAILED` coverage;
- research-priority buckets;
- setup types;
- opportunity funnel;
- highest-priority research queue.

Treat the funnel as an **attention-allocation tool**, not a portfolio recommendation:

```text
~500 securities
    ↓
screenable businesses
    ↓
HIGH_PRIORITY / WORTH_UNDERWRITING
    ↓
companies worth deeper research
```

## 2. Screener

The Screener evaluates six deterministic dimensions:

1. Business Quality
2. Capital Efficiency
3. Per-Share Compounding
4. Balance-Sheet Strength
5. Capital Allocation
6. Economic Momentum

It answers:

> **Based on the economics OwnerLens can measure, how attractive is this company to investigate further?**

It does not use current valuation, intrinsic value, expected return, scenario probabilities, portfolio fit, or an LLM.

# Screener terminology

## Dimension bands

| Label | Meaning |
|---|---|
| `STRONG` / `STR` | Strong evidence |
| `ADEQUATE` / `ADQ` | Acceptable but not exceptional |
| `WEAK` / `WEK` | Material weakness or deterioration |
| `POOR` / `POR` | Serious weakness under current deterministic rules |
| `NOT_EVALUABLE` / `---` | Insufficient valid evidence to judge |

`NOT_EVALUABLE` is **not zero** and is not neutral. It is excluded from the score and constrains coverage.

## Business Quality

**Question:** Does this business consistently produce strong owner earnings?

Evidence includes persistent positive FCF, operating-margin direction, FCF-margin direction, and interruptions in cash generation.

**Mental model:** *Is the underlying economic machine good?*

## Capital Efficiency

**Question:** How productively does the business use invested capital?

ROIC is central. OwnerLens separates **ROIC level** from **ROIC trend**: level helps judge capital efficiency; trend contributes to economic momentum.

**Mental model:** *How much economic output does each dollar of invested capital produce?*

**Caveat:** generic ROIC and balance-sheet logic are not equally meaningful for banks, insurers, REITs and some other specialized businesses.

## Per-Share Compounding

**Question:** Is economic value actually compounding for each shareholder?

Evidence includes FCF/share growth, aggregate FCF growth, diluted-share changes, and whether buybacks merely manufacture per-share growth.

**Mental model:** *Is my slice of the economic pie getting bigger?*

## Balance-Sheet Strength

**Question:** How resilient is the company if conditions deteriorate?

Evidence can include cash, debt, net cash/net debt, changes in the balance-sheet cushion, and leverage relative to FCF where meaningful.

**Mental model:** *How difficult is this company to financially break?*

## Capital Allocation

**Question:** What happens to the cash after the business generates it?

OwnerLens considers repurchases, dividends, SBC, retained FCF, whether buybacks actually reduce shares, and capital returned relative to FCF.

**Mental model:** *Does management use cash in a way that benefits continuing owners?*

## Economic Momentum

**Question:** Are the company's economics improving or deteriorating relative to its own history?

This is **business-economic momentum**, not stock-price momentum.

**Mental model:** *Is the economic machine getting better or worse?*

A `WEAK` or `POOR` momentum result does not automatically mean a bad business. It can identify temporary deterioration worth underwriting.

# Screening score

```text
STRONG   = 3
ADEQUATE = 2
WEAK     = 1
POOR     = 0
NOT_EVALUABLE = excluded
```

Maximum score with six evaluable dimensions: **18**.

> **The score does not determine the research-priority bucket.**

OwnerLens applies gates, rules and coverage ceilings first. The score mainly orders companies **within** a bucket.

# Research Priority

Priority answers:

> **How soon should I spend expensive underwriting time on this company?**

It is research order, never investment advice.

## `HIGH_PRIORITY`

Measured economics are unusually strong and complete enough to justify serious research soon.

> **Put this near the front of the underwriting queue.**

It does not mean the stock is attractively valued.

## `WORTH_UNDERWRITING`

Enough economic strength or an interesting enough setup exists to justify deeper work, but meaningful weaknesses or questions remain.

## `WATCH`

Enough quality exists to retain interest, but stronger opportunities deserve research time first.

`WATCH` does not mean "bad company."

## `LOW_PRIORITY`

Current measured economics make this a relatively weak use of underwriting time versus the rest of the universe.

## `INSUFFICIENT_DATA`

OwnerLens cannot produce enough valid economics to screen reliably.

> **OwnerLens does not know enough.**

Do not interpret this as bearish evidence.

# Setup Type

Setup Type is orthogonal to Priority.

Priority asks **how urgently should I research it?**

Setup asks **why might it be interesting?**

## `COMPOUNDER`

An already-strong business displaying sustained owner-economic compounding.

> **A strong machine that may keep compounding.**

## `POTENTIAL_ASYMMETRIC_SETUP`

Strong underlying economics coexist with one or more meaningful current weaknesses.

> **Something good may temporarily look bad.**

This is a research setup, not a buy signal.

## `NEITHER`

The evidence does not clearly fit either archetype.

# Coverage

Coverage answers:

> **How complete is the evidence needed by Feature 7?**

It is not a quality score.

## `FULL`

Every analytical layer needed by screening produced usable output; all six dimensions can be evaluated.

## `PARTIAL`

Owner economics are usable, but one or more downstream dimensions cannot be evaluated reliably.

Coverage ceilings prevent missing negative evidence from becoming an advantage.

## `FAILED`

Owner economics cannot be built reliably enough for Feature 7.

> **Screening failed, not necessarily the company.**

Use Data Quality to determine why.

# Limiting Factor

| Value | Meaning |
|---|---|
| `FUNDAMENTALS` | Evidence is sufficient; measured economics constrain the result |
| `COVERAGE` | Missing/unusable evidence constrains the result |
| `BOTH` | Both economics and coverage constrain the result |
| none | No material limiting factor |

# Why it surfaced / What holds it back / What we cannot see

## Why it surfaced

Supporting evidence can include durable cash generation, exceptional returns on capital, improving ROIC, strong per-share compounding, shrinking shares, net cash, owner-friendly capital allocation, effective buybacks, and improving economics.

These tell you **what the screen likes**.

## What holds it back

Limiting evidence can include interrupted cash generation, contracting margins, falling returns, flat/declining per-share economics, dilution, shrinking net cash, leverage, heavy SBC, questionable capital allocation, and deteriorating economics.

These should become **underwriting questions**.

## What we cannot see

Coverage reasons explain where OwnerLens lacks enough valid evidence to judge. That is different from a negative conclusion.

# How to use the filters

## Highest-quality research queue

```text
Priority = HIGH_PRIORITY + WORTH_UNDERWRITING
Coverage = FULL
```

## Durable compounders

```text
Setup = COMPOUNDER
Business Quality = STRONG
Capital Efficiency = STRONG
Per-Share Compounding = STRONG
```

## Potential asymmetric dislocations

```text
Business Quality = STRONG
Capital Efficiency = STRONG
Balance Sheet = STRONG
Economic Momentum = WEAK or POOR
```

This hunts for:

> **A historically strong franchise experiencing potentially temporary economic deterioration.**

That pattern deserves underwriting, not automatic purchase.

## Coverage cleanup

```text
Coverage = PARTIAL or FAILED
```

Then use Data Quality to distinguish a fixable data problem from a genuinely unsupported model/business.

# Recommended reading order for one company

1. **Priority** — should this deserve attention now?
2. **Coverage** — how much should I trust the screen?
3. **Setup** — compounder, possible dislocation, or neither?
4. **Six dimensions** — where are the strengths and weaknesses?
5. **Why it surfaced** — what drove the positive result?
6. **What holds it back** — what needs investigation?
7. **Evidence** — what metrics support the claims?
8. Ask: **What is the single most important unanswered question?**

That question is the bridge from screening to underwriting.

## 3. Company

Use Company to inspect annual owner economics, capital efficiency, capital allocation, Economic Value Lens, screening evidence, provider/provenance, quarterly evidence, latest persisted EOD price, and clearly separated market expectations.

Preserve the semantic boundary:

```text
FACT ≠ EXPECTATION ≠ ASSUMPTION ≠ JUDGMENT ≠ CALCULATION
```

Quarterly evidence, EOD price and analyst expectations do not currently feed Feature 7's annual screening rules.

### Underwriting

The Underwriting tab displays the latest immutable version and as-of date,
with its frozen market price/date. `CAPTURED` means the record exists; it does
not mean valuation or challenger outputs have been saved for that version.
Absent outputs remain `N/A`, and no calculation or challenger runs automatically.
Use the displayed exact-version offline commands when you choose to generate them.

Read the section in this order:

```text
Expected return
→ Bear/Base/Bull
→ sensitivity
→ variant view
→ evidence
→ dependencies/breakers
→ challenger
```

* Start with expected five-year CAGR, your required-return hurdle, spread versus
  hurdle and conditional classification. Expected CAGR comes from the
  probability-weighted terminal value and frozen price, not averaged scenario
  CAGRs. Classification is an underwriting assessment, not a buy/sell recommendation.
* Inspect Bear/Base/Bull assumptions, manually approved probabilities, terminal
  value/share and implied scenario CAGR. These expose the beliefs behind the result.
* Check Base-case sensitivities and the recorded variant view: which inputs
  drive value, and where do your beliefs actually differ from captured expectations?
* Review business drivers, supporting versus disconfirming evidence, biggest
  uncertainty and most important variable. Missing evidence remains explicit.
* Read thesis dependencies (what must be true), breakers (what would invalidate
  the thesis) and next evidence to collect.
* Review saved challenger findings: assessment, strongest argument against,
  fragile assumptions, probability challenges, missing evidence and questions.
  Challenger commentary is advisory JUDGMENT, not verified FACT.

### Create or revise underwriting

Select **Create New Underwriting**. **Start from latest underwriting** copies
ASSUMPTION/JUDGMENT into a new draft, with feedback identifying the source and
next version. Existing versions remain immutable; saving appends a new version.
**Review Draft** is required before **Create Immutable Underwriting Version**.
Edits invalidate review. Drafts are not permanent underwriting records.

| Field hierarchy | Contents |
| --- | --- |
| Required, expanded | Each Bear/Base/Bull narrative, revenue CAGR, year-5 FCF margin, share-count CAGR, terminal FCF multiple and key dependency; three probabilities, probability rationale and required return |
| Required by current v2, in collapsed deeper-work sections | 3–5 business drivers, biggest uncertainty, most important variable, dependency/breaker statements and next evidence to collect |
| Recommended, collapsed | Variant rationales, supporting/disconfirming evidence, observables and thresholds |
| Optional, collapsed | Detailed sources/references, monitoring cadence/date, extra evidence metadata and policy rationale |

The current v2-required judgments still block review when empty. Recommended
omissions do not; supplied evidence/metadata must still pass domain validation.
The large OwnerLens facts/history/consensus context is a collapsed reference,
not a form to re-enter. Available presets require explicit investor selection.

```text
OwnerLens supplies FACT + EXPECTATION
Investor supplies/approves ASSUMPTION + JUDGMENT
OwnerLens produces CALCULATION
```

The Workbench form is the preferred human authoring experience. Versioned JSON
remains the durable import/export and CLI/testing contract. See the
[canonical contract](../feature_docs/feature_08f1_underwriting_contract.md) and
[authoring guide](../feature_docs/feature_08f4_underwriting_authoring.md).

### Copy Research Context

Select **Copy Research Context** to reveal compact Markdown for ChatGPT or
human reasoning, with Markdown and sanitized machine-readable JSON downloads.
No data is sent automatically; review the content before sharing.

The export distinguishes current persisted economics/screening from frozen
underwriting inputs. It includes nearest available captured forward consensus,
beliefs, available outputs and explicit missing data, without raw evidence
blobs, secrets or internal paths. Newer context does not alter an old version.

```text
OwnerLens evidence
→ ChatGPT / human reasoning
→ investor-approved judgment
→ new immutable underwriting version
```

### Feature 8 lifecycle

```text
Evidence
→ Immutable Underwriting
→ Deterministic Valuation
→ Market Expectations / Variant Perception
→ Probabilities / Expected Return
→ Challenger
→ Thesis Monitoring
```

Probabilities are manually approved when authoring; this reading sequence does
not imply automatic probability generation. Monitoring conditions, sources and
dates are structured, but monitoring is not automated or event-driven.

## 4. Compare

Use Compare for two-to-five-company side-by-side inspection.

Useful questions include:

- Which has stronger per-share economics?
- Which is more capital efficient?
- Which has the healthier balance sheet?
- Which allocates capital better?
- Are their compounding windows actually comparable?

Missing values remain `N/A`; unavailable dimensions remain `NOT EVALUABLE`.

Compare is not yet a complete capital-allocation decision because expected return, uncertainty and portfolio opportunity cost are not integrated.

## 5. Data Quality

Use Data Quality whenever you ask:

> **Why isn't this company screenable, or why is its coverage only partial?**

See [Data Quality & Coverage Reference](data_quality_reference.md).

# What the Screener deliberately does not know yet

Feature 7 does not currently determine:

- intrinsic value;
- expected return;
- bear/base/bull scenarios;
- probabilities;
- variant perception;
- qualitative moat durability;
- catalysts;
- portfolio fit;
- position sizing;
- personal investing edge.

Feature 8 surfaces scenario valuation, expected return, probabilities and
variant perception separately on Company; these do not redesign Feature 7 rankings.

A great business can be a poor investment at an extreme price. A temporarily weak business can be a wonderful investment if the weakness is misunderstood and price is attractive.

# One-line glossary

| Term | Plain-English meaning |
|---|---|
| Priority | How urgently should I research it? |
| Setup | What kind of research opportunity might this be? |
| Coverage | How complete is the evidence needed by screening? |
| Business Quality | Does the business consistently generate owner earnings? |
| Capital Efficiency | How productive is invested capital? |
| Per-Share Compounding | Is each owner's economic claim growing? |
| Balance-Sheet Strength | How financially resilient is the company? |
| Capital Allocation | Does management deploy cash effectively for continuing owners? |
| Economic Momentum | Are business economics improving or deteriorating? |
| Score | Ordering aid within a bucket; not the bucket setter |
| Limited By | What prevents a stronger research-priority result? |
| Why it surfaced | Positive deterministic evidence |
| What holds it back | Negative deterministic evidence |
| What we cannot see | Missing/unsupported evidence |
| `HIGH_PRIORITY` | Research soon |
| `WORTH_UNDERWRITING` | Interesting enough for deeper work |
| `WATCH` | Retain interest, but stronger candidates exist |
| `LOW_PRIORITY` | Weak relative use of research time |
| `INSUFFICIENT_DATA` | OwnerLens cannot judge reliably |
| `COMPOUNDER` | Strong sustained owner economics |
| `POTENTIAL_ASYMMETRIC_SETUP` | Strong underlying economics plus meaningful current weakness |

# Mental model to remember

The Screener is not trying to identify the cheapest stock.

It solves the first scarce-resource problem:

> **Out of hundreds of companies, where should I spend my next hour?**

```text
Feature 7: Where should I look?
Feature 8: Is this attractive at this price, under what assumptions?
Feature 9: What deserves capital relative to alternatives?
Later calibration: Where do I demonstrate repeatable investing edge?
```

This guide should evolve as later layers become real, while Feature 7 meanings should remain stable unless the screening contract itself changes.

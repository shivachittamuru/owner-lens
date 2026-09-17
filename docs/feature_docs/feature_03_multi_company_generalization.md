# Feature 3 — Multi-Company Generalization

## Purpose

Feature 3 answers the most important generalization question in OwnerLens:

> Is this a real financial engine, or just an Adobe analysis script?

Feature 1 and Feature 2 were intentionally developed against Adobe first.

Feature 3 removed the single-company assumptions and tested the architecture against deliberately different U.S. businesses.

The golden companies became:

- `ADBE` — Adobe
- `V` — Visa
- `COST` — Costco

These companies were selected because their economics differ materially.

Adobe is a high-margin software business.

Visa is a capital-light payment network.

Costco is a low-margin, working-capital-heavy retailer.

If the same financial abstractions survived all three, OwnerLens would have a much stronger foundation for a broader company universe.

---

## Feature 3 Strategy

Feature 3 progressed through three stages:

```text
3A
Generalize company identity

        ↓

3B
Generalize financial metric normalization

        ↓

3C
Run the full OwnerLens pipeline honestly
across multiple business models
```

The project deliberately postponed databases, scoring, and broad-universe ingestion until this foundation was validated.

---

# Slice 3A — Generalize Company Identity and SEC Resolution

## Goal

Remove the artificial Adobe-only restriction from company identity and raw SEC retrieval.

The existing SEC client was already mostly generic.

The main job was to stop saying:

> OwnerLens supports only ADBE.

and instead say:

> OwnerLens can resolve any appropriate company present in the SEC ticker mapping.

## What changed

The SEC layer removed:

- `SUPPORTED_TICKER`
- the ADBE allow-list gate
- SEC-layer `UnsupportedTickerError`

and introduced:

- `MalformedTickerError`

for invalid empty/whitespace ticker input.

## Failure semantics

OwnerLens now distinguishes:

### Malformed ticker

Example:

```text
"   "
```

Fails before any network request.

### Well-formed but unmapped ticker

The ticker is syntactically valid but cannot be resolved from the SEC mapping.

### SEC retrieval / trust-boundary failures

Remain separate typed failures.

## Canonicalization

Ticker input is case-insensitive and whitespace-normalized.

Examples:

```text
adbe → ADBE
v    → V
cost → COST
```

## Live validation

The SEC layer successfully resolved:

```text
ADBE → Adobe Inc. → CIK 0000796343
V    → Visa Inc.  → CIK 0001403161
COST → Costco     → CIK 0000909832
```

and retrieved valid Company Facts for all three.

## Important scope boundary

Only **identity and raw retrieval** were generalized in 3A.

Financial normalization remained Adobe-only until Slice 3B.

This prevented accidentally claiming broader support before the accounting rules had been tested.

---

# Slice 3B — Generalize Financial Metric Normalization

## Goal

Separate:

> canonical OwnerLens economic concepts

from:

> company-specific SEC XBRL tags.

The central question became:

> Can Revenue, Debt, Equity, CapEx, etc. mean the same thing inside OwnerLens even when different companies report them under different source tags?

---

## Canonical Metric Layer

Feature 3B introduced a small canonical metric-definition / resolution layer.

Conceptually:

```text
OwnerLens canonical metric
        ↓
default SEC concept preference
        ↓
optional company-specific replacement override
        ↓
duration / instant normalizer
        ↓
canonical observation + provenance
```

This avoids spreading code like:

```python
if ticker == "V":
    ...
elif ticker == "COST":
    ...
```

throughout the system.

---

## What Generalized Cleanly

Live SEC research showed that many important metrics worked across Adobe, Visa, and Costco using the existing concept preferences.

Examples included:

- revenue,
- operating income,
- net income,
- operating cash flow,
- CapEx,
- tax expense,
- pretax income,
- repurchases,
- SBC,
- dividends where applicable.

This was an important result:

> Most accounting concepts did not require company-specific hacks.

---

## Where Company Overrides Were Required

### Debt

Adobe and Visa/Costco exposed a particularly useful generalization problem.

Adobe's correct debt representation used:

```text
DebtCurrent
LongTermDebt
```

Visa and Costco required:

```text
LongTermDebtCurrent
LongTermDebtNoncurrent
```

A simple global fallback ordering would be unsafe because some alternate tags are stale for one company while correct for another.

Therefore Feature 3B established **replacement overrides**, not merely appended fallbacks.

This is a key architectural decision.

---

## Visa Equity Override

Visa required:

```text
StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest
```

because the plain `StockholdersEquity` concept was stale for Visa.

Again, the canonical meaning remains:

> Total stockholders' equity.

Only the source mapping changes.

---

## Visa Short-Term Investments

Visa's investment securities were deliberately **not** treated as equivalent to Adobe's corporate short-term investments.

OwnerLens chose the conservative policy:

```text
Visa canonical STI = absent
```

rather than broadening the definition and accidentally counting financial assets that did not match the intended economic meaning.

---

## Visa Diluted Weighted-Average Shares

A critical limitation emerged:

Visa did not expose the trusted US-GAAP concept OwnerLens needs for:

```text
WeightedAverageNumberOfDilutedSharesOutstanding
```

OwnerLens therefore marked this metric:

```text
UNSUPPORTED
```

It did **not** substitute:

- point-in-time common shares,
- an inferred denominator,
- another approximate source.

This became a central Feature 3 principle:

> Unsupported is better than fabricated.

---

## The Missing-Data Semantic Model

Feature 3B permanently encoded the distinction between:

### AVAILABLE

A trusted canonical value exists.

### STRUCTURALLY ABSENT

The metric genuinely does not apply / is not part of the company's program.

Example:

```text
Adobe dividends
```

### UNSUPPORTED

The metric may economically matter, but OwnerLens cannot currently obtain it through a trusted canonical mapping.

Example:

```text
Visa diluted weighted-average shares
```

### REPORTED ZERO

The company actually reported a zero economic value.

### INSUFFICIENT_DATA

An analytical result cannot be produced because required trusted inputs are missing.

These meanings must never be collapsed into one generic null/zero state.

---

## Provenance Survives Canonicalization

Even when two companies map different SEC tags into the same OwnerLens concept, the selected source concept remains visible.

Conceptually:

```text
Canonical metric:
Revenue

Company:
COST

Source concept:
<actual selected SEC concept>

Source filing:
10-K

Accession:
...
```

This allows collaborators and future agents to understand exactly how a canonical number was produced.

---

## Educational Notebook

Feature 3B added:

- `07_multi_company_metric_normalization.ipynb`

The notebook explains:

- canonical metrics,
- source tags,
- company overrides,
- provenance,
- absent vs unsupported,
- what Visa and Costco broke in the original Adobe assumptions.

---

# Slice 3C — Full Golden-Company Validation

## Goal

Run the complete OwnerLens pipeline across:

- Adobe,
- Visa,
- Costco.

The question was no longer:

> Can I normalize their revenue?

It became:

> Can the entire Feature 1 + Feature 2 system work honestly across multiple business models?

---

## Initial Visa Choke Point

Live validation exposed an important architecture issue.

`owner_economics_from_facts` required diluted shares unconditionally.

Visa's unsupported diluted-share fact therefore caused a failure that cascaded through:

- owner economics,
- annual economic value,
- compounding,
- capital allocation,
- company summary.

Yet many other Visa metrics were completely available.

This meant:

> one missing denominator was unnecessarily killing the entire analytical pipeline.

---

## Graceful Degradation Fix

Feature 3C made one narrow change.

If diluted weighted-average shares are unsupported:

```text
canonical diluted-share series = empty/unavailable
```

OwnerLens does not fabricate a value.

Downstream calculations naturally produce:

```text
FCF/share = None
```

and dependent classifications become:

```text
INSUFFICIENT_DATA
```

while independent analytics continue to work.

No broad optional-data framework was required.

This is a major robustness improvement.

---

## Coverage Layer

Feature 3C introduced a small read-only coverage reporter.

It represents:

- metric coverage,
- analytical-layer coverage,
- company coverage,
- human-readable coverage reasons.

It is not a workflow engine.

Its purpose is to answer:

> What can OwnerLens analyze for this company, and what prevents fuller coverage?

---

## Golden Company Results

### Adobe

Full coverage.

Representative results:

```text
Overall Economic Value: IMPROVING
FCF/share CAGR:          ~12.7%
ROIC:                    ~61.6%
```

Adobe remained the regression baseline.

---

### Costco

Full coverage.

Representative result:

```text
Overall Economic Value: IMPROVING
Compounding:             STRONGLY_COMPOUNDING
FCF/share growth:        ~9.9%
ROIC:                    ~40.9%
```

The importance of Costco was not whether the exact classification was attractive.

It proved that OwnerLens does **not** equate:

```text
high margins = good business
low margins  = bad business
```

Costco's low-margin business could still be recognized as economically strong through:

- compounding,
- per-share economics,
- capital efficiency,
- trajectory.

This validated that the Feature 2 logic was not simply Adobe-shaped.

---

### Visa

Partial coverage.

What works includes substantial parts of:

- fundamentals,
- capital efficiency,
- balance-sheet analysis,
- other non-per-share metrics.

But:

```text
diluted weighted-average shares = UNSUPPORTED
```

therefore:

```text
FCF/share                   unavailable
per-share annual analysis   INSUFFICIENT_DATA
per-share compounding       INSUFFICIENT_DATA
```

The important outcome is:

> Visa still produces useful verified evidence without OwnerLens pretending to know a per-share metric it cannot support.

---

## Threshold Generalization Audit

Feature 3C audited the deterministic Feature 2 thresholds across different business models.

Most survived as sufficiently general.

One important caveat emerged:

> fixed FCF/share CAGR bands may eventually need more context-aware interpretation.

The future issue is not necessarily "software thresholds vs retail thresholds."

A more precise framing is that growth quality may depend on context such as:

- maturity,
- reinvestment runway,
- ROIC,
- capital intensity,
- cyclicality,
- durability.

No threshold values were changed in Feature 3C because no clearly incorrect generic assumption had yet been demonstrated.

---

## Golden-Company Coverage Philosophy

Feature 3 established that success is **not**:

```text
every cell must be green
```

Success is:

```text
every green, absent, unsupported,
zero, and insufficient state is truthful.
```

This matters enormously for future:

- screeners,
- scores,
- databases,
- agents.

A future agent should prefer:

> "I cannot compute this because the trusted denominator is unavailable."

over:

> "Here is a plausible-looking number."

---

## Feature 3 Architecture

By the end of Feature 3:

```text
Ticker
  ↓
Generic SEC identity resolution
  ↓
Raw Company Facts
  ↓
Canonical metric registry
  ↓
Default concept mapping
  + narrow company overrides
  ↓
Trusted normalized facts
  ↓
Feature 1 metrics
  ↓
Feature 2 economic-value analysis
  ↓
Coverage model
```

This is the point where OwnerLens became a genuinely multi-company financial foundation.

---

## Tests and Quality

By the end of Feature 3, the suite had grown substantially while preserving all prior behavior.

Examples of permanently tested invariants include:

```text
AVAILABLE ≠ STRUCTURALLY_ABSENT
AVAILABLE ≠ UNSUPPORTED
UNSUPPORTED ≠ zero
INSUFFICIENT_DATA ≠ zero
```

and Adobe regression behavior remained intact.

---

## Educational Notebook

Feature 3C added:

- `08_golden_company_validation.ipynb`

It documents:

- why the golden companies were chosen,
- what generalized,
- what broke,
- partial coverage,
- business-model diversity,
- remaining blockers before scaling.

---

## What Feature 3 Deliberately Did Not Build

Feature 3 did not yet introduce:

- database persistence,
- batch ingestion,
- S&P 500 coverage,
- Azure infrastructure,
- scores,
- screeners,
- valuation,
- agents,
- market-price data.

Those would be premature without trustworthy multi-company semantics.

---

## Feature 3 Outcome

Feature 3 proved that the project's central architecture can support meaningfully different businesses without sacrificing correctness.

OwnerLens now understands the difference between:

> different source tags for the same economic meaning

and:

> genuinely different or unsupported economic concepts.

The result is no longer an Adobe-specific notebook system.

It is becoming:

> **a deterministic, provenance-backed financial intelligence substrate for U.S. public-company analysis.**

The next logical requirement is persistence:

> How do we store companies, source snapshots, canonical facts, metrics, coverage, and analysis history so OwnerLens can scale beyond in-memory analysis?

That begins Feature 4.

# Feature 2 — Economic Value Lens

## Purpose

Feature 2 turns trustworthy fundamentals from Feature 1 into a compact owner-oriented interpretation of the business.

The central question is:

> If I owned the entire business privately and ignored the stock price, are the economics of my ownership improving?

Feature 2 does not attempt to calculate intrinsic value.

Instead, it separates:

```text
Economic Value Creation
        ↓
Intrinsic Value
        ↔
Market Price
```

Feature 2 focuses on the first layer.

---

## Design Philosophy

Feature 2 remains deterministic.

It does **not** use:

- LLM judgment,
- hidden scores,
- weighted 0–100 systems,
- stock price,
- valuation multiples.

Instead it consumes Feature 1 outputs and produces:

- explicit classifications,
- structured reason codes,
- transparent evidence.

The system is intentionally explainable.

---

## Slice 2A — Annual Economic Value Snapshot

### Goal

Answer:

> Did the company's observable owner economics improve this year?

### Inputs

Feature 2A consumes existing Feature 1 outputs such as:

- revenue,
- operating margin,
- FCF,
- FCF margin,
- FCF/share,
- diluted shares,
- ROIC,
- net cash/debt.

It does not call SEC directly.

### Level vs change metrics

A major design distinction is preserved between:

#### Level metrics

Examples:

- operating margin,
- FCF margin,
- ROIC,
- net cash/debt.

#### Change metrics

Examples:

- revenue growth,
- operating-margin change,
- FCF growth,
- FCF/share growth,
- share-count change,
- ROIC change.

This prevents a high absolute level from being confused with improvement.

### Annual classification

Feature 2A introduced coarse deterministic states:

- `IMPROVING`
- `STABLE`
- `DETERIORATING`
- `INSUFFICIENT_DATA`

### Per-share primacy

FCF/share growth is the primary annual owner signal.

Why?

Because aggregate growth can overstate owner benefit when dilution is high.

Example:

```text
FCF grows +10%
shares grow +15%
```

Aggregate company cash generation improved, but each owner's claim may have worsened.

### Guardrails

The annual verdict is tempered by factors such as:

- severe ROIC deterioration,
- real balance-sheet deterioration,
- margin changes,
- dilution.

### Transparent drivers

Instead of a mysterious score, each classification carries deterministic drivers such as:

```text
FCF_PER_SHARE_STRONG_GROWTH
SHARE_COUNT_DECLINED
ROIC_EXPANDED
```

### Important live correction

Adobe live validation exposed an over-aggressive leverage rule.

The original logic treated a decline in net cash as deterioration even when Adobe was simply deploying surplus cash into buybacks while remaining net-cash positive.

The rule was corrected so deterioration means something economically meaningful, such as:

- turning into net debt,
- deepening an existing net-debt position.

This was an important example of real company validation improving the interpretation layer.

---

## Slice 2B — Multi-Year Economic Compounding View

### Goal

Answer:

> Over several years, what kind of economic compounding machine has this business been?

### Core metrics

Feature 2B calculates multi-year:

- Revenue CAGR
- FCF CAGR
- FCF/share CAGR
- Diluted-share CAGR

and compares start/end:

- operating margin,
- FCF margin,
- ROIC,
- net cash/debt.

### Correct CAGR interval semantics

A critical correctness rule was established:

```text
FY2021 → FY2025
```

contains **four compounding intervals**, not five.

Therefore:

```text
CAGR = (Ending / Beginning)^(1 / intervals) - 1
```

OwnerLens labels views using actual fiscal-year intervals.

For example:

```text
FY2022 → FY2025 = 3-year CAGR
FY2021 → FY2025 = 4-year CAGR
```

When more history becomes available, the long view can naturally become a true five-year CAGR.

### Adobe result

For Adobe, the long view showed approximately:

```text
Revenue CAGR        +10.8%
FCF CAGR             +9.4%
FCF/share CAGR      +12.7%
Share-count CAGR     -2.9%
ROIC                 ~40% → ~62%
```

### Key owner insight

Adobe's per-share cash generation compounded faster than aggregate cash generation because the share count shrank.

This is the core difference between:

> business growth

and:

> owner growth.

### Compounding classification

Feature 2B introduced:

- `STRONGLY_COMPOUNDING`
- `COMPOUNDING`
- `STABLE`
- `DETERIORATING`
- `INSUFFICIENT_DATA`

The classification is not an average of annual verdicts.

### Buyback illusion guardrail

Feature 2B explicitly distinguishes:

#### Healthy per-share amplification

```text
FCF grows
shares shrink
FCF/share grows faster
```

from:

#### Shrinking underlying business masked by buybacks

```text
FCF declines materially
shares shrink even faster
FCF/share appears positive
```

This prevents buybacks from automatically making a deteriorating business look excellent.

---

## Slice 2C — Capital Allocation Lens

### Goal

Answer:

> What did management do with the cash the business generated, and did those decisions help owners?

### New reported facts

Feature 2C added canonical normalization for:

- Share Repurchases
- Stock-Based Compensation
- Dividends Paid

### Adobe concepts

Live SEC research established:

- Repurchases — `PaymentsForRepurchaseOfCommonStock`
- SBC — `ShareBasedCompensation`, with fallback support
- Dividends — structurally absent for Adobe

### Absence is not zero

Adobe has no dividend program.

OwnerLens does not fabricate:

```text
dividends = 0
```

when no canonical reported concept exists.

Instead, it preserves the semantic state:

```text
NO_DIVIDEND_PROGRAM
```

This distinction became important later in Feature 3.

### Derived capital-allocation metrics

Feature 2C calculates:

- Repurchases / FCF
- Dividends / FCF
- SBC / FCF
- Capital Returned
- Capital Returned / FCF
- Retained FCF
- Actual diluted-share change

### Negative retained FCF preserved

```text
Retained FCF =
    FCF
  - Repurchases
  - Dividends
```

If shareholder returns exceed FCF, retained FCF can be negative.

OwnerLens preserves this instead of clamping it to zero.

### Buyback effectiveness

Buyback spending and share-count reduction are not treated as the same thing.

The system looks at:

```text
cash spent on repurchases
        versus
actual diluted-share movement
```

Possible interpretations include:

- effective buybacks,
- partly offset by dilution,
- ineffective buybacks,
- net dilution,
- insufficient data.

### SBC interpretation

SBC is shown as an owner-relevant burden but is not subtracted again from conventional FCF.

OwnerLens shows both:

- conventional FCF,
- SBC / FCF,
- actual share-count outcome.

This prevents assuming SBC maps one-for-one to dilution.

### Adobe result

Across FY2021–FY2025, Adobe generated approximately:

```text
FCF:        ~$38.9B
Buybacks:   ~$35.7B
```

Buybacks represented roughly 92% of cumulative FCF.

Despite meaningful SBC, diluted shares declined in the years where comparison was available.

The interpretation was therefore generally:

```text
OWNER_FRIENDLY
```

while still surfacing warnings:

- high SBC burden,
- capital returned above FCF,
- declining net-cash cushion.

### Watch vs guardrail

Feature 2C established an important interpretive distinction.

#### Watch signal

Economically relevant, but not severe enough to change the verdict alone.

Examples:

- high SBC while shares are still shrinking,
- capital returned above FCF while the company remains net-cash positive.

#### Guardrail

Severe enough to downgrade the verdict.

Examples:

- materially deepening net debt,
- destructive dilution,
- severe deterioration in business quality.

---

## Slice 2D — Company-Level Economic Value Summary

### Goal

Combine Feature 2A, 2B, and 2C into one concise owner-oriented conclusion.

The question becomes:

> If I owned this business privately, what should I know about how its economic value has been developing?

### Composition, not recomputation

Feature 2D consumes:

```text
2A Annual Snapshot
2B Compounding View
2C Capital Allocation Lens
```

It does not:

- call SEC,
- normalize facts,
- recalculate Feature 1 metrics,
- duplicate prior business logic.

### Durable-first hierarchy

The multi-year compounding verdict is the anchor.

A strong latest year cannot manufacture a `STRONGLY_IMPROVING` company classification if long-term compounding does not support it.

Conceptually:

```text
Long-term compounding
        ↓
latest-year confirmation / dampening
        ↓
capital-allocation modifier
        ↓
severe guardrails
```

This intentionally resists recency bias.

### Tension handling

Feature 2D explicitly recognizes situations such as:

```text
RECENT_SLOWDOWN
```

when long-term economics remain strong but the latest year weakens.

And:

```text
EARLY_IMPROVEMENT_NOT_YET_PROVEN
```

when recent results improve but long-term history remains weak.

### Adobe summary

Adobe's final Feature 2 output was approximately:

```text
Latest annual economics:      IMPROVING
Recent compounding:           COMPOUNDING
Long-term compounding:        COMPOUNDING
Capital allocation:           OWNER_FRIENDLY

Overall:
IMPROVING
```

Positive evidence included:

- per-share cash-flow compounding,
- high and improving ROIC,
- shrinking share count,
- effective buybacks.

Watch items included:

- high SBC burden,
- capital returns exceeding FCF,
- declining net-cash cushion.

---

## Feature 2 Architecture

Feature 2 established this analytical stack:

```text
Feature 1 trusted fundamentals
        ↓
2A Annual Economic Value Snapshot
        ↓
2B Multi-Year Compounding View
        ↓
2C Capital Allocation Lens
        ↓
2D Company-Level Economic Value Summary
```

The interpretation remains:

- deterministic,
- transparent,
- testable,
- traceable,
- separate from valuation.

---

## Educational Notebooks

Feature 2 produced notebooks including:

- `03_adbe_economic_value.ipynb`
- `04_adbe_compounding.ipynb`
- `05_adbe_capital_allocation.ipynb`
- `06_adbe_economic_value_summary.ipynb`

These notebooks turn the code into an investing-learning system.

---

## What Feature 2 Does Not Claim

Feature 2 does **not** claim:

```text
FCF/share CAGR = intrinsic-value CAGR
```

Nor does:

```text
IMPROVING = stock is a buy
```

A wonderful business can be overpriced.

A temporarily deteriorating business can be undervalued.

Feature 2 only answers:

> How are the observable underlying owner economics developing?

Valuation remains a separate future layer.

---

## Feature 2 Outcome

Feature 2 transformed OwnerLens from a financial-data engine into an owner-economics engine.

It can now explain:

- what changed,
- how quickly the business compounded,
- whether owners benefited per share,
- whether capital allocation helped,
- what deserves monitoring.

The next question was:

> Does this work only because Adobe is a convenient software company?

That led directly to Feature 3: **Multi-Company Generalization**.

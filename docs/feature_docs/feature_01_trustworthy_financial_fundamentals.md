# Feature 1 — Trustworthy Financial Fundamentals

## Purpose

Feature 1 establishes the trusted financial-data foundation of OwnerLens.

The goal was not to recreate an entire financial-data platform. The goal was to answer a narrower question well:

> Can OwnerLens take structured SEC data and turn it into a small set of trustworthy, provenance-backed financial facts and owner-relevant metrics?

This feature deliberately focused on correctness, traceability, and learning the semantics of SEC XBRL before building scores, screeners, valuation, databases, or agents.

---

## What Feature 1 Built

Feature 1 created the pipeline:

```text
Ticker
  ↓
SEC company identity
  ↓
Raw SEC Company Facts
  ↓
Canonical annual reported facts
  ↓
Deterministic financial metrics
  ↓
Owner-economics and capital-efficiency views
```

The initial golden company was Adobe (`ADBE`).

---

## Slice 1A — SEC Company Identity + Raw Company Facts

### Goal

Prove that OwnerLens can reliably:

1. resolve a ticker to the correct SEC company identity,
2. retrieve SEC Company Facts,
3. validate the trust boundary,
4. preserve the raw parsed payload unchanged.

### Key implementation

The slice introduced a synchronous SEC client that:

- resolves ticker → CIK using SEC `company_tickers.json`,
- formats the CIK to ten digits,
- retrieves SEC Company Facts,
- sends an explicit SEC-compliant User-Agent,
- validates the returned identity,
- returns the parsed raw response unchanged.

### Important design principle

Feature 1A intentionally performed **no financial interpretation**.

OwnerLens first proved:

> "I retrieved the right company's source truth."

before asking:

> "What does this financial fact mean?"

### Failure behavior

Typed failures were introduced for conditions such as:

- unresolved ticker,
- malformed SEC mapping,
- transport errors,
- malformed SEC responses,
- company identity mismatch.

No partial or fabricated success was allowed.

### Validation

The live ADBE path returned:

- canonical ticker,
- Adobe company name,
- CIK `0000796343`,
- top-level Company Facts keys,
- available XBRL namespaces.

---

## Slice 1B — Annual Revenue Normalization

### Goal

Move from raw SEC data to the first canonical financial series:

> Adobe annual revenue.

### Key lesson: SEC `fy` is not the observation year

A critical discovery was that the raw XBRL `fy` field belongs to the **filing context**, not necessarily the economic fiscal year of the fact.

For example, a full-year FY2023 value can appear again as a comparative observation in FY2024 and FY2025 filings.

Therefore OwnerLens does **not** trust `fy` as the economic year.

Instead, the fiscal year is derived from the observation's **period end date**.

### Revenue concept selection

A deterministic concept preference order was introduced:

1. `RevenueFromContractWithCustomerExcludingAssessedTax`
2. `Revenues`
3. `SalesRevenueNet`

Adobe resolved to `Revenues`.

OwnerLens selects one concept for the canonical series rather than mixing multiple concepts across years.

Since Slice 6B, selection is also **recency-aware**. A concept is eligible only if it covers the company's latest fiscal year, so a concept the company stopped reporting is skipped in favor of the next current concept, or the metric becomes unsupported. See [Feature 6](feature_06_universe_coverage.md#slice-6b--recency-aware-sec-concept-selection).

### Full-year detection

Annual duration facts are selected using:

- `USD`,
- `fp = FY`,
- duration approximately 350–380 days.

The duration range supports 52/53-week fiscal calendars while excluding quarterly and YTD observations.

### Comparative-repeat handling

When identical annual values repeat in later 10-Ks:

- they are collapsed into one canonical observation,
- the earliest-filed provenance is retained.

If distinct values remain for the same economic year, OwnerLens fails explicitly rather than silently choosing one.

### Provenance retained

Each selected fact carries fields such as:

- canonical metric,
- SEC concept,
- value,
- unit,
- fiscal year,
- start date,
- end date,
- form,
- filed date,
- accession number.

### Adobe revenue series

Feature 1B produced:

| Fiscal Year | Revenue |
| --- | ---: |
| 2021 | $15.785B |
| 2022 | $17.606B |
| 2023 | $19.409B |
| 2024 | $21.505B |
| 2025 | $23.769B |

---

## Slice 1C — Operating Income + Operating Margin

### Goal

Add a second reported financial metric and the first meaningful derived profitability metric.

### Reported metric

Adobe operating income resolves through:

- `OperatingIncomeLoss`

### Derived metric

```text
Operating Margin = Operating Income / Revenue
```

This established an important architectural distinction:

> Reported facts come from SEC.  
> Derived metrics come from deterministic OwnerLens code.

### Reusable annual primitive

Revenue and operating income exposed concrete duplication. That justified extracting a small internal annual-duration primitive responsible for:

- annual duration filtering,
- fiscal-year derivation,
- comparative-repeat deduplication,
- provenance,
- concept-preference resolution.

This abstraction emerged from real duplication rather than speculative design.

### Adobe output

OwnerLens produced a five-year table containing:

- revenue,
- operating income,
- operating margin.

---

## Slice 1D — Core Owner Economics

### Goal

Move from accounting profit to the cash economics attributable to an owner.

### New normalized reported facts

Feature 1D added:

- Net Income — `NetIncomeLoss`
- Operating Cash Flow — `NetCashProvidedByUsedInOperatingActivities`
- CapEx — `PaymentsToAcquirePropertyPlantAndEquipment`
- Diluted Weighted-Average Shares — `WeightedAverageNumberOfDilutedSharesOutstanding`

### Important share-count distinction

OwnerLens uses **diluted weighted-average shares** for per-share operating economics.

It does not substitute point-in-time common shares outstanding.

This distinction is permanently encoded in tests.

### Derived metrics

Feature 1D calculates:

```text
Net Margin = Net Income / Revenue
FCF = Operating Cash Flow - CapEx
FCF Margin = FCF / Revenue
FCF/share = FCF / Diluted Weighted-Average Shares
```

It also calculates:

- annual FCF growth,
- annual FCF/share growth,
- diluted-share growth.

### CapEx semantics

For Adobe, the selected SEC CapEx concept is reported as a positive expenditure magnitude.

OwnerLens therefore uses:

```text
FCF = OCF - CapEx
```

rather than silently applying `abs()` to surprising values.

### Example owner insight

Adobe FCF/share increased from approximately:

```text
FY2021: $14.31
FY2025: $23.07
```

while diluted share count declined.

That was the first point where OwnerLens directly answered an owner-oriented question:

> Is each share's claim on the company's cash generation improving?

### Missing growth values

The earliest displayed year correctly has no prior-year growth comparison.

OwnerLens preserves this as unavailable (`None` internally, `n/a` in presentation) rather than replacing it with 0%.

---

## Slice 1E — Balance Sheet + Capital Efficiency

### Goal

Introduce a fundamentally different type of financial fact:

> point-in-time balance-sheet facts.

### Duration vs instant facts

OwnerLens explicitly models two paths:

#### Duration facts

```text
start ---------------- end
```

Examples:

- revenue,
- operating income,
- net income,
- OCF.

#### Instant facts

```text
                      ●
                   period end
```

Examples:

- cash,
- debt,
- assets,
- equity.

The two paths are kept explicit rather than hidden behind one generic selector.

### Normalized balance-sheet facts

Feature 1E added:

- Cash — `CashAndCashEquivalentsAtCarryingValue`
- Short-Term Investments — `ShortTermInvestments`
- Current Debt — `DebtCurrent`
- Long-Term Debt — `LongTermDebt`
- Total Assets — `Assets`
- Total Equity — `StockholdersEquity`

### Derived balance-sheet metrics

```text
Cash + STI
Total Debt
Net Cash / Net Debt
```

### Capital-efficiency inputs

Feature 1E also normalized:

- Income Tax Expense
- Pretax Income

These support:

```text
Effective Tax Rate = Tax Expense / Pretax Income
NOPAT = Operating Income × (1 - Effective Tax Rate)
```

### Invested capital

The initial transparent definition is:

```text
Invested Capital =
    Total Debt
  + Total Equity
  - (Cash + Short-Term Investments)
```

This treats all cash/STI as excess cash.

That assumption is intentionally documented because it can increase calculated ROIC relative to definitions that retain operating cash.

### Average-balance denominators

OwnerLens calculates:

```text
ROA  = Net Income / Average Total Assets
ROE  = Net Income / Average Total Equity
ROIC = NOPAT / Average Invested Capital
```

The average uses beginning and ending balances.

If the prior-year balance required for the denominator is unavailable, the metric is omitted instead of substituting ending balances.

### Real taxonomy conflict caught safely

Live Adobe validation exposed a historical pretax-income concept transition.

A stale/older concept produced an ambiguity, and OwnerLens failed loudly instead of choosing a convenient number.

Research established the more appropriate recent concept preference and documented the decision.

This validated the project's "fail loudly" philosophy.

---

## Feature 1 Architecture

By the end of Feature 1, OwnerLens had a structure conceptually like:

```text
SEC access
  ↓
raw Company Facts
  ↓
annual duration normalization
annual instant normalization
  ↓
canonical reported facts
  ↓
deterministic metrics
  ↓
owner economics
capital efficiency
```

Key properties:

- source provenance retained,
- no hidden LLM calculations,
- explicit financial definitions,
- duration/instant semantics separated,
- ambiguity surfaced instead of guessed,
- calculations deterministic and tested.

---

## Educational Notebooks

Feature 1 created educational artifacts rather than hiding all financial semantics inside production code.

Examples include:

- `01_adbe_revenue_normalization.ipynb`
- `02_adbe_owner_economics.ipynb`

The notebooks explain concepts such as:

- raw XBRL observations,
- annual normalization,
- comparative repeats,
- cash generation,
- per-share economics,
- balance-sheet strength,
- capital efficiency.

---

## What Feature 1 Deliberately Did Not Build

Feature 1 did **not** build:

- valuation,
- stock-price data,
- DCF,
- scores,
- screeners,
- databases,
- Azure infrastructure,
- agents,
- portfolio construction,
- risk management.

Those layers depend on trusted financial fundamentals, so they were intentionally deferred.

---

## Feature 1 Outcome

Feature 1 transformed OwnerLens from an idea into a trustworthy financial engine for Adobe.

It established the core rule:

> Facts, metrics, scores, and judgment are different layers and must remain distinguishable.

The next feature could therefore focus on interpretation rather than data collection.

That became Feature 2: **Economic Value Lens**.

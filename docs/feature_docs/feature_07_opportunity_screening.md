# Feature 7 — Deterministic Opportunity Screening

## Purpose

Features 1 through 6 answer questions about a *company*: what it reported, what its owner economics
are, how they are developing, and how much of that OwnerLens can actually see. Feature 7 is the
first layer that answers a question about *research*:

> Which companies look economically strong enough, improving enough, and resilient enough to deserve
> expensive underwriting?

It deliberately does not answer:

> Is this stock cheap, and should I buy it?

**Status: closed.** Slice 7A built the evidence assembly and the six dimension bands, 7B the gates,
buckets, setup types, and explanations, and 7C the universe ranking, CLI, notebook, and
documentation. Screening the 24-company universe narrows it to 7 companies worth deeper work, with
an auditable reason for every name on and off the list.

| Slice | Change | Tests |
|---|---|---:|
| 7A | Coverage-aware evidence assembly and six dimension bands | 54 |
| 7B | Gates, buckets, setup types, limiting factor, explanations | 52 |
| 7C | Universe ranking, `owner-lens screen`, script, notebook, docs | 26 |

## Boundaries

Feature 7 contains no stock price, no multiple, no intrinsic value, no DCF, no expected return, no
bear/base/bull scenario, no probability distribution, no edge, no position size, and no portfolio
construction. It introduces no analyst estimate, no news, no qualitative moat score, and no LLM
call. Every band, gate, bucket, and reason is a documented deterministic rule over facts OwnerLens
already derived, so the same universe re-screens identically tomorrow.

A bucket communicates **research priority**, never investment advice.

---

# Slice 7A — Screening Evidence and Dimension Bands

## Goal

Compose the existing Feature 1 and Feature 2 outputs into six interpretable, independently
explainable dimensions, honouring the Feature 6 coverage contract exactly: nothing missing becomes
a zero, a neutral score, or a silent omission.

## What the data forced

The design is grounded in an offline run of the existing pipeline across all 24 companies, not in
ratios chosen in advance. Three measured facts shaped every rule that follows.

### 1. Coverage is the binding constraint, not the metrics

Only 7 of 24 companies have every layer available. Eight of the ten `PARTIAL` companies — NOW, ORCL,
LULU, PG, KO, HD, LOW, and UNH — have **only** owner economics: no ROIC, no balance sheet, no
capital allocation. `economic_value_summary_from_history` raises for every one of them.

A screener that consumed the Feature 2D company-level summary alone would return "insufficient data"
for 17 of 24 companies and be useless. Feature 7 therefore composes from the **component** layers
and records exactly which ones were obtainable.

### 2. ROIC level and ROIC trend must be separated

Microsoft's ROIC fell 44 percentage points over the window:

```
FY2022  79.9%
FY2023  56.5%
FY2024  46.3%
FY2025  39.5%
FY2026  35.9%
```

That is not a collapse in earning power. Invested capital is debt plus equity minus cash, so
spending down a vast net-cash pile mechanically enlarges the denominator. A 36% return is still
exceptional. If trend were allowed to demote level, Microsoft would screen as a broken business.

So the **level** sets the capital-efficiency band, the **fall** is reported as a reason and scored
under economic momentum, and the downward guardrail fires only when the resulting level is *also*
below the strong threshold.

### 3. Margin levels must never be scored across companies

Costco runs a 3.8% operating margin and a 2.8% FCF margin against a 40.9% ROIC. Any absolute margin
band makes Costco look weak and bakes business-model bias into the screen permanently.

So business quality reads *cash-generation durability* for its base band and *margin trend* for a
bounded one-notch modifier. Margin levels appear in the evidence and never in a band. The only
absolute cross-company level threshold in the entire design is ROIC, which is already
capital-turnover adjusted — which is exactly why a low-margin, high-turnover retailer scores
correctly on it.

## The six dimensions

| Dimension | Question it answers | Requires |
|---|---|---|
| Business quality | Does it reliably convert activity into cash, and is that improving or eroding? | owner economics only |
| Capital efficiency | What return does it earn on the capital it employs? | capital efficiency |
| Per-share compounding | Is economic value per ownership unit growing? | diluted shares |
| Balance-sheet strength | Can it survive a bad outcome without a forced decision? | capital efficiency |
| Capital allocation | Does management convert cash into owner value? | capital allocation |
| Economic momentum | Are economics improving, stable, or deteriorating? | economic value, with two fallbacks |

Coverage confidence is a seventh concern but is **not scored**: it sets a bucket ceiling and a
visible flag, so absent negative evidence can never become an advantage.

Each dimension resolves to `STRONG` (3), `ADEQUATE` (2), `WEAK` (1), `POOR` (0), or
`NOT_EVALUABLE` (no ordinal). Bands are deliberately coarse: a 13% FCF/share CAGR and an 87% one
both land in `STRONG`, which is precisely what stops one extraordinary number from deciding a
ranking.

### Business quality

Base band from cash-generation durability, then a bounded one-notch margin-trend modifier.

* `STRONG`: free cash flow positive every year and the latest year at or above the earliest
* `ADEQUATE`: positive in at least 80% of years
* `WEAK`: positive in at least 50% of years
* `POOR`: otherwise, or the latest year burns cash
* `-1` notch when the operating margin contracted at least 3pp **and** the FCF margin also contracted
* `+1` notch when the operating margin expanded at least 3pp **and** the FCF margin did not contract
* the modifier is skipped entirely when margin data is missing

### Capital efficiency

ROIC level only, with one downward guardrail.

* `STRONG`: ROIC at or above 20% — the `high_roic_level` already used by Features 2A through 2D
* `ADEQUATE`: at or above 10%
* `WEAK`: at or above 5%
* `POOR`: below 5%
* `-1` notch only when ROIC fell at least 10pp **and** the latest level is below 20%

A ROIC improvement is reported as a reason and never lifts the band. Salesforce climbing from 1% to
10.3% stays `ADEQUATE`; the improvement shows up in momentum, where it belongs.

### Per-share compounding

Long-term FCF/share CAGR, with a bounded share-count modifier.

* `STRONG`: at or above 15%
* `ADEQUATE`: at or above 7%
* `WEAK`: above -2%
* `POOR`: at or below -2%
* `-1` notch when the diluted-share CAGR is at or above +1%
* `+1` notch when the diluted-share CAGR is at or below -1% **and** aggregate FCF did not decline
* when a sign change voids the CAGR, the start-to-end *direction* decides: a negative or lower
  endpoint is `POOR`, a recovery from negative is `WEAK`

The condition on the upward modifier is deliberate. Lowe's shrank its share count 5.4% a year to
produce 3.7% FCF/share growth while aggregate free cash flow *declined* 1.9% a year. That earns no
credit and emits `PER_SHARE_GROWTH_FROM_BUYBACKS_ONLY`.

### Balance-sheet strength

* `STRONG`: a net cash position, regardless of size
* `ADEQUATE`: net debt at or below 2× latest free cash flow
* `WEAK`: at or below 4×
* `POOR`: above 4×, or net debt with non-positive free cash flow
* `NOT_EVALUABLE`: net debt with no derivable free cash flow at all — debt that
  cannot be sized against anything is refused, never banded worst
* `-1` notch when a **net-debt** position deteriorated materially, using Feature 2C's 5% net-cash
  materiality rule

A net-cash company whose cushion shrank stays `STRONG` and carries a watch reason, mirroring Feature
2D's `DECLINING_NET_CASH_CUSHION`. Only a worsening net-debt position demotes. The gate and the band
resolve "latest free cash flow" through one shared helper, so a trailing year whose free cash flow
could not be derived cannot make them disagree about which year is latest.

### Capital allocation

The base band is the existing Feature 2C classification, so screening introduces no second opinion:
`OWNER_FRIENDLY` to `STRONG`, `BALANCED` to `ADEQUATE`, `QUESTIONABLE` to `WEAK`,
`OWNER_UNFRIENDLY` to `POOR`.

A `-1` notch applies when stock-based compensation is at least 25% of free cash flow, or when
capital returned exceeded free cash flow in a **majority** of measurable years. The persistence
requirement stops a single year's buyback surge from demoting a sound allocator.

### Economic momentum

Three paths, each labelled so the reader knows what was actually seen.

| Path | Used when | Ceiling |
|---|---|---|
| `ECONOMIC_VALUE_SUMMARY` | the Feature 2D verdict is available | none |
| `ANNUAL_SNAPSHOTS` | compounding or capital allocation is blocked | none |
| `OWNER_ECONOMICS_ONLY` | only owner economics is available | `ADEQUATE` |

The owner-economics path reads the direction of the FCF/share **level** series, never growth
percentages. Oracle's FY2026 growth reads as +5812% because the prior year was negative; its level
series falls from 4.18 to -8.13, which is what the band must follow.

## Tests

`tests/test_screening_dimensions.py` (54 tests) covers every band boundary for every dimension, both
modifier directions and their bounds, the undefined-CAGR sign-change path, all three momentum paths,
and the band algebra including the rule that `NOT_EVALUABLE` never satisfies an "adequate or better"
comparison. Two tests exist specifically for the load-bearing properties: a synthetic low-margin,
high-turnover company must band identically to a high-margin one, and a 44-point ROIC fall must not
demote a level that is still above the strong threshold. Three more pin the refusal path: net debt
with no derivable free cash flow is `NOT_EVALUABLE` rather than `POOR`, and the latest-cash-flow
resolution is shared with the gates.

## What Slice 7A Deliberately Did Not Build

- any valuation input: price, multiple, estimate, or expected return,
- a continuous or weighted score,
- a second coverage opinion divergent from Feature 6,
- new economics: every metric is read from an existing Feature 1 or Feature 2 object.

---

# Slice 7B — Gates, Buckets, Setup Types, and Explanations

## Goal

Turn six bands into one research-priority verdict that a reader can always explain by pointing at a
rule, plus the structured reasons behind it.

## Gate versus score: the hybrid, evaluated explicitly

**Pure weighted scoring fails on this data.** With eight companies evaluable on two of six
dimensions, a weighted average either silently renormalizes — which rewards *absent* negative
evidence, the exact failure mode this layer must avoid — or imputes neutral values, which fabricates
facts the constitution forbids. It also cannot express "two straight years of cash burn disqualifies
regardless of everything else".

**Pure gating fails too.** Gates are binary. They cannot rank the seven fully covered companies, and
they cannot express "intact foundation, temporarily depressed economics".

**The hybrid is adopted.** Gates are survival and usability filters only, never quality preferences
— which is what "leverage last" means in practice. Everything that survives is banded and bucketed
by an explicit rule table.

## The gates

Gates run in order and short-circuit the **bucket**, not the explanation: a gated company still
reports every dimension it could measure.

| Gate | Condition | Result | Reason |
|---|---|---|---|
| G0a | coverage `FAILED` | `INSUFFICIENT_DATA` | `COVERAGE_FAILED` |
| G0b | fewer than 2 evaluable dimensions, or business quality not evaluable | `INSUFFICIENT_DATA` | `TOO_FEW_EVALUABLE_DIMENSIONS` |
| G1 | free cash flow at or below zero in both of the last two years | `LOW_PRIORITY` | `PERSISTENT_CASH_BURN` |
| G2a | net debt with non-positive free cash flow | `LOW_PRIORITY` | `NET_DEBT_WITHOUT_CASH_FLOW` |
| G2b | net debt above 6× latest free cash flow | `LOW_PRIORITY` | `LEVERAGE_UNSUPPORTED_BY_CASH_FLOW` |
| G3 | ROIC below 5% in every year and not materially improving | `LOW_PRIORITY` | `RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL` |
| G4 | diluted-share CAGR at or above +5% a year | `LOW_PRIORITY` | `PERSISTENT_MATERIAL_DILUTION` |

G2 and G3 are **skipped**, never assumed, when the balance sheet or ROIC is invisible. G1 catches
Oracle (-$0.4B then -$23.7B). G3 deliberately spares Salesforce at 10.3% and rising from 1%. A
single bad year is a band, not a gate.

## The buckets

The bucket comes from a rule table over named dimensions; the first match wins. The score never
decides a bucket.

* **`HIGH_PRIORITY`** — coverage `FULL`, **every** dimension actually measured, business quality
  `STRONG`, per-share compounding and momentum at least `ADEQUATE`, every dimension at least
  `ADEQUATE`, and at least four of six `STRONG`.
* **`WORTH_UNDERWRITING`** — any of:
  * *(a) strong with one caveat*: quality, capital efficiency, compounding, and balance sheet all at
    least `ADEQUATE`, no `POOR`, at most one `WEAK`, at least two `STRONG`;
  * *(b) asymmetric setup*: quality and capital efficiency `STRONG`, balance sheet at least
    `ADEQUATE`, and compounding or momentum at `WEAK` or below;
  * *(c) coverage-limited*: `PARTIAL` with at least three evaluable dimensions, all at least
    `ADEQUATE`, at least two `STRONG`.
* **`WATCH`** — at least two evaluable dimensions at `ADEQUATE` or better and at most one `POOR`.
* **`LOW_PRIORITY`** — anything else, or gated.
* **`INSUFFICIENT_DATA`** — gated by G0.

### Why "four of six strong" rather than named strong dimensions

Intuit's ROIC is 19.95%, four hundredths of a percentage point below the 20% strong threshold. A
rule requiring capital efficiency to be `STRONG` would drop Intuit a whole bucket on a number that
rounds to the threshold — exactly the false precision this layer exists to avoid. Requiring four of
six strong, with nothing below adequate, keeps a single band boundary from deciding the top bucket
on its own while still demanding breadth.

## The coverage ceiling

A company that was not measured on every dimension is missing evidence in **both** directions: its
unseen dimensions could be strengths or weaknesses. Scoring it on what is visible and ranking it
beside a fully measured company would let absent negative evidence become an advantage.

The cap is keyed on the **evaluable dimension count**, not only on the Feature 6 coverage class. The
two can disagree: capital allocation returns rows whenever *any* year classifies, while the
dimension reads the latest year, so a company can be `FULL` at the layer level and still have an
unmeasured dimension. It is just as unmeasured either way.

| Measured | Evaluable dimensions | Ceiling |
|---|---:|---|
| every dimension, coverage `FULL` | 6 | none |
| not every dimension | 3 or more | `WORTH_UNDERWRITING` |
| not every dimension | fewer than 3 | `WATCH` |
| nothing (`FAILED`) | 0 | excluded as `INSUFFICIENT_DATA` |

A ceiling only ever lowers a bucket, and any unmeasured dimension also emits `COVERAGE_LIMITED`.
ServiceNow is the test of whether this is honest: its measurable economics match the leaders' — 25%
FCF/share CAGR, expanding margins, barely any dilution — but its balance sheet is unknowable from
SEC Company Facts today. It reaches `WORTH_UNDERWRITING`, high enough that a human will look, and no
higher. Within every bucket, `FULL` sorts ahead of `PARTIAL`.

## Setup type and limiting factor

Priority says *when* to look. Two orthogonal fields say *why*.

**`setup_type`**:

* `COMPOUNDER` — quality `STRONG`, capital efficiency and compounding and momentum at least
  `ADEQUATE`
* `POTENTIAL_ASYMMETRIC_SETUP` — quality and capital efficiency `STRONG`, balance sheet at least
  `ADEQUATE`, and compounding or momentum at `WEAK` or below
* `NEITHER` — otherwise, **including every company whose returns on capital cannot be seen**: neither
  label may be granted on cash-flow evidence alone

**`limiting_factor`** answers "excluded because it is weak, or because we cannot see it": `NONE`,
`FUNDAMENTALS`, `COVERAGE`, or `BOTH`. A fired gate counts as `FUNDAMENTALS` even when it demoted no
band, so a gated company never reports that nothing limits it. This is what makes the Feature 6
coverage gap measurable rather than invisible.

## The score

`screening_score` is the integer sum of the evaluable dimension ordinals, bounded 0 to 18. It orders
companies **within** a bucket and never sets one; it is not comparable across coverage classes, which
is why the coverage class sorts ahead of it in `rank_key`. Microsoft and Salesforce both score 11 and
sit in different buckets, which is the point.

Ranking order is `(bucket, coverage class, descending score, ticker)`.

## Tests

`tests/test_screening_buckets.py` (52 tests) covers each gate in isolation and in full precedence
order, the skip behaviour when a gate's inputs are invisible, every bucket rule path including all
three `WORTH_UNDERWRITING` routes, both coverage ceilings, the rule that a ceiling never raises a
bucket, the cap that applies when a dimension is unmeasured under `FULL` layer coverage, setup-type
assignment including the returns-on-capital requirement, `limiting_factor` resolution including the
gated case, integer-only score bounds, the proof that two equal scores can occupy different buckets,
reason categorization and deduplication, the rendering contract, and determinism.

## What Slice 7B Deliberately Did Not Build

- weights of any kind: dimensions are equal-ordinal and the bucket is a rule table,
- a buy, sell, hold, or conviction rating,
- any company-specific exception: a wrong result is fixed by changing a documented rule or threshold,
- a second judgement on capital allocation or economic value; both reuse Feature 2 verdicts directly.

---

# Slice 7C — Universe Screening, Ranking, and Delivery

## Goal

Screen a whole universe cheaply and offline, rank it, and make the result readable from the CLI, a
script, and a notebook.

## Cost

Screening one company costs one evidence assembly: the two base layers (owner economics and capital
efficiency) run once each, and every composed layer is built from those rows rather than re-derived
from the canonical history. There is no cross-company work and no network access, so a universe
screen is linear in company count. The 24-company screen runs from stored snapshots in seconds.

## Running it

```powershell
# Every persisted company, from the local store, no network call
uv run owner-lens screen

# A subset, with the full per-company justification
uv run owner-lens screen ADBE MSFT NOW --detail

# The 24-company universe from the stored SEC snapshots
uv run python scripts/screen_universe.py
uv run python scripts/screen_universe.py --detail
```

`owner-lens show TICKER` now also reports the screening verdict. The script writes
`data/screening_report.json` with every band, reason, and piece of evidence, so a run is
reproducible and diffable.

## Results: the 24-company universe

| Bucket | Companies | Count |
|---|---|---:|
| `HIGH_PRIORITY` | ADBE, CMG, NVDA, COST, INTU | 5 |
| `WORTH_UNDERWRITING` | MSFT, NOW | 2 |
| `WATCH` | CRM, PG, V, LOW | 4 |
| `LOW_PRIORITY` | AMZN, LULU, HD, KO, UNH, ORCL | 6 |
| `INSUFFICIENT_DATA` | CAT, CVX, DE, META, NKE, PFE, XOM | 7 |

Seven of 24 companies warrant deeper underwriting. Full bands:

```
Company Priority Setup       Coverage  BUSI CAPI PER_ BALA CAPI ECON  Score  Limited by
---------------------------------------------------------------------------------------
ADBE    HIGH     compounder  FULL      STR  STR  STR  STR  STR  STR      18
CMG     HIGH     compounder  FULL      STR  STR  STR  STR  STR  STR      18
NVDA    HIGH     compounder  FULL      STR  STR  STR  STR  STR  STR      18
COST    HIGH     compounder  FULL      STR  STR  ADQ  STR  ADQ  STR      16
INTU    HIGH     compounder  FULL      STR  ADQ  STR  ADQ  STR  STR      16
MSFT    WORTH    asymmetric  FULL      STR  STR  WEK  STR  WEK  POR      11  fundamentals
NOW     WORTH                PARTIAL   STR  ---  STR  ---  ---  ADQ       8  coverage
CRM     WATCH                FULL      STR  ADQ  STR  WEK  WEK  WEK      11  fundamentals
PG      WATCH                PARTIAL   STR  ---  ADQ  ---  ---  ADQ       7  coverage
V       WATCH                PARTIAL   ADQ  STR  ---  WEK  ---  ---       6  both
LOW     WATCH                PARTIAL   ADQ  ---  WEK  ---  ---  ADQ       5  both
AMZN    LOW                  PARTIAL   ADQ  ADQ  POR  STR  ---  POR       7  both
LULU    LOW                  PARTIAL   ADQ  ---  WEK  ---  ---  WEK       4  both
HD      LOW                  PARTIAL   ADQ  ---  WEK  ---  ---  POR       3  both
KO      LOW                  PARTIAL   ADQ  ---  POR  ---  ---  WEK       3  both
UNH     LOW                  PARTIAL   WEK  ---  POR  ---  ---  POR       1  both
ORCL    LOW                  PARTIAL   POR  ---  POR  ---  ---  POR       0  both
```

## Sanity checks

These were stated before the screen was built and are asserted in
`tests/test_screening_universe.py`.

* **Adobe screens strong despite current market concerns.** `HIGH_PRIORITY`, 18 of 18. Market
  sentiment is outside this layer entirely; the only thing held against Adobe is its shrinking
  net-cash cushion, which is reported.
* **Costco scores highly on business quality despite structurally low margins.** `STRONG` quality
  and `STRONG` capital efficiency on a 3.8% operating margin, because margin levels are structurally
  excluded from scoring.
* **NVIDIA does not dominate on one exceptional metric.** Its 94.5% ROIC and 87% FCF/share CAGR land
  in the same `STRONG` bands as Adobe's 61.6% and 13%. The two tie at 18 and share the top bucket.
  Banding is what produces that.
* **Partial coverage does not outrank full coverage.** ServiceNow's measurable economics match the
  leaders'; the tiered ceiling and the coverage-class tiebreak keep it a bucket below Adobe.
* **No business-model bias.** The only absolute cross-company level threshold is ROIC, which is
  already capital-turnover adjusted. Home Depot and Lowe's land low on measured flat-to-declining
  FCF/share, flagged `BOTH`, not on retail being retail.
* **Weak fundamentals are distinguished from incomplete data.** Meta is `INSUFFICIENT_DATA` with
  `COVERAGE_FAILED`; Salesforce is `WATCH` with `limiting_factor` `FUNDAMENTALS` on full coverage;
  Home Depot is `LOW_PRIORITY` with `BOTH`.

### The Microsoft case

Microsoft is the clearest demonstration that this is not a momentum filter. Feature 2 calls it
`STRONGLY_DETERIORATING`; its FCF/share CAGR is 1.0% and its capital allocation is `QUESTIONABLE`.
But its ROIC is 35.9% and it holds $36.5B of net cash, so the asymmetric path keeps it in
`WORTH_UNDERWRITING` and labels it `POTENTIAL_ASYMMETRIC_SETUP`:

```
Why it ranks where it does:
  + DURABLE_CASH_GENERATION
  + EXCEPTIONAL_RETURNS_ON_CAPITAL
  + PER_SHARE_COMPOUNDING_ACCELERATING
  + NET_CASH_POSITION

What holds it back:
  - ROIC_FELL_BUT_LEVEL_REMAINS_HIGH
  - PER_SHARE_COMPOUNDING_FLAT
  - NET_CASH_CUSHION_SHRINKING
  - QUESTIONABLE_CAPITAL_ALLOCATION
  - ECONOMICS_DETERIORATING
```

Amazon is the control. It is in a comparable capital cycle but its free cash flow was negative in
two of five years and its ROIC is 19.5%, so quality is `ADEQUATE` rather than `STRONG` and the
asymmetric path does not open. It lands in `LOW_PRIORITY`. The difference between the two is a
measured difference in how intact the foundation is, not a judgement call.

## Tests

`tests/test_screening_universe.py` (19 tests) covers the golden companies end to end from raw SEC
Company Facts, the agreement between the screening coverage class and the Feature 6 contract, the
rule that a structurally absent metric is not a blocker, ranking order and stability under input
reordering, the distribution and rendering contracts, a scale check proving no layer runs more than
its documented number of passes, and a feature-boundary check that no valuation or recommendation
word can appear in a rendered result. The full 24-company characterization table is pinned in
`EXPECTED_UNIVERSE`; those tests skip automatically when `data/` is absent, since it is not
committed.

`tests/test_cli.py` gains 7 tests covering `owner-lens screen`, its subset and `--detail` modes, its
refusal to screen a company that was never ingested, and a guard asserting that screening makes no
SEC call.

## Educational Notebook

[notebooks/16_opportunity_screening.ipynb](../../notebooks/16_opportunity_screening.ipynb) walks
through what the data forced, the six dimensions, the gate-versus-score argument, the bucket rules,
the coverage ceiling, the Microsoft and Salesforce contrast, and the four sanity checks.

## What Slice 7C Deliberately Did Not Build

- persistence of screening results to the store: the JSON report follows the Feature 6 survey
  precedent, and a store schema change is not justified until something reads it,
- a universe definition of its own: it screens whatever is persisted or listed in the coverage report,
- ranking across time, sectors, or peer groups,
- any notion of a watchlist, alert, or portfolio.

---

# Feature 7 closeout

## What it answers

1. **Which companies deserve deeper underwriting?** Seven of 24: ADBE, CMG, NVDA, COST, INTU, MSFT,
   NOW.
2. **Why?** Six named bands and a categorized reason list for every company, drawn from Feature 2
   drivers rather than new judgement.
3. **Which dimensions drive the priority?** The bucket rule that matched names them, and the
   rendered result shows every band with its evidence.
4. **Weak fundamentals or incomplete data?** `limiting_factor` separates them explicitly, and
   `INSUFFICIENT_DATA` is a distinct bucket from `LOW_PRIORITY`.
5. **Is the ranking interpretable?** The bucket is a rule table over named dimensions; the integer
   score only orders within a bucket.
6. **Does it avoid business-model bias?** Margin levels are structurally excluded from scoring; ROIC
   is the only absolute cross-company level threshold and is already turnover-adjusted.
7. **Does it scale cheaply?** One evidence assembly per company, linear, offline, no cross-company
   work.

## The finding worth carrying forward

Four companies — HD, LOW, LULU, and KO — rank low partly because only owner economics is visible for
them, and their `limiting_factor` says `BOTH`. Eight of the ten `PARTIAL` companies can be judged on
two or three dimensions out of six.

That is the sharpest measurement yet of what the Feature 6 coverage gap costs. Feature 6 closed with
the recommendation to stop normalization and proceed upward; this is the evidence that will tell us
whether reopening it is worth doing, and exactly which metrics — current debt, short-term
investments, operating income — would buy the most.

## Where this stops

Feature 7 produces a short list and an auditable reason for every name on and off it. It says
nothing about what any of them is worth.

Everything that comes next — intrinsic value, bear/base/bull distributions, expected return, edge,
position sizing — needs a price, and a price is the first input in this entire system that OwnerLens
does not derive from a filing. Keeping it out of this layer is what lets the short list be
re-derived identically tomorrow, and what will make the valuation layer's assumptions visible when
it arrives.

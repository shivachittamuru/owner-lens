---
title: "Feature 10A: Forecast Outcome Tracker"
description: "Immutable manual market and fundamental outcomes compared with exact frozen underwriting forecasts."
---

## Scope and semantic boundary

Feature 10A answers what happened after an underwriting, not whether the investor
was skilled, lucky or made a good decision. The shared
[outcome domain](../../src/owner_lens/outcomes.py) owns FORECAST vs OUTCOME.
ASSESSMENT, calibration, probability scoring, mistake patterns and attribution
remain outside this feature.

There is no retrieval, scheduling, monitoring agent, automatic change event,
re-underwriting, assumption/probability update, decision or sizing change.
Market outcomes are price comparisons, not portfolio performance. Shadow
entries, including ACTUAL_CHOICE/WATCH/PASS, never imply an execution.

## Immutable observation schema

Create an observation against an exact completed Feature 8 underwriting version.
The existing Feature 9A loader validates saved valuation, probabilities, hurdle
and frozen evidence cutoff. An explicit version is never replaced with latest.

| Input | Meaning |
|-------|---------|
| `observation_date` | YYYY-MM-DD market measurement date and information snapshot date |
| `observed_at` | Timezone-aware availability timestamp, no later than recording |
| `horizon` | QUARTERLY, 1Y, 2Y, 3Y, 5Y or CUSTOM |
| `horizon_note` | Optional description; required for CUSTOM |
| `category` | FACT only in this manual, verified-outcome workflow |
| `references` | Explicit source metadata list: title, URI, observed_at and note |
| `verification_note` | Manual verification explanation; required when any numeric value exists |
| `market` | Null or price/currency/basis object; each value explicitly nullable |
| `fundamentals` | Explicit list of linked metric observations; [] does not manufacture missing metrics |

Non-null numeric observations require a nonempty source title or URI and a
verification note. These are investor assertions of verification, not automated
source verification. References apply to the observation bundle; record separate
observations when different measurements require independent provenance.
An empty observation with explicit nulls can record a missing-data snapshot.

Saved output adds `observation_id`, ticker/security ID, exact underwriting
UUID/version/hash/as-of/creation time, UTC `recorded_at`, actual elapsed days and
ACT/365.2425 years since underwriting as-of, frozen forecast/snapshot/valuation,
derived comparisons and calculation version `forecast-outcomes-v1`.
Observed values retain FACT; elapsed intervals, returns and comparisons are
CALCULATION. The forecast preserves its original semantic categories.

SQLite schema 10 adds an append-only observation table with foreign keys,
content hashes and update/delete/replace rejection triggers. Migration from
schema 9 is additive. Creation validates the complete frozen report atomically.
Historical reads verify integrity and return stored calculations without
re-running newer rules or fetching newer evidence.

Observation and metric-period dates must follow underwriting as-of.
`observed_at` cannot precede creation of the selected underwriting.
Require `period_end <= observation_date <= observed_at UTC date` and
`observed_at <= recorded_at`. Dated sources cannot exceed observed_at.
Fiscal-year labels are explicitly supplied, not inferred; future labels beyond
the reported period's following calendar year are rejected.

## Market outcomes

The market object accepts:

```json
{
  "price": 30.0,
  "currency": "USD",
  "basis": "EOD_CLOSE_SAME_SHARE_BASIS"
}
```

The basis asserts EOD close on the same per-share basis as the frozen price.
Do not use it when splits or other corporate actions make the prices incompatible.
The engine performs no FX, split or dividend adjustments. Missing currency/basis
is INSUFFICIENT_DATA; different currencies or basis are NOT_COMPARABLE.
A frozen price with unknown currency is not silently assigned USD.
Prices may be zero, but never negative.

For comparable prices:

```text
total_price_return = observed_price / frozen_price - 1
elapsed_price_days = observation_date - frozen_market_date
annualized_price_return =
    (observed_price / frozen_price) ** (365.2425 / elapsed_price_days) - 1
```

Annualization is withheld until at least one calendar year has elapsed from
the frozen market date. The result remains null with an explicit reason before
then. February 29 anniversaries use February 28 in non-leap years.
Price return excludes dividends, execution timing, costs, taxes and position
changes. It is not investor realized return or total shareholder return.

## Fundamental definitions and horizon alignment

Each fundamental observation explicitly supplies:

```json
{
  "forecast": {"kind": "SCENARIO", "id": "revenue_cagr"},
  "observable": "revenue_cagr",
  "value": 0.074,
  "unit": "ratio",
  "basis": "FISCAL_CAGR",
  "fiscal_year": 2030,
  "start_fiscal_year": 2025,
  "period_end": "2030-12-31",
  "cadence": null,
  "source_family": null
}
```

All shown metric fields must be explicit, including nulls. Values are finite
numbers, not booleans. Link IDs are unique within each observation.
Unknown forecast IDs are rejected, never mapped by similar prose.

For SCENARIO links, observable must equal the exact frozen field ID:

| Field ID | Unit | Basis | Time alignment |
|----------|------|-------|----------------|
| `revenue_cagr` | ratio | FISCAL_CAGR | CAGR from frozen starting fiscal year through year 5 |
| `share_count_cagr` | ratio | FISCAL_CAGR | Diluted-share CAGR over that same full interval |
| `fcf_margin_year5` | ratio | ANNUAL_FISCAL | Annual equity-FCF/revenue margin in fiscal year 5 |
| `terminal_fcf_multiple` | multiple | FISCAL_YEAR_END | Equity-value/equity-FCF multiple at fiscal year-5 end |

Target fiscal year is frozen `latest_fiscal_year + 5`. CAGR starting fiscal year
must exactly equal frozen latest fiscal year. A single year's YoY revenue growth
or share-count change is not a five-year CAGR. Quarterly margins are not annual
terminal margins. Ratio 0.074 means 7.4%; no percentage or other unit conversion
is inferred.

Correctly defined observations before target fiscal year are
INTERIM_OBSERVATION, not forecast failures. After-target observations are
NOT_COMPARABLE. Missing definitions, values or required periods are
INSUFFICIENT_DATA. Incompatible definitions/units/bases are NOT_COMPARABLE.

For market scenario comparisons, only the exact fifth calendar anniversary of
underwriting as-of is compared with frozen terminal prices. Earlier observations
are INTERIM_OBSERVATION; later observations are NOT_COMPARABLE. Return calculations
can still be available. The underlying model has no encoded price path, so the
tracker does not interpolate, compound a fictional scenario path, or invent
linear progress toward terminal margins or multiples.

Horizon labels are user-supplied snapshot labels, not evidence that periods align.
Actual dates/fiscal windows control comparison even if the user labels a
six-month observation 5Y. Every observation is independent; absent quarters and
anniversaries stay absent.

## Structured thesis-variable links

Use `forecast: {"kind": "CONDITION", "id": "<exact condition_id>"}` to track any
frozen structured dependency/breaker observable, including ARR or ROIC where
actually defined. Preserve its exact observable, unit, cadence, source family
and measurement period. The existing deterministic Feature 9D matcher checks
literal legacy thresholds or first-class predicates, source constraints and
monitoring dates. No fuzzy matching or metric invention occurs.

Output includes frozen belief, observed value/date/source, predicate result and
condition status. Comparable conditions without Bear/Base/Bull values show
NO_SCENARIO_RANGE plus CONDITION_MET/CONDITION_BREACHED. Qualitative legacy
conditions remain NOT_COMPARABLE; missing metadata stays INSUFFICIENT_DATA.
No candidate change classification or re-underwriting trigger is emitted.
Unknown or ambiguous condition links are rejected.

## Scenario range classification

For time-aligned scenario values `B <= M <= U`, tolerance is
`t = 1e-9 * max(1, abs(M))` in the metric's native units. This is floating-point
comparison tolerance, not an investor confidence band.

| State | Deterministic rule, in this order |
|-------|----------------------------------|
| BELOW_BEAR | observed < B - t |
| ABOVE_BULL | observed > U + t |
| NEAR_BASE | abs(observed - M) <= t |
| WITHIN_BEAR_BASE | remaining observed < M |
| WITHIN_BASE_BULL | remaining observed >= M |

Missing values are INSUFFICIENT_DATA. Unordered scenario values are
NOT_COMPARABLE for range labels; the engine does not reorder them.
Nearest scenario values are also shown descriptively, including ties within
tolerance. They can still be displayed for unordered values, such as diluted
shares declining toward BULL. They do not declare a winning scenario, infer
scenario probabilities, or assess forecast/decision quality.

## Feature 9 context and safeguards

Each observation copies decision/change records linked to its exact underwriting
and available by recording time, including approvals available at that cutoff.
This is context only. Later decisions, events and approvals cannot rewrite the
copy. Other underwriting versions are not substituted.

Creating or comparing an outcome never mutates underwritings, events, approvals,
decisions, shadow entries, portfolios or sizing analyses. A user can separately
use outcome evidence in a manual 9D event, but 10A offers no automatic transition.
Canonical sorted JSON makes repeated reads/comparisons stable for the same
selected version and observation history. A newly appended observation
intentionally changes the history; it does not alter earlier observations.

## Synthetic ADBE example

The [future 5Y synthetic fixture](../examples/adbe_outcome_5y.synthetic.json) is
for automated tests with an explicitly future recording clock, not manual
validation in 2026 and not an Adobe disclosure. Do not alter the recording clock
or bypass look-ahead validation to record it. With an underwriting dated 2026-06-02, frozen
price 20 USD on 2026-06-01 and starting fiscal year 2025:

```text
Observed 2031-06-02 price: 30 USD
MARKET_OUTCOME price return: +50%
Annualized price return: approximately +8.44%
No dividend, execution or investor-performance claim.

Revenue CAGR, FY2025 through FY2030:
Frozen Bear 0% / Base 10% / Bull 20%
Observed 7.4%: WITHIN_BEAR_BASE; nearest scenario value BASE

FY2030 annual FCF margin:
Frozen Bear 10% / Base 20% / Bull 30%
Observed 25%: WITHIN_BASE_BULL; nearest values BASE and BULL (tie)

The same terminal-margin field measured in FY2027:
INTERIM_OBSERVATION, not a forecast assessment.
New change event, decision, sizing or underwriting: none.
```

## Workbench

Open **Outcomes**, select an exact completed underwriting and review its as-of,
frozen starting price, scenario definitions and thesis variables. Paste manual
JSON or upload a file, then explicitly record an immutable observation.

The table shows observation dates, declared horizons, price return, annualized
price return, fundamental values, comparison states, condition results and
nearest scenario values. Expand observations for frozen beliefs, provenance and
Feature 9 context. Missing metrics stay explicit. Download reproducible JSON.
Opening or navigating the view never fetches or saves observations.

## Manual PowerShell validation

No live validation was performed. Run these commands yourself against your
chosen local store. The [manual template](../examples/adbe_outcome.sample.json)
uses CUSTOM/interim dates and null measurements, not invented Adobe evidence.
Its dates are illustrative UTC dates. Replace them with actual observation and
availability dates at or before recording, after your exact underwriting.

For a newly created ADBE v7, start with a CUSTOM observation. The engine requires
`observation_date` strictly after underwriting as-of and `observed_at` at or after
underwriting creation. If v7 was created with today's as-of, wait until a later
date with genuinely available observations; there is no valid same-day shortcut.
Do not backdate the underwriting, invent evidence or advance the recording clock.

Populate price only with a verified compatible close. For the optional margin,
enter a verified completed annual measurement, its actual fiscal year and
`period_end`, which must itself be after underwriting as-of. If no such report
exists yet, leave it null or use `fundamentals: []`. Add genuine source references
and a verification note for every populated observation bundle.
Null values remain INSUFFICIENT_DATA. A populated, definition-compatible annual
margin before the frozen target year is INTERIM_OBSERVATION, never evaluated as
the terminal 5Y forecast. Do not relabel a quarterly margin as ANNUAL_FISCAL.

Genuine 1Y/3Y/5Y outcome validation becomes available only as time actually passes
and the corresponding evidence becomes available. Horizon labels do not advance
time. Future fixture dates are correctly rejected by the unchanged safeguard.

Run the creation block before any show command. A nonzero exit means no observation
ID was created: stop, correct the input, and retry creation. Do not run
`outcome show` after a failed creation or reuse an ID from an earlier attempt.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

New-Item -ItemType Directory -Force .\data\outcomes | Out-Null
Copy-Item .\docs\examples\adbe_outcome.sample.json .\data\outcomes\adbe-outcome.json
notepad .\data\outcomes\adbe-outcome.json

$observation = $null
$createdJson = uv run owner-lens outcome create ADBE --version 7 --file .\data\outcomes\adbe-outcome.json --json
if ($LASTEXITCODE -ne 0) {
    throw "Creation failed. No observation ID was created; do not run outcome show."
}
$observation = $createdJson | ConvertFrom-Json
if (-not $observation.observation_id) {
    throw "No observation ID returned; stop before outcome show."
}
uv run owner-lens outcome show $observation.observation_id
uv run owner-lens outcome history ADBE --json
uv run owner-lens outcome compare ADBE --version 7

$a = uv run owner-lens outcome compare ADBE --version 7 --json
$b = uv run owner-lens outcome compare ADBE --version 7 --json
if ($a -cne $b) { throw "Non-reproducible outcome comparison" }

uv run owner-lens workbench
```

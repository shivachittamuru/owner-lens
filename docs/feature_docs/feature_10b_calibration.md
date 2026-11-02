---
title: "Feature 10B: Calibration"
description: "Deterministic, sample-guarded calibration of exact frozen forecasts against comparable completed outcomes."
---

## Purpose and boundary

Calibration asks how stated probabilities and forecast ranges matched realized
outcomes. It does not infer skill, luck, mistakes, investment quality or decision
quality. It never updates probabilities, tunes models, changes processes,
creates decisions or triggers re-underwriting.

The [calibration domain](../../src/owner_lens/calibration.py) reads immutable
Feature 8 forecasts and Feature 10A observations offline. Nothing is fetched or
scheduled. Insufficient history is a valid report, not an error.

## Eligibility and sampling

The report's UTC `as_of_date` is an end-of-day availability cutoff. Only
underwritings created/as-of by that cutoff and observations recorded by that
cutoff enter the report. Source availability, observed_at, measurement dates,
FACT verification and exact underwriting UUID/version/hash/snapshot are
validated. No explicit version is replaced with latest, and no new path is
inferred. Future observations are not manufactured by selecting a later cutoff.

Required completed forecasts have saved Feature 8 valuation, ordered terminal
scenario prices, explicit Bear/Base/Bull probabilities and hurdle, and valid
frozen evidence. Incomplete forecasts stay excluded with their reason.

| Pair state | Meaning |
|------------|---------|
| ELIGIBLE | A completed, comparable terminal-market or full fiscal-horizon measurement exists |
| INTERIM_ONLY | Feature 10A reports INTERIM_OBSERVATION |
| NOT_COMPARABLE | Definitions, units, timing or supported outcome-model version are incompatible |
| INSUFFICIENT_DATA | Missing outcome, observed value, required metadata or period |
| NOT_ELIGIBLE | Incomplete forecast, condition-only variable without scenario probabilities, unavailable outcome or duplicate completed pair |

Market eligibility reuses Feature 10A's exact fifth as-of anniversary, compatible
currency/share basis and scenario-range comparison. Fiscal eligibility requires
exact definitions/units, frozen starting fiscal year for CAGR and end fiscal
year `latest_fiscal_year + 5`. A single YoY observation is not a five-year CAGR.
Declared CUSTOM/1Y/5Y snapshot labels do not establish eligibility.

Revenue CAGR, year-5 annual FCF margin, diluted-share CAGR and terminal FCF
multiple support continuous Base errors. Reversed share-count scenario ordering
does not invalidate a time-aligned continuous Base comparison; it still cannot
produce an ordered scenario region. Condition-only ARR/ROIC observations without
Bear/Base/Bull forecasts are not silently converted into calibration targets.

For each exact underwriting and metric, retain the earliest eligible observation
by recording timestamp, then observed_at, then observation UUID. Earlier interim
or incompatible records do not block a later completed pair. Subsequent
completed observations are explicit duplicate exclusions, even if they would
give a different class. This avoids selecting later evidence for a better score.

Counts are explicit:

* `eligible_sample_count` counts distinct exact underwritings with any eligible metric
* `eligible_pair_count` counts included underwriting/metric pairs
* `excluded_sample_count` counts rejected candidate pairs, including one missing-outcome entry for a forecast without observations
* `candidate_pair_count` equals included pairs plus excluded pairs
* `excluded_underwriting_count` counts forecasts with no eligible pair

An observation offers one market candidate, plus each explicitly tracked
fundamental. Do not treat pair counts as independent forecasts. Multiple metrics,
versions and companies can overlap. Version-level samples are not independent
statistical trials; no significance or causal inference is made.

## Versioned sample-size guardrails

Model `forecast-calibration-v1` fixes these thresholds:

| Eligible samples in that summary | State | Output |
|---------------------------------|-------|--------|
| 0-4 | INSUFFICIENT_HISTORY_FOR_CALIBRATION | Raw traceable errors/scores only; aggregate metrics withheld |
| 5-19 | EARLY_SIGNAL_ONLY | Descriptive aggregates, no optimistic/pessimistic narrative |
| 20+ | CALIBRATION_AVAILABLE | Descriptive aggregates and limited continuous-bias interpretation |

Every probability summary, continuous metric and cohort has its own sample
guard. The global count is not the probability denominator or the count of any
one continuous variable. CALIBRATION_AVAILABLE is a data-availability label,
not proof that forecasts were good, bad or statistically independent.

## Scenario-probability calibration

Scenario probabilities refer to underwriting narratives, not originally defined
price bins. This v1 report uses a fixed operational region diagnostic and warns
about that limitation. Only a terminal MARKET_OUTCOME determines a discrete
class; individual fundamental observations do not independently classify the
same scenario probability distribution.

Use the frozen Feature 10A terminal price anchors and range comparison. Set
`t = 1e-9 * max(1, abs(Base price))`. Require strictly ordered anchors separated
by more than `2*t`:

```text
Bear region: observed price <= Bear + t
Base region: abs(observed price - Base) <= t
Bull region: observed price >= Bull - t
Otherwise: ambiguous, including between-anchor ranges
```

Non-distinct/overlapping anchors are ambiguous. A nearest scenario is never
promoted to a winner. Below-Bear and above-Bull outcomes fall in the respective
tail regions. Exact Bear and Bull anchors belong to those regions.

For the same unambiguous included market samples:

```text
assigned_probability_average = sum(assigned scenario probability) / N
observed_region_frequency = count(realized region == scenario) / N
```

Between-scenario outcomes remain comparable range observations but are listed
separately as ambiguous exclusions from probability scoring/frequency calibration.
Report comparable market count, unambiguous count and ambiguous count separately.
Unambiguous-only selection can bias frequencies and scores: do not generalize
these diagnostics to the ambiguous/excluded population.

## Brier score and probability buckets

For a single unambiguous three-class outcome:

```text
Brier = sum over Bear/Base/Bull of (assigned_probability - one_hot_outcome)^2
```

Definition `SUM_3_CLASS_UNNORMALIZED_V1` has range [0,2]. There is no division by
three or two, no probability normalization, and no Brier score for ambiguous
outcomes. Per-pair scores and exact input IDs remain available even below five
samples; the mean score is withheld until five unambiguous samples.
No score is labeled good or bad.

For each scenario separately, fixed buckets are [0,.2), [.2,.4), [.4,.6),
[.6,.8), [.8,1]. Boundary probabilities go into the higher bucket; 1 belongs
to the final bucket. Show mean assigned probability versus realized frequency
only for buckets with at least five unambiguous samples. Empty/sparse buckets
are omitted, nonempty suppressed buckets are counted, and displayed buckets
carry their own sample-size status. Bucket granularity never adapts to data.

## Continuous forecast bias

For each time-aligned fundamental:

```text
forecast_error = observed - frozen Base forecast
mean_error = sum(errors) / N
median_error = median(errors)
mean_absolute_error = sum(abs(errors)) / N
```

Errors stay in native units; ratio errors also expose `mean_error_pp = 100 *
mean_error`. Below five samples, retain raw errors but withhold aggregates.
At five or more, directional bias is BASE_ABOVE_OBSERVED for mean < -1e-9,
BASE_BELOW_OBSERVED for mean > 1e-9, otherwise
NO_DIRECTIONAL_BIAS_DETECTED. This tolerance is numerical, not a significance
test or economic materiality threshold.

At 20 or more comparable samples, negative mean revenue-growth/FCF-margin error
permits the description "Base assumptions have tended to be optimistic"; positive
mean permits "pessimistic". Share-count and multiple errors retain literal
above/below direction only, since their economic desirability is not universal.
No bias changes future assumptions or implies decision quality.

## Cohorts

Only fixed, one-dimensional cohorts are available:

* Company, grouped by stable security ID
* Frozen Feature 7 setup type
* Sector/industry if actually present in frozen company or Feature 7 metadata
* Forecast horizon (5Y in this version)
* First recorded exact-version decision available before both observation availability and the bundle's earliest measurement date, if present
* Documented variant-rationale presence/absence in the frozen manual snapshot

Missing metadata is counted explicitly, not enriched using today's universe.
Decision types remain labels; WATCH/PASS and shadow records imply no execution.
Variant presence means documentation presence, not proven correctness.

Cohorts below five distinct eligible underwritings expose counts/status only.
Larger cohorts apply the same independent guards per metric and probability
subset. There is no arbitrary cross-product slicing, search for best-performing
subsets or statistical mining.

## Reproducible report and persistence

Reports include model/rules version, as-of, company filter, forecast/measurement
date ranges, horizon, exact underwriting and outcome IDs/hashes, included pairs,
exclusions with reasons, raw probabilities/scores/errors, guarded aggregates,
cohorts and limitations.

`report_id` is the SHA-256 of canonical report content before adding its ID.
No random ID or wall-clock generation timestamp changes identical report
content. Future-recorded observations do not change a historical as-of report.
Appending newly available input intentionally creates a different report.

CLI run/company commands explicitly persist the report. SQLite schema 11 adds
an immutable report table; migration from schema 10 is additive. Identical runs
reuse the same report ID. Historical show verifies hashes and returns saved
bytes without rerunning current rules. Saves validate the report against exact
inputs in a transaction. No Feature 8/9/10A record is mutated.

## Workbench and insufficient-history example

Open **Calibration** for a read-only preview. Select UTC as-of and optionally a
company. Review status, eligible/excluded counts, scenario frequencies, Brier
metrics, probability buckets, continuous errors and fixed cohort summaries.
Low sample-size warnings remain visible. Expand exact links/exclusions/raw
values; download JSON or explicitly save an immutable report. Enter a saved
report ID to inspect its historical content.

Current 2026 records can legitimately yield:

```text
Status: INSUFFICIENT_HISTORY_FOR_CALIBRATION
Eligible forecasts: 0
Eligible metric pairs: 0
Excluded pairs: 2
Exclusions: INTERIM_ONLY (or missing outcomes, as applicable)
Probability samples: 0
Mean Brier: null
Continuous bias interpretation: unavailable
```

Genuine completed history requires elapsed time and comparable evidence.
Do not backdate records, advance recording clocks or populate synthetic outcomes
to obtain a calibration score.

## Manual PowerShell validation

These are user-run offline commands; no live validation was performed.
Run on the actual current date for current history. A future requested cutoff
does not produce missing observations. Historical reports use records available
by the requested date.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

$today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$report = $null
$reportJson = uv run owner-lens calibration run --as-of $today --json
if ($LASTEXITCODE -ne 0) { throw "Calibration failed; do not run show without a report ID." }
$report = $reportJson | ConvertFrom-Json
if (-not $report.report_id) { throw "No report ID returned." }

uv run owner-lens calibration show $report.report_id
uv run owner-lens calibration company ADBE --as-of $today --json

$a = uv run owner-lens calibration run --as-of $today --json
$b = uv run owner-lens calibration run --as-of $today --json
if ($a -cne $b) { throw "Non-reproducible calibration report" }

uv run owner-lens workbench
```

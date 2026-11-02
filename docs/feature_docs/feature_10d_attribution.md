---
title: "Feature 10D - Layered Attribution"
description: "Immutable, evidence-bounded process, forecast, decision, sizing and external-contributor reviews."
---

## Scope and identity

Feature 10D separates recorded process consistency, mature forecast errors,
decision-framework consistency, transparent contributions and investor-reviewed
external factors. It does not measure skill, luck, persistent alpha, optimal
sizing or causation.

The `layered-attribution-v1` report is an append-only JUDGMENT with semantic role
ATTRIBUTION. Schema 13 adds an immutable table without changing source records.
Every review stores a UUID, recording timestamp, as-of date, model version,
exact underwriting UUID/version/content hash, normalized investor input, copied
source context, five layers, relative outcomes and a compact summary.
Optional links identify exact decision, sizing analysis, outcome observations,
change events, calibration report and mistake review. No supplied version is
replaced with latest. A mistake review retains semantic role MISTAKE_REVIEW;
approved mistake labels never automatically become attribution conclusions.

Source facts/calculations retain their semantic categories. Investor audits,
interpretations and external explanations remain judgments. The store rebuilds
and verifies the report against its inputs before saving canonical JSON, hashes
the payload and rejects updates, deletes and replacement inserts. Historical
reads verify identity/hash and return saved bytes rather than recomputing them.

## Evidence and time boundaries

The cutoff is the earlier of recording time and the as-of day's UTC end.
Underwriting, decision, outcomes, approvals and linked reviews must have existed
by cutoff. Selected outcomes must match the exact frozen underwriting.
Calibration inputs receive their underlying timestamp/hash checks, not merely a
same-day report-date check. Future sources are rejected.

An unresolved layer does not prevent a review. Missing evidence stays missing.
No new evidence is fetched, no outcome is manufactured and no review is created
automatically. Later source records cannot rewrite a saved review.

## Five independent layers

### Process attribution

Mechanical checks reuse Feature 10C for supporting-evidence verification,
disconfirming evidence presence, variant documentation, unresolved challenger
questions, hurdle consistency, sizing proposals and required re-underwriting.
An additional check asks whether disconfirming evidence was considered rather
than merely present.

Optional `process_reviews` supply code, status, `performed_at`, rationale,
evidence references and `investor_reviewed: true`. Valid audit statuses are
SATISFIED, EXCEPTION, UNRESOLVED and NOT_APPLICABLE. Check codes are:

```text
SUPPORTING_EVIDENCE_VERIFIED
DISCONFIRMING_EVIDENCE_PRESENT
DISCONFIRMING_EVIDENCE_CONSIDERED
VARIANT_VIEW_DOCUMENTED
CHALLENGER_QUESTIONS
HURDLE_CONSISTENCY
SIZING_WITHIN_POLICY
REUNDERWRITING_PERFORMED
```

Audit evidence must exist when work was performed. Initial checks cannot be
completed after the linked decision; follow-up re-underwriting and sizing
checks may occur later. Investor audits cannot erase or downgrade a mechanical
exception. Any exception yields PROCESS_EXCEPTIONS; all checks satisfied or
explicitly inapplicable yields PROCESS_COMPLIANT; otherwise PROCESS_UNRESOLVED.
These are bounded source/audit checks, not proof that compliance caused return.
Selected change events define the scope; this is not a full account audit.

### Forecast attribution

Feature 10A/10B comparability is reused without interpolating paths or changing
units. Terminal prices require the exact five-year anniversary; fundamentals
require the frozen fiscal five-year definitions, units and period alignment.
Interim evidence yields NOT_MATURE, incompatible evidence NOT_COMPARABLE and
missing measurements INSUFFICIENT_DATA.

For eligible revenue CAGR, year-five FCF margin, share-count CAGR and terminal
FCF multiple, error is observed minus frozen Base. An error below/above the
material boundary yields MISSED_LOW/MISSED_HIGH. Otherwise it is SUPPORTED.
Boundaries are 0.01 for ratios (one percentage point) and 1 multiple turn, with
1e-9 numerical tolerance. Direction is arithmetic, not economic desirability:
lower share-count growth is not automatically worse.

For terminal price, below Bear is MISSED_LOW, above Bull is MISSED_HIGH and
numerically near Base is SUPPORTED. Between-anchor regions remain ambiguous
and NOT_COMPARABLE for directional attribution; no nearest-scenario winner is
invented. Raw eligibility, region and errors remain available. Linked calibration
is copied with its independent sample-size status, not reinterpreted as skill.

### Decision attribution

Only original frozen decision context is used. BUY/ADD with expected return at
or above its recorded hurdle (within 1e-9) is consistent with that bounded rule;
below-hurdle actions are inconsistent. An exact decision-linked sizing proposal
already recorded at decision time and exceeding its cap is an inconsistency.

WATCH/PASS can be consistent when an explicit reviewed framework basis matches
the original context: HURDLE with negative spread, EVIDENCE_INSUFFICIENT with
frozen missing dimensions, or UNRESOLVED_RISK with frozen unresolved questions.
No prose interpretation or hindsight price rule is used. Other actions or
unsupported/missing bases remain DECISION_CONTEXT_INCOMPLETE.

These rules report CONSISTENT_WITH_RECORDED_FRAMEWORK or
INCONSISTENT_WITH_RECORDED_FRAMEWORK, not overall investment quality. They do
not claim that every possible policy or risk was checked.

### Portfolio and sizing attribution

Sizing proposals and Feature 9B shadows are HYPOTHETICAL_ONLY, never execution
proof. A hypothetical contribution is proposed constant starting weight times
the selected frozen-price return. WATCH/PASS without execution evidence reports
NOT_DEPLOYED, scoped to that recorded action rather than proof of account cash.
BUY without execution evidence remains NOT_ESTABLISHED.

There is no transaction ledger in OwnerLens. Optional `actual_position` accepts
bounded investor-verified opening execution/position evidence:

```json
{
  "category": "FACT",
  "units": 10,
  "entry_price": 25,
  "entry_at": "2026-06-03T13:00:00+00:00",
  "currency": "USD",
  "starting_portfolio_value": 1000,
  "end_observation_id": "replace-with-selected-exact-observation-id",
  "constant_units_no_flows": true,
  "basis": "EOD_CLOSE_SAME_SHARE_BASIS",
  "rationale": "Replace with verified execution and opening NAV evidence.",
  "evidence_references": [{"title": "Replace with sourced execution evidence"}],
  "investor_reviewed": true
}
```

This example shows field shape, not an Adobe trade. Entry follows the exact
decision and precedes cutoff; selected end evidence must be later, currency and
same-share basis compatible. Positive units, entry and opening NAV are required;
opening unlevered cost cannot exceed NAV. Constant units/no flows is mandatory.

Position contribution is units times (end price minus entry price), in currency.
Portfolio contribution is that mark-to-market gain divided by opening NAV.
Position price return uses actual entry, not frozen underwriting price.
These exclude dividends, fees, taxes and sales, and are not realized P&L or full
portfolio performance. Flows, leverage and changing positions are unsupported.

Proposal `policy_status` remains distinct from `actual_policy_status`. Actual
opening weight is checked against an explicit cap only when linked sizing
predates entry, its portfolio date matches entry and required dimensions are
complete. Otherwise actual policy remains unresolved. Frozen cash, thesis/sector
weights and warnings are shown as exposure context, not fabricated causal
contributions or an optimal-size judgment.

### External contributors

The investor explicitly selects EXTERNAL_CONTRIBUTOR_RECORDED,
NO_EXTERNAL_CONTRIBUTOR_RECORDED or UNRESOLVED. Recorded status requires
nonempty reviewed contributors, each with kind, statement, rationale and
evidence. Other statuses require an empty list. No macro, technology or
multiple-expansion explanation is inferred from returns.

## Relative outcomes and cross-case summaries

`relative_outcomes` link an exact recorded benchmark, BEST_ALTERNATIVE or
PASS_CANDIDATE shadow to a selected outcome. ACTUAL_CHOICE is not a comparator.
Inputs require sourced start/end prices, identical dates/currency/share basis,
`return_basis` UNDERWRITING_MARKET or ACTUAL_POSITION, and explicit review.
The best alternative means best recorded at the decision, not best ex post.

UNDERWRITING_MARKET starts at the frozen underwriting market date. Alternatives
must match their exact frozen shadow start; benchmark placeholders require a
manually verified start. ACTUAL_POSITION requires verified execution and the
exact same end observation/entry interval; comparator endpoints for that
interval are manually verified, not falsely labeled frozen shadow starts.
`difference` is chosen price return minus comparator price return. Outputs are
BENCHMARK_OUTCOME/SHADOW_ALTERNATIVE_OUTCOME with semantic role RELATIVE_OUTCOME,
not alpha or causal attribution. Frozen-market rows never establish execution.

`outcome` uses actual position price return when supplied; otherwise it is
explicitly scoped as FROZEN_UNDERWRITING_MARKET_NOT_CAPITAL. `market_outcome`
stays separate so favorable frozen-price results cannot conceal adverse actual
entry results. Mixed, zero or absent market returns remain unresolved.

Summaries use the earliest mature review per exact underwriting, or earliest
review if none are mature. Other reviews remain in history and do not inflate
case counts. Versions may overlap and are not independent trials.
Below five cases the warning is INSUFFICIENT_ATTRIBUTION_HISTORY; otherwise
DESCRIPTIVE_ONLY. Compliance rate requires five resolved process cases.
Average benchmark difference requires five eligible terminal five-year
UNDERWRITING_MARKET comparisons, one per case; interim and actual execution
periods are not pooled. Raw individual comparisons remain available.

Forecast misses count each metric/direction once per case. Proposal and actual
sizing exceptions are separate counts. Fixed cohorts use decision type,
frozen Feature 7 setup and variant-view presence, with missing metadata counts,
per-cohort warnings and outcomes separated by market/actual basis.
No statistical-significance, causal or persistent-alpha conclusions are made.

## Workbench and synthetic example

Open **Attribution**, select an exact version, paste/import strict review JSON,
inspect evidence and check explicit investor review before appending. History
shows linked records, all layers, relative comparisons, interpretation,
unresolved areas and downloadable canonical JSON. Navigation does not write.

An illustrative synthetic ADBE case could report:

```text
Process: PROCESS_COMPLIANT (explicit contemporaneous audit evidence)
Revenue CAGR: MISSED_LOW (Base 10%, comparable realized 5%)
FCF margin: SUPPORTED (comparable evidence within materiality)
Decision: CONSISTENT_WITH_RECORDED_FRAMEWORK (original BUY above hurdle)
Sizing: HYPOTHETICAL_ONLY (proposal, no execution evidence)
External: UNRESOLVED
Market outcome: ADVERSE, not an actual capital outcome
```

Interpretation: "The adverse frozen-price outcome was associated with a growth
forecast miss. Recorded hurdle consistency and process audits remained
compliant. There is no verified execution or external causal evidence."
This is not an assertion about Adobe and does not establish skill or bad luck.
The supplied [manual template](../examples/adbe_attribution.sample.json)
intentionally contains no outcome or execution evidence and stays unresolved.

## Manual PowerShell validation

No live validation was performed. These commands are for you to run offline
against your chosen exact completed version. Replace 7 when appropriate.
First prepare a draft and inspect every assertion, exact link and approval:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

New-Item -ItemType Directory -Force .\data\attribution | Out-Null
$draft = Get-Content .\docs\examples\adbe_attribution.sample.json -Raw | ConvertFrom-Json
$draft.as_of_date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$draft | ConvertTo-Json -Depth 40 | Set-Content .\data\attribution\adbe-attribution.json -Encoding utf8
notepad .\data\attribution\adbe-attribution.json
```

Only after reviewing the draft, explicitly append and inspect the saved result:

```powershell
$review = $null
$reviewJson = uv run owner-lens attribution review create ADBE --version 7 --file .\data\attribution\adbe-attribution.json --json
if ($LASTEXITCODE -ne 0) { throw "Creation failed; do not run show." }
$review = $reviewJson | ConvertFrom-Json
if (-not $review.review_id) { throw "No review ID returned; do not run show." }

uv run owner-lens attribution review show $review.review_id --json
uv run owner-lens attribution review history ADBE --json
uv run owner-lens attribution summary --json
uv run owner-lens workbench
```

All top-level fields shown in the template are required. Optional linked IDs
may be null; observations/events are explicit lists. Reviewed nested objects
require rationale, nonempty evidence references and `investor_reviewed: true`.
References support the existing title/URI/observed-at evidence format.
Do not backdate synthetic evidence to force mature forecast conclusions.

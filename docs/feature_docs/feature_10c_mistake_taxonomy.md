---
title: "Feature 10C: Mistake Taxonomy"
description: "Append-only investor post-mortems with evidence-gated candidates and separate outcome, forecast and process dimensions."
---

## Purpose and authority

Mistake Review separates an adverse outcome, a forecast miss, a process exception
and an investor's explanation. It never infers skill, scores luck, assesses decision
quality or performs attribution. A poor outcome need not receive a mistake label.
A favorable outcome does not establish a good process.

The [review domain](../../src/owner_lens/mistakes.py) operates offline over exact
immutable Feature 8, 9 and 10 records. No fetching, agents, automatic reviews,
probability updates, decisions, sizing changes or re-underwriting occur.

## First-class taxonomy

| Category | Codes |
|----------|-------|
| EVIDENCE_RESEARCH | MISSING_RELEVANT_EVIDENCE, UNVERIFIED_EVIDENCE, IGNORED_DISCONFIRMING_EVIDENCE, STALE_EVIDENCE, MISREAD_EVIDENCE |
| ASSUMPTION_FORECAST | GROWTH_TOO_HIGH, GROWTH_TOO_LOW, MARGIN_TOO_HIGH, MARGIN_TOO_LOW, SHARE_COUNT_ASSUMPTION_WRONG, TERMINAL_MULTIPLE_TOO_HIGH, TERMINAL_MULTIPLE_TOO_LOW, PROBABILITY_TOO_OPTIMISTIC, PROBABILITY_TOO_PESSIMISTIC, SCENARIO_RANGE_TOO_NARROW |
| THESIS_CAUSAL_MODEL | WRONG_BUSINESS_DRIVER, WRONG_CAUSAL_EXPLANATION, MOAT_OVERESTIMATED, MOAT_UNDERESTIMATED, DISRUPTION_RISK_UNDERESTIMATED, OPTIONALITY_UNDERESTIMATED, TEMPORARY_VS_STRUCTURAL_MISREAD |
| VALUATION | TERMINAL_ASSUMPTION_UNJUSTIFIED, VALUATION_MODEL_INAPPROPRIATE, RISK_NOT_REFLECTED_IN_SCENARIOS, EXPECTED_RETURN_OVERSTATED |
| DECISION_PROCESS | ACTED_WITHOUT_REQUIRED_EVIDENCE, IGNORED_CHALLENGER_WARNING, FAILED_TO_REUNDERWRITE, CHANGED_THESIS_WITHOUT_NEW_EVIDENCE, OVERREACTION_TO_NOISE, INCONSISTENT_HURDLE |
| PORTFOLIO_SIZING | POSITION_TOO_LARGE, POSITION_TOO_SMALL, THESIS_CONCENTRATION_IGNORED, DOWNSIDE_BUDGET_IGNORED, CASH_OPTIONALITY_IGNORED |
| BEHAVIORAL | FOMO, ANCHORING, CONFIRMATION_BIAS, LOSS_AVERSION, ACTION_BIAS, PATIENCE_FAILURE, THESIS_ATTACHMENT, RECENCY_BIAS |
| NO_MISTAKE_EXTERNAL | NO_IDENTIFIED_MISTAKE, ADVERSE_OUTCOME_WITH_REASONABLE_PROCESS, FAVORABLE_OUTCOME_WITH_WEAK_PROCESS, UNRESOLVED |

These are investor classifications, not automatic causal diagnoses.
External-outcome labels do not establish that luck caused an outcome.
NO_IDENTIFIED_MISTAKE cannot coexist with an approved mistake category.

## Immutable review schema

Model `mistake-review-v1` produces:

* `review_id`: generated UUID; each submission is a new independent review
* `recorded_at`: actual UTC recording timestamp; `review_date`: investor's date
* `category`: JUDGMENT
* `underwriting`: exact UUID, version and content hash; stable `security_id`
* `judgment`: reviewer, rationale, confidence, evidence references, selected links,
  explicitly approved labels, optional primary code and unresolved questions
* `links`: optional exact decision ID, outcome IDs, calibration report ID,
  change-event IDs and Feature 9C sizing-analysis ID
* `context`: copied frozen forecast, linked original records, approvals available
  by cutoff and completed/excluded follow-up underwriting identities
* `comparison_evidence`, `process_checks`, `candidate_labels`, `approved_labels`
* `primary_mistake`: optional, investor-selected approved code
* `secondary_mistakes`: remaining approved codes; all codes if primary is null
* `quality`: separate outcome, forecast, process and decision fields

Each label preserves code, taxonomy category, LOW/MEDIUM/HIGH confidence,
rationale, evidence references, `machine_suggested`, `investor_approved` and
`semantic_category: JUDGMENT`. Original copied facts, assumptions, expectations,
judgments and calculations retain their categories.

Create accepts [the manual template](../examples/adbe_mistake_review.sample.json).
Links omitted or null mean no selection, never latest. No labels are mandatory:
`approved_labels: []` is valid. Label confidence and review confidence are separate.

SQLite schema 12 adds the review table and update/delete/replace rejection
triggers. Saves rebuild and verify the submitted review against exact sources
inside a transaction. Reads verify hashes and return stored bytes without
re-running suggestions. Later evidence, approvals or rules do not change a
historical review. There is no edit, replace or automatic-approval operation.

## Candidate versus approved

Suggest is read-only. By default it explicitly enumerates all observations and
change events for the requested version available at cutoff; its returned links
show that selection. It does not choose a decision, sizing analysis or calibration
report implicitly. Optional IDs select those records exactly. Workbench and create
use only the links explicitly selected by the investor.

Candidates always have `machine_suggested: true`, `investor_approved: false`.
They do not enter approved summaries or become primary/secondary mistakes.
Approval is never inferred from matching a candidate code.

For create, each approved-label entry must contain:

```json
{
  "code": "UNRESOLVED",
  "confidence": "LOW",
  "rationale": "Investor rationale, not a machine conclusion.",
  "evidence_references": [{"title": "Exact selected evidence"}],
  "investor_approved": true
}
```

Behavioral codes are never suggested. Only explicit investor review with rationale,
references and boolean approval can record them. Manual research, causal-model,
valuation and process judgments require the same approval, even without a
candidate. Their causal meaning is not machine-verified.

## Evidence guardrails and materiality

The evidence cutoff is the earlier of recording time and UTC review-date end.
Review date cannot be future. Selected underwritings, outcomes, decisions,
events, approvals, sizing and calibration evidence must be available by cutoff.
Foreign-version links fail explicitly; no latest substitution is allowed.
Future-recorded observations are not silently included in historical suggestions.

Comparison eligibility reuses Feature 10B's pair rules and Feature 10A's frozen
comparisons. It requires exact units, observables and complete fiscal/terminal
horizons, with verified FACT provenance. No fuzzy matching, unit conversions or
interpolated paths are introduced.

| Evidence state | Meaning |
|----------------|---------|
| REVIEWABLE | Comparable completed evidence or a supported deterministic candidate exists |
| INTERIM_ONLY | Selected evidence is interim and has no supported candidate |
| NOT_COMPARABLE | Definitions, units or horizons are incompatible |
| INSUFFICIENT_EVIDENCE | No usable outcome or supported candidate exists |

These states govern machine evidence sufficiency, not permission to document an
investor's unresolved review. They do not prove that a mistake occurred.

Versioned material-error thresholds are strictly greater than:

| Metric | Native-unit threshold |
|--------|-----------------------|
| Revenue CAGR | 0.01 ratio (1 percentage point) |
| Year-5 FCF margin | 0.01 ratio (1 percentage point) |
| Share-count CAGR | 0.01 ratio (1 percentage point) |
| Terminal FCF multiple | 1.0 multiple turn |

Use an additional `1e-9` numerical tolerance at boundaries. These fixed v1
thresholds are diagnostic policy, not statistical significance.

Comparable observed-minus-Base errors suggest the directional growth, margin,
share-count or multiple code. Comparable fundamentals outside the full frozen
scenario span by more than the same threshold suggest SCENARIO_RANGE_TOO_NARROW.
A terminal price result alone never diagnoses a valuation or business-model error.

Manual forecast labels still require a relevant comparable completed metric.
Probability judgments require a linked 10B probability summary with
CALIBRATION_AVAILABLE (at least 20 unambiguous samples), including this exact
underwriting in its raw scores. No probability-error candidate is generated.
The calibration report's region-selection caveats remain in copied evidence.
Portfolio labels require exact Feature 9C context. No sizing label follows from
a stock rising or falling.

## Process checks and candidate rules

Checks are CALCULATION questions, not mistake verdicts:

* Supporting-evidence verification remains UNRESOLVED where no verification
  audit exists. A FACT category or citation alone is not proof of verification.
* Disconfirming-evidence presence is SATISFIED or EXCEPTION. Presence does not
  prove adequacy or that contrary evidence was heeded.
* Variant-rationale presence is SATISFIED; absence remains UNRESOLVED.
* Challenger questions are copied from the exact selected decision where present.
  Their presence does not establish that a warning was ignored or never resolved.
* BUY/ADD judgment below the frozen expected-return hurdle is an EXCEPTION.
  WATCH/PASS and missing decisions remain unresolved, not trades.
* Sizing compares the recorded proposal with its own frozen explicit cap.
  Missing proposal/context remains unresolved. Complete in-cap proposals can
  satisfy this check; missing dimensions prevent an overall compliance conclusion.
* Only selected approved THESIS_UPDATE/THESIS_BREAK events require re-underwriting.
  Pending events do not. A later NOISE event cannot cancel a prior requirement.

FAILED_TO_REUNDERWRITE is a candidate only when such an approval predates the
review day and no later completed underwriting for the same security was recorded
by cutoff. A saved valuation and valid completed probabilities/hurdle are required
for a follow-up to count; incomplete follow-ups expose exclusion reasons.
Temporal succession is not proof that the specific concern was resolved.
No deadline was encoded in 9D: investors must assess elapsed time and work outside
OwnerLens before approving the candidate.

Sizing proposals can suggest POSITION_TOO_LARGE when above their own cap,
DOWNSIDE_BUDGET_IGNORED when the proposed contribution breaches its explicit
budget, CASH_OPTIONALITY_IGNORED when the proposed increment breaches the cash
reserve, and THESIS_CONCENTRATION_IGNORED for selected exposure tags breaching
their explicit limit. These remain proposals, not evidence of executed trades
or investor intent.

## Separate quality dimensions

The descriptive quality projection keeps:

* `outcome_quality`: FAVORABLE/ADVERSE by positive/negative selected price-only
  returns; missing, mixed or zero returns are UNRESOLVED
* `forecast_quality`: MISSED if a comparable fundamental Base error exceeds its
  material threshold; otherwise SUPPORTED for the selected comparable metrics,
  or UNRESOLVED if none exist
* `process_quality`: EXCEPTIONS for a documented check exception, COMPLIANT only
  if all checks are satisfied, otherwise UNRESOLVED
* `decision_quality`: always NOT_ASSESSED_HERE

SUPPORTED concerns only the selected metrics, not the entire thesis. The process
projection remains unresolved when verification/resolution audits are missing.
Investor classifications can express a judgment about reasonable or weak
process without rewriting these mechanical checks.

## Workbench and summaries

Open **Mistake Review** and select an exact completed version. Select optional
decision, outcome, event, sizing and calibration links. Inspect copied evidence,
quality dimensions, process questions and machine candidates.

The form starts with no selected labels. Select codes, supply per-label approval
JSON and rationale/evidence, and check explicit approval before appending.
Selected codes must exactly match approved JSON entries. An empty approved list
can document an unresolved review. Historical reviews display approved labels,
primary/secondary choices, reviewer rationale and unresolved questions, with
JSON download.

Summary counts use approved labels only. Categories count each review once per
category; labels count each approved code once per review. Multiple reviews of
the same version count separately and are not independent trials. No-mistake/
external labels are kept distinguishable from actual mistake categories.
Below five labeled reviews show INSUFFICIENT_REVIEW_HISTORY; otherwise
DESCRIPTIVE_ONLY. Neither status claims statistically significant tendencies.

## Manual PowerShell validation

No live validation was performed. These commands are for you to run offline
against your chosen exact version. Review the template before approving any
label. Replace version 7 if your intended immutable version differs.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

uv run owner-lens mistakes review suggest ADBE --version 7 --json

New-Item -ItemType Directory -Force .\data\reviews | Out-Null
$inputReview = Get-Content .\docs\examples\adbe_mistake_review.sample.json -Raw | ConvertFrom-Json
$inputReview.review_date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$inputReview | ConvertTo-Json -Depth 30 | Set-Content .\data\reviews\adbe-review.json -Encoding utf8
# Inspect and edit the file's rationale, exact links and explicit approvals first.

$review = $null
$reviewJson = uv run owner-lens mistakes review create ADBE --version 7 --file .\data\reviews\adbe-review.json --json
if ($LASTEXITCODE -ne 0) { throw "Creation failed; no review ID was created. Do not run show." }
$review = $reviewJson | ConvertFrom-Json
if (-not $review.review_id) { throw "No review ID returned; do not run show." }

uv run owner-lens mistakes review show $review.review_id --json
uv run owner-lens mistakes review history ADBE --json
uv run owner-lens mistakes summary --json
uv run owner-lens workbench
```

The template's UNRESOLVED label is an explicit investor choice, not a populated
Adobe outcome or an automatic conclusion. Do not backdate outcomes or add
synthetic future evidence to obtain forecast-mistake labels.

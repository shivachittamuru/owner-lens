---
title: "Feature 9B: Decision Record and Shadow Portfolio"
description: "Append-only investor judgments and frozen counterfactual starts tied to exact completed underwriting versions."
---

## Purpose and boundaries

Record what you knew, believed and chose, together with the exact alternatives
you considered. A later feature can observe outcomes without rewriting these
starting conditions. A good decision can have a bad outcome, and a bad decision
can have a good outcome. No outcome is interpreted as decision quality.

Feature 9B has no position sizing, portfolio weights, optimization, correlation,
factor analysis, tax allocation, options, automatic decisions, skill/calibration
scores, attribution, agents, event-driven re-underwriting or P&L dashboard.
It does not retrieve current market prices or calculate returns.

The shared domain is [`decisions.py`](../../src/owner_lens/decisions.py).
The CLI and Workbench use the same validation and append-only storage boundary.

Opportunity Comparison also offers an inline **Evaluate Allocation -> Record
Decision** workflow. It carries the exact comparison and alternatives, calls
existing 9C calculations, then requires explicit investor judgment and approval.
When sizing is available, a saved 9C analysis links to the immutable decision;
intended weight is retained there, not added to the 9B schema. This path creates
no shadow or actual position. WATCH/PASS do not require portfolio context.
See the [contextual workflow and manual steps](feature_09c_portfolio_sizing.md#contextual-comparison-to-decision-workflow).
The standalone decision/shadow controls remain unchanged.

## Decision-record schema

`DecisionSnapshot` is a frozen domain value serialized as canonical JSON:

| Field                | Meaning                                                         |
|----------------------|-----------------------------------------------------------------|
| `decision_id`        | New UUID per approval; contextual retries reuse the approval UUID |
| `recorded_at`        | Time this record was actually created, UTC                       |
| `decision_at`        | Investor-declared decision timestamp, UTC                        |
| `as_of_date`         | Explicit information cutoff date; defaults to decision UTC date  |
| `state`              | `DECISION_STATE`, never a current observation                     |
| `model_version`      | `decision-record-v1`                                             |
| `judgment`           | Action, rationale, confidence, primary reason, risk, change rule  |
| `chosen`             | Exact original underwriting and frozen Feature 9A projection     |
| `alternatives`       | Exact opportunity copies, investor disposition and reason        |
| `comparison`         | Optional complete validated Feature 9A JSON export               |
| `comparison_status`  | `FROZEN` or `NOT_PROVIDED`                                        |
| `alternatives_status`| `RECORDED` or `NONE_RECORDED`                                     |
| `shadow_requested`   | Explicit opt-in; false creates no shadow entries                  |
| `shadows`            | Complete immutable bundle of any requested shadow starts          |

`judgment.category` must be `JUDGMENT`. Actions are exactly `BUY`, `ADD`, `HOLD`,
`WATCH`, `PASS`, `TRIM`, `EXIT`. Confidence is the investor's explicit `LOW`,
`MEDIUM` or `HIGH`, not a probability or calibrated score. Rationale,
`primary_reason`, `biggest_risk` and `what_would_change_decision` are required,
non-empty strings. Text is preserved exactly, not paraphrased or inferred.

`chosen.underwriting` retains `security_id`, frozen ticker, exact underwriting
UUID/version/hash, original creation/as-of dates and original `snapshot_json`
bytes. CIK is not used as security identity. The copied
`chosen.opportunity.summary` retains the saved required-return hurdle at
`investor_policy.required_return`, frozen price/date, expected CAGR and
classification, Bear/Base/Bull values/CAGRs/probabilities, variant view and all
local sensitivities. The copied quality section preserves the Feature 9A
bounded challenger state/model, unresolved questions and missing dimensions.
It is the 9A offline-rule state, not a silently selected latest saved review.

Original semantic categories remain intact: price FACT and consensus
EXPECTATION in the original snapshot, ASSUMPTION scenarios and drivers,
JUDGMENT probabilities/hurdle/rationales, CALCULATION values/returns/sensitivity.
Nothing is relabeled JUDGMENT merely because it was copied into a decision.
Feature 9B does not override the saved underwriting hurdle.

Each alternative contains the same exact frozen opportunity structure plus
a `JUDGMENT` reason and a disposition: `PREFERRED`, `DEFERRED`, `PASSED_OVER`.
Preferred means an investor-described competing opportunity, not an execution.
Duplicate underlying UUIDs, including repeating the chosen UUID as an
alternative through a ticker alias, are rejected. Different immutable versions
of the same security can be explicitly considered.

An optional comparison must contain exactly the chosen opportunity and all
recorded alternatives. It is checked against those exact versions and current
Feature 9A rules at save, then copied with its model version. An altered or
incompatible comparison fails explicitly, rather than being silently replaced.
Omitting a comparison or alternatives is valid and explicitly represented.

The relational `decision_records` table indexes decision ID, security ID,
ticker, underwriting UUID/version, decision time and as-of date. Its
`snapshot_json` and SHA-256 `content_hash` preserve the complete value.

## Shadow-portfolio schema

Shadow creation is optional and atomic with decision creation. Each entry is
an independent hypothetical starting point, not part of a weighted portfolio.

| Field                         | Meaning                                                  |
|-------------------------------|----------------------------------------------------------|
| `shadow_id`, `decision_id`     | Immutable entry UUID and parent decision UUID             |
| `decision_at`, `as_of_date`    | Exact same decision event and cutoff as the parent        |
| `security_id`, `ticker`        | Frozen identity, not a current universe lookup            |
| `underwriting_id/version/hash` | Exact associated underwriting, absent only for benchmark  |
| `role`                        | Explicit counterfactual role                              |
| `action`                      | Parent decision's recorded action, not an execution       |
| `frozen_price`, `market_date`  | Copied underwriting price FACT/date                       |
| `price_category`              | `FACT`; benchmark price is missing, never zero            |
| `price_basis`                 | `FROZEN_UNDERWRITING` or `BENCHMARK_PLACEHOLDER`            |
| `basis`                       | `INDEPENDENT_HYPOTHETICAL_100_USD`                         |
| `notional_usd`, `currency`     | Explicit fixed 100 USD per independent comparison         |
| `state`, `outcome_state`       | `DECISION_STATE`, `NOT_OBSERVED`                           |
| `missing_reason`              | Explicit benchmark price/provenance absence               |
| `model_version`               | `shadow-entry-v1`                                         |

Roles follow conservative validation:

* Exactly one `ACTUAL_CHOICE` is created when shadow creation is requested.
  It identifies the opportunity associated with the decision, even for
  `WATCH`, `PASS`, `TRIM` or `EXIT`; it never asserts a purchase or holding.
* At most one `BEST_ALTERNATIVE` may reference an explicitly considered,
  non-`PASSED_OVER` alternative.
* Any number of distinct `PASS_CANDIDATE` entries may reference explicitly
  `PASSED_OVER` alternatives.
* At most one `BENCHMARK` can be included explicitly. Feature 9B uses `^GSPC`,
  an S&P 500 reference placeholder, with no fabricated security ID,
  underwriting, price or market date. This is not a tradable instrument.
* The same underwriting cannot occupy multiple shadow roles for one decision.
  Duplicates or inconsistent roles are errors, never silently deduplicated.
* Considered alternatives without a requested shadow role remain fully recorded
  in the decision; they do not automatically become hypothetical investments.

The `shadow_entries` table stores entry ID, decision/underwriting links, role,
canonical snapshot JSON and content hash. Its frozen entries are also embedded
in the parent decision bundle. Reads verify the two copies agree.

## Outcome preparation

Frozen market price/date, decision event time, security identity, USD currency,
underwriting identity, parent decision and explicit $100 basis provide the start
for future observation/return calculations. Price date can precede decision
date: this is the selected underwriting's frozen price, not a claim about a
quote or fill on the decision date. Both dates remain visible.

No observations or return values are fabricated. A later feature must append
separate `CURRENT_OBSERVATION` or dated outcome data, never overwrite
`DECISION_STATE`. Total return will also require distributions and
corporate-action treatment; price alone is not total return. The S&P placeholder
cannot support benchmark returns until actual point-in-time data is captured.

## Immutability, time and reproducibility

Schema version 7 adds tables/indexes/triggers without modifying underwritings
or existing decisions. SQLite rejects UPDATE, DELETE and conflicting
INSERT OR REPLACE operations on decisions and shadow entries. Storage validates
exact source identities and copied evidence before insertion. The decision and
all shadows commit together or all roll back.

A changed mind requires a new decision ID and an additional history row.
The same action can also be explicitly recorded again. Re-rendering a
Workbench page is not a save. History is ordered by decision time, then stable
insertion order for timestamp ties. Backdated decisions retain their later
`recorded_at`; no claim is made that they were recorded contemporaneously.

Decision timestamps require a timezone. Future decision times or future as-of
dates are rejected. Source underwritings, including alternatives, must have
existed by the earlier of decision time and as-of end-of-day. Feature 9A
additionally validates the source underwriting's own frozen evidence cutoff,
so later observations cannot enter through a legacy record or a reference.
Deterministic projections can be calculated at save from earlier frozen inputs;
this is not evidence that a historical investor saw a later-generated report.
The stored investor judgment remains their explicit assertion.

Creating another underwriting or later acquiring evidence cannot change these
copies. Reading a decision never recalculates Feature 8 or Feature 9A, selects
latest alternatives, fetches prices or selects latest challenger runs. Repeated
JSON reads are stable, with sorted keys, original finite numeric values and
persisted timestamps/UUIDs. Separate saves intentionally produce separate IDs.
Duplicate JSON keys, non-finite constants, unknown fields and malformed roles
are rejected explicitly.

## Workbench UX

There are three entry points:

1. **Company > Underwriting > Record decision for this underwriting version**
   opens Decisions with that explicitly displayed version selected.
2. **Opportunity Comparison > Record a decision from this comparison** carries
   the complete exact comparison to Decisions. Select the focal opportunity
   and give dispositions/reasons for every other compared version.
3. **Decisions** allows direct exact-version selection with no default/latest
   selection and an optional alternatives picker.

The form shows the frozen source price/date and saved hurdle, then requires
action, confidence, rationale, primary reason, risk and what changes the
decision. Optional historical decision/as-of inputs are explicit.
Choose shadow roles and opt into independent $100 starts. Save only with
**Save new immutable decision**. Validation errors preserve the form and write
nothing. Success displays the new immutable ID.

Decision history is separate and read-only, with full frozen JSON downloads.
**Shadow Portfolio** shows decision date, ticker, role, frozen price/date,
underwriting version, parent decision/action, basis and missing outcome state.
It has no P&L metrics or editing controls.

## Illustrative ADBE decision and alternatives

The [sample JSON](../examples/adbe_decision.sample.json) is illustrative
investor-authored input, not a real company recommendation:

* ADBE:7: `WATCH`, medium confidence. Expected return is attractive, but evidence
  verification and the AI-disruption thesis still need validation.
* GOOGL:2: `PREFERRED` competing alternative, with the supplied reason.
* MSFT:2: `DEFERRED`, retaining its exact version and reason.
* NFLX:1: `PASSED_OVER`, retaining its exact version and reason.
* Change condition: verified AI monetization evidence or a more favorable entry
  price, recorded exactly rather than interpreted as an automatic trigger.

If shadow creation is enabled in the sample, ADBE is `ACTUAL_CHOICE`, GOOGL is
`BEST_ALTERNATIVE`, NFLX is `PASS_CANDIDATE`, and `^GSPC` is a benchmark
placeholder. MSFT is considered but not shadow-tracked. Every hypothetical start
has an independent $100 basis; no real portfolio size is implied.

## Manual PowerShell validation

Implementation tests use temporary stores and offline fixtures. These commands
are for you to run against existing records; no live validation was performed.
Check actual version numbers first and edit the illustrative file before saving.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

uv run owner-lens underwriting history ADBE
uv run owner-lens underwriting history GOOGL
uv run owner-lens underwriting history MSFT
uv run owner-lens underwriting history NFLX

New-Item -ItemType Directory -Force .\data\decisions | Out-Null
Copy-Item .\docs\examples\adbe_decision.sample.json .\data\decisions\ADBE.json
```

After reviewing the input and adjusting exact versions and investor text,
optionally attach the matching comparison before saving:

```powershell
$comparison = uv run owner-lens compare-underwriting ADBE:7 GOOGL:2 MSFT:2 NFLX:1 --json
if ($LASTEXITCODE -ne 0) { throw "Exact comparison failed; no decision saved" }
$decisionInput = Get-Content .\data\decisions\ADBE.json -Raw | ConvertFrom-Json
$decisionInput.comparison = $comparison | ConvertFrom-Json
$decisionInput | ConvertTo-Json -Depth 100 | Set-Content .\data\decisions\ADBE.json -Encoding utf8

uv run owner-lens decision create ADBE --version 7 --file .\data\decisions\ADBE.json --json
uv run owner-lens decision show ADBE
uv run owner-lens decision history ADBE
uv run owner-lens decision history ADBE --json
uv run owner-lens shadow show
uv run owner-lens shadow show --json
uv run owner-lens workbench --provider fmp
```

`decision show` without an ID shows the most recent decision, not a latest
underwriting substitution. For an exact decision, use the saved UUID:

```powershell
$historyJson = uv run owner-lens decision history ADBE --json
if ($LASTEXITCODE -ne 0) { throw "History read failed" }
$history = @($historyJson | ConvertFrom-Json)
if ($history.Count -eq 0) { throw "No recorded decisions" }
$id = $history[-1].decision_id
$first = uv run owner-lens decision show ADBE --decision-id $id --json
if ($LASTEXITCODE -ne 0) { throw "Exact decision read failed" }
$second = uv run owner-lens decision show ADBE --decision-id $id --json
if ($LASTEXITCODE -ne 0) { throw "Repeated decision read failed" }
if ($first -cne $second) { throw "Frozen output changed" }
uv run owner-lens shadow show --decision-id $id --json
```

To record a changed mind, change the input action/rationale and explicitly
create another decision. Do not edit the database or reuse a stored snapshot
as authoring input. Missing versions or IDs must fail rather than fall back.

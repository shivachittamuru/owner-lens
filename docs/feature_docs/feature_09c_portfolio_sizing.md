---
title: "Feature 9C: Portfolio Context and Position Sizing"
description: "Immutable manual portfolio snapshots and explicit, cash-funded downside-budget constraints over exact completed underwritings."
---

## Purpose and boundaries

Answer how much exposure fits explicitly supplied risk budgets, not which trade
to execute. This is a bounded framework, not optimization, a score, Kelly sizing,
correlation estimation, factor analysis, rebalancing, tax planning or attribution.
There is no brokerage integration, price retrieval, automated decision, trade,
monitoring or agent. A modeled Bear case is not a worst-case risk guarantee.

The shared domain is
[`position_sizing.py`](../../src/owner_lens/position_sizing.py).
CLI and Workbench use the same rules. No default portfolio or policy is created.
The framework uses exact Feature 8 versions through the Feature 9A loader,
including frozen Feature 7 context without screening recomputation.
Optional exact Feature 9B decision context retains its alternatives, comparison
and shadow entries. These are context only: `ACTUAL_CHOICE`, including WATCH,
PASS and EXIT, never establishes an executed position. Only manually supplied
holdings establish current weights.

## Portfolio snapshot schema

Use the [synthetic portfolio example](../examples/portfolio_context.sample.json)
as a structural example, not suggested holdings.

| Input | Meaning |
|-------|---------|
| `as_of_date` | Required YYYY-MM-DD; not after snapshot creation date |
| `basis` | Exactly `MARKET_VALUE` or `WEIGHT`, never mixed |
| `currency` | Required three-letter code for market values; absent/null for weights |
| `holdings` | Explicit list, including empty for a cash-only portfolio |
| Holding `ticker` | Required uppercase symbol |
| Holding `security_id` | Optional persisted identity, verified if supplied |
| Holding `asset_type` | `EQUITY`, `ETF`, `BOND` or `OTHER`; target company must be EQUITY |
| Holding `market_value` or `weight` | Finite nonnegative amount; weights are decimal ratios in [0,1] |
| Holding `sector`, `industry` | Optional manual labels; exact, case-sensitive equality |
| Holding `exposure_tags` | Optional uppercase tags, null/omitted for unknown, [] explicitly none |
| `cash` | Optional amount in the same basis; zero is distinct from missing |
| Root/holding `notes` | Optional nonempty text |

All market values must already use the declared currency. No FX conversion or
aggregation of different currencies occurs. Short positions, leverage, options
and duplicate tickers/security identities are rejected; consolidate lots first.
Known identities are resolved once when creating the snapshot. An unresolved
manual ticker stays explicitly identity-unknown and uses exact frozen ticker
matching, not a later alias lookup.

For supplied holding amounts `a[i]` and supplied cash `c`:

```text
denominator = sum(a[i]) + c, if cash supplied
denominator = sum(a[i]),    if cash missing
weight[i] = a[i] / denominator
cash_weight = c / denominator, or null if not supplied
```

The denominator must be positive and finite. Weight input need not sum to one:
normalization is intentional and the raw amounts, denominator and basis are
preserved and displayed. Missing cash means reported-holdings-only weights,
not verified fractions of total wealth. It blocks additional deployment.
Missing holdings lists are rejected; omission of individual holdings cannot be
detected and remains the investor's responsibility.

Saved snapshots add `snapshot_id` (UUID), UTC `created_at`, normalized weights,
`cash_input`, `cash_weight`, `normalization_total`, manual context category
`JUDGMENT`, and model version `manual-portfolio-v1`. Hash and immutable JSON
are stored together. Market values are manually asserted context, not fetched
quotes. They do not replace the independently frozen underwriting price/date.

## Explicit sizing policy schema

Every field below is required; all are investor `JUDGMENT`, not model defaults.
The [synthetic policy example](../examples/sizing_policy.sample.json) is not
an endorsed risk policy.

| Field | Constraint or meaning |
|-------|-----------------------|
| `category` | Exactly `JUDGMENT` |
| `max_single_position_weight` | Maximum total company weight |
| `max_initial_position_weight` | Additional ceiling only when current weight is zero |
| `max_portfolio_bear_loss_contribution` | Budget for the selected company's modeled Bear loss |
| `max_sector_weight` | Maximum weight for each manually labeled sector |
| `min_cash_reserve` | Cash weight unavailable for new deployment |
| `starter_position_weight` | Conservative ceiling when any quality concern exists |
| `max_thesis_weight` | Maximum weight for each manual thesis tag |
| `severe_bear_loss_threshold` | Positive loss threshold activating the starter cap |

All numeric fields must be finite ratios in [0,1]. Require
`starter_position_weight <= max_initial_position_weight <= max_single_position_weight`.
No qualitative confidence is converted to a probability, numeric score or
calibrated maximum. Zero budgets are valid except for the severe-loss threshold.

## Deterministic equations

All weights refer to the unchanged snapshot denominator. Deployment is cash-only,
with no assumed sale of another holding and no new external contribution.

```text
bear_terminal_return = Bear value/share / frozen underwriting price - 1
modeled_bear_loss = max(0, -bear_terminal_return)
current_bear_loss_contribution = current_weight * modeled_bear_loss
downside_ceiling = min(1, bear_loss_budget / modeled_bear_loss)
cash_ceiling = min(1, current_weight + max(0, cash_weight - min_cash_reserve))
sector_ceiling = max(0, max_sector_weight - other_holdings_in_target_sector)
tag_ceiling[tag] = max(0, max_thesis_weight - other_holdings_with_tag)
thesis_ceiling = min(tag_ceiling[tag]) over the target's explicit tags
```

Bear loss is terminal loss, not annualized Bear CAGR and not probability-weighted
loss. If Bear terminal return is nonnegative, the downside ceiling is explicitly
not applicable; other ceilings remain active and a risk-guarantee warning appears.
For explicitly no tags, thesis ceiling is 100%, still constrained by other limits.
Multi-tag holdings count independently toward each tag; tag weights are not added
as if they were disjoint sectors or estimated factors.

```text
maximum = min(
  single_position_ceiling,
  initial_ceiling if unheld,
  downside_ceiling if applicable,
  starter_ceiling if any quality concern,
  sector_ceiling,
  thesis_ceiling,
  cash_ceiling,
  economics_gate if applicable
)
target_range = [0, maximum]
incremental_room = [0, max(0, maximum - current_weight)]
```

The zero lower bound intentionally does not invent an obligation to invest.
The economics gate sets the ceiling to zero unless Feature 8 classifies the
opportunity `INTERESTING` or `ATTRACTIVE` with a positive hurdle spread.
This is a condition for additional exposure, not a sell or trim instruction.
`NO_POSITION` means zero ceiling; `STARTER` means a positive ceiling at or below
the explicit starter limit; `NORMAL` means a larger ceiling. No
`HIGH_CONVICTION` label is inferred from expected return.

All constraints tied for the minimum within `1e-12` are listed as binding.
`ABOVE_POLICY_RANGE` appears if current weight exceeds the ceiling; incremental
room stays zero without negative capital or automatic trimming.
Optional proposed increment is evaluated separately and never changes the range.
Its target weight and Bear contribution are shown in JSON.
With a complete market-value denominator, incremental monetary room is reported
in the explicitly declared currency; weight-only or cash-unknown snapshots have
no inferred dollar portfolio size.

## Quality caps and missingness

Any of the following activates the same explicit starter ceiling:

- Missing supporting or disconfirming evidence.
- Documented variant view is false or unknown.
- Any unresolved challenger question, fragile assumption or missing-evidence item.
- Feature 9A's most sensitive local driver has band `HIGH`.
- Feature 7/8 context is missing or not evaluable.
- Modeled Bear loss meets or exceeds the investor's severe-loss threshold.

Feature 9A's bounded challenger has no verified high-impact/resolved taxonomy.
The framework conservatively treats any unresolved question as unresolved,
instead of guessing its severity or inventing a resolution. This means many
completed underwritings still receive starter caps. Confidence remains qualitative.

Missing target sector or unknown sector on any positive-weight holding blocks
additional sector deployment: the sector ceiling becomes current weight.
Unknown target tags or unknown tags on any positive-weight holding similarly
block additional thesis deployment. Missing industry is shown explicitly but
does not imply a neutral or estimated industry; there is no industry-limit policy.
Missing cash similarly sets cash ceiling to current weight. These coverage
constraints can still coexist with stricter policy ceilings below current weight.

## Concentration warnings

Warnings use strict limit breaches beyond the same numeric tolerance:

- `SINGLE_NAME_CONCENTRATION_WARNING`: any reported holding exceeds the single-name
  limit, or the target's proposed weight would exceed it.
- `SECTOR_CONCENTRATION_WARNING`: any known sector exceeds its limit, or the
  proposed increment would push the target's known sector over it.
- `THESIS_CONCENTRATION_WARNING`: any known manual tag exceeds its limit, or the
  proposed increment would push a target tag over it.
- `PROPOSED_INCREMENT_EXCEEDS_ROOM`: proposal exceeds permitted incremental room.
- `CASH_BELOW_RESERVE`, `INCOMPLETE_PORTFOLIO_CONTEXT` and
  `ABOVE_POLICY_RANGE` distinguish funding, coverage and current-position issues.

Known concentration totals remain visible even with incomplete coverage; they
are partial observations, never assertions that unidentified exposures are zero.
No correlations or shared economic sensitivities are estimated.

## Immutable analysis schema

The `downside-budget-sizing-v1` report freezes:

- Original underwriting record, UUID/version/hash and snapshot bytes.
- Feature 9A projection with probabilities, scenarios, expected return, hurdle,
  classification, variant, sensitivity, evidence, challenger and Feature 7 context.
- Exact portfolio UUID, full snapshot and content hash.
- Complete explicit policy and target manual exposure context.
- Optional exact decision JSON, alternatives, comparison and shadow context.
- Current/cash weights, Bear loss/contribution, known exposures and largest positions.
- Each ceiling, quality-cap reasons, interval, increment, bindings and warnings.
- Model version, calculation category and conditional-guidance disclaimer.

Preview has no generated UUID/time and yields stable canonical JSON for the same
selected sources. Explicit save adds analysis UUID and actual UTC creation time.
The storage boundary recomputes and compares the report to exact sources before
insertion, preventing fabricated or edited results. SQLite update/delete/replace
triggers prohibit editing portfolios or analyses. A changed portfolio, policy or
view creates another record. Saved reads verify hashes/identities and return the
stored JSON without recalculating it under newer rules. Schema 8 is additive and
preserves prior underwritings, valuations, decisions and shadow entries.

No latest-version substitution, current quote fetching, mutable challenger lookup,
or later evidence import is used. Source creation times must precede analysis
time, and Feature 9A validates the underwriting's frozen evidence cutoff.

## Synthetic ADBE example

The offline fixture has frozen price 20, expected CAGR approximately 39.80% and
Bear terminal loss 50%. These are synthetic inputs, not an Adobe valuation.
With the included synthetic 100,000 USD snapshot and policy:

| Output | Value |
|--------|-------|
| Current ADBE weight | 2% |
| Cash | 40% |
| Bear contribution at current weight | 1% |
| Single-name ceiling | 10% |
| Initial-position ceiling | Not applicable |
| Bear-budget ceiling | 3% / 50% = 6% |
| Evidence-quality ceiling | 6%, unresolved questions remain |
| Sector ceiling | 40% - 18% other Technology = 22% |
| Thesis ceiling | 30% - 18% other AI_CAPEX = 12% |
| Cash ceiling | 2% + 40% - 10% = 32% |
| Target range | 0-6% |
| Incremental room | +0-4%, USD 0-4,000 |
| Binding constraints | Bear loss budget and evidence quality |

The return estimate is not maximized. Starter-sized conditional economics remain
limited by downside and unfinished research. No trade or decision is created.

## Workbench

Open **Portfolio Context / Position Sizing**. Create a snapshot from reviewed
JSON or select an exact saved snapshot. Its current holdings, cash, normalization
and manual context are visible. Select an exact underwriting version and optional
decision ID. Enter the complete explicit policy JSON, optional exposure context
for an unheld company, and optional incremental proposal.

**Review position-size range** previews the table, binding constraints and full
JSON. Only checking **Save this sizing analysis immutably** before submitting
appends an analysis. Reruns and preview do not save again. The saved-analysis
section is read-only and supports exact JSON download. There are no editable
underwriting fields, inferred executions, automatic decisions or trades.
Incomplete selected underwritings are rejected explicitly.

## Manual PowerShell validation

These are user-run commands. No live validation or real portfolio modification
was performed by the implementation workflow. Run against your own chosen local
store, and review all sample inputs first.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

# Copy and EDIT the synthetic examples before saving any personal context.
New-Item -ItemType Directory -Force .\data\portfolio | Out-Null
Copy-Item .\docs\examples\portfolio_context.sample.json .\data\portfolio\portfolio.json
Copy-Item .\docs\examples\sizing_policy.sample.json .\data\portfolio\policy.json
notepad .\data\portfolio\portfolio.json
notepad .\data\portfolio\policy.json

$portfolio = uv run owner-lens portfolio snapshot create --file .\data\portfolio\portfolio.json --json | ConvertFrom-Json
uv run owner-lens portfolio snapshot show $portfolio.snapshot_id --json
uv run owner-lens portfolio snapshot list --json

# Replace version 7 with an exact completed version already in your store.
uv run owner-lens position-size ADBE --version 7 --portfolio $portfolio.snapshot_id --policy .\data\portfolio\policy.json
$a = uv run owner-lens position-size ADBE --version 7 --portfolio $portfolio.snapshot_id --policy .\data\portfolio\policy.json --json
$b = uv run owner-lens position-size ADBE --version 7 --portfolio $portfolio.snapshot_id --policy .\data\portfolio\policy.json --json
if ($a -cne $b) { throw "Non-reproducible sizing output" }

# Explicit save, no trade or decision creation.
$saved = uv run owner-lens position-size ADBE --version 7 --portfolio $portfolio.snapshot_id --policy .\data\portfolio\policy.json --increment 0.01 --save --json | ConvertFrom-Json
uv run owner-lens sizing show $saved.analysis_id --json
uv run owner-lens sizing history --json
uv run owner-lens workbench
```

For an unheld company, `--context` accepts JSON containing exactly `sector`,
`industry` and `exposure_tags`, each explicitly nullable. A context supplied for
an existing holding must agree with that snapshot. To preserve an exact decision
and its comparison, add `--decision-id <UUID>`; it must reference the same exact
underwriting. Neither option looks up latest alternatives or implies positions.

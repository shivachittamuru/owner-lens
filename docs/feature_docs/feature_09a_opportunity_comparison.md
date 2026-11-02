---
title: "Feature 9A: Opportunity Comparison"
description: "Offline, unscored comparison of exact immutable underwriting versions, with research attention and conditional capital economics."
---

## Scope and offline workflow

Compare 2-5 completed immutable Feature 8 versions, including different versions
of one company. Each must have a saved, validated Bear/Base/Bull valuation,
approved probabilities, a saved required-return hurdle and a valid Feature 8
expected-return classification. An evaluation-only hurdle override does not
complete a saved underwriting. Unordered scenarios are ineligible.

```powershell
uv run owner-lens underwriting history ADBE
uv run owner-lens underwriting history MSFT
uv run owner-lens underwriting history GOOGL
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 GOOGL:2
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 GOOGL:2 --json
```

Use version numbers that actually exist in your store. Missing or incomplete
versions fail explicitly; the command never substitutes latest or creates a
valuation. No API key, network access or evidence refresh is required.

This is not a recommendation. There is no aggregate numeric score, optimizer,
portfolio, position size, buy/sell decision, instrument selection, monitoring,
LLM ranking or agentic research.

## Domain model and identity

The shared domain engine is
[`opportunity_comparison.py`](../../src/owner_lens/opportunity_comparison.py).

* `UnderwritingSelection` requires an explicit ticker and positive version.
* `Opportunity` retains the full Feature 8 `UnderwritingSummary`: immutable ID,
  version, content hash, frozen price/date, scenarios, probabilities, expected
  terminal value/CAGR, saved hurdle/spread/classification and variant report.
* `UnderwritingQuality` contains supporting/disconfirming evidence text,
  variant documentation state, maximum local sensitivity, bounded challenger
  status/questions, biggest uncertainty and explicit missing dimensions.
* `BusinessContext` contains frozen Feature 7 priority, setup, coverage and all
  six dimension bands, without its numeric screening score.
* `PairwiseComparison` records both sides' advantages/flags, unknown dimensions,
  dominance/conclusion, key tradeoff, research attention and capital economics.
* `OpportunityComparison` contains opportunities, every unordered pair,
  `model_version=opportunity-comparison-v1` and a disclaimer.

Each opportunity also exposes `flags`, `research_attention`,
`capital_attractiveness`, `key_tradeoff` and `unresolved_issue`. Pairwise flags
identify the counterpart; aggregated per-opportunity flags alone are not a rank.
An opportunity can dominate one peer and have a tradeoff with another.

The engine validates the saved valuation against the selected underwriting,
then reuses Feature 8 summary, variant and local-sensitivity calculations.
It does not normalize probabilities or invent missing inputs. Ratios in JSON
are decimals, not percentages; display rounding never affects comparisons.

## Deterministic flags

Numeric differences must exceed `1e-12` in unrounded decimal units. There are no
hidden materiality weights. Exact/tolerance ties do not earn superiority flags.

| Flag                         | Definition                                                        |
|------------------------------|-------------------------------------------------------------------|
| `HIGHER_EXPECTED_RETURN`     | Higher Feature 8 expected five-year CAGR                           |
| `BETTER_DOWNSIDE_PROTECTION` | Higher Bear CAGR, not a claim about all possible losses            |
| `STRONGER_VARIANT_VIEW`      | Material driver disagreement with recorded rationale vs without it |
| `MORE_FRAGILE`               | Larger maximum absolute local CAGR perturbation                   |
| `WEAKER_EVIDENCE`            | Missing a supporting or disconfirming evidence category a peer has |
| `HIGHER_BUSINESS_QUALITY`    | Higher evaluable frozen Feature 7 Business Quality band            |
| `DOMINATED`                 | Conservative core dominance, subject to the gates below            |
| `TRADEOFF`                  | Both sides have at least one known advantage                      |

Variant documentation reuses Feature 8 driver materiality and rationales.
A larger numerical disagreement is not a stronger thesis or proof of an edge.
When no material disagreement exists and some consensus is missing, variant
documentation is unknown, not false. Unknown vs documented earns no superiority
flag. The original Feature 8 variant conclusion remains separately visible.

Sensitivity reuses Feature 8's one-at-a-time BASE perturbations: +1 percentage
point for ratios, +1x terminal multiple. Maximum absolute CAGR delta identifies
the driver; ties follow Feature 8's fixed driver order. `MORE_FRAGILE` is relative
local model sensitivity, not a total-risk judgment. The existing HIGH band
(at least 2 percentage points absolute CAGR effect) prompts additional research.

Evidence completeness means presence of investor-authored evidence categories,
not independent verification or assessment of evidentiary persuasiveness.
Missing disconfirming evidence is not evidence that the thesis is safe.

## Conservative dominance

The core consists of:

1. Expected five-year CAGR
2. Bear CAGR
3. Supporting evidence presence
4. Disconfirming evidence presence
5. Frozen Feature 7 Business Quality band

Both opportunities must have supporting and disconfirming evidence and an
evaluable Business Quality band. Missing evidence or quality blocks dominance.
The candidate must be at least as good on every core dimension and strictly
better on at least one core dimension.

Known conflicts in hurdle spread, probability of terminal loss, maximum local
sensitivity, variant documentation or any other evaluable frozen Feature 7
dimension veto dominance. Feature 7 bands retain their existing ordinal order;
`NOT_EVALUABLE` has no ordinal value. Priority, setup and coverage remain context,
not numerical ranking inputs. Unknown optional guards are explicitly reported,
not assumed favorable or unfavorable, and do not establish an advantage.
Dominance is a statement about this documented core, not every business risk.

Any known advantage on each side produces `TRADEOFF`, including higher return
against worse downside, evidence or quality. `INCOMPLETE` means missing core
information prevented a conclusion without a known two-sided tradeoff.
`NO_CORE_DOMINANCE` covers complete ties or guard-only advantages.

## Research attention and capital attractiveness

Research attention gives reasons to do work, not a numerical queue:

* Missing supporting or disconfirming evidence
* Positive hurdle spread dependent on incomplete evidence
* Documented variant rationales requiring validation, or unavailable consensus
* HIGH local sensitivity and its named driver
* Missing frozen dimensions and unresolved advisory questions

Capital attractiveness identifies higher conditional expected return and any
conservative core dominance, while exposing downside, hurdle, quality and
evidence conflicts. A return leader is not automatically a capital winner.
With tradeoffs or unknowns, no overall capital preference is established.

The comparison reuses the bounded Feature 8 `offline-rules-v1` challenger on
the selected snapshot. Its status is `OFFLINE_RULE_REVIEW_REQUIRED`; questions
remain advisory. It never selects a latest persisted challenger run, incorporates
later research, writes a review, or interprets questions as resolved.

## Frozen context and reproducibility

New Feature 8 captures freeze Feature 7 outputs using the existing screening
engine on the same captured annual history. No Feature 7 formulas are duplicated.
Comparison never calls the screening engine or queries current annual evidence.
Existing immutable versions without this context remain explicitly missing.
Creating a new underwriting version can capture context; old records are never
backfilled or silently enriched.

The cutoff is the earliest of creation time, as-of end-of-day and the frozen
evidence cutoff. Captured observation/retrieval dates, evidence dates, actual
financial period ends and market dates must not exceed it, for legacy and
current schemas alike. Future analyst target dates and future thesis-monitoring
dates are intentional and are not mistaken for future observations.

JSON has sorted keys, canonical ticker/version ordering, fixed pair ordering,
unrounded finite numbers and no generated timestamp. Reversing selection order
does not change output. Underwriting hashes and the saved valuation hash remain
visible. Adding another version, current evidence or a saved challenger run
cannot change a selected version's comparison. No comparison writes occur.
The output model version identifies the rules needed to reproduce an export.

## Illustrative three-company comparison

These are synthetic test fixtures, not real company assessments or live data.
They use identical scenario beliefs and 12% hurdles with different frozen prices.

| Fixture | Frozen price | Expected CAGR | Hurdle spread | Bear CAGR | Terminal loss probability |
|---------|--------------|---------------|---------------|-----------|---------------------------|
| ADBE:1  | $20          | 39.80%        | +27.80%       | -12.94%   | 25%                       |
| MSFT:1  | $25          | 33.70%        | +21.70%       | -16.74%   | 25%                       |
| GOOGL:1 | $30          | 28.91%        | +16.91%       | -19.73%   | 25%                       |

ADBE has higher expected return and better Bear CAGR, but a larger absolute
local CAGR perturbation under the same sensitivity tests. Each pair is a
`TRADEOFF`, not dominance. Capital economics favor ADBE's conditional return
profile, without an overall capital preference. Research attention remains on
validating recorded variant rationales, missing comparable consensus and the
bounded challenger questions. These labels make no actual company claims.

## Workbench UX

Open **Opportunity Comparison**, independently of the current provider's company
list or screening. The picker lists only validated completed versions with
explicit `TICKER:VERSION` labels. There is no default/latest selection.
Incomplete or invalid versions appear in an exclusion expander with reasons.

The read-only table follows expected return, Bear/asymmetry, evidence,
variant, sensitivity, business/setup and unresolved challenger context.
Pairwise conclusions separate capital economics from research attention.
Expand each opportunity for questions, missing dimensions, uncertainty and
immutable identity. Download the same deterministic JSON used by the CLI.
No underwriting fields can be edited here.

## Manual PowerShell validation

The commands below are for you to run against existing local records.
Implementation validation used offline fixtures, not your live store.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

uv run owner-lens underwriting history ADBE
uv run owner-lens underwriting history MSFT
uv run owner-lens compare-underwriting ADBE:7 MSFT:3
uv run owner-lens compare-underwriting ADBE:7 MSFT:3 GOOGL:2 --json

$first = uv run owner-lens compare-underwriting ADBE:7 MSFT:3 --json
if ($LASTEXITCODE -ne 0) { throw "First comparison failed" }
$second = uv run owner-lens compare-underwriting MSFT:3 ADBE:7 --json
if ($LASTEXITCODE -ne 0) { throw "Second comparison failed" }
if ($first -cne $second) { throw "Comparison output changed" }

uv run owner-lens workbench --provider fmp
```

Replace example version numbers only after checking history. In the Workbench,
select the same versions and inspect the table, pairwise flags, research
expanders and downloaded JSON. Confirm an unavailable version errors instead
of switching to latest.

---
title: "Feature 8E: Probabilities, Expected Return and Underwriting Challenger"
description: "Weight immutable scenario terminal values, compare an explicit investor hurdle and persist bounded offline advisory challenges."
---

## Immutable manual policy

Feature 8E adds optional `probability_distribution` and `investor_policy` to
[8B underwriting](feature_08b_immutable_underwriting.md). They remain
`JUDGMENT`, not company facts or model-generated forecasts.

```json
{
  "probability_distribution": {
    "category": "JUDGMENT",
    "rationale": "Illustrative only; replace with your approved distribution.",
    "scenarios": [
      {"name": "BEAR", "probability": 0.25, "category": "JUDGMENT"},
      {"name": "BASE", "probability": 0.50, "category": "JUDGMENT"},
      {"name": "BULL", "probability": 0.25, "category": "JUDGMENT"}
    ]
  },
  "investor_policy": {
    "required_return": 0.12,
    "category": "JUDGMENT",
    "rationale": "Illustrative investor policy, not company evidence."
  }
}
```

Add these fields to a complete scenario input, such as the
[ADBE structural sample](../examples/adbe_probability_underwriting.sample.json).
Exactly BEAR, BASE and BULL probabilities and assumptions are required when a
distribution is supplied. Probabilities must be finite, within `[0, 1]` and
sum to one within absolute tolerance `1e-9`. Zero probabilities are allowed
but challenged. Values are never generated, normalized or rounded in storage.
Changing probabilities, distribution rationale or saved policy creates a new
underwriting version. Old versions without them keep their original bytes.

Distribution and policy rationales are optional; absence is explicit. Required
return must be finite and greater than `-1`, expressed as a decimal ratio.
It is an investor policy, not evidence of company performance.

`--required-return` explicitly evaluates an alternative hurdle without changing
the underwriting. The summary records both the policy value and its origin
(`explicit_evaluation` versus `saved_underwriting`). No default hurdle exists.

## Expected return and risk context

Summary calculations require a saved
[8C valuation](feature_08c_scenario_valuation.md) for the exact underwriting
version. The saved content hash, identity, starting facts, assumptions and
arithmetic are validated. Current prices or newer evidence are never substituted.
No challenger is needed to compute the summary.

For probability `p_i`, scenario terminal value/share `V_i` and saved price `P0`:

```text
Expected_terminal_value = sum(p_i * V_i)
Expected_5Y_CAGR = (Expected_terminal_value / P0)^(1/5) - 1
Return_spread = Expected_5Y_CAGR - Required_return
Scenario_terminal_return_i = V_i / P0 - 1
Weighted_downside = sum(p_i * max(-Scenario_terminal_return_i, 0))
Weighted_upside = sum(p_i * max(Scenario_terminal_return_i, 0))
```

Expected CAGR is not the probability-weighted average of scenario CAGRs. No
interim distribution, present-value method or additional valuation approach
is introduced. Zero expected terminal value yields `-1` CAGR.

Loss/gain probabilities sum weights for terminal values below/above saved
price; equal-price outcomes count in neither. Weighted downside/upside are
unconditional terminal-return contributions, not confidence intervals or
conditional averages. Bear/Base/Bull values and CAGRs, probabilities, saved
price/date, exact underwriting and valuation hashes remain visible.

All outcomes and classification are `CALCULATION`; probabilities and hurdle
remain nested, explicitly typed `JUDGMENT`. The summary includes the
[8D variant view](feature_08d_variant_perception.md) and all local BASE
sensitivities ordered by absolute implied-CAGR effect.

### Transparent classification

Rules in `weighted-terminal-return-v1` use unrounded spread and a
`1e-12` floating-point boundary tolerance:

| Classification | Rule |
| --- | --- |
| INSUFFICIENT | Terminal scenario values are not ordered BEAR <= BASE <= BULL |
| UNATTRACTIVE | Spread below -1 percentage point |
| WATCH | Spread within +/-1 percentage point, including endpoints |
| INTERESTING | Spread above +1 but below +3 percentage points |
| ATTRACTIVE | Spread at least +3 percentage points |

Missing probabilities, hurdle, price or saved valuation fail explicitly rather
than yielding a success-shaped default. An unordered scenario set keeps the
arithmetic visible but is `INSUFFICIENT` until labels/assumptions are reviewed.
Classification is conditional on the manual beliefs, not a buy/sell decision,
portfolio recommendation or guaranteed alpha. A variant view is shown, not
silently required by the spread rules. Threshold bands reduce false precision;
they do not measure model uncertainty.

## Challenger architecture

This first implementation uses `RuleBasedChallenger`, an offline, deterministic
backend behind the small `ChallengerBackend` protocol. It is not an LLM.
There is no model SDK, external disclosure, retrieval or agent orchestration.
The interface receives only an immutable JSON context, never a store handle,
market client or tools. Future model integration requires a separate approved
provider implementation; investment arithmetic remains independent.

Context contains the exact underwriting identity and frozen snapshot, saved
8C valuation and deterministic 8D report. Its hash covers every input.
The backend returns structured `ChallengerOutput`, entirely `JUDGMENT`:

* `overall_assessment`
* `strongest_argument_against`
* `fragile_assumptions`
* `probability_challenges`
* `contradictory_evidence`
* `missing_evidence`
* `alternative_explanations`
* `thesis_breaker_quality`
* `variant_view_challenge`
* `questions_to_resolve`

Each challenge carries a JSON-pointer citation into the frozen context,
the cited source category, exact cited JSON and `evidence_available`.
Cited facts remain facts; the challenge around them is judgment.
Contradictory items quote recorded disconfirming evidence without certifying
its truth. Rules cannot determine whether a narrative is persuasive or a
business explanation is correct, so they state that limitation and pose
questions instead of inventing facts.

Rules flag historical-range departures across scenarios, stacked
valuation-favorable departures, the largest local BASE sensitivity, missing
consensus/support, interpretation or unreferenced supporting items, absent
probability rationale, zero scenario weight and BEAR weight below an explicit
10% human-review threshold. That threshold is not an estimated downside
probability or an instruction to change it.

Thesis-breaker quality is `NOT_ASSESSED_AUTOMATICALLY`: request observable
metrics, thresholds, sources and dates. No company-specific alternative
causal explanation is fabricated. Where none is established, the challenger
asks for one and for distinguishing evidence, marked unavailable.

The review is bounded to four drivers, three scenarios and the first 20 items
in each supporting/disconfirming list. If more exist, the output explicitly
asks for manual review of the remainder. The full captured context remains
available for audit. The challenger does not fetch references or interpret
embedded instructions as commands.

### Separate immutable runs

Schema version 6 additively introduces `challenger_runs`. Each run stores:

* Run UUID, underwriting UUID/version/hash.
* Challenger version `underwriting-falsification-v1`.
* Model/rules version `offline-rules-v1`.
* Actual UTC creation time.
* Input content hash and complete frozen context JSON.
* Structured output JSON and its content hash.

Updates, deletes and replacements are blocked by SQLite triggers. Runs are
separate from underwriting and cannot alter assumptions, probabilities or
saved valuations. Repeated runs append independent UUIDs; identical context
under the same rules yields identical output. `show` reads saved commentary
without rerunning the backend. It defaults to the latest run for that exact
underwriting version; `--run-id` selects an exact prior run.

## Manual PowerShell validation

Do not treat illustrative assumptions or placeholders as your beliefs. Edit
every relevant field, add support/disconfirmation, and optionally add your
own per-driver variant rationales before creating a real record.

```powershell
New-Item -ItemType Directory -Force .\data\underwriting | Out-Null
Copy-Item .\docs\examples\adbe_probability_underwriting.sample.json .\data\underwriting\ADBE-loop.json
notepad .\data\underwriting\ADBE-loop.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE-loop.json
uv run owner-lens underwriting history ADBE
$Version = 1 # Replace with the new version printed by create/history.
uv run owner-lens valuation run ADBE --version $Version
uv run owner-lens underwriting summary ADBE --version $Version --required-return 0.12
uv run owner-lens underwriting summary ADBE --version $Version --required-return 0.12 --json
uv run owner-lens challenger run ADBE --version $Version
uv run owner-lens challenger show ADBE --version $Version
```

To use the explicitly saved investor policy, omit `--required-return`.
These commands use your persisted evidence only; no live FMP or model call is
performed. The challenger is runnable without saved probabilities but reports
them unavailable; summary math requires approved probabilities and a hurdle.

Check the terminal-value weighted sum manually. Compare it with the nonlinear
CAGR transform, not an average of CAGRs. Verify the saved price/date, scenario
labels, spread band, probability rationale, cited categories and missing
evidence. A challenge is a question to investigate, not a verified finding.

For exact run inspection and v1 reproducibility:

```powershell
uv run owner-lens underwriting summary ADBE --version $Version --required-return 0.12 --json |
    Set-Content -Encoding utf8 .\data\underwriting\ADBE-summary-before.json
$RunId = "REPLACE-with-run_id-printed-by-challenger-run"
uv run owner-lens challenger show ADBE --version $Version --run-id $RunId

# Edit the distribution; create a new version, never modify the old record.
notepad .\data\underwriting\ADBE-loop.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE-loop.json
uv run owner-lens underwriting history ADBE

uv run owner-lens underwriting summary ADBE --version $Version --required-return 0.12 --json |
    Set-Content -Encoding utf8 .\data\underwriting\ADBE-summary-after.json
Compare-Object (Get-Content .\data\underwriting\ADBE-summary-before.json) (Get-Content .\data\underwriting\ADBE-summary-after.json)
```

No comparison output means the old summary is unchanged. Run valuation,
summary and challenger for the newly printed version separately.

## Boundaries

No sizing, instruments/options selection, portfolio fit, autonomous decisions,
retrieval agents, current/future evidence substitution, model self-improvement,
multi-agent workflow, event-driven re-underwriting or Streamlit editing is added.
Fixture tests require neither FMP credentials nor a model service.

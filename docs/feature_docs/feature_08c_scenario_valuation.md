---
title: "Feature 8C: Deterministic Scenario Valuation"
description: "Calculate reproducible five-year Bear, Base, and Bull terminal equity FCF valuations from immutable underwriting."
ms.topic: how-to
---

## One explicit model

Feature 8C applies a single terminal equity-FCF-multiple method to an immutable
[8B underwriting version](feature_08b_immutable_underwriting.md). It never
loads newer financial facts, a live price, or analyst expectations to replace
that version's starting facts. The engine does not invent scenario inputs.

For each scenario, let `R0` be starting annual revenue, `S0` diluted shares,
`P0` the underwriting's persisted EOD close, `g` revenue CAGR, `m` year-five FCF
margin, `s` diluted-share CAGR, and `M` the terminal equity FCF multiple:

```text
R5 = R0 * (1 + g)^5
FCF5 = R5 * m
S5 = S0 * (1 + s)^5
FCF_per_share5 = FCF5 / S5
Equity_value5 = FCF5 * M
Value_per_share5 = Equity_value5 / S5
Implied_CAGR5 = (Value_per_share5 / P0)^(1/5) - 1
```

The terminal multiple directly produces equity value, not enterprise value.
There is no separate addition of current net cash or subtraction of debt.
There are no interim dividends, distributions, discounting, or present-value
calculation. Share-count assumptions capture the assumed future net evolution
of diluted shares without modeling buyback funding or a cash/debt bridge.
Do not interpret this simple model as a complete capital-allocation forecast.

The five compounding steps start from the captured latest fiscal-year state.
The implied CAGR uses the captured price as a five-year comparison denominator;
it is not calendar-day annualization from the price's market date to a fiscal
period end. Price age and starting fiscal year remain visible.

## Scenario contract and semantics

The manual input optionally adds a `scenarios` list to 8B. When present, it
must contain exactly one `BEAR`, `BASE`, and `BULL`:

* `category`: `ASSUMPTION`.
* `narrative`: required manual rationale.
* `revenue_cagr`, `fcf_margin_year5`, `share_count_cagr`, and
  `terminal_fcf_multiple`: required finite numbers.
* `horizon_years`: the integer `5`, required for every scenario.
* `key_dependency`: optional manual text.

Growth and margins are decimal ratios; `0.05` is 5% and `-0.02` is a 2%
decline. The terminal multiple is a positive dimensionless multiple, not a
percentage. Share and revenue CAGR must exceed `-1`; FCF margin must be within
`[0, 1]`. Zero FCF yields zero terminal equity value and `-1` implied CAGR.
Negative FCF terminal-multiple valuation is not supported by this method.

The engine rejects duplicate/unknown scenario names, missing inputs, inconsistent
horizons, non-finite numbers, non-positive starting shares/revenue/price, invalid
source categories, mismatched starting fiscal years, incompatible known price
currency, and malformed price provenance. Numerical overflow or non-positive
projected shares/revenue fails explicitly. Calculations are not rounded before
compounding or division. Unknown price currency stays `null`, not inferred USD;
the model assumes the quote unit is compatible with the USD financial inputs
and does not perform FX conversion.

Starting revenue, diluted shares, and market price remain `FACT`. Scenario
inputs remain `ASSUMPTION`. Every output is `CALCULATION`. Narrative and optional
dependency text are retained with the scenario. Generic 8B forward assumptions
are not silently inherited into scenarios. You can supply an empty
`forward_assumptions` list when complete scenarios provide the explicit inputs.

Older underwriting records without scenarios remain unchanged and readable.
Valuing them fails clearly. Add scenarios by creating a new underwriting
version, never editing an old one.

## Persistence and CLI

SQLite schema version 5 additively introduces `valuation_results`, keyed by
`(underwriting_id, model_version)`. JSON outputs include the exact underwriting
version/hash, price provenance, starting facts, assumptions, and intermediates.
Content-hash verification and immutable triggers protect saved results.
Model version `equity-fcf-multiple-5y-v1` identifies the arithmetic.

```powershell
uv run owner-lens valuation run ADBE --version 1
uv run owner-lens valuation show ADBE --version 1
```

`run` computes and persists once; repeating it returns the identical saved
JSON. `show` reads only persisted outputs and fails if that version has not
been run. An exact underwriting version is required for both commands.
New model arithmetic must use a new model version instead of overwriting
results. A new underwriting version gets independent outputs.

## Manual ADBE validation

The [complete sample input](../examples/adbe_scenario_underwriting.sample.json)
contains illustrative scenario numbers, not recommended ADBE assumptions.
Replace its numbers, rationales, and all `REPLACE` strings with your own beliefs
before creating a real underwriting record.

```powershell
New-Item -ItemType Directory -Force .\data\underwriting | Out-Null
Copy-Item .\docs\examples\adbe_scenario_underwriting.sample.json .\data\underwriting\ADBE-scenarios.json
notepad .\data\underwriting\ADBE-scenarios.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE-scenarios.json
uv run owner-lens underwriting history ADBE
```

Use the version just created, not an older version without scenarios:

```powershell
$Version = 1 # Replace with the version printed by create/history.
uv run owner-lens valuation run ADBE --version $Version
uv run owner-lens valuation show ADBE --version $Version |
    Set-Content -Encoding utf8 .\data\underwriting\valuation-before.json
uv run owner-lens valuation run ADBE --version $Version |
    Set-Content -Encoding utf8 .\data\underwriting\valuation-repeat.json
(Get-FileHash .\data\underwriting\valuation-before.json).Hash -eq (Get-FileHash .\data\underwriting\valuation-repeat.json).Hash
```

Inspect all starting inputs, scenario assumptions, and intermediate values.
Verify the displayed arithmetic against the equations above. Edit your
scenario file, create another underwriting version, and value its exact
version. Re-show the original version and verify it still matches the export.
No refresh or API key is needed for valuation.

## Validation and exclusions

Fixture tests verify compounding, margin and terminal-multiple arithmetic,
share-count evolution, CAGR, separate scenarios, invalid inputs, price
provenance, legacy compatibility, schema migration, immutable outputs,
repeated runs, and v1/v2 isolation. The ADBE integration fixture creates
underwriting from persisted FMP facts before valuation. Network access is
prohibited in workflow tests.

There are no probabilities, expected-value weighting, return hurdle, edge,
reverse DCF, Monte Carlo, alternative valuation methods, AI research,
recommendations, portfolio sizing, or Streamlit valuation editing.

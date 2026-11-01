---
title: "Feature 8D: Market Expectations and Variant Perception"
description: "Compare frozen historical evidence, analyst expectations and BASE assumptions without inventing consensus or edge."
---

## Offline, immutable inputs

`variant show` derives a deterministic report from an exact
[underwriting version](feature_08b_immutable_underwriting.md). It uses the
captured historical base rates, captured annual analyst estimates and explicit
BASE scenario from [8C](feature_08c_scenario_valuation.md). It does not load
new financial evidence, consult FMP, or require a previously saved valuation.
Historical records without scenarios fail clearly; create a new version.

Reports include the underwriting id, version, hash, as-of date and comparison
model version `variant-base-local-sensitivity-v1`. No new SQLite table is
necessary: the frozen inputs reproduce the report, including its JSON export.
Existing underwriting bytes and saved valuation results remain unchanged.

## Comparison contract

The four drivers are `revenue_cagr`, `fcf_margin_year5`, `share_count_cagr`
and `terminal_fcf_multiple`.

* History remains `FACT` or derived `CALCULATION`, including observations,
  latest value, minimum, maximum and missing reasons.
* Consensus remains `EXPECTATION`. Derived revenue CAGR carries
  `basis_category=CALCULATION`, its formula and the original expectation
  snapshot id, hash, retrieval time, target date, range and analyst count.
* BASE inputs remain `ASSUMPTION`.
* Deltas, direction, sensitivity and the report conclusion are `CALCULATION`.
* Recorded per-driver disagreement explanations remain `JUDGMENT`, with
  optional references. They are not generated from scenario narratives.

### Revenue horizon

Use the latest annual snapshot already captured in the underwriting, even if
it is empty or missing the relevant average. Its retrieval time must not exceed
the captured cutoff, underwriting as-of end of day or actual creation time.
Quarterly estimates are never substituted.

Select the farthest annual target aligned to the starting revenue fiscal
period end within one to five fiscal years. Allow up to 14 days of anniversary
drift for 52/53-week fiscal calendars; do not substitute a calendar-year target
for a different fiscal-year end. Ambiguous starting period ends, missing
averages and no aligned target produce explicit unavailable consensus.
Duplicate target periods, inconsistent low/average/high ranges, invalid
categories or non-positive revenue fail explicitly.

For that target, calculate:

```text
Consensus_CAGR = (target_revenue / frozen_starting_revenue)^(1 / fiscal_year_gap) - 1
Delta = BASE_revenue_CAGR - Consensus_CAGR
Relative_delta = Delta / abs(Consensus_CAGR)
```

Low and high revenue estimates use the same equation. Compare the constant
annual BASE growth assumption over the same target horizon. A three-year
estimate is not five-year consensus, and no estimate is extrapolated to year
five. Displayed deltas are ratios: `0.02` is two percentage points. The
relative delta is unavailable when consensus equals zero.

FMP's captured revenue/EPS estimates do not supply comparable FCF margins,
share-count CAGR or terminal FCF multiples. Those consensus fields and deltas
remain unavailable. EPS is not an FCF-margin proxy; price does not imply a
consensus terminal multiple. The assumptions, available history, rationales
and sensitivities for those drivers remain visible.

### Materiality and an honest conclusion

A material numerical disagreement means at least one percentage point of
absolute ratio delta (or one multiple turn if comparable multiple consensus
exists in a future model). Direction is `ABOVE`, `BELOW`, `ALIGNED` or
`UNAVAILABLE`. Materiality does not imply evidence quality, edge or a trade.

`IDENTIFIABLE_VARIANT_VIEW` requires a material comparable consensus difference
and an explicit recorded driver rationale. Otherwise the valid result is
`NO_IDENTIFIABLE_VARIANT_VIEW`. Material differences without rationales are
still displayed rather than hidden. Missing consensus never forces a view.

## Deterministic sensitivity

Reuse the unchanged 8C valuation engine, perturbing only one BASE input at a
time, holding everything else fixed:

* Revenue CAGR: add `0.01`.
* Year-five FCF margin: add `0.01`; subtract `0.01` instead when addition would
  exceed 100%. The signed perturbation is displayed.
* Share-count CAGR: add `0.01` (more dilution or less share shrinkage).
* Terminal FCF multiple: add `1.0`.

Show baseline and perturbed value/share, absolute and relative value delta,
baseline and perturbed implied CAGR, and CAGR delta. Relative value change
is unavailable at zero baseline value. Each counterfactual exists only in
memory, not as a new underwriting version or saved valuation.

Bands depend on absolute change in implied CAGR: `LOW` below one percentage
point, `MEDIUM` from one to below two, `HIGH` at least two. These documented
local perturbations are not cross-driver elasticities or new screening rules.
They are not uncertainty estimates or forecasts. The report exposes exact
inputs and results rather than only the band.

## Manual ADBE workflow

Use an existing complete version, or copy and edit the
[illustrative scenario input](../examples/adbe_scenario_underwriting.sample.json).
The sample is not an ADBE recommendation. Keep `variant_rationales` empty if
you have no identifiable disagreement. Otherwise add only your own recorded
reasons, for example this structural template:

```json
{
  "variant_rationales": [
    {
      "driver": "revenue_cagr",
      "category": "JUDGMENT",
      "text": "REPLACE with your reason for differing from captured consensus.",
      "references": [
        {"title": "Your supporting source", "uri": "https://example.com"}
      ]
    }
  ]
}
```

This is an optional field inside the complete underwriting input, not a
standalone input. Unknown/duplicate drivers, empty explanations and category
substitutions fail. Adding or changing a rationale requires a new version.

```powershell
New-Item -ItemType Directory -Force .\data\underwriting | Out-Null
Copy-Item .\docs\examples\adbe_scenario_underwriting.sample.json .\data\underwriting\ADBE-variant.json
notepad .\data\underwriting\ADBE-variant.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE-variant.json
uv run owner-lens underwriting history ADBE
$Version = 1 # Replace with the new version printed by create/history.
uv run owner-lens valuation run ADBE --version $Version
uv run owner-lens variant show ADBE --version $Version
uv run owner-lens variant show ADBE --version $Version --json
```

All commands above operate on persisted evidence, not live endpoints. Inspect
the target horizon, snapshot time/hash, historical ranges, unavailable
consensus reasons and your rationales. Verify perturbation arithmetic against
the saved BASE valuation. After newer evidence arrives or v2 is created,
repeat the v1 report and confirm it is identical. JSON exports can be saved
with `Set-Content -Encoding utf8` and compared with `Compare-Object`.

## Fixture example

Synthetic ADBE-labeled inputs, not live ADBE findings: starting revenue 1,000,
shares 100, price 20; BASE growth 10%, margin 20%, share CAGR -2%, multiple
20x; three-year consensus revenue CAGR 8% with a manual fixture rationale:

```text
Driver              History   Consensus       Mine     Delta   Sensitivity
Revenue CAGR           7.00%       8.00%     10.00%     2.00%        MEDIUM
FCF margin            18.00%         n/a     20.00%       n/a        MEDIUM
Share CAGR            -1.00%         n/a     -2.00%       n/a        MEDIUM
Terminal multiple       n/a         n/a     20.00x       n/a        MEDIUM
IDENTIFIABLE_VARIANT_VIEW
```

Remove the manual rationale or align BASE growth with consensus and the
conclusion becomes `NO_IDENTIFIABLE_VARIANT_VIEW`. This feature adds no
probabilities, weighted returns, hurdle, edge score, AI, portfolio logic or
Streamlit UI.

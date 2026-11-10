---
title: Deterministic Owner Earnings Bridge Validator
description: Read-only structural validation and Decimal historical owner-earnings arithmetic for Bridge v1.
---

## Scope and usage

The additive [manual research handoff](feature_m2a4_3_research_handoff.md)
exports validated bridge evidence for ChatGPT and checks unapproved research
responses without importing them into Feature 8.

The validator consumes the existing
[Bridge v1 schema](../examples/owner_earnings_bridge_v1.schema.json) without
changing it or Feature 8 Authoring v2. It reads one explicit JSON file, emits
deterministic JSON, and does not open a database or call a provider.

```powershell
uv run owner-lens owner-earnings-bridge --file .\docs\examples\deck_owner_earnings_bridge_v1.sample.json
$LASTEXITCODE
```

Exit 0 means the document is structurally and economically consistent.
It can contain UNRESOLVED research cases. Exit 2 means invalid input, an
inconsistent calculation or an unreadable file; errors go to stderr.
Unresolved research is not invalid data and is never silently converted to zero.

If dependency synchronization encounters a running Windows owner-lens.exe,
leave that process alone. After dependencies are installed, use:

```powershell
uv run --no-sync owner-lens owner-earnings-bridge --file .\docs\examples\deck_owner_earnings_bridge_v1.sample.json
```

## Implemented checks

* Draft 2020-12 validation, date formats, unknown fields, numeric states,
  decimal strings, duplicate JSON keys and nonfinite values
* Unique source, period, observation, adjustment, claim and case IDs, including
  rejection of ambiguous cross-namespace IDs
* Resolvable source/period/input/adjustment/claim links and acyclic observation
  and adjustment dependencies
* Historical fiscal alignment, chronological cutoffs, retrieval/filing dates,
  provider acceptance dates and quote chronology
* Observation units/categories, scalar historical values, nonnegative canonical
  PP&E CapEx and matching optional canonical metadata
* OCF minus CapEx reconciliation and aligned annual diluted-share division
* Adjustment dependencies, exclusions, overlap groups and assumption status
* Baseline identity, empty baseline adjustment list, correct output units,
  declared result amounts and explicit unsupported selected components
* Preserved investor approval, activated gates, business uncertainty, financial
  warnings, evidence limitations and price compatibility states

Three outcomes remain independent of investment merit:

* VALID_REPORTED_BASELINE: declared sourced canonical baseline reconciles
* VALID_CONDITIONAL: hypothetical arithmetic reconciles with selected adjustment
  categories and approval states disclosed
* UNRESOLVED: an indispensable numerator, effect or positive aligned share
  denominator is unsupported

A supported total remains reportable when per-share evidence is missing.
Structural contradictions and mismatched amounts are errors, not unresolved
results. A numeric investor assumption and resulting case must remain
CONDITIONAL even when approved. UNREVIEWED remains UNREVIEWED.

## Arithmetic

All new arithmetic uses Decimal in an isolated, operand-scaled context with
at least 50 digits and standard half-even rounding. Cash sums are compared
exactly. Division outputs allow absolute error of `1e-12` to accommodate
serialized canonical floats; this tolerance is not applied to cash totals.

Signed effects add to reported FCF. Interval endpoints propagate by addition
and division by the same positive diluted-share scalar. They are deterministic
envelopes, not probabilities. No averaging or missing-value substitution occurs.
Negative and zero FCF are preserved.

## Observed DECK result

The committed example reconciles FY2026 OCF of USD 1,181,955,000 less canonical
CapEx of USD 84,623,000 to FCF of USD 1,097,332,000. Dividing by 145,805,000
annual diluted shares gives approximately USD 7.526024484757039/share.

The reported case is VALID_REPORTED_BASELINE. Historical normalization remains
UNRESOLVED. Quote currency remains NOT_VERIFIED and share basis UNVERIFIED.
No existing underwriting is loaded, changed or approved.

## Synthetic controls and focused validation

The test fixtures are synthetic structural examples, not company facts.
The ORCL-shaped control retains negative reported FCF and an existing
PERSISTENT_CASH_BURN gate while maintenance/growth allocation remains unresolved.
The JPM-shaped control retains the financial-sector comparability limitation
and gate. Neither produces a generic price/FCF valuation.

Run the essential suite, including invalid references, chronology, approval,
signed/ranged effects, missing shares and mismatched outputs:

```powershell
uv run --no-sync pytest -q tests\test_owner_earnings_bridge.py tests\test_cli.py tests\test_underwriting_contract.py tests\test_research_context.py
uv run --no-sync ruff check --no-cache src tests
uv run --no-sync mypy src
git diff --check
```

Run only the synthetic cross-business controls:

```powershell
uv run --no-sync pytest -q tests\test_owner_earnings_bridge.py -k synthetic_cross_business_controls
```

Run invalid-data controls:

```powershell
uv run --no-sync pytest -q tests\test_owner_earnings_bridge.py -k "semantic_errors or structural_errors or file_loading_errors"
```

The full regression was cancelled by the investor because of its runtime.
Focused validation covers the new service/CLI and existing research/Authoring
v2 boundary. Unrelated Workbench/provider/persistence workflows were not fully
rerun; retain that residual integration risk until the next milestone.

## Explicit limits

Source hashes and IDs are provenance claims, not verified raw payloads.
This service checks the document, not whether its evidence is true.
Adjustment effects are declared inputs: free-text calculations, recurrence,
maintenance/growth allocation, working-capital policy and management claims
are not executed or certified. Numeric CALCULATION effects require supported
referenced observations and sources, but the narrative derivation still needs
human review.

Capital-efficiency metrics other than FCF/share are preserved and checked for
units/category/links; their entire tax and prior-capital arithmetic is not
reimplemented. Provider acceptance timestamps without timezones are checked
by date only. No timezone is invented. Fiscal-year labels are not assumed to
equal calendar period-end years.

No sector-specific accounting engine, SBC/dilution economic adjudication,
source fetching, normalized valuation, forecast or underwriting importer is
provided. The schema remains the single wire-shape definition and is packaged
with documentation for installations outside a checkout.

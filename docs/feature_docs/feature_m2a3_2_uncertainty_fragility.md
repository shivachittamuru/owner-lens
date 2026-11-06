---
title: Uncertainty and Fragility Review
description: Independent historical research prompts, financial evidence states, and accounting limitations in the Screener.
---

## Scope

The Screener's optional Uncertainty & Fragility review reads persisted evidence
only. It preserves Feature 7 rankings, all six bands, every existing gate,
Improving Economics eligibility, candidate-review selection, prices, and frozen
underwriting. It does not produce a risk score, safety classification, or
investment recommendation.

The review covers the active persisted universe in original Feature 7 order.
Per-company cached results are plain data, keyed on company evidence and the
original screening result. Loading is opt-in; no provider calls are made.

## Business indicators

All indicators are historical research prompts, not predictions or
HIGH_UNCERTAINTY labels. Thresholds are inclusive except the 1.50 normalization
ratio, which must be exceeded. Annual periods must be consecutive and align
revenue, operating cash flow, PP&E spending, and diluted shares.
Inclusive percentage-change boundaries use a 1e-12 absolute floating-point
tolerance; the strict normalization ratio does not.

| Indicator | Exact rule |
| --- | --- |
| FCF/share direction reversal | Five positive annual FCF/share observations; at least one annual increase of 10% or more and one decrease of 10% or more |
| FCF/share normalization sensitivity | Latest three positive annual observations; latest FCF/share exceeds 1.50 times their median |
| FCF margin change | Latest three annual margins available; latest annual decline is at least 3 percentage points, or their range is at least 10 percentage points |
| Revenue growth deceleration | Three positive annual revenues; latest year-over-year growth is at least 10 percentage points below the preceding growth |

Unsupported or incompatible comparisons are suppressed, not interpreted as
stable economics. Financial Services and Real Estate do not receive these
ordinary-business indicators. Qualitative uncertainty about competition, brand
relevance, regulation, and technology always requires investor research.

## Financial evidence states

These are evidence states, not four measured risk levels:

* ACTIVATED_EXISTING_GATE preserves the existing financial survival gate.
* OBSERVED_FINANCIAL_WARNING means at least one supported warning is present.
* NO_FLAG_FROM_CURRENT_CHECKS does not mean safe or low fragility.
* INSUFFICIENT_EVIDENCE means essential history, FCF/share, balance-sheet or
  capital-efficiency evidence is unavailable or incompatible.

Coverage gates remain visible as existing gates, but are not reclassified as
financial distress. Existing gates take precedence over missingness; an
observable financial warning is retained even when other evidence is missing.

Warnings include latest nonpositive canonical FCF, existing MATERIAL_DILUTION
with Feature 7 measurements, and net debt/positive latest FCF above Feature 7's
existing adequate threshold of 2.0. A separate financing-context prompt fires
when canonical net debt is present and latest PP&E spending/revenue is at least
20%. None estimates cash runway, maturities, covenants, or refinancing needs.

All original dimension measurements are available in expanded detail, including
the measurements supporting cash-burn, returns, leverage, and dilution gates.

## Evidence uncertainty

Missing annual periods, unsupported canonical metrics/layers, absent debt
observations, and sector incompatibility appear separately. Canonical-linked
FMP cash-flow and balance snapshots provide definition checks:

* Absolute PP&E spending versus absolute provider capitalExpenditure.
* Short-term plus long-term debt versus provider totalDebt.

A nonzero difference of at least 5% of the larger absolute definition is flagged
as material for this review. This relative threshold is not an estimate of
economic impairment; small absolute differences may still be immaterial to an
investor. Missing or malformed fields and inaccessible, malformed, or
hash/identity-mismatched raw evidence are NOT_VERIFIED. Missing or duplicate
source periods and non-USD or unknown reported currency do not establish
definition comparability.

Differences are not repaired, substituted into canonical calculations, or used
to activate new survival gates. Economic inclusion remains unresolved. Source
snapshot IDs, endpoints, retrieval dates, and hashes are shown. These are
retrospective observations, not certified point-in-time evidence.
Income-statement source provenance is retained for revenue and diluted-share
observations. Annual alignment does not certify recurring economics or full
year duration when the provider omits period-start metadata.

## Manual Workbench validation

Run from the repository directory. To inspect the existing disposable pilot:

```powershell
$pilotRoot = (Resolve-Path -LiteralPath "data\historical-price-pilot-f8a480903eb34e4cb6f74371ed9c8565").Path
$pilotDb = Join-Path $pilotRoot "ownerlens.db"
$pilotRaw = Join-Path $pilotRoot "raw"
$env:OWNER_LENS_RAW_DATA_PATH = $pilotRaw
uv run owner-lens workbench --db "$pilotDb" --provider fmp
```

To use your configured persisted store instead:
Run this in a separate terminal, without the pilot raw-data override.

```powershell
uv run owner-lens workbench --provider fmp
```

Open the local URL printed by Streamlit. Select Screener, then enable
Show Uncertainty & Fragility review. It is available below both the Standard
Screener and Improving Economics lane.

1. Leave Flagged evidence only enabled, select a company, and expand
   Observations, rules and source evidence.
2. Compare DECK and CMG: strong original priorities and no active gates must
   remain unchanged. Definition differences must not become distress labels.
   No deterministic business indicator does not remove qualitative research.
3. Inspect ADSK's FCF/share reversal and latest/median sensitivity. Compare
   fiscal-period values with cash-flow definition and debt-component limitations.
4. Inspect ORCL and INTC: existing cash-burn gates must remain prominent.
   Compare latest FCF, canonical debt, capital intensity, and dilution evidence.
5. Disable Flagged evidence only to inspect companies with no flags.
   No flag from these checks must never read as SAFE.
6. Use Open research / underwriting in Company view. Existing research and
   immutable underwriting remain the destination; no records are created.
7. Rerun the Screener and confirm stable ordering and repeatable observations.

## Validation commands

```powershell
uv run pytest -q tests\test_uncertainty_fragility.py tests\test_workbench_pages.py tests\test_workbench_fmp.py tests\test_screening_buckets.py tests\test_candidate_review.py
uv run ruff check src tests
uv run mypy src
git diff --check
```

The change is additive and does not change shared financial, persistence,
screening, or underwriting semantics. The full regression suite is reserved
for the next integration checkpoint. Automated rendering tests use offline
fixtures; investor judgment about UI usefulness and company-specific risks
still requires manual review.

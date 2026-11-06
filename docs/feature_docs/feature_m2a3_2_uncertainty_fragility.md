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

### Integrated discovery queue

M2-A3.3 adds a multi-company queue above the evidence inspector. It is visible
by default below the existing Screener and Improving Economics views; uncheck
Show Uncertainty & Fragility review to hide the additive section.

Two opportunity lanes use existing eligibility, not missingness or accounting
differences:

* Strong compounders: M2-A3's compounder setup, High Priority or Worth
  Underwriting, Strong business-quality, capital-efficiency and per-share
  bands, and no existing gate.
* Improving businesses: existing M2-A1 financial criteria and WATCH/LOW_PRIORITY
  eligibility, with no existing gate.

Financial Services and Real Estate are excluded from ordinary-business
opportunity comparisons. All activated financial gates are retained in a
separate fragility lane. Coverage gates are not financial distress; they remain
available in the inspector and primary Screener.

Each lane reports its total eligible count and displays the first eight in
original Feature 7 rank order. Eight is the existing M2-A3 presentation bound,
not a financial threshold. Expand the remainder to inspect all eligible names
and gates. No normalization-control reservation is applied to discovery, and
M2-A3 candidate selection itself is unchanged.

The first eight opportunity companies per lane receive cached M2-A3 worksheets
using each company's latest saved market date. Dates can differ across names.
No quote is fetched; conditional ratios remain unverified. Unsupported ratios
are unresolved, never cheap or expensive. Additional names and gated controls
remain economics/gate reviews, not valuation comparisons.

Choose Shortlisted company to investigate, then Inspect shortlisted company
evidence to populate the existing inspector, or Open shortlisted company
research / underwriting to navigate to Company. Price/denominator provenance
for bounded opportunity worksheets is available in a separate expander.

Read-only validation of the current pilot found 28 eligible compounders, 56
ungated improving businesses, and 173 existing financial-gate cases. These are
observed counts, not selection targets. DECK and CMG appear in the first eight
compounders; ADSK appears in the first eight improving businesses. ORCL and
INTC remain in the expanded financial-gate lane.

For October 30, 2026 persisted prices, DECK's conditional latest/median P/FCF
is approximately 10.9x/13.1x; CMG's is 29.6x/29.6x; ADSK's latest is 22.3x
and its median comparison is unresolved. These are arithmetic observations,
not valuation verdicts. Current USD profile evidence permits conditional
arithmetic; historical currency/share adjustment remains unverified.

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
8. Confirm the discovery tables show multiple companies without first entering
   a ticker. Inspect DECK and CMG in compounders, ADSK in improving (or the
   expanded remainder), and ORCL/INTC in the fragility lane. A debt-definition
   limitation alone must never create an opportunity candidate.

## Validation commands

```powershell
uv run pytest -q tests\test_discovery.py tests\test_uncertainty_fragility.py tests\test_screening_buckets.py tests\test_candidate_review.py
uv run ruff check src tests
uv run mypy src
git diff --check
```

The change is additive and does not change shared financial, persistence,
screening, or underwriting semantics. The full regression suite is reserved
for the next integration checkpoint. Automated rendering tests use offline
fixtures; investor judgment about UI usefulness and company-specific risks
still requires manual review.

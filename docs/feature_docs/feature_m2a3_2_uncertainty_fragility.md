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

The inspector covers the active persisted universe in original Feature 7 order.
The additive discovery queue has independent conditional valuation-attention
ordering; it does not write back a new screening rank.
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

Each lane displays the first eight and reports its total count. Eight is the
existing M2-A3 presentation bound, not a financial threshold. Expand the
remainder to inspect all eligible names and gates. No normalization-control
reservation is applied to discovery, and M2-A3 candidate selection is unchanged.

M2-A3.4 evaluates cached M2-A3 worksheets for every economically eligible
opportunity before choosing the first eight. It does not evaluate price
worksheets for the financial-gate lane. No quote is fetched.

### Conditional valuation-attention policy

The common attention date is the newest saved opportunity quote date, not a
live price or financial statement date. A company is conditionally orderable
only when it has:

* Existing economic eligibility and no activated gate
* A known sector compatible with ordinary-business FCF comparisons
* Sufficient financial-resilience observations from the existing review
* Three distinct consecutive fiscal years of positive canonical FCF/share
* Supported positive latest and median P/FCF comparisons
* Supported currency evidence, including explicitly inferred current profiles
* A saved quote on the common attention date

Orderable names are grouped by sector alphabetically, then ordered by ascending
three-year-median P/FCF within that sector. Original Feature 7 rank breaks ties.
Alphabetical sector placement is a display convention, not investment
preference. Sectors are coarse peer groups, not proof of comparable business
models. There is no cross-sector cheapness score or universal multiple cutoff.
Unranked economically eligible names follow in original Feature 7 order and
remain selectable. Financial gates retain their original ordering.

Conditional latest and median FCF yields equal the reciprocal of supported
positive P/FCF. Denominator sensitivity equals latest positive FCF/share divided
by positive three-year median FCF/share. Missing, negative, gapped or unsupported
denominators cannot produce a normalized ordering. Latest-year revenue and
FCF/share growth, historical periods, financial warnings and definition conflicts
remain available. The selected-company expander preserves raw worksheet
provenance and the exact ordering or exclusion reason.

Missing prices or currency evidence, insufficient resilience, incompatible
sectors, source-definition conflicts and invalid canonical inputs remain
explicitly unresolved or unranked. An invalid metric in a candidate worksheet
does not crash the full queue or rewrite the canonical facts. A generic debt
definition difference is not financial distress and does not qualify a company.
Observed financing warnings remain visible even for orderable names.

Conditional ratios are NOT_VERIFIED. Inferred currency and unverified share
adjustment are never upgraded into verified valuation. A historical median is
not normalized sustainable FCF or intrinsic value. High growth, cyclical
investment and temporary working-capital effects require investor research.

Choose Shortlisted company to investigate, then Inspect shortlisted company
evidence to populate the existing inspector, or Open shortlisted company
research / underwriting to navigate to Company. Price/denominator provenance
for opportunity worksheets is available in a separate expander.

Read-only validation of the current pilot found 28 eligible compounders, 56
ungated improving businesses, and 173 existing financial-gate cases. These are
observed counts, not selection targets. With the saved evidence, 8 compounders
and 5 improving businesses meet conditional ordering requirements; the other
71 stay unranked.
These counts depend on saved evidence, not economic eligibility changes.

The first eight compounders change from ADBE, CMG, DECK, EME, LRCX, NVDA, RMD,
ANET to DECK, CMG, EME, ADBE, ANET, LRCX, NVDA, MU. Improving businesses change
from DIS, NOW, TYL, VEEV, VRSK, STE, TT, ADSK to DIS, STE, VRSK, TT, NOW, TYL,
VEEV, ADSK. These are sector-grouped research queues, not global return rankings.
ORCL and INTC retain PERSISTENT_CASH_BURN in the expanded financial-gate lane.
HST (Real Estate) and JPM (Financial Services) remain available in the primary
Screener/inspector, outside generic-FCF opportunity ordering.

For October 30, 2026 persisted prices, DECK's conditional latest/median P/FCF
is approximately 10.9x/13.1x; CMG's is 29.6x/29.6x; ADSK's latest is 22.3x
and its median comparison is unresolved. These are arithmetic observations,
not valuation verdicts. Current USD profile evidence permits conditional
arithmetic; historical currency/share adjustment remains unverified.

NVDA's conditional latest/median multiples are 51.9x/83.4x, yields 1.93%/1.20%,
and denominator ratio 1.61x. ADSK's denominator ratio is 1.62x, but earlier CapEx
conflicts block median comparison and ordering. DECK's median yield is 7.66%
versus CMG's 3.38%, with denominator ratios 1.20x and 1.00x. These differences
justify questions about durability and expectations, not an attractiveness
classification. MU is orderable at roughly 596.7x median P/FCF and 34.79x
denominator sensitivity; inclusion does not imply a low multiple.

Of the 71 unranked companies, 62 lack supported currency comparability, 5 have
blocked latest/median comparisons and 4 have unresolved canonical repurchase
signs. Those input errors are disclosed, not corrected in this slice. Source
statement retrievals for the representative controls are October 31, 2026;
exact fiscal periods, retrieval timestamps and hashes remain in the inspector
and selected-company evidence. The read-only pilot database SHA-256 was
unchanged before/after validation.

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
9. Compare DECK before CMG within Consumer Cyclical and ADBE before ANET, LRCX,
   NVDA and MU within Technology. Sector placement is alphabetical, not a
   cross-sector valuation ranking. Check the common October 30 saved date.
10. Inspect ADSK's unresolved median, NVDA's growth/sensitivity and MU's extreme
    sensitivity. Confirm their warnings survive ordering. Expand remaining
    names to see exclusion reasons, then select one for its complete evidence.
11. Compare HST or JPM in the primary Screener and inspector. Neither should
    receive generic-FCF valuation ordering. No gated company belongs to an
    opportunity lane, regardless of its saved price.

## M2-A5.1 numeric sorting and compact discovery tables

The existing [Screener renderer](../../src/owner_lens/workbench/views/screener.py)
keeps the same discovery membership, valuation-attention order, first-eight
shortlist and company navigation. No calculation, gate, provider, persistence
or underwriting service changes are involved.

Previously, long text columns combined multiples, yields, economic trends and
research questions. Opportunity tables now show eight columns: ticker, sector,
economic setup, median P/FCF, median FCF yield, latest-to-median FCF/share,
financial warnings and valuation/evidence status. Financial-gate tables show
ticker, economic priority, gate/warning summary and coverage.

Median/latest P/FCF, median/latest FCF yield, latest-to-median FCF/share, revenue
growth and FCF/share growth remain numeric, including in the expanded detail
tables. The separate Improving Economics review table also keeps diluted-share
CAGR numeric. Streamlit NumberColumn uses multiple suffixes and percent
formatting; a stored ratio of 0.12 displays as 12.00%, not 0.12%. Missing metrics
remain numeric nulls, never zero or text placeholders.

The first view contains eight companies per lane. The existing all-eligible
expander uses the same compact columns and includes every eligible company,
not only the remainder. Economics, valuation and screening details remain in
a separate expander, including company names, historical trends, latest
metrics, research questions and exclusion reasons. Selected-company source
details and the existing uncertainty/fragility inspector retain dates,
denominators, currency/share-basis limitations and complete gate evidence.

Sorting changes presentation only. Conditional P/FCF and FCF yield are not
verified undervaluation measures and may not be comparable across business
models.

Header sorting applies only to that displayed table. It cannot change shortlist
membership, lane membership, Feature 7 rank, the default attention order or the
company selector order. Use the all-eligible expander to sort the whole lane.
Null cells have no economic meaning; consult the separate status and detailed
evidence. Streamlit controls client-side sort indicators and null placement.

### Manual numeric-table checks

Run these commands from the repository directory to open the existing saved
pilot, without fetching new evidence:

```powershell
$pilotRoot = (Resolve-Path -LiteralPath "data\historical-price-pilot-f8a480903eb34e4cb6f74371ed9c8565").Path
$pilotDb = Join-Path $pilotRoot "ownerlens.db"
$pilotRaw = Join-Path $pilotRoot "raw"
$env:OWNER_LENS_RAW_DATA_PATH = $pilotRaw
uv run --no-sync owner-lens workbench --db "$pilotDb" --provider fmp
```

In Screener, enable Show Uncertainty & Fragility review:

1. Compare the initial eight names against the unchanged attention order.
   Expand all eligible names; confirm none disappeared.
2. Click median P/FCF in both directions. Compare DECK, CMG and NVDA using
   numeric magnitude, not leading digits. Test yields in both directions.
3. Confirm ADSK's blocked median remains null (blank/None), with an explicit unranked
   explanation. Inspect its supported latest comparison in expanded details.
4. Confirm ORCL and INTC retain their cash-burn gate and original coverage.
   Use Inspect shortlisted company evidence for the complete gate reasons.
5. Inspect saved dates, source IDs, annual denominators and currency/share
   limitations. Use Open shortlisted company research / underwriting and
   confirm Company remains the destination, without saving a version.
6. Rerun/reset the view to verify default ordering is unchanged. Table sorting
   is local presentation state, not a persisted ranking policy.

### Focused presentation validation

The local-evidence test is opt-in. It opens the supplied existing database
read-only, verifies DECK, CMG, NVDA, ADSK, ORCL and INTC, blocks HTTP requests
and checks zero database changes plus an unchanged database SHA-256. It never
initializes or seeds that database.

```powershell
$pilotRoot = (Resolve-Path -LiteralPath "data\historical-price-pilot-f8a480903eb34e4cb6f74371ed9c8565").Path
$env:OWNER_LENS_DISCOVERY_TEST_DB = Join-Path $pilotRoot "ownerlens.db"
$env:OWNER_LENS_DISCOVERY_TEST_RAW = Join-Path $pilotRoot "raw"
uv run --no-sync pytest -q tests\test_discovery.py tests\test_workbench_frames.py tests\test_workbench.py
uv run --no-sync ruff check src tests
uv run --no-sync mypy src
git diff --check
Remove-Item Env:\OWNER_LENS_DISCOVERY_TEST_DB, Env:\OWNER_LENS_DISCOVERY_TEST_RAW
```

Without those two test variables, fixture-based tests still run; the single
local-evidence test skips. The M2-A4 integration checkpoint passed 1,952 tests.
This presentation-only slice does not require another full-suite run.

## Earlier evidence-service validation commands

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

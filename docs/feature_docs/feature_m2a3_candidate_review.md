---
title: Price-Aware Candidate Review Pilot
description: Bounded offline research worksheets and explicit selected-candidate FMP price evidence.
---

## Scope

`candidate-review` selects up to 24 distinct securities from the existing FMP
universe. It reuses Feature 7 screening, the Improving Economics review filter,
canonical owner economics, and Copy Research Context. It changes no financial
definitions, rankings, classifications, frozen underwritings, or Workbench UI.

The report opens SQLite in read-only mode without initialization or migration.
Only `retrieve-prices` makes provider requests. Reporting, Research Card export,
and Workbench navigation never invoke that operation.

## Reproducible cohorts

Selection uses the current persisted five-year financial evidence. It is not
a historical-as-of screen. Existing Feature 7 `rank_key` orders every eligible
list; prices never affect selection.

1. Reserve four distinct normalization controls: first eligible Real Estate,
   Financial Services, questionable capital allocation, and below-quality
   capital returns cases, in that order.
2. Reserve four remaining companies with an existing financial survival gate.
   These are gate controls, not a new insolvency classification.
3. Select eight remaining compounders from the existing deeper-research queue,
   with Strong business-quality, capital-efficiency, and per-share bands,
   no gate, and no financial-services or real-estate sector.
4. Select eight remaining companies from the existing Improving Economics
   review filter, excluding financial-services and real-estate sectors.

The Improving Economics filter requires five positive-FCF annual observations,
increasing FCF and FCF/share in the latest three, and latest revenue above the
five-year starting revenue. Its original gate remains visible.

Shortfalls and unavailable evidence are explicit. No ineligible fillers are
substituted. Acquisition is blocked if cohort selection has errors.
Up to five ungated positive-FCF cases are named for research in the original
cohort/rank order, not because their prices have been verified as attractive.

## Offline report

Run from the repository directory. Keep these variables in the same PowerShell
terminal. Use the disposable copy from the historical-price pilot:

```powershell
$pilotRoot = (Resolve-Path -LiteralPath "data\historical-price-pilot-f8a480903eb34e4cb6f74371ed9c8565").Path
$pilotDb = Join-Path $pilotRoot "ownerlens.db"
$pilotRaw = Join-Path $pilotRoot "raw"

uv run owner-lens candidate-review report --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30
uv run owner-lens candidate-review report --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30 --format json
```

The command returns 1 for selection or worksheet errors. Missing price/currency
evidence is an explicit unresolved research state, not a fabricated ratio.
An exact requested market date is required; no earlier close is silently used.

## Explicit price acquisition

This operation targets only the selected cohort, not all 503 securities.
It rejects the configured primary database or raw-data path. Review the offline
cohorts before consenting to provider calls:

```powershell
uv run owner-lens candidate-review retrieve-prices --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30 --confirm-disposable-store --confirm-fmp-requests
if ($LASTEXITCODE -ne 0) { throw "Inspect the reported acquisition errors before interpreting quotes." }

uv run owner-lens candidate-review report --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30
```

Each security uses the existing FMP profile, splits, and full EOD methods.
The price window is 14 calendar days plus the endpoint date; split evidence
covers the preceding 1,095 days. There are at most 72 logical requests for
24 candidates, subject to the existing client's bounded transport retry policy.
No statements, estimates, universe membership, or investment records are refreshed.

Responses use the existing content-addressed raw store and evidence-snapshot
table, under `candidate_profile`, `candidate_splits`, and `candidate_price`.
No schema changes are needed. The historical-price table and existing latest
price records remain unchanged. Separate retrieval timestamps remain separate
vintages; equal payloads share content hashes instead of duplicating raw files.
Price differences across saved snapshots on the requested date are reported
and block comparison rather than choosing a favorable revision.

## Calculation safeguards

Canonical FCF is operating cash flow minus absolute PP&E spending.
Diluted weighted-average shares are used without inventing split factors.
Each denominator discloses period end, filing/acceptance fields, retrieval
timestamps, source IDs/hashes, and the alternate provider FCF/share.
The Markdown report deduplicates provenance in an evidence-source index;
JSON retains the full source-linked worksheets. Improvement indicators reuse
the existing financial criteria; they do not alter review-lane eligibility.

Current profile USD does not establish historical bar currency. Such arithmetic
is conditional on inferred currency compatibility and always `NOT_VERIFIED`
because price/share adjustment basis is unverified. Missing or non-USD quote
currency blocks arithmetic. No split factor or dividend convention is assumed.

Nonpositive/missing denominators, price revision conflicts, financial currency
uncertainty, unavailable filings, or financial-services/real-estate comparability
block the affected ratios. Conflicting CapEx definitions block ratios that use
the affected annual references. A median requires three observations.
Provider FCF that fails its own cash-flow/CapEx reconciliation blocks the
affected comparison. Canonical period or PP&E/source mismatches are worksheet
errors, not silently substituted denominators.

Debt components and provider totalDebt are shown separately. Disagreement is
a warning requiring investigation; it does not rewrite Feature 7 net cash.
No gate is proof of safety, and an activated gate is not proof of insolvency.
SBC, dilution, ROIC, reinvestment burden, and existing limiting reasons remain
visible. A median cash-flow reference is not sustainable FCF or intrinsic value.

## Research handoff

Export one selected case:

```powershell
uv run owner-lens candidate-review report --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30 --ticker ADBE
```

The Research Card includes the existing sanitized Copy Research Context,
source-linked candidate evidence, research questions, and an investor-led
ChatGPT prompt, including the latest saved immutable underwriting when present.
No new assumptions or probabilities are generated.
Incomplete legacy Copy Research Context metadata is reported as a worksheet
error; frozen evidence is not repaired or replaced.
ChatGPT must preserve sourced facts, separate expectations from judgment,
test competing hypotheses, and explain whether full Feature 8 underwriting is
justified. It must not approve probabilities or create investment decisions.

## Manual validation

1. Run the offline JSON report twice and compare outputs. Confirm cohort counts
   8/8/4/4, unique security IDs, and unchanged Feature 7 priorities/gates.
2. Before and after offline reporting, compare the database SHA-256:

   ```powershell
   $before = (Get-FileHash -LiteralPath $pilotDb -Algorithm SHA256).Hash
   uv run owner-lens candidate-review report --db "$pilotDb" --raw-data "$pilotRaw" --date 2026-10-30 | Out-Null
   $after = (Get-FileHash -LiteralPath $pilotDb -Algorithm SHA256).Hash
   if ($before -ne $after) { throw "Offline report changed the database." }
   ```

3. Recalculate three annual denominators from the displayed source fields and
   weighted-average diluted shares. Check TYL's FY2023 PP&E versus provider
   CapEx difference and ADSK's FY2024/FY2025 differences.
4. Confirm the quote date is exactly requested and retrieval is separately
   reported. Inspect missing profiles before running the opt-in acquisition.
5. After retrieval, inspect snapshot IDs/hashes and revisions. Verify existing
   latest quotes, canonical facts, and underwritings are unchanged using the
   [historical pilot fingerprints](./feature_08a2_fmp_evidence.md).
6. Inspect all four gated controls alongside the research cases. Check that no
   ratio overrides warnings or claims historical contemporaneous availability.
7. Paste a Research Card into ChatGPT and judge usefulness separately from
   calculation correctness: does it expose disconfirming evidence and justify
   deeper research, rather than relabeling an unresolved valuation attractive?

Focused fixture tests cover cohort counts/order, missingness, source dates,
canonical arithmetic, definition conflicts, revisions, identities, read-only
storage, explicit acquisition, and unchanged latest-price storage.
No live retrieval is part of automated validation.

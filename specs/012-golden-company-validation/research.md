---
title: Golden-Company Validation Research
description: Live pipeline audit, threshold generality audit, coverage design, and graceful-degradation decisions for ADBE, V, COST
ms.date: 2026-09-03
ms.topic: reference
---

## Overview

This slice validates and hardens the existing pipeline against three deliberately different
companies. The decisions below are grounded in a live pipeline audit run on 2026-09-03 that executed
every Feature 1 and Feature 2 aggregator for ADBE, V, and COST and recorded exactly which layers
succeeded and which raised.

## Live pipeline audit (2026-09-03)

| Layer | ADBE | V | COST |
|-------|------|---|------|
| owner_economics (F1) | OK (5 rows) | RAISES `ConceptNotFoundError` (diluted shares) | OK (5 rows) |
| capital_efficiency (F1) | OK (5 rows) | OK (5 rows) | OK (5 rows) |
| economic_value (2A) | OK (5 rows) | RAISES (via owner_economics) | OK (5 rows) |
| compounding (2B) | OK | RAISES (via owner_economics) | OK |
| capital_allocation (2C) | OK (5 rows) | RAISES (via owner_economics) | OK (5 rows) |
| economic_summary (2D) | OK -> `IMPROVING` | RAISES (via owner_economics) | OK -> `IMPROVING` |

Per-share coverage detail: ADBE FY2025 FCF/share ~23.07 (427.0M shares); COST FY2025 FCF/share
~17.62 (444.8M shares); Visa owner economics unavailable because diluted shares are unsupported.

### Key findings

* **Single choke point.** Every Feature 2 aggregator (`economic_value_from_facts`,
  `compounding_views_from_facts`, `capital_allocation_from_facts`, `economic_value_summary_from_facts`)
  calls `owner_economics_from_facts`, which calls `normalize_diluted_shares` unconditionally. That
  one call raises for Visa (no weighted-average diluted-share concept), cascading a failure through
  the entire Feature 2 stack even though revenue, operating income, net income, operating cash flow,
  capital expenditures, capital efficiency (ROIC), and capital-allocation reported facts all resolve.
* **Capital efficiency already works for Visa.** `capital_efficiency_from_facts` uses tolerant
  short-term investments plus the Slice 3B debt/equity overrides, so ROIC is available for Visa.
* **ADBE and COST are already full-coverage** and both classify `IMPROVING`. Costco, a low-margin
  (~4% net) working-capital-heavy retailer, is not misclassified as deteriorating, which is direct
  evidence the thresholds are not Adobe-only.

## Decision: Narrow diluted-shares tolerance at the owner-economics boundary

* **Decision**: In `owner_economics_from_facts`, wrap the `normalize_diluted_shares` call in a
  `try/except ConceptNotFoundError` and, on failure, pass an empty `AnnualSeries` (metric
  `diluted_shares`, empty concept, no observations) to `compute_owner_economics`.
* **Rationale**: `compute_owner_economics` already yields `None` for `diluted_shares`, `fcf_per_share`,
  `fcf_per_share_growth`, and `diluted_share_growth` when the shares series is empty, and populates
  every non-per-share field. This single narrow change unblocks Visa through owner economics and all
  four Feature 2 layers with honest partial results, and it is the minimal fix that the audit
  justifies. Adobe and Costco have diluted shares, so the `except` path never triggers for them and
  their output is unchanged.
* **Guardrail**: The substitute is an empty (unavailable) series, never a fabricated value and never
  point-in-time shares outstanding (spec FR-004). Diluted shares remains `UNSUPPORTED` at the
  normalizer level (`normalize_diluted_shares` still raises), preserving the Slice 3B distinction;
  only the owner-economics aggregator degrades gracefully.
* **Alternatives considered**:
  * *Make `normalize_diluted_shares` tolerant-absent*: rejected \u2014 it would erase the unsupported vs
    absent distinction established in Slice 3B and break its tests.
  * *Substitute `dei` period-end shares outstanding*: rejected \u2014 that silently changes the metric's
    meaning (period-end \u2260 weighted-average diluted) and is a fabricated denominator.
  * *Let the whole company fail*: rejected \u2014 it conflates incomplete data with incorrect data and
    discards Visa's genuinely available revenue, FCF, ROIC, and capital-allocation evidence.

## Decision: Downstream layers gain only exposed insufficient-data handling

* **Decision**: After the tolerance change, re-run the live pipeline for Visa and add narrow
  insufficient-data handling to `economic_value.py`, `compounding.py`, or `economic_summary.py` only
  where a real crash on `None` per-share is exposed. Do not preemptively refactor.
* **Rationale**: These layers were built to treat a missing per-share input as insufficient (the
  earliest-year case already produces `INSUFFICIENT_DATA`), so most `None` handling likely exists.
  Spec FR-008 requires fixing only assumptions actually exposed, using narrow handling rather than a
  generic optional-field framework.
* **Alternatives considered**: rewriting Feature 2 into an optional-field/result-monad framework
  (rejected as speculative over-generalization).

## Decision: A small read-only coverage helper

* **Decision**: Add `coverage.py` with a `MetricCoverage` state (`AVAILABLE`, `STRUCTURALLY_ABSENT`,
  `UNSUPPORTED`), a `LayerCoverage` state (`AVAILABLE`, `PARTIAL`, `INSUFFICIENT_DATA`,
  `UNAVAILABLE`) with an optional reason and blocking input, a `CompanyCoverage` record, a
  `company_coverage(raw_facts, ticker)` builder, and a deterministic `format_coverage_report`.
* **Rationale**: FR-005, FR-013, and FR-014 require an explicit coverage representation, a
  cross-company report, and honest company-level output. Building it as a read-only reporter over the
  existing entry points keeps it a small helper, not an orchestration engine (FR-016, Constitution
  VI). Input coverage is derived by probing the normalizers: a raise is `UNSUPPORTED`, an empty
  tolerant series is `STRUCTURALLY_ABSENT`, and a populated series is `AVAILABLE`.
* **Alternatives considered**: a generic DAG/workflow engine or reflection-based pipeline (rejected
  by the spec).

## Threshold generality audit

Every existing Feature 2 threshold was reviewed for whether it encodes a business-model-independent
economic concept. Change-based thresholds and self-normalized ratios are independent of absolute
margin level; ROIC is cross-industry comparable.

| Threshold (module) | Value | Nature | Classification |
|--------------------|-------|--------|----------------|
| material_growth (economic_value) | 0.05 | revenue/FCF change | GENERAL ENOUGH |
| material_margin_change (economic_value) | 0.01 | margin *change* | GENERAL ENOUGH |
| material_roic_change / severe_roic_change (economic_value) | 0.02 / 0.05 | ROIC change | GENERAL ENOUGH |
| material_share_change (economic_value) | 0.01 | share-count change | GENERAL ENOUGH |
| high_roic_level (all modules) | 0.20 | absolute ROIC | GENERAL ENOUGH (ROIC is cross-industry comparable) |
| strong / healthy / flat fcf_per_share_cagr (compounding) | 0.15 / 0.07 / 0.02 | per-share compounding rate | NEEDS DOCUMENTED LIMITATION |
| material_fcf_cagr / material_share_cagr (compounding) | 0.05 / 0.01 | change | GENERAL ENOUGH |
| material_margin_change / material_roic_change (compounding) | 0.02 / 0.03 | change | GENERAL ENOUGH |
| high_sbc_to_fcf (capital_allocation) | 0.15 | ratio to own FCF | GENERAL ENOUGH |
| meaningful_repurchase_to_fcf (capital_allocation) | 0.25 | ratio to own FCF | GENERAL ENOUGH |
| capital_returned_over_fcf_material (capital_allocation) | 1.00 | ratio to own FCF | GENERAL ENOUGH |
| material_roic_change / material_share_change (capital_allocation) | 0.03 / 0.01 | change | GENERAL ENOUGH |
| severe_roic_collapse (economic_summary) | 0.10 | ROIC change | GENERAL ENOUGH |
| high_roic_level (economic_summary) | 0.20 | absolute ROIC | GENERAL ENOUGH |

**Documented limitation**: the per-share FCF-CAGR bands (0.15 strong / 0.07 healthy) assume per-share
free-cash-flow compounding is the primary quality signal. This is deliberate and general for cash
compounders, but a capital-intensive business in a heavy reinvestment phase could be understated.
This is flagged as `REQUIRES FUTURE INDUSTRY-AWARE HANDLING` for a later slice; no value is changed
now because the live audit shows both a high-margin (ADBE) and a low-margin (COST) company classify
correctly, so there is no demonstrated incorrect generic assumption to correct in this slice.

## Minimum-data contracts (made explicit)

* **FCF/share and per-share classification**: require a trustworthy weighted-average diluted-share
  denominator. Unavailable for Visa \u2192 per-share analyses `INSUFFICIENT_DATA`.
* **ROIC / capital efficiency**: require operating income, income-tax and pretax inputs, and invested
  capital (debt + equity - cash and short-term investments). Available for all three.
* **Compounding (per-share)**: requires per-share FCF endpoints; unavailable for Visa.
* **Compounding (revenue / FCF)**: require the respective series endpoints; available for all three.
* **Capital allocation**: requires FCF and repurchases; dividends optional (structurally absent is
  fine); buyback effectiveness requires a diluted-share change and is `INSUFFICIENT` without it.

## Company-level coverage expectations (to validate live after the fix)

* **ADBE**: FULL across all layers (regression baseline; summary `IMPROVING`).
* **COST**: FULL across all layers (summary `IMPROVING`); validates 52/53-week handling and
  low-margin economics.
* **V**: capital efficiency, revenue, FCF, and capital-allocation reported facts AVAILABLE; per-share
  owner economics, 2A per-share classification, 2B per-share compounding, and the per-share portion
  of 2D reported `INSUFFICIENT_DATA` with the reason naming unsupported diluted shares.

## Remaining blockers to broader universe ingestion (documented)

* Weighted-average diluted shares are unsupported for some filers (Visa), blocking per-share
  analysis until a separately researched share-count source or definition is added.
* Per-share FCF-CAGR bands may need industry-aware calibration before scaling beyond conventional
  operating companies.
* No persistence or batch ingestion exists yet (intentionally out of scope here).

## Testing approach

Controlled ADBE/V/COST fixtures (reusing `tests/_fixtures.py`) drive: full-coverage ADBE and COST;
Visa partial coverage with per-share `INSUFFICIENT_DATA` and available non-per-share layers;
absent-vs-zero distinctions; business-model-diversity classification (a low-margin healthy-trajectory
company is not deteriorating, a high-margin weakening company is not improving, ROIC meaningful
across margin structures); deterministic coverage report; and full preservation of every existing
Adobe test. Live SEC calls are reserved for the optional honest-coverage report.

---
title: Generalize Metric Normalization Research
description: Live SEC concept research and design decisions for multi-company canonical metric normalization
ms.date: 2026-09-02
ms.topic: reference
---

## Overview

This slice generalizes Feature 1 normalization from Adobe-only to any conventional U.S. operating
company. Concept selection is grounded in live SEC Company Facts inspected for ADBE, V, and COST on
2026-09-02 (fiscal years shown are the three most recent full years available at inspection time).
The findings below drive a minimal, documented override set and one explicit unsupported metric.

## Method

Each candidate concept was checked in `facts["us-gaap"]`, filtering duration facts to full fiscal
years (`fp == "FY"`, ~350-380 day period) and instant facts to fiscal-year-end observations. Recent
values were compared to confirm the concept is the correct, current representation rather than a
stale or deprecated tag. Concept names were never inferred from company name or industry.

## Compatibility matrix (duration metrics, USD unless noted)

| Metric | ADBE concept | V concept | COST concept | Default works? | Override |
|--------|--------------|-----------|--------------|----------------|----------|
| Revenue | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` | `RevenueFromContractWithCustomerExcludingAssessedTax` | Yes (existing preference order resolves each) | none |
| Operating income | `OperatingIncomeLoss` | `OperatingIncomeLoss` | `OperatingIncomeLoss` | Yes | none |
| Net income | `NetIncomeLoss` | `NetIncomeLoss` | `NetIncomeLoss` | Yes | none |
| Operating cash flow | `NetCashProvidedByUsedInOperatingActivities` | same | same | Yes | none |
| Capital expenditures | `PaymentsToAcquirePropertyPlantAndEquipment` | `PaymentsToAcquireProductiveAssets` (2nd preference) | `PaymentsToAcquirePropertyPlantAndEquipment` | Yes (existing 2-concept preference) | none |
| Diluted weighted-avg shares (`shares`) | `WeightedAverageNumberOfDilutedSharesOutstanding` | **absent** | `WeightedAverageNumberOfDilutedSharesOutstanding` | No for V | **UNSUPPORTED for V** |
| Income tax expense | `IncomeTaxExpenseBenefit` | same | same | Yes | none |
| Pretax income | `...BeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` | same | same | Yes | none |
| Share repurchases | `PaymentsForRepurchaseOfCommonStock` | same | same | Yes | none |
| Stock-based compensation | `ShareBasedCompensation` | same | same | Yes | none |
| Dividends paid (tolerant) | absent (no program) | `PaymentsOfDividends` | `PaymentsOfDividendsCommonStock` | Yes (existing preference; tolerant absence) | none |

## Compatibility matrix (instant metrics, USD)

| Metric | ADBE concept | V concept | COST concept | Default works? | Override |
|--------|--------------|-----------|--------------|----------------|----------|
| Cash and equivalents | `CashAndCashEquivalentsAtCarryingValue` | same | same | Yes | none |
| Short-term investments | `ShortTermInvestments` | **absent** | `ShortTermInvestments` | No for V | **tolerant-absent for V** |
| Current debt | `DebtCurrent` | `LongTermDebtCurrent` | `LongTermDebtCurrent` | No for V, COST | V, COST -> `LongTermDebtCurrent` |
| Long-term debt | `LongTermDebt` | `LongTermDebtNoncurrent` | `LongTermDebtNoncurrent` | No for V, COST | V, COST -> `LongTermDebtNoncurrent` |
| Total assets | `Assets` | `Assets` | `Assets` | Yes | none |
| Total equity | `StockholdersEquity` | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` | `StockholdersEquity` | No for V | V -> `...IncludingPortionAttributableToNoncontrollingInterest` |

## Decision: A canonical metric-definition registry with per-company overrides

* **Decision**: Introduce `CanonicalMetricDefinition(name, kind, unit, default_concepts, overrides)`
  in a new `metrics.py`, plus a resolver that returns `overrides.get(ticker, default_concepts)`.
  Overrides fully replace the default preference for a `(metric, ticker)` pair.
* **Rationale**: The spec requires declarative, minimal, per-metric overrides and forbids scattered
  ticker conditionals. A single registry is the one auditable home for company-specific knowledge
  and keeps the selection primitives company-agnostic.
* **Alternatives considered**:
  * *Broaden default preferences instead of overrides*: rejected because it breaks Adobe (see the
    debt and equity decisions below) — Adobe and the other companies have opposite stale tags.
  * *Plugin/registry/config-file system*: rejected as speculative architecture (Constitution VI).

## Decision: Overrides must replace, not append, for debt and equity

* **Decision**: For V and COST, the current-debt, long-term-debt, and (V only) equity overrides
  replace the default concept preference entirely.
* **Rationale**: A naive appended fallback would mis-select stale tags:
  * `LongTermDebt` is present but stale for V (through 2021) and COST (through 2021); their current
    long-term debt is `LongTermDebtNoncurrent`. Appending `LongTermDebtNoncurrent` after
    `LongTermDebt` would still pick the stale `LongTermDebt`.
  * Conversely, Adobe's `LongTermDebtNoncurrent` is stale (through 2009) while `LongTermDebt` is
    current, so making the default prefer `LongTermDebtNoncurrent` would break Adobe.
  * `StockholdersEquity` is stale for V (through 2011); V's current equity is
    `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, while COST and ADBE use
    `StockholdersEquity` currently.
  This opposite-staleness is exactly why per-company replacement overrides are required and why
  clever default reordering cannot work without regressing Adobe.
* **Alternatives considered**: appended fallbacks (rejected as above); most-recent-observation
  auto-selection across concepts (rejected as nondeterministic and prone to mixing concepts).

## Decision: Debt double-count safety

* **Decision**: Canonical total debt stays current interest-bearing debt plus long-term
  interest-bearing debt. For V and COST, `LongTermDebtCurrent + LongTermDebtNoncurrent` is used,
  which by definition partitions total debt into current and noncurrent with no overlap. Adobe keeps
  `DebtCurrent + LongTermDebt`, its validated pairing.
* **Rationale**: `LongTermDebtNoncurrent` excludes the current portion, so pairing it with
  `LongTermDebtCurrent` avoids the double count that pairing a current tag with the all-inclusive
  `LongTermDebt` could cause. Non-debt operating liabilities (accounts payable, general current
  liabilities, settlement obligations, lease liabilities) are never counted.

## Decision: Short-term investments is tolerant-absent, not broadened, for Visa

* **Decision**: Make short-term-investments normalization tolerant of a missing concept (return an
  empty series, contributing zero to cash-plus-short-term-investments), mirroring the existing
  tolerant dividends pattern. Do not map Visa's investment securities into the canonical STI concept.
* **Rationale**: Visa reports no `ShortTermInvestments` concept. Its balance sheet carries large
  investment securities (available-for-sale and other), which are not equivalent to excess corporate
  cash under OwnerLens's existing corporate-liquidity definition. The spec is explicit: do not absorb
  such assets; use a narrow override or omit rather than broaden incorrectly. Treating STI as absent
  keeps Visa cash defined while conservatively excluding non-cash-equivalent securities.
* **Documented limitation**: For Visa, cash-plus-short-term-investments therefore equals cash only,
  which conservatively understates liquid assets and slightly overstates invested capital (hence
  understates ROIC). This is a known, surfaced limitation to revisit in a later slice, not a silent
  approximation.
* **Alternatives considered**: mapping Visa `AvailableForSaleSecuritiesCurrent` or `LongTermInvestments`
  into STI (rejected — economic meaning differs from corporate excess cash); marking Visa
  cash-plus-STI wholly unsupported (rejected — cash itself is cleanly available and useful).

## Decision: Visa diluted weighted-average shares is UNSUPPORTED

* **Decision**: Report Visa diluted weighted-average shares as unsupported (typed
  `ConceptNotFound`), and document that per-share metrics for Visa are therefore unavailable in this
  slice.
* **Rationale**: Visa tags no weighted-average diluted (or basic) share-count concept anywhere in
  `us-gaap`; a broad search returned only option-award and pro-forma EPS concepts. Deriving shares
  from net income divided by diluted EPS would be a fabricated denominator, which the spec forbids.
* **Alternatives considered**: derive from EPS (rejected — fabrication); use a `dei` instant
  share-count (rejected — period-end shares are not a weighted-average and would silently change the
  metric's meaning).

## Decision: Remove the Adobe-only normalization gate

* **Decision**: Remove `ensure_supported_ticker` from the normalization entry points and canonicalize
  the ticker (trim, uppercase) without an allow-list. "Unsupported" arises naturally as a typed
  `ConceptNotFound` when no concept resolves for a company.
* **Rationale**: The spec forbids both the Adobe restriction and a replacement ticker allow-list.
  Unsupported must mean "no trustworthy canonical representation," not "ticker not listed."
* **Alternatives considered**: `SUPPORTED_TICKERS = {ADBE, V, COST}` (explicitly rejected by the
  spec).

## Decision: Preserve separate duration and instant selectors and all existing semantics

* **Decision**: Keep `select_annual_series` and `select_instant_series` distinct and unchanged in
  behavior (fiscal-year derivation from period end, full-year and 52/53-week handling, comparative
  deduplication, explicit ambiguity failures, unit validation). Only the concept preference source
  changes (registry resolution per ticker).
* **Rationale**: These primitives are validated and the spec forbids merging them. The generalization
  is entirely about which concepts feed them.

## Decision: Preserve Adobe selection exactly

* **Decision**: Adobe carries no overrides; its default concept preferences are unchanged, so every
  Adobe series, owner-economics, capital-efficiency, capital-allocation, and Feature 2 output is
  byte-for-byte preserved.
* **Rationale**: FR-016 requires unchanged Adobe results. The registry's Adobe path is the current
  behavior expressed as data.

## Testing approach

Controlled ADBE, V, and COST fixtures drive: registry resolution (default, override, unknown metric,
deterministic ordering); multi-company normalization of every in-scope metric; semantic checks
(duration vs instant, unit, CapEx sign preserved, debt no double count, tolerant STI absence, Visa
diluted-shares unsupported, provenance reports the actual selected concept); and full preservation of
every existing Adobe Feature 1 and Feature 2 test. Live SEC calls are reserved for the optional
coverage report, not the default suite.

---
title: Adobe Operating Income and Margin Research
description: Decisions for operating-income normalization, margin derivation, and shared-code extraction
ms.date: 2026-09-01
ms.topic: reference
---

## Observed Adobe operating-income data shape

A live inspection of Adobe's Company Facts (CIK 0000796343) grounded these decisions. Among the
operating and income concepts, the single top-line operating result is `OperatingIncomeLoss`,
disclosed only in the `USD` unit. Its facts carry the same fields as `Revenues`: `start`, `end`,
`val`, `accn`, `fy`, `fp`, `form`, `filed`, and sometimes `frame`.

The same `fy` pitfall from Slice 1B is present. The full-year period `2022-12-03` to `2023-12-01`
(operating income 6,650,000,000) appears in the 2024, 2025, and 2026 filings with `fy` 2023, 2024,
and 2025 and different accession numbers but the same value. Full-year detection and fiscal-year
derivation must therefore work exactly as they do for revenue.

## Operating-income concept selection

**Decision**: Select operating income from the single-concept preference order
`OperatingIncomeLoss`. Adobe reports its operating result under this one concept in USD.

**Rationale**: `OperatingIncomeLoss` is the standard US-GAAP operating income or loss line and is the
only top-line operating result Adobe tags. A documented preference order keeps the selection explicit
and extensible if a future filer used an alternate tag, while for Adobe it deterministically resolves
to `OperatingIncomeLoss`.

**Alternatives considered**:

* Deriving operating income as revenue minus `OperatingExpenses` or cost lines introduces arithmetic
  across concepts, which the specification forbids without demonstrated necessity, and risks
  definitional drift.
* Mixing `OperatingIncomeLoss` with pre-tax income concepts such as
  `IncomeLossFromContinuingOperationsBeforeIncomeTaxes...` would blend different economic lines.
* Selecting the most recently filed value ignores fiscal-period semantics, exactly the mistake the
  revenue slice already rejected.

## Reuse of the annual selection behavior

**Decision**: Extract the annual selection behavior shared by revenue and operating income into one
small internal primitive, `_annual.py`. It provides full fiscal-year filtering (USD, `fp == FY`,
350-380 day duration), fiscal-year derivation from the period end date, comparative deduplication
keeping earliest-filed provenance, canonical observation provenance, and a preference-ordered concept
selection loop. The concept preference list and the metric-specific typed error classes are injected
by each metric module.

**Rationale**: Live inspection shows the two metrics duplicate this logic exactly. Extracting it now
is duplication-driven, not speculative, and satisfies the architecture objective of finding the
smallest useful reusable primitive. Injecting the concept list and error types keeps each metric's
public exceptions and vocabulary intact while removing the duplicated engine.

**Alternatives considered**:

* Copying the revenue logic into a new operating-income module would duplicate roughly the entire
  selection engine, the precise duplication this slice is meant to resolve.
* Building a general financial-statement normalization framework anticipates out-of-scope metrics and
  is explicitly prohibited.
* Sharing through inheritance from a metric base class adds indirection without reducing the actual
  duplicated logic; plain functions plus injected specifics are smaller and clearer.

## Preserving Slice 1B behavior during refactor

**Decision**: Refactor `revenue.py` to consume `_annual.py` while keeping its public names
(`normalize_annual_revenue`, `AnnualRevenueSeries`, `AnnualRevenueObservation`,
`REVENUE_CONCEPT_PREFERENCE`, and the revenue error classes) and all existing tests unchanged.

**Rationale**: The specification requires preserving Slice 1A and 1B behavior and tests. Keeping the
public surface stable ensures the refactor is internal only. Existing revenue tests act as the
regression guard for the extraction.

**Alternatives considered**:

* Renaming revenue types to shared names would break Slice 1B tests and downstream imports.
* Leaving revenue untouched and duplicating logic in operating income would defeat the extraction
  objective.

## Fiscal-year alignment of the two series

**Decision**: Align revenue and operating income by their derived economic fiscal year, the calendar
year of the period end date used in both slices. Alignment produces per-year rows exposing the
optional revenue observation, the optional operating-income observation, and the optional derived
margin.

**Rationale**: Both metrics already derive the same fiscal-year label from the period end date, so
alignment on that key is consistent and unambiguous. Per-year rows make missing inputs explicit
rather than silently dropped.

**Alternatives considered**:

* Aligning on the raw `fy` field would misalign comparative repeats, reintroducing the Slice 1B bug.
* Aligning by list position assumes both series cover identical years, which is not guaranteed.

## Operating-margin derivation

**Decision**: Compute operating margin as operating income divided by revenue in application code,
producing a derived `OperatingMargin` value distinct from any reported observation. Produce a margin
only for fiscal years where both canonical inputs exist and revenue is non-zero. Represent the margin
as a floating-point ratio. Negative operating income yields a valid negative margin.

**Rationale**: The margin is a calculated ratio, and a distinct type preserves the fact-versus-metric
boundary the constitution requires. Deterministic division of two integer inputs is reproducible.
Restricting output to years with both inputs and non-zero revenue makes omissions explicit and avoids
an invented, infinite, or undefined value.

**Alternatives considered**:

* Trusting an external precomputed margin is prohibited and untraceable.
* Emitting a null, zero, or infinite margin for zero or missing revenue would present a fabricated or
  undefined value as a fact.
* Using `Decimal` adds precision machinery beyond what a display ratio needs; a float ratio is
  deterministic for equal integer inputs and adequate here. This choice is documented so it can be
  revisited if exact decimal reporting becomes a requirement.

## Test strategy

**Decision**: Add `test_operating_income.py` and `test_margin.py` using in-memory fixtures modeled on
the observed Adobe shape, and keep all existing tests. Cover operating-income concept selection,
full-year versus quarterly and year-to-date filtering, identical comparative repeats, ambiguous
distinct values, missing concept, revenue and operating-income alignment by fiscal year, margin math
including a negative operating income, and missing and zero revenue handling.

**Rationale**: Controlled fixtures make the new selection, alignment, and margin rules reproducible
and exercise failure and edge paths deterministically without live calls. Retaining the Slice 1A and
1B suites guards the refactor.

**Alternatives considered**:

* Live-only validation is nondeterministic and cannot reliably reproduce conflicts, missing concepts,
  or zero-revenue edges.
* Testing only the happy path would leave the fact-versus-metric and zero-revenue guarantees
  unverified.

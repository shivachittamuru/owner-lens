---
title: Adobe Annual Revenue Normalization Research
description: Decisions for selecting a canonical annual revenue series from raw SEC Company Facts
ms.date: 2026-09-01
ms.topic: reference
---

## Observed Adobe revenue data shape

A live inspection of Adobe's Company Facts (CIK 0000796343) grounded these decisions. The
`us-gaap` taxonomy contains many revenue-named concepts, but the reported top-line revenue is under
`Revenues`, disclosed only in the `USD` unit. Each fact carries `start`, `end`, `val`, `accn`,
`fy`, `fp`, `form`, `filed`, and sometimes `frame`.

A critical finding: the raw `fy` field is the filing's fiscal year, not the observation period's.
The same full-year period repeats across later 10-K filings as a comparative with the same value but
a different `fy` and `accn`. For example, the FY2023 period `2022-12-03` to `2023-12-01`
(value 19,409,000,000) appears in the 2024, 2025, and 2026 filings with `fy` 2023, 2024, and 2025.
Selection therefore cannot trust `fy` or filing recency; it must derive the fiscal year from the
period end date and dedup by period.

## Revenue concept selection

**Decision**: Choose one revenue concept for the whole series using a documented preference order,
selecting the first concept present that yields at least one qualifying annual observation:
`RevenueFromContractWithCustomerExcludingAssessedTax`, then `Revenues`, then `SalesRevenueNet`. For
Adobe today this resolves to `Revenues`. Do not mix concepts within a single series.

**Rationale**: A fixed preference order is explicit and testable and prefers the modern ASC 606
contract-revenue concept when a filer uses it, while covering Adobe's actual `Revenues` tag. Using a
single concept keeps the canonical series internally consistent and avoids blending differently
defined line items across years.

**Alternatives considered**:

* Selecting the most recently filed value ignores fiscal-period semantics and would pick comparative
  repeats or partial periods.
* Summing segment or product and service revenue concepts introduces aggregation and definitional
  drift that this slice explicitly excludes.
* Merging multiple concepts across years to fill gaps mixes definitions; returning fewer years is
  preferable to a blended series.

## Full fiscal-year observation identification

**Decision**: Qualify an observation as annual when its unit is `USD`, its `fp` is `FY`, and its
period duration from `start` to `end` falls within a full-year tolerance window of 350 to 380 days.
Exclude any observation outside this window.

**Rationale**: Adobe uses a 52-to-53 week fiscal calendar, so annual periods span roughly 363 to 371
days rather than exactly 365. The duration window plus `fp == FY` cleanly separates full-year
observations from quarterly (about 91 days) and year-to-date partial periods (about 182 and 273
days), independent of which form embedded them.

**Alternatives considered**:

* Relying on `form == 10-K` alone would admit year-to-date interim periods disclosed within annual
  filings and exclude valid `10-K/A` amendments.
* Requiring exactly 365 days would wrongly reject Adobe's 52-to-53 week periods.
* Trusting the `frame` field is insufficient because it is calendar-aligned and not present on every
  fact.

## Fiscal-year derivation

**Decision**: Derive each observation's canonical fiscal year from the calendar year of its period
`end` date. Store this derived fiscal year rather than the raw `fy`.

**Rationale**: Adobe's fiscal year ends in late November or early December, so the end date's
calendar year equals the fiscal year label. This makes each full-year period map to exactly one
fiscal year and neutralizes the misleading filing-based `fy` on comparative repeats.

**Alternatives considered**:

* Using the raw `fy` groups comparative repeats under multiple years and breaks the one-per-year
  guarantee.
* Using the period start year would be off by one for a fiscal year that begins in the prior
  calendar year.

## Deterministic duplicate and comparative resolution

**Decision**: Group qualifying observations by derived fiscal year. Within a group, collapse
observations that share the same value into one, and choose the retained provenance deterministically
by earliest `filed`, then lowest `accn`. If a group contains two or more distinct values, raise an
explicit ambiguity failure identifying that fiscal year.

**Rationale**: Identical comparative repeats are the same fact restated, so collapsing them is safe;
preferring the earliest filing keeps the provenance of the original 10-K that first reported the year
as current. Distinct values for one year signal a genuine conflict, such as a restatement, that this
slice must surface rather than silently resolve.

**Alternatives considered**:

* Keeping the latest filing would prefer comparative restatements over the original report without a
  documented reason.
* Averaging or picking the maximum invents a value and violates fail-loudly.
* Treating any repeat as a conflict would fail on ordinary identical comparatives that are not
  actually ambiguous.

## Series windowing and output

**Decision**: Order the resolved per-year observations by fiscal year descending and return up to the
latest five. Return fewer when fewer completed fiscal years qualify. Fail explicitly only when no
concept is usable or when a targeted year is genuinely conflicting.

**Rationale**: This matches the specification's "approximately the latest five completed fiscal
years" and its rule to return fewer rather than invent missing years, while still failing on true
ambiguity.

**Alternatives considered**:

* Padding to exactly five years would fabricate missing observations.
* Failing whenever fewer than five years exist contradicts the specification's allowance for fewer.

## Module boundary and dependencies

**Decision**: Implement a pure, offline `revenue.py` module that accepts the raw Company Facts
mapping and returns the canonical series or raises a typed failure. Use only the standard library.
Keep it independent from `sec.py` transport.

**Rationale**: Normalization is deterministic computation and must stay out of the network layer per
the constitution. A standalone module keeps provider retrieval and metric derivation separated and
testable without live calls.

**Alternatives considered**:

* Extending `sec.py` would couple transport with normalization and blur the provider boundary.
* Adding a generic normalization framework or metric-strategy interface anticipates out-of-scope
  metrics and violates the minimal-slice rule.

## Test strategy

**Decision**: Test with small in-memory Company Facts fixtures modeled on the observed Adobe shape.
Cover the happy path five-year series, identical comparative repeats, quarterly and year-to-date
exclusion, an amended-filing repeat, a genuine conflicting-value failure, a missing-concept failure,
fewer-than-five available years, and non-USD unit exclusion. Assert exact selected values and full
provenance, including the derived fiscal year.

**Rationale**: Controlled fixtures make selection and tie-breaking rules reproducible and let failure
paths be exercised deterministically without depending on live SEC data. A manual live check remains
available through the existing retrieval path but stays outside the default suite.

**Alternatives considered**:

* Live-only tests are nondeterministic and cannot reliably reproduce conflicts or missing concepts.
* A single large recorded Adobe payload would be brittle and obscure which rule each case exercises.

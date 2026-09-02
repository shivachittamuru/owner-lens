---
title: Adobe Core Owner Economics Research
description: Verified Adobe concepts, CapEx sign, diluted-share semantics, and derivation decisions
ms.date: 2026-09-01
ms.topic: reference
---

## Verified Adobe concepts and shapes

A live inspection of Adobe's Company Facts (CIK 0000796343) grounded every decision below. Values
quoted are from the current payload and are used only to verify shape and semantics; OwnerLens never
hard-codes them.

| Reported fact          | Concept                                              | Unit     | Shape                       |
|------------------------|------------------------------------------------------|----------|-----------------------------|
| Net income             | `NetIncomeLoss`                                       | `USD`    | Duration full-year FY facts |
| Operating cash flow    | `NetCashProvidedByUsedInOperatingActivities`         | `USD`    | Duration full-year FY facts |
| Capital expenditures   | `PaymentsToAcquirePropertyPlantAndEquipment`         | `USD`    | Duration full-year FY facts |
| Diluted shares         | `WeightedAverageNumberOfDilutedSharesOutstanding`    | `shares` | Duration full-year FY facts |

All four exhibit the same `fy` comparative-repeat behavior already handled by `_annual`: a full-year
period reappears across later 10-K filings with the same value and a different `fy` and accession.
Fiscal-year derivation from the period end date and earliest-filed deduplication therefore apply
unchanged.

## Concept preference orders

**Decision**: Use single-concept preference orders grounded in what Adobe reports, with a documented
fallback for CapEx:

* Net income: `NetIncomeLoss`
* Operating cash flow: `NetCashProvidedByUsedInOperatingActivities`
* Capital expenditures: `PaymentsToAcquirePropertyPlantAndEquipment`, then
  `PaymentsToAcquireProductiveAssets`
* Diluted shares: `WeightedAverageNumberOfDilutedSharesOutstanding`

**Rationale**: Each first choice is the standard US-GAAP line Adobe actually tags. The CapEx fallback
covers filers that report productive-asset purchases under the alternate tag, selected only if the
primary is absent, never mixed within one series.

**Alternatives considered**:

* `ProfitLoss` for net income is absent for Adobe and would include noncontrolling interest; rejected.
* `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` is absent for Adobe; the total
  operating-activities concept is correct here.
* Summing multiple CapEx concepts introduces aggregation across differently defined lines and is
  excluded unless research proves it necessary.

## Capital expenditure sign

**Decision**: Adobe reports `PaymentsToAcquirePropertyPlantAndEquipment` as a positive cash outflow
amount (for example 179,000,000 for the latest year). The reported observation preserves this source
value unchanged. Free cash flow uses the positive magnitude, computing
`FCF = operating_cash_flow - abs(capex)`.

**Rationale**: Verifying the sign against real facts prevents a silent double-negative or sign error.
Using the absolute magnitude at the point of derivation guarantees `FCF = OCF - CapEx` with a
positive expenditure, while keeping the stored reported value faithful to the source for provenance.
For Adobe the magnitude equals the source value, so the guard is defensive rather than corrective.

**Alternatives considered**:

* Assuming CapEx is negative and adding it would be wrong for Adobe and would silently inflate FCF.
* Mutating the stored reported value to a normalized sign would break provenance fidelity; the
  canonicalization belongs in the derivation step.

## Diluted-share semantics and units

**Decision**: Use `WeightedAverageNumberOfDilutedSharesOutstanding` in the `shares` unit. The value
is a full-count weighted-average for the fiscal year (for example 427,000,000), not a scaled or
point-in-time figure. Preserve the `shares` unit in provenance and use the value directly for
per-share economics.

**Rationale**: This concept is the weighted-average diluted share count used for diluted per-share
figures. It is a duration fact spanning the fiscal year, unlike the instant
`CommonStockSharesOutstanding`, which has no start date and reflects point-in-time shares. The unit is
a raw share count, so no scaling is applied; the unit is retained explicitly for traceability.

**Alternatives considered**:

* `CommonStockSharesOutstanding` is an instant, point-in-time measure and would misstate per-share
  economics; explicitly rejected.
* `WeightedAverageNumberOfSharesOutstandingBasic` is basic, not diluted; rejected for diluted
  per-share metrics.

## Extending the shared primitive

**Decision**: Add a single `unit` parameter to the `_annual` selection engine, defaulting to `USD`.
Value metrics pass `USD`; diluted shares pass `shares`. No other engine change is required.

**Rationale**: Net income, operating cash flow, and CapEx match the existing USD duration-fact path
exactly. The only concrete difference discovered is the share unit. A single additive parameter is
the minimal extension that supports it, satisfying the rule to extend shared logic only for a
demonstrated difference.

**Alternatives considered**:

* Hard-coding a second shares path would duplicate the engine.
* Making the engine unit-agnostic by scanning all units risks selecting an unintended unit; an
  explicit per-metric unit is safer and documented.

## Generic reported-metric normalization

**Decision**: Introduce one generic `normalize_annual_metric(raw_facts, spec, *, ticker, max_years)`
driven by a small `MetricSpec` (metric name, concept preference, unit), returning a generic
`AnnualSeries`. Provide thin public functions `normalize_net_income`,
`normalize_operating_cash_flow`, `normalize_capital_expenditures`, and `normalize_diluted_shares`.
Use shared generic `ConceptNotFoundError` and `AmbiguousValueError` that name the metric.

**Rationale**: Slices 1B and 1C each wrote a metric-specific wrapper and error pair. Repeating that
for four more metrics is the duplication this slice is meant to expose. With six concrete metrics, a
single spec-driven normalizer plus shared generic errors is the abstraction that survives. Revenue
and operating income keep their existing modules and error types to preserve their tests; the
research records that they can converge to the generic form later without behavior change.

**Alternatives considered**:

* Four more per-metric wrapper modules would duplicate roughly the same code four times.
* A full financial-statement framework anticipates out-of-scope metrics and is prohibited.
* Refactoring revenue and operating income now would risk their public error contracts and their
  passing tests for no functional gain in this slice.

## Derived owner-economics metrics

**Decision**: Derive per fiscal year, aligning inputs by economic fiscal year:

* Net margin = net income / revenue
* Free cash flow = operating cash flow - abs(capex)
* FCF margin = free cash flow / revenue
* FCF per diluted share = free cash flow / diluted weighted-average shares

Represent ratios as floats and free cash flow as an integer currency amount. Produce each metric only
when its inputs exist and its denominator is non-zero; otherwise omit it explicitly. Negative net
income or free cash flow is valid and never treated as malformed.

**Rationale**: These are calculated ratios and sums, kept in derived types distinct from reported
facts. Deterministic arithmetic over aligned integer inputs is reproducible. Explicit omission on
missing inputs or zero denominators upholds the fail-loudly principle without inventing values.

**Alternatives considered**:

* Sourcing any of these from an external precomputed field is prohibited and untraceable.
* Emitting zero, null, or infinite for a missing input or zero denominator would present a fabricated
  or undefined value as a fact.

## Adjacent-year growth

**Decision**: Compute FCF growth, FCF-per-share growth, and diluted-share growth as
`(current - prior) / prior` for adjacent completed fiscal years, where the prior year is the
immediately preceding fiscal year and the prior value is present and non-zero. Omit growth otherwise,
including for the earliest available year.

**Rationale**: Adjacent-year growth reflects real annual change and must not compare non-consecutive
years or divide by a missing or zero base. Explicit omission makes gaps visible rather than silently
imputed.

**Alternatives considered**:

* Comparing to the nearest available prior year regardless of adjacency would misstate annual growth
  across a gap year.
* Emitting a growth of zero or null where no valid base exists would fabricate a comparison.

## Test strategy

**Decision**: Add `test_reported.py` and `test_owner_economics.py` using in-memory fixtures modeled on
the verified Adobe shapes, and keep all existing tests. Cover concept selection per metric, the
`shares` unit path, full-year versus quarterly and year-to-date filtering, comparative repeats,
ambiguity, CapEx positive-magnitude behavior, diluted-share versus shares-outstanding semantics,
missing years, fiscal-year alignment across metrics, net margin, FCF, FCF margin, FCF per share, the
three growth metrics, and zero or missing denominator behavior.

**Rationale**: Controlled fixtures make the new selection, unit, alignment, derivation, and growth
rules reproducible and exercise failure and edge paths deterministically without live calls.
Retaining the Slice 1A through 1C suites guards the primitive extension.

**Alternatives considered**:

* Live-only validation is nondeterministic and cannot reliably reproduce conflicts, missing concepts,
  zero denominators, or the earliest-year growth omission.

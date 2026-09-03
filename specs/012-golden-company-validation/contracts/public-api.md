---
title: Golden-Company Coverage Public API Contract
description: Library contract for graceful degradation and the read-only coverage reporter
ms.date: 2026-09-03
ms.topic: reference
---

## Scope

This slice hardens the existing pipeline for honest partial coverage and adds a small read-only
coverage reporter. It introduces no new analytical feature. Existing Feature 1 and Feature 2 entry
points keep their signatures; the only behavioral change is graceful degradation when a required
input is unsupported.

## Graceful degradation

### Owner economics tolerates unsupported diluted shares

```text
owner_economics_from_facts(raw_facts, *, ticker, max_years=5) -> tuple[OwnerEconomicsRow, ...]
```

Contract change:

* When weighted-average diluted shares are unsupported (`normalize_diluted_shares` raises
  `ConceptNotFoundError`), the entry point substitutes an empty diluted-share series and continues.
* Resulting rows have `diluted_shares`, `fcf_per_share`, `fcf_per_share_growth`, and
  `diluted_share_growth` equal to `None`; all non-per-share fields are populated as before.
* The substitute is an empty (unavailable) series, never a fabricated or point-in-time value.
* Companies that report diluted shares (Adobe, Costco) are unaffected; their output is unchanged.

### Downstream Feature 2 entry points

`economic_value_from_facts`, `compounding_views_from_facts`, `capital_allocation_from_facts`, and
`economic_value_summary_from_facts` keep their signatures and now complete for a company with
unsupported diluted shares, reporting per-share-dependent classifications as `INSUFFICIENT_DATA`
while non-per-share evidence remains available. Any additional `None`-per-share handling is added
only where live re-validation exposes a real crash.

## Coverage reporter

### States

```text
MetricCoverage: AVAILABLE | STRUCTURALLY_ABSENT | UNSUPPORTED
LayerCoverage:  AVAILABLE | PARTIAL | INSUFFICIENT_DATA | UNAVAILABLE
```

### Per-company coverage

```text
company_coverage(raw_facts, *, ticker, max_years=5) -> CompanyCoverage
```

Contract:

1. Probe each canonical input via its normalizer: a raise records `UNSUPPORTED`, an empty tolerant
   series records `STRUCTURALLY_ABSENT`, and a populated series records `AVAILABLE`.
2. Run each analytical layer via its existing entry point and record `AVAILABLE`, `PARTIAL`,
   `INSUFFICIENT_DATA`, or `UNAVAILABLE`, with a reason and blocking input for any non-available
   layer.
3. Perform no network access beyond the caller-supplied facts; be deterministic.

### Cross-company report

```text
format_coverage_report(coverages: Sequence[CompanyCoverage]) -> str
```

Contract: render a deterministic grid of companies by layers, with a reason for every non-available
cell. It is a validation artifact, not a ranking or scoring feature.

### Company-level output

```text
company_output(coverage, raw_facts, *, ticker) -> str
```

Contract: for a full-coverage company, render the compact Feature 2D economic-value summary; for a
partial-coverage company, render available evidence, unavailable layers, the exact missing or
unsupported inputs, and an explicit insufficient-data state, with no fabricated classification. Exact
function names may differ if a cleaner design emerges; the contract is the behavior above.

## Failure and honesty guarantees

* No entry point fabricates or substitutes a value to complete a layer.
* Unsupported, structurally absent, reported zero, and insufficient outcomes stay distinct.
* Adobe results and provenance are unchanged.
* No threshold value changes unless a genuine, economically general bug is found and documented.

## Regression contract

Every existing Feature 1 and Feature 2 Adobe output, classification, value, and provenance is
preserved, and all existing tests continue to pass.

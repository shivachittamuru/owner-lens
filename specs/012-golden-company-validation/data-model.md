---
title: Golden-Company Validation Data Model
description: Coverage states, per-company coverage, minimum-data contracts, and the cross-company report
ms.date: 2026-09-03
ms.topic: reference
---

## Metric Coverage

The coverage state of one canonical input metric for one company.

### States

| State | Meaning | How detected |
|-------|---------|--------------|
| `AVAILABLE` | The metric normalized to a non-empty series | Normalizer returns observations |
| `STRUCTURALLY_ABSENT` | The metric is tolerantly absent (no concept; e.g. Adobe dividends, Visa short-term investments) | Tolerant normalizer returns an empty series |
| `UNSUPPORTED` | No trustworthy concept resolves (e.g. Visa diluted weighted-average shares) | Normalizer raises `ConceptNotFoundError` |

Notes: a reported value of `0` is `AVAILABLE` (a real observation), never absence. `AVAILABLE`,
`STRUCTURALLY_ABSENT`, `UNSUPPORTED`, reported zero, and insufficient history remain distinct.

## Layer Coverage

The coverage state of one analytical layer for one company.

### Fields

| Field | Type | Meaning |
|-------|------|---------|
| `layer` | string | Analytical layer name (owner_economics, capital_efficiency, economic_value, compounding, capital_allocation, economic_summary) |
| `state` | enum | `AVAILABLE`, `PARTIAL`, `INSUFFICIENT_DATA`, or `UNAVAILABLE` |
| `reason` | string or none | Why the layer is not fully available |
| `blocking_input` | string or none | The canonical input whose absence or unsupport limited the layer |

### State meaning

| State | Meaning |
|-------|---------|
| `AVAILABLE` | The layer produced a complete result |
| `PARTIAL` | The layer produced a result but some sub-analyses are insufficient (for example, per-share fields unavailable) |
| `INSUFFICIENT_DATA` | The layer ran but a required input made its primary classification insufficient |
| `UNAVAILABLE` | The layer could not run because a required input is unsupported or absent |

## Company Coverage

The complete coverage picture for one golden company.

### Fields

| Field | Type | Meaning |
|-------|------|---------|
| `ticker` | string | Canonical company ticker |
| `inputs` | map of metric name to Metric Coverage | Per-input coverage states |
| `layers` | ordered map of layer name to Layer Coverage | Per-layer coverage states with reasons |

### Rules

* Coverage is derived deterministically by probing the existing normalizers and running the existing
  analytical entry points; it performs no network access of its own beyond the caller-supplied facts.
* A layer's `blocking_input` must name an actual input recorded as `STRUCTURALLY_ABSENT` or
  `UNSUPPORTED`, never an invented reason.
* The representation adds no orchestration; it records outcomes of the existing pipeline.

## Minimum-Data Contract

The inputs an analysis requires for its result to be economically meaningful.

| Analysis | Required inputs | Behavior when missing |
|----------|-----------------|-----------------------|
| FCF per share and per-share classification | weighted-average diluted shares | `INSUFFICIENT_DATA`; never substitute point-in-time shares |
| Return on invested capital | operating income, income tax, pretax income, invested capital | omit the metric when a baseline is missing (existing behavior) |
| Per-share compounding | per-share FCF endpoints | `INSUFFICIENT_DATA` |
| Revenue and FCF compounding | respective series endpoints | `INSUFFICIENT_DATA` when endpoints missing |
| Capital allocation | free cash flow and repurchases | dividends optional (structurally absent allowed); buyback effectiveness `INSUFFICIENT` without a diluted-share change |

## Cross-Company Coverage Report

The deterministic validation grid across the golden companies.

### Rules

* Rows are the golden companies; columns are the analytical layers.
* Each cell shows the layer state; every non-`AVAILABLE` cell has an accompanying reason naming the
  blocking input.
* The report is deterministic and reproducible from the same facts.
* It is a validation artifact, not a comparison, ranking, or scoring feature.

## Company-Level Output

The most complete honest result per company.

### Rules

* A full-coverage company shows its compact economic-value summary (Feature 2D).
* A partial-coverage company shows available economic evidence, the unavailable layers, the exact
  missing or unsupported inputs, and an explicit insufficient-data state.
* No company-level output presents a fabricated classification.

## State transitions (per layer, per company)

```text
Requested
  -> UNAVAILABLE          (a required input is unsupported/absent and no honest result is possible)
  -> INSUFFICIENT_DATA    (ran, but a required input made the primary classification insufficient)
  -> PARTIAL              (ran; some sub-analyses insufficient, others available)
  -> AVAILABLE            (complete result)
```

Adobe reaches `AVAILABLE` for every layer, unchanged from before this slice.

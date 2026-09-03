---
title: Generalize Metric Normalization Data Model
description: Canonical metric definitions, overrides, resolution, and coverage outcomes for multi-company normalization
ms.date: 2026-09-02
ms.topic: reference
---

## Canonical Metric Definition

A company-independent description of one economic concept OwnerLens uses.

### Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `name` | string | Yes | Canonical metric name (for example, `revenue`, `current_debt`) |
| `kind` | enum {duration, instant} | Yes | Which selection primitive applies |
| `unit` | string | Yes | Expected unit (`USD`, or `shares` for diluted shares) |
| `default_concepts` | ordered tuple of strings | Yes | Default source-concept preference, tried in order |
| `overrides` | map of ticker to ordered tuple of strings | No | Per-company concept preference that fully replaces the default |

### Validation rules

* `default_concepts` is non-empty and ordered by preference.
* Each override value fully replaces the default for that ticker; it does not append.
* `kind` selects the duration or the instant primitive and never both.
* Definitions exist only for metrics OwnerLens currently uses; no general taxonomy is modeled.
* Adobe carries no overrides for any in-scope metric, preserving current selection.

### In-scope metrics

Duration: revenue, operating income, net income, operating cash flow, capital expenditures, diluted
weighted-average shares, income tax expense, pretax income, share repurchases, stock-based
compensation, dividends paid. Instant: cash, short-term investments, current debt, long-term debt,
total assets, total equity. Concept values and overrides are recorded in [research.md](research.md).

## Metric Resolution

Turns a canonical metric plus a ticker into the concrete concept preference consumed by the existing
normalization primitive.

### Rules

* Resolution returns the ticker override when present, otherwise the default preference.
* The ticker is canonicalized (trimmed, uppercased); no allow-list gates resolution.
* Resolution is deterministic: the same metric and ticker always yield the same ordered preference.
* Resolution never performs network access and never inspects company facts.

## Normalized Observation and Series

Unchanged in shape from Feature 1; only the range of companies and selected concepts widens.

### Series fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `metric` | string | Yes | Canonical metric name |
| `ticker` | string | Yes | Canonicalized company ticker |
| `concept` | string | Yes | Actual selected source concept (provenance) |
| `unit` | string | Yes | Observation unit |
| `observations` | ordered tuple | Yes | Canonical annual values with full SEC provenance |

### Rules

* `concept` records the concept actually selected for this company, which may be an override.
* Each observation retains its source concept, unit, fiscal year, period, form, filed date, and
  accession, exactly as in Feature 1.
* Canonicalization never overwrites or hides the source concept.

## Metric Coverage Outcome

The per-company, per-metric classification of a normalization attempt.

### Categories

| Category | Trigger | Result |
|----------|---------|--------|
| Normalized | A default or override concept resolves with qualifying observations | Canonical series with provenance |
| Non-applicable / absent | The concept is structurally absent for a tolerant metric (dividends; short-term investments) | Empty series contributing zero, distinct from a reported zero |
| Unsupported | No trustworthy concept resolves (for example, Visa diluted weighted-average shares) | Typed `ConceptNotFound`; never a fabricated value |
| Ambiguous | A fiscal year has conflicting distinct full-year values | Typed ambiguity failure (unchanged from Feature 1) |

### Rules

* Absence and unsupported are never represented as a silent zero.
* A tolerant-absent metric returns an empty series so downstream sums treat it as zero contribution
  while preserving the distinction from a reported zero.
* An unsupported metric fails explicitly and prevents any dependent per-company output that requires
  it (for example, Visa per-share metrics).

## Relationships

* One Canonical Metric Definition produces, per ticker, exactly one resolved concept preference.
* One resolved concept preference feeds exactly one selection primitive (duration or instant).
* One normalization attempt yields exactly one Metric Coverage Outcome.
* Adobe definitions produce the same resolved preferences and outcomes as before this slice.

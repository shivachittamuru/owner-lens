---
title: "Data Model: Persistence Model and Storage Boundary"
description: Relational schema, record dataclasses, keys, and coverage representation for OwnerLens Slice 4A local persistence
ms.date: 2026-09-04
ms.topic: reference
---

## Overview

This model defines the smallest useful relational schema that stores OwnerLens **outputs** with full
provenance, explicit coverage semantics, historical snapshots, and idempotency. Seven conceptual
entities map to seven physical tables plus a `schema_meta` key/value table. Storage types follow
research Decision 2: `INTEGER` for exact money/share values and fiscal years, `REAL` for derived
ratios (IEEE-754 floating point — approximate, not exact decimal; validated with tolerances), `TEXT`
for dates (ISO-8601), enum state names, concepts, and identifiers. SQL `NULL` is used
only for genuinely optional fields and never as the business meaning of an unavailable value.

Each persisted fact, metric, analysis, and coverage row references a `source_snapshot`, so multiple
historical snapshots for a company coexist and no single mutable "latest" row is used (FR-015).

## Entity summary

| Entity | Table | Purpose | Natural key |
|--------|-------|---------|-------------|
| Company | `companies` | Stable SEC entity; CIK-anchored identity | `cik` |
| Source Snapshot | `source_snapshots` | A fetched Company Facts payload event | (`cik`, `source_provider`, `source_type`, `content_hash`) |
| Reported Fact | `reported_facts` | One canonical normalized observation + provenance | (`snapshot_id`, `canonical_metric`, `concept`, `fiscal_year`, `period_end`) |
| Derived Metric | `derived_metrics` | One deterministic calculated value | (`snapshot_id`, `metric_name`, `fiscal_year`, `calculation_version`) |
| Analysis Result | `analysis_results` | One Feature 2 output + classification | (`snapshot_id`, `analysis_type`, `analysis_period`, `analysis_rule_version`) |
| Analysis Driver | `analysis_drivers` | Ordered reason code for an analysis result | (`analysis_result_id`, `position`) |
| Coverage Result | `coverage_results` | Explicit coverage state per input/layer | (`snapshot_id`, `subject_kind`, `subject`) |
| Schema metadata | `schema_meta` | Store-level version(s) | `key` |

## Tables

### `companies`

Anchors identity on CIK; ticker and company name are mutable current attributes (FR-004, FR-005).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `cik` | TEXT | no | Zero-padded 10-digit CIK; `UNIQUE` |
| `ticker` | TEXT | no | Current ticker (uppercase) |
| `company_name` | TEXT | no | Current company name |
| `updated_at` | TEXT | no | ISO-8601 timestamp of last upsert |

Uniqueness: `UNIQUE(cik)`. UPSERT updates `ticker`, `company_name`, `updated_at` on conflict so
historical ticker/name changes do not create duplicate companies.

### `source_snapshots`

A fetched SEC Company Facts payload event; references raw storage, never embeds it (FR-006, FR-007).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `company_id` | INTEGER FK→companies.id | no | Owning company |
| `source_provider` | TEXT | no | e.g. `sec` |
| `source_type` | TEXT | no | e.g. `company_facts` |
| `fetched_at` | TEXT | no | ISO-8601 fetch timestamp |
| `source_uri` | TEXT | no | Source URI or logical source identifier |
| `content_hash` | TEXT | no | SHA-256 of the raw payload |
| `raw_object_ref` | TEXT | yes | Filesystem path/key of stored raw payload; NULL if not stored |
| `processing_status` | TEXT | yes | Optional status (e.g. `analyzed`); NULL if unused |

Uniqueness: `UNIQUE(company_id, source_provider, source_type, content_hash)`. Same payload → same
snapshot (idempotent); a distinct payload → a new snapshot (history preserved).

### `reported_facts`

Long-form canonical observations with full SEC provenance (FR-008, FR-009). Preserves the distinction
between canonical metric (`revenue`) and source concept (`SalesRevenueNet`). A genuine reported zero is
a present row with `value = 0`; an unavailable metric has no row (its reason lives in
`coverage_results`).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `company_id` | INTEGER FK→companies.id | no | Company |
| `snapshot_id` | INTEGER FK→source_snapshots.id | no | Producing snapshot |
| `canonical_metric` | TEXT | no | e.g. `revenue`, `operating_cash_flow` |
| `value` | INTEGER | no | Exact reported value (money or shares) |
| `unit` | TEXT | no | e.g. `USD`, `shares` |
| `fact_kind` | TEXT | no | `duration` or `instant` |
| `fiscal_year` | INTEGER | no | Economic fiscal year (from period end) |
| `period_start` | TEXT | yes | ISO date; NULL for instant facts |
| `period_end` | TEXT | no | ISO date |
| `concept` | TEXT | no | Source XBRL concept/tag |
| `form` | TEXT | no | e.g. `10-K` |
| `filed` | TEXT | no | ISO filing date |
| `accession` | TEXT | no | Accession number |

Uniqueness: `UNIQUE(snapshot_id, canonical_metric, concept, fiscal_year, period_end)`.

Source: `AnnualObservation` fields (`concept`, `unit`, `fiscal_year`, `fiscal_period`, `period_start`,
`period_end`, `form`, `filed`, `accession`, `value`) plus the canonical metric name from the
`AnnualSeries.metric` that produced it. `fact_kind` derives from whether the observation carries a
`period_start` (duration) or not (instant).

### `derived_metrics`

Deterministic calculated values, stored separately from reported facts (FR-010, FR-011). Ratios/growthare `REAL`; count/currency derived values (e.g. `free_cash_flow`) are `INTEGER`.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `company_id` | INTEGER FK→companies.id | no | Company |
| `snapshot_id` | INTEGER FK→source_snapshots.id | no | Producing snapshot |
| `metric_name` | TEXT | no | e.g. `fcf_per_share`, `roic`, `fcf_margin`, `net_cash` |
| `fiscal_year` | INTEGER | no | Period scope (fiscal year) |
| `value_real` | REAL | yes | Value when the metric is a ratio/growth/float (approximate; tolerance-tested) |
| `value_int` | INTEGER | yes | Value when the metric is an exact currency/share integer |
| `unit` | TEXT | yes | Unit or semantic type (e.g. `USD`, `ratio`, `per_share`) |
| `calculation_version` | TEXT | no | Definition version (default constant this slice); part of the natural key |
| `computed_at` | TEXT | no | ISO-8601 timestamp |

Exactly one of `value_real` / `value_int` is populated per row, chosen by the metric's semantic type
(documented per metric); the other is `NULL` as an optional-storage field, not as business meaning.
Lineage to the canonical input period is the (`company_id`, `snapshot_id`, `fiscal_year`) linkage;
raw SEC provenance is not duplicated here (FR-011).

Uniqueness: `UNIQUE(snapshot_id, metric_name, fiscal_year, calculation_version)`.

### `analysis_results`

Higher-level Feature 2 outputs, separate from facts and simple metrics (FR-012, FR-013).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `company_id` | INTEGER FK→companies.id | no | Company |
| `snapshot_id` | INTEGER FK→source_snapshots.id | no | Producing snapshot |
| `analysis_type` | TEXT | no | `annual_snapshot` \| `compounding` \| `capital_allocation` \| `economic_value_summary` |
| `analysis_period` | TEXT | no | Fiscal year (annual) or period label (e.g. `FY2021-FY2025`) |
| `classification` | TEXT | no | Enum name (e.g. `IMPROVING`, `STRONGLY_COMPOUNDING`, `OWNER_FRIENDLY`, `INSUFFICIENT_DATA`) |
| `analysis_rule_version` | TEXT | no | Rule-set version (default constant this slice) |
| `computed_at` | TEXT | no | ISO-8601 timestamp |

Uniqueness: `UNIQUE(snapshot_id, analysis_type, analysis_period, analysis_rule_version)`. No free-form
interpretive text is stored (FR-013).

### `analysis_drivers`

Ordered, structured reason codes belonging to an analysis result (FR-013). Order is preserved via an
explicit `position`.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `analysis_result_id` | INTEGER FK→analysis_results.id | no | Owning analysis result |
| `position` | INTEGER | no | 0-based order as emitted by the analysis layer |
| `code` | TEXT | no | Driver enum name / reason code |
| `category` | TEXT | yes | Optional grouping (e.g. `positive` \| `watch` \| `negative`) |

Uniqueness: `UNIQUE(analysis_result_id, position)`. Retrieval orders by `position` to preserve driver
order (US1 AS-4).

### `coverage_results`

Explicit coverage state per input metric or analytical layer (FR-014). Never `NULL` for the state.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | INTEGER PK | no | Surrogate key |
| `company_id` | INTEGER FK→companies.id | no | Company |
| `snapshot_id` | INTEGER FK→source_snapshots.id | no | Producing snapshot |
| `subject_kind` | TEXT | no | `input` (MetricCoverage) or `layer` (LayerCoverage) |
| `subject` | TEXT | no | Input metric name or layer name |
| `state` | TEXT | no | `AVAILABLE` \| `STRUCTURALLY_ABSENT` \| `UNSUPPORTED` \| `INSUFFICIENT_DATA` \| `PARTIAL` \| `UNAVAILABLE` |
| `reason` | TEXT | yes | Reason (e.g. `weighted-average diluted shares unsupported`) |
| `blocking_input` | TEXT | yes | Blocking input for a non-available layer |

Uniqueness: `UNIQUE(snapshot_id, subject_kind, subject)`. `state` stores the exact enum names from
`MetricCoverage`/`LayerCoverage` (`coverage.py`); `PARTIAL`/`UNAVAILABLE` apply only to `layer`
subjects. Reported zero is **not** a coverage row — it is a real `reported_facts` value.

### `schema_meta`

Store-level version awareness (FR-018).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `key` | TEXT PK | no | e.g. `schema_version` |
| `value` | TEXT | no | e.g. `1` |

On open, the store reads `schema_version`; a mismatch with the code's expected version raises
`SchemaVersionError`. Initialization inserts the row only if absent (safe repeat-init).

## Record dataclasses (`persistence/records.py`)

Plain frozen dataclasses mirror the tables and carry no behavior. Illustrative shapes:

* `CompanyRecord(cik, ticker, company_name)`
* `SourceSnapshotRecord(cik, source_provider, source_type, fetched_at, source_uri, content_hash,
  raw_object_ref=None, processing_status=None)`
* `ReportedFactRecord(cik, canonical_metric, value, unit, fact_kind, fiscal_year, period_end,
  concept, form, filed, accession, period_start=None)`
* `DerivedMetricRecord(cik, metric_name, fiscal_year, value_int=None, value_real=None, unit=None,
  calculation_version=DEFAULT_CALCULATION_VERSION, computed_at=...)`
* `AnalysisResultRecord(cik, analysis_type, analysis_period, classification, drivers: tuple[...],
  analysis_rule_version=DEFAULT_ANALYSIS_RULE_VERSION, computed_at=...)`
* `AnalysisDriverRecord(position, code, category=None)`
* `CoverageResultRecord(cik, subject_kind, subject, state, reason=None, blocking_input=None)`

Values on records use the same Python types as the domain (`int` money/shares, `float` ratios) so
adapters do no lossy conversion.

## Relationships

```text
companies 1──* source_snapshots
companies 1──* reported_facts        source_snapshots 1──* reported_facts
companies 1──* derived_metrics       source_snapshots 1──* derived_metrics
companies 1──* analysis_results      source_snapshots 1──* analysis_results
analysis_results 1──* analysis_drivers
companies 1──* coverage_results      source_snapshots 1──* coverage_results
```

`snapshot_id` on every dependent row is what makes the model historical rather than "one mutable row
per company" (FR-015). "Latest" queries select the most recent applicable snapshot per company.

## Validation rules (from requirements)

* Monetary/share values are stored as `INTEGER` and round-trip exactly with no rounding (FR-017).
  Ratios are stored as `REAL` (IEEE-754 floating point): they preserve practical analytical
  precision, not a bit-perfect decimal representation, and are validated with tolerances.
* `fact_kind ∈ {duration, instant}`; `period_start` is `NULL` iff `fact_kind = instant`.
* Coverage `state` is always a non-NULL enum name; the four spec states plus layer-only
  `PARTIAL`/`UNAVAILABLE` are the allowed values (FR-014).
* Reported zero is representable and distinct from absence (SC-003).
* All uniqueness constraints above enforce idempotency; identical repeats are UPSERT no-ops (FR-016).
* Canonical metric name and source concept are stored in separate columns (FR-009).

## State and history semantics

* No row is mutated to represent a new fiscal-period reality; new realities arrive as new snapshots.
* A later snapshot that restates an earlier fiscal year produces a new `reported_facts` row under the
  new `snapshot_id`; both coexist, enabling future restatement analysis without implementing it now.
* Whether a classification changed due to data or rules is answerable by comparing `snapshot_id`
  (data) and `analysis_rule_version` (rules) across `analysis_results` rows.
* Version-context invariant: *same company + same source content hash + same calculation/analysis-rule
  version* is an idempotent repeat (UPSERT no-op), while *same source snapshot + newer
  calculation/analysis-rule version* produces a new derived-metric/analysis-result row that coexists
  with the prior one (the version is part of the natural key). This is what lets a later ROIC or
  Feature 2 rule change be recorded without overwriting earlier results.

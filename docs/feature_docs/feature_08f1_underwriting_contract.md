---
title: "OwnerLens canonical underwriting contract"
description: "The boundary between automatic evidence, investor beliefs and reproducible calculations."
---

## Ownership and semantics

OwnerLens supplies evidence. You author or approve beliefs. OwnerLens calculates
outcomes; neither captured evidence nor calculated attractiveness is investment truth.

| Category | Owner | Contents |
| --- | --- | --- |
| FACT | OwnerLens | Security identity, actual creation/as-of time, frozen EOD price/date, starting annual revenue, margins, FCF, diluted shares, FCF/share, net cash/debt, ROIC and source provenance |
| EXPECTATION | OwnerLens | Captured annual/quarterly analyst revenue and EPS estimates, targets, ranges, counts, retrieval times and raw snapshot provenance |
| ASSUMPTION | Investor | Exactly BEAR, BASE and BULL: revenue CAGR, year-five FCF margin, share CAGR, terminal equity FCF multiple, narrative and optional key dependency |
| JUDGMENT | Investor | Three to five business drivers, evidence interpretations, disagreement rationales, scenario probabilities/rationale, thesis, investor hurdle |
| CALCULATION | OwnerLens | Historical base-rate transformations, scenario valuation/CAGR, sensitivities, variant deltas, expected terminal value/CAGR, hurdle spread and conditional classification |

Historical observations are evidence; growth and range transformations remain
`CALCULATION`. Existing starting metrics marked `FACT` retain their explicit
`basis=CALCULATION` and formula when derived. No category is silently relabeled.
Supporting/disconfirming items retain their own category: putting an observation
in a JUDGMENT-owned authoring section does not convert it into judgment or certify
it as fact. SEC remains authoritative for filings; frozen FMP evidence is isolated.

## Minimal authoring surface

Use the [illustrative ADBE authoring example](../examples/adbe_consolidated_underwriting.sample.json):

The primary human entry point is now
[Company-page authoring](feature_08f4_underwriting_authoring.md).
It constructs this same v2 contract; JSON remains available for import/export
and CLI workflows.

```text
authoring_version: 2
assumptions [ASSUMPTION]
  scenarios: BEAR / BASE / BULL assumptions
judgments [JUDGMENT]
  business_drivers: 3-5 statements
  supporting_evidence / disconfirming_evidence
  variant_rationales: optional per-driver reasons
  probability_distribution: separate BEAR / BASE / BULL weights and rationale
  investor_policy: required_return and optional rationale
  thesis: dependencies, breakers, uncertainty, variable, next evidence
```

You do not enter company identity, price, starting financials, estimates, their
provenance or calculated outputs. The ticker is supplied to the existing create
command; as-of/creation time is captured automatically. The new format rejects
automatic/calculated fields and removes the redundant empty
`forward_assumptions` requirement. Missing scenario assumptions are never inferred.
Full scenario probabilities, their rationale and explicit hurdle are required
in version 2. Probabilities remain separate `JUDGMENT`, never valuation inputs
disguised as `ASSUMPTION`.

The example numbers and business statements are illustrative, not verified ADBE
beliefs. Empty evidence lists deliberately mean no evidence was authored.

```powershell
New-Item -ItemType Directory -Force .\data\underwriting | Out-Null
Copy-Item .\docs\examples\adbe_consolidated_underwriting.sample.json .\data\underwriting\ADBE-contract.json
notepad .\data\underwriting\ADBE-contract.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE-contract.json
uv run owner-lens underwriting history ADBE
```

## Evidence tied to beliefs

Evidence entries accept existing `text`, `category` and `references`, plus:

* `evidence_id`: optional record-local identifier, unique across both evidence lists.
* `evidence_date`: optional observation/as-of date in `YYYY-MM-DD`.
* `belief_references`: optional JSON pointers into this frozen snapshot.

Example structure, not a factual ADBE claim:

```json
{
  "evidence_id": "retention-note",
  "category": "JUDGMENT",
  "text": "Illustrative interpretation: retention evidence would support durable demand.",
  "evidence_date": "2026-10-30",
  "references": [{"title": "Your dated research note", "observed_at": "2026-10-30"}],
  "belief_references": [
    "/manual/business_drivers/0",
    "/manual/scenarios/1/revenue_cagr",
    "/manual/thesis/monitoring_dependencies/0"
  ]
}
```

Pointers must resolve to existing drivers, scenario assumptions, dependencies or
breakers in the same immutable snapshot. They cannot refer to future/current
records or calculated results. Evidence dates and v2 reference observation
times cannot exceed the captured as-of/cutoff. References can retain title,
URI, observation time and notes; user references are not fetched or verified.
OwnerLens's provider provenance remains automatically copied, not retyped.

## Thesis conditions, not a monitoring engine

Dependencies and breakers in v2 are structured `JUDGMENT`:

```json
{
  "condition_id": "erosion",
  "category": "JUDGMENT",
  "statement": "Illustrative: structural demand erosion would invalidate the thesis.",
  "observable": "Annual revenue trend and disclosed retention",
  "threshold": "Two annual revenue declines with deteriorating retention",
  "sources": [{"title": "Filed annual reports"}],
  "monitoring_cadence": "At each annual filing"
}
```

`condition_id`, category and statement are required. Observable, threshold,
sources, cadence and optional `monitoring_date` remain optional; missing
metadata is surfaced by the projection, not silently filled. Condition ids
are unique across dependencies/breakers. A monitoring date may be future:
it is an intention, not future evidence. No scheduler, alerts or retrieval runs.
This structure directly addresses the 8E challenger request for observable
metrics, thresholds, sources and monitoring dates. The challenger still does
not claim automated verification of thesis quality.

## Durable versions and lifecycle

```text
Evidence
  -> investor judgment
  -> immutable underwriting
  -> deterministic valuation
  -> variant perception
  -> probabilities / expected return
  -> challenger
```

The canonical snapshot keeps automatic `starting_financial_state`,
`historical_base_rates` and copied `evidence` separate from `manual`.
Investor assumptions/probabilities never contain duplicated terminal values or
returns. Saved valuations and challenger runs remain separate append-only records.

New authoring uses `contract_version=2` and snapshot `schema_version=2`.
SQLite remains schema 6; no financial model or classification version changes.
The loader supports snapshot versions 1 and 2. Legacy optional fields are omitted
exactly as before, preserving v1-v5 byte-for-byte round trips and hashes.
Legacy text dependencies/breakers are not upgraded or rewritten.

For v2, text dependencies/breakers are deterministic compatibility mirrors of
structured conditions, allowing unchanged 8B-8E consumers to operate. They are
not independently authored and contain no duplicated calculations.
Any revision creates a new security-scoped underwriting version. New evidence
cannot replace evidence in a historical snapshot.

## Read projection for 8F2

`project_underwriting(store, ticker, version=...)` is a frozen domain projection,
not a Streamlit page or a new investing capability. Omit version only to select
the latest record; an explicit absent version fails.

| Surface | Projection field |
| --- | --- |
| Status/version/as-of/identity | `status`, `record` |
| Starting facts and historical base rates | `snapshot.starting_financial_state`, `snapshot.historical_base_rates` |
| Frozen price, analyst ranges/counts/horizons/provenance | `snapshot.evidence_json` |
| Bear/Base/Bull beliefs, weights and policy | `snapshot.manual.scenarios`, `probability_distribution`, `investor_policy` |
| Saved scenario results | `valuation_json` |
| Expected return/hurdle/classification | `summary` |
| Variant view and ranked/local sensitivities | `variant`, `summary.variant` |
| Business drivers, uncertainty, dependencies/breakers | `snapshot.manual` |
| Advisory findings and exact run identity | `challenger_runs` |
| Missing evidence or unapproved inputs | `missing_evidence` |

Statuses are `NOT_CREATED`, `CAPTURED`, `VALUED` and `SUMMARY_READY`. Missing
valuation is not silently generated. Existing saved valuation integrity is
validated against the same frozen version; summary/variant derivation reuses
domain engines, never latest evidence or provider calls. Historical outputs
are never saved or replaced during projection. Corruption/errors propagate.
Absent probabilities, policy, evidence, consensus or monitoring metadata remain
visible; a summary-ready record is not certified as investment-ready.
Challenger `show` data comes from saved runs, never automatic advisory execution.

8F2 can render these values without implementing financial arithmetic. No UI,
new valuation, AI, monitoring, sizing, instruments or portfolio logic is added.

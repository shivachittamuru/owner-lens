# ADR-003 — Immutable Underwriting History and Evidence Provenance

**Status:** Accepted  
**Scope:** Persistence, learning, calibration, and auditability

## Context

OwnerLens is intended to improve investment judgment over time.

That requires more than storing the latest thesis. The system must preserve what was believed at a given point in time, what evidence was available, what decisions followed, what happened afterward, and where the investor was right or wrong.

Overwriting past assumptions would destroy the ability to calibrate the process and would invite hindsight bias.

## Decision

OwnerLens will preserve immutable, timestamped history for:

- underwritings,
- assumptions,
- scenario probabilities,
- expected returns,
- edge assessments,
- confidence,
- evidence,
- decisions,
- portfolio context,
- material updates.

Updates create new versions rather than mutating historical records.

Important evidence must retain provenance:

```text
claim
→ source
→ source date
→ retrieval / ingestion timestamp
→ supporting passage or structured record
```

Conceptually:

```text
Underwriting
    ↓
Decision
    ↓
Outcome
    ↓
Calibration
    ↓
What was right / wrong?
    ↓
Future underwriting
```

## Rationale

The durable asset in OwnerLens is not any current LLM, data provider, graph technology, or retrieval stack.

It is the accumulated record of:

- historical beliefs,
- assumptions,
- decisions,
- outcomes,
- calibration,
- mistakes,
- company models,
- portfolio history.

This makes OwnerLens a personal investing learning system rather than only a stock-analysis tool.

## Alternatives considered

### 1. Store only the latest underwriting

Rejected because it prevents calibration and hides belief changes.

### 2. Overwrite changed assumptions in place

Rejected because it introduces hindsight bias.

### 3. Preserve snapshots but not source provenance

Rejected because later review would be unable to distinguish evidence quality from judgment quality.

## Consequences

### Positive

- Enables calibration.
- Supports "What changed?" workflows.
- Preserves accountability.
- Makes decision-quality review possible.
- Enables future analysis of personal investing edge.

### Negative

- Storage and schema complexity increase.
- Historical-version querying must be supported.
- Data migrations require care to preserve semantics.

## Revisit when

The decision itself should not be reversed. Implementation details may evolve, but historical investment-state preservation remains a core product invariant.

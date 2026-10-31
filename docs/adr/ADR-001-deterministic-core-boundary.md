# ADR-001 — Separate Deterministic Financial Truth from Probabilistic Judgment

**Status:** Accepted  
**Scope:** OwnerLens core architecture

## Context

OwnerLens combines reported financial data, derived owner-economics metrics, qualitative business understanding, future assumptions, scenario probabilities, and expected-return calculations.

These categories have different reliability characteristics.

Reported and normalized financial facts should be reproducible from authoritative data. Derived metrics should be deterministic given the same inputs. By contrast, moat strength, disruption risk, future growth, scenario probabilities, and expected-return judgments are inherently uncertain.

Allowing LLM-generated judgment to contaminate the deterministic financial core would make the system harder to audit, reproduce, debug, and trust.

## Decision

OwnerLens will enforce a hard conceptual boundary:

```text
Reported / Provider-Normalized Facts
                ↓
      Deterministic Metrics
                ↓
──────────────────────────────────
         Judgment Layer
                ↓
          Assumptions
                ↓
           Scenarios
                ↓
         Probabilities
                ↓
        Expected Returns
```

The deterministic core owns:

- canonical financial definitions,
- normalized facts,
- owner-economics calculations,
- historical metrics,
- deterministic valuation math.

The probabilistic layer owns:

- qualitative business interpretation,
- assumptions,
- scenarios,
- probabilities,
- edge,
- confidence,
- forward-looking reasoning.

LLMs may inform judgment, but they do not silently rewrite deterministic facts.

## Rationale

This provides:

- reproducibility,
- auditability,
- provider/model independence,
- clearer debugging,
- explicit uncertainty,
- safer future model replacement.

It also prevents false precision by making uncertain judgments visibly different from hard financial facts.

## Alternatives considered

### 1. Let the LLM produce a unified investment record

Rejected because it would blur facts, calculations, assumptions, and narrative judgment.

### 2. Put all logic inside agent workflows

Rejected because deterministic financial logic should remain testable code rather than model behavior.

### 3. Use only deterministic models

Rejected because underwriting requires forward-looking judgment that cannot be reduced to historical arithmetic alone.

## Consequences

### Positive

- Financial truth remains stable even if models change.
- Underwriting errors can be traced to either data/calculation or judgment.
- Scenario assumptions remain explicit.
- Provider migration is easier.

### Negative

- More schemas and interfaces are required.
- Some information may exist in both structured and narrative forms.
- The system must maintain discipline around layer boundaries.

## Revisit when

Reconsider only if a future probabilistic component can provide stronger guarantees of reproducibility and provenance than current LLM-based reasoning while preserving clear fact/judgment separation.

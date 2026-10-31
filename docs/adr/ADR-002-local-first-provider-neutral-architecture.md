# ADR-002 — Local-First, Provider-Neutral, Selectively Cloud-Enabled Architecture

**Status:** Accepted  
**Scope:** Infrastructure and data-provider architecture

## Context

OwnerLens is initially a single-user investment research and decision-support system.

The project can use many cloud services and data providers, but premature infrastructure would increase cost, maintenance, cognitive load, and development time without necessarily improving investment decisions.

The project also needs resilience to provider changes.

## Decision

OwnerLens will remain:

> **local-first, provider-neutral, and selectively cloud-enabled.**

Initial defaults:

```text
Python
uv
SQLite / local relational persistence
Parquet / local files where appropriate
raw immutable snapshots
CLI / notebooks
```

Data access will use provider adapters that map external payloads into OwnerLens canonical schemas.

Azure or other managed infrastructure will be introduced only when a specific requirement justifies it, such as:

- scheduled monitoring,
- multi-user access,
- scalable document retrieval,
- production-grade observability,
- remote execution,
- durable shared storage.

## Rationale

The scarce resource is engineering attention.

A local-first architecture keeps iteration cheap and fast while the investment model is still evolving.

Provider-neutral contracts preserve the ability to change sources without rewriting the underwriting system.

## Alternatives considered

### 1. Cloud-first architecture

Rejected for the initial system because the operating complexity is not yet justified.

### 2. Bind the core directly to one provider

Rejected because provider schemas and commercial terms can change.

### 3. Build a full production platform immediately

Rejected because OwnerLens must first prove investment utility.

## Consequences

### Positive

- Low operating cost.
- Fast experimentation.
- Easier debugging.
- Provider replacement is possible.
- Architecture evolves with demonstrated need.

### Negative

- Some future migration work is expected.
- Local tooling may be less convenient for scheduling or remote access.
- Certain managed capabilities may be introduced later than in a cloud-first design.

## Revisit when

Introduce managed infrastructure when one or more are true:

- recurring jobs become operationally painful,
- local persistence limits scale,
- retrieval latency becomes unacceptable,
- multi-device or multi-user access matters,
- production observability becomes necessary,
- a managed service materially reduces total engineering effort.

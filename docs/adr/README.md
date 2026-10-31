# OwnerLens Architecture Decision Records

This folder captures consequential architectural decisions for OwnerLens.

## Purpose

The PRDs describe **what OwnerLens should do and why**.

These ADRs describe **why the system is architected the way it is**, including trade-offs, rejected alternatives, consequences, and conditions that should trigger reconsideration.

The intent is to keep OwnerLens technically disciplined without allowing architecture work to become an end in itself.

## ADR format

Each ADR contains:

- **Status**
- **Context**
- **Decision**
- **Rationale**
- **Alternatives considered**
- **Consequences**
- **Revisit when**

## Decision index

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-deterministic-core-boundary.md) | Separate deterministic financial truth from probabilistic judgment | Accepted |
| [ADR-002](ADR-002-local-first-provider-neutral-architecture.md) | Local-first, provider-neutral, selectively cloud-enabled architecture | Accepted |
| [ADR-003](ADR-003-immutable-underwriting-and-provenance.md) | Immutable underwriting history and evidence provenance | Accepted |
| [ADR-004](ADR-004-adaptive-evidence-acquisition.md) | Adaptive evidence acquisition instead of a universal RAG pipeline | Accepted |
| [ADR-005](ADR-005-investment-knowledge-graph-boundary.md) | Knowledge graph is a relationship layer, not a source of financial truth | Accepted |
| [ADR-006](ADR-006-bounded-agents-human-decision-control.md) | Bounded agents with human-controlled capital allocation | Accepted |

## Documentation hierarchy

```text
PRD
→ What are we building and why?

Extension PRD
→ What investing capabilities come next?

ADR
→ Why is the system architected this way?

Design note
→ How does a specific capability work?

Code
→ Implementation
```

## Governing principle

Every architectural addition should be able to answer:

> Does this improve underwriting, expose a meaningful risk, identify a better opportunity, improve portfolio construction, or prevent a bad investment decision?

If not, do not build it yet.

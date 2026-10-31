# ADR-005 — Investment Knowledge Graph Is a Relationship Layer, Not a Source of Financial Truth

**Status:** Accepted  
**Scope:** Graph and portfolio-intelligence architecture

## Context

OwnerLens needs to reason about relationships that are poorly represented by independent document chunks or financial tables.

Examples:

- competitor relationships,
- supplier dependencies,
- customer concentration,
- technology exposure,
- economic themes,
- portfolio-level shared drivers,
- multi-hop dependencies.

However, a graph generated partly from unstructured evidence introduces new failure modes:

- missed entities,
- duplicate entities,
- incorrect relationships,
- stale relationships,
- LLM extraction errors.

The graph must not become a substitute for authoritative financial data.

## Decision

The Investment Knowledge Graph will represent:

> **durable economic and strategic relationships.**

It will not duplicate fast-changing financial truth.

Boundary:

```text
Structured OwnerLens Store
→ revenue, FCF, margins, debt, price, valuation

Evidence Store
→ filings, transcripts, passages, source documents

Investment Knowledge Graph
→ company, product, competitor, supplier, technology,
  risk, theme, geography, dependency relationships
```

Every important graph edge should retain:

- provenance,
- observed timestamp,
- validity period where useful,
- confidence where inferred.

Graph retrieval must return supporting evidence for material conclusions.

The graph is introduced only when relationship-heavy or portfolio questions justify it.

## Rationale

This captures the genuine strength of graph retrieval without contaminating financial truth or turning GraphRAG into the project roadmap.

The graph becomes especially useful for portfolio intelligence:

- hidden concentration,
- common economic drivers,
- indirect dependencies,
- theme exposure,
- second-order beneficiaries and risks.

## Alternatives considered

### 1. Put all company knowledge into the graph

Rejected because financial data and live market state already have better authoritative representations.

### 2. Full GraphRAG as the default retrieval system

Rejected because most investment questions do not require graph traversal.

### 3. No graph layer

Rejected as a long-term position because some portfolio questions are fundamentally relationship-shaped.

## Consequences

### Positive

- Clear source-of-truth boundaries.
- Relationship intelligence can evolve independently.
- Graph errors cannot silently rewrite financial facts.
- Portfolio topology can become explicit.

### Negative

- Cross-store joins are required.
- Entity resolution becomes a real concern.
- Temporal relationship maintenance may be necessary.

## Revisit when

Expand the graph only when evaluation proves material value for:

- relational questions,
- multi-hop questions,
- hidden portfolio dependencies,
- global thematic analysis.

Do not expand merely because graph technology is available.

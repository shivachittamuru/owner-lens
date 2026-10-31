# ADR-004 — Adaptive Evidence Acquisition Instead of a Universal RAG Pipeline

**Status:** Accepted  
**Scope:** Retrieval and evidence architecture

## Context

OwnerLens needs different evidence types for different investment questions.

Examples:

```text
"What was FY2025 FCF/share?"
→ structured financial data

"What did management say about AI monetization?"
→ filing / transcript retrieval

"Which holdings depend on hyperscaler AI capex?"
→ relationship graph

"Did this price decline improve expected return or reflect thesis deterioration?"
→ prior underwriting + live data + new evidence
```

A universal vector-RAG pipeline would be inefficient and would force structured, live, relational, and textual questions through the same retrieval mechanism.

## Decision

OwnerLens will use an adaptive evidence-acquisition layer.

The system will first identify the information need, then select the cheapest authoritative source that can answer it.

```text
Investment Question
        ↓
Information Requirements
        ↓
Evidence Router
        ↓
┌────────────┬────────────┬────────────┬────────────┐
│ Structured │ Hybrid RAG │ Live Data  │ Graph      │
└────────────┴────────────┴────────────┴────────────┘
        ↓
Evidence State
        ↓
Sufficient?
   /         yes         no
  ↓           ↓
reason      re-plan
```

Simple questions should exit early.

Complex questions may use planned multi-source retrieval.

Agentic retrieval is allowed only when the retrieval path itself is uncertain.

## Rationale

This architecture:

- matches retrieval strategy to question shape,
- avoids unnecessary latency and model cost,
- improves source authority,
- allows structured systems to remain authoritative,
- makes retrieval behavior observable and testable.

## Alternatives considered

### 1. Vector search for all questions

Rejected because semantic similarity is not the right abstraction for structured facts, live state, or relationships.

### 2. Always run the maximum retrieval pipeline

Rejected because unnecessary rewriting, multi-query, reranking, graph traversal, or agent loops increase cost and failure surface.

### 3. Fully autonomous retrieval agent

Rejected as the default because many questions have deterministic retrieval paths.

## Consequences

### Positive

- Lower cost and latency for simple questions.
- Better source selection.
- Easier stage-level evaluation.
- Supports modern multi-source retrieval without forcing complexity everywhere.

### Negative

- Routing logic must be designed and evaluated.
- More retrieval contracts exist.
- Observability requirements increase.

## Revisit when

Revisit routing policies when evaluation shows:

- systematic source-selection errors,
- a new source materially changes answer quality,
- a simpler unified mechanism becomes demonstrably better,
- retrieval cost/latency shifts materially.

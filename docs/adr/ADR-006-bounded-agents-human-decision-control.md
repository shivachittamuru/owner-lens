# ADR-006 — Bounded Agents with Human-Controlled Capital Allocation

**Status:** Accepted  
**Scope:** Agent autonomy, decision support, and execution boundaries

## Context

OwnerLens can benefit from agents for:

- evidence planning,
- source selection,
- underwriting challenge,
- contradiction search,
- event classification,
- opportunity comparison,
- re-underwriting support.

But investing decisions contain irreducible uncertainty.

An autonomous agent may also:

- over-retrieve,
- chase noise,
- overfit narratives,
- create false precision,
- overtrade,
- act on stale or weak evidence.

The system must improve judgment without removing accountability.

## Decision

OwnerLens agents will operate under bounded autonomy.

Agents may:

- plan retrieval,
- call approved tools,
- challenge assumptions,
- compare alternatives,
- classify evidence,
- recommend research or decision states.

Agents may not autonomously:

- execute trades,
- change final portfolio allocations,
- set final position sizes without review,
- silently overwrite assumptions,
- bypass source-authority rules,
- run unbounded retrieval loops.

Controls should include:

```text
tool contracts
retrieval budgets
max iterations
source authority
evidence provenance
stopping criteria
audit trail
human approval
```

Preferred interaction:

```text
Agent
  ↓
Evidence + Analysis
  ↓
Recommendation / Decision State
  ↓
Human Review
  ↓
Capital Allocation / Execution
```

## Rationale

This preserves the value of agentic reasoning while protecting against:

- automation bias,
- false confidence,
- unnecessary activity,
- uncontrolled costs,
- opaque decisions.

It also aligns with OwnerLens's role as an investment research and decision-support system rather than an autonomous trading bot.

## Alternatives considered

### 1. Fully autonomous investing agent

Rejected because uncertainty, model error, and portfolio consequences remain too material.

### 2. No agents; purely manual workflows

Rejected because planned retrieval and repetitive analytical tasks can benefit from controlled automation.

### 3. Deterministic workflows only

Rejected because some research and underwriting tasks genuinely require semantic reasoning.

## Consequences

### Positive

- Better auditability.
- Lower risk of overtrading.
- Agents remain replaceable components.
- Human accountability remains explicit.

### Negative

- Some workflows require review steps.
- Full automation is intentionally limited.
- Product UX must clearly distinguish recommendation from action.

## Revisit when

Revisit specific autonomy boundaries only after:

- strong prospective calibration,
- reliable evidence provenance,
- robust failure monitoring,
- demonstrated performance across varied market regimes,
- explicit user approval for any increased action scope.

Execution autonomy should remain a separate architectural decision.

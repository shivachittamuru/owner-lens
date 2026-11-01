---
title: "OwnerLens Data Quality & Coverage Reference"
description: "Provider, canonical and analytical coverage with explicit underwriting evidence limitations."
---

## Purpose

This document explains what OwnerLens means when data is `FULL`, `PARTIAL`, `FAILED`, unavailable, unsupported, or otherwise unusable.

The key principle is:

> **A data problem is not a business conclusion.**

OwnerLens should prefer an explicit "I do not know" over a fabricated number, silent fallback, or false sense of completeness.

# Three different questions

When interpreting Data Quality, separate these:

1. **Did the provider return data?**
2. **Can OwnerLens normalize that data into trustworthy canonical facts?**
3. **Can the downstream analytical model use those facts meaningfully?**

These are not the same thing.

FMP Premium can provide excellent raw coverage while OwnerLens still reports `PARTIAL` or `FAILED` because a required field is absent, a provider concept is unmapped, history is too short, data is ambiguous, or the generic model is not appropriate for the business.

# Provider coverage vs OwnerLens coverage

## Provider coverage

> **Did FMP or SEC return the requested evidence?**

Examples: annual statements, quarterly statements, EOD price, analyst estimates.

## Canonical coverage

> **Can OwnerLens convert provider evidence into the canonical metrics it needs without guessing?**

A provider statement can exist while a canonical metric remains unsupported.

## Analytical coverage

> **Can OwnerLens build owner economics, capital efficiency, compounding, capital allocation, economic value and screening from the canonical history?**

A company can therefore have excellent FMP statement coverage and still have incomplete Feature 7 coverage.

# Canonical metric states

## `AVAILABLE`

The metric was found and normalized with sufficient confidence.

## `STRUCTURALLY_ABSENT`

The metric is legitimately not present because the economic concept does not apply or is not separately reported in the expected structure.

This is different from missing provider data.

## `UNSUPPORTED`

OwnerLens could not derive the metric using its accepted concepts/rules.

This can mean the provider has data in an as-yet-unmapped form, or the current canonical model does not support the reporting structure.

## `INVALID`

Evidence was present but failed a validity, consistency, ambiguity, or normalization rule.

OwnerLens deliberately refuses to approximate through the problem.

# Feature 7 coverage classes

## `FULL`

All analytical layers Feature 7 needs produced usable output.

This normally means all six screening dimensions are evaluable.

`FULL` does **not** mean every possible accounting field is present. It means enough trustworthy evidence exists for the current screening contract.

## `PARTIAL`

Owner economics are usable, but one or more downstream analytical layers or dimensions are unavailable.

Examples can include:

- missing per-share evidence;
- incomplete capital-allocation history;
- an unavailable balance-sheet metric;
- insufficient history for one compounding calculation;
- a specialized accounting structure that prevents one dimension from being interpreted reliably.

A partial company may still be valuable to research.

## `FAILED`

OwnerLens cannot construct usable owner economics under the current canonical contract.

> **The current screening pipeline failed for this security.**

It does **not** mean the company is financially bad.

# Why Premium does not make everything `FULL`

FMP Premium solves a major part of the evidence problem:

- broad company coverage;
- long annual history;
- recent quarterly history;
- prices;
- analyst estimates.

But raw data availability is only the first layer.

`PARTIAL` or `FAILED` can still occur when:

- required concepts are absent from normalized statements;
- share-count or SBC history is incomplete or unusual;
- debt/cash/equity structures do not fit the generic model;
- reporting history is too short;
- a newly public or reorganized company lacks comparable periods;
- provider rows conflict;
- a company uses a business/accounting model where generic FCF/ROIC logic is not economically meaningful.

The goal is not 100% FULL coverage.

> **Broad usable coverage + explicit limitations + no silent guessing.**

# Diagnostic failure classification

The following taxonomy is the recommended human-facing explanation for `PARTIAL` and `FAILED` cases.

**Important:** these categories are a reference target. Unless/until implemented as first-class Data Quality fields, treat them as a diagnostic framework rather than existing persisted enums.

## `MAPPING_GAP`

### Meaning

The provider appears to contain the required economic information, but OwnerLens does not currently recognize or map the relevant field/concept.

### Example

```text
FMP contains a usable concept
        ↓
canonical adapter does not recognize that variant
        ↓
metric becomes UNSUPPORTED
```

### Action

Usually worth fixing when the mapping is economically unambiguous, benefits multiple companies, and does not weaken normalization rules.

> **Likely an OwnerLens normalization opportunity.**

## `PROVIDER_MISSING`

### Meaning

The provider genuinely does not supply enough evidence for the required metric or period.

### Action

- accept the limitation;
- check SEC as authoritative filed evidence;
- consider another source later only if decision value justifies it.

Do not manufacture a value.

> **The evidence source does not know enough.**

## `SPECIAL_MODEL_REQUIRED`

### Meaning

The data may be valid, but the generic corporate economics model is not appropriate enough to make the intended inference.

Common candidates include:

- banks;
- insurers;
- REITs;
- some asset managers;
- utilities or other regulated/capital-structure-specific businesses.

### Action

Do **not** force these businesses into generic comparability merely to get `FULL`.

Future specialized models should exist only when they materially improve investing decisions.

> **This is a model-applicability problem, not necessarily a data problem.**

## `SHORT_HISTORY`

### Meaning

The company does not have enough comparable history for a required trend, CAGR, compounding window, or capital-allocation judgment.

Common causes:

- recent IPO;
- spin-off;
- major restructuring;
- newly formed public entity;
- limited comparable provider history.

### Action

Keep the limitation explicit. Do not shorten requirements solely to improve coverage statistics.

> **We may know recent facts without having enough history to judge durability.**

## `INVALID_OR_AMBIGUOUS`

### Meaning

Evidence exists, but OwnerLens cannot choose a trustworthy interpretation because values conflict, periods overlap, signs are implausible, or multiple concepts remain materially ambiguous.

### Action

Investigate provenance. Fix only when there is a deterministic, economically defensible rule.

> **The system correctly refused to guess.**

# Suggested diagnosis order

When a company is `PARTIAL` or `FAILED`, ask:

```text
1. Did FMP return the required dataset?
        ↓ no
   PROVIDER_MISSING

2. Is the needed concept present but unmapped?
        ↓ yes
   MAPPING_GAP

3. Is there enough comparable history?
        ↓ no
   SHORT_HISTORY

4. Is the evidence contradictory or ambiguous?
        ↓ yes
   INVALID_OR_AMBIGUOUS

5. Is the generic model appropriate for this business?
        ↓ no
   SPECIAL_MODEL_REQUIRED
```

Some companies may have more than one issue. Prefer the **primary decision-relevant blocker** rather than forcing every case into one category.

# What should be fixed?

## Usually worth fixing

### Reusable mapping gaps

Fix when a mapping is deterministic, economically correct, and benefits multiple companies.

### Clear normalization defects

Fix sign, period, split, restatement or field-selection problems when the correct rule can be stated and tested.

### Persistence/provenance bugs

Always fix when they can cause OwnerLens to attribute a value to the wrong evidence.

# What should usually remain explicit?

## Genuine provider gaps

Do not invent missing evidence.

## Short history

Do not fabricate durability.

## Specialized business models

Do not distort a bank, insurer or REIT merely to make it comparable to Adobe.

## Real ambiguity

Do not choose a convenient interpretation merely because the Screener wants a number.

# Coverage ceilings

Missing evidence must never become an advantage.

That is why Feature 7 uses coverage-aware ceilings.

A partially measured company cannot automatically outrank fully measured companies simply because the system never observed its weak dimension.

> **Absence of negative evidence is not positive evidence.**

# Why `FAILED` companies remain visible

OwnerLens deliberately retains failed securities rather than quietly dropping them.

Dropping them would create hidden survivorship bias in the research universe.

A failed company should trigger:

> **Why did OwnerLens fail to evaluate this?**

not:

> **Remove it from the universe.**

# How to use Data Quality in practice

## When you see `FULL`

Proceed normally.

Remember that `FULL` means complete **for the current analytical contract**, not perfect knowledge of the business.

## When you see `PARTIAL`

Ask:

1. Which dimension is `NOT_EVALUABLE`?
2. Which canonical metric or analytical layer blocks it?
3. Is the problem `MAPPING_GAP`, `PROVIDER_MISSING`, `SHORT_HISTORY`, `SPECIAL_MODEL_REQUIRED`, or `INVALID_OR_AMBIGUOUS`?
4. Would fixing it materially change an investing decision?

Only then decide whether engineering work is justified.

## When you see `FAILED`

Ask:

1. Did annual evidence ingest successfully?
2. Can a canonical history be built?
3. Which owner-economics input failed?
4. Is this a reusable gap or a specialized business?
5. Is the company important enough to justify a targeted fix?

Do not begin with:

> **How do we get this to FULL?**

Begin with:

> **What exactly prevents a trustworthy judgment?**

# Provider authority

| Evidence / calculation | Authority |
|---|---|
| Filed accounting facts / filing provenance | SEC |
| Broad normalized history | FMP as operational evidence source, validated against SEC where useful |
| Quarterly normalized evidence | FMP, with SEC validation when decision-relevant |
| EOD market price | FMP |
| Analyst consensus expectations | FMP |
| FCF, FCF/share, ROIC, margins, screening | OwnerLens deterministic code |
| Personal thesis assumptions | Investor-approved ASSUMPTION in immutable underwriting |
| Scenario valuation / expected return | OwnerLens deterministic code over frozen underwriting inputs |
| Scenario probability | Explicit judgment |
| Investment decision | Investor |

Do not silently fill an FMP metric with SEC inside one canonical history or vice versa.

## Underwriting evidence is not screening completeness

Investor-entered evidence labeled `JUDGMENT` is an interpretation, not automatically
equivalent to independently verified FACT or provider provenance. Source references
retain what the investor supplied; OwnerLens does not autonomously retrieve or
verify them. Other asserted categories also do not establish independent verification.

Missing consensus, supporting/disconfirming evidence and unsaved derived outputs
remain explicit. `FULL` screening coverage does not establish a complete thesis;
`CAPTURED` underwriting does not establish saved valuation or challenger output.
Absence of evidence, including disconfirming evidence, is not positive evidence.
These distinctions do not change the failure taxonomy above.

# Point-in-time discipline

Data Quality is also about **when** evidence was known.

Preserve:

- provider;
- endpoint/dataset;
- fetched/observed time;
- fiscal period;
- market date;
- content hash/raw provenance;
- expectation snapshot time.

Future calibration must distinguish:

> **What was actually knowable when the decision was made?**

from:

> **What we know now with hindsight?**

# The principle to remember

The goal of Data Quality is not a prettier dashboard.

It is to protect every downstream investment judgment from bad evidence.

```text
Trustworthy FULL coverage
    > honest PARTIAL coverage
    > explicit FAILED coverage
    > fabricated completeness
```

When OwnerLens says it cannot evaluate something, that refusal is often evidence that the system is behaving correctly.

---
title: OwnerLens Constitution
description: Non-negotiable engineering and financial-integrity principles for OwnerLens
author: OwnerLens maintainers
ms.date: 2026-08-31
ms.topic: reference
---

<!--
Sync Impact Report

* Version change: unversioned scaffold -> 1.0.0
* Modified principles:
	* Template Principle 1 -> I. Financial Correctness Is the Primary Constraint
	* Template Principle 2 -> II. Every Financial Fact Is Traceable
	* Template Principle 3 -> III. Deterministic Computation Before AI
	* Template Principle 4 -> IV. Financial Definitions and Tests Are Contracts
	* Template Principle 5 -> V. Fail Loudly; Never Fabricate
* Added principles:
	* VI. Build Only What the Current Release Requires
* Added sections:
	* Architecture and Delivery Constraints
	* Quality Gates and Development Workflow
* Removed sections: none; placeholder sections were concretized
* Follow-up TODOs: none
-->

## Core Principles

### I. Financial Correctness Is the Primary Constraint

Financial correctness MUST take precedence over feature breadth, delivery speed, provider coverage,
and architectural novelty. A release MUST support a narrow set of financial facts and metrics
correctly before it expands coverage. Differences from authoritative filings or accepted reference
outputs MUST be investigated and explained rather than dismissed. This priority makes OwnerLens a
trustworthy financial-intelligence foundation rather than a collection of plausible outputs.

### II. Every Financial Fact Is Traceable

Every reported financial fact MUST retain sufficient provenance to identify its provider, source
concept or tag when available, filing or accession identifier when available, unit, fiscal period,
and fiscal year. Transformations MUST preserve links to their input facts so a user can determine
where a value came from and how it was produced. Outputs without adequate provenance MUST NOT be
presented as verified financial facts. Traceability enables reconciliation, correction, and audit.

### III. Deterministic Computation Before AI

Calculations, normalization, period selection, and other transformations that do not require AI
reasoning MUST be implemented as deterministic code. AI agents MUST consume deterministic
OwnerLens tools and MUST NOT invent, estimate, or independently assert financial facts. AI use MUST
remain limited to tasks requiring interpretation or judgment, and its output MUST remain clearly
distinguishable from facts, metrics, and scores. This separation keeps reproducible computation out
of probabilistic systems.

### IV. Financial Definitions and Tests Are Contracts

Every supported financial metric MUST have an explicit, documented definition that identifies its
inputs, formula, period semantics, units, and permitted edge-case behavior. Implementations MUST NOT
silently substitute alternate definitions. Financial transformations and fiscal-period handling
MUST have focused automated tests covering representative, missing, ambiguous, and boundary data.
A meaningful new financial concept MUST include an educational notebook that demonstrates the
definition, provenance, calculation, and interpretation with reproducible inputs. These artifacts
make financial behavior reviewable and prevent unnoticed semantic drift.

### V. Fail Loudly; Never Fabricate

Missing, conflicting, or ambiguous financial data MUST produce an explicit, actionable result such
as a typed error, validation failure, or clearly marked unavailable value. OwnerLens MUST NOT guess,
backfill, coerce, or fabricate a financial value merely to complete an output. Any permitted fallback
or derivation MUST be defined in advance, exposed in provenance, and covered by tests. Visible
failure protects users from treating uncertainty as fact.

### VI. Build Only What the Current Release Requires

Each release MUST be narrow, incremental, and tied to an active requirement. Infrastructure,
dependencies, abstractions, provider capabilities, and features MUST NOT be introduced for a
speculative future use case. A proposal that adds any of these MUST identify the current requirement
it satisfies and why a simpler option is inadequate. This rule limits maintenance cost and keeps
engineering effort focused on validated financial value.

## Architecture and Delivery Constraints

* Provider-specific retrieval and mapping MUST remain outside downstream financial metric logic.
* Provider boundaries MUST expose only the contract required by supported use cases. They MUST NOT
	generalize across hypothetical providers or unsupported taxonomies.
* Local development MUST remain sufficient for the project's basic retrieval, transformation,
	testing, and notebook workflows.
* Azure or other hosted infrastructure MUST be introduced only when an active requirement cannot be
	satisfied adequately by the local-first design.
* Dependencies and architectural layers MUST have a current consumer and a documented purpose.
* Production code, tests, and notebooks MUST use reproducible inputs or record the exact source and
	retrieval context needed to reconcile changing external data.

## Quality Gates and Development Workflow

Each feature specification and implementation review MUST identify the financial definitions,
source-provenance behavior, missing-data behavior, and period semantics it affects. Before merge:

* Financial calculations and transformations MUST pass focused automated tests.
* Period handling MUST be tested whenever annual, quarterly, trailing, comparative, or fiscal-period
	behavior changes.
* Reported facts MUST expose the required provenance and MUST be reconcilable to their source.
* New failure paths MUST surface missing or ambiguous data explicitly.
* Meaningful new financial concepts MUST include or update a runnable educational notebook.
* New providers, dependencies, abstractions, infrastructure, and AI behavior MUST demonstrate an
	active release requirement and compliance with the relevant core principles.
* Reviewers MUST reject changes that broaden scope without preserving financial correctness.

Exceptions MUST be documented in the governing feature specification or decision record, include a
bounded duration or removal condition, and identify the principle affected. An exception MUST NOT
permit fabricated financial values or untraceable facts.

## Governance

This constitution governs all OwnerLens specifications, plans, implementation tasks, reviews, and
releases. When another project document conflicts with it, this constitution takes precedence.

Amendments MUST be proposed as an explicit constitution change, include the rationale and migration
impact, update the Sync Impact Report, and receive maintainer approval before dependent work merges.
Compliance MUST be reviewed during specification, planning, and code review. Any unresolved
violation MUST block release unless governed by a documented exception permitted above.

Constitution versions follow semantic versioning:

* MAJOR increments remove or incompatibly redefine a principle or governance obligation.
* MINOR increments add a principle or materially expand governance requirements.
* PATCH increments clarify wording without changing required behavior.

The ratification date records initial adoption. The last-amended date MUST change whenever normative
content changes. Reviews of this constitution MUST occur before each meaningful release and whenever
a recurring compliance conflict indicates that its rules are unclear or incomplete.

**Version**: 1.0.0 | **Ratified**: 2026-08-31 | **Last Amended**: 2026-08-31

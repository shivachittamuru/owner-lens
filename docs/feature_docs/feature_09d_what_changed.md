---
title: "Feature 9D: What Changed and Re-underwriting"
description: "Immutable manual evidence events, exact structured predicates and investor-approved re-underwriting triggers."
---

## Purpose and boundaries

Record whether new information is noise, evidence, a thesis update or a thesis
break, without rewriting the beliefs, decisions or sizing that preceded it.
This workflow is offline and manual. It has no agents, retrieval, scheduling,
automatic extraction, LLM classification, automatic assumption/probability
changes, trade instructions, rebalancing or self-improving loop.

The shared domain is [`changes.py`](../../src/owner_lens/changes.py).
The CLI and Workbench use the same event, assessment and approval boundary.

## Change-event schema

Events require an exact completed Feature 8 underwriting version. The Feature 9A
loader validates its saved valuation, expected-return inputs and evidence cutoff.
No explicit version is replaced with latest.

| Input field | Meaning |
|-------------|---------|
| `event_date` | YYYY-MM-DD date of the event or reported measurement |
| `observed_at` | Timezone-aware timestamp when the investor observed this information |
| `observation.category` | `FACT`, `EXPECTATION` or `JUDGMENT`; never automatically recategorized |
| `observation.statement` | Concise nonempty observation |
| `observation.references` | Explicit list of source title, URI, observation date/time and note |
| `observation.verification_note` | Required nonempty manual verification explanation for FACT |
| `observation.metric` | Optional object containing `observable`, `value`, `unit`, `cadence` and optional `source_family`; each explicitly nullable |
| `interpretation` | Required `category: JUDGMENT` and nonempty `text` |
| `condition_id` | Optional exact structured dependency/breaker ID, or null |
| `affected_beliefs` | Required list of exact JSON pointers into the original frozen snapshot; [] means none linked, not none affected |
| `affected_binding_constraints` | Optional explicit list of linked historical sizing bindings affected in the investor's judgment |

Saved events add an event UUID, actual UTC `recorded_at`, frozen ticker/security
identity, original underwriting UUID/version/hash and snapshot bytes,
deterministic assessment, previous linked beliefs, frozen optional decision/sizing
context, and model version `manual-change-assessment-v1.1` for new events.
Previously saved v1 events and approvals are read unchanged.

FACT requires source title or URI plus a manual verification note. This is an
investor assertion that verification occurred, not an OwnerLens verification
service. Source metadata does not independently prove a claim. EXPECTATION and
JUDGMENT remain in their original categories and cannot drive numeric threshold
candidates in v1.

An event can describe an older measurement that was newly observed, but
`observed_at` cannot precede creation of its selected underwriting.
Require `event_date <= observed_at UTC date <= recorded_at UTC date`, with exact
timestamp ordering for observation/recording. Each dated source must be available
by `observed_at`; date-only source metadata means its declared observation date.
Events never enter the original underwriting evidence snapshot.

## Deterministic condition matching

Feature 8F originally stored monitoring observables and thresholds as text.
Feature 9D.1 also supports first-class structured predicates in newly authored
dependencies and breakers. A linked condition must exist uniquely in the exact
underwriting. Unstructured legacy thesis text remains available but is not
silently converted into a structured condition.

### Structured predicates

The human thesis statement remains separate from the machine predicate:

```json
{
  "condition_id": "total_adobe_arr_growth",
  "category": "JUDGMENT",
  "statement": "Total Adobe ARR growth must remain at least 6%.",
  "observable": "Total Adobe ARR growth",
  "operator": "GTE",
  "threshold": 6.0,
  "unit": "percent_yoy",
  "cadence": "quarterly",
  "source_family": "adobe_earnings"
}
```

All seven machine fields are required for a structured predicate. `operator`
must be `GT`, `GTE`, `LT`, `LTE` or `EQ`; `threshold` must be a finite JSON
number, not text or a boolean. Threshold zero is valid. Partial structured
predicates and conflicting `cadence`/legacy `monitoring_cadence` are rejected.
Optional existing `sources` and `monitoring_date` constraints still apply.

The corresponding event metric is:

```json
{
  "observable": "Total Adobe ARR growth",
  "value": 5.8,
  "unit": "percent_yoy",
  "cadence": "quarterly",
  "source_family": "adobe_earnings"
}
```

Observable, unit, cadence and source family must match exactly, including case
and whitespace. Source family is explicitly supplied provenance metadata, never
inferred from a URL or source title. A mismatch is NOT_COMPARABLE; missing required
event metadata is INSUFFICIENT_DATA. No fuzzy matching or unit conversion occurs.
The source-family label does not replace the verification note and reference
required for a FACT observation.

Future authoring JSON can use these fields directly. The existing underwriting
form offers **Use structured predicate** and explicit operator, numeric threshold,
unit, cadence and source-family inputs. Cloning preserves them; review and save
remain explicit. Historical snapshots do not acquire new null fields or change
their serialized bytes/hashes. No database migration or historical rewrite is
needed for this cleanup.

### Legacy conditions

Supported threshold grammar is one operator (`<`, `<=`, `>`, `>=`, `==`),
one finite signed decimal number and one explicit unit:

```text
>= 7%
< 0%
>= 0.07 ratio
>= 100 USD
```

The unit is `%` or an ASCII letter followed by letters, digits or underscores.
The event's observable must exactly match the condition's observable, including
case and definition. Unit strings must match exactly. A percentage observation
of `5.8` with unit `%` means 5.8%, not 0.058. There is no percent/ratio conversion,
annualization, currency conversion, fuzzy naming, epsilon threshold adjustment
or inference of multiple consecutive periods.

If the condition specifies cadence, the observation must provide exactly the
same cadence. If a monitoring date exists, the event date must reach it. If the
condition has sources, at least one must match: URI equality when that condition
source has a URI, otherwise exact nonempty title equality. This validates declared
provenance compatibility, not document contents. Missing source/cadence/date
constraints are not invented.

| Result | Rule |
|--------|------|
| `CONDITION_MET` | Dependency predicate is true, or breaker predicate is false |
| `CONDITION_BREACHED` | Dependency predicate is false, or breaker predicate is true |
| `NOT_COMPARABLE` | Incompatible observable, unit, cadence or source; unsupported/qualitative threshold |
| `INSUFFICIENT_DATA` | No condition, missing metric/value/unit/observable/required cadence, non-FACT observation, missing condition inputs or monitoring date not reached |

A breaker predicate describes the invalidating state. Thus a breaker `< 0%`
is breached when observed growth is negative. Its predicate being true does
not mean the thesis is healthy.

## Classification authority and triggers

The four approved classifications are exactly `NOISE`, `EVIDENCE`,
`THESIS_UPDATE`, `THESIS_BREAK`.

| Deterministic assessment | Candidate |
|--------------------------|-----------|
| Dependency breach | `THESIS_UPDATE` |
| Breaker triggered | `THESIS_BREAK` |
| Comparable condition with no breach | `EVIDENCE` |
| Not comparable or insufficient | null, not determined |

No materiality rule is invented to automatically classify information as NOISE.
Unknown comparisons do not become neutral evidence. The investor may approve any
of the four classifications, including a causal thesis break that cannot be
encoded as a threshold, but must provide an explicit rationale. The candidate
remains visible even when the approved classification differs.

Approval is a separate immutable record containing approval UUID, event UUID,
actual UTC `approved_at`, `approved_classification`, rationale, JUDGMENT category,
trigger and model version. An approval cannot predate event recording.
There is exactly one approval per event; repeated approval is rejected instead
of editing history. Corrections require a new explicit event, not an overwrite.
Pending events are visible but are not classified re-underwriting history.

| Approved classification | Trigger |
|-------------------------|---------|
| `NOISE` | `NO_REUNDERWRITING_REQUIRED` |
| `EVIDENCE` | `REVIEW_RECOMMENDED` |
| `THESIS_UPDATE` | `NEW_UNDERWRITING_REQUIRED` |
| `THESIS_BREAK` | `NEW_UNDERWRITING_REQUIRED` |

Pending approval has no authoritative trigger. Candidate classifications,
including THESIS_UPDATE/THESIS_BREAK, never increment approved counters.
No trigger creates a new underwriting, changes an assumption/probability, or
changes an investment action.

## Delta and decision context

The delta retains the exact linked condition/threshold, observation,
interpretation, result, candidate, approval and previous affected belief values.
`affected_beliefs` supports pointers under:

- `/manual/scenarios/` and `/manual/forward_assumptions/`: ASSUMPTION.
- `/manual/probability_distribution/`: JUDGMENT probabilities.
- `/manual/thesis/` and `/manual/business_drivers/`: JUDGMENT thesis statements.

Pointers must resolve to nonmissing values. Negative/ambiguous array indexes and
unresolved paths are rejected. Linking a belief does not change it. None linked
is explicit and never means all beliefs were assessed as unaffected.

At event recording, the latest available recorded decision for the same stable
security is copied, together with its date, change rule and complete exact-version
identity. The latest available historical sizing analysis is likewise copied,
including its portfolio, policy, status, ceiling and bindings. Their underwriting
versions may differ from the event's version and remain explicit. Later decisions
or sizing analyses do not alter the event's frozen context.

Affected sizing bindings must be selected explicitly from that copied analysis.
They are `INVESTOR_IDENTIFIED` JUDGMENT, explained by the investor interpretation.
Without an explicit link, effect is `NOT_DETERMINED`, not unaffected. Neither
selection nor approval recalculates sizing or claims that a constraint resolved.
Missing decision/sizing context stays null.

For approved EVIDENCE/THESIS_UPDATE/THESIS_BREAK, the descriptive implication is
for example, "Recorded WATCH decision should be revisited." It is never SELL,
BUY or TRIM. Shadow entries are counterfactual context, not positions.

## Current-state summary and immutable history

`change summary TICKER` reports latest underwriting, latest available recorded
decision/change rule, latest historical sizing status/ceiling, all four approved
counts since latest underwriting creation, both pending counters and aggregate status.
Every event observed since that creation is included, even if linked to an older
version. One later NOISE event cannot clear an earlier approved thesis update.

Only separate approval records contribute to the four classification counters.
`pending_approval` counts all unapproved events. `pending_non_comparable` counts
the subset of those pending events whose assessment is NOT_COMPARABLE. Approved
non-comparable events leave both pending counters and count only under their
explicit approved classification. INSUFFICIENT_DATA events count as pending,
but not as non-comparable.

Aggregate status is `REUNDERWRITING_REQUIRED` if any included approved update/break
exists, otherwise `REVIEW_PENDING` if any unapproved event exists, otherwise
`REVIEW_RECOMMENDED` for any approved evidence, otherwise
`NO_REUNDERWRITING_REQUIRED`. Pending candidates never trigger re-underwriting.
Both CLI and Workbench display **Pending approval** and **Pending non-comparable
assessment** independently. Later approved NOISE cannot erase an approved thesis
update/break.
Newer underwriting starts a new since-underwriting window; older events and
their exact links remain in complete company history. This does not assert that
every old issue was resolved. The summary states its scope explicitly.

SQLite schema 9 adds event/approval tables with source foreign keys, content
hashes and update/delete/replace rejection triggers. Atomic validated saves
reject fabricated source links and changed candidate results. Saved event
assessments and approved triggers are read without rerunning newer rules.
Canonical sorted JSON preserves stable output for the same event/approval state.
Approval intentionally changes the assessment envelope, not the event record.

## Synthetic ADBE assessment

The [sample event](../examples/adbe_change.sample.json) is synthetic, not an Adobe
disclosure. If the exact selected underwriting contains dependency `arr-growth`:

```text
Previous dependency: ARR growth remains at least 7%.
Observable: ARR growth YoY, constant currency
Threshold: >= 7%
Cadence: Quarterly
Source title: Fixture company report

Observed FACT (manually verified synthetic fixture): 5.8%
Condition result: CONDITION_BREACHED
Candidate: THESIS_UPDATE
Approved classification: PENDING_APPROVAL
Trigger: PENDING_APPROVAL

Investor approves THESIS_UPDATE with rationale:
Revisit growth persistence and base-case trajectory.

Trigger: NEW_UNDERWRITING_REQUIRED
Affected: linked Base revenue CAGR, Base probability and dependency.
Decision implication: Recorded WATCH decision should be revisited, if present.
Sizing: historical ceiling displayed; effect NOT_DETERMINED unless explicitly linked.
New underwriting saved: none.
```

Replace condition IDs, pointers, dates, source and definitions with those from
your own exact snapshot. Incompatible definitions stay NOT_COMPARABLE;
nonexistent condition IDs are rejected, never silently dropped.

## Workbench workflow

Open **What Changed?**, select an exact completed underwriting version and
optionally select its dependency/breaker. Paste/import complete event JSON and
explicitly record a pending event. An imported condition ID conflicting with the
selector is rejected. Review the threshold result, candidate, affected beliefs,
frozen context and downloadable JSON.

Select an approved classification with no preselected default and provide an
approval/override rationale. Only **Explicitly approve classification** appends
approval. The company summary aggregates all relevant events rather than showing
only the latest one.

For an approved update/break, **Start from latest underwriting** explicitly
initializes an independent draft from the company's then-latest saved beliefs.
It does not substitute that latest version into the event. The existing Feature
8 authoring workflow opens on this page so you can edit only changed beliefs,
review persisted evidence context, then explicitly save a new immutable version.
No automatic draft save occurs. The original event, underwriting, decision and
sizing remain unchanged.

## Manual PowerShell validation

These are user-run commands; no live validation was performed. Review and edit
the synthetic example before saving to your chosen local store. Replace version
7 with an exact completed underwriting and use condition IDs/pointers actually
present in that snapshot.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src

New-Item -ItemType Directory -Force .\data\changes | Out-Null
Copy-Item .\docs\examples\adbe_change.sample.json .\data\changes\adbe-q4.json
notepad .\data\changes\adbe-q4.json

$event = uv run owner-lens change create ADBE --version 7 --file .\data\changes\adbe-q4.json --json | ConvertFrom-Json
uv run owner-lens change show $event.event_id
uv run owner-lens change assess $event.event_id --json
uv run owner-lens change summary ADBE --json

$a = uv run owner-lens change assess $event.event_id --json
$b = uv run owner-lens change assess $event.event_id --json
if ($a -cne $b) { throw "Non-reproducible change assessment" }

uv run owner-lens change approve $event.event_id --classification THESIS_UPDATE --rationale "Revisit growth persistence and the base-case trajectory."
uv run owner-lens change history ADBE
uv run owner-lens change summary ADBE
uv run owner-lens workbench
```

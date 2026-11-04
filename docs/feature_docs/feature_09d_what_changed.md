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

## Company Monitor golden path

Open **Company -> Monitor** for the selected company. The initial monitoring
baseline is the completed underwriting shown by Company (normally the latest
completed version). If Company is inspecting an incomplete version, Monitor
instead discovers the latest fully analyzed version. A review pins the exact
UUID/version/hash in session state, and subsequent reruns do not substitute a
newer underwriting. Newer incomplete versions are disclosed without replacing
the completed thesis. An explicit **Start a new review on latest completed
underwriting** action changes the baseline when no evidence submission is active.

The compact view shows underwriting as-of, readable dependencies/breakers and
literal thresholds, authoritative thesis status, pending and non-comparable
counts, recent approved events, and whether re-underwriting is required.
Predicates, UUIDs, hashes and full provenance remain in advanced details.
Opening Monitor, previewing evidence or exporting context creates no records.

The cleanup addresses an occasional but consequential workflow, usually around
new company developments. Previously the investor left Company, chose an exact
version again in What Changed?, created a pending event, selected that event
again, approved separately and initialized a separate draft editor. The primary
path is now:

1. **Record New Evidence** and paste existing 9D event JSON.
2. **Validate + Preview** to validate and run the existing deterministic
   assessment without persistence.
3. Choose an investor classification and rationale.
4. **Record & Approve Change** once.
5. Continue monitoring, or **Prepare Re-underwriting** when the authoritative
   summary requires it.

The JSON input uses the existing event schema below. Company/security identity
and the exact underwriting are supplied by the selected context, never typed or
inferred from source prose. An optional condition picker supplies its exact
frozen ID; a conflicting JSON condition is rejected. Unknown fields, including
attempted company/security overrides, are rejected by the existing validator.
An existing JSON file can be loaded as a secondary input. Editing JSON or
condition selection invalidates the preview.

Observation/recording timestamps, observed values, source references, metric
definitions, units, cadence and source family are not manufactured. Source
verification remains the investor's assertion, not an OwnerLens verification
claim. The preview separates observed evidence, frozen condition, comparability,
met/breached result, candidate classification and affected frozen beliefs.
Structured predicates retain exact matching. Legacy qualitative conditions
remain explicitly non-comparable when the existing engine cannot assess them.

No classification is preselected, even when the deterministic candidate is
THESIS_UPDATE or THESIS_BREAK. The investor must supply a classification and a
nonempty rationale. The existing approval compatibility rules remain unchanged.

### Summary and review scope

Company Monitor applies existing 9D precedence to events observed since the
pinned completed underwriting's creation, including links to other versions:

1. Approved THESIS_UPDATE or THESIS_BREAK: REUNDERWRITING_REQUIRED.
2. Otherwise pending events: REVIEW_PENDING.
3. Otherwise approved EVIDENCE: REVIEW_RECOMMENDED.
4. Otherwise: NO_REUNDERWRITING_REQUIRED.

The scope and baseline are shown explicitly. A newer incomplete underwriting
does not reset this cutoff. Later NOISE cannot erase an approved update/break
within that scope. Pending events never count as approved changes. The full
company timeline includes events outside the current summary scope and labels
each event's exact underwriting version, assessment and approval separately.
Standalone What Changed? and CLI summary defaults retain their existing latest
record scope; their lower-level commands remain available.

### Immutable recording and retries

The [application workflow](../../src/owner_lens/monitoring_workflow.py) reuses
9D build/validate/assessment, storage and approval services. Streamlit performs
no thesis matching or investment calculation. **Record & Approve Change** creates
an immutable event and a separate immutable approval through the existing
transactional boundaries; the two records are not collapsed into a new schema.

Before any event write, classification and rationale are validated and the
submission is frozen in session state with a stable event UUID. If either write
or its UI receipt fails, the same submission can be retried. The service reuses
an identical event and an identical existing approval, and rejects conflicting
retries. A created but unapproved event is shown as pending, not successful
approval. **Retry Record & Approve Change** finishes that same event. Inputs
are locked while a submission is pending recovery.

After a session loss, a persisted pending event remains in the timeline and
can be completed with **Approve Recorded Change**, without recreating evidence.
A persisted approval also remains visible after a lost receipt. If no event
was committed before session loss, there is nothing to recover. Do not repaste
an already recorded event as new evidence.

### Re-underwriting without an automatic thesis revision

After approval the authoritative status is displayed immediately. NOISE or
EVIDENCE alone does not demand a new underwriting; the investor can leave
without another action. An earlier approved thesis change can still require
re-underwriting even when the most recent event is NOISE.

When required, **Prepare Re-underwriting** opens the existing JSON-first
authoring state in the Company's **Underwriting** tab. It does not generate
revised assumptions or replace an existing editor's JSON. **Copy Re-underwriting
Context** displays selectable text with the exact monitored identity, approved
evidence/rationale, linked conditions and beliefs, prior Bear/Base/Bull scenarios,
and the existing sanitized research context. It labels pasted content as
untrusted research data and preserves the no-source-verification caveat.
Pending events are counted, never exported as approved changes.

Discuss that context in ChatGPT, prepare revised investor-reviewed Authoring v2
JSON, then use Cleanup 1's **Paste JSON -> Validate + Preview -> Commit & Analyze**.
No underwriting, probability, decision or sizing is changed by monitoring or
by preparing/exporting the handoff. A newly committed underwriting remains a
separate immutable version.

### Manual Company validation

No live validation was performed for this cleanup. Use your existing completed
ADBE underwriting and evidence you actually reviewed for the ordinary path.

#### A. Ordinary evidence

1. Open Workbench, select the appropriate persisted provider and ADBE Company,
   then open **Monitor**.
2. Confirm company, completed version and as-of date. Inspect dependencies,
   breakers, status and pending counters. Expand advanced identity details.
3. If a newer incomplete version exists, confirm the warning. It must not
   replace the monitored completed version.
4. Choose **Record New Evidence**. Paste your existing valid 9D event JSON.
   Supply real event/observation dates, provenance and interpretation; do not
   label unverified pasted text as FACT. Select a frozen condition only when
   the observation genuinely targets it.
5. Choose **Validate + Preview**. Compare observable, value, unit, cadence,
   source family and provenance with the frozen condition. Mismatches must
   remain NOT_COMPARABLE or INSUFFICIENT_DATA. Candidate is not approval.
6. Confirm history is unchanged. Choose EVIDENCE or NOISE only if it reflects
   your judgment, enter a rationale, and choose **Record & Approve Change**.
7. Check the receipt and timeline: one event, one separate approval, correct
   exact underwriting and rationale. If there are no other approved thesis
   changes or pending events in scope, EVIDENCE gives REVIEW_RECOMMENDED and
   NOISE gives NO_REUNDERWRITING_REQUIRED. Existing events may take precedence.
8. Rerun or reopen Monitor. Counts must not grow. Underwriting, decision and
   sizing histories must remain unchanged. No re-underwriting action is needed
   for ordinary evidence alone.

#### B. Thesis change in an isolated database

1. Use a separate test database already containing a completed fixture ADBE
   underwriting. Launch Workbench with its explicit `--db` path. Confirm the
   active database before proceeding; never use the real investment store for
   synthetic evidence.
2. Open ADBE **Monitor**. Record baseline history counts and exact identity.
3. Choose **Record New Evidence** and paste a valid test event with a statement,
   interpretation and verification note clearly labeled SYNTHETIC TEST. Supply
   explicit compatible metric/source metadata if exercising a structured
   predicate. Otherwise leave the condition unlinked and expect insufficient
   assessment rather than invented numeric matching.
4. Choose **Validate + Preview**. Confirm that no event has yet been saved.
   Choose THESIS_UPDATE explicitly and enter a synthetic-test rationale.
5. Choose **Record & Approve Change**. Confirm REUNDERWRITING_REQUIRED. In this
   isolated store only, approving a later NOISE event must not erase the update.
6. Choose **Prepare Re-underwriting**, then **Copy Re-underwriting Context**.
   Copy the displayed text and confirm exact identity, approved test rationale,
   linked beliefs/conditions, prior scenarios and research context.
7. Use the context for a ChatGPT discussion, retaining its synthetic label.
   Prepare revised Authoring v2 JSON through investor reasoning, not automatic
   probability or assumption changes in OwnerLens.
8. Open the same Company's **Underwriting** tab. Paste the revised JSON and use
   **Validate + Preview**. Only if intentionally testing a new version in the
   isolated database, choose **Commit & Analyze**. The prior underwriting and
   change history must remain immutable.
9. For controlled failure testing in an isolated environment, interrupt approval
   after event persistence. Confirm REVIEW_PENDING and the same pending event
   ID, then retry. Event and approval counts must each end at one for that
   submission. Reopening a lost session permits approval from its timeline.

Follow-up candidates, not implemented: a provenance-aware event template
generator, durable recovery of entirely uncommitted drafts, and large-history
monitoring performance profiling. No retrieval or scheduled monitoring is added.

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

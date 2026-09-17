# Feature Specification: Persisted Single-Company Ingestion

**Feature Branch**: `014-persisted-single-company-ingestion`

**Created**: 2026-09-17

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 4B: Persisted Single-Company Ingestion. Turn the existing local ingestion script into a first-class OwnerLens ingestion workflow that accepts a ticker, retrieves live SEC Company Facts, runs the maximum trustworthy analysis supported for that company, persists all valid outputs locally, and clearly reports what succeeded or failed."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ingest a company and persist everything trustworthy (Priority: P1)

An OwnerLens owner-analyst names a single company by its stock ticker and asks OwnerLens to bring
that company into the local store. OwnerLens resolves the company's identity, retrieves its source
financial facts, runs every analytical layer the company's data can honestly support, saves the raw
source evidence and all valid outputs locally, and returns one concise report describing what was
retrieved, what was persisted, and how complete the analysis is.

**Why this priority**: This is the core promise of the slice — turning validated analytical code into
a repeatable operational workflow. Without it there is no first-class ingestion; everything else
(partial handling, idempotency, history) only refines this single act. It is independently valuable:
a user can populate the store for one fully supported company and immediately inspect trustworthy,
provenance-linked results.

**Independent Test**: Ingest a fully supported company (Adobe) and confirm that the raw source
snapshot, company identity, source-snapshot metadata, reported facts, derived metrics, analyses, and
coverage are all persisted, and that the returned result reports a complete outcome with accurate
counts and coverage.

**Acceptance Scenarios**:

1. **Given** a fully supported company ticker and an empty local store, **When** the analyst ingests
   that company, **Then** OwnerLens persists the raw source payload, company identity, source snapshot,
   reported facts, derived metrics, analyses, and coverage, and reports a complete outcome.
2. **Given** a successful ingestion, **When** the analyst reads the returned result, **Then** it states
   the company, the source snapshot identity, an unambiguous status, the counts of persisted facts /
   metrics / analyses, per-layer coverage, and any warnings or unsupported items — without a bare
   success/failure boolean.
3. **Given** a company that ingests fully, **When** the process ends and a brand-new process queries the
   store, **Then** the persisted results are returned from storage alone, independent of any in-memory
   state.

---

### User Story 2 - Preserve honest partial results for companies OwnerLens cannot fully analyze (Priority: P2)

An analyst ingests a company whose source data does not support every OwnerLens metric (for example a
company whose diluted share representation OwnerLens does not safely normalize). OwnerLens still
retrieves and stores the raw evidence, persists every layer that is trustworthy, records the exact
reason the unsupported metrics could not be produced, and reports the outcome as a legitimate partial
ingestion rather than a failure — never fabricating the missing values.

**Why this priority**: A universe of real companies does not behave like the golden set. Preserving
everything trustworthy while explicitly marking what is unsupported is what makes ingestion honest and
prepares OwnerLens to scale. It builds directly on P1 but is separately testable and separately
valuable.

**Independent Test**: Ingest a company with a known unsupported metric (Visa) and confirm that the
independent layers persist, the unsupported metric is recorded as an explicit coverage limitation with
its reason, no value is fabricated, and the result status reflects partial (processed) coverage rather
than failure.

**Acceptance Scenarios**:

1. **Given** a company with an unsupported required metric, **When** the analyst ingests it, **Then**
   OwnerLens persists the raw snapshot and every trustworthy layer, and records the unsupported metric
   as an explicit coverage state with a human-readable reason.
2. **Given** such a partial ingestion, **When** the analyst reads the result, **Then** the status
   indicates a processed company with partial analytical coverage, and the report shows which layers are
   full and which are limited, with the reason.
3. **Given** a metric OwnerLens cannot safely normalize, **When** ingestion runs, **Then** no value is
   guessed, coerced, or backfilled, and the failure of that metric does not abort unrelated layers that
   can still be produced.

---

### User Story 3 - Idempotent re-ingestion and historical source snapshots (Priority: P3)

An analyst ingests the same company again. If the source financial facts are byte-for-byte the same as
what was already stored, OwnerLens recognizes the unchanged source and does not duplicate any stored
data, reporting an unchanged outcome. If the source content has changed since the last ingestion,
OwnerLens records a new source snapshot alongside the previous one rather than overwriting history, so
the store accumulates a truthful timeline of source states.

**Why this priority**: Idempotency and source history are what make repeated ingestion safe and make
OwnerLens ready for future "what changed" questions. They are essential for operational trust but only
meaningful once ingestion (P1) and honest coverage (P2) exist.

**Independent Test**: Ingest a company twice with identical source content and confirm no duplicate raw
payload, source snapshot, facts, metrics, or analyses are created and the second result reports an
unchanged outcome; then ingest with changed source content and confirm a new snapshot is created while
the previous snapshot is retained.

**Acceptance Scenarios**:

1. **Given** a company already ingested, **When** the analyst re-ingests it with identical source
   content, **Then** no duplicate stored data is created and the result reports an unchanged outcome.
2. **Given** a company already ingested, **When** the analyst re-ingests it and the source content has
   changed, **Then** OwnerLens creates a new source snapshot and retains the previous one.
3. **Given** an unchanged re-ingestion, **When** the workflow detects the identical source and the same
   calculation and analysis-rule versions already exist, **Then** it may skip redundant recomputation
   while still returning an accurate unchanged result.

---

### Edge Cases

- **Unresolvable ticker**: The ticker is not present in the source ticker mapping. OwnerLens reports a
  retrieval failure that clearly distinguishes "company not found" from network or data problems, and
  writes nothing.
- **Source unavailable or malformed**: The source service is unreachable, times out, or returns an
  unusable response. OwnerLens reports a retrieval failure distinct from unsupported-metric and
  persistence problems, and writes nothing (no raw snapshot for an un-retrieved payload).
- **Raw stored but analysis fails**: The raw payload is retrieved and stored, but a downstream
  analytical layer fails. OwnerLens preserves the raw evidence, marks the processing status to reflect
  that the source exists even though processing did not complete, and reports the failure class.
- **Insufficient data for a trend**: A trustworthy metric exists for too few years to compute a
  multi-year trend. OwnerLens reports this as insufficient data for that specific analysis, distinct
  from an unsupported metric, and still persists what is available.
- **Persistence failure mid-write**: A storage write fails partway through the structured (analytical)
  writes. The raw source snapshot may remain independently, but the structured results for the
  processed analytical snapshot must not be left in a misleading half-written state.
- **Company with no unsupported metrics but a thin history**: Layers that need multiple years degrade to
  insufficient-data coverage rather than being reported as unsupported or as failures.
- **Arbitrary previously untried company**: The analyst ingests a company never validated before.
  OwnerLens attempts as much as it can honestly support and reports the honest coverage; it must not
  claim full analyzability for a company it has not verified.

## Requirements *(mandatory)*

### Functional Requirements

**Ingestion workflow**

- **FR-001**: OwnerLens MUST provide a first-class ingestion workflow that accepts a single company
  ticker and produces one structured ingestion outcome.
- **FR-002**: The ingestion workflow MUST resolve the company identity from the source ticker mapping,
  retrieve the raw source financial facts, and run the analytical layers the company's data supports.
- **FR-003**: The ingestion workflow MUST persist all trustworthy outputs locally: the raw source
  payload, the company identity, the source-snapshot metadata, reported facts, derived metrics, the
  analyses that could be produced, and the coverage picture.
- **FR-004**: The reusable ingestion logic MUST live at the application/domain boundary and MUST NOT be
  owned exclusively by a standalone script. Any remaining script MUST be a thin caller of that logic,
  and OwnerLens MUST NOT maintain two divergent ingestion implementations.
- **FR-005**: Persistence writes MUST NOT be embedded inside financial calculation, normalization, or
  classification logic; the analytical layers MUST remain storage-independent.

**Structured result**

- **FR-006**: The ingestion workflow MUST return a deterministic result object that reports the company,
  the source snapshot, an unambiguous status, the persisted fact / metric / analysis counts, the
  coverage picture, any warnings, and any unsupported items. It MUST NOT reduce the outcome to a bare
  success/failure boolean.
- **FR-007**: The result status MUST distinguish, at minimum, a complete outcome, a partial (processed
  but not fully analyzable) outcome, an unchanged (already-present source) outcome, and a failed
  outcome.

**Honest partial coverage**

- **FR-008**: The ingestion workflow MUST NOT assume every company is fully analyzable. When a required
  metric cannot be safely normalized, OwnerLens MUST record an explicit coverage limitation with a
  human-readable reason and MUST preserve every unrelated layer that can still be produced.
- **FR-009**: OwnerLens MUST NOT guess, backfill, coerce, or fabricate any financial value to complete
  an output, and MUST NOT weaken a metric's meaning merely to increase coverage.
- **FR-010**: A company with legitimate partial analytical coverage MUST be reported as processed with
  partial coverage, not as a failed ingestion.

**Failure classes**

- **FR-011**: The ingestion outcome MUST distinguish these failure classes from one another: retrieval
  failure (source unavailable, unresolved ticker, malformed response), unsupported financial
  representation (a required metric cannot be safely normalized), insufficient data (a trustworthy
  metric exists for too short a history to complete a specific analysis), and persistence failure
  (a storage write error).

**Raw evidence first**

- **FR-012**: OwnerLens MUST persist the raw source snapshot before or alongside downstream processing,
  so that a successfully retrieved source is recorded even if a later analytical layer fails. Raw
  evidence MUST NOT be discarded because a downstream layer failed.
- **FR-013**: OwnerLens MUST record a meaningful processing status for each source snapshot that can
  express at least: retrieved-but-unprocessed, fully processed, processed with partial coverage, and
  failed processing.

**Idempotency and history**

- **FR-014**: When the same company is ingested again with source content identical to what is already
  stored (same company identity and same source content fingerprint), OwnerLens MUST NOT create
  duplicate raw payloads, source snapshots, facts, metrics, or analyses, and MUST return an unchanged
  outcome.
- **FR-015**: When re-ingesting the same company whose source content has changed, OwnerLens MUST create
  a new source snapshot and MUST retain the previous snapshot rather than overwriting history.
- **FR-016**: When an unchanged source snapshot and the same calculation and analysis-rule versions are
  already present, OwnerLens SHOULD skip redundant recomputation while still returning an accurate
  unchanged result.

**Transaction and failure semantics**

- **FR-017**: If ingestion fails partway through the structured analytical writes, OwnerLens MUST NOT
  leave the structured results for that processed analytical snapshot in a misleading half-written
  state; the raw source snapshot MAY exist independently. The chosen failure semantics MUST be
  documented.

**Command-line experience**

- **FR-018**: OwnerLens MUST expose the ingestion workflow as a first-class command of the form
  `ingest <ticker>`, extending the existing command-line interface. The command MUST parse arguments,
  load configuration, build local dependencies, invoke ingestion, format the result concisely, and set
  an exit code that reflects the outcome.
- **FR-019**: The command MUST support choosing the number of fiscal years of history to analyze, and
  MUST NOT add operational flags beyond what this slice requires. Any bypass of idempotency MUST be
  offered only if a genuine need is established.
- **FR-020**: The command output MUST be concise and owner/developer friendly — showing company
  identity, source snapshot and status, persisted counts, per-layer coverage, and the overall economic
  value classification — and MUST NOT dump all raw financial values by default. A partially supported
  company MUST visibly show partial coverage and the exact reason.

**Optional inspection**

- **FR-021**: OwnerLens MAY provide a small inspection command of the form `show <ticker>` that reads
  the latest persisted summary and coverage from storage. This MUST remain optional and MUST NOT expand
  the slice into a broad query interface.

**Golden-company preservation and generalization policy**

- **FR-022**: The new ingestion workflow MUST preserve the existing behavior of the golden companies:
  Adobe and Costco ingest fully, and Visa ingests with honest partial coverage because its diluted
  share representation remains unsupported. Ingestion becoming generic MUST NOT change these semantics.
- **FR-023**: A company-specific source-concept override MUST be added only when a genuine source
  taxonomy difference is exposed, its economic meaning is clear, the selected concept is verified from
  source data, the default mapping is wrong or stale or missing, and the override preserves canonical
  meaning. Overrides MUST flow through the canonical metric registry and MUST NOT be scattered as
  ticker-specific hacks in the orchestration. An override MUST NOT be added merely to obtain full
  coverage.

**Persistence composition**

- **FR-024**: The ingestion workflow MUST reuse the existing local persistence composition (local
  relational store over the local raw-snapshot store) built from configuration, and MUST introduce no
  cloud dependencies.

### Key Entities *(include if feature involves data)*

- **Ingestion Request**: The analyst's intent to bring one company into the store — the target company
  ticker and how many fiscal years of history to analyze.
- **Ingestion Result**: The deterministic outcome of one ingestion — the resolved company, the source
  snapshot reference, an unambiguous status (complete / partial / unchanged / failed), persisted fact /
  metric / analysis counts, the coverage picture, warnings, and unsupported items.
- **Source Snapshot**: A recorded source-retrieval event for a company, identified by a content
  fingerprint of the raw payload, carrying a processing status and a link to the stored raw evidence.
  Multiple snapshots for one company coexist to form a source history.
- **Processing Status**: The state of a source snapshot's downstream handling — retrieved-but-unprocessed,
  processed, processed-with-partial-coverage, or failed.
- **Coverage Picture**: The per-input and per-layer trustworthiness report for a company (available,
  partial, insufficient-data, unsupported, structurally-absent), each limitation carrying its reason.
- **Failure Class**: The category of an unsuccessful outcome — retrieval, unsupported representation,
  insufficient data, or persistence — kept distinct from one another.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An analyst can ingest a single company end-to-end with one command and receive a concise
  outcome report in a single step, without editing code or copying a script.
- **SC-002**: For a fully supported company, 100% of the produced layers (raw evidence, identity, source
  snapshot, facts, metrics, analyses, coverage) are persisted and are retrievable by a fresh process
  that shares no in-memory state.
- **SC-003**: For a company with an unsupported metric, ingestion completes as a processed/partial
  outcome, every trustworthy layer is preserved, and the unsupported metric is recorded with an
  explicit reason — with zero fabricated values.
- **SC-004**: Re-ingesting a company whose source content is unchanged creates zero duplicate stored
  rows across raw payload, source snapshot, facts, metrics, and analyses, and reports an unchanged
  outcome.
- **SC-005**: Re-ingesting a company whose source content has changed results in exactly one additional
  source snapshot while every earlier snapshot remains retrievable.
- **SC-006**: Every reported financial fact and analysis in the store is linked to the source snapshot
  it was produced from (100% provenance linkage).
- **SC-007**: The four failure classes (retrieval, unsupported, insufficient data, persistence) are each
  reported distinctly, verified by a test for each class.
- **SC-008**: The three golden companies retain their prior semantics: Adobe full, Costco full, Visa
  honest partial — with no regression in any existing test.
- **SC-009**: At least two previously unvalidated but resolvable companies can be attempted safely and
  return an honest coverage report without crashing and without fabricating values.
- **SC-010**: A future collaborator can understand the persistence and ingestion layer (4A model, 4B
  ingestion, idempotency, source history, coverage behavior, deferred cloud persistence) from the
  feature documentation alone, without reading conversation history.

## Assumptions

- **Users and interface**: The "user" is an OwnerLens owner-analyst or developer working locally via the
  existing command-line interface; there is no web or multi-user surface in this slice.
- **Local-first persistence**: Ingestion targets the existing local storage established in Slice 4A —
  a local relational store for structured outputs and a local content-addressed store for raw payloads —
  built from local configuration. No cloud, external database, or object-storage dependency is
  introduced. Azure persistence is intentionally deferred and out of scope.
- **Source of facts**: The single source of financial facts is the existing SEC Company Facts retrieval
  capability; identity resolution uses the existing SEC ticker mapping. This slice does not add new data
  providers.
- **Content fingerprint**: "Same source content" is judged by the existing content-hash of the raw
  payload combined with the company identity; a differing hash means changed source content.
- **Version identity for skip decisions**: The existing calculation-version and analysis-rule-version
  identifiers determine whether recomputation can be safely skipped for an unchanged source.
- **Golden companies as fixtures**: Adobe, Visa, and Costco remain deterministic regression fixtures and
  define the expected full / partial / full behavior.
- **Exploration companies**: Two conventional, source-resolvable operating companies (for example
  Microsoft and Salesforce) are used to discover normalization gaps; their success is not a completion
  criterion — the goal is honest discovery, not guaranteed full coverage.
- **Educational notebook**: A runnable educational notebook accompanies this slice to demonstrate
  ingestion versus analysis, full and partial ingestion, idempotent re-ingestion, source history, an
  unseen company, and the gaps that must close before batch ingestion.
- **Out of scope**: Cloud persistence, external databases, object storage, batch/universe ingestion,
  concurrency, job queues, schedulers, large-index ingestion, scores, screeners, valuation,
  market-price data, agents, an API service, a web UI, and any industry-specific normalization
  framework or external normalized-data provider.

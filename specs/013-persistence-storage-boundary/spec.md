# Feature Specification: Persistence Model and Storage Boundary

**Feature Branch**: `013-persistence-storage-boundary`

**Created**: 2026-09-04

**Status**: Draft

**Input**: User description: "Implement OwnerLens Slice 4A: Persistence Model and Storage Boundary — introduce the first persistence layer for OwnerLens without changing its financial-analysis semantics and without introducing Azure infrastructure yet."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reproduce a company's economic-value analysis from local storage (Priority: P1)

An OwnerLens user runs the existing analysis pipeline for a company (for example Adobe), then persists the
resulting company identity, source-snapshot metadata, canonical reported facts, derived metrics, Feature 2
analysis outputs, and coverage states to a local durable store. Later, in a fresh session and without
re-fetching from SEC, the user reopens the store and retrieves the latest Economic Value Summary and a
multi-year metric history that exactly match what the pipeline computed in memory.

**Why this priority**: This is the core of Slice 4A. Without durable, faithful round-tripping of the four
output layers (facts, metrics, analysis, coverage), no other persistence capability has value. Delivered
alone it already lets a user reproduce and query prior analytical states offline, which is the primary
question the slice answers.

**Independent Test**: Persist a full ADBE analysis to a fresh local store, close it, reopen it, and retrieve
the latest summary plus a five-year FCF/share history. The retrieved values must equal the in-memory
OwnerLens outputs.

**Acceptance Scenarios**:

1. **Given** a freshly created local store, **When** the store is initialized, **Then** the schema and its
   version metadata exist and re-initializing the same store does not error or duplicate structures.
2. **Given** an in-memory ADBE analysis, **When** its company identity, snapshot metadata, canonical facts,
   derived metrics, analysis outputs, and coverage states are saved, **Then** each layer is retrievable and
   equal in value to the source computation.
3. **Given** a store containing five fiscal years of ADBE derived metrics, **When** the user requests
   ADBE FCF/share for the latest five fiscal years, **Then** the store returns the five values in fiscal-year
   order with units preserved.
4. **Given** a store containing an ADBE Economic Value Summary, **When** the user requests the latest summary
   for ADBE, **Then** the returned classification and its ordered drivers match the persisted analysis.

---

### User Story 2 - Preserve provenance and semantic missing-data states across persistence (Priority: P2)

An OwnerLens user needs to trust stored values as much as freshly computed ones. When they persist facts for
a company such as Costco, each canonical fact retains the SEC concept, form, filing date, accession number,
and originating source snapshot. When they persist a company such as Visa that has unsupported diluted-share
data, the coverage state remains explicitly `UNSUPPORTED` rather than collapsing to a null or a zero.

**Why this priority**: Provenance and semantic missing-data distinctions are non-negotiable OwnerLens
invariants (constitution principles II and V). Persistence that silently loses lineage or coerces
absence/unsupported/insufficient into `NULL` or `0` would corrupt trust. This builds on P1 storage but is
separable: it can be verified independently by inspecting stored provenance and coverage semantics.

**Independent Test**: Persist COST FY2025 revenue and Visa coverage, then query them back. The revenue record
must expose its source SEC concept and filing identifiers; Visa's diluted-shares coverage must read
`UNSUPPORTED` and its reported zero repurchases (where applicable) must remain a genuine zero.

**Acceptance Scenarios**:

1. **Given** a persisted COST FY2025 revenue fact, **When** the user asks which SEC concept and filing
   produced it, **Then** the store returns the canonical metric name, the distinct source concept, the form,
   the filing date, the accession number, and the source snapshot reference.
2. **Given** persisted Visa coverage, **When** the user asks what layers are unavailable and why, **Then**
   the store returns `UNSUPPORTED` for diluted shares with its recorded reason, and does not represent it as a
   missing storage field.
3. **Given** a persisted fact whose real observed value is zero, **When** it is retrieved, **Then** it remains
   an explicit zero and is distinguishable from an absent or unsupported value.
4. **Given** a persisted Feature 2 layer that was `INSUFFICIENT_DATA`, **When** it is retrieved, **Then** its
   coverage state is still `INSUFFICIENT_DATA` and is not confused with `AVAILABLE` or `UNSUPPORTED`.

---

### User Story 3 - Idempotent re-processing and retained historical snapshots (Priority: P3)

An OwnerLens user re-runs persistence for a source snapshot they already stored (for example after a repeated
analysis run). Re-saving identical data does not create duplicate companies, snapshots, facts, metrics, or
analysis rows. Separately, when a genuinely new snapshot is stored for the same company over time, earlier
snapshots and the facts/metrics/analyses derived from them are retained rather than overwritten, so the store
can later answer "what did OwnerLens know after this filing".

**Why this priority**: Idempotency and historical retention prepare the model for future batch ingestion and
reproducibility without building either now. They depend on the P1 model existing and on the P2 identity keys
being stable, so they come last while still being independently demonstrable.

**Independent Test**: Persist the same ADBE snapshot twice and confirm row counts are unchanged after the
second write; then persist a distinct later snapshot for ADBE and confirm both snapshots (and their derived
records) coexist and are individually retrievable.

**Acceptance Scenarios**:

1. **Given** a store already containing an ADBE company and snapshot, **When** the identical identity and
   snapshot are saved again, **Then** no duplicate rows are created and existing records are unchanged.
2. **Given** a store containing one ADBE snapshot, **When** a second, distinct ADBE snapshot is saved,
   **Then** both snapshots and their associated facts, metrics, and analyses are retained and separately
   retrievable.
3. **Given** persisted metrics for ADBE, Visa, and Costco, **When** the user requests the latest ROIC for all
   three, **Then** the store returns each company's most recent ROIC value with units, drawing from the latest
   applicable snapshot per company.

---

### Edge Cases

- What happens when a retrieval targets a company or metric that has never been persisted? The store MUST
  return an explicit empty result, not fabricate a value or raise a financial-domain error.
- What happens when two distinct values are presented for the same natural key within one write (a genuine
  conflict, not an identical repeat)? The store MUST surface a persistence-layer conflict rather than silently
  keeping the last write or coercing the values.
- How does the store behave when initialization runs against an already-initialized store? It MUST be a safe
  no-op that preserves existing data and version metadata.
- How does the store behave when the underlying storage cannot be opened, written, or read? It MUST raise a
  persistence-category error distinct from OwnerLens financial errors (for example concept-not-found or
  insufficient-data).
- What happens when a stored schema version differs from the version the running code expects? The store MUST
  surface an explicit schema/version incompatibility rather than reading data under wrong assumptions.
- How are exact monetary values and share counts preserved so that no silent rounding occurs during
  persistence and retrieval?

## Requirements *(mandatory)*

### Functional Requirements

#### Persistence boundary and separation of concerns

- **FR-001**: The persistence layer MUST store only outputs produced by existing OwnerLens layers and MUST NOT
  perform SEC normalization, financial calculation, classification, or company-specific accounting logic.
- **FR-002**: Financial calculation and analysis functions MUST remain free of persistence side effects;
  saving MUST occur through explicit orchestration (for example `store.save_analysis(result)`) rather than
  hidden writes inside computation functions.
- **FR-003**: The system MUST expose a small, domain-oriented persistence interface driven by current use
  cases (save company identity, save source-snapshot metadata, save canonical facts, save derived metrics,
  save analysis outputs, save coverage states, and the retrieval operations in FR-020..FR-024). It MUST NOT
  introduce generic CRUD abstractions such as a generic repository, generic DAO, or generic CRUD service.

#### Company identity

- **FR-004**: The system MUST persist stable company identity including ticker, CIK, and company name, and
  MUST NOT persist fabricated metadata.
- **FR-005**: The system MUST treat CIK as the strongest current SEC entity identifier and MUST allow ticker
  and company name to change over time without making CIK-based identity ambiguous.

#### Source snapshot metadata

- **FR-006**: The system MUST persist source-snapshot metadata sufficient to answer which source was queried,
  for which company, when it was fetched, which payload/version was analyzed, and how the raw source can be
  located later. Recorded metadata MUST include company/CIK, source provider (for example `sec`), source type
  (for example `company_facts`), fetched-at timestamp, a source URI or logical source identifier, and a
  content hash/checksum; an optional raw-object storage reference and a processing status MAY be recorded.
- **FR-007**: The relational persistence model MUST NOT store the full raw SEC JSON payload by default;
  instead it MUST reference raw snapshots. Raw payload storage for the local implementation MAY use the local
  filesystem, and the design MUST anticipate raw payloads moving to object storage later without reworking the
  relational model.

#### Canonical reported facts

- **FR-008**: The system MUST persist normalized reported observations in a long-form canonical representation,
  one record per observation, retaining at minimum: company identifier, canonical metric name, value, unit,
  fact kind (`duration` or `instant`), fiscal year, period start (where applicable), period end, source
  concept / XBRL tag, form, filing date, accession number, and a source-snapshot reference.
- **FR-009**: The system MUST preserve the distinction between a canonical metric name (for example `revenue`)
  and its underlying source concept (for example `SalesRevenueNet`), and MUST NOT reduce facts to wide tables
  that lose provenance.

#### Derived metrics

- **FR-010**: The system MUST persist deterministic derived metrics (for example FCF, operating margin, FCF
  margin, FCF/share, FCF growth, ROIC, net cash / net debt, economic-value change metrics) separately from
  reported facts.
- **FR-011**: Each derived-metric record MUST retain company, metric name, fiscal year or period scope, value,
  unit or semantic type where useful, a computed-at timestamp, and enough lineage to identify the canonical
  input period; it MUST link to the shared company/fiscal-period model rather than duplicating raw SEC
  provenance fields onto every derived metric. A calculation-definition version MAY be recorded where
  justified.

#### Analysis outputs

- **FR-012**: The system MUST persist higher-level deterministic Feature 2 analysis outputs (annual Economic
  Value Snapshot classification, multi-year compounding classification, capital allocation classification, and
  the Company Economic Value Summary) separately from raw facts and simple metrics.
- **FR-013**: Each analysis record MUST retain its classification, its structured drivers/reason codes in
  preserved order, its analysis period, a generated-at/computed-at timestamp, and MAY retain the version of the
  analytical rule set. The system MUST NOT persist free-form interpretive text, because these layers use no
  probabilistic judgment.

#### Coverage semantics

- **FR-014**: The system MUST preserve the existing coverage distinctions — `AVAILABLE`,
  `STRUCTURALLY_ABSENT`, `UNSUPPORTED`, `INSUFFICIENT_DATA`, and genuine reported zero — as explicit persisted
  states. It MUST NOT collapse these into SQL `NULL`. Storage `NULL` MAY represent an absent storage field but
  MUST NOT become the business meaning of an unavailable value.

#### Historical snapshots and reproducibility

- **FR-015**: The persistence model MUST support retaining multiple historical analytical states for a company
  over time and MUST NOT be structured as a single mutable latest-values row per company. It MUST allow future
  questions such as which snapshot produced a normalized fact and whether a later filing restated an earlier
  fiscal year, without requiring restatement/version-history resolution to be implemented in this slice.

#### Idempotency

- **FR-016**: The system MUST define stable natural or synthetic identifiers for company, source snapshot,
  canonical reported observation, derived metric, and analysis output such that repeated processing of the same
  source snapshot is idempotent (identical repeats create no duplicates). A simple deterministic uniqueness
  strategy MUST be used; no distributed idempotency framework may be introduced.

#### Data types and precision

- **FR-017**: The system MUST store exact monetary values and share counts without floating-point precision
  loss and MUST NOT silently round canonical values during persistence. Percentages/ratios MUST use a
  documented numeric representation, and units MUST be preserved explicitly.

#### Schema and definition versioning

- **FR-018**: The system MUST record a minimum viable schema version so that stored data is not treated as if
  metric and classification definitions are timeless. It MUST additionally support recording
  calculation-definition and analysis-rule versions where justified (see FR-011, FR-013). A full migration
  framework MUST NOT be introduced.

#### Failure semantics

- **FR-019**: The system MUST use persistence-category error types that are distinct from OwnerLens financial
  errors, covering at least: connection/setup failure, schema/version incompatibility, write failure, and
  read/query failure. Persistence errors MUST NOT be swallowed and MUST NOT be transformed into financial
  error semantics such as concept-not-found or insufficient-data.

#### Retrieval / query use cases

- **FR-020**: The system MUST support retrieving a company's multi-year history for a given metric (for
  example ADBE FCF/share for the latest five fiscal years), returned in fiscal-year order with units.
- **FR-021**: The system MUST support retrieving the provenance of a specific fact (for example which SEC
  concept and filing produced COST FY2025 revenue).
- **FR-022**: The system MUST support retrieving the latest Company Economic Value Summary for a company (for
  example ADBE), including its ordered drivers.
- **FR-023**: The system MUST support retrieving a company's coverage explanation (for example which layers are
  unavailable for Visa and why), preserving coverage states.
- **FR-024**: The system MUST support retrieving a single latest primitive metric across multiple companies
  (for example latest ROIC for ADBE, Visa, and Costco) as preparation for future comparison, without building
  any comparison, scoring, or screening feature in this slice.

#### Regression and scope

- **FR-025**: All existing Feature 1–3 behavior and tests MUST continue to pass unchanged; persistence MUST NOT
  alter financial-analysis semantics.
- **FR-026**: The slice MUST NOT introduce Azure SDKs, hosted PostgreSQL or Blob provisioning,
  infrastructure-as-code, batch/large-universe ingestion, scheduled refreshes, a migrations framework,
  authentication, an API service, agents, vector stores, scores, screeners, price/market data, or valuation.

### Key Entities *(include if feature involves data)*

- **Company**: A stable SEC entity. Key attributes: CIK (strongest current identifier), current ticker,
  current company name. Ticker/name may change over time; CIK anchors identity.
- **Source Snapshot**: A fetched SEC Company Facts payload event. Key attributes: owning company/CIK, source
  provider, source type, fetched-at, source URI/logical identifier, content hash/checksum, optional raw-object
  reference, optional processing status. References raw snapshot storage rather than embedding the payload.
- **Reported Fact**: One canonical normalized observation. Key attributes: company, canonical metric name,
  value, unit, fact kind (`duration`/`instant`), fiscal year, period start (optional), period end, source
  concept/XBRL tag, form, filing date, accession number, source-snapshot reference.
- **Derived Metric**: One deterministic calculated value. Key attributes: company, metric name, fiscal
  year/period scope, value, unit/semantic type, computed-at, canonical-input lineage, optional
  calculation-definition version.
- **Analysis Result**: One higher-level Feature 2 output. Key attributes: company, analysis type (annual
  snapshot / compounding / capital allocation / economic value summary), classification, analysis period,
  computed-at, optional analysis-rule version.
- **Analysis Driver**: A structured, ordered reason code belonging to an Analysis Result. Key attributes:
  owning analysis result, ordered position, driver code/category, and any structured payload the driver
  carries. Order MUST be preserved.
- **Coverage Result**: The persisted coverage state for a company (and its inputs/layers). Key attributes:
  company, subject (input or layer), coverage state (`AVAILABLE` / `STRUCTURALLY_ABSENT` / `UNSUPPORTED` /
  `INSUFFICIENT_DATA`), recorded reason, blocking input where applicable.
- **Schema/Version Metadata**: Store-level record of schema version and, where used, calculation-definition and
  analysis-rule versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can persist and then retrieve, in a fresh session without re-fetching SEC data, ADBE/V/COST
  company identity, at least one source-snapshot metadata record per company, canonical facts, derived metrics,
  Feature 2 analysis outputs, and coverage states, with 100% of retrieved values matching the corresponding
  in-memory OwnerLens outputs.
- **SC-002**: 100% of persisted canonical facts retain their source concept and filing provenance, verified by
  answering "which SEC concept and filing produced COST FY2025 revenue" directly from storage.
- **SC-003**: The four coverage states plus genuine reported zero survive a persist-and-retrieve round trip
  with zero cases collapsed into a null or a zero (verified via Visa unsupported diluted shares and an
  insufficient-data Feature 2 layer).
- **SC-004**: Re-persisting an identical source snapshot produces zero additional company, snapshot, fact,
  metric, or analysis rows, while persisting a distinct later snapshot retains both snapshots and their derived
  records.
- **SC-005**: A user can retrieve each of the five target queries — five-year ADBE FCF/share history, COST
  FY2025 revenue with provenance, latest ADBE Economic Value Summary, Visa coverage limitations, and latest
  ROIC across ADBE/V/COST — from the local store, and the results match live OwnerLens outputs.
- **SC-006**: Exact monetary values and share counts round-trip through persistence with no precision loss and
  no silent rounding.
- **SC-007**: The full existing Feature 1–3 automated test suite continues to pass, confirming financial
  calculation modules remain storage-independent.
- **SC-008**: Persistence failures surface through persistence-category errors and are never reported as
  financial errors such as concept-not-found or insufficient-data.

## Assumptions

- The default local durable store is SQLite, chosen for zero external service dependency, relational semantics
  close to a future PostgreSQL target, and easy local validation; the concrete access approach
  (standard-library `sqlite3` versus a lightweight toolkit) is a planning-phase decision constrained to the
  simpler option unless it demonstrably reduces future migration friction.
- Raw SEC payloads, if stored at all in this slice, are held on the local filesystem and referenced from
  relational metadata; object-storage (Blob) placement is deferred to Slice 4B.
- The values being persisted come from the already-validated ADBE/V/COST live analysis outputs produced by
  existing Feature 1–3 code; persistence does not recompute or re-fetch them.
- Coverage states, canonical metric names, source concepts, and Feature 2 classifications are taken as-is from
  the existing OwnerLens modules (`coverage.py`, `metrics.py`, and the Feature 2 modules) and are not
  redefined here.
- "Latest" for a company means the most recent applicable snapshot/period already present in the store;
  cross-company retrieval draws each company's latest independently.
- An educational notebook (`09_persistence_model.ipynb`) accompanies the slice per the constitution's
  requirement that meaningful new concepts include a runnable notebook.
- Local development remains sufficient for this slice; no hosted infrastructure is required (constitution
  Architecture and Delivery Constraints).

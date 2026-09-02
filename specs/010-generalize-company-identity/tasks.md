---
description: "Task list for Generalize Company Identity and SEC Ticker Resolution (Slice 3A)"
---

# Tasks: Generalize Company Identity and SEC Ticker Resolution

**Input**: Design documents from `specs/010-generalize-company-identity/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/public-api.md

**Tests**: Included. The feature specification explicitly requests controlled unit tests for ticker canonicalization, multi-company resolution, unknown and malformed input, source failures, identity mismatch, and raw-payload preservation.

**Organization**: Tasks are grouped by user story. The SEC client generalization is a small in-place edit that all stories depend on, so it is the foundational phase; each story then adds its controlled tests and validation.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US3)
- File paths are exact and relative to the repository root

## Path Conventions

Single Python project: source in `src/owner_lens/`, tests in `tests/`, notebooks in `notebooks/`.

---

## Phase 1: Setup

**Purpose**: Confirm a clean baseline before changing the SEC access layer

- [X] T001 Confirm the baseline is green by running `uv run pytest`, `uv run ruff check .`, and `uv run mypy src`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Generalize the SEC client so any mapped ticker resolves, and reconcile the public error surface. This blocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 In src/owner_lens/sec.py, add `MalformedTickerError(SecError)`, remove the `SUPPORTED_TICKER` constant and the `UnsupportedTickerError` class, and rewrite `resolve_company` to trim-and-uppercase the ticker, raise `MalformedTickerError` when the canonical ticker is empty (before any network access), then resolve any single valid mapping entry via the existing `_resolve_identity_from_mapping` machinery
- [X] T003 In src/owner_lens/__init__.py, replace the `UnsupportedTickerError` import and `__all__` entry in the `owner_lens.sec` block with `MalformedTickerError`, leaving the normalization modules' own `UnsupportedTickerError` re-exports untouched

**Checkpoint**: `SecClient.resolve_company` resolves arbitrary mapped tickers, empty input fails as malformed, and the package imports cleanly

---

## Phase 3: User Story 1 - Resolve Any SEC-Mapped Ticker (Priority: P1) 🎯 MVP

**Goal**: Resolve arbitrary mapped tickers (ADBE, V, COST, and any other entry) to a canonical identity and retrieve each company's own raw Company Facts, with case-insensitive, whitespace-tolerant canonicalization.

**Independent Test**: Given a controlled multi-company mapping and matching Company Facts, requesting ADBE, V, COST, and an arbitrary mapped ticker each returns the correct canonical identity and that company's unchanged raw payload, and lowercase or padded input resolves identically.

### Implementation for User Story 1

- [X] T004 [US1] In src/owner_lens/__init__.py, update the `main()` usage or examples comment so the console entry point documents multi-company validation (`owner-lens ADBE`, `owner-lens V`, `owner-lens COST`) without adding financial-analysis output

### Tests for User Story 1

- [X] T005 [US1] In tests/test_sec.py, add a multi-company controlled mapping (ADBE, V, COST, plus one additional arbitrary entry) with matching Company Facts fixtures, and add tests that each ticker resolves to its own canonical identity, requests its own ten-digit CIK, and returns its unchanged raw payload
- [X] T006 [US1] In tests/test_sec.py, add canonicalization tests proving lowercase, uppercase, and whitespace-padded input for V and COST each resolve to the same canonical uppercase identity

**Checkpoint**: Arbitrary mapped tickers resolve and retrieve their own raw facts; canonicalization is consistent

---

## Phase 4: User Story 2 - Preserve Adobe Behavior as a Regression Case (Priority: P2)

**Goal**: Keep Adobe's identity resolution and raw retrieval semantics identical, including every previously passing SEC-client assertion, and retire only the obsolete allow-list test.

**Independent Test**: The existing ADBE success and failure assertions pass unchanged, and the removed allow-list behavior is replaced by the new malformed/unmapped semantics.

### Tests for User Story 2

- [X] T007 [US2] In tests/test_sec.py, replace the obsolete `test_unsupported_ticker_is_rejected_without_network` (which asserted an allow-list rejection) with a test proving a well-formed unmapped ticker now raises `CompanyResolutionError` after the mapping fetch, and update the `UnsupportedTickerError` import to `MalformedTickerError`
- [X] T008 [US2] In tests/test_sec.py, confirm the existing ADBE success, raw-payload-preservation, ten-digit-CIK, and mapping/facts failure tests remain and pass unchanged under the generalized client

**Checkpoint**: Adobe behavior is preserved; the allow-list test is retired without losing coverage

---

## Phase 5: User Story 3 - Distinguish Resolution and Retrieval Failures (Priority: P3)

**Goal**: Each failure mode surfaces as its own distinct typed error with no partial success.

**Independent Test**: Malformed input, unmapped ticker, unavailable/malformed mapping, unavailable/malformed facts, and CIK mismatch each raise their documented distinct failure.

### Tests for User Story 3

- [X] T009 [US3] In tests/test_sec.py, add tests that empty and whitespace-only tickers raise `MalformedTickerError` without any network access, distinct from the unmapped-ticker `CompanyResolutionError`
- [X] T010 [US3] In tests/test_sec.py, add or confirm tests for duplicate/conflicting mapping entries, transport failure, unsuccessful status, malformed (non-object / non-JSON) mapping, malformed Company Facts, and Company Facts CIK mismatch, asserting each raises its documented typed failure and returns no partial result, using a non-ADBE company where practical to prove generality

**Checkpoint**: The full failure taxonomy is distinct, typed, and multi-company

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole slice and record what was learned

- [X] T011 Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src tests` and confirm all pass
- [X] T012 Run the optional live validation `owner-lens ADBE`, `owner-lens V`, and `owner-lens COST` with `OWNER_LENS_SEC_USER_AGENT` set, confirming each reports canonical ticker, company name, ten-digit CIK, top-level keys, and facts namespaces
- [X] T013 [P] Update repository memory notes in /memories/repo/owner-lens.md with the Slice 3A generalization (allow-list removal, `MalformedTickerError`, normalization-still-Adobe boundary) and any implementation deltas

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational completion; they share `tests/test_sec.py` so their test tasks run sequentially
- **Polish (Phase 6)**: Depends on all user stories being complete

### Within Each User Story

- Implementation before that story's tests
- Story complete before moving to the next priority

### Parallel Opportunities

- Phase 2 tasks touch two files but T003 depends on T002's new symbol, so run them in order
- Tasks that edit `tests/test_sec.py` (T005-T010) must run sequentially; only T013 (a different file) is marked [P]

---

## Implementation Strategy

MVP is User Story 1 (arbitrary mapped-ticker resolution) built on the foundational SEC generalization. User Story 2 guards the Adobe regression, and User Story 3 completes the distinct failure taxonomy. The entire slice is one small in-place edit to `sec.py`, a one-line export reconciliation in `__init__.py`, and expanded controlled tests in `tests/test_sec.py`.

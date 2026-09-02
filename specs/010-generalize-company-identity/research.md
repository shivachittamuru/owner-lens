---
title: Generalize Company Identity Research
description: Decisions for generalizing SEC ticker resolution and raw Company Facts retrieval beyond ADBE
ms.date: 2026-09-02
ms.topic: reference
---

## Overview

Feature 1 (Slice 1A) built a synchronous `SecClient` that resolves ADBE through the SEC
`company_tickers.json` mapping and retrieves raw Company Facts. The mapping match, ten-digit CIK
formatting, retrieval, and CIK-match validation were written generically; only an explicit
allow-list gate restricted the client to ADBE. This slice removes that restriction. The research
below records the design decisions and the alternatives rejected.

## Decision: Remove the allow-list gate rather than expand it

* **Decision**: Delete the `SUPPORTED_TICKER` constant and the `if normalized != SUPPORTED_TICKER:
  raise UnsupportedTickerError` gate in `sec.py`. Let `resolve_company` attempt resolution for any
  canonical ticker against the SEC mapping.
* **Rationale**: The spec forbids a manual supported-ticker list (FR-002). The mapping already
  contains every U.S.-listed company the SEC recognizes, so absence is naturally expressed as "no
  mapping entry." Removing the gate is the smallest change that satisfies arbitrary resolution.
* **Alternatives considered**:
  * *Expand the allow-list to `{ADBE, V, COST}`*: rejected; it is exactly the manual list the spec
    prohibits and would not support arbitrary tickers.
  * *Add a configurable allow-list*: rejected as speculative configuration with no current consumer
    (Constitution VI).

## Decision: Introduce a distinct malformed-ticker-input failure

* **Decision**: Add `MalformedTickerError(SecError)`, raised when the canonicalized ticker is empty
  (input was empty or whitespace only). Keep "well-formed but absent from mapping" as the existing
  `CompanyResolutionError`.
* **Rationale**: FR-011 requires malformed input to be distinguishable from an unmapped ticker.
  Before this slice, both non-ADBE and empty input collapsed into the allow-list rejection; that
  conflation must be replaced with explicit, separate failures.
* **Alternatives considered**:
  * *Raise `ValueError`*: rejected; feature failures should inherit from `SecError` so callers can
    catch one hierarchy, consistent with the Feature 1 contract.
  * *Treat empty input as an unmapped ticker*: rejected; it hides an input error behind a mapping
    outcome and fails the "distinct failure" requirement.

## Decision: Retire `sec.UnsupportedTickerError`; keep the normalization one

* **Decision**: Remove `UnsupportedTickerError` from `sec.py` (it is only raised by the deleted
  gate). Update `__init__.py` to export `MalformedTickerError` in its place. The separate
  `_annual.UnsupportedTickerError` used by the normalization modules is unchanged.
* **Rationale**: The SEC-layer allow-list concept no longer exists, so its error is obsolete. The
  package-level name previously bound to the SEC error is freed. Normalization tests import their
  error from the normalization modules (`owner_lens.revenue`, etc.), which re-export the `_annual`
  class, so they are unaffected.
* **Impact**: The package no longer exports a top-level `UnsupportedTickerError`. This is an
  intentional public-surface change scoped to the SEC identity layer; the ADBE-only normalization
  error remains importable from its owning modules.
* **Alternatives considered**:
  * *Re-point the package `UnsupportedTickerError` export to the `_annual` class*: rejected; it
    would preserve a name at the cost of conflating the identity layer with normalization and is
    unnecessary for any current consumer.

## Decision: Keep financial normalization Adobe-only in this slice

* **Decision**: Leave `_annual.SUPPORTED_TICKER = "ADBE"` and `ensure_supported_ticker` in place so
  `normalize_annual_revenue`, `normalize_annual_operating_income`, `reported` normalizers, and the
  balance-sheet normalizers continue to reject non-ADBE tickers.
* **Rationale**: The slice generalizes company identity and raw retrieval only (spec scope, FR-014).
  Company-specific concept mappings and cross-company normalization are explicitly deferred to
  Slice 3B. Generalizing normalization now would introduce untested multi-company metric behavior,
  violating Financial Correctness (Constitution I).
* **Alternatives considered**:
  * *Generalize normalization at the same time*: rejected; it exceeds scope, risks Adobe regression,
    and lacks the per-company concept research that Slice 3B will perform.

## Decision: Fetch the mapping per retrieval; add no caching

* **Decision**: Preserve the current behavior where `resolve_company` fetches `company_tickers.json`
  on each call and `retrieve_company_facts` performs exactly one mapping fetch followed by one
  Company Facts fetch. Add no persistent cache or database.
* **Rationale**: The spec explicitly allows per-invocation mapping fetch for simplicity and forbids
  persistent caching. Two sequential requests per retrieval keep the client within SEC fair-access
  limits and remain simple to reason about.
* **Alternatives considered**:
  * *In-memory mapping cache across calls*: rejected as an optimization with no current requirement;
    it also complicates freshness reasoning against changing SEC data.
  * *On-disk cache*: rejected; the spec forbids persistence in this slice.

## Decision: Do not add optional identity fields (exchange, security title)

* **Decision**: Keep `CompanyIdentity` as `ticker`, `company_name`, and `cik`. Do not add exchange
  or security title.
* **Rationale**: `company_tickers.json` supplies only `cik_str`, `ticker`, and `title`. Exchange and
  security title are not present in that source, and the spec forbids inferring or fabricating
  metadata (FR-005). Optional fields are permitted only when directly supplied, which they are not.
* **Alternatives considered**:
  * *Switch to `company_tickers_exchange.json` to add exchange*: rejected; it changes the
    established mapping source without a current requirement and adds a field no consumer needs yet.

## Decision: Reuse the existing CIK-match validation and console output

* **Decision**: Keep `_validate_company_facts` (structure plus payload-CIK-equals-resolved-CIK) and
  the existing `main()` console output, which already prints canonical ticker, company name,
  ten-digit CIK, top-level keys, facts namespaces, and a sample of us-gaap concepts.
* **Rationale**: These paths are already company-agnostic and satisfy FR-010 and FR-015 without
  change once resolution is generalized. Editing them would add risk without benefit.
* **Alternatives considered**:
  * *Add per-company output branches*: rejected; the spec forbids financial-analysis tables for the
    newly supported companies in this slice.

## Testing approach

* **Decision**: Extend `test_sec.py` with a multi-company controlled mapping (at least ADBE, V,
  COST, plus one additional arbitrary entry) and `httpx.MockTransport`. Cover lowercase and
  uppercase canonicalization, ADBE/V/COST/arbitrary resolution, unknown ticker, empty and
  whitespace input, duplicate/conflicting entries, transport failure, unsuccessful status,
  malformed mapping and malformed Company Facts, CIK mismatch, and raw-payload preservation.
* **Rationale**: The spec requires broad offline coverage that does not rely on live SEC calls
  (FR-016, SC-006). Every previously passing Adobe assertion is preserved except the obsolete
  offline allow-list rejection test, which is rewritten to assert the new behavior (a well-formed
  unmapped ticker now fails as `CompanyResolutionError` after a mapping fetch, and empty input fails
  as `MalformedTickerError` without network).
* **Alternatives considered**:
  * *Rely on live SEC responses in tests*: rejected; live data is nondeterministic and violates the
    repeatable-verification requirement.

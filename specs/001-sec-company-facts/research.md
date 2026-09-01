---
title: SEC Company Facts Retrieval Research
description: Decisions for the first OwnerLens SEC data-access vertical slice
ms.date: 2026-09-01
ms.topic: reference
---

## SEC identity mapping source

**Decision**: Retrieve `https://www.sec.gov/files/company_tickers.json` and select the single entry whose normalized `ticker` equals `ADBE`. Read `cik_str`, `ticker`, and `title` from that entry.

**Rationale**: The SEC Developer FAQ identifies this JSON document as its ticker, CIK, and company-name association used by EDGAR search. It satisfies the requirement to derive Adobe's CIK from an SEC-supported source rather than embedding it in business logic. The document is a JSON object keyed by ordinal strings, with each value carrying `cik_str`, `ticker`, and `title`.

**Alternatives considered**:

* `ticker.txt` is also SEC-supported, but omits the company name needed by this slice.
* A hard-coded ADBE-to-CIK mapping is smaller but violates the specification and would hide identity drift.
* A third-party market-data service adds a provider, credentials, and reconciliation risk without serving a current requirement.

## Company Facts retrieval and CIK format

**Decision**: Convert the resolved CIK to its canonical numeric identity for comparisons, then left-pad it to ten digits in `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.

**Rationale**: SEC documentation defines the Company Facts route and requires a ten-digit CIK, including leading zeros. Numeric canonicalization accepts the mapping's integer representation while rejecting booleans, empty values, non-digits, zero, negatives, and values longer than ten digits.

**Alternatives considered**:

* Using an unpadded CIK conflicts with the documented SEC route.
* Looking up Company Facts by ticker is unavailable because the endpoint is keyed by CIK.
* Downloading the nightly bulk archive is inefficient for one company and broadens the slice.

## Synchronous HTTP dependency

**Decision**: Use the existing `httpx` dependency synchronously, with a small `SecClient` that can receive an `httpx.Client` for controlled tests.

**Rationale**: The use case makes only two sequential requests and has no concurrency requirement. `httpx.MockTransport` supports deterministic request assertions and responses without another mocking dependency. Client injection keeps network testing focused without introducing a transport repository or provider interface.

**Alternatives considered**:

* Async HTTP adds lifecycle and concurrency complexity without a current benefit.
* The existing `requests` dependency can perform the calls, but deterministic transport injection would require monkeypatching or another adapter. The implementation should use only one HTTP library.
* A custom transport protocol or generic provider interface anticipates future providers and violates the minimal-slice constraint.

## SEC request identification and fair access

**Decision**: Require the caller to supply a non-empty declared User-Agent containing the application identity and an administrative contact, for example `OwnerLens admin@example.com`. Send it on mapping and Company Facts requests. Make two sequential requests, set bounded timeouts, and add no automatic retries.

**Rationale**: SEC guidance asks automated clients to declare a User-Agent in this form and limits aggregate access to no more than 10 requests per second. One synchronous operation makes two requests and remains below that limit. No retries prevent accidental request multiplication and keep failure behavior explicit.

**Alternatives considered**:

* A generic library default would not identify the operator and could produce an undeclared bot request.
* An empty or browser-like User-Agent would not meet the SEC identification intent.
* Automatic retries could obscure the first failure and complicate request-rate compliance.
* A rate-limiter abstraction is unnecessary for the one-operation, two-request slice. Broader repeated or concurrent use must add rate coordination before scope expands.

## Raw payload preservation and validation

**Decision**: Return the parsed Company Facts JSON object unchanged alongside a separate resolved `CompanyIdentity`. Validate only the trust boundary: JSON object shape, non-empty `entityName`, canonical `cik` matching the resolved CIK, and object-valued `facts`. Do not rewrite, copy selected concepts, normalize units, or infer periods.

**Rationale**: Object-level preservation supports inspection and exact structural equality in tests while leaving all source concepts and provenance intact. Minimal structural and identity validation prevents malformed or wrong-company data from being presented as verified Company Facts. SEC conformed names can differ in punctuation or casing, so CIK is the authoritative identity match; names are exposed but not required to be textually identical.

**Alternatives considered**:

* Returning response bytes would preserve wire formatting but make the required identity and structure validation less useful and expose transport encoding concerns.
* Mapping the payload into financial domain models would discard unknown fields and introduce normalization prematurely.
* Validating every XBRL fact would duplicate SEC schema behavior and broaden the feature beyond data access.

## Failure model

**Decision**: Define a small typed exception hierarchy rooted at `SecError`, with distinct unsupported-ticker, resolution, transport, HTTP-response, malformed-response, and identity-mismatch failures. A full retrieval returns only after both requests and validations succeed.

**Rationale**: Callers and tests can distinguish actionable failure stages without parsing strings. Atomic return behavior prevents a resolved identity from being mistaken for a successful Company Facts result when the second request fails.

**Alternatives considered**:

* Returning `None`, empty objects, or partially populated results violates the fail-loudly constitution principle.
* One undifferentiated exception hides whether resolution, external access, or source validation failed.
* A result-monad dependency adds machinery not otherwise needed by the project.

## Test strategy

**Decision**: Keep the default suite fully controlled with `pytest` and `httpx.MockTransport`. Cover request order, URLs, User-Agent, ticker normalization, mapping uniqueness, CIK padding, unchanged payload equality, malformed JSON and shape, CIK mismatch, transport errors, and unsuccessful statuses. Keep a live ADBE smoke check manual and optional.

**Rationale**: Controlled payloads are reproducible and can exercise failure paths that live SEC calls cannot reliably produce. A manual smoke check still verifies current source compatibility without making CI depend on network availability or changing SEC data.

**Alternatives considered**:

* Live-only tests are nondeterministic, consume SEC capacity, and cannot reliably verify error handling.
* Recorded full Adobe responses become large and stale. Minimal representative fixtures prove the contract while preserving all fields supplied to the test.

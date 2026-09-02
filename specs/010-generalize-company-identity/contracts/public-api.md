---
title: SEC Client Public API Contract
description: Generalized SEC client contract for resolving any mapped ticker and retrieving raw Company Facts
ms.date: 2026-09-02
ms.topic: reference
---

## Scope

The package exposes one SEC-specific synchronous client. It resolves any ticker present in the SEC
company ticker mapping and returns the resolved SEC identity together with a validated, otherwise
unchanged Company Facts JSON object. This contract does not define a generic financial-data
provider interface, and it does not generalize financial normalization, which remains Adobe-only in
this slice.

## Values

### `CompanyIdentity`

An immutable value with these readable attributes:

| Attribute      | Type  | Contract                                             |
|----------------|-------|------------------------------------------------------|
| `ticker`       | `str` | Canonical uppercase ticker matched in the SEC mapping|
| `company_name` | `str` | Non-empty SEC conformed mapping title                |
| `cik`          | `str` | Positive CIK padded to exactly ten digits            |

No optional fields are added; the mapping source does not supply exchange or security title.

### `CompanyFactsResult`

An immutable value with these readable attributes:

| Attribute   | Type             | Contract                                              |
|-------------|------------------|------------------------------------------------------|
| `identity`  | `CompanyIdentity`| Identity resolved before Company Facts retrieval     |
| `raw_facts` | `dict[str, Any]` | Same parsed object obtained from the SEC facts source|

`raw_facts` is not normalized or selectively copied. Callers that mutate it mutate their local
result; the client does not retain it.

## `SecClient`

### Construction

```text
SecClient(user_agent: str, *, http_client: httpx.Client | None = None) -> SecClient
```

Contract:

* `user_agent` must be non-empty after trimming and must identify the application and administrative
  contact in accordance with SEC guidance.
* The client sends this value as `User-Agent` on every SEC request.
* An injected synchronous HTTP client is optional and enables deterministic tests.
* When no HTTP client is injected, the SEC client owns a bounded-timeout synchronous HTTP client.
* Construction performs no network access.

### Resolve identity

```text
resolve_company(ticker: str) -> CompanyIdentity
```

Contract:

1. Trim and uppercase `ticker`.
2. Reject an empty canonical ticker with `MalformedTickerError` before any network access.
3. Retrieve the SEC company mapping.
4. Require exactly one valid mapping entry for the canonical ticker.
5. Return its canonical ticker, title, and ten-digit CIK.

This method never retrieves Company Facts and never hard-codes a CIK.

### Retrieve Company Facts for an identity

```text
get_company_facts(identity: CompanyIdentity) -> dict[str, Any]
```

Contract:

1. Construct the documented SEC Company Facts location from `identity.cik`.
2. Retrieve and parse a JSON object.
3. Require non-empty `entityName`, object-valued `facts`, and a CIK equal to `identity.cik` after
   canonicalization.
4. Return the same parsed object without financial transformations.

This method accepts a resolved Company Identity rather than a free CIK so business code cannot
bypass ticker resolution in the primary flow.

### Complete retrieval

```text
retrieve_company_facts(ticker: str) -> CompanyFactsResult
```

Contract:

1. Call `resolve_company(ticker)`.
2. Call `get_company_facts(identity)` only after successful resolution.
3. Return one result only after both stages and all validations succeed.

No partial Company Facts Result is returned if either stage fails.

## Exceptions

All feature failures inherit from `SecError`. Public exception categories are:

| Exception                      | Meaning                                                    |
|--------------------------------|------------------------------------------------------------|
| `MalformedTickerError`         | Ticker is empty or whitespace only after trimming          |
| `CompanyResolutionError`       | Mapping is absent, ambiguous, or unusable for the ticker   |
| `SecTransportError`            | Network or timeout failure occurred                        |
| `SecResponseError`             | An SEC source returned an unsuccessful status              |
| `MalformedSecResponseError`    | A source did not return valid JSON with required structure |
| `CompanyIdentityMismatchError` | Company Facts CIK conflicts with the resolved identity     |

The operation does not convert these failures to `None`, empty dictionaries, placeholder
identities, or successful partial values. Error messages identify the failed stage without including
a fabricated fact.

### Surface change from Feature 1

* `MalformedTickerError` is new and replaces the removed allow-list rejection.
* The package no longer exports `UnsupportedTickerError` from the SEC layer; a well-formed ticker
  absent from the mapping now fails as `CompanyResolutionError`. The distinct
  `UnsupportedTickerError` used by the Adobe-only normalization modules is unchanged and remains
  importable from those modules.

## External request contract

| Purpose         | Method | Location                                                        |
|-----------------|--------|-----------------------------------------------------------------|
| Company mapping | GET    | `https://www.sec.gov/files/company_tickers.json`                |
| Company Facts   | GET    | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` |

Every request includes the declared User-Agent. The successful path sends the mapping request first
and the Company Facts request second. The client does not retry automatically, follow alternate
providers, cache, or return stale local data.

## Minimal validation entry point

The existing `owner-lens` console entry point accepts exactly one positional ticker for manual
validation of any supported company:

```text
owner-lens ADBE
owner-lens V
owner-lens COST
```

It reads the declared SEC User-Agent from `OWNER_LENS_SEC_USER_AGENT`, invokes the complete
retrieval, and reports the canonical ticker, company name, ten-digit CIK, the top-level Company
Facts keys, and the namespaces available in the facts payload. Missing configuration, malformed
input, and SEC failures produce a nonzero exit status and a concise error. It does not print
extracted financial metrics or add financial-analysis tables for newly supported companies.

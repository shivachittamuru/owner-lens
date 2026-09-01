---
title: SEC Company Facts Data Model
description: Data values, validation rules, relationships, and states for raw Adobe retrieval
ms.date: 2026-09-01
ms.topic: reference
---

## Company Identity

Represents the company identity resolved from the SEC company ticker mapping.

### Fields

| Field          | Type   | Required | Meaning                                              |
|----------------|--------|----------|------------------------------------------------------|
| `ticker`       | string | Yes      | Canonical uppercase ticker from the SEC mapping      |
| `company_name` | string | Yes      | Non-empty SEC conformed company name from `title`    |
| `cik`          | string | Yes      | Canonical ten-digit CIK, including leading zeros     |

### Validation rules

* Input ticker is trimmed and compared case-insensitively.
* This slice accepts only normalized `ADBE`; every other ticker is explicitly unsupported.
* The mapping must contain exactly one valid ADBE entry. No match is unresolved; multiple matches are ambiguous.
* `ticker` and `title` must be non-empty strings.
* `cik_str` must represent a positive integer containing no more than ten digits. A boolean is invalid even though Python treats booleans as integers.
* The stored CIK is always the ten-digit, zero-padded representation.

## Raw Company Facts

Represents the complete parsed JSON object returned by the SEC Company Facts source.

### Required boundary fields

| Field        | Type   | Required | Meaning                                             |
|--------------|--------|----------|-----------------------------------------------------|
| `cik`        | number or digit string | Yes | Company identity asserted by the SEC payload |
| `entityName` | string | Yes      | Non-empty SEC company name for the payload          |
| `facts`      | object | Yes      | Source taxonomy and concept hierarchy               |

All additional fields and every descendant of `facts` remain in the returned object unchanged. OwnerLens does not define financial concept, unit, period, frame, form, filed-date, fiscal-year, fiscal-period, or accession-number models in this slice.

### Validation rules

* The top-level JSON value must be an object.
* `entityName` must be a non-empty string.
* `facts` must be an object; an empty object is valid raw source data.
* The payload CIK must canonicalize to the same positive numeric CIK as the resolved Company Identity.
* Validation must not mutate the payload.

## Company Facts Result

Represents the atomic successful result exposed to the caller.

### Fields

| Field      | Type             | Required | Meaning                                  |
|------------|------------------|----------|------------------------------------------|
| `identity` | Company Identity | Yes      | Identity resolved from the SEC mapping   |
| `raw_facts`| Raw Company Facts| Yes      | Validated, otherwise unchanged SEC object|

### Relationships

* One Company Facts Result contains exactly one Company Identity.
* One Company Facts Result contains exactly one Raw Company Facts object.
* `identity.cik` and `raw_facts.cik` must identify the same company.
* A failed operation creates no Company Facts Result.

## Retrieval Failure

Represents an explicit exceptional outcome rather than returned financial data.

### Failure categories

| Category               | Trigger                                                        |
|------------------------|----------------------------------------------------------------|
| Unsupported ticker     | Normalized input is not ADBE                                    |
| Resolution failure     | Mapping has no ADBE, ambiguous ADBE entries, or invalid fields  |
| Transport failure      | DNS, connection, TLS, or timeout failure reaches the client     |
| HTTP response failure  | Either SEC source returns an unsuccessful status                |
| Malformed response     | JSON parsing fails or required structure has an invalid shape   |
| Identity mismatch      | Company Facts CIK differs from the resolved mapping CIK          |

A failure may carry the failed source or operation and safe response context such as status code. It must not carry invented identity or financial values.

## State transitions

```text
Requested
  -> RejectedUnsupportedTicker
  -> FetchingMapping
       -> FailedTransportOrHTTP
       -> FailedMalformedMapping
       -> FailedUnresolvedOrAmbiguous
       -> IdentityResolved
            -> FetchingCompanyFacts
                 -> FailedTransportOrHTTP
                 -> FailedMalformedFacts
                 -> FailedIdentityMismatch
                 -> Completed
```

Only `Completed` yields a Company Facts Result. Every failure state terminates the operation without partial success.

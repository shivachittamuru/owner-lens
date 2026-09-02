---
title: Generalize Company Identity Data Model
description: Canonical identity, raw facts, result, and failure model for multi-company SEC resolution
ms.date: 2026-09-02
ms.topic: reference
---

## Canonical Company Identity

Represents the company identity resolved from the SEC company ticker mapping for any supported
ticker. The value object is unchanged from Feature 1; only its permitted ticker range widens.

### Fields

| Field          | Type   | Required | Meaning                                              |
|----------------|--------|----------|------------------------------------------------------|
| `ticker`       | string | Yes      | Canonical uppercase ticker matched in the SEC mapping|
| `company_name` | string | Yes      | Non-empty SEC conformed company name from `title`    |
| `cik`          | string | Yes      | Canonical ten-digit CIK, including leading zeros     |

Optional fields such as exchange or security title are intentionally omitted because
`company_tickers.json` does not supply them; OwnerLens does not infer or fabricate them.

### Validation rules

* Input ticker is trimmed and compared case-insensitively; the canonical form is uppercase.
* A ticker that is empty after trimming is malformed input, distinct from an unmapped ticker.
* The mapping must contain exactly one valid entry for the requested ticker. No match is
  unresolved; multiple matches are ambiguous.
* `ticker` and `title` must be non-empty strings.
* `cik_str` must represent a positive integer containing no more than ten digits. A boolean is
  invalid even though Python treats booleans as integers.
* The stored CIK is always the ten-digit, zero-padded representation.

## Raw Company Facts

Represents the complete parsed JSON object returned by the SEC Company Facts source for the
resolved CIK. Unchanged from Feature 1.

### Required boundary fields

| Field        | Type                    | Required | Meaning                                     |
|--------------|-------------------------|----------|---------------------------------------------|
| `cik`        | number or digit string  | Yes      | Company identity asserted by the SEC payload|
| `entityName` | string                  | Yes      | Non-empty SEC company name for the payload  |
| `facts`      | object                  | Yes      | Source taxonomy and concept hierarchy       |

All additional fields and every descendant of `facts` remain in the returned object unchanged.
OwnerLens defines no financial concept, unit, period, frame, form, filed-date, fiscal-year,
fiscal-period, or accession-number model in this slice, and no per-company concept mapping.

### Validation rules

* The top-level JSON value must be an object.
* `entityName` must be a non-empty string.
* `facts` must be an object; an empty object is valid raw source data.
* The payload CIK must canonicalize to the same positive numeric CIK as the resolved identity.
* Validation must not mutate the payload.

## Company Facts Result

Represents the atomic successful result exposed to the caller. Unchanged from Feature 1.

### Fields

| Field       | Type             | Required | Meaning                                   |
|-------------|------------------|----------|-------------------------------------------|
| `identity`  | Company Identity | Yes      | Identity resolved from the SEC mapping    |
| `raw_facts` | Raw Company Facts| Yes      | Validated, otherwise unchanged SEC object |

### Relationships

* One Company Facts Result contains exactly one Company Identity.
* One Company Facts Result contains exactly one Raw Company Facts object.
* `identity.cik` and `raw_facts.cik` must identify the same company.
* A failed operation creates no Company Facts Result and no partial company object.

## Resolution Failure

Represents an explicit exceptional outcome rather than returned financial data. The taxonomy
widens by one category (malformed input) and drops the obsolete allow-list category.

### Failure categories

| Category                | Trigger                                                             | Exception                       |
|-------------------------|---------------------------------------------------------------------|---------------------------------|
| Malformed ticker input  | Ticker is empty or whitespace only after trimming                   | `MalformedTickerError`          |
| Resolution failure      | Mapping has no entry, ambiguous entries, or invalid fields for it   | `CompanyResolutionError`        |
| Transport failure       | DNS, connection, TLS, or timeout failure reaches the client         | `SecTransportError`             |
| HTTP response failure   | Either SEC source returns an unsuccessful status                    | `SecResponseError`              |
| Malformed response      | JSON parsing fails or required structure has an invalid shape       | `MalformedSecResponseError`     |
| Identity mismatch       | Company Facts CIK differs from the resolved mapping CIK             | `CompanyIdentityMismatchError`  |

A failure may carry the failed source or operation and safe response context such as a status
code. It must not carry invented identity or financial values. All categories inherit from
`SecError`.

## State transitions

```text
Requested
  -> RejectedMalformedTicker            (empty/whitespace input; no network)
  -> FetchingMapping
       -> FailedTransportOrHTTP
       -> FailedMalformedMapping
       -> FailedUnresolvedOrAmbiguous   (well-formed ticker absent or conflicting)
       -> IdentityResolved
            -> FetchingCompanyFacts
                 -> FailedTransportOrHTTP
                 -> FailedMalformedFacts
                 -> FailedIdentityMismatch
                 -> Completed
```

Only `Completed` yields a Company Facts Result. Every failure state terminates the operation
without partial success.

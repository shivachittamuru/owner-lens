---
title: "Feature 8B: Immutable Underwriting Record"
description: "Manually capture point-in-time facts, expectations, assumptions, judgments, and calculations."
ms.topic: how-to
---

## Purpose and boundaries

An underwriting record preserves the evidence and manual beliefs used at a
particular time. Each explicit creation appends a new version for the stable
`security_id`. Nothing updates a previous record. This supports future
calibration without implementing calibration, valuation, probabilities, AI,
recommendations, portfolio logic, or a Streamlit editor.

Creation reads persisted FMP annual canonical histories and 8A2 market evidence
only. It never calls FMP or SEC and never substitutes one provider's values for
another. SEC remains authoritative for filed facts; FMP remains normalized
evidence. There are no generated business assumptions or automatic decisions.

## Domain sections

| Section | Semantic category | Contents |
|---------|-------------------|----------|
| Starting financial state | `FACT` | Latest fiscal-year revenue, operating margin, FCF, FCF margin, diluted shares, FCF/share, signed net cash/debt, and ROIC |
| Historical base rates | `CALCULATION` | Annual observations, observed minimum/maximum/latest, units, and formulas for growth, margins, ROIC, and share-count change |
| Market expectations | `EXPECTATION` | Latest annual and quarterly estimate snapshots, target dates, revenue/EPS low/average/high, counts, and retrieval metadata |
| Business drivers | `JUDGMENT` | Three to five explicit manual drivers with optional references |
| Forward assumptions | `ASSUMPTION` | Named value, units, required rationale, optional confidence text and references |
| Supporting/disconfirming evidence | Explicit per item | Text with one of the five categories and optional source metadata |
| Thesis and optional decision | `JUDGMENT` | Dependencies, breakers, biggest uncertainty, most important variable, next evidence, and optional manual decision |

Starting margins, FCF, net cash/debt, and ROIC describe observed history, so they
retain the requested `FACT` category. Their `basis=CALCULATION` and formula
explicitly distinguish OwnerLens derivations from filed line items. They are
not labeled as FMP-reported ratios or forward predictions.

Frozen domain objects live in `owner_lens.underwriting`. All starting fields
use the same latest fiscal year; an unavailable field is `null` with a reason,
never an older-year value or a forward assumption. The existing deterministic
economics engines and complete persisted annual window supply the history.
Growth requires consecutive fiscal years; missing values are not zero.

## Storage and point in time

SQLite schema version 4 adds `underwriting_records`:

* UUID `underwriting_id`, stable `security_id`, recorded ticker, and per-security
  integer `version`.
* Actual UTC `created_at` and evidence `as_of_date`.
* Self-contained `snapshot_json` and SHA-256 `content_hash`.
* Unique `(security_id, version)` and database triggers rejecting updates,
  deletes, and replacements.

The additive migration retains SEC and FMP evidence. Version allocation and
insert use an immediate SQLite transaction. Repeating `create`, even with
identical inputs, appends a version. Read integrity is checked against the
stored content hash.

The JSON copies manual inputs, starting values, base-rate observations,
canonical facts and coverage, calculation version, exact fact-linked source
metadata, the EOD close, and selected analyst rows. Sources retain snapshot
ids, endpoints, request parameters, retrieval times, hashes, and raw references.
Later ingestion cannot change a saved record. Reload reads only the saved
JSON; it does not recompute using current evidence or read raw files.

By default, the evidence cutoff is creation time. An optional earlier
`as_of_date` uses UTC end of that date, capped at creation time. Annual histories
and analyst snapshots must have been retrieved by that cutoff; prices also
require a market date no later than the as-of date. A future as-of date is
rejected. An earlier as-of date is not a claim that today's manual beliefs
existed then: `created_at` always records when the beliefs were actually saved.

Missing annual owner-economics inputs block creation explicitly. Optional
price/estimate evidence and unavailable capital-efficiency metrics remain
explicitly missing. An empty latest estimate snapshot is preserved, not
silently replaced by an older consensus. Annual and quarterly expectations
remain separate.

## Manual ADBE workflow

The [sample input](../examples/adbe_underwriting.sample.json) contains structural
placeholders, not an ADBE thesis or recommended numeric assumptions. Replace
every `REPLACE` string and every numeric placeholder with your own inputs
before creating a real record. Omit optional `as_of_date` to use today's UTC
date. Ratio inputs use decimals: `0.05` means 5%, and `-0.02` means a 2% decline.

```powershell
New-Item -ItemType Directory -Force .\data\underwriting | Out-Null
Copy-Item .\docs\examples\adbe_underwriting.sample.json .\data\underwriting\ADBE.json
notepad .\data\underwriting\ADBE.json
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE.json
uv run owner-lens underwriting show ADBE
uv run owner-lens underwriting history ADBE
```

Supported assumption names are `revenue_growth_5y` (annualized),
`operating_margin_year5`, `fcf_margin_year5`, `annual_share_count_change`,
`terminal_assumption`, `tax_rate`, and `discount_rate`. Numeric assumptions
require `unit="ratio"`; the terminal assumption is qualitative text, not a
terminal-value calculation. At least one assumption is required. No assumption
is used to calculate a forward result in 8B.

Evidence and confidence are optional. For example, a manually supplied
supporting item can preserve a document reference:

```json
{
  "category": "FACT",
  "text": "Your exact cited observation.",
  "references": [
    {
      "title": "Document title",
      "uri": "Your document URL or local reference",
      "observed_at": "Your observation time",
      "note": "Relevant page or section"
    }
  ]
}
```

Manual citations are not automatically verified. Unknown fields, duplicate
JSON keys, duplicate assumption names, semantic substitutions, and invalid
numeric values fail explicitly. Starting facts and market expectations cannot
be supplied or overridden in the manual input.

After editing your input, create a revised version and inspect the old record:

```powershell
uv run owner-lens underwriting create ADBE --file .\data\underwriting\ADBE.json
uv run owner-lens underwriting show ADBE --version 1
uv run owner-lens underwriting history ADBE
```

For reproducibility validation, export version 1 before and after creating the
revision or separately refreshing FMP evidence. Compare the saved JSON or its
content hash. The original version must remain identical. Fixture tests cover
this behavior without a live API key.

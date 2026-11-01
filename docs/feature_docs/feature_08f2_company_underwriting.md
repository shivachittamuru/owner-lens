---
title: "Feature 8F2: Company Underwriting and Research Context"
description: "Read saved underwriting on the Company page and export compact research context without retrieval or editing."
---

## Company page

The existing Company page now has Fundamentals, Screening and Underwriting tabs.
The Underwriting tab uses the latest frozen
[8F1 domain projection](feature_08f1_underwriting_contract.md), keeping financial
logic outside Streamlit. It displays:

* Version, as-of, frozen market price/date and conditional classification.
* Expected five-year CAGR, explicit hurdle, spread and variant-view status.
* Bear/Base/Bull probabilities, saved terminal value/share and implied CAGR.
* Local BASE sensitivities, recorded disagreement rationales and uncertainty.
* Business drivers, supporting/disconfirming evidence, dependencies, breakers
  and next evidence in an expandable section.
* The latest saved challenger assessment, challenges, questions and field
  references in a separate expander.
* Explicit missing evidence, unavailable outputs and monitoring metadata.

An absent record, saved valuation or challenger is reported as absent. The page
does not create records, run valuation/challenger, or retrieve evidence.
FACT, EXPECTATION, ASSUMPTION, JUDGMENT and CALCULATION distinctions remain
visible. Existing quarterly, EOD and analyst evidence sections stay separate
from annual screening.

The projection is loaded for the selected Company page, not for the whole
universe. It reads current persisted versions/runs so revisions are visible on
rerun. Domain validation and deterministic derivation reuse the frozen inputs;
no new financial arithmetic lives in the rendering layer.

## Copy Research Context

Select **Copy Research Context** to reveal a selectable Markdown code block.
Use its copy icon or select/copy the text; alternatively download Markdown or
JSON. Browser clipboard permissions are not required. Nothing is automatically
sent to ChatGPT or another service. Review the excerpt before sharing.

The export contains identity, persisted screening and six dimensions, reason
codes, annual economics/history, captured market expectations and underwriting
when present. Underwriting includes assumptions, judgment probabilities,
saved scenario outputs, expected return/hurdle/spread, variant/sensitivities,
drivers, thesis, challenger highlights and missing evidence.

Current persisted screening/economics are explicitly distinguished from the
separately labeled immutable underwriting price, financial state and estimates.
Analyst target dates, period types and retrieval dates explain the estimate
horizon without copying raw provider requests. Decimal ratios are labeled:
`0.12` means 12%. JSON uses `null`; Markdown renders missing values as `N/A`.

Annual consensus windows use the nearest five future target dates available
(three to five desired); quarterly windows use the nearest four. Targets must
be strictly after the frozen underwriting as-of date, or estimate retrieval
date when no underwriting exists. Actual FMP dates are preserved, sorted
ascending; the export never extrapolates or uses newest/farthest targets first.
Sparse windows and distant first targets explicitly report that nearer periods
were not captured, not that FMP necessarily lacks them.

Markdown is a compact reasoning excerpt: latest economics, observed endpoints,
trends, nearest consensus, one combined scenario/weight/output line per scenario
and concise thesis/advisory highlights. Duplicate frozen starting facts are
shown only when overlapping frozen starting metrics differ from current
economics. JSON retains all export section data, unrounded values, all captured
estimate rows in `available_rows`, selected rows in `rows`, and estimate
snapshot id/hash/endpoint/retrieval provenance. It is still a sanitized research
export, not the complete internal audit record.

Exports are deterministic for the same detail/projection. Raw payloads, provider
request parameters, run UUIDs, database paths and giant provenance blobs
are omitted. Credential assignments, common token patterns, URLs and local
paths in free text are redacted or omitted. This reduces accidental disclosure,
but is not a guarantee that arbitrary private content in investor notes is
shareable. Always review before pasting.

No extra investing logic, editor, agents, instruments or portfolio features
are added.

A `CAPTURED` underwriting explicitly shows N/A for absent valuation, variant,
expected-return and saved challenger outputs. An expander offers exact offline
CLI commands for that version, but never executes them. Variant remains a
deterministic derived report rather than a separately saved artifact; no new
persistence model is introduced.

## Manual ADBE validation

```powershell
uv run owner-lens workbench --provider fmp
```

Choose Company and ADBE, then inspect:

* Underwriting version/as-of and frozen price/date match the CLI.
* Probabilities and Bear/Base/Bull values match the saved version.
* Expected CAGR, hurdle, spread and classification match the summary.
* Missing evidence is not converted to zero or invented support.
* Challenger is the saved advisory run; visiting the page creates no run.
* Structured dependencies/breakers, uncertainty and variant rationale are visible.
* Copy Research Context includes the relevant sections and distinguishes
  current evidence from frozen underwriting.
* Downloaded JSON retains missing values and omits internal paths/raw provenance.
* A company without underwriting shows an explicit empty state.

For independent comparison, use the version shown by the page:

```powershell
$Version = 5 # Replace with the version shown in the Company page.
uv run owner-lens underwriting show ADBE --version $Version
uv run owner-lens valuation show ADBE --version $Version
uv run owner-lens underwriting summary ADBE --version $Version
uv run owner-lens challenger show ADBE --version $Version
```

No live API or model validation is needed to browse persisted data.

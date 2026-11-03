---
title: "Feature 8F2: Company Underwriting and Research Context"
description: "Read saved underwriting on the Company page and export compact research context without retrieval or editing."
---

## Company page

The existing Company page now has Fundamentals, Screening and Underwriting tabs.
The Underwriting tab uses a read-only decision projection over the latest
completed [8F1 domain projection](feature_08f1_underwriting_contract.md),
keeping financial logic outside Streamlit. The default hierarchy shows the
frozen price and screening context, expected return versus the explicit hurdle,
Bear/Base/Bull assumptions and saved outcomes, the supporting case, key
uncertainty, dependencies, thesis breakers, variant status and the most
sensitive variable. The saved challenger's strongest counterargument and
unresolved questions stay visible.

Supporting and disconfirming evidence, historical base rates, full sensitivity
detail, full challenger output, missing items, frozen evidence provenance and
the full snapshot are available in expanders. **Record decision** routes to the
existing decision workflow. **Compare this underwriting** carries the displayed
exact version into Opportunity Comparison, where other companies can be added.

When a newer version is incomplete, the page keeps the latest completed version
in the Investment View and exposes the newer version through the existing
exact-version retry controls. If no completed version exists, the incomplete
version remains visible with unavailable values left as N/A. Frozen Feature 7
context is shown when present; older snapshots without it remain N/A rather
than being recomputed from current screening.

An absent record, saved valuation or challenger is reported as absent. Reading
the saved projection does not retrieve evidence. The separate
[8F4 authoring flow](feature_08f4_underwriting_authoring.md) validates pasted
Authoring v2 JSON before one explicit commit action. After commit, that
application operation runs the existing valuation, expected-return,
variant/sensitivity and challenger services for the new version.
FACT, EXPECTATION, ASSUMPTION, JUDGMENT and CALCULATION distinctions remain
visible. Existing quarterly, EOD and analyst evidence sections stay separate
from annual screening.

The projection is loaded for the selected Company page, not for the whole
universe. It reads persisted versions and runs without retrieval or writes, so
opening the view does not create records or analysis. Domain validation and
deterministic derivation reuse frozen inputs; no new financial arithmetic lives
in the rendering layer.

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

The read/export projection adds no investing logic, agents, instruments or
portfolio features. Draft authoring is handled separately by Feature 8F4.
If a derived stage fails after commit, the immutable record remains and the
page offers a retry for that exact version. Variant remains a deterministic
derived report rather than a separately saved artifact; no new persistence
model is introduced.

## Manual ADBE validation

```powershell
uv run owner-lens workbench --provider fmp
```

Choose Company and ADBE, then inspect:

* The Investment View displays frozen context and the exact underwriting version.
* Probabilities, assumptions and Bear/Base/Bull values match the saved version.
* Expected CAGR, hurdle, spread and classification match the saved summary.
* Supporting case, uncertainty, dependencies and thesis breakers remain concise.
* Missing evidence is not converted to zero or invented support.
* Variant status and sensitivity use the saved report; no edge is inferred.
* Challenger questions are from the saved advisory run; reading creates no run.
* A newer incomplete version does not replace the latest completed view and can
  still be retried.
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

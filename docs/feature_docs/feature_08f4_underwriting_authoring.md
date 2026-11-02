---
title: "Feature 8F4: Workbench Underwriting Authoring"
description: "Approve Authoring v2 JSON once and immediately run deterministic underwriting analysis."
---

## JSON approval workflow

Launch the workbench against your persisted FMP store:

```powershell
uv run owner-lens workbench --provider fmp
```

Select Company, choose a ticker and open Underwriting. The latest saved
underwriting is the default view. Select **New Underwriting**, paste an
Authoring v2 JSON document and choose **Validate + Preview**.

Validation uses the existing Authoring v2 parser, semantic checks and frozen
evidence validation. It resolves the selected company and previews the next
version from immutable history. Validation does not create an immutable record.
The preview shows the Bear/Base/Bull assumptions and probabilities, investor
hurdle, business drivers, uncertainty, variant rationales, thesis conditions
and supporting/disconfirming evidence. When a prior version exists, it shows
the deterministic economic and thesis changes. Full JSON is available in an
expander.

Select **Commit & Analyze** once to approve and append the displayed investor
judgment. The existing atomic version guard rejects a stale preview. No
additional checkbox or confirmation page is required.

After the immutable record is committed, OwnerLens runs the existing valuation,
expected-return, variant/sensitivity and challenger services. The latest
completed result appears on the same Company page. A failed analysis stage
does not delete or alter the underwriting. The page reports each stage and
offers **Retry analysis** for that exact version without creating another
record.

File upload remains available under **Advanced import from JSON file**. The
field-by-field manual authoring form is not part of the Company page workflow;
its legacy helpers remain available to existing tests and callers.

## CLI workflow

The CLI uses the same approval and analysis operation:

```powershell
uv run owner-lens underwriting complete ADBE --file .\underwriting.json
```

If a derived stage fails, retry that committed version without submitting its
JSON again:

```powershell
uv run owner-lens underwriting analyze ADBE --version 8
```

Low-level create, valuation, summary, variant and challenger commands remain
available for debugging, reproduction and development.

## Company and ChatGPT loop

The intended workflow remains manual and reviewable:

1. Select **Copy Research Context** and review the copied evidence.
2. Use the context with ChatGPT to prepare Authoring v2 JSON.
3. Paste the JSON into the Company page and validate the preview.
4. Approve once with **Commit & Analyze**.

No ChatGPT API integration or automatic sharing is introduced. History and
the full frozen snapshot remain available from the Underwriting page.

## Manual ADBE validation

1. Open ADBE Company and select Underwriting.
2. Select **New Underwriting** and paste valid Authoring v2 JSON.
3. Validate the preview and confirm the proposed version and readable changes.
4. Select **Commit & Analyze** once and confirm one immutable version exists.
5. Confirm valuation, expected return, variant/sensitivity and challenger
   complete, then review the result on the same page.
6. Reopen ADBE and confirm the latest completed version is the default.
7. Verify full JSON and history remain accessible.
8. If practical, trigger a downstream failure in a disposable test store and
   confirm retry resumes the same version without creating another record.

The immutable history, JSON contract, semantic classifications and valuation
math remain unchanged. Deterministic analysis reuses existing Feature 8
services. Investor assumptions and judgments are not inferred or normalized.

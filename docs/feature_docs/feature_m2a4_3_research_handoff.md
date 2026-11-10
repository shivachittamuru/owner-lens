---
title: Manual ChatGPT Research Intelligence Handoff
description: Export validated local evidence and review unapproved research without changing financial or underwriting records.
---

## Workflow

M2-A4.3 adds two local-file commands. Neither loads settings, opens a database,
requests provider data, invokes ChatGPT or writes files. Redirect stdout only
when you want to save an export or review.

1. Validate an existing Owner Earnings Bridge v1.
2. Export a reproducible Markdown package for manual copying into ChatGPT.
3. Give ChatGPT the embedded instructions and response schema.
4. Save the returned JSON locally and review it against the same bridge.
5. Verify the research yourself before manually entering any Feature 8 beliefs.

The [response schema](../examples/research_response_v1.schema.json) is a small
research sidecar. It is not a second bridge, an evidence importer or an
Authoring v2 payload. The [bridge schema](../examples/owner_earnings_bridge_v1.schema.json)
and Authoring v2 remain unchanged.

## Export and binding

The package includes security identity, source IDs/dates, canonical observations,
validated historical results, screening/gates, existing research questions,
unresolved adjustments, price compatibility and evidence limitations.
The ten research questions cover economics, advantages, recurring cash flow,
reinvestment, working capital, employee equity/repurchases, deterioration,
impairment, expectations, alternatives and possible edge.

Bridge binding is SHA-256 over UTF-8 JSON with sorted keys and compact separators,
not the input file's whitespace. Changing an observation, gate, date or source
requires re-exporting and rebinding the response. A matching hash proves that
the files agree, not that the source payload is true.

An optional `--context-json` accepts the JSON export from existing Copy Research
Context, saved manually. It must match ticker/provider, saved screening and
overlapping canonical figures and must not postdate the bridge cutoff.
Only existing Research Context sections are included. This attachment is
supplemental user-supplied evidence, not a way to override the bridge or import
new estimates. Without it, the bridge alone is sufficient to export a package.

Exports reuse existing Research Context sanitization and additionally redact
credential-bearing fields, bearer/basic credentials, private-key blocks, local
paths and credential-like text. URLs are omitted from shareable excerpts,
including API-key query strings. Raw payloads, endpoints, environment settings
and filesystem roots are not exported. Review manually before sharing any
free-text financial research; redaction is not a universal secret detector.

## Response conventions

Reuse bridge source IDs with verification status BRIDGE_REFERENCE. This means
the source register matches the bridge, not that OwnerLens verified its payload.
New public sources must be UNVERIFIED_EXTERNAL. Supply title, URL, publication
date and observation timestamp when available. URLs must use HTTP(S) without
credentials, query strings or fragments. A bridge source URL may be null when
omitted by export sanitization; its source ID remains bound to the exact bridge.
The reviewer never fetches URLs.

Canonical observations are referenced by ID, never editable numerical copies.
For a FACT or CALCULATION citation with an observation ID, copy its
`quantity.reason` verbatim and preserve its category/source IDs. Put interpretation
in a separate JUDGMENT claim. A new external FACT or CALCULATION assertion remains
unverified and creates a gap. This deliberately conservative convention prevents
free-text amounts from being accepted as revised canonical economics.

Material theses require distinct supporting and disconfirming IDs. IDs may
refer to source-register entries, bridge observations/claims or response claims.
Claim IDs are new, unique and acyclic. A valid citation is not proof of relevance
or entailment; the investor must assess both sides.

Normalization proposals reuse existing bridge adjustment IDs and periods.
All proposals have approval UNREVIEWED:

* A CALCULATION effect must match the validated deterministic bridge effect and
  retain its input/source references.
* A numeric ASSUMPTION is hypothetical and requires investor substantiation.
* A JUDGMENT cannot carry a numerical adjustment.
* Null effect means unsupported, not zero.

New adjustment categories require a separately reviewed bridge update. No
calculation text is executed. No new normalization formula or combined adjusted
earnings result is created here.

Scenario proposals are optional unreviewed ranges for the four existing drivers:
`revenue_cagr`, `fcf_margin_year5`, `share_count_cagr` and
`terminal_fcf_multiple`. Rates use ratios, not percentage points; terminal
multiples use `multiple`. Bounds are Decimal strings, not probabilities.
Use null without a supported range. FCF-margin proposals must disclose all
unresolved bridge normalization dependencies. No probabilities or return
hurdle are accepted in this response format.

## Deterministic review

The explicit review `--as-of` date makes chronology reproducible; the command
does not use the wall clock. Research cannot predate the bridge cutoff or
postdate that review date. Source publication cannot follow observation,
and observation/claim dates cannot follow the research date.

| Outcome                     | Meaning                                                        | Exit |
| --------------------------- | -------------------------------------------------------------- | ---- |
| READY_FOR_INVESTOR_REVIEW    | Internal checks pass with no outstanding declared/review gaps   | 0    |
| NEEDS_MORE_EVIDENCE          | Consistent response with actionable evidence requirements       | 0    |
| INVALID_RESEARCH_RESPONSE   | Contradictory binding, shape, facts, references or preserved risk | 2    |

READY_FOR_INVESTOR_REVIEW is not factual certification, a completed underwriting
or permission to invest. It can describe a fully documented watchlist or
potential-trap judgment. An explicit insufficient-evidence decision remains
NEEDS_MORE_EVIDENCE. Missing comparable expectations are retained as a limitation,
not invented from price; an asserted supported comparison still requires
independent horizon/unit verification. Unverified external sources and unresolved
normalization create gaps.

Invalid responses return errors without a usable Feature 8 handoff. Malformed
local JSON or an invalid input bridge returns exit 2 with a sanitized diagnostic.
Each consistent response includes a readable, non-mutating Feature 8 handoff:
driver proposals or missing ranges, evidence/rationale, normalization
dependencies, dilution risks, thesis breakers/alternatives and investor actions.

## DECK demonstration

The [committed bridge](../examples/deck_owner_earnings_bridge_v1.sample.json)
reconciles FY2026 FCF of USD 1,097,332,000 and approximately USD
7.526024484757039/share. This is reported cash generation, not a normalized
or sustainable owner-earnings estimate.

The [sample response](../examples/deck_research_response_v1.sample.json)
is an illustrative manual response assembled only from existing bridge evidence,
not newly verified external research or a claimed ChatGPT execution. Review
returns NEEDS_MORE_EVIDENCE with no structural/economic contradictions.

It preserves three unresolved categories:

* Working-capital recurrence
* Maintenance versus growth reinvestment
* SBC, dilution and repurchase policy

Reported revenue/cash generation could anchor future revenue and margin research.
Annual diluted shares could inform investigation of issuance and repurchases,
not a forecast share-count policy. The excerpt supplies no brand-durability
finding, analyst expectation, forward growth range or terminal-multiple basis.
All four scenario ranges remain null and unreviewed. Cash conversion, competitive
durability, financing-obligation composition, compensation economics and
disconfirming evidence remain research requirements. Quote currency/share
compatibility stays unverified. Existing DECK v1 is neither opened nor changed.

Only after explicit investor review may findings inform existing Authoring v2
`assumptions.scenarios` or `judgments.thesis`, supporting/disconfirming evidence
and variant rationales. Reference keys remain only `title`, `uri`, `observed_at`
and `note`. This workflow generates no automatically approved payload.

## PowerShell validation

Run from the repository root with installed dependencies. `--no-sync` avoids
reinstalling an executable locked by another Windows process.

Capture database and input hashes before the workflow:

```powershell
$paths = @(
    '.\data\ownerlens.db',
    '.\data\historical-price-pilot-f8a480903eb34e4cb6f74371ed9c8565\ownerlens.db',
    '.\docs\examples\deck_owner_earnings_bridge_v1.sample.json'
)
$before = $paths | ForEach-Object { Get-FileHash -LiteralPath $_ -Algorithm SHA256 }
```

Validate, export, and review the supplied sample:

```powershell
uv run --no-sync owner-lens owner-earnings-bridge --file .\docs\examples\deck_owner_earnings_bridge_v1.sample.json
uv run --no-sync owner-lens research-export --bridge .\docs\examples\deck_owner_earnings_bridge_v1.sample.json |
    Set-Content -Encoding utf8 .\deck-chatgpt-research.md
uv run --no-sync owner-lens research-review --bridge .\docs\examples\deck_owner_earnings_bridge_v1.sample.json --response .\docs\examples\deck_research_response_v1.sample.json --as-of 2026-11-10
$LASTEXITCODE # 0; NEEDS_MORE_EVIDENCE is valid unresolved research
```

The generated Markdown includes the full response schema. Paste it into ChatGPT,
save the returned JSON as a separate local file, then substitute that path for
`--response`. For another company use its validated bridge; do not copy DECK
identity, fingerprint or observation IDs.

Optionally add the existing Workbench export saved as a local JSON file:

```powershell
uv run --no-sync owner-lens research-export --bridge .\docs\examples\deck_owner_earnings_bridge_v1.sample.json --context-json .\saved-research-context.json
```

Deliberately invalidate identity without changing either committed example:

```powershell
$badPath = Join-Path ([System.IO.Path]::GetTempPath()) 'ownerlens-invalid-research-response.json'
$bad = Get-Content -Raw .\docs\examples\deck_research_response_v1.sample.json | ConvertFrom-Json
$bad.identity.ticker = 'NOT_DECK'
[System.IO.File]::WriteAllText(
    $badPath, ($bad | ConvertTo-Json -Depth 100),
    [System.Text.UTF8Encoding]::new($false)
)
uv run --no-sync owner-lens research-review --bridge .\docs\examples\deck_owner_earnings_bridge_v1.sample.json --response $badPath --as-of 2026-11-10
$LASTEXITCODE # 2; INVALID_RESEARCH_RESPONSE
Remove-Item -LiteralPath $badPath
```

JSON inputs use UTF-8 without a BOM. For a readable handoff rather than JSON:

```powershell
$result = uv run --no-sync owner-lens research-review --bridge .\docs\examples\deck_owner_earnings_bridge_v1.sample.json --response .\docs\examples\deck_research_response_v1.sample.json --as-of 2026-11-10 | ConvertFrom-Json
$result.outcome
$result.evidence_gaps
$result.handoff_markdown
```

Confirm unchanged database bytes, which also cover frozen underwriting records:

```powershell
$after = $paths | ForEach-Object { Get-FileHash -LiteralPath $_ -Algorithm SHA256 }
Compare-Object ($before | ForEach-Object { "$($_.Path):$($_.Hash)" }) ($after | ForEach-Object { "$($_.Path):$($_.Hash)" })
# No output expected when no other process wrote to these files.
```

Do not run a provider refresh or commit an underwriting concurrently with this
check. In an actively written WAL database, include its WAL in the comparison;
the operations themselves never create a database connection.

## Focused tests and limits

```powershell
uv run --no-sync pytest -q tests\test_research_handoff.py tests\test_owner_earnings_bridge.py tests\test_research_context.py tests\test_underwriting_contract.py tests\test_cli.py
uv run --no-sync ruff check --no-cache src tests
uv run --no-sync mypy src
git diff --check
```

Controls exercise deterministic output, redaction, binding, chronology, external
verification limits, canonical mutations, approval constraints, gate/limitation
preservation, missing disconfirmation, unsupported expectations, all three
workflow outcomes and blocked settings/database/network access.

No existing financial, ranking, screening, normalization or frozen-underwriting
service is modified. Full regression is deferred to the next integration
milestone; unrelated workflows are not claimed as fully revalidated.

The reviewer checks internal consistency only. It cannot determine whether
qualitative prose is truthful, a citation genuinely disconfirms a thesis,
a hypothetical range is economically sound or a competitive advantage exists.
External truth, raw-source integrity, expectation comparability and every
investment belief remain human responsibilities.

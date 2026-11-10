---
title: Owner Earnings and Research Intelligence Contract
description: Proposed v1 research sidecar, evidence bridge and unchanged Authoring v2 handoff, validated against persisted DECK evidence.
---

## Status and scope

The additive [M2-A4.2 validator](feature_m2a4_2_owner_earnings_validator.md)
now implements structural and bounded historical arithmetic checks. The
M2-A4.1 design and wire schema below remain unchanged.

M2-A4.1 is a contract design, not an earnings-normalization engine.
The [JSON Schema](../examples/owner_earnings_bridge_v1.schema.json) defines the
serializable types. The [DECK sample](../examples/deck_owner_earnings_bridge_v1.sample.json)
is a bounded, sourced example, not a normalization conclusion or underwriting
proposal. No runtime exporter, parser, provider call, UI, ranking, database
migration or investment write is introduced.

The submitted request ended mid-section E after "Supporting and disconfirming
evide". This design covers the visible requirements, including supporting and
disconfirming evidence; it does not presume additional unseen requirements.

Survival evidence stays independent of business uncertainty, missingness and
price. Absence of a gate is not proof of safety. Historical FCF is neither
intrinsic value nor necessarily distributable, recurring owner earnings.

## Inspected architecture and additive seam

Paths below are the authoritative implementation; line anchors identify the
inspected definitions, not a proposed replacement.

| Surface                       | Existing type or function                                                                                                | Reuse and boundary                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| Annual canonical facts        | [CanonicalFact / MetricStatus](../../src/owner_lens/canonical.py#L175)                                                   | Fiscal dates, units, provider fields, resolutions and additive components; explicit absence/errors       |
| Reported owner economics      | [OwnerEconomicsRow / compute_owner_economics](../../src/owner_lens/owner_economics.py#L39)                               | FCF = OCF - absolute PP&E spending; annual diluted weighted-average denominator                          |
| FMP mapping                   | [FMP_FIELD_MAP](../../src/owner_lens/fmp_adapter.py#L82)                                                                 | PP&E versus provider CapEx, SBC, cash, short investments and two debt components remain distinct         |
| SEC mapping                   | [_to_fact / canonical_history_from_sec](../../src/owner_lens/sec_adapter.py#L110)                                        | Preserve concept, fiscal duration, filing/accession, split resolutions and component provenance          |
| Persisted FMP reconstruction  | [load_canonical_history](../../src/owner_lens/workbench/data.py#L307)                                                    | Copies history-linked facts; FMP filed/form/accession and duration start currently remain null           |
| Persisted identity/evidence   | [SecurityRecord / FmpEvidenceSnapshotRecord](../../src/owner_lens/persistence/records.py#L181)                           | Store-local security identity; optional non-unique issuer CIK; snapshot IDs, retrievals and hashes       |
| Capital and debt evidence     | [CapitalEfficiencyRow / compute_capital_efficiency](../../src/owner_lens/capital_efficiency.py#L38)                      | Cash/STI, component debt, net cash, NOPAT and average-capital returns; retain existing missing treatment |
| Candidate evidence            | [candidate_worksheet](../../src/owner_lens/candidate_review.py#L230)                                                     | Checks canonical-linked raw periods, filings, currency, CapEx conflicts, prices and share denominators   |
| Uncertainty/fragility         | [UncertaintyFragilityReview / assess_uncertainty_fragility](../../src/owner_lens/uncertainty_fragility.py#L46)           | Preserve independent observations, exact gates and source limitations                                    |
| Conditional attention         | [valuation_attention](../../src/owner_lens/workbench/discovery.py#L59)                                                   | Historical median is a reference, not normalized earnings; no new eligibility or attention model         |
| Existing research export      | [build_research_context](../../src/owner_lens/research_context.py#L120)                                                  | Manual Copy Research Context; sanitized excerpts distinguish current and frozen state                    |
| Authoring v2                  | [parse_authoring_input](../../src/owner_lens/underwriting_contract.py#L34)                                               | Exactly authoring_version, assumptions and judgments; rejects automatic facts and extra root fields      |
| Reference vocabulary          | [Reference / Statement](../../src/owner_lens/underwriting.py#L44)                                                        | Reference keys are title, uri, observed_at, note only; supplied references are not certified evidence    |
| Frozen inputs                 | [capture_underwriting_inputs / UnderwritingInputs](../../src/owner_lens/underwriting.py#L871)                            | Read-only capture, snapshot cutoff and belief-link validation; no bridge substitution                    |
| Approval                      | [review_authoring](../../src/owner_lens/underwriting_authoring.py#L167)                                                  | Canonical parser plus frozen-input validation before any approval or commit                              |
| Scenario valuation            | [value_underwriting](../../src/owner_lens/valuation.py#L83)                                                              | Pure five-year revenue/margin/share/multiple calculation from immutable snapshot                         |
| Sensitivity                   | [_sensitivity / compare_variant](../../src/owner_lens/variant.py#L285)                                                   | Existing one-driver perturbations in transient counterfactuals; no saved belief overwritten              |

The additive seam is a separate research sidecar alongside Copy Research
Context, before investor approval of an Authoring v2 draft. This slice defines
that sidecar only. A future exporter could compose these existing read-only
services. Do not force full CompanyDetail when only one supported metric layer
is needed: invalid repurchases can block its unrelated capital-allocation
section even when owner economics are available.

SEC is supported by the source/canonical contract, not by an invented SEC
Feature 8 ingestion path. Current `capture_underwriting_inputs` captures FMP
histories and requires persisted security identity. SEC-only research without
that supported capture remains research-only.

## Versioned wire contract

The contract identifier is `owner-earnings-bridge/1`; it is unrelated to
`authoring_version: 2` and frozen snapshot schema versions. Unknown top-level
fields are rejected. Adding or changing wire fields requires a reviewed
contract revision, not opportunistic keys inside Authoring v2.

The JSON Schema is the typed definition, not an additional Python domain
hierarchy. All types are JSON objects, arrays, strings, integers, booleans or
null. IDs are local to the document except persisted IDs, which are qualified
by `store_namespace`. The namespace is a public alias, not a filesystem path.
Ticker alone is not stable identity. SEC research may have null security_id;
that does not make it eligible for FMP underwriting.

### Source identity and evidence

`source_evidence` contains source records, fiscal periods, a dated quote and
explicit limitations. Each observation identifies its fiscal period and source
IDs. Source records carry provider, dataset, immutable snapshot/hash where
available, endpoint, retrieval date, provider-reported filing/acceptance metadata
and accession. Keep multiple provider records separate, including disagreements.
Completeness is scoped explicitly as COMPLETE_FOR_STATED_SCOPE, PARTIAL or
INSUFFICIENT; complete baseline arithmetic does not mean complete normalization.
New BridgeSource records also have a title and nullable public URI for
qualitative sources. External sources use provider=external, remain
NOT_VERIFIED when supplied by ChatGPT, and do not become canonical facts.
These are new sidecar fields, not additions to the existing Reference type.

Economic period-end, provider-reported filing date, actual retrieval time,
knowledge cutoff, quote date and generated time are different concepts.
Missing dates remain null. FMP's timezone-less acceptedDate stays verbatim;
do not assign a timezone or treat retrieval as publication. SEC filed/accession
survive in the optional unmodified CanonicalFact copy. A full export must
preserve its resolution/superseded/component objects, not flatten them away.
The compact sample explicitly omits those copies and links the original history.

Retrievals must not exceed the knowledge cutoff. Historical periods must end
by that cutoff. A late retrieval with an earlier reported filing date is not
certified point-in-time evidence. A bridge produced today cannot be silently
attached as evidence observed before an older frozen underwriting cutoff.

Quote close and the financial denominator have independent currency/share
compatibility. Preserve VERIFIED_BAR, INFERRED_CURRENT_PROFILE or NOT_VERIFIED,
and share adjustment limitations. A known raw close is not proof of USD/share.
No FX, split correction or alternate share denominator is invented. Do not
substitute candidate_price/historical_price for Feature 8's captured EOD record.

### Reported owner economics

`reported_owner_economics` holds identified observations with quantities,
source IDs, input IDs and formulas. Revenue, OCF, positive canonical CapEx,
annual diluted shares, cash and debt components remain FACT. FCF, FCF/share,
net cash and ROIC are CALCULATION in this sidecar. This does not relabel
Feature 8 FinancialState, whose FACT entries retain basis=CALCULATION.

Always include the six baseline metrics (revenue, OCF, CapEx, FCF, shares and
FCF/share), and explicit capital/debt availability. Retain unsupported and
invalid metrics rather than inventing inputs. The finite metric vocabulary
also permits SBC. Working-capital or other raw lines used for adjustments need
source-linked interpretation, not new canonical accounting metrics.

Existing capital-efficiency calculations allow absent current debt or STI to
contribute zero in specified circumstances. Preserve the output and its input
statuses; do not generalize that implementation behavior into "all missing debt
is zero". STRUCTURALLY_ABSENT is not UNSUPPORTED. Neither canonical zero debt
nor a debt-definition difference proves absence/presence of distress.

### Quantities and evidence states

Each quantity has status, amount or lower/upper, unit and reason. Decimal
strings avoid JSON binary rounding and preserve large integers. Units are
absolute USD, shares, USD/share or ratios; never undocumented millions or
percent points. An unknown-currency quote uses UNKNOWN_CURRENCY/share.

Exactly one numeric representation is allowed: scalar, interval, or no number.
AVAILABLE and CONDITIONAL can carry numbers. STRUCTURALLY_ABSENT, UNSUPPORTED,
INVALID, NOT_VERIFIED, INSUFFICIENT_EVIDENCE and NOT_APPLICABLE carry nulls.
An observed zero is a valid AVAILABLE value, not missingness. Negative FCF is
preserved, not filtered to zero. A confidence explanation is narrative evidence,
not a risk score or probability.

Finite canonical float outputs serialize using their existing representation.
Recompute divisions with Decimal and compare at absolute tolerance `1e-12`
for per-share/ratio examples, not exact equality to a rounded display. Integral
USD/share counts and additive cash arithmetic must match exactly.

## Traceable normalization adjustments

An adjustment has its own ID, category, period, signed effect, inputs,
calculation/assumption, rationale, source links, uncertainty and approval state.
Positive effect increases the baseline; negative effect reduces it.
Quantified ranges are signed effects, not probability distributions.

| Category                         | Evidence or assumption needed                                       | Principal double-counting trap                                     |
| -------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| WORKING_CAPITAL                  | Identified cash lines, recurring business baseline, period scope    | Adding both inventory and an aggregate cash-conversion adjustment  |
| MAINTENANCE_GROWTH_REINVESTMENT  | Sourced sustaining/growth split and required competitive spending   | Adding growth CapEx back while assuming growth without funding it  |
| NONRECURRING_CASH                | Proof of cash occurrence, tax treatment and nonrecurrence           | Repeating an exclusion already in OCF or a working-capital bridge  |
| SBC_DILUTION                     | Explicit compensation-cost versus dilution policy                   | Deducting the same economic cost and also counting its dilution    |
| LEASE_FINANCING                  | Contractual obligation and cash-flow classification evidence        | Subtracting lease payments already included in operating cash      |
| CYCLICAL_MARGIN                  | Investor cycle assumptions, working capital and reinvestment needs  | Combining a margin haircut with the same cash-line adjustments     |
| SECTOR_ACCOUNTING                | Sector-specific definitions and a separately justified methodology  | Treating REIT/financial generic FCF as comparable owner earnings   |

These are supported categories, not seven mandatory numerical deductions.
Unassessed applicability is insufficient evidence, not NOT_APPLICABLE.
NOT_APPLICABLE requires an explanation. No adjustment becomes AVAILABLE
solely because ChatGPT proposes a number or management labels an item unusual.

CALCULATION with NOT_REQUIRED_DETERMINISTIC approval requires cited supported
inputs and a fully reproducible rule. Any assumed recurrence, maintenance
allocation, cycle margin or owner-cost policy is ASSUMPTION, even if its math
is deterministic. UNREVIEWED assumptions may be displayed as hypothetical
conditional research, never as an investor-approved conclusion.

`depends_on` is an acyclic prerequisite graph, not an instruction to add a
dependency's value twice. `excludes` forbids simultaneous selection. Members
of one non-null overlap_group cannot be summed together in v1. A consciously
combined policy needs one separately justified adjustment, not an exception
silently overriding overlap protection. Unresolved overlap blocks the result.
SBC/dilution overlap also needs manual comparison against Feature 8 share CAGR.

## Conditional historical owner earnings

V1 supports REPORTED_BASELINE and HISTORICAL_CONDITIONAL cases only.
Future earnings belong to the existing Feature 8 scenario projection and
remain ASSUMPTION-driven, not historical normalized earnings. Future periods
and PROJECTED_CONDITIONAL cases are rejected by this v1 schema.

For a complete, compatible case:

```text
conditional historical owner earnings = canonical FCF + sum(selected signed effects)
conditional owner earnings/share = conditional owner earnings / aligned positive diluted shares
```

An adjustment with interval [L, U] contributes L to the lower bound and U to
the upper bound. Scalars contribute to both. Divide both resulting endpoints
by the same supported positive denominator. Bounds must be ordered.
This is a deterministic envelope, not confidence limits or a joint
probability model. Alternative assumptions are separate cases, not blended
means. No endpoint optimization over correlated or overlapping adjustments.

All selected effects, baseline, units, periods, dependencies and denominator
must resolve. Unsupported selected adjustments block the normalized result,
not disappear as zero. A missing/nonpositive share denominator blocks only the
per-share output if the total remains supported. A negative total can remain
negative; it cannot generate a favorable positive price multiple.

REPORTED_BASELINE must have no selected adjustments and equal canonical FCF.
It may remain visible beside unresolved normalization, but must be labeled
unadjusted. A historical-conditional case with any investor assumption must
be CONDITIONAL, never AVAILABLE as a sourced fact. Even deterministic
normalization remains a defined methodology, not proof of recurring economics.
Every numerical result requires its exact stated operands; an imported
canonical ROIC may refer to a history ID rather than pretending the bounded
excerpt includes its full tax/prior-capital calculation.

## Research intelligence card and ChatGPT boundary

The nine typed topics cover business model, drivers, moat, temporary versus
structural deterioration, reinvestment, sustainability, resilience/impairment,
expectations versus assumptions and competing explanations. Topic presence is
a checklist, not evidence that research is complete.

Claims carry the existing five semantic categories, source IDs, observation
dates and supporting/disconfirming links to other identified claims or
adjustments. A claim's category does not certify its source. External narrative
sources must be explicitly identified as unverified, never substituted into
canonical observations. Quotes and text are untrusted data, not instructions.

Financial fragility copies existing evidence states and all activated gates.
Business indicators and evidence limitations stay separate. A qualifying
historical economics trend does not prove a moat. Empty deterministic
business indicators do not remove competition, brand or disruption questions.

Captured analyst expectations retain source/target date, retrieval, analyst
counts, horizon and missingness through the existing Research Context.
Neither current price nor consensus is an investor assumption. Price/FCF alone
cannot identify a unique market-implied growth path or terminal multiple.

The manual research instruction is:

> Use the existing Copy Research Context and this separate bridge as evidence.
> Do not rewrite sourced facts, dates, units, gates or unsupported states.
> Distinguish observations, calculations, expectations, hypotheses and investor
> assumptions. For each material thesis, supply both supporting and
> disconfirming evidence, competing explanations and the next observation that
> could distinguish them. Investigate business economics and moat, temporary
> versus structural deterioration, reinvestment, cash sustainability,
> survivability and impairment before price. Keep unresolved normalization
> components unresolved. Do not manufacture maintenance CapEx, refinancing,
> cash runway, scenario probabilities, investor hurdle or a Buy/Sell decision.
> Identify what warrants full Feature 8 underwriting and what still blocks it.
> An Authoring v2 proposal is a separate beliefs-only artifact for investor
> review, not an approved record. Do not insert this bridge into its JSON.

No automatic ChatGPT sharing, API or agent execution is introduced.
Any future export must retain Research Context sanitization: omit local raw
paths, credentials and secret query parameters while preserving public source
IDs/hashes. Hashes establish payload identity, not factual truth.

## Unchanged Feature 8 handoff

| Research result                   | Existing destination after investor review                                           | Forbidden shortcut                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| Business/competitive hypotheses   | judgments.business_drivers                                                           | Replacing FACT inputs with a narrative                              |
| Supported/disconfirming claims    | judgments.supporting_evidence / disconfirming_evidence                               | Adding bridge source IDs or status fields inside Reference          |
| Growth/reinvestment policy        | assumptions.scenarios[].revenue_cagr / fcf_margin_year5                              | A new normalized_owner_earnings scenario field                      |
| Compensation/dilution policy      | assumptions.scenarios[].share_count_cagr plus narrative and dependency               | Automatic SBC haircut plus unreviewed matching dilution             |
| Terminal expectations             | assumptions.scenarios[].terminal_fcf_multiple and judgments.variant_rationales       | One universal terminal multiple or inferred investor belief         |
| Survivability/structural risks    | judgments.thesis dependencies, breakers, uncertainty, variable and next evidence     | Weakening an activated gate or inventing maturity coverage          |
| Probabilities and return hurdle   | judgments.probability_distribution / investor_policy                                 | ChatGPT auto-approval, normalization of weights or default hurdle   |

An existing Reference accepts **only** title, uri, observed_at and note.
Bridge snapshot IDs, hashes and adjustment IDs may be described in note or a
public artifact reference; do not add keys. Reference observation time means
actual evidence observation, not an earlier fiscal end chosen to pass cutoff.
Belief references remain JSON pointers into the frozen `/manual/...` graph.
They must not point into this external sidecar. V2 claim evidence_id and
evidence_date remain their existing fields on Statement, not Reference.

OwnerLens recaptures its own starting state and price; the bridge is not a
new evidence importer. A sidecar is not automatically frozen into Feature 8.
For reproducible research, retain its versioned file/hash externally and cite
it using existing Reference fields. Full bridge persistence can be considered
later only with explicit approval.

The current valuation computes five-year revenue from starting revenue and
revenue CAGR, FCF from year-five FCF margin, shares from share CAGR and terminal
equity value from the FCF multiple. It does not roll forward normalized FCF,
use an enterprise-value bridge or automatically add net cash, and it does not
value interim dividends. Existing sensitivity perturbs BASE revenue/margin/share
rates by 1 percentage point and terminal multiple by 1x. Research must not
imply a richer valuation model than this one.

Validate a separate proposed Authoring v2 payload with parse_authoring_input,
then review_authoring against captured inputs. Only the existing investor
Commit & Analyze flow may append a version. This slice does neither.

## Validation and observed controls

The main persisted store has DECK v1, created November 6, 2026 at
08:05:05.373214 UTC, with snapshot hash
`9201c0b0405a438a57b3df61cff1c7599866f632e6f13fe7950ac240f5ad71a9`.
The separate price pilot has no DECK underwriting. Do not conflate stores or
assume later manually captured profile evidence exists in the main store.
The actual frozen evidence cutoff is November 6 at 08:04:58.227854 UTC, a few
seconds before record creation. Recapture must use that saved preview cutoff,
not the commit timestamp. Using the latter changes the cutoff and therefore
the content hash even when financial values are unchanged.

DECK FY2026 ends March 31, 2026. Main-store reported values reconcile:

```text
OCF 1,181,955,000 - PP&E CapEx 84,623,000 = FCF 1,097,332,000 USD
FCF / 145,805,000 annual diluted shares = 7.526024484757039 USD/share
```

The source-reported filing date is May 22, 2026; statement retrievals are
October 31, 2026, 08:29:57 UTC, with exact timestamps/hashes in the sample.
The saved October 30 close is 81.99, retrieved October 31 at 08:29:58.011503
UTC. Main-store quote currency is NOT_VERIFIED and share basis UNVERIFIED.
No price/owner-earnings comparison is produced by the bridge.

Existing Feature 8 accepts a null frozen price currency and reproduces DECK
v1 scenario arithmetic. That acceptance is not evidence that currency or
adjustment compatibility has been verified; the sidecar does not rewrite it.
Recomputed Bear/Base/Bull year-five values are approximately
45.0379 / 157.2351 / 338.9076 per share and CAGRs
-11.2919% / 13.9089% / 32.8202%. These are existing investor-conditioned outputs,
not new research conclusions or newly approved assumptions.

| Persisted control   | Observed constraint                                | Required contract behavior                                           |
| ------------------- | -------------------------------------------------- | -------------------------------------------------------------------- |
| DECK                | No current financial flag; debt definitions differ | Preserve baseline; no safety claim or automatic normalization        |
| ADSK                | WATCH; prior-year CapEx definitions differ         | Trace individual periods; no unsupported median/maintenance estimate |
| ORCL / INTC         | PERSISTENT_CASH_BURN                               | Preserve negative cash generation and activated gate                 |
| CMG                 | Strong screen; debt definitions differ             | Accounting uncertainty does not automatically mean distress          |
| JPM                 | Financial sector; existing cash-burn gate          | Preserve gate and incompatible generic-FCF treatment separately      |
| Missing history     | No aligned annual baseline                         | Null outputs with explicit evidence limitation                       |
| Missing shares      | Missing, zero or negative denominator              | Total may survive; no per-share output                               |

Schema validation alone cannot prove arithmetic, factual provenance, unique
IDs, unit compatibility, chronology, dependency resolution or no double
counting. These are normative semantic checks for a future consumer:

1. Validate Draft 2020-12 shape and dates; reject unknown keys and nonfinite numbers.
2. Resolve unique source/period/observation/adjustment/claim IDs and every link.
3. Check source hashes against persisted payloads and store-qualified identity.
4. Preserve canonical values/statuses and source-specific conflicting definitions.
5. Recompute baseline and each included adjustment with stated inputs, units and period.
6. Require lower <= upper, acyclic prerequisites and no excluded/overlapping selections.
7. Propagate unsupported selected components; prohibit fabricated zero adjustments.
8. Recompute per-share output only with aligned positive shares; distinguish annual/current bases.
9. Keep investor assumptions CONDITIONAL and unapproved unless explicitly approved.
10. Preserve gates and sector limitations; never infer safety or valuation attractiveness.
11. Reject projected cases in v1; use existing Feature 8 for future scenarios.
12. Reject bridge fields in Authoring v2 or new keys inside its Reference objects.

Design validation uses the installed JSON Schema library without adding a
production dependency. In-memory synthetic cases exercise a signed USD
100 million deduction and a USD 50-100 million deduction interval, including
null/negative denominators and overlap rejection. These are arithmetic test
fixtures only, not proposed DECK assumptions. The real sample deliberately
keeps normalized owner earnings unresolved.

Read-only checks block HTTP and compare database SHA-256 before/after. They
recompute DECK's existing frozen scenario/variant results without calling
save, create, complete, refresh or provider ingestion.

Completed checks:

* Draft 2020-12 schema self-validation, sample validation and JSON round trip
* Twelve malformed-shape rejection cases, including nonfinite/mistyped amounts,
  numeric unsupported states, invalid dates and future earnings in v1
* Exact reported FCF and per-share reconciliation, synthetic scalar/range
  arithmetic, three invalid-share cases and three dependency/overlap constraints
* Four raw source payload hashes and exact source retrieval/filing dates
* Byte-identical DECK frozen snapshot round trip and read-only recapture/review
  at its actual evidence cutoff
* Rejection of two bridge/normalized fields at the Authoring v2 root and a
  new snapshot_id key inside its existing Reference type
* Existing three scenarios and four driver sensitivities recomputed read-only
* 150 focused regression tests passed; Ruff, mypy and diff checks passed
* Main and pilot database hashes unchanged, with HTTP blocked during evidence
  and frozen-underwriting validation

These are design probes and existing regression tests, not a shipped bridge
validator. In particular, cross-object semantic checks are specified above;
JSON Schema does not implement them or certify any normalization conclusion.

### Manual inspection

Open the two JSON artifacts and compare the schema's types with the sample's
dates, source hashes and null states. Check that the unadjusted baseline is
numeric while historical-normalization-unresolved remains null.
With the already installed JSON Schema library, validate the wire example:

```powershell
uv run python -c "import json; from pathlib import Path; from jsonschema import Draft202012Validator, FormatChecker; s=json.loads(Path(r'docs\examples\owner_earnings_bridge_v1.schema.json').read_text()); d=json.loads(Path(r'docs\examples\deck_owner_earnings_bridge_v1.sample.json').read_text()); Draft202012Validator.check_schema(s); Draft202012Validator(s, format_checker=FormatChecker()).validate(d); print('Bridge shape valid; semantic review still required')"
```

This library was available in the development environment; no production
dependency or automatic package installation is introduced.

Review DECK in the main persisted Workbench:
An existing raw-data override from pilot work must be removed or reset to the
main raw directory in that terminal:

```powershell
$env:OWNER_LENS_RAW_DATA_PATH = (Resolve-Path -LiteralPath .\data\raw).Path
uv run owner-lens workbench --db .\data\ownerlens.db --provider fmp
```

Open Company, select DECK, then Copy Research Context and Underwriting.
Compare current evidence to frozen v1 rather than mixing their observation
times. Do not select Commit & Analyze for contract review. In Screener,
compare ADSK, ORCL, INTC, CMG and JPM's existing warning/limitation details.

Focused unchanged-boundary regression:

```powershell
uv run pytest -q tests\test_owner_economics.py tests\test_capital_efficiency.py tests\test_research_context.py tests\test_underwriting_contract.py tests\test_underwriting_authoring.py tests\test_valuation.py tests\test_variant.py
uv run ruff check --no-cache src tests
uv run mypy src
git diff --check
```

No full normalization model, numerical recommendations, automated research,
provider refresh or new underwriting has been authorized. Contract shape and
baseline reproducibility can be validated now; normalized earnings usefulness
still requires investor research and review.

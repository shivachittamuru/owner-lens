---
title: "Feature 8F4: Workbench Underwriting Authoring"
description: "Author investor beliefs through a draft, review and explicit immutable save on the Company page."
---

## Company authoring

Launch the workbench against your persisted FMP store:

```powershell
uv run owner-lens workbench --provider fmp
```

Select Company, ADBE, Underwriting, then **Create New Underwriting**.
Saved versions remain read-only. The draft states which new version will be
created and that existing versions will not change. Opening a draft does not
create a record or run any retrieval, valuation or challenger.

Start blank, select **Start from latest underwriting**, or optionally import
authoring JSON into a draft. Cloning copies only investor beliefs, not saved
facts, estimates, valuations or challenger output. Previously authored reference
metadata and belief links are retained. JSON import/export and CLI creation
remain supported.

## Context and explicit assumptions

OwnerLens captures the same persisted, FMP-only FACT and EXPECTATION inputs used
by CLI creation. The draft displays starting financials, saved price/date,
nearest captured consensus periods and source retrieval metadata. As-of defaults
to the current UTC date and may be changed explicitly; refresh draft evidence
context after changing it. Refresh reads the local store only.

Each Bear/Base/Bull section contains narrative, four numeric assumptions and a
key dependency. Percentage controls use `8` for 8%; JSON/domain ratios remain
`0.08`. Terminal equity FCF multiple uses `15` for 15x.

Inputs start blank. Historical/consensus context never silently becomes an
assumption. Available presets must be selected and then explicitly applied:

* Historical latest: latest observed annual growth, margin or share change.
* Historical 3-5Y: revenue/share CAGR over available 3-5 fiscal-year intervals,
  using the existing CAGR helper and captured endpoints.
* Consensus: the existing 8D aligned annual revenue CAGR with its actual target,
  horizon and retrieval provenance, not a fabricated five-year forecast.

Absent evidence means the corresponding preset is absent. Terminal multiple
has no preset or invented consensus. No generic Conservative preset is offered:
calling an arbitrary haircut conservative would disguise investment judgment.
Manual numeric entry is always available.

The form shows historical latest/ranges, existing consensus and deterministic
warnings for assumptions outside annual observed ranges or Base growth above/
below captured consensus. Annual growth ranges are not forecast distributions
or multi-year CAGR ranges. These hints identify questions, not investment truth.

## Judgment and evidence

Probabilities start blank, display a live total and must sum to 100% within the
existing domain tolerance. They are never normalized. Probability rationale
and an explicit required-return hurdle are required.

Use repeatable controls for three to five business drivers, next evidence,
supporting/disconfirming evidence and separate dependencies/breakers. Variant
rationale has one optional text area per valuation driver.

Evidence supports category, claim, optional evidence id/date, repeatable source
title/URI/observation time/note and optional relations selected by belief label.
No JSON-pointer authoring is required. A category is an investor assertion,
not automatic verification. Missing supporting/disconfirming evidence remains
explicit and is not a blocker when the canonical contract allows an empty list.

Conditions support statement, observable, threshold, repeatable sources,
cadence and optional monitoring date. Condition ids are technical identifiers,
not generated thesis statements. A future monitoring date is an intention;
a source claiming a future observation is rejected at review.

## Review and immutable save

Select **Review Draft**. The canonical v2 parser and existing point-in-time/
belief-link validator run before persistence. Errors display without creating
a row. Review includes scenarios, separate probabilities/rationale, drivers,
variant rationale, uncertainty, evidence counts, conditions and investor policy;
details are available for inspection and authoring JSON download.

Select **Create Immutable Underwriting Version** to append the new record.
The exact reviewed facts/estimates are frozen: newer evidence arriving between
review and save is not silently substituted. Creation time is the actual save
time; the evidence cutoff remains the earlier capture time.

Editing a draft invalidates review. If another process creates a version after
review, an atomic version guard rejects the stale submission; review again.
There is no permanent autosave. Discarding a draft does not change the store.
Session drafts are temporary and are not underwriting versions.

After creation, the page reloads and shows the new version as `CAPTURED`.
Saved valuation/variant/summary/challenger values remain N/A until explicitly
generated. The existing offline command expander supplies the exact ticker/
version commands for valuation and challenger. Creation never executes them.

## ADBE validation flow

1. Launch the workbench, select ADBE and inspect the latest saved version.
2. Create a draft and verify all numeric inputs are blank.
3. Start from latest underwriting if you want to revise existing real beliefs.
4. Inspect captured price, annual starting facts and consensus dates before
   approving assumptions. Missing nearer estimates remain explicit.
5. Change a Base assumption manually or explicitly apply an available preset.
6. Confirm all three narratives/dependencies and the live probability total.
7. Review drivers, variant rationale, evidence links and observable breakers.
8. Select Review Draft and inspect the full review. Change a field and verify
   a second review is required.
9. Create the immutable version. Verify the new version is `CAPTURED` and the
   previous version is unchanged.
10. Run valuation/challenger only when you explicitly choose to do so using
    the displayed commands. Reload the Company page to inspect saved outputs.

No new schema, valuation methodology, LLM, autonomous retrieval, monitoring,
portfolio sizing or instrument selection is introduced. The source of truth
remains the [8F1 immutable contract](feature_08f1_underwriting_contract.md).

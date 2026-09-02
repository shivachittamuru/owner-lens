---
title: Adobe Balance Sheet and Capital Efficiency Research
description: Verified instant concepts, cash/debt/invested-capital/tax definitions, and derivation decisions
ms.date: 2026-09-01
ms.topic: reference
---

## Instant facts versus duration facts

A live inspection of Adobe's Company Facts (CIK 0000796343) confirmed the accounting distinction.
Balance-sheet concepts (cash, short-term investments, debt, total assets, total equity) are instant
facts: every observation has an `end` date and no `start` date. Income and cash-flow concepts (income
tax expense, pretax income) are duration facts with both `start` and `end`. Values quoted below verify
shape and definitions only; OwnerLens never hard-codes them.

Balance-sheet instants show the same `fy` comparative-repeat behavior as duration facts. For example,
Adobe's FY2024 year-end total assets (`end` 2024-11-29) appears in both the 2025-filed 10-K (`fy`
2024) and the 2026-filed 10-K (`fy` 2025) with the same value. Fiscal-year derivation from the
period-end date and earliest-filed deduplication therefore apply, but selection must use instant
semantics, not a duration window.

## Instant selection rule

**Decision**: Select balance-sheet observations that are instant (no `start`), have fiscal period
`FY`, and originate from an annual `10-K` (or `10-K/A`) form. Derive the fiscal year from the `end`
date's calendar year. Group by derived fiscal year, collapse identical repeats to the earliest-filed
observation, and raise a typed ambiguity error on distinct conflicting values.

**Rationale**: Instant facts have no duration, so the duration window is inapplicable and would be
meaningless. Requiring `FY` and 10-K context selects the fiscal-year-end balance and excludes interim
quarter-end instants, satisfying the preference for annual reporting. Adobe's fiscal year ends in late
November or early December, so the `end` date's calendar year equals the fiscal-year label and each
year maps to a single year-end date.

**Alternatives considered**:

* Reusing the duration window would either reject all instant facts or select them by an irrelevant
  criterion.
* Selecting by the raw `fy` field would misgroup comparative repeats, the same trap avoided in prior
  slices.
* Accepting any form would admit 10-Q comparative year-end instants; requiring 10-K keeps provenance
  on the original annual report.

## Instant primitive scope

**Decision**: Add a second selection path, `select_instant_series`, in the shared `_annual` module. It
reuses the fiscal-year grouping, earliest-filed deduplication, and ambiguity resolution already used
by `select_annual_series`, but qualifies facts with an instant rule instead of a duration window.
Duration and instant remain two clearly named functions.

**Rationale**: Cash, short-term investments, current debt, long-term debt, total assets, and total
equity duplicate the same instant selection. One small shared path removes that duplication while the
distinct name preserves the instant-versus-duration distinction the constitution and this slice
require.

**Alternatives considered**:

* Copying instant selection into each balance-sheet concept would duplicate it six times.
* Merging duration and instant into one flag-driven engine would blur the accounting distinction and
  make the code harder to reason about.

## Cash and short-term investments

**Decision**: Normalize cash (`CashAndCashEquivalentsAtCarryingValue`) and short-term investments
(`ShortTermInvestments`) as separate instant facts. Define canonical cash plus short-term investments
as `cash + short_term_investments`, treating short-term investments as optional and zero when absent.
Do not also add the combined concept.

**Rationale**: Adobe reports both separates and a combined `CashCashEquivalentsAndShortTermInvestments`
concept, and the separates sum exactly to the combined value (verified: 5,431 + 1,164 = 6,595).
Summing the two separates avoids double counting and preserves independent provenance for cash and
short-term investments, which the live view displays separately. The combined concept is a
cross-check, not an additional addend.

**Alternatives considered**:

* Adding the combined concept to the separates would double count.
* Using only the combined concept would lose the separate cash and short-term-investment provenance
  the view requires.

## Total debt

**Decision**: Define total debt as `current_debt + long_term_debt`, where current debt is `DebtCurrent`
and long-term debt is `LongTermDebt` (the noncurrent carrying amount). Current debt is optional and
zero when absent. Preserve the provenance of both components. Exclude current maturities reported
separately under `LongTermDebtCurrent` to avoid double counting, since `DebtCurrent` already captures
the current portion.

**Rationale**: Adobe has no `ShortTermDebt` concept; its interest-bearing debt is the current portion
plus the noncurrent long-term debt. Verified: FY2024 total debt 1,499 + 4,129 = 5,628; FY2025
0 + 6,210 = 6,210. Using `DebtCurrent` plus `LongTermDebt` captures total borrowings without
double counting current maturities or including unrelated operating liabilities.

**Alternatives considered**:

* Adding `LongTermDebtCurrent` would double count the current portion already in `DebtCurrent`.
* Including total liabilities would wrongly count payables and deferred revenue as debt.

## Invested capital and excess-cash treatment

**Decision**: Define invested capital as `total_debt + total_equity - (cash + short_term_investments)`,
treating all cash and short-term investments as excess for this initial, transparent definition. This
equals total equity minus net cash.

**Rationale**: This is a simple, reproducible starting definition that ties directly to the reported
capital structure and the net-cash figure this slice already computes. Documenting that all cash and
short-term investments are treated as excess makes the assumption explicit and easy to refine later,
rather than silently splitting operating and excess cash.

**Alternatives considered**:

* Treating no cash as excess (`total_debt + total_equity`) is simpler but ignores Adobe's substantial
  cash and would overstate the capital actually at work.
* Splitting operating versus excess cash requires a working-capital model, which is out of scope.

## Tax rate and NOPAT

**Decision**: Derive the effective tax rate per fiscal year as
`income_tax_expense / pretax_income`, using duration facts `IncomeTaxExpenseBenefit` and
`IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`
(falling back to the `...MinorityInterestAndIncomeLossFromEquityMethodInvestments` variant). Compute
NOPAT as `operating_income * (1 - effective_tax_rate)`. Omit the rate, and therefore ROIC, for any
year whose pretax income is missing or zero.

**Rationale**: A reported single-year effective rate is the simplest defensible approach and needs no
multi-year normalization model. Both tax inputs are duration full-year facts, so the existing Slice 1D
duration normalizer handles them directly. Omitting on invalid pretax income avoids a fabricated or
undefined rate. Live validation revealed that Adobe switched pretax concepts: the
`...ExtraordinaryItemsNoncontrollingInterest` variant carries fiscal years 2014 through 2025, while
the `...MinorityInterest...` variant stops at 2020 and contains a rounding restatement for fiscal
2019. The preference order therefore lists the recent variant first so current years are selected
cleanly, with the older variant retained only as a fallback.

**Alternatives considered**:

* A fixed statutory rate ignores Adobe's actual tax profile.
* A multi-year smoothed rate adds a model this slice explicitly avoids.

## Average-balance denominators and baseline year

**Decision**: Compute ROA, ROE, and ROIC with average balances: average total assets, average total
equity, and average invested capital are each the mean of the beginning and ending fiscal-year-end
balances. Fetch one additional prior fiscal-year-end (calculation-only baseline) so the earliest
displayed year can use a true beginning balance. Omit an average-based metric for any year whose
beginning balance is unavailable rather than substituting the ending balance.

**Rationale**: Average balances better match a full-year flow (net income, NOPAT) to the capital in
place during that year. A single baseline year supplies the beginning balance for the earliest
displayed year without expanding the displayed window. Omission on a missing baseline preserves
correctness over convenience.

**Alternatives considered**:

* Ending-balance denominators are simpler but mismatch a full-year numerator against a point-in-time
  balance and were explicitly discouraged.
* Fetching many extra years is unnecessary; one baseline year suffices for adjacent averages.

## Derived metric behavior

**Decision**: Derive net cash or net debt as `cash_plus_sti - total_debt`, ROA as
`net_income / average_total_assets`, ROE as `net_income / average_total_equity`, and ROIC as
`nopat / average_invested_capital`. Produce each derived metric only when its inputs exist and its
denominator is non-zero; otherwise omit it explicitly. Zero or negative equity omits ROE; negative net
cash and other economically valid negatives are valid.

**Rationale**: These are calculated values kept in a derived row type distinct from reported
observations. Deterministic arithmetic over aligned inputs is reproducible, and explicit omission on
missing inputs or zero denominators upholds fail-loudly without inventing values.

**Alternatives considered**:

* Emitting zero, null, or infinite for a zero or negative denominator would present a fabricated or
  undefined value as a fact.

## Test strategy

**Decision**: Add `test_balance_sheet.py` and `test_capital_efficiency.py` using in-memory fixtures
modeled on the verified instant and duration shapes, and extend `test_reported.py` for the tax and
pretax duration specs. Keep all existing tests. Cover instant-versus-duration handling, fiscal-year-end
selection, interim exclusion, comparative repeats, conflicting values, cash plus short-term
investments without double counting, debt aggregation, average-assets and average-equity, invested
capital, tax-rate derivation, NOPAT, ROA, ROE, ROIC, zero and negative denominators, and the missing
prior-year baseline omission.

**Rationale**: Controlled fixtures make the new instant selection, definitions, averages, and
derivations reproducible and exercise every failure and edge path deterministically without live
calls. Retaining the prior suites guards the primitive change.

**Alternatives considered**:

* Live-only validation is nondeterministic and cannot reliably reproduce conflicts, missing concepts,
  zero denominators, or the missing-baseline omission.

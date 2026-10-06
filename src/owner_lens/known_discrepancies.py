"""Documented SEC-vs-FMP discrepancies: the reconciliation audit trail (Slice 5C).

Each entry explains one investigated difference between the SEC-backed and the
FMP-backed canonical histories, with the evidence used to reach the conclusion.
Entries are data, not logic: ``reconcile_histories`` applies them only to rows that
still differ, and reports any entry that no longer matches a difference as stale,
so an explanation can never silently mask a future change.

``fmp_trusted`` answers one question: is FMP's value acceptable as an OwnerLens
fact? It is ``False`` when FMP deviates from the value the company filed, and
``True`` when FMP carries the filed canonical meaning (including cases where the
SEC path, not FMP, is the one that is wrong or incomplete).

Evidence was gathered on 2026-10-06 from live SEC Company Facts and cached FMP
``stable`` annual statements (``limit=5``).
"""

from __future__ import annotations

from typing import Final

from owner_lens.reconciliation import DiscrepancyCategory, KnownDiscrepancy

__all__ = ["KNOWN_DISCREPANCIES"]

_C = DiscrepancyCategory

KNOWN_DISCREPANCIES: Final[tuple[KnownDiscrepancy, ...]] = (
    # --- ADBE -----------------------------------------------------------------
    KnownDiscrepancy(
        ticker="ADBE",
        metric="capital_expenditures",
        fiscal_year=2024,
        category=_C.PROVIDER_NORMALIZATION,
        explanation=(
            "FMP reports 232M of FY2024 capital expenditures; Adobe filed 183M. This "
            "49M gap is the entire FCF difference (SEC 7,873M vs FMP 7,824M)."
        ),
        evidence=(
            "SEC PaymentsToAcquirePropertyPlantAndEquipment FY2024 = 183M in both the "
            "10-K filed 2025-01-13 (0000796343-25-000004) and the comparative in the "
            "10-K filed 2026-01-15 (0000796343-26-000003). FMP "
            "investmentsInPropertyPlantAndEquipment and capitalExpenditure both = -232M "
            "while otherInvestingActivities = 51M, so FMP reclassified investing cash "
            "flows away from the filed line items."
        ),
        fmp_trusted=False,
    ),
    KnownDiscrepancy(
        ticker="ADBE",
        metric="stock_based_compensation",
        fiscal_year=2024,
        category=_C.PROVIDER_NORMALIZATION,
        explanation="FMP reports 1,881M of FY2024 stock-based compensation; Adobe filed 1,833M.",
        evidence=(
            "SEC ShareBasedCompensation and AllocatedShareBasedCompensationExpense FY2024 "
            "= 1,833M in both the 2025-01-13 and 2026-01-15 10-Ks. FMP "
            "stockBasedCompensation = 1,881M (+48M); no filed line item matches it."
        ),
        fmp_trusted=False,
    ),
    # --- V --------------------------------------------------------------------
    KnownDiscrepancy(
        ticker="V",
        metric="repurchases",
        fiscal_year=2025,
        category=_C.PROVIDER_NORMALIZATION,
        explanation=(
            "FMP reports 13,389M of FY2025 common-stock repurchases; Visa filed 18,316M. "
            "FMP appears to move about 4.9B into other financing activities."
        ),
        evidence=(
            "SEC PaymentsForRepurchaseOfCommonStock FY2025 = 18,316M (10-K filed "
            "2025-11-06, 0001403161-25-000089). FMP commonStockRepurchased = -13,389M and "
            "otherFinancingActivities = -4,959M; earlier years match exactly."
        ),
        fmp_trusted=False,
    ),
    KnownDiscrepancy(
        ticker="V",
        metric="cash",
        fiscal_year=2025,
        category=_C.PROVIDER_NORMALIZATION,
        explanation=(
            "FMP reports 20,154M of FY2025 cash and equivalents; Visa filed 17,164M. FMP's "
            "figure matches neither the filed cash line nor the restricted-inclusive total."
        ),
        evidence=(
            "SEC CashAndCashEquivalentsAtCarryingValue FY2025 = 17,164M and "
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents = 24,987M (10-K "
            "filed 2025-11-06). FMP cashAndCashEquivalents = 20,154M (+2,990M); FY2021-FY2024 "
            "match exactly."
        ),
        fmp_trusted=False,
    ),
    KnownDiscrepancy(
        ticker="V",
        metric="diluted_shares",
        fiscal_year=None,
        category=_C.UNSUPPORTED,
        explanation=(
            "SEC Company Facts carry no undimensioned diluted-share count for Visa's "
            "multi-class structure, so the SEC path is UNSUPPORTED. FMP supplies an "
            "as-converted class A diluted count that cannot be verified against SEC."
        ),
        evidence=(
            "No WeightedAverageNumberOfDilutedSharesOutstanding or EarningsPerShareDiluted "
            "in Visa Company Facts. FMP weightedAverageShsOutDil FY2025 = 1,966M, equal to "
            "FMP netIncome / epsDiluted (20,058M / 10.20); FMP diluted equals basic in "
            "FY2022-FY2023, so FMP's share basis is not consistent across years."
        ),
        fmp_trusted=False,
    ),
    KnownDiscrepancy(
        ticker="V",
        metric="short_term_investments",
        fiscal_year=None,
        category=_C.POLICY_DIFFERENCE,
        explanation=(
            "OwnerLens canonical policy treats Visa's investment securities as not "
            "corporate excess cash (structurally absent). FMP reports them as short-term "
            "investments; this changes Visa's net cash and invested capital."
        ),
        evidence=(
            "SEC canonical policy: no ShortTermInvestments concept for Visa (Slice 3B). "
            "FMP shortTermInvestments FY2025 = 1,833M."
        ),
        fmp_trusted=True,
    ),
    # --- COST -----------------------------------------------------------------
    KnownDiscrepancy(
        ticker="COST",
        metric="current_debt",
        fiscal_year=2025,
        category=_C.PROVIDER_NORMALIZATION,
        explanation=(
            "FMP's FY2025 short-term debt (361M) includes 286M of current lease "
            "liabilities; Costco filed 75M of current long-term debt. Other years exclude "
            "leases, so FMP is inconsistent across years."
        ),
        evidence=(
            "SEC LongTermDebtCurrent FY2025 = 75M (10-K filed 2025-10-08, "
            "0000909832-25-000101); OperatingLeaseLiabilityCurrent = 208M and "
            "FinanceLeaseLiabilityCurrent = 78M. FMP shortTermDebt = 361M = 75M + "
            "capitalLeaseObligationsCurrent 286M."
        ),
        fmp_trusted=False,
    ),
    *(
        KnownDiscrepancy(
            ticker="COST",
            metric=metric,
            fiscal_year=2026,
            category=_C.PERIOD_TIMING,
            explanation=(
                "FMP has FY2026 (ended 2026-08-30) from a pre-10-K release; Costco had not "
                "filed its FY2026 10-K with the SEC when evidence was gathered."
            ),
            evidence=(
                "FMP filingDate 2026-09-24 for period end 2026-08-30. The latest SEC "
                "Company Facts observation for COST is the 10-Q filed 2026-06-03."
            ),
            fmp_trusted=False,
        )
        for metric in (
            "revenue",
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "capital_expenditures",
            "diluted_shares",
            "income_tax_expense",
            "pretax_income",
            "repurchases",
            "stock_based_compensation",
            "dividends_paid",
            "cash",
            "short_term_investments",
            "current_debt",
            "long_term_debt",
            "total_assets",
            "total_equity",
        )
    ),
    # --- MSFT -----------------------------------------------------------------
    # The former long_term_debt (SEC concept selection) and current_debt
    # (unsupported) entries were retired once MSFT gained the
    # LongTermDebtCurrent/LongTermDebtNoncurrent override; both went stale, as intended.
    KnownDiscrepancy(
        ticker="MSFT",
        metric="current_debt",
        fiscal_year=2024,
        category=_C.SEC_CONCEPT_SELECTION,
        explanation=(
            "At FY2024 year-end Microsoft held 6,693M of commercial paper in addition to "
            "2,249M of current long-term debt. The SEC path selects one concept "
            "(LongTermDebtCurrent) and so omits the commercial paper; FMP shortTermDebt "
            "(8,942M) is the complete current debt. Other years carry no commercial paper "
            "and match."
        ),
        evidence=(
            "FY2024 (10-K filed 2024-07-30): SEC LongTermDebtCurrent = 2,249M and "
            "CommercialPaper = 6,693M; FMP shortTermDebt = 8,942M = 2,249M + 6,693M. "
            "CommercialPaper is 0 at FY2023 and FY2025 year-ends. The canonical registry "
            "selects a single concept per metric and cannot sum concepts; follow-up."
        ),
        fmp_trusted=True,
    ),
    KnownDiscrepancy(
        ticker="MSFT",
        metric="short_term_investments",
        fiscal_year=None,
        category=_C.PROVIDER_NORMALIZATION,
        explanation=(
            "FMP short-term investments are 6-12M below Microsoft's filed amount in every "
            "compared year. The filed SEC value is authoritative; FMP's adjustment is "
            "unidentified."
        ),
        evidence=(
            "FY2025: SEC ShortTermInvestments = 64,323M (10-K filed 2025-07-30) vs FMP "
            "shortTermInvestments = 64,313M; FY2022-FY2024 differ by -8M, -6M, -12M."
        ),
        fmp_trusted=False,
    ),
)

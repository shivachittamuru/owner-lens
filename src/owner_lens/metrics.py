"""Canonical financial metric definitions and per-company concept resolution.

This module is the single auditable home for OwnerLens's canonical metric
definitions. Each definition names an economic concept OwnerLens uses, its fact
kind (duration or instant), expected unit, an ordered default source-concept
preference, and any minimal per-company overrides. Overrides are declarative and
traceable to observed SEC facts (see the compatibility matrix in
specs/011-generalize-metric-normalization/research.md); they fully replace the
default preference for a company rather than appending to it. Adobe carries no
overrides, so its concept selection is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from owner_lens._annual import TARGET_UNIT
from owner_lens.canonical import MetricKind

SHARES_UNIT: Final = "shares"


@dataclass(frozen=True)
class MetricComposition:
    """How a metric may be resolved when SEC splits it across several concepts.

    A metric's ``default_concepts`` name *total* concepts that already include
    every component, so they are always preferred and never summed (this is the
    double-counting guard). When no total resolves, the metric may be composed
    by adding the ``components`` reported at the same fiscal-year end.

    ``components`` are mutually exclusive additive parts in a documented order;
    the first one present supplies the composed fact's top-level provenance.
    Concepts whose economic meaning is wider than the canonical metric are
    deliberately absent from the list, never silently summed.

    ``unsafe`` names concepts that mix a component with economics the canonical
    metric excludes, so their presence makes the split undeterminable. A
    non-zero ``unsafe`` value refuses composition rather than understating.

    ``absence_proof`` is a ``(total, remainder)`` concept pair that proves the
    metric is zero from the company's own reported totals: when the company
    reports ``total`` at its latest fiscal-year end and that total either equals
    ``remainder`` or is zero, the metric is structurally absent. Absence is
    never inferred from a missing tag.
    """

    components: tuple[str, ...]
    unsafe: tuple[str, ...] = ()
    absence_proof: tuple[str, str] | None = None


@dataclass(frozen=True)
class CanonicalMetricDefinition:
    """A company-independent definition of one economic metric OwnerLens uses."""

    name: str
    kind: MetricKind
    unit: str
    default_concepts: tuple[str, ...]
    overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    composition: MetricComposition | None = None


def resolve_concepts(
    definition: CanonicalMetricDefinition,
    ticker: str,
) -> tuple[str, ...]:
    """Return the ordered concept preference for a metric and company.

    The company override fully replaces the default preference when present;
    otherwise the default is used. Resolution is deterministic and performs no
    network access.
    """
    canonical = ticker.strip().upper()
    return definition.overrides.get(canonical, definition.default_concepts)


# --- Duration metrics -------------------------------------------------------

REVENUE: Final = CanonicalMetricDefinition(
    "revenue",
    MetricKind.DURATION,
    TARGET_UNIT,
    (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
)
OPERATING_INCOME: Final = CanonicalMetricDefinition(
    "operating_income", MetricKind.DURATION, TARGET_UNIT, ("OperatingIncomeLoss",)
)
NET_INCOME: Final = CanonicalMetricDefinition(
    "net_income", MetricKind.DURATION, TARGET_UNIT, ("NetIncomeLoss",)
)
OPERATING_CASH_FLOW: Final = CanonicalMetricDefinition(
    "operating_cash_flow",
    MetricKind.DURATION,
    TARGET_UNIT,
    ("NetCashProvidedByUsedInOperatingActivities",),
)
CAPITAL_EXPENDITURES: Final = CanonicalMetricDefinition(
    "capital_expenditures",
    MetricKind.DURATION,
    TARGET_UNIT,
    ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
)
DILUTED_SHARES: Final = CanonicalMetricDefinition(
    "diluted_shares",
    MetricKind.DURATION,
    SHARES_UNIT,
    ("WeightedAverageNumberOfDilutedSharesOutstanding",),
)
INCOME_TAX_EXPENSE: Final = CanonicalMetricDefinition(
    "income_tax_expense", MetricKind.DURATION, TARGET_UNIT, ("IncomeTaxExpenseBenefit",)
)
PRETAX_INCOME: Final = CanonicalMetricDefinition(
    "pretax_income",
    MetricKind.DURATION,
    TARGET_UNIT,
    (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
)
REPURCHASES: Final = CanonicalMetricDefinition(
    "repurchases",
    MetricKind.DURATION,
    TARGET_UNIT,
    ("PaymentsForRepurchaseOfCommonStock",),
)
STOCK_BASED_COMPENSATION: Final = CanonicalMetricDefinition(
    "stock_based_compensation",
    MetricKind.DURATION,
    TARGET_UNIT,
    ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
)
DIVIDENDS_PAID: Final = CanonicalMetricDefinition(
    "dividends_paid",
    MetricKind.DURATION,
    TARGET_UNIT,
    ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
)

# --- Instant (balance-sheet) metrics ----------------------------------------

CASH: Final = CanonicalMetricDefinition(
    "cash", MetricKind.INSTANT, TARGET_UNIT, ("CashAndCashEquivalentsAtCarryingValue",)
)
SHORT_TERM_INVESTMENTS: Final = CanonicalMetricDefinition(
    "short_term_investments", MetricKind.INSTANT, TARGET_UNIT, ("ShortTermInvestments",)
)
# Current debt is the one metric SEC companies routinely split across concepts
# (Slice 6D). ``DebtCurrent`` is the total and always wins when reported, so
# components are never double counted. The four components are short-term
# borrowings in the canonical sense: the current portion of long-term debt,
# commercial paper, and other short-term borrowings.
#
# Deliberately NOT components (the economics are wider than debt):
#   OperatingLeaseLiabilityCurrent, FinanceLeaseLiabilityCurrent,
#   CapitalLeaseObligationsCurrent -- lease liabilities are not borrowings.
#   The Slice 5C Costco reconciliation, where FMP's current debt silently
#   included 286M of lease liabilities, is the standing warning against this.
#   ConvertibleDebtCurrent, NotesPayableCurrent, LinesOfCreditCurrent,
#   SecuredDebtCurrent -- these restate part of the current portion rather than
#   adding to it (CRM reports ConvertibleDebtCurrent equal to its whole
#   LongTermDebtCurrent), so summing them would double count.
#
# LongTermDebtAndCapitalLeaseObligationsCurrent is "unsafe": it bundles the
# current portion of debt with capital leases and cannot be split, so a
# non-zero value refuses composition (HD, KO, and LOW) rather than
# understating current debt or widening it to include leases.
#
# Per-company overrides are no longer needed for V, COST, or MSFT: all three
# resolve through the component policy.
_CURRENT_DEBT_COMPOSITION: Final = MetricComposition(
    components=(
        "LongTermDebtCurrent",
        "CommercialPaper",
        "ShortTermBorrowings",
        "OtherShortTermBorrowings",
    ),
    unsafe=("LongTermDebtAndCapitalLeaseObligationsCurrent",),
    absence_proof=("LongTermDebt", "LongTermDebtNoncurrent"),
)
CURRENT_DEBT: Final = CanonicalMetricDefinition(
    "current_debt",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("DebtCurrent",),
    composition=_CURRENT_DEBT_COMPOSITION,
)
LONG_TERM_DEBT: Final = CanonicalMetricDefinition(
    "long_term_debt",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("LongTermDebt",),
    overrides={
        # LongTermDebtNoncurrent excludes the current portion, so pairing it with
        # the current-debt policy avoids double counting. MSFT's LongTermDebt
        # includes the current portion (FY2025: 43,151M = 40,152M + 2,999M), so
        # it uses the same pair (verified in Slice 5C reconciliation).
        "V": ("LongTermDebtNoncurrent",),
        "COST": ("LongTermDebtNoncurrent",),
        "MSFT": ("LongTermDebtNoncurrent",),
    },
)
TOTAL_ASSETS: Final = CanonicalMetricDefinition(
    "total_assets", MetricKind.INSTANT, TARGET_UNIT, ("Assets",)
)
# V reports current equity under the including-noncontrolling-interest concept;
# ADBE and COST use the plain StockholdersEquity concept.
TOTAL_EQUITY: Final = CanonicalMetricDefinition(
    "total_equity",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("StockholdersEquity",),
    overrides={
        "V": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",)
    },
)

__all__ = [
    "CAPITAL_EXPENDITURES",
    "CASH",
    "CURRENT_DEBT",
    "DILUTED_SHARES",
    "DIVIDENDS_PAID",
    "INCOME_TAX_EXPENSE",
    "LONG_TERM_DEBT",
    "NET_INCOME",
    "OPERATING_CASH_FLOW",
    "OPERATING_INCOME",
    "PRETAX_INCOME",
    "REPURCHASES",
    "REVENUE",
    "SHARES_UNIT",
    "SHORT_TERM_INVESTMENTS",
    "STOCK_BASED_COMPENSATION",
    "TOTAL_ASSETS",
    "TOTAL_EQUITY",
    "CanonicalMetricDefinition",
    "MetricComposition",
    "MetricKind",
    "resolve_concepts",
]

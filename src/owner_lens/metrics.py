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
class CanonicalMetricDefinition:
    """A company-independent definition of one economic metric OwnerLens uses."""

    name: str
    kind: MetricKind
    unit: str
    default_concepts: tuple[str, ...]
    overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)


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
# V and COST report the current portion of debt under LongTermDebtCurrent; Adobe
# uses DebtCurrent. LongTermDebtNoncurrent excludes the current portion, so
# pairing it with LongTermDebtCurrent avoids double counting.
CURRENT_DEBT: Final = CanonicalMetricDefinition(
    "current_debt",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("DebtCurrent",),
    overrides={"V": ("LongTermDebtCurrent",), "COST": ("LongTermDebtCurrent",)},
)
LONG_TERM_DEBT: Final = CanonicalMetricDefinition(
    "long_term_debt",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("LongTermDebt",),
    overrides={"V": ("LongTermDebtNoncurrent",), "COST": ("LongTermDebtNoncurrent",)},
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
    "MetricKind",
    "resolve_concepts",
]

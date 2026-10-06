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
from enum import Enum
from typing import Final

from owner_lens._annual import TARGET_UNIT
from owner_lens.canonical import MetricKind

SHARES_UNIT: Final = "shares"


class ConceptDecision(Enum):
    """Verdict on a recurring SEC alternative concept (Slice 6E).

    Only ``SAFE_EQUIVALENT`` concepts are adopted automatically. The rest are
    recorded so a future reader sees they were evaluated and rejected on
    evidence, not overlooked.
    """

    SAFE_EQUIVALENT = "SAFE_EQUIVALENT"
    SEMANTICALLY_DIFFERENT = "SEMANTICALLY_DIFFERENT"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    REJECT = "REJECT"


@dataclass(frozen=True)
class AlternativeConcept:
    """One evaluated alternative SEC concept, its verdict, and the evidence."""

    metric: str
    concept: str
    decision: ConceptDecision
    rationale: str
    evidence: str

    @property
    def adopted(self) -> bool:
        return self.decision is ConceptDecision.SAFE_EQUIVALENT


# Slice 6E evaluated the recurring alternatives the 6A-6D survey surfaced.
# Measurements are from the 24-company survey snapshots of 2026-10-06.
ALTERNATIVE_CONCEPT_POLICY: Final[tuple[AlternativeConcept, ...]] = (
    AlternativeConcept(
        metric="long_term_debt",
        concept="LongTermDebtNoncurrent",
        decision=ConceptDecision.SAFE_EQUIVALENT,
        rationale=(
            "The canonical metric is noncurrent debt, the partner of current_debt; "
            "total debt is their sum. LongTermDebtNoncurrent states exactly that. "
            "LongTermDebt is ambiguous: some filers use it for the noncurrent line "
            "and others for the total including the current portion, which double "
            "counts when added to current debt. Preferring the explicit concept is "
            "both safer and more precise, and it replaces three company overrides."
        ),
        evidence=(
            "LongTermDebt equals LongTermDebtNoncurrent + LongTermDebtCurrent for "
            "MSFT (40,294 = 31,067 + 9,227), CRM (14,439 = 10,439 + 4,000), NVDA "
            "(8,468 = 7,469 + 999), INTU (7,669 = 6,420 + 1,249), NKE (7,942 = "
            "5,942 + 2,000), and KO (37,507 = 35,547 + 1,960). META reports both as "
            "58,744 (no current portion). ADBE, HD, and LOW report no noncurrent "
            "concept, so they keep LongTermDebt unchanged."
        ),
    ),
    AlternativeConcept(
        metric="net_income",
        concept="ProfitLoss",
        decision=ConceptDecision.SEMANTICALLY_DIFFERENT,
        rationale=(
            "ProfitLoss is consolidated profit including noncontrolling interests. "
            "OwnerLens net income is the earnings attributable to the owners of the "
            "parent, and it drives FCF per share, margins, ROE, and the Feature 2 "
            "classifications. Substituting a consolidated figure would silently "
            "credit owners with income they do not own."
        ),
        evidence=(
            "UNH FY2025 ProfitLoss 12,807M vs NetIncomeLoss 12,056M (+6.2%); CVX "
            "12,485M vs 12,299M; PG 16,144M vs 16,046M; DE 4,998M vs 5,027M "
            "(lower). Identical only where there is no noncontrolling interest "
            "(V, COST)."
        ),
    ),
    AlternativeConcept(
        metric="net_income",
        concept="NetIncomeLossAvailableToCommonStockholdersBasic",
        decision=ConceptDecision.SEMANTICALLY_DIFFERENT,
        rationale=(
            "This concept is net income after preferred dividends. It matches net "
            "income only for filers with no preferred stock, so adopting it would "
            "change the metric's definition for the filers that have some."
        ),
        evidence=(
            "ORCL FY2026 16,984M vs NetIncomeLoss 17,087M; PG 15,754M vs 16,046M; "
            "LOW 6,636M vs 6,654M. Equal for PFE."
        ),
    ),
    AlternativeConcept(
        metric="total_equity",
        concept="StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        decision=ConceptDecision.CONTEXT_DEPENDENT,
        rationale=(
            "Equity including noncontrolling interests is the right denominator for "
            "ROIC, whose NOPAT is consolidated, but the wrong one for ROE, whose "
            "numerator is parent net income. OwnerLens uses one equity series for "
            "both, so adopting this concept generally would understate ROE wherever "
            "the noncontrolling interest is material. Visa keeps a documented "
            "override because it reports no other equity concept and carries no "
            "noncontrolling interest at all."
        ),
        evidence=(
            "Noncontrolling interest as a share of equity: UNH 5,980M of 100,090M "
            "(6.0%), KO 2,106M of 34,275M (6.1%), CVX 5,726M of 192,176M (3.0%), PG "
            "230M of 54,311M (0.4%). V reports no MinorityInterest; COST reports "
            "both concepts as identical."
        ),
    ),
    AlternativeConcept(
        metric="cash",
        concept="CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        decision=ConceptDecision.SEMANTICALLY_DIFFERENT,
        rationale=(
            "Restricted cash is not available to owners. OwnerLens cash feeds net "
            "cash and invested capital, so including customer funds and other "
            "restricted balances would overstate excess cash and understate "
            "invested capital, sometimes by a large factor."
        ),
        evidence=(
            "INTU FY2026 9,216M vs CashAndCashEquivalentsAtCarryingValue 4,705M "
            "(+96%, customer funds); V 24,987M vs 17,164M (+46%); AMZN 90,106M vs "
            "86,810M; META 39,100M vs 35,873M. Identical where there is no "
            "restricted cash (ADBE, COST, MSFT, CRM, NVDA, NKE)."
        ),
    ),
)


def adopted_alternatives(metric: str) -> tuple[str, ...]:
    """Concepts adopted for a metric by the Slice 6E policy, in evaluation order."""
    return tuple(
        entry.concept
        for entry in ALTERNATIVE_CONCEPT_POLICY
        if entry.metric == metric and entry.adopted
    )


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
# The canonical metric is noncurrent debt: total debt is current_debt plus this
# series, so the two must not overlap. LongTermDebtNoncurrent says exactly that
# and is preferred (Slice 6E). LongTermDebt is the fallback for filers that
# report no noncurrent concept; for them it is the balance-sheet long-term line
# (ADBE, HD, LOW). Where a filer uses LongTermDebt for the total including the
# current portion, the preferred concept wins first, so nothing double counts.
LONG_TERM_DEBT: Final = CanonicalMetricDefinition(
    "long_term_debt",
    MetricKind.INSTANT,
    TARGET_UNIT,
    ("LongTermDebtNoncurrent", "LongTermDebt"),
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
    "ALTERNATIVE_CONCEPT_POLICY",
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
    "AlternativeConcept",
    "CanonicalMetricDefinition",
    "ConceptDecision",
    "MetricComposition",
    "MetricKind",
    "adopted_alternatives",
    "resolve_concepts",
]

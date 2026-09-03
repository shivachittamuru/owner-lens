"""OwnerLens package.

Exposes the SEC identity and raw Company Facts retrieval slice and a minimal
console entry point used to validate it.
"""

from __future__ import annotations

import os
import sys

from owner_lens._annual import AnnualObservation
from owner_lens.balance_sheet import (
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.capital_allocation import (
    DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS,
    BuybackEffectiveness,
    CapitalAllocationClassification,
    CapitalAllocationDriver,
    CapitalAllocationRow,
    CapitalAllocationThresholds,
    build_capital_allocation_rows,
    capital_allocation_from_facts,
    capital_allocation_summary,
    classify_buyback_effectiveness,
    format_capital_allocation_view,
)
from owner_lens.capital_efficiency import (
    CapitalEfficiencyRow,
    capital_efficiency_from_facts,
    compute_capital_efficiency,
)
from owner_lens.compounding import (
    DEFAULT_COMPOUNDING_THRESHOLDS,
    CompoundingClassification,
    CompoundingDriver,
    CompoundingThresholds,
    EconomicCompoundingView,
    build_compounding_view,
    cagr,
    classify_compounding,
    compounding_view_from_facts,
    compounding_views_from_facts,
    format_compounding_view,
)
from owner_lens.economic_summary import (
    DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS,
    EconomicSummaryThresholds,
    EconomicValueSummary,
    OverallEconomicValueClassification,
    SummaryDriver,
    economic_value_summary_from_facts,
    format_economic_value_summary,
    synthesize_economic_value_summary,
)
from owner_lens.economic_value import (
    DEFAULT_THRESHOLDS,
    EconomicValueClassification,
    EconomicValueDriver,
    EconomicValueSnapshot,
    EconomicValueThresholds,
    build_economic_value_snapshots,
    classify_economic_value,
    economic_value_from_facts,
    format_economic_value_view,
)
from owner_lens.margin import (
    AnnualMetricRow,
    OperatingMargin,
    align_annual_metrics,
    operating_margins,
)
from owner_lens.metrics import (
    CanonicalMetricDefinition,
    MetricKind,
    resolve_concepts,
)
from owner_lens.operating_income import (
    AmbiguousOperatingIncomeError,
    AnnualOperatingIncomeObservation,
    AnnualOperatingIncomeSeries,
    OperatingIncomeConceptNotFoundError,
    OperatingIncomeNormalizationError,
    normalize_annual_operating_income,
)
from owner_lens.owner_economics import (
    OwnerEconomicsRow,
    compute_owner_economics,
    owner_economics_from_facts,
)
from owner_lens.reported import (
    AmbiguousValueError,
    AnnualSeries,
    ConceptNotFoundError,
    normalize_annual_metric,
    normalize_capital_expenditures,
    normalize_diluted_shares,
    normalize_dividends_paid,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_operating_cash_flow,
    normalize_pretax_income,
    normalize_repurchases,
    normalize_stock_based_compensation,
)
from owner_lens.revenue import (
    AmbiguousRevenueError,
    AnnualRevenueObservation,
    AnnualRevenueSeries,
    MalformedFactsError,
    RevenueConceptNotFoundError,
    RevenueNormalizationError,
    normalize_annual_revenue,
)
from owner_lens.sec import (
    CompanyFactsResult,
    CompanyIdentity,
    CompanyIdentityMismatchError,
    CompanyResolutionError,
    MalformedSecResponseError,
    MalformedTickerError,
    SecClient,
    SecError,
    SecResponseError,
    SecTransportError,
)

__all__ = [
    "DEFAULT_CAPITAL_ALLOCATION_THRESHOLDS",
    "DEFAULT_COMPOUNDING_THRESHOLDS",
    "DEFAULT_ECONOMIC_SUMMARY_THRESHOLDS",
    "DEFAULT_THRESHOLDS",
    "AmbiguousOperatingIncomeError",
    "AmbiguousRevenueError",
    "AmbiguousValueError",
    "AnnualMetricRow",
    "AnnualObservation",
    "AnnualOperatingIncomeObservation",
    "AnnualOperatingIncomeSeries",
    "AnnualRevenueObservation",
    "AnnualRevenueSeries",
    "AnnualSeries",
    "BuybackEffectiveness",
    "CanonicalMetricDefinition",
    "CapitalAllocationClassification",
    "CapitalAllocationDriver",
    "CapitalAllocationRow",
    "CapitalAllocationThresholds",
    "CapitalEfficiencyRow",
    "CompanyFactsResult",
    "CompanyIdentity",
    "CompanyIdentityMismatchError",
    "CompanyResolutionError",
    "CompoundingClassification",
    "CompoundingDriver",
    "CompoundingThresholds",
    "ConceptNotFoundError",
    "EconomicCompoundingView",
    "EconomicSummaryThresholds",
    "EconomicValueClassification",
    "EconomicValueDriver",
    "EconomicValueSnapshot",
    "EconomicValueSummary",
    "EconomicValueThresholds",
    "MalformedFactsError",
    "MalformedSecResponseError",
    "MalformedTickerError",
    "MetricKind",
    "OperatingIncomeConceptNotFoundError",
    "OperatingIncomeNormalizationError",
    "OperatingMargin",
    "OverallEconomicValueClassification",
    "OwnerEconomicsRow",
    "RevenueConceptNotFoundError",
    "RevenueNormalizationError",
    "SecClient",
    "SecError",
    "SecResponseError",
    "SecTransportError",
    "SummaryDriver",
    "align_annual_metrics",
    "build_capital_allocation_rows",
    "build_compounding_view",
    "build_economic_value_snapshots",
    "cagr",
    "capital_allocation_from_facts",
    "capital_allocation_summary",
    "capital_efficiency_from_facts",
    "classify_buyback_effectiveness",
    "classify_compounding",
    "classify_economic_value",
    "compounding_view_from_facts",
    "compounding_views_from_facts",
    "compute_capital_efficiency",
    "compute_owner_economics",
    "economic_value_from_facts",
    "economic_value_summary_from_facts",
    "format_capital_allocation_view",
    "format_compounding_view",
    "format_economic_value_summary",
    "format_economic_value_view",
    "main",
    "normalize_annual_metric",
    "normalize_annual_operating_income",
    "normalize_annual_revenue",
    "normalize_capital_expenditures",
    "normalize_cash",
    "normalize_current_debt",
    "normalize_diluted_shares",
    "normalize_dividends_paid",
    "normalize_income_tax_expense",
    "normalize_long_term_debt",
    "normalize_net_income",
    "normalize_operating_cash_flow",
    "normalize_pretax_income",
    "normalize_repurchases",
    "normalize_short_term_investments",
    "normalize_stock_based_compensation",
    "normalize_total_assets",
    "normalize_total_equity",
    "operating_margins",
    "owner_economics_from_facts",
    "resolve_concepts",
    "synthesize_economic_value_summary",
]

_USER_AGENT_ENV_VAR = "OWNER_LENS_SEC_USER_AGENT"


def main() -> None:
    """Validate the slice by retrieving raw Company Facts for one ticker."""
    args = sys.argv[1:]
    if len(args) != 1:
        print("Usage: owner-lens <TICKER>", file=sys.stderr)
        raise SystemExit(2)
    ticker = args[0]

    user_agent = os.environ.get(_USER_AGENT_ENV_VAR, "").strip()
    if not user_agent:
        print(
            f"Set {_USER_AGENT_ENV_VAR} to an SEC User-Agent identifying the "
            "application and an administrative contact, for example "
            "'OwnerLens admin@example.com'.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        with SecClient(user_agent) as client:
            result = client.retrieve_company_facts(ticker)
    except SecError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    identity = result.identity
    raw = result.raw_facts
    print(f"ticker: {identity.ticker}")
    print(f"company: {identity.company_name}")
    print(f"CIK: {identity.cik}")
    print()
    print("top-level keys:")
    print(list(raw.keys()))
    print()

    facts = raw.get("facts", {})
    print("facts namespaces:")
    print(sorted(facts.keys()))
    print()

    us_gaap = facts.get("us-gaap", {})
    print("sample us-gaap concepts:")
    print(sorted(us_gaap.keys())[:10])
    print()
    print("-" * 30)


# $env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
# uv run owner-lens ADBE
# uv run owner-lens V
# uv run owner-lens COST
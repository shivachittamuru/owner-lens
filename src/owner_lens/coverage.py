"""Read-only golden-company coverage reporting for OwnerLens.

This module supports OwnerLens Slice 3C. It does not add an analytical feature:
it probes the existing normalizers and runs the existing Feature 1 and Feature 2
entry points to record, per company, which inputs are available, structurally
absent, or unsupported, and which analytical layers are available, partial,
insufficient, or unavailable. It performs no network access of its own; the
caller supplies raw Company Facts. Nothing here fabricates or substitutes a
value.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from owner_lens.balance_sheet import (
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.capital_allocation import (
    CapitalAllocationClassification,
    capital_allocation_from_facts,
)
from owner_lens.capital_efficiency import capital_efficiency_from_facts
from owner_lens.compounding import (
    CompoundingClassification,
    compounding_views_from_facts,
)
from owner_lens.economic_summary import (
    OverallEconomicValueClassification,
    economic_value_summary_from_facts,
    format_economic_value_summary,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    economic_value_from_facts,
)
from owner_lens.operating_income import (
    OperatingIncomeConceptNotFoundError,
    normalize_annual_operating_income,
)
from owner_lens.owner_economics import owner_economics_from_facts
from owner_lens.reported import (
    ConceptNotFoundError,
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
from owner_lens.revenue import RevenueConceptNotFoundError, normalize_annual_revenue

__all__ = [
    "CompanyCoverage",
    "LayerCoverage",
    "LayerResult",
    "MetricCoverage",
    "company_coverage",
    "company_output",
    "format_coverage_report",
]

# Concept-not-found is how a normalizer signals an unsupported input.
_CONCEPT_ERRORS = (
    ConceptNotFoundError,
    RevenueConceptNotFoundError,
    OperatingIncomeConceptNotFoundError,
)
_DILUTED_SHARES_REASON = "weighted-average diluted shares unsupported"


class MetricCoverage(Enum):
    """Coverage state of one canonical input metric."""

    AVAILABLE = "AVAILABLE"
    STRUCTURALLY_ABSENT = "STRUCTURALLY_ABSENT"
    UNSUPPORTED = "UNSUPPORTED"


class LayerCoverage(Enum):
    """Coverage state of one analytical layer."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class LayerResult:
    """The coverage outcome of one analytical layer, with its reason."""

    state: LayerCoverage
    reason: str | None = None
    blocking_input: str | None = None


@dataclass(frozen=True)
class CompanyCoverage:
    """The complete coverage picture for one company."""

    ticker: str
    inputs: dict[str, MetricCoverage]
    layers: dict[str, LayerResult]


_Normalizer = Callable[..., Any]

# Canonical input metrics probed for coverage, in a stable order.
_INPUTS: tuple[tuple[str, _Normalizer], ...] = (
    ("revenue", normalize_annual_revenue),
    ("operating_income", normalize_annual_operating_income),
    ("net_income", normalize_net_income),
    ("operating_cash_flow", normalize_operating_cash_flow),
    ("capital_expenditures", normalize_capital_expenditures),
    ("diluted_shares", normalize_diluted_shares),
    ("income_tax_expense", normalize_income_tax_expense),
    ("pretax_income", normalize_pretax_income),
    ("repurchases", normalize_repurchases),
    ("stock_based_compensation", normalize_stock_based_compensation),
    ("dividends_paid", normalize_dividends_paid),
    ("cash", normalize_cash),
    ("short_term_investments", normalize_short_term_investments),
    ("current_debt", normalize_current_debt),
    ("long_term_debt", normalize_long_term_debt),
    ("total_assets", normalize_total_assets),
    ("total_equity", normalize_total_equity),
)

# Analytical layers reported in the cross-company grid, in pipeline order.
LAYER_ORDER: tuple[str, ...] = (
    "owner_economics",
    "capital_efficiency",
    "economic_value",
    "compounding",
    "capital_allocation",
    "economic_summary",
)


def _probe_input(
    normalizer: _Normalizer,
    raw_facts: dict[str, Any],
    ticker: str,
    max_years: int,
) -> MetricCoverage:
    try:
        series = normalizer(raw_facts, ticker=ticker, max_years=max_years)
    except _CONCEPT_ERRORS:
        return MetricCoverage.UNSUPPORTED
    if not series.observations:
        return MetricCoverage.STRUCTURALLY_ABSENT
    return MetricCoverage.AVAILABLE


def company_coverage(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> CompanyCoverage:
    """Derive the per-input and per-layer coverage for one company."""
    inputs = {
        name: _probe_input(normalizer, raw_facts, ticker, max_years)
        for name, normalizer in _INPUTS
    }
    shares_unsupported = inputs["diluted_shares"] is MetricCoverage.UNSUPPORTED
    layers = _layer_coverage(raw_facts, ticker, max_years, shares_unsupported)
    return CompanyCoverage(ticker=ticker.strip().upper(), inputs=inputs, layers=layers)


def _layer_coverage(
    raw_facts: dict[str, Any],
    ticker: str,
    max_years: int,
    shares_unsupported: bool,
) -> dict[str, LayerResult]:
    share_reason = _DILUTED_SHARES_REASON if shares_unsupported else None
    share_input = "diluted_shares" if shares_unsupported else None
    layers: dict[str, LayerResult] = {}

    try:
        owner_economics_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    except _CONCEPT_ERRORS as exc:
        layers["owner_economics"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    if "owner_economics" not in layers:
        state = LayerCoverage.PARTIAL if shares_unsupported else LayerCoverage.AVAILABLE
        layers["owner_economics"] = LayerResult(state, share_reason, share_input)

    try:
        capital_efficiency_from_facts(raw_facts, ticker=ticker, max_years=max_years)
        layers["capital_efficiency"] = LayerResult(LayerCoverage.AVAILABLE)
    except _CONCEPT_ERRORS as exc:
        layers["capital_efficiency"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))

    snapshots = economic_value_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    if snapshots and all(
        s.classification is EconomicValueClassification.INSUFFICIENT_DATA
        for s in snapshots
    ):
        layers["economic_value"] = LayerResult(
            LayerCoverage.INSUFFICIENT_DATA, share_reason, share_input
        )
    else:
        layers["economic_value"] = LayerResult(LayerCoverage.AVAILABLE)

    recent, long_term = compounding_views_from_facts(
        raw_facts, ticker=ticker, max_years=max_years
    )
    if (
        recent.classification is CompoundingClassification.INSUFFICIENT_DATA
        and long_term.classification is CompoundingClassification.INSUFFICIENT_DATA
    ):
        layers["compounding"] = LayerResult(
            LayerCoverage.INSUFFICIENT_DATA, share_reason, share_input
        )
    else:
        layers["compounding"] = LayerResult(LayerCoverage.AVAILABLE)

    allocation = capital_allocation_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    if allocation and all(
        r.classification is CapitalAllocationClassification.INSUFFICIENT_DATA
        for r in allocation
    ):
        # Reported repurchase, SBC, and dividend facts remain available; only the
        # classification is blocked, so the layer is partial rather than absent.
        layers["capital_allocation"] = LayerResult(
            LayerCoverage.PARTIAL, share_reason, share_input
        )
    else:
        layers["capital_allocation"] = LayerResult(LayerCoverage.AVAILABLE)

    summary = economic_value_summary_from_facts(raw_facts, ticker=ticker, max_years=max_years)
    if (
        summary.overall_economic_value_classification
        is OverallEconomicValueClassification.INSUFFICIENT_DATA
    ):
        layers["economic_summary"] = LayerResult(
            LayerCoverage.INSUFFICIENT_DATA, share_reason, share_input
        )
    else:
        layers["economic_summary"] = LayerResult(LayerCoverage.AVAILABLE)

    return layers


def _is_full(coverage: CompanyCoverage) -> bool:
    return all(
        result.state is LayerCoverage.AVAILABLE for result in coverage.layers.values()
    )


def format_coverage_report(coverages: Sequence[CompanyCoverage]) -> str:
    """Render a deterministic company-by-layer coverage grid with reasons."""
    headers = ["Company", *LAYER_ORDER]
    widths = [max(len(h), 10) for h in headers]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))]
    lines.append("  ".join("-" * w for w in widths))
    for coverage in coverages:
        cells = [coverage.ticker.ljust(widths[0])]
        for i, layer in enumerate(LAYER_ORDER, start=1):
            cells.append(coverage.layers[layer].state.value.ljust(widths[i]))
        lines.append("  ".join(cells))

    reasons: list[str] = []
    for coverage in coverages:
        for layer in LAYER_ORDER:
            result = coverage.layers[layer]
            if result.state is not LayerCoverage.AVAILABLE and result.reason:
                reasons.append(f"  {coverage.ticker} {layer}: {result.reason}")
    if reasons:
        lines.append("")
        lines.append("Reasons:")
        lines.extend(reasons)
    return "\n".join(lines)


def company_output(
    coverage: CompanyCoverage,
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> str:
    """Render the most complete honest per-company result.

    A full-coverage company shows its compact economic-value summary; a partial
    company shows available evidence, unavailable layers, and the exact missing
    or unsupported inputs, with no fabricated classification.
    """
    if _is_full(coverage):
        summary = economic_value_summary_from_facts(
            raw_facts, ticker=ticker, max_years=max_years
        )
        return format_economic_value_summary(summary)

    available = [n for n, r in coverage.layers.items() if r.state is LayerCoverage.AVAILABLE]
    limited = [
        (n, r) for n, r in coverage.layers.items() if r.state is not LayerCoverage.AVAILABLE
    ]
    unsupported = [n for n, s in coverage.inputs.items() if s is MetricCoverage.UNSUPPORTED]
    absent = [
        n for n, s in coverage.inputs.items() if s is MetricCoverage.STRUCTURALLY_ABSENT
    ]

    lines = [f"{coverage.ticker} - OwnerLens Coverage (partial)", ""]
    lines.append(f"Available layers: {', '.join(available) or 'none'}")
    lines.append("Limited layers:")
    for name, result in limited:
        reason = f" ({result.reason})" if result.reason else ""
        lines.append(f"  {name}: {result.state.value}{reason}")
    lines.append(f"Unsupported inputs: {', '.join(unsupported) or 'none'}")
    lines.append(f"Structurally absent inputs: {', '.join(absent) or 'none'}")
    lines.append("")
    lines.append("No classification is fabricated for unavailable per-share analysis.")
    return "\n".join(lines)

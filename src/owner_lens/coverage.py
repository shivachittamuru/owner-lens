"""Read-only golden-company coverage reporting for OwnerLens.

This module supports OwnerLens Slice 3C. It does not add an analytical feature:
it reads each canonical input's status and runs the existing Feature 1 and
Feature 2 entry points to record, per company, which inputs are available,
structurally absent, or unsupported, and which analytical layers are available,
partial, insufficient, or unavailable. Since Slice 5A it consumes only a
provider-neutral ``CanonicalFinancialHistory``; ``company_coverage`` and
``company_output`` remain as compatibility wrappers over raw SEC Company Facts.
Nothing here fabricates or substitutes a value.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from owner_lens.canonical import (
    CanonicalFinancialHistory,
    MetricStatus,
    MetricUnsupportedError,
)
from owner_lens.capital_allocation import (
    CapitalAllocationClassification,
    capital_allocation_from_history,
)
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.compounding import (
    CompoundingClassification,
    compounding_views_from_history,
)
from owner_lens.economic_summary import (
    EconomicValueSummary,
    OverallEconomicValueClassification,
    economic_value_summary_from_facts,
    economic_value_summary_from_history,
    format_economic_value_summary,
)
from owner_lens.economic_value import (
    EconomicValueClassification,
    economic_value_from_history,
)
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "CompanyCoverage",
    "LayerCoverage",
    "LayerResult",
    "MetricCoverage",
    "company_coverage",
    "company_coverage_from_history",
    "company_output",
    "company_output_from_history",
    "format_coverage_report",
]

# A required input that is unsupported surfaces as this provider-neutral error.
_CONCEPT_ERRORS = (MetricUnsupportedError,)
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


_STATUS_COVERAGE = {
    MetricStatus.AVAILABLE: MetricCoverage.AVAILABLE,
    MetricStatus.STRUCTURALLY_ABSENT: MetricCoverage.STRUCTURALLY_ABSENT,
    MetricStatus.UNSUPPORTED: MetricCoverage.UNSUPPORTED,
}

# Analytical layers reported in the cross-company grid, in pipeline order.
LAYER_ORDER: tuple[str, ...] = (
    "owner_economics",
    "capital_efficiency",
    "economic_value",
    "compounding",
    "capital_allocation",
    "economic_summary",
)


def _input_coverage(history: CanonicalFinancialHistory) -> dict[str, MetricCoverage]:
    inputs: dict[str, MetricCoverage] = {}
    for metric, status in history.statuses().items():
        if status is MetricStatus.INVALID:
            history.require(metric)  # re-raises the stored malformed/ambiguous error
        inputs[metric] = _STATUS_COVERAGE[status]
    return inputs


def company_coverage_from_history(history: CanonicalFinancialHistory) -> CompanyCoverage:
    """Derive the per-input and per-layer coverage for one company's canonical history."""
    inputs = _input_coverage(history)
    shares_unsupported = inputs["diluted_shares"] is MetricCoverage.UNSUPPORTED
    layers = _layer_coverage(history, shares_unsupported)
    return CompanyCoverage(ticker=history.ticker, inputs=inputs, layers=layers)


def company_coverage(
    raw_facts: dict[str, Any],
    *,
    ticker: str = "ADBE",
    max_years: int = 5,
) -> CompanyCoverage:
    """Compatibility wrapper: map raw SEC Company Facts, then derive coverage."""
    return company_coverage_from_history(
        canonical_history_from_sec(raw_facts, ticker=ticker, max_years=max_years)
    )


def _layer_coverage(
    history: CanonicalFinancialHistory,
    shares_unsupported: bool,
) -> dict[str, LayerResult]:
    share_reason = _DILUTED_SHARES_REASON if shares_unsupported else None
    share_input = "diluted_shares" if shares_unsupported else None
    layers: dict[str, LayerResult] = {}

    try:
        owner_economics_from_history(history)
    except _CONCEPT_ERRORS as exc:
        layers["owner_economics"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    if "owner_economics" not in layers:
        state = LayerCoverage.PARTIAL if shares_unsupported else LayerCoverage.AVAILABLE
        layers["owner_economics"] = LayerResult(state, share_reason, share_input)

    try:
        capital_efficiency_from_history(history)
        layers["capital_efficiency"] = LayerResult(LayerCoverage.AVAILABLE)
    except _CONCEPT_ERRORS as exc:
        layers["capital_efficiency"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))

    try:
        snapshots = economic_value_from_history(history)
    except _CONCEPT_ERRORS as exc:
        layers["economic_value"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    else:
        if snapshots and all(
            s.classification is EconomicValueClassification.INSUFFICIENT_DATA
            for s in snapshots
        ):
            layers["economic_value"] = LayerResult(
                LayerCoverage.INSUFFICIENT_DATA, share_reason, share_input
            )
        else:
            layers["economic_value"] = LayerResult(LayerCoverage.AVAILABLE)

    try:
        recent, long_term = compounding_views_from_history(history)
    except _CONCEPT_ERRORS as exc:
        layers["compounding"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    else:
        if (
            recent.classification is CompoundingClassification.INSUFFICIENT_DATA
            and long_term.classification is CompoundingClassification.INSUFFICIENT_DATA
        ):
            layers["compounding"] = LayerResult(
                LayerCoverage.INSUFFICIENT_DATA, share_reason, share_input
            )
        else:
            layers["compounding"] = LayerResult(LayerCoverage.AVAILABLE)

    try:
        allocation = capital_allocation_from_history(history)
    except _CONCEPT_ERRORS as exc:
        layers["capital_allocation"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    else:
        if allocation and all(
            r.classification is CapitalAllocationClassification.INSUFFICIENT_DATA
            for r in allocation
        ):
            # Reported repurchase, SBC, and dividend facts remain available; only
            # the classification is blocked, so the layer is partial not absent.
            layers["capital_allocation"] = LayerResult(
                LayerCoverage.PARTIAL, share_reason, share_input
            )
        else:
            layers["capital_allocation"] = LayerResult(LayerCoverage.AVAILABLE)

    try:
        summary = economic_value_summary_from_history(history)
    except _CONCEPT_ERRORS as exc:
        layers["economic_summary"] = LayerResult(LayerCoverage.UNAVAILABLE, str(exc))
    else:
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
    """Render the most complete honest per-company result from raw SEC Company Facts.

    Compatibility wrapper; the summary echoes the caller's ``ticker`` exactly.
    """
    return _render_output(
        coverage,
        lambda: economic_value_summary_from_facts(
            raw_facts, ticker=ticker, max_years=max_years
        ),
    )


def company_output_from_history(
    coverage: CompanyCoverage,
    history: CanonicalFinancialHistory,
) -> str:
    """Render the most complete honest per-company result from a canonical history."""
    return _render_output(coverage, lambda: economic_value_summary_from_history(history))


def _render_output(
    coverage: CompanyCoverage,
    summarize: Callable[[], EconomicValueSummary],
) -> str:
    """Render a full summary, or for a partial company the honest coverage picture.

    A full-coverage company shows its compact economic-value summary; a partial
    company shows available evidence, unavailable layers, and the exact missing
    or unsupported inputs, with no fabricated classification.
    """
    if _is_full(coverage):
        return format_economic_value_summary(summarize())

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

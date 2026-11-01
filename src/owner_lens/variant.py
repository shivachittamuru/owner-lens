"""Offline variant comparison and one-at-a-time deterministic BASE sensitivity."""

from __future__ import annotations

import json
import math
from calendar import monthrange
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

from owner_lens.persistence import UnderwritingRecord, compute_content_hash
from owner_lens.underwriting import (
    BaseRate,
    DriverRationale,
    ScenarioName,
    SemanticType,
    UnderwritingSnapshot,
)
from owner_lens.valuation import ScenarioValuation, ValuationError, value_underwriting

MODEL_VERSION = "variant-base-local-sensitivity-v1"
DRIVERS = (
    "revenue_cagr",
    "fcf_margin_year5",
    "share_count_cagr",
    "terminal_fcf_multiple",
)
_HISTORY = {
    "revenue_cagr": "revenue_growth",
    "fcf_margin_year5": "fcf_margin",
    "share_count_cagr": "share_count_change",
}
_LABELS = {
    "revenue_cagr": "Revenue CAGR",
    "fcf_margin_year5": "FCF margin",
    "share_count_cagr": "Share CAGR",
    "terminal_fcf_multiple": "Terminal multiple",
}


class VariantError(ValueError):
    """Invalid point-in-time expectations or sensitivity inputs."""


@dataclass(frozen=True)
class Consensus:
    value: float | None
    low: float | None = None
    high: float | None = None
    horizon_years: int | None = None
    target_date: str | None = None
    snapshot_id: int | None = None
    fetched_at: str | None = None
    content_hash: str | None = None
    analyst_count: int | None = None
    reason: str | None = None
    category: SemanticType = SemanticType.EXPECTATION
    calculation: str | None = None
    basis_category: SemanticType = SemanticType.CALCULATION


@dataclass(frozen=True)
class Sensitivity:
    perturbation: float
    original_assumption: float
    perturbed_assumption: float
    base_value_per_share: float
    perturbed_value_per_share: float
    value_delta: float
    value_percentage_delta: float | None
    base_implied_cagr: float
    perturbed_implied_cagr: float
    cagr_delta: float
    band: str
    category: SemanticType = SemanticType.CALCULATION


@dataclass(frozen=True)
class DriverComparison:
    driver: str
    history: BaseRate | None
    consensus: Consensus
    assumption: float
    absolute_delta: float | None
    percentage_delta: float | None
    direction: str
    material: bool
    materiality_threshold: float
    sensitivity: Sensitivity
    rationale: DriverRationale | None
    history_reason: str | None = None
    assumption_category: SemanticType = SemanticType.ASSUMPTION
    difference_category: SemanticType = SemanticType.CALCULATION


@dataclass(frozen=True)
class VariantReport:
    underwriting_id: str
    underwriting_version: int
    underwriting_content_hash: str
    ticker: str
    as_of_date: str
    drivers: tuple[DriverComparison, ...]
    conclusion: str
    model_version: str = MODEL_VERSION
    scenario: str = "BASE"
    conclusion_category: SemanticType = SemanticType.CALCULATION

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VariantError(f"{label} must be a finite numeric value.")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise VariantError(f"{label} exceeds numeric range.") from exc
    if not math.isfinite(numeric):
        raise VariantError(f"{label} must be finite.")
    return numeric


def _timestamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _revenue_consensus(
    snapshot: UnderwritingSnapshot, record: UnderwritingRecord
) -> Consensus:
    """Annual target CAGR from the frozen starting fact, never five-year extrapolation."""
    evidence = json.loads(snapshot.evidence_json)
    expectations = evidence.get("market_expectations")
    if expectations is None:
        return Consensus(
            None, reason="No market expectations captured in this underwriting."
        )
    if expectations["category"] != SemanticType.EXPECTATION:
        raise VariantError("Consensus must remain EXPECTATION.")
    candidates = [
        item
        for item in expectations["snapshots"]
        if item["source"]["dataset"] == "annual_analyst_estimates"
    ]
    if not candidates:
        return Consensus(None, reason="No annual analyst estimate snapshot captured.")
    cutoff = min(
        _timestamp(record.created_at),
        _timestamp(record.as_of_date + "T23:59:59.999999+00:00"),
    )
    if evidence.get("cutoff"):
        cutoff = min(cutoff, _timestamp(evidence["cutoff"]))
    for item in candidates:
        source = item["source"]
        if source["evidence_kind"] != SemanticType.EXPECTATION:
            raise VariantError("Annual analyst source is not EXPECTATION.")
        if source["period_type"] != "annual":
            raise VariantError("Annual analyst source must have annual period type.")
        if _timestamp(source["fetched_at"]) > cutoff:
            raise VariantError(
                "Captured consensus was retrieved after underwriting cutoff."
            )
    selected = max(
        candidates,
        key=lambda item: (
            _timestamp(item["source"]["fetched_at"]),
            item["source"]["snapshot_id"],
        ),
    )
    source = selected["source"]
    provenance = {
        "snapshot_id": source["snapshot_id"],
        "fetched_at": source["fetched_at"],
        "content_hash": source["content_hash"],
    }
    revenue = next(
        item for item in snapshot.starting_financial_state if item.name == "revenue"
    )
    starting = _finite(revenue.value, "Starting revenue")
    facts = evidence.get("canonical_history", {}).get("facts", [])
    start_dates = {
        item["period_end"]
        for item in facts
        if item["metric"] == "revenue" and item["fiscal_year"] == revenue.fiscal_year
    }
    if len(start_dates) != 1:
        return Consensus(
            None,
            **provenance,
            reason="No unambiguous starting revenue fiscal period end.",
        )
    start_end = date.fromisoformat(next(iter(start_dates)))
    compatible: list[dict[str, Any]] = []
    for row in selected["rows"]:
        if (
            row["evidence_kind"] != SemanticType.EXPECTATION
            or row["snapshot_id"] != source["snapshot_id"]
        ):
            raise VariantError(
                "Estimate row category/snapshot does not match its captured source."
            )
        target = date.fromisoformat(row["target_date"])
        years = target.year - start_end.year
        if 1 <= years <= 5:
            anniversary = date(
                target.year,
                start_end.month,
                min(start_end.day, monthrange(target.year, start_end.month)[1]),
            )
            # Allow normal 52/53-week fiscal-calendar drift, not calendar-quarter substitution.
            if abs((target - anniversary).days) <= 14:
                compatible.append(row)
    if not compatible:
        return Consensus(
            None,
            **provenance,
            reason="No annual target aligned to starting fiscal year-end within five years.",
        )
    dates = [row["target_date"] for row in compatible]
    if len(set(dates)) != len(dates):
        raise VariantError("Duplicate annual estimate target periods.")
    # Farthest aligned target; never fall back to an older target when its average is missing.
    row = max(compatible, key=lambda item: item["target_date"])
    years = date.fromisoformat(row["target_date"]).year - start_end.year
    if row.get("revenue_average") is None:
        return Consensus(
            None,
            **provenance,
            horizon_years=years,
            target_date=row["target_date"],
            reason="Farthest aligned annual target has no revenue average.",
        )

    def cagr(value: Any) -> float | None:
        if value is None:
            return None
        amount = _finite(value, "Consensus revenue")
        if amount <= 0:
            raise VariantError("Consensus revenue must be positive.")
        return _finite((amount / starting) ** (1 / years) - 1, "Consensus revenue CAGR")

    average, low, high = (
        cagr(row["revenue_average"]),
        cagr(row.get("revenue_low")),
        cagr(row.get("revenue_high")),
    )
    if average is None:
        raise VariantError("Consensus revenue average is missing.")
    if (low is not None and low > average) or (high is not None and high < average):
        raise VariantError("Consensus revenue low/average/high range is inconsistent.")
    count = row.get("revenue_analyst_count")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count < 0
    ):
        raise VariantError("Consensus analyst count must be a non-negative integer.")
    return Consensus(
        average,
        low,
        high,
        years,
        row["target_date"],
        analyst_count=count,
        **provenance,
        calculation="(target revenue / starting revenue)^(1 / aligned fiscal years) - 1",
    )


def _base(results: tuple[ScenarioValuation, ...]) -> ScenarioValuation:
    return next(
        result for result in results if result.assumptions.name is ScenarioName.BASE
    )


def _sensitivity(
    record: UnderwritingRecord,
    snapshot: UnderwritingSnapshot,
    base: ScenarioValuation,
    driver: str,
) -> Sensitivity:
    original = float(getattr(base.assumptions, driver))
    step = 1.0 if driver == "terminal_fcf_multiple" else 0.01
    if driver == "fcf_margin_year5" and original + step > 1:
        step = -step
    if driver == "revenue_cagr":
        changed = replace(base.assumptions, revenue_cagr=original + step)
    elif driver == "fcf_margin_year5":
        changed = replace(base.assumptions, fcf_margin_year5=original + step)
    elif driver == "share_count_cagr":
        changed = replace(base.assumptions, share_count_cagr=original + step)
    else:
        changed = replace(base.assumptions, terminal_fcf_multiple=original + step)
    scenarios = tuple(
        changed if item.name is ScenarioName.BASE else item
        for item in snapshot.manual.scenarios
    )
    payload = replace(
        snapshot, manual=replace(snapshot.manual, scenarios=scenarios)
    ).to_json()
    # A transient counterfactual, not a new persisted belief or underwriting version.
    counterfactual = replace(
        record,
        snapshot_json=payload,
        content_hash=compute_content_hash(payload.encode()),
    )
    perturbed = _base(value_underwriting(counterfactual).scenarios)
    cagr_delta = perturbed.implied_5y_cagr - base.implied_5y_cagr
    magnitude = abs(cagr_delta)
    band = (
        "HIGH"
        if magnitude >= 0.02 - 1e-12
        else "MEDIUM"
        if magnitude >= 0.01 - 1e-12
        else "LOW"
    )
    value_delta = perturbed.year5_value_per_share - base.year5_value_per_share
    return Sensitivity(
        step,
        original,
        original + step,
        base.year5_value_per_share,
        perturbed.year5_value_per_share,
        value_delta,
        value_delta / abs(base.year5_value_per_share)
        if base.year5_value_per_share
        else None,
        base.implied_5y_cagr,
        perturbed.implied_5y_cagr,
        cagr_delta,
        band,
    )


def compare_variant(record: UnderwritingRecord) -> VariantReport:
    """Derive a versioned report from immutable evidence only; no storage mutations."""
    try:
        baseline = value_underwriting(record)
        snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
        base = _base(baseline.scenarios)
        consensus_revenue = _revenue_consensus(snapshot, record)
        histories = {item.name: item for item in snapshot.historical_base_rates}
        rationales = {item.driver: item for item in snapshot.manual.variant_rationales}
        drivers: list[DriverComparison] = []
        for driver in DRIVERS:
            consensus = (
                consensus_revenue
                if driver == "revenue_cagr"
                else Consensus(
                    None,
                    reason="Captured FMP revenue/EPS estimates do not provide comparable "
                    + _LABELS[driver]
                    + " consensus.",
                )
            )
            mine = _finite(getattr(base.assumptions, driver), driver)
            delta = mine - consensus.value if consensus.value is not None else None
            percentage = (
                delta / abs(consensus.value)
                if delta is not None and consensus.value
                else None
            )
            threshold = 0.01 if driver != "terminal_fcf_multiple" else 1.0
            material = delta is not None and abs(delta) >= threshold - 1e-12
            direction = (
                "UNAVAILABLE"
                if delta is None
                else "ALIGNED"
                if abs(delta) < 1e-12
                else "ABOVE"
                if delta > 0
                else "BELOW"
            )
            history = histories.get(_HISTORY.get(driver, ""))
            if history and history.category not in (
                SemanticType.FACT,
                SemanticType.CALCULATION,
            ):
                raise VariantError("Historical base rates must be FACT/CALCULATION.")
            drivers.append(
                DriverComparison(
                    driver,
                    history,
                    consensus,
                    mine,
                    delta,
                    percentage,
                    direction,
                    material,
                    threshold,
                    _sensitivity(record, snapshot, base, driver),
                    rationales.get(driver),
                    history_reason=history.missing_reason
                    if history
                    else "No historical reference captured for this driver.",
                )
            )
        conclusion = (
            "IDENTIFIABLE_VARIANT_VIEW"
            if any(item.material and item.rationale for item in drivers)
            else "NO_IDENTIFIABLE_VARIANT_VIEW"
        )
        return VariantReport(
            record.underwriting_id,
            record.version,
            record.content_hash,
            record.ticker,
            record.as_of_date,
            tuple(drivers),
            conclusion,
        )
    except (
        ValuationError,
        ValueError,
        TypeError,
        KeyError,
        StopIteration,
        OverflowError,
    ) as exc:
        if isinstance(exc, VariantError):
            raise
        raise VariantError(f"Cannot compare immutable underwriting: {exc}") from exc


def format_variant(report: VariantReport) -> str:
    def number(value: float | None, multiple: bool = False) -> str:
        return (
            "n/a" if value is None else f"{value:.2f}x" if multiple else f"{value:.2%}"
        )

    lines = [
        f"{report.ticker} underwriting v{report.underwriting_version} | {report.as_of_date} | {report.model_version}",
        "History=FACT/CALCULATION; consensus=EXPECTATION; mine=ASSUMPTION; deltas/sensitivity=CALCULATION.",
        "Driver              History   Consensus       Mine     Delta   Sensitivity",
    ]
    for item in report.drivers:
        multiple = item.driver == "terminal_fcf_multiple"
        lines.append(
            f"{_LABELS[item.driver]:<19} {number(item.history.latest if item.history else None, multiple):>8} "
            f"{number(item.consensus.value, multiple):>11} {number(item.assumption, multiple):>10} "
            f"{number(item.absolute_delta, multiple):>9} {item.sensitivity.band:>13}"
        )
    lines.append(report.conclusion + " (not an edge or investment recommendation)")
    lines.append(
        "Sensitivity: one-at-a-time +1pp ratios / +1x multiple; LOW <1pp, MEDIUM 1-2pp, HIGH >=2pp absolute CAGR effect."
    )
    for item in report.drivers:
        lines.append(
            f"\n{_LABELS[item.driver]}: {item.direction}; material={item.material}"
        )
        if item.history:
            lines.append(
                f"Historical latest/range: {number(item.history.latest)} / "
                f"{number(item.history.minimum)} to {number(item.history.maximum)}"
            )
        else:
            lines.append("History n/a: " + str(item.history_reason))
        if item.consensus.value is not None:
            lines.append(
                f"EXPECTATION CAGR horizon: {item.consensus.horizon_years} fiscal years to {item.consensus.target_date}; "
                f"snapshot {item.consensus.snapshot_id} retrieved {item.consensus.fetched_at}. "
                "Compared with constant annual BASE growth, not extrapolated consensus."
            )
            lines.append(f"Relative delta: {number(item.percentage_delta)}")
        else:
            lines.append("Consensus n/a: " + str(item.consensus.reason))
        lines.append(
            "JUDGMENT rationale: "
            + (
                item.rationale.text
                if item.rationale
                else "Not recorded; no rationale is generated."
            )
        )
        if item.material and item.rationale is None:
            lines.append(
                "A material numerical difference exists, but no explicit driver disagreement rationale is recorded."
            )
        sensitivity = item.sensitivity
        lines.append(
            f"CALCULATION perturbation {sensitivity.perturbation:+.4f}: value/share "
            f"{sensitivity.base_value_per_share:.4f} -> {sensitivity.perturbed_value_per_share:.4f}; "
            f"CAGR change {sensitivity.cagr_delta:+.4%}"
        )
    return "\n".join(lines)

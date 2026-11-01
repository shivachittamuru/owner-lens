"""Probability-weighted terminal outcomes and explicit investor-policy comparison."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from owner_lens.persistence import SqliteStore, UnderwritingRecord, compute_content_hash
from owner_lens.underwriting import (
    InvestorPolicy,
    ScenarioName,
    ScenarioProbability,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    parse_investor_policy,
)
from owner_lens.valuation import MODEL_VERSION, ValuationError, value_underwriting
from owner_lens.variant import VariantError, VariantReport, compare_variant

SUMMARY_VERSION = "weighted-terminal-return-v1"


class SummaryError(ValueError):
    """Expected return cannot be computed from incomplete or invalid saved inputs."""


@dataclass(frozen=True)
class ScenarioOutcome:
    name: ScenarioName
    probability: ScenarioProbability
    value_per_share: float
    implied_cagr: float
    terminal_return: float
    weighted_value_contribution: float
    category: SemanticType = SemanticType.CALCULATION


@dataclass(frozen=True)
class UnderwritingSummary:
    underwriting_id: str
    underwriting_version: int
    underwriting_content_hash: str
    ticker: str
    as_of_date: str
    current_price: float
    market_date: str
    valuation_model_version: str
    valuation_content_hash: str
    scenarios: tuple[ScenarioOutcome, ...]
    probability_rationale: str | None
    expected_terminal_value_per_share: float
    expected_5y_cagr: float
    investor_policy: InvestorPolicy
    policy_source: str
    return_spread: float
    classification: str
    classification_reason: str
    loss_probability: float
    gain_probability: float
    weighted_downside: float
    weighted_upside: float
    variant: VariantReport
    model_version: str = SUMMARY_VERSION
    horizon_years: int = 5
    category: SemanticType = SemanticType.CALCULATION

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


def classify_return(spread: float, *, ordered: bool = True) -> tuple[str, str]:
    if not math.isfinite(spread):
        raise SummaryError("Return spread must be finite.")
    if not ordered:
        return (
            "INSUFFICIENT",
            "Scenario terminal values are not ordered BEAR <= BASE <= BULL; review labels.",
        )
    if spread < -0.01 - 1e-12:
        return (
            "UNATTRACTIVE",
            "Expected CAGR is more than 1 percentage point below the explicit hurdle.",
        )
    if spread <= 0.01 + 1e-12:
        return (
            "WATCH",
            "Within +/-1 percentage point of the hurdle; avoid threshold precision.",
        )
    if spread < 0.03 - 1e-12:
        return (
            "INTERESTING",
            "Expected CAGR is more than 1 but less than 3 percentage points above hurdle.",
        )
    return (
        "ATTRACTIVE",
        "Expected CAGR is at least 3 percentage points above hurdle, conditional on manual beliefs.",
    )


def saved_valuation(store: SqliteStore, record: UnderwritingRecord) -> str:
    saved = store.get_valuation(record.underwriting_id, MODEL_VERSION)
    if saved is None:
        raise SummaryError(
            "No saved 8C valuation. Run 'valuation run' for this exact version first."
        )
    # Validate identity, source provenance, assumptions and every intermediate, without overwriting.
    try:
        if json.loads(saved) != json.loads(value_underwriting(record).to_json()):
            raise SummaryError(
                "Saved valuation does not match the exact underwriting hash/version and 8C calculations."
            )
    except (ValueError, TypeError, KeyError) as exc:
        raise SummaryError(f"Invalid saved valuation: {exc}") from exc
    return saved


def summarize_underwriting(
    record: UnderwritingRecord,
    valuation_json: str,
    *,
    required_return: float | None = None,
) -> UnderwritingSummary:
    """Offline calculation from a verified saved valuation, with no probability normalization."""
    try:
        if compute_content_hash(record.snapshot_json.encode()) != record.content_hash:
            raise SummaryError("Underwriting integrity verification failed.")
        snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
        distribution = snapshot.manual.probability_distribution
        if distribution is None:
            raise SummaryError(
                "Missing manually approved scenario probabilities; create a new underwriting version."
            )
        policy = (
            parse_investor_policy(
                {"required_return": required_return, "category": "JUDGMENT"}
            )
            if required_return is not None
            else snapshot.manual.investor_policy
        )
        if policy is None:
            raise SummaryError(
                "Missing explicit required return; supply --required-return or saved investor_policy."
            )
        saved: dict[str, Any] = json.loads(valuation_json)
        if saved != json.loads(value_underwriting(record).to_json()):
            raise SummaryError(
                "Saved valuation differs from exact underwriting/8C outputs."
            )
        price = saved["current_price"]
        probabilities = {item.name: item for item in distribution.scenarios}
        outcomes = tuple(
            ScenarioOutcome(
                ScenarioName(item["assumptions"]["name"]),
                probabilities[ScenarioName(item["assumptions"]["name"])],
                item["year5_value_per_share"],
                item["implied_5y_cagr"],
                item["year5_value_per_share"] / price - 1,
                probabilities[ScenarioName(item["assumptions"]["name"])].probability
                * item["year5_value_per_share"],
            )
            for item in saved["scenarios"]
        )
        expected = math.fsum(item.weighted_value_contribution for item in outcomes)
        cagr = (expected / price) ** 0.2 - 1
        spread = cagr - policy.required_return
        downside = math.fsum(
            item.probability.probability * max(-item.terminal_return, 0)
            for item in outcomes
        )
        upside = math.fsum(
            item.probability.probability * max(item.terminal_return, 0)
            for item in outcomes
        )
        if not all(
            math.isfinite(value) for value in (expected, cagr, spread, downside, upside)
        ):
            raise SummaryError(
                "Expected return calculation exceeds finite numeric range."
            )
        classification, reason = classify_return(
            spread,
            ordered=outcomes[0].value_per_share
            <= outcomes[1].value_per_share
            <= outcomes[2].value_per_share,
        )
        return UnderwritingSummary(
            record.underwriting_id,
            record.version,
            record.content_hash,
            record.ticker,
            record.as_of_date,
            price,
            saved["market_date"],
            saved["model_version"],
            compute_content_hash(valuation_json.encode()),
            outcomes,
            distribution.rationale,
            expected,
            cagr,
            policy,
            "explicit_evaluation"
            if required_return is not None
            else "saved_underwriting",
            spread,
            classification,
            reason,
            math.fsum(
                item.probability.probability
                for item in outcomes
                if item.terminal_return < 0
            ),
            math.fsum(
                item.probability.probability
                for item in outcomes
                if item.terminal_return > 0
            ),
            downside,
            upside,
            compare_variant(record),
        )
    except (
        UnderwritingError,
        ValuationError,
        VariantError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
    ) as exc:
        if isinstance(exc, SummaryError):
            raise
        raise SummaryError(f"Cannot summarize underwriting: {exc}") from exc


def format_summary(summary: UnderwritingSummary) -> str:
    lines = [
        f"{summary.ticker} underwriting v{summary.underwriting_version} | as of {summary.as_of_date}",
        f"Saved price FACT {summary.current_price:.2f} | market date {summary.market_date}",
        "Distribution JUDGMENT rationale: "
        + (summary.probability_rationale or "Not recorded."),
        "Scenario  Probability(JUDGMENT)  Value/share  Implied CAGR  Terminal return",
    ]
    for item in summary.scenarios:
        lines.append(
            f"{item.name:<8} {item.probability.probability:>20.1%} {item.value_per_share:>12.2f}"
            f" {item.implied_cagr:>13.2%} {item.terminal_return:>16.2%}"
        )
    lines.extend(
        [
            f"CALCULATION expected terminal value/share: {summary.expected_terminal_value_per_share:.2f}",
            f"Expected 5Y CAGR: {summary.expected_5y_cagr:.2%}",
            f"Required return JUDGMENT: {summary.investor_policy.required_return:.2%} ({summary.policy_source})",
            f"Spread vs hurdle: {summary.return_spread:+.2%} | {summary.classification}",
            summary.classification_reason,
            f"Loss/gain scenario probability: {summary.loss_probability:.1%} / {summary.gain_probability:.1%}",
            f"Weighted terminal downside/upside: {summary.weighted_downside:.2%} / {summary.weighted_upside:.2%}",
            f"Variant view: {summary.variant.conclusion}",
            "Most locally sensitive BASE drivers (absolute CAGR effect):",
        ]
    )
    for driver in sorted(
        summary.variant.drivers,
        key=lambda item: abs(item.sensitivity.cagr_delta),
        reverse=True,
    ):
        lines.append(
            f"  {driver.driver}: {driver.sensitivity.band}, {driver.sensitivity.cagr_delta:+.2%}"
            f" from perturbation {driver.sensitivity.perturbation:+.4f}"
        )
    lines.append(
        "Conditional underwriting summary, not a buy/sell recommendation or guaranteed alpha."
    )
    return "\n".join(lines)

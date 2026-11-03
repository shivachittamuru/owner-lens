"""Read-only, decision-oriented projection for the Company underwriting view."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from owner_lens.persistence import SqliteStore
from owner_lens.underwriting_contract import (
    UnderwritingProjection,
    project_underwriting,
)
from owner_lens.underwriting_summary import UnderwritingSummary
from owner_lens.variant import VariantReport


@dataclass(frozen=True)
class ScenarioView:
    name: str
    probability: float | None
    narrative: str
    revenue_cagr: float
    fcf_margin_year5: float
    share_count_cagr: float
    terminal_fcf_multiple: float
    value_per_share: float | None
    implied_cagr: float | None


@dataclass(frozen=True)
class EvidenceView:
    category: str
    text: str
    evidence_date: str | None
    references: tuple[str, ...]


@dataclass(frozen=True)
class DriverView:
    name: str
    direction: str
    assumption: float
    consensus: float | None
    rationale: str | None
    cagr_delta: float
    sensitivity_band: str
    perturbation: float


@dataclass(frozen=True)
class HistoricalMetricView:
    name: str
    fiscal_year: int | None
    value: float | None
    unit: str


@dataclass(frozen=True)
class ChallengerView:
    created_at: str
    assessment: str | None
    strongest_argument_against: str | None
    unresolved_questions: tuple[str, ...]


@dataclass(frozen=True)
class UnderwritingInvestmentView:
    ticker: str
    version: int
    as_of_date: str
    provider: str | None
    frozen_priority: str | None
    frozen_setup: str | None
    frozen_coverage: str | None
    current_price: float | None
    market_date: str | None
    required_return: float | None
    expected_cagr: float | None
    return_spread: float | None
    classification: str | None
    classification_reason: str | None
    scenarios: tuple[ScenarioView, ...]
    key_takeaway: str
    biggest_uncertainty: str
    most_important_variable: str
    dependencies: tuple[str, ...]
    breakers: tuple[str, ...]
    business_drivers: tuple[EvidenceView, ...]
    supporting_evidence: tuple[EvidenceView, ...]
    disconfirming_evidence: tuple[EvidenceView, ...]
    historical_metrics: tuple[HistoricalMetricView, ...]
    probability_rationale: str | None
    variant_conclusion: str | None
    variant_drivers: tuple[DriverView, ...]
    most_sensitive_driver: DriverView | None
    challenger: ChallengerView | None
    missing: tuple[tuple[str, str], ...]
    record_id: str
    content_hash: str
    snapshot_json: str


def is_analysis_complete(projection: UnderwritingProjection) -> bool:
    return bool(
        projection.record
        and projection.valuation_json
        and projection.summary
        and projection.variant
        and projection.challenger_runs
    )


def select_investment_projection(
    store: SqliteStore, ticker: str
) -> tuple[UnderwritingProjection, UnderwritingProjection | None]:
    """Prefer the newest completed view, retaining a newer partial version for retry."""
    latest = project_underwriting(store, ticker)
    if latest.record is None or is_analysis_complete(latest):
        return latest, None

    records = store.list_underwriting(ticker.strip().upper())
    for record in reversed(records):
        if record.version >= latest.record.version:
            continue
        candidate = project_underwriting(store, ticker, version=record.version)
        if is_analysis_complete(candidate):
            return candidate, latest
    return latest, None


def _evidence(items: tuple[Any, ...]) -> tuple[EvidenceView, ...]:
    return tuple(
        EvidenceView(
            item.category.value,
            item.text,
            item.evidence_date,
            tuple(
                " | ".join(
                    part for part in (reference.title, reference.uri, reference.observed_at)
                    if part
                )
                for reference in item.references
            ),
        )
        for item in items
    )


def _drivers(report: VariantReport | None) -> tuple[DriverView, ...]:
    if report is None:
        return ()
    return tuple(
        DriverView(
            driver.driver,
            driver.direction,
            driver.assumption,
            driver.consensus.value,
            driver.rationale.text if driver.rationale else None,
            driver.sensitivity.cagr_delta,
            driver.sensitivity.band,
            driver.sensitivity.perturbation,
        )
        for driver in report.drivers
    )


def _challenger(projection: UnderwritingProjection) -> ChallengerView | None:
    if not projection.challenger_runs:
        return None
    run = projection.challenger_runs[-1]
    output = json.loads(run.output_json)
    questions = output.get("questions_to_resolve", [])
    return ChallengerView(
        run.created_at,
        _finding_text(output.get("overall_assessment")),
        _finding_text(output.get("strongest_argument_against")),
        tuple(text for item in questions if (text := _finding_text(item))),
    )


def _finding_text(value: Any) -> str | None:
    if isinstance(value, dict):
        text = value.get("text")
        return text if isinstance(text, str) else None
    if isinstance(value, str):
        return value
    return None


def _takeaway(summary: UnderwritingSummary | None) -> str:
    if summary is None:
        return "Expected-return assessment is unavailable for this version."
    if summary.classification == "INSUFFICIENT":
        return (
            "Expected-return assessment is insufficient: "
            + summary.classification_reason
        )
    return (
        f"Expected CAGR is {summary.expected_5y_cagr:.1%}; "
        f"{summary.classification.lower()} versus the "
        f"{summary.investor_policy.required_return:.1%} required return "
        f"({summary.return_spread:+.1%})."
    )


def build_investment_view(
    projection: UnderwritingProjection,
) -> UnderwritingInvestmentView:
    """Project saved underwriting inputs and outputs without running analysis."""
    record, snapshot = projection.record, projection.snapshot
    if record is None or snapshot is None:
        raise ValueError("An immutable underwriting snapshot is required.")

    manual = snapshot.manual
    evidence = json.loads(snapshot.evidence_json)
    feature7 = evidence.get("feature7_context") or {}
    price = evidence.get("eod_price", {}).get("value")
    summary = projection.summary
    saved_valuation = (
        json.loads(projection.valuation_json) if projection.valuation_json else {}
    )
    saved_scenarios = {
        row["assumptions"]["name"]: row
        for row in saved_valuation.get("scenarios", [])
    }
    probabilities = (
        {item.name: item.probability for item in manual.probability_distribution.scenarios}
        if manual.probability_distribution
        else {}
    )
    scenarios = tuple(
        ScenarioView(
            scenario.name.value,
            probabilities.get(scenario.name),
            scenario.narrative,
            scenario.revenue_cagr,
            scenario.fcf_margin_year5,
            scenario.share_count_cagr,
            scenario.terminal_fcf_multiple,
            saved_scenarios.get(scenario.name.value, {}).get("year5_value_per_share"),
            saved_scenarios.get(scenario.name.value, {}).get("implied_5y_cagr"),
        )
        for scenario in manual.scenarios
    )
    variant_drivers = _drivers(projection.variant)
    most_sensitive = (
        max(variant_drivers, key=lambda item: abs(item.cagr_delta))
        if variant_drivers
        else None
    )
    historical = tuple(
        HistoricalMetricView(
            item.name,
            next(
                (
                    observation.fiscal_year
                    for observation in reversed(item.observations)
                    if observation.value == item.latest
                ),
                None,
            ),
            item.latest,
            item.unit,
        )
        for item in snapshot.historical_base_rates
        if item.latest is not None
    )
    dependencies = tuple(
        item.statement for item in manual.thesis.monitoring_dependencies
    ) or manual.thesis.dependencies
    breakers = tuple(
        item.statement for item in manual.thesis.monitoring_breakers
    ) or manual.thesis.breakers
    price_value = price.get("close") if isinstance(price, dict) else None

    return UnderwritingInvestmentView(
        record.ticker,
        record.version,
        record.as_of_date,
        evidence.get("provider"),
        feature7.get("priority"),
        feature7.get("setup_type"),
        feature7.get("coverage"),
        price_value,
        price.get("market_date") if isinstance(price, dict) else None,
        summary.investor_policy.required_return
        if summary
        else manual.investor_policy.required_return
        if manual.investor_policy
        else None,
        summary.expected_5y_cagr if summary else None,
        summary.return_spread if summary else None,
        summary.classification if summary else None,
        summary.classification_reason if summary else None,
        scenarios,
        _takeaway(summary),
        manual.thesis.biggest_uncertainty,
        manual.thesis.most_important_variable,
        dependencies,
        breakers,
        _evidence(manual.business_drivers),
        _evidence(manual.supporting_evidence),
        _evidence(manual.disconfirming_evidence),
        historical,
        manual.probability_distribution.rationale
        if manual.probability_distribution
        else None,
        projection.variant.conclusion if projection.variant else None,
        variant_drivers,
        most_sensitive,
        _challenger(projection),
        tuple((item.section, item.reason) for item in projection.missing_evidence),
        record.underwriting_id,
        record.content_hash,
        record.snapshot_json,
    )

"""Human drafts and contextual hints over the same immutable v2 domain contract."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from owner_lens.compounding import cagr
from owner_lens.underwriting import (
    PROBABILITY_TOLERANCE,
    ManualUnderwriting,
    ScenarioName,
    UnderwritingError,
    UnderwritingInputs,
    UnderwritingSnapshot,
    condition_data,
)
from owner_lens.underwriting_contract import parse_authoring_input
from owner_lens.variant import DRIVERS, Consensus, revenue_consensus


def empty_authoring() -> dict[str, Any]:
    """Technical shape only: no suggested beliefs, probabilities or policy."""
    return {
        "authoring_version": 2,
        "assumptions": {
            "category": "ASSUMPTION",
            "scenarios": [
                {"name": name.value, "category": "ASSUMPTION", "narrative": "",
                 **dict.fromkeys(DRIVERS), "horizon_years": 5, "key_dependency": None}
                for name in ScenarioName
            ],
        },
        "judgments": {
            "category": "JUDGMENT",
            "business_drivers": [{"category": "JUDGMENT", "text": ""} for _ in range(3)],
            "supporting_evidence": [], "disconfirming_evidence": [],
            "variant_rationales": [],
            "probability_distribution": {
                "category": "JUDGMENT", "rationale": None,
                "scenarios": [{"name": name.value, "category": "JUDGMENT", "probability": None}
                              for name in ScenarioName],
            },
            "investor_policy": {"category": "JUDGMENT", "required_return": None, "rationale": None},
            "thesis": {
                "category": "JUDGMENT", "dependencies": [], "breakers": [],
                "biggest_uncertainty": "", "most_important_variable": "",
                "next_evidence_to_collect": [],
            },
        },
    }


def authoring_from_manual(manual: ManualUnderwriting) -> dict[str, Any]:
    """Copy beliefs only; never copy FACT/EXPECTATION/CALCULATION or alter a version."""
    data = asdict(manual)
    thesis = data["thesis"]
    for field in ("dependencies", "breakers"):
        structured = thesis.pop("monitoring_" + field)
        conditions = getattr(manual.thesis, "monitoring_" + field)
        thesis[field] = [condition_data(item) for item in conditions] if structured else [
            {"condition_id": f"{field}-{index + 1}", "category": "JUDGMENT", "statement": text}
            for index, text in enumerate(thesis[field])
        ]
    blank = empty_authoring()
    judgments = blank["judgments"]
    for key in judgments:
        if key != "category" and data.get(key) is not None:
            judgments[key] = data[key]
    if manual.scenarios:
        blank["assumptions"]["scenarios"] = data["scenarios"]
    # JSON makes an independent, serializable draft and normalizes tuples/enums.
    return json.loads(json.dumps(blank))


@dataclass(frozen=True)
class DriverContext:
    driver: str
    latest: float | None
    minimum: float | None
    maximum: float | None
    historical_cagr: float | None = None
    start_year: int | None = None
    end_year: int | None = None
    consensus: Consensus | None = None
    range_basis: str = "Annual observations, not a forecast distribution."

    def presets(self) -> dict[str, float]:
        choices: dict[str, float] = {}
        if self.latest is not None:
            choices["Historical latest"] = self.latest
        if self.historical_cagr is not None:
            choices["Historical 3-5Y"] = self.historical_cagr
        if self.consensus and self.consensus.value is not None:
            choices["Consensus"] = self.consensus.value
        return choices


def authoring_context(inputs: UnderwritingInputs) -> tuple[DriverContext, ...]:
    """Shared historical CAGR helper and existing 8D consensus, no valuation execution."""
    evidence = json.loads(inputs.evidence_json)
    consensus = revenue_consensus(
        inputs, created_at=inputs.captured_at, as_of_date=inputs.as_of_date
    )
    contexts = []
    mapping = {"revenue_cagr": "revenue_growth", "fcf_margin_year5": "fcf_margin",
               "share_count_cagr": "share_count_change"}
    for driver in DRIVERS:
        rate = next((item for item in inputs.historical_base_rates if item.name == mapping.get(driver)), None)
        aggregate, start, end = None, None, None
        metric = {"revenue_cagr": "revenue", "share_count_cagr": "diluted_shares"}.get(driver)
        if metric:
            points = {item["fiscal_year"]: item["value"] for item in evidence["canonical_history"]["facts"]
                      if item["metric"] == metric and item["value"] is not None}
            end = inputs.latest_fiscal_year
            candidates = [year for year in points if 3 <= end - year <= 5]
            if end in points and candidates:
                start = min(candidates)
                aggregate = cagr(points[start], points[end], end - start)
        latest = rate.latest if rate else None
        if driver == "fcf_margin_year5":
            latest = next((item.value for item in inputs.starting_financial_state if item.name == "fcf_margin"), None)
        contexts.append(DriverContext(
            driver, latest, rate.minimum if rate else None, rate.maximum if rate else None,
            aggregate, start, end, consensus if driver == "revenue_cagr" else None,
        ))
    return tuple(contexts)


def probability_feedback(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    values = [item["probability"] for item in payload["judgments"]["probability_distribution"]["scenarios"]]
    if any(value is None for value in values):
        return None, "Enter all three probabilities; none is assumed."
    total = math.fsum(values)
    if any(not 0 <= value <= 1 for value in values) or abs(total - 1) > PROBABILITY_TOLERANCE:
        return total, f"Probabilities sum to {total:.1%}, not 100%; no normalization."
    return total, None


def draft_hints(payload: dict[str, Any], contexts: tuple[DriverContext, ...]) -> tuple[str, ...]:
    hints = []
    _, error = probability_feedback(payload)
    if error:
        hints.append(error)
    judgment = payload["judgments"]
    for field, label in (("supporting_evidence", "supporting"), ("disconfirming_evidence", "disconfirming")):
        if not judgment[field]:
            hints.append(f"No {label} evidence recorded.")
    rationales = {item["driver"] for item in judgment["variant_rationales"]}
    for context in contexts:
        if context.driver not in rationales:
            hints.append(f"No variant rationale recorded for {context.driver}.")
        for scenario in payload["assumptions"]["scenarios"]:
            value = scenario.get(context.driver)
            if value is None:
                continue
            if context.minimum is not None and context.maximum is not None and not context.minimum <= value <= context.maximum:
                hints.append(f"{scenario['name']} {context.driver} is outside the observed annual historical range (not a CAGR probability range).")
            if scenario["name"] == "BASE" and context.consensus and context.consensus.value is not None:
                delta = (value - context.consensus.value) * 100
                hints.append(f"BASE {context.driver} is {abs(delta):.2f}pp {'above' if delta >= 0 else 'below'} captured consensus over its {context.consensus.horizon_years}Y horizon, not necessarily 5Y.")
    return tuple(hints)


def review_authoring(payload: dict[str, Any], inputs: UnderwritingInputs) -> UnderwritingSnapshot:
    """The canonical parser plus evidence-to-belief/date validation, before persistence."""
    manual = parse_authoring_input(payload)
    if any(not scenario.key_dependency for scenario in manual.scenarios):
        raise UnderwritingError("Each authored scenario needs an explicit key dependency.")
    return inputs.snapshot(manual)

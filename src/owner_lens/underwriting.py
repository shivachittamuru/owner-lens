"""Manual, semantically typed, self-contained underwriting belief snapshots."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any

from owner_lens.canonical import CanonicalDataError, CanonicalFinancialHistory
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.persistence.records import (
    DEFAULT_CALCULATION_VERSION,
    UnderwritingRecord,
)
from owner_lens.persistence.store import SqliteStore
from owner_lens.screening import screen_company_from_history
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchSource,
    load_canonical_history,
)


class UnderwritingError(ValueError):
    """Invalid manual input or unavailable point-in-time evidence."""


class SemanticType(StrEnum):
    FACT = "FACT"
    EXPECTATION = "EXPECTATION"
    ASSUMPTION = "ASSUMPTION"
    JUDGMENT = "JUDGMENT"
    CALCULATION = "CALCULATION"


Scalar = str | int | float | None


@dataclass(frozen=True)
class Reference:
    """User-provided source metadata, never interpreted as verified evidence."""

    title: str | None = None
    uri: str | None = None
    observed_at: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Statement:
    category: SemanticType
    text: str
    references: tuple[Reference, ...] = ()
    evidence_id: str | None = None
    evidence_date: str | None = None
    belief_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThesisCondition:
    condition_id: str
    statement: str
    observable: str | None = None
    threshold: str | None = None
    sources: tuple[Reference, ...] = ()
    monitoring_cadence: str | None = None
    monitoring_date: str | None = None
    category: SemanticType = SemanticType.JUDGMENT


@dataclass(frozen=True)
class Assumption:
    name: str
    value: Scalar
    rationale: str
    category: SemanticType = SemanticType.ASSUMPTION
    unit: str | None = None
    confidence: str | None = None
    references: tuple[Reference, ...] = ()


@dataclass(frozen=True)
class Thesis:
    dependencies: tuple[str, ...]
    breakers: tuple[str, ...]
    biggest_uncertainty: str
    most_important_variable: str
    next_evidence_to_collect: tuple[str, ...]
    category: SemanticType = SemanticType.JUDGMENT
    monitoring_dependencies: tuple[ThesisCondition, ...] = ()
    monitoring_breakers: tuple[ThesisCondition, ...] = ()


class ScenarioName(StrEnum):
    BEAR = "BEAR"
    BASE = "BASE"
    BULL = "BULL"


@dataclass(frozen=True)
class ScenarioAssumption:
    name: ScenarioName
    narrative: str
    revenue_cagr: float
    fcf_margin_year5: float
    share_count_cagr: float
    terminal_fcf_multiple: float
    horizon_years: int
    key_dependency: str | None = None
    category: SemanticType = SemanticType.ASSUMPTION


@dataclass(frozen=True)
class DriverRationale:
    driver: str
    text: str
    category: SemanticType = SemanticType.JUDGMENT
    references: tuple[Reference, ...] = ()


@dataclass(frozen=True)
class ScenarioProbability:
    name: ScenarioName
    probability: float
    category: SemanticType = SemanticType.JUDGMENT


@dataclass(frozen=True)
class ProbabilityDistribution:
    scenarios: tuple[ScenarioProbability, ...]
    rationale: str | None = None
    category: SemanticType = SemanticType.JUDGMENT


@dataclass(frozen=True)
class InvestorPolicy:
    required_return: float
    rationale: str | None = None
    category: SemanticType = SemanticType.JUDGMENT


@dataclass(frozen=True)
class ManualUnderwriting:
    as_of_date: str | None
    business_drivers: tuple[Statement, ...]
    forward_assumptions: tuple[Assumption, ...]
    supporting_evidence: tuple[Statement, ...]
    disconfirming_evidence: tuple[Statement, ...]
    thesis: Thesis
    decision: Statement | None = None
    scenarios: tuple[ScenarioAssumption, ...] = ()
    variant_rationales: tuple[DriverRationale, ...] = ()
    probability_distribution: ProbabilityDistribution | None = None
    investor_policy: InvestorPolicy | None = None
    contract_version: int = 1


@dataclass(frozen=True)
class FinancialState:
    name: str
    value: int | float | None
    unit: str
    fiscal_year: int
    # Derived historical starting values are FACT as requested, not forecasts.
    category: SemanticType = SemanticType.FACT
    basis: SemanticType = SemanticType.FACT
    calculation: str | None = None
    missing_reason: str | None = None


@dataclass(frozen=True)
class HistoricalObservation:
    fiscal_year: int
    value: float | None


@dataclass(frozen=True)
class BaseRate:
    name: str
    observations: tuple[HistoricalObservation, ...]
    minimum: float | None
    maximum: float | None
    latest: float | None
    calculation: str
    category: SemanticType = SemanticType.CALCULATION
    unit: str = "ratio"
    missing_reason: str | None = None


@dataclass(frozen=True)
class UnderwritingSnapshot:
    """Frozen domain sections; copied JSON evidence is immutable, not a live link."""

    manual: ManualUnderwriting
    starting_financial_state: tuple[FinancialState, ...]
    historical_base_rates: tuple[BaseRate, ...]
    evidence_json: str
    latest_fiscal_year: int
    calculation_version: str = DEFAULT_CALCULATION_VERSION
    schema_version: int = 1

    def to_json(self) -> str:
        data = asdict(self)
        if self.manual.contract_version == 1:
            data["manual"].pop("contract_version")
        for field in ("business_drivers", "supporting_evidence", "disconfirming_evidence"):
            for item in data["manual"][field]:
                _omit_statement_metadata(item)
        if data["manual"]["decision"] is not None:
            _omit_statement_metadata(data["manual"]["decision"])
        for field in ("monitoring_dependencies", "monitoring_breakers"):
            if not data["manual"]["thesis"][field]:
                data["manual"]["thesis"].pop(field)
        if not self.manual.scenarios:
            data["manual"].pop("scenarios")
        if not self.manual.variant_rationales:
            data["manual"].pop("variant_rationales")
        for field in ("probability_distribution", "investor_policy"):
            if getattr(self.manual, field) is None:
                data["manual"].pop(field)
        data["evidence"] = json.loads(data.pop("evidence_json"))
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, payload: str) -> UnderwritingSnapshot:
        data = json.loads(payload)
        if data["schema_version"] not in (1, 2):
            raise UnderwritingError("Unsupported underwriting snapshot schema.")
        manual_data = data["manual"]
        manual = parse_manual_input(manual_data)
        if manual.contract_version != data["schema_version"]:
            raise UnderwritingError("Snapshot and authoring contract versions do not match.")
        starting = tuple(
            FinancialState(
                **{
                    **item,
                    "category": SemanticType(item["category"]),
                    "basis": SemanticType(item["basis"]),
                }
            )
            for item in data["starting_financial_state"]
        )
        rates = tuple(
            BaseRate(
                **{
                    **item,
                    "category": SemanticType(item["category"]),
                    "observations": tuple(
                        HistoricalObservation(**obs) for obs in item["observations"]
                    ),
                }
            )
            for item in data["historical_base_rates"]
        )
        return cls(
            manual,
            starting,
            rates,
            json.dumps(data["evidence"], sort_keys=True, allow_nan=False),
            data["latest_fiscal_year"],
            data["calculation_version"],
            data["schema_version"],
        )


def _omit_statement_metadata(item: dict[str, Any]) -> None:
    for field in ("evidence_id", "evidence_date", "belief_references"):
        if not item[field]:
            item.pop(field)


def _optional_date(value: Any, label: str) -> str | None:
    text = _optional_text(value, label)
    if text is not None:
        try:
            if date.fromisoformat(text).isoformat() != text:
                raise ValueError
        except ValueError as exc:
            raise UnderwritingError(f"{label} must be YYYY-MM-DD.") from exc
    return text


def _object(
    value: Any, name: str, allowed: set[str], required: set[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnderwritingError(f"{name} must be an object.")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown or missing:
        raise UnderwritingError(
            f"{name}: unknown fields {sorted(unknown)}; missing fields {sorted(missing)}."
        )
    return value


def load_manual_json(payload: str) -> ManualUnderwriting:
    """Do not let JSON's duplicate-key behavior silently replace a manual belief."""

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UnderwritingError(f"Duplicate JSON field: {key}.")
            result[key] = value
        return result

    return parse_manual_input(json.loads(payload, object_pairs_hook=unique_keys))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnderwritingError(f"{name} must be non-empty text.")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise UnderwritingError(f"{name} must be a list.")
    return list(value)


def _references(value: Any) -> tuple[Reference, ...]:
    return tuple(
        Reference(
            **{
                key: _optional_text(item.get(key), f"reference.{key}")
                for key in ("title", "uri", "observed_at", "note")
            }
        )
        for item in (
            _object(raw, "reference", {"title", "uri", "observed_at", "note"}, set())
            for raw in _list(value, "references")
        )
    )


def _statement(
    value: Any, name: str, category: SemanticType | None = None
) -> Statement:
    item = _object(
        value, name, {"category", "text", "references", "evidence_id", "evidence_date", "belief_references"},
        {"category", "text"}
    )
    try:
        kind = SemanticType(item["category"])
    except (ValueError, TypeError) as exc:
        raise UnderwritingError(
            f"{name} must use one of the five semantic categories."
        ) from exc
    if category is not None and kind is not category:
        raise UnderwritingError(f"{name} must be {category}, not {kind}.")
    return Statement(
        kind, _text(item["text"], name), _references(item.get("references", [])),
        _optional_text(item.get("evidence_id"), "evidence_id"),
        _optional_date(item.get("evidence_date"), "evidence_date"),
        tuple(_text(raw, "belief reference") for raw in _list(item.get("belief_references", []), "belief_references")),
    )


_ASSUMPTIONS = {
    "revenue_growth_5y",
    "operating_margin_year5",
    "fcf_margin_year5",
    "annual_share_count_change",
    "terminal_assumption",
    "tax_rate",
    "discount_rate",
}


def parse_manual_input(data: Any) -> ManualUnderwriting:
    """Reject category substitution and unknown fields; never accept starting-fact overrides."""
    if isinstance(data, dict) and "authoring_version" in data:
        from owner_lens.underwriting_contract import parse_authoring_input

        return parse_authoring_input(data)
    fields = {
        "as_of_date",
        "business_drivers",
        "forward_assumptions",
        "supporting_evidence",
        "disconfirming_evidence",
        "thesis",
        "decision",
        "scenarios",
        "variant_rationales",
        "probability_distribution",
        "investor_policy",
        "contract_version",
    }
    root = _object(
        data,
        "underwriting input",
        fields,
        {"business_drivers", "forward_assumptions", "thesis"},
    )
    contract_version = root.get("contract_version", 1)
    if type(contract_version) is not int or contract_version not in (1, 2):
        raise UnderwritingError("Unsupported underwriting contract version.")
    as_of = _optional_text(root.get("as_of_date"), "as_of_date")
    if as_of is not None:
        try:
            if date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError
        except ValueError as exc:
            raise UnderwritingError("as_of_date must be YYYY-MM-DD.") from exc
    drivers = tuple(
        _statement(item, "business driver", SemanticType.JUDGMENT)
        for item in _list(root["business_drivers"], "business_drivers")
    )
    if not 3 <= len(drivers) <= 5:
        raise UnderwritingError("Supply 3 to 5 manual business drivers.")
    assumptions: list[Assumption] = []
    for raw in _list(root["forward_assumptions"], "forward_assumptions"):
        item = _object(
            raw,
            "assumption",
            {
                "name",
                "category",
                "value",
                "rationale",
                "confidence",
                "unit",
                "references",
            },
            {"name", "category", "value", "rationale"},
        )
        if item["category"] != SemanticType.ASSUMPTION:
            raise UnderwritingError("Forward inputs must be ASSUMPTION.")
        name = _text(item["name"], "assumption.name")
        if name not in _ASSUMPTIONS or any(
            existing.name == name for existing in assumptions
        ):
            raise UnderwritingError(f"Unsupported or duplicate assumption: {name}.")
        value = item["value"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (str, int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise UnderwritingError(
                f"{name} requires a finite number or text, not null/bool/container."
            )
        if name == "terminal_assumption":
            _text(value, name)
        elif not isinstance(value, (int, float)) or item.get("unit") != "ratio":
            raise UnderwritingError(
                f"{name} requires a numeric ratio and unit='ratio' (0.05 = 5%)."
            )
        assumptions.append(
            Assumption(
                name,
                value,
                _text(item["rationale"], "rationale"),
                unit=_optional_text(item.get("unit"), "unit"),
                confidence=_optional_text(item.get("confidence"), "confidence"),
                references=_references(item.get("references", [])),
            )
        )
    scenario_inputs = _list(root.get("scenarios", []), "scenarios")
    scenarios = parse_scenarios(scenario_inputs) if scenario_inputs else ()
    if root.get("probability_distribution") is not None and not scenarios:
        raise UnderwritingError("Probabilities require complete BEAR, BASE and BULL scenario assumptions.")
    if not assumptions and not scenarios:
        raise UnderwritingError("Supply at least one explicit forward assumption.")
    thesis_fields = {
        "dependencies",
        "breakers",
        "biggest_uncertainty",
        "most_important_variable",
        "next_evidence_to_collect",
    }
    thesis_data = _object(
        root["thesis"], "thesis", thesis_fields | {"category", "monitoring_dependencies", "monitoring_breakers"}, thesis_fields
    )
    if thesis_data.get("category", SemanticType.JUDGMENT) != SemanticType.JUDGMENT:
        raise UnderwritingError("Thesis must be JUDGMENT.")
    lists = {
        key: tuple(_text(item, key) for item in _list(thesis_data[key], key))
        for key in ("dependencies", "breakers", "next_evidence_to_collect")
    }
    if any(not values for values in lists.values()):
        raise UnderwritingError(
            "Thesis dependencies, breakers, and next evidence must be non-empty."
        )
    thesis = Thesis(
        dependencies=lists["dependencies"],
        breakers=lists["breakers"],
        next_evidence_to_collect=lists["next_evidence_to_collect"],
        biggest_uncertainty=_text(
            thesis_data["biggest_uncertainty"], "biggest_uncertainty"
        ),
        most_important_variable=_text(
            thesis_data["most_important_variable"], "most_important_variable"
        ),
        monitoring_dependencies=_conditions(thesis_data.get("monitoring_dependencies", [])),
        monitoring_breakers=_conditions(thesis_data.get("monitoring_breakers", [])),
    )
    rationales: list[DriverRationale] = []
    for raw in _list(root.get("variant_rationales", []), "variant_rationales"):
        item = _object(
            raw, "variant rationale", {"driver", "text", "category", "references"},
            {"driver", "text", "category"},
        )
        driver = _text(item["driver"], "driver")
        if driver not in {
            "revenue_cagr", "fcf_margin_year5", "share_count_cagr", "terminal_fcf_multiple",
        }:
            raise UnderwritingError(f"Unknown variant driver: {driver}.")
        if any(existing.driver == driver for existing in rationales):
            raise UnderwritingError(f"Duplicate variant rationale: {driver}.")
        statement = _statement(
            {key: value for key, value in item.items() if key != "driver"},
            "variant rationale", SemanticType.JUDGMENT,
        )
        rationales.append(DriverRationale(driver, statement.text, references=statement.references))
    manual = ManualUnderwriting(
        as_of,
        drivers,
        tuple(assumptions),
        tuple(
            _statement(item, "supporting evidence")
            for item in _list(
                root.get("supporting_evidence", []), "supporting_evidence"
            )
        ),
        tuple(
            _statement(item, "disconfirming evidence")
            for item in _list(
                root.get("disconfirming_evidence", []), "disconfirming_evidence"
            )
        ),
        thesis,
        _statement(root["decision"], "decision", SemanticType.JUDGMENT)
        if root.get("decision") is not None
        else None,
        scenarios,
        tuple(rationales),
        parse_probabilities(root["probability_distribution"])
        if root.get("probability_distribution") is not None else None,
        parse_investor_policy(root["investor_policy"])
        if root.get("investor_policy") is not None else None,
        contract_version,
    )
    if contract_version == 2:
        if (manual.forward_assumptions or not manual.scenarios
                or manual.probability_distribution is None
                or not manual.probability_distribution.rationale
                or manual.investor_policy is None):
            raise UnderwritingError("Contract v2 requires complete scenarios, probability rationale and investor policy, without duplicated forward assumptions.")
        if (manual.thesis.dependencies != tuple(item.statement for item in manual.thesis.monitoring_dependencies)
                or manual.thesis.breakers != tuple(item.statement for item in manual.thesis.monitoring_breakers)):
            raise UnderwritingError("Contract v2 thesis text must match structured conditions.")
    return manual


def _conditions(data: Any) -> tuple[ThesisCondition, ...]:
    result: list[ThesisCondition] = []
    for raw in _list(data, "thesis conditions"):
        item = _object(raw, "thesis condition",
                       {"condition_id", "statement", "observable", "threshold", "sources",
                        "monitoring_cadence", "monitoring_date", "category"},
                       {"condition_id", "statement", "category"})
        if item["category"] != SemanticType.JUDGMENT:
            raise UnderwritingError("Thesis conditions must be JUDGMENT.")
        identifier = _text(item["condition_id"], "condition_id")
        if any(existing.condition_id == identifier for existing in result):
            raise UnderwritingError("Duplicate thesis condition id.")
        result.append(ThesisCondition(
            identifier, _text(item["statement"], "condition statement"),
            _optional_text(item.get("observable"), "observable"),
            _optional_text(item.get("threshold"), "threshold"),
            _references(item.get("sources", [])),
            _optional_text(item.get("monitoring_cadence"), "monitoring_cadence"),
            _optional_date(item.get("monitoring_date"), "monitoring_date"),
        ))
    return tuple(result)


PROBABILITY_TOLERANCE = 1e-9


def _policy_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnderwritingError(f"{label} must be a finite number.")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise UnderwritingError(f"{label} is outside numeric range.") from exc
    if not math.isfinite(numeric):
        raise UnderwritingError(f"{label} must be finite.")
    return numeric


def parse_probabilities(data: Any) -> ProbabilityDistribution:
    root = _object(data, "probability distribution", {"scenarios", "rationale", "category"},
                   {"scenarios", "category"})
    if root["category"] != SemanticType.JUDGMENT:
        raise UnderwritingError("Probability distribution must be JUDGMENT.")
    probabilities: dict[ScenarioName, ScenarioProbability] = {}
    for raw in _list(root["scenarios"], "probability scenarios"):
        item = _object(raw, "scenario probability", {"name", "probability", "category"},
                       {"name", "probability", "category"})
        try:
            name = ScenarioName(item["name"])
        except (ValueError, TypeError) as exc:
            raise UnderwritingError("Probability name must be BEAR, BASE, or BULL.") from exc
        if name in probabilities:
            raise UnderwritingError(f"Duplicate scenario probability: {name}.")
        if item["category"] != SemanticType.JUDGMENT:
            raise UnderwritingError("Scenario probabilities must be JUDGMENT.")
        value = _policy_number(item["probability"], str(name))
        if not 0 <= value <= 1:
            raise UnderwritingError("Scenario probabilities must be between 0 and 1.")
        probabilities[name] = ScenarioProbability(name, value)
    if set(probabilities) != set(ScenarioName):
        raise UnderwritingError("Supply BEAR, BASE and BULL probabilities; none may be missing.")
    if abs(math.fsum(item.probability for item in probabilities.values()) - 1) > PROBABILITY_TOLERANCE:
        raise UnderwritingError("Scenario probabilities must sum to 1 within 1e-9; no normalization.")
    return ProbabilityDistribution(
        tuple(probabilities[name] for name in ScenarioName),
        _optional_text(root.get("rationale"), "probability rationale"),
    )


def parse_investor_policy(data: Any) -> InvestorPolicy:
    item = _object(data, "investor policy", {"required_return", "rationale", "category"},
                   {"required_return", "category"})
    if item["category"] != SemanticType.JUDGMENT:
        raise UnderwritingError("Investor policy must be JUDGMENT.")
    hurdle = _policy_number(item["required_return"], "required_return")
    if hurdle <= -1:
        raise UnderwritingError("Required return must exceed -1.")
    return InvestorPolicy(hurdle, _optional_text(item.get("rationale"), "policy rationale"))


def parse_scenarios(data: Any) -> tuple[ScenarioAssumption, ...]:
    """One strict five-year contract shared by input parsing and valuation."""
    scenarios: dict[ScenarioName, ScenarioAssumption] = {}
    fields = {"name", "narrative", "revenue_cagr", "fcf_margin_year5",
              "share_count_cagr", "terminal_fcf_multiple", "horizon_years",
              "key_dependency", "category"}
    for raw in _list(data, "scenarios"):
        item = _object(raw, "scenario", fields, fields - {"key_dependency"})
        try:
            name = ScenarioName(item["name"])
        except (ValueError, TypeError) as exc:
            raise UnderwritingError("Scenario name must be BEAR, BASE, or BULL.") from exc
        if name in scenarios:
            raise UnderwritingError(f"Duplicate scenario: {name}.")
        if item["category"] != SemanticType.ASSUMPTION:
            raise UnderwritingError("Scenarios must be ASSUMPTION.")
        horizon = item["horizon_years"]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon != 5:
            raise UnderwritingError("Each scenario requires horizon_years=5.")
        numeric: dict[str, float] = {}
        for key in ("revenue_cagr", "fcf_margin_year5", "share_count_cagr", "terminal_fcf_multiple"):
            value = item[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UnderwritingError(f"{name}.{key} must be a finite number.")
            try:
                number = float(value)
            except OverflowError as exc:
                raise UnderwritingError(f"{name}.{key} is outside numeric range.") from exc
            if not math.isfinite(number):
                raise UnderwritingError(f"{name}.{key} must be finite.")
            numeric[key] = number
        if numeric["revenue_cagr"] <= -1 or numeric["share_count_cagr"] <= -1:
            raise UnderwritingError("Revenue/share-count CAGR must be greater than -1 (decimal ratios).")
        if not 0 <= numeric["fcf_margin_year5"] <= 1:
            raise UnderwritingError("Year-5 FCF margin must be between 0 and 1.")
        if numeric["terminal_fcf_multiple"] <= 0:
            raise UnderwritingError("Terminal equity FCF multiple must be positive.")
        scenarios[name] = ScenarioAssumption(
            name=name, narrative=_text(item["narrative"], "scenario.narrative"),
            horizon_years=horizon,
            revenue_cagr=numeric["revenue_cagr"],
            fcf_margin_year5=numeric["fcf_margin_year5"],
            share_count_cagr=numeric["share_count_cagr"],
            terminal_fcf_multiple=numeric["terminal_fcf_multiple"],
            key_dependency=_optional_text(item.get("key_dependency"), "key_dependency"),
        )
    if set(scenarios) != set(ScenarioName):
        raise UnderwritingError("Supply exactly one BEAR, BASE, and BULL scenario.")
    return tuple(scenarios[name] for name in ScenarioName)


def _capture_financials(
    history: CanonicalFinancialHistory,
) -> tuple[tuple[FinancialState, ...], tuple[BaseRate, ...], int]:
    try:
        owner = owner_economics_from_history(history)
    except CanonicalDataError as exc:
        raise UnderwritingError(
            f"Starting annual owner economics unavailable: {exc}"
        ) from exc
    if not owner:
        raise UnderwritingError("No persisted annual financial observations.")
    latest = owner[0]
    try:
        efficiency = capital_efficiency_from_history(history)
        capital_reason = "Capital-efficiency observation absent for latest fiscal year."
    except CanonicalDataError as exc:
        efficiency = ()
        capital_reason = str(exc)
    capital = next(
        (row for row in efficiency if row.fiscal_year == latest.fiscal_year), None
    )
    values = (
        ("revenue", latest.revenue.value if latest.revenue else None, "USD", None),
        (
            "operating_margin",
            latest.operating_margin,
            "ratio",
            "operating_income / revenue",
        ),
        (
            "fcf",
            latest.free_cash_flow,
            "USD",
            "operating_cash_flow - abs(capital_expenditures)",
        ),
        ("fcf_margin", latest.fcf_margin, "ratio", "fcf / revenue"),
        (
            "diluted_shares",
            latest.diluted_shares.value if latest.diluted_shares else None,
            "shares",
            None,
        ),
        ("fcf_per_share", latest.fcf_per_share, "USD/share", "fcf / diluted_shares"),
        (
            "net_cash_debt",
            capital.net_cash if capital else None,
            "USD",
            "cash + short_term_investments - total_debt; positive = net cash",
        ),
        (
            "roic",
            capital.roic if capital else None,
            "ratio",
            "NOPAT / average invested capital",
        ),
    )
    starting = tuple(
        FinancialState(
            name,
            value,
            unit,
            latest.fiscal_year,
            basis=SemanticType.CALCULATION if calculation else SemanticType.FACT,
            calculation=calculation,
            missing_reason=(
                capital_reason
                if name in ("net_cash_debt", "roic") and capital is None
                else f"Required persisted inputs unavailable for FY{latest.fiscal_year}."
            )
            if value is None
            else None,
        )
        for name, value, unit, calculation in values
    )
    revenue_by_year = {
        row.fiscal_year: row.revenue.value for row in owner if row.revenue
    }
    observations: dict[str, tuple[HistoricalObservation, ...]] = {
        "revenue_growth": tuple(
            HistoricalObservation(
                row.fiscal_year,
                row.revenue.value / revenue_by_year[row.fiscal_year - 1] - 1
                if row.revenue and revenue_by_year.get(row.fiscal_year - 1)
                else None,
            )
            for row in owner
        ),
        "operating_margin": tuple(
            HistoricalObservation(row.fiscal_year, row.operating_margin)
            for row in owner
        ),
        "fcf_margin": tuple(
            HistoricalObservation(row.fiscal_year, row.fcf_margin) for row in owner
        ),
        "roic": tuple(
            HistoricalObservation(row.fiscal_year, row.roic) for row in efficiency
        ),
        "share_count_change": tuple(
            HistoricalObservation(row.fiscal_year, row.diluted_share_growth)
            for row in owner
        ),
    }
    formulas = {
        "revenue_growth": "revenue / prior consecutive fiscal year revenue - 1",
        "operating_margin": "operating_income / revenue",
        "fcf_margin": "fcf / revenue",
        "roic": "NOPAT / average invested capital",
        "share_count_change": "diluted_shares / prior consecutive fiscal year diluted_shares - 1",
    }
    rates: list[BaseRate] = []
    for name, points in observations.items():
        available = [point.value for point in points if point.value is not None]
        rates.append(
            BaseRate(
                name,
                points,
                min(available) if available else None,
                max(available) if available else None,
                points[0].value if points else None,
                formulas[name],
                missing_reason=(
                    capital_reason
                    if name == "roic"
                    else "Required consecutive annual observations unavailable."
                )
                if not available
                else None,
            )
        )
    return starting, tuple(rates), latest.fiscal_year


@dataclass(frozen=True)
class UnderwritingInputs:
    """Read-only point-in-time inputs; a draft/review is not a persisted version."""

    security_id: int
    ticker: str
    as_of_date: str
    captured_at: str
    starting_financial_state: tuple[FinancialState, ...]
    historical_base_rates: tuple[BaseRate, ...]
    evidence_json: str
    latest_fiscal_year: int

    def snapshot(self, manual: ManualUnderwriting) -> UnderwritingSnapshot:
        manual = parse_manual_input(asdict(manual))
        if manual.as_of_date and manual.as_of_date != self.as_of_date:
            raise UnderwritingError("Draft as-of date differs from captured inputs.")
        snapshot = UnderwritingSnapshot(
            manual, self.starting_financial_state, self.historical_base_rates,
            self.evidence_json, self.latest_fiscal_year,
            schema_version=manual.contract_version,
        )
        from owner_lens.underwriting_contract import validate_belief_links

        validate_belief_links(snapshot, self.as_of_date)
        return snapshot


def capture_underwriting_inputs(
    source: WorkbenchSource,
    ticker: str,
    *,
    as_of_date: str | None = None,
    now: datetime | None = None,
) -> UnderwritingInputs:
    """Capture the CLI's exact FACT/EXPECTATION inputs without writing a record."""
    if not isinstance(source.store, SqliteStore):
        raise UnderwritingError("Underwriting requires the SQLite evidence store.")
    created = now or datetime.now(UTC)
    if created.tzinfo is None:
        raise UnderwritingError("Creation time must be timezone-aware.")
    created = created.astimezone(UTC)
    as_of = (
        date.fromisoformat(as_of_date) if as_of_date else created.date()
    )
    if as_of > created.date():
        raise UnderwritingError("as_of_date cannot be in the future.")
    cutoff = min(created, datetime.combine(as_of, time.max, UTC)).isoformat()
    symbol = ticker.strip().upper()
    security = next(
        (item for item in source.store.list_securities() if item.symbol == symbol), None
    )
    if security is None:
        raise UnderwritingError(f"{symbol} has no persisted security identity.")
    evidence = source.store.get_underwriting_evidence(
        security.security_id, cutoff=cutoff, as_of_date=as_of.isoformat()
    )
    if evidence["history_id"] is None:
        raise UnderwritingError(
            f"No FMP annual canonical history was observed by {cutoff}."
        )
    record = source.store.get_fmp_canonical_history(evidence["history_id"])
    if evidence["price"] and evidence["price"]["evidence_kind"] != SemanticType.FACT:
        raise UnderwritingError("EOD price evidence is not classified as FACT.")
    if any(
        item["evidence_kind"] != SemanticType.FACT or item["period_type"] != "annual"
        for item in evidence["sources"]
    ):
        raise UnderwritingError(
            "Annual canonical provenance is not annual FACT evidence."
        )
    for expectation in evidence["expectations"]:
        if expectation["source"]["evidence_kind"] != SemanticType.EXPECTATION or any(
            row["evidence_kind"] != SemanticType.EXPECTATION
            for row in expectation["rows"]
        ):
            raise UnderwritingError(
                "Analyst evidence is not classified as EXPECTATION."
            )
        expectation["missing_reason"] = (
            None
            if expectation["rows"]
            else "Selected analyst snapshot contains no estimate rows."
        )
    company = PersistedCompany(
        symbol,
        security.name,
        security.cik or "",
        record.input_hash,
        record.observed_at,
        "SUCCEEDED",
        provider="fmp",
        security_id=security.security_id,
        history_id=record.history_id,
    )
    history = load_canonical_history(source, company, max_years=record.max_years)
    if any(
        fact.period_end > as_of
        for series in history.series
        for fact in series.observations
    ):
        raise UnderwritingError("Annual history contains periods after as_of_date.")
    if any(
        _retrieved_at(item["fetched_at"]) > datetime.fromisoformat(cutoff)
        for item in evidence["sources"]
    ):
        raise UnderwritingError(
            "Annual provenance contains evidence retrieved after the cutoff."
        )
    starting, rates, year = _capture_financials(history)
    screening = screen_company_from_history(history)
    copied = {
        "provider": "fmp",
        "issuer_cik": security.cik,
        "security_name": security.name,
        "cutoff": cutoff,
        "canonical_history": asdict(record),
        "annual_sources": evidence["sources"],
        "feature7_context": {
            "priority": screening.bucket.value,
            "setup_type": screening.setup_type.value,
            "coverage": screening.coverage_class.value,
            "dimensions": {
                dimension.value: score.band.value
                for dimension, score in screening.dimensions.items()
            },
        },
        "eod_price": {
            "category": SemanticType.FACT,
            "value": evidence["price"],
            "missing_reason": None
            if evidence["price"]
            else "No reliable EOD price persisted by cutoff.",
        },
        "market_expectations": {
            "category": SemanticType.EXPECTATION,
            "snapshots": evidence["expectations"],
            "missing_reason": None
            if evidence["expectations"]
            else "No analyst estimate snapshot persisted by cutoff.",
        },
    }
    return UnderwritingInputs(
        security.security_id, symbol, as_of.isoformat(), created.isoformat(),
        starting, rates, json.dumps(copied, sort_keys=True, allow_nan=False), year,
    )


def save_underwriting_inputs(
    source: WorkbenchSource,
    inputs: UnderwritingInputs,
    manual: ManualUnderwriting,
    *,
    expected_latest_version: int | None = None,
    now: datetime | None = None,
) -> UnderwritingRecord:
    """Validate and append reviewed inputs, never recapture newer evidence at save."""
    if not isinstance(source.store, SqliteStore):
        raise UnderwritingError("Underwriting requires the SQLite evidence store.")
    snapshot = inputs.snapshot(manual)
    created = now or datetime.now(UTC)
    if created.tzinfo is None or created < _retrieved_at(inputs.captured_at):
        raise UnderwritingError("Save time must be timezone-aware and not precede input capture.")
    return source.store.save_underwriting(
        security_id=inputs.security_id, ticker=inputs.ticker,
        created_at=created.astimezone(UTC).isoformat(), as_of_date=inputs.as_of_date,
        snapshot_json=snapshot.to_json(), expected_latest_version=expected_latest_version,
    )


def create_underwriting(
    source: WorkbenchSource,
    ticker: str,
    manual: ManualUnderwriting,
    *,
    now: datetime | None = None,
) -> UnderwritingRecord:
    """CLI/JSON and workbench share capture, validation and immutable persistence."""
    manual = parse_manual_input(asdict(manual))
    created = now or datetime.now(UTC)
    inputs = capture_underwriting_inputs(source, ticker, as_of_date=manual.as_of_date, now=created)
    return save_underwriting_inputs(source, inputs, manual, now=created)


def _retrieved_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UnderwritingError(
            f"Invalid persisted retrieval timestamp: {value}."
        ) from exc
    # SQLite julianday treats timezone-free timestamps as UTC.
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )

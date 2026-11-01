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


@dataclass(frozen=True)
class ManualUnderwriting:
    as_of_date: str | None
    business_drivers: tuple[Statement, ...]
    forward_assumptions: tuple[Assumption, ...]
    supporting_evidence: tuple[Statement, ...]
    disconfirming_evidence: tuple[Statement, ...]
    thesis: Thesis
    decision: Statement | None = None


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
        data["evidence"] = json.loads(data.pop("evidence_json"))
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, payload: str) -> UnderwritingSnapshot:
        data = json.loads(payload)
        if data["schema_version"] != 1:
            raise UnderwritingError("Unsupported underwriting snapshot schema.")
        manual_data = data["manual"]
        manual = parse_manual_input(manual_data)
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
        )


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
        value, name, {"category", "text", "references"}, {"category", "text"}
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
        kind, _text(item["text"], name), _references(item.get("references", []))
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
    fields = {
        "as_of_date",
        "business_drivers",
        "forward_assumptions",
        "supporting_evidence",
        "disconfirming_evidence",
        "thesis",
        "decision",
    }
    root = _object(
        data,
        "underwriting input",
        fields,
        {"business_drivers", "forward_assumptions", "thesis"},
    )
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
    if not assumptions:
        raise UnderwritingError("Supply at least one explicit forward assumption.")
    thesis_fields = {
        "dependencies",
        "breakers",
        "biggest_uncertainty",
        "most_important_variable",
        "next_evidence_to_collect",
    }
    thesis_data = _object(
        root["thesis"], "thesis", thesis_fields | {"category"}, thesis_fields
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
    )
    return ManualUnderwriting(
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
    )


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


def create_underwriting(
    source: WorkbenchSource,
    ticker: str,
    manual: ManualUnderwriting,
    *,
    now: datetime | None = None,
) -> UnderwritingRecord:
    """Capture local evidence by retrieval time and append a fully copied snapshot."""
    if not isinstance(source.store, SqliteStore):
        raise UnderwritingError("Underwriting requires the SQLite evidence store.")
    manual = parse_manual_input(asdict(manual))
    created = now or datetime.now(UTC)
    if created.tzinfo is None:
        raise UnderwritingError("Creation time must be timezone-aware.")
    created = created.astimezone(UTC)
    as_of = (
        date.fromisoformat(manual.as_of_date) if manual.as_of_date else created.date()
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
    copied = {
        "provider": "fmp",
        "issuer_cik": security.cik,
        "security_name": security.name,
        "cutoff": cutoff,
        "canonical_history": asdict(record),
        "annual_sources": evidence["sources"],
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
    snapshot = UnderwritingSnapshot(
        manual,
        starting,
        rates,
        json.dumps(copied, sort_keys=True, allow_nan=False),
        year,
    )
    return source.store.save_underwriting(
        security_id=security.security_id,
        ticker=symbol,
        created_at=created.isoformat(),
        as_of_date=as_of.isoformat(),
        snapshot_json=snapshot.to_json(),
    )


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

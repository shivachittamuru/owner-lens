"""Immutable forecast-versus-outcome observations, without decision assessment."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from owner_lens.changes import _date, _time, condition_assessment
from owner_lens.decisions import read_decision
from owner_lens.opportunity_comparison import UnderwritingSelection, load_opportunity
from owner_lens.persistence import SqliteStore
from owner_lens.position_sizing import canonical_json
from owner_lens.underwriting import (
    UnderwritingSnapshot,
    _object,
    _policy_number,
    _references,
    _text,
    condition_data,
)
from owner_lens.underwriting_summary import saved_valuation

MODEL_VERSION = "forecast-outcomes-v1"
HORIZONS = ("QUARTERLY", "1Y", "2Y", "3Y", "5Y", "CUSTOM")
SCENARIO_METRICS = {
    "revenue_cagr": ("ratio", "FISCAL_CAGR"),
    "share_count_cagr": ("ratio", "FISCAL_CAGR"),
    "fcf_margin_year5": ("ratio", "ANNUAL_FISCAL"),
    "terminal_fcf_multiple": ("multiple", "FISCAL_YEAR_END"),
}
DISCLAIMER = (
    "FORECAST vs OUTCOME only. Market price return is not investor realized return "
    "or portfolio performance; excludes dividends, costs and taxes. No scenario winner, "
    "probability update, skill/luck assessment, thesis change or decision instruction."
)


class OutcomeError(ValueError):
    """An observation, source or exact forecast link is invalid."""


def _number(value: Any, label: str) -> float | None:
    return None if value is None else _policy_number(value, label)


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _year(value: Any, label: str) -> int | None:
    if value is not None and (type(value) is not int or not 1 <= value <= 9999):
        raise OutcomeError(f"{label} must be an explicit fiscal year or null.")
    return value


def parse_observation(data: Any, *, recorded_at: str) -> dict[str, Any]:
    fields = {
        "observation_date",
        "observed_at",
        "horizon",
        "horizon_note",
        "category",
        "references",
        "verification_note",
        "market",
        "fundamentals",
    }
    obj = _object(data, "outcome observation", fields, fields - {"horizon_note"})
    observed = _time(obj["observed_at"], "observed_at")
    observation_date = _date(obj["observation_date"], "observation_date")
    if observation_date > observed.date() or observed > _time(
        recorded_at, "recorded_at"
    ):
        raise OutcomeError("Outcome dates cannot look ahead of observation/recording.")
    if obj["category"] != "FACT":
        raise OutcomeError(
            "Outcome observations must be manually verified FACT, not forecasts or judgments."
        )
    if obj["horizon"] not in HORIZONS:
        raise OutcomeError(f"horizon must be one of {HORIZONS}.")
    note = _optional_text(obj.get("horizon_note"), "horizon_note")
    if obj["horizon"] == "CUSTOM" and note is None:
        raise OutcomeError("CUSTOM horizon requires horizon_note.")
    refs = _references(obj["references"])
    for ref in refs:
        if ref.observed_at:
            source_date = (
                _time(ref.observed_at, "reference observed_at")
                if "T" in ref.observed_at
                else datetime.combine(
                    _date(ref.observed_at, "reference observed_at"),
                    datetime.min.time(),
                    UTC,
                )
            )
            if source_date > observed:
                raise OutcomeError("Source exceeds observed_at cutoff.")
    verification = _optional_text(obj["verification_note"], "verification_note")
    market = obj["market"]
    if market is not None:
        market_fields = {"price", "currency", "basis"}
        market = dict(_object(market, "market outcome", market_fields, market_fields))
        market["price"] = _number(market["price"], "market price")
        if market["price"] is not None and market["price"] < 0:
            raise OutcomeError("Observed market price cannot be negative.")
        for field in ("currency", "basis"):
            market[field] = _optional_text(market[field], field)
    if not isinstance(obj["fundamentals"], list):
        raise OutcomeError("fundamentals must be an explicit list.")
    metrics = []
    seen: set[tuple[str, str]] = set()
    for raw in obj["fundamentals"]:
        metric_fields = {
            "forecast",
            "observable",
            "value",
            "unit",
            "basis",
            "fiscal_year",
            "start_fiscal_year",
            "period_end",
            "cadence",
            "source_family",
        }
        metric = dict(_object(raw, "fundamental outcome", metric_fields, metric_fields))
        link = _object(
            metric["forecast"], "forecast link", {"kind", "id"}, {"kind", "id"}
        )
        if link["kind"] not in ("SCENARIO", "CONDITION"):
            raise OutcomeError("Forecast kind must be SCENARIO or CONDITION.")
        link = {"kind": link["kind"], "id": _text(link["id"], "forecast id")}
        key = (link["kind"], link["id"])
        if key in seen:
            raise OutcomeError("Duplicate forecast link within observation.")
        seen.add(key)
        if link["kind"] == "SCENARIO" and link["id"] not in SCENARIO_METRICS:
            raise OutcomeError(
                "Unknown frozen scenario metric; no inferred metric mapping."
            )
        metric["forecast"] = link
        metric["value"] = _number(metric["value"], "observed metric")
        for field in ("observable", "unit", "basis", "cadence", "source_family"):
            metric[field] = _optional_text(metric[field], field)
        for field in ("fiscal_year", "start_fiscal_year"):
            metric[field] = _year(metric[field], field)
        if metric["period_end"] is not None:
            end = _date(metric["period_end"], "period_end")
            if end > observation_date:
                raise OutcomeError("Metric period_end exceeds observation_date.")
            if (
                metric["fiscal_year"] is not None
                and metric["fiscal_year"] > end.year + 1
            ):
                raise OutcomeError(
                    "Fiscal year cannot look ahead of the reported period."
                )
        if (
            metric["fiscal_year"] is not None
            and metric["start_fiscal_year"] is not None
            and metric["start_fiscal_year"] >= metric["fiscal_year"]
        ):
            raise OutcomeError("CAGR start fiscal year must precede end fiscal year.")
        metrics.append(metric)
    has_value = (market is not None and market["price"] is not None) or any(
        metric["value"] is not None for metric in metrics
    )
    if has_value and (
        not verification or not any(ref.uri or ref.title for ref in refs)
    ):
        raise OutcomeError(
            "FACT values require source metadata and an explicit manual verification_note."
        )
    return {
        "observation_date": observation_date.isoformat(),
        "observed_at": observed.isoformat(),
        "horizon": obj["horizon"],
        "horizon_note": note,
        "category": "FACT",
        "references": [asdict(ref) for ref in refs],
        "verification_note": verification,
        "market": market,
        "fundamentals": metrics,
    }


def range_comparison(
    value: float | None, scenarios: dict[str, float]
) -> dict[str, Any]:
    """Ordered labels only; near BASE is numerical equality, not a judgment band."""
    result: dict[str, Any] = {
        "category": "CALCULATION",
        "scenario_values": scenarios,
        "status": "INSUFFICIENT_DATA",
        "reason": "Observed value is missing.",
        "nearest_scenarios": [],
        "base_tolerance": None,
    }
    if value is None:
        return result
    bear, base, bull = (scenarios[name] for name in ("BEAR", "BASE", "BULL"))
    tolerance = 1e-9 * max(1.0, abs(base))
    result["base_tolerance"] = tolerance
    distance = min(abs(value - item) for item in scenarios.values())
    result["nearest_scenarios"] = [
        name
        for name, item in scenarios.items()
        if abs(abs(value - item) - distance) <= tolerance
    ]
    if not bear <= base <= bull:
        result.update(
            status="NOT_COMPARABLE",
            reason="Frozen scenario values are not BEAR <= BASE <= BULL; no reordering.",
        )
        return result
    status = (
        "BELOW_BEAR"
        if value < bear - tolerance
        else "ABOVE_BULL"
        if value > bull + tolerance
        else "NEAR_BASE"
        if abs(value - base) <= tolerance
        else "WITHIN_BEAR_BASE"
        if value < base
        else "WITHIN_BASE_BULL"
    )
    result.update(
        status=status,
        reason="Time-aligned comparison to frozen scenario values, not a forecast assessment.",
    )
    return result


def _anniversary(start: date, years: int) -> date:
    # February 29 anniversaries use February 28 in non-leap years.
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return start.replace(year=start.year + years, day=28)


def _market(observation: dict[str, Any], forecast: dict[str, Any]) -> dict[str, Any]:
    market = observation["market"]
    values = {
        item["assumptions"]["name"]: item["year5_value_per_share"]
        for item in forecast["valuation"]["scenarios"]
    }
    comparison = range_comparison(None, values)
    result = {
        "family": "MARKET_OUTCOME",
        "category": "CALCULATION",
        "observed": market,
        "frozen_starting_price": forecast["valuation"]["current_price"],
        "starting_market_date": forecast["valuation"]["market_date"],
        "total_price_return": None,
        "annualized_price_return": None,
        "annualization_reason": "No comparable observed price.",
        "comparison": comparison,
    }
    if market is None or market["price"] is None:
        return result
    if (
        market["currency"] is None
        or forecast["valuation"]["price_currency"] is None
        or market["basis"] is None
    ):
        comparison.update(
            status="INSUFFICIENT_DATA",
            reason="Price currency or same-share-basis attestation missing.",
        )
        return result
    if (
        market["currency"] != forecast["valuation"]["price_currency"]
        or market["basis"] != "EOD_CLOSE_SAME_SHARE_BASIS"
    ):
        comparison.update(
            status="NOT_COMPARABLE",
            reason="Currency or price/share basis differs; no FX/split adjustment inferred.",
        )
        return result
    observed_date = _date(observation["observation_date"], "observation_date")
    start = _date(forecast["valuation"]["market_date"], "market_date")
    days = (observed_date - start).days
    if days <= 0:
        comparison.update(
            status="INSUFFICIENT_DATA",
            reason="Market outcome requires a positive elapsed price interval.",
        )
        return result
    ratio = market["price"] / result["frozen_starting_price"]
    result["total_price_return"] = _policy_number(ratio - 1, "price return")
    if observed_date >= _anniversary(start, 1):
        result["annualized_price_return"] = _policy_number(
            ratio ** (365.2425 / days) - 1, "annualized price return"
        )
        result["annualization_reason"] = (
            "At least one calendar year; ACT/365.2425 from frozen market date, price-only."
        )
    else:
        result["annualization_reason"] = (
            "Less than one calendar year; annualization withheld."
        )
    terminal = _anniversary(_date(forecast["as_of_date"], "as_of_date"), 5)
    if observed_date == terminal:
        result["comparison"] = range_comparison(market["price"], values)
    else:
        comparison.update(
            status="INTERIM_OBSERVATION"
            if observed_date < terminal
            else "NOT_COMPARABLE",
            reason="No price path is encoded. Only the exact five-year as-of anniversary matches terminal values.",
        )
    return result


def _fundamental(
    metric: dict[str, Any], observation: dict[str, Any], forecast: dict[str, Any]
) -> dict[str, Any]:
    link = metric["forecast"]
    report: dict[str, Any] = {
        "family": "FUNDAMENTAL_OUTCOME",
        "category": "CALCULATION",
        "observed": metric,
        "observation_date": observation["observation_date"],
        "references": observation["references"],
        "frozen_belief": None,
        "status": "INSUFFICIENT_DATA",
        "reason": "Observed value or measurement period missing.",
        "nearest_scenarios": [],
    }
    if link["kind"] == "CONDITION":
        condition = next(
            (
                item
                for item in forecast["conditions"]
                if item["condition_id"] == link["id"]
            ),
            None,
        )
        if condition is None:
            raise OutcomeError(f"Unknown or ambiguous frozen condition: {link['id']}.")
        report["frozen_belief"] = condition
        if metric["period_end"] is None or metric["value"] is None:
            return report
        assessed = condition_assessment(
            {
                "event_date": metric["period_end"],
                "observation": {
                    "category": observation["category"],
                    "metric": metric,
                    "references": observation["references"],
                },
            },
            condition,
            condition["kind"],
        )
        report.update(
            status="NOT_COMPARABLE"
            if assessed["result"] == "NOT_COMPARABLE"
            else "INSUFFICIENT_DATA"
            if assessed["result"] == "INSUFFICIENT_DATA"
            else "NO_SCENARIO_RANGE",
            reason="Frozen dependency/breaker comparison only; no scenario range or change classification inferred. "
            + assessed["reason"],
            condition_status=assessed["result"],
            predicate_satisfied=assessed["predicate_satisfied"],
        )
        return report
    field = link["id"]
    values = {
        item["assumptions"]["name"]: item["assumptions"][field]
        for item in forecast["valuation"]["scenarios"]
    }
    unit, basis = SCENARIO_METRICS[field]
    target_year = forecast["valuation"]["latest_fiscal_year"] + 5
    report["frozen_belief"] = {
        "category": "ASSUMPTION",
        "field": field,
        "scenario_values": values,
        "unit": unit,
        "basis": basis,
        "target_fiscal_year": target_year,
        "start_fiscal_year": forecast["valuation"]["latest_fiscal_year"]
        if basis == "FISCAL_CAGR"
        else None,
    }
    if any(
        metric[key] is None
        for key in ("value", "observable", "unit", "basis", "fiscal_year", "period_end")
    ):
        return report
    if (metric["observable"], metric["unit"], metric["basis"]) != (field, unit, basis):
        report.update(
            status="NOT_COMPARABLE",
            reason="Observable definition, unit or measurement basis differs; no fuzzy matching or conversions.",
        )
        return report
    if basis == "FISCAL_CAGR" and metric["start_fiscal_year"] is None:
        return report
    if (
        basis == "FISCAL_CAGR"
        and metric["start_fiscal_year"] != forecast["valuation"]["latest_fiscal_year"]
    ):
        report.update(
            status="NOT_COMPARABLE",
            reason="CAGR does not start from the frozen starting fiscal year.",
        )
        return report
    if metric["fiscal_year"] != target_year:
        report.update(
            status="INTERIM_OBSERVATION"
            if metric["fiscal_year"] < target_year
            else "NOT_COMPARABLE",
            reason="Only the frozen year-5 fiscal horizon is comparable; no interim trajectory encoded.",
        )
        return report
    report.update(range_comparison(metric["value"], values))
    return report


def frozen_forecast(
    store: SqliteStore, selection: UnderwritingSelection
) -> dict[str, Any]:
    opportunity = load_opportunity(store, selection)
    record = next(
        item
        for item in store.list_underwriting(selection.ticker)
        if item.underwriting_id == opportunity.summary.underwriting_id
    )
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    conditions = [
        {**condition_data(item), "kind": kind}
        for kind, group in (
            ("DEPENDENCY", snapshot.manual.thesis.monitoring_dependencies),
            ("BREAKER", snapshot.manual.thesis.monitoring_breakers),
        )
        for item in group
    ]
    if len({item["condition_id"] for item in conditions}) != len(conditions):
        raise OutcomeError(
            "Condition IDs must be unique across dependencies and breakers."
        )
    return {
        "semantic_role": "FORECAST",
        "ticker": record.ticker,
        "security_id": record.security_id,
        "underwriting_id": record.underwriting_id,
        "version": record.version,
        "content_hash": record.content_hash,
        "as_of_date": record.as_of_date,
        "created_at": record.created_at,
        "snapshot": json.loads(record.snapshot_json),
        "valuation": json.loads(saved_valuation(store, record)),
        "conditions": conditions,
    }


def _record_context(
    store: SqliteStore, underwriting_id: str, cutoff: datetime
) -> dict[str, Any]:
    decisions = [
        json.loads(read_decision(item).to_json())
        for item in store.list_decisions()
        if item.underwriting_id == underwriting_id
    ]
    decisions = [
        item
        for item in decisions
        if _time(item["recorded_at"], "decision recorded_at") <= cutoff
        and _time(item["decision_at"], "decision_at") <= cutoff
    ]
    approvals = {
        item.event_id: json.loads(item.snapshot_json)
        for item in store.list_change_approvals()
        if _time(item.approved_at, "approved_at") <= cutoff
    }
    changes = [
        {
            "event": json.loads(item.snapshot_json),
            "approval": approvals.get(item.event_id),
        }
        for item in store.list_change_events()
        if item.underwriting_id == underwriting_id
        and _time(item.recorded_at, "event recorded_at") <= cutoff
    ]
    return {
        "scope": "Records linked to this exact underwriting available at outcome recording; context only.",
        "decisions": decisions,
        "changes": changes,
    }


def build_observation(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    observation_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    UUID(observation_id)
    observation = parse_observation(data, recorded_at=recorded_at)
    forecast = frozen_forecast(store, selection)
    recorded = _time(recorded_at, "recorded_at")
    observed = _time(observation["observed_at"], "observed_at")
    start = _date(forecast["as_of_date"], "as_of_date")
    end = _date(observation["observation_date"], "observation_date")
    if (
        observed < _time(forecast["created_at"], "underwriting created_at")
        or end <= start
    ):
        raise OutcomeError(
            "Outcome must follow the exact underwriting as-of and cannot be observed before its creation."
        )
    for metric in observation["fundamentals"]:
        if (
            metric["period_end"] is not None
            and _date(metric["period_end"], "period_end") <= start
        ):
            raise OutcomeError(
                "Outcome measurement period must end after underwriting as-of."
            )
    return {
        "observation_id": observation_id,
        "ticker": forecast["ticker"],
        "security_id": forecast["security_id"],
        "underwriting": {
            key: forecast[key]
            for key in (
                "underwriting_id",
                "version",
                "content_hash",
                "as_of_date",
                "created_at",
            )
        },
        "recorded_at": recorded.isoformat(),
        "model_version": MODEL_VERSION,
        "semantic_role": "OUTCOME",
        "observation": observation,
        "elapsed": {
            "days_since_underwriting_as_of": (end - start).days,
            "years_act_365_2425": (end - start).days / 365.2425,
            "category": "CALCULATION",
        },
        "forecast": forecast,
        "market_outcome": _market(observation, forecast),
        "fundamental_outcomes": [
            _fundamental(metric, observation, forecast)
            for metric in observation["fundamentals"]
        ],
        "record_context": _record_context(store, forecast["underwriting_id"], recorded),
        "disclaimer": DISCLAIMER,
    }


def validate_observation(store: SqliteStore, report: dict[str, Any]) -> None:
    expected = build_observation(
        store,
        UnderwritingSelection(report["ticker"], report["underwriting"]["version"]),
        report["observation"],
        observation_id=report["observation_id"],
        recorded_at=report["recorded_at"],
    )
    if canonical_json(report) != canonical_json(expected):
        raise OutcomeError(
            "Outcome differs from exact frozen forecast, sources, context or deterministic calculations."
        )


def create_observation(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise OutcomeError("recorded_at requires an explicit timezone.")
    report = build_observation(
        store,
        selection,
        data,
        observation_id=str(uuid4()),
        recorded_at=timestamp.astimezone(UTC).isoformat(),
    )
    store.save_outcome_observation(canonical_json(report))
    return report


def read_observation(store: SqliteStore, observation_id: str) -> dict[str, Any]:
    """Read frozen calculations, not a rerun against newer evidence or model rules."""
    return json.loads(store.get_outcome_observation(observation_id).snapshot_json)


def outcome_history(store: SqliteStore, ticker: str) -> list[dict[str, Any]]:
    records = store.list_underwriting(ticker)
    if not records:
        raise OutcomeError(f"No underwriting exists for {ticker}.")
    security_id = records[0].security_id
    return [
        json.loads(item.snapshot_json)
        for item in store.list_outcome_observations()
        if item.security_id == security_id
    ]


def compare_outcomes(
    store: SqliteStore, selection: UnderwritingSelection
) -> dict[str, Any]:
    forecast = frozen_forecast(store, selection)
    observations = [
        item
        for item in outcome_history(store, selection.ticker)
        if item["underwriting"]["underwriting_id"] == forecast["underwriting_id"]
    ]
    tracked = {
        item["forecast"]["id"]
        for observation in observations
        for item in observation["observation"]["fundamentals"]
        if item["forecast"]["kind"] == "SCENARIO" and item["value"] is not None
    }
    conditions = {
        item["forecast"]["id"]
        for observation in observations
        for item in observation["observation"]["fundamentals"]
        if item["forecast"]["kind"] == "CONDITION" and item["value"] is not None
    }
    return {
        "model_version": MODEL_VERSION,
        "forecast": forecast,
        "observations": observations,
        "missing_observations": {
            "market": not any(
                item["observation"]["market"] is not None
                and item["observation"]["market"]["price"] is not None
                for item in observations
            ),
            "scenario_metrics": sorted(set(SCENARIO_METRICS) - tracked),
            "conditions": sorted(
                item["condition_id"]
                for item in forecast["conditions"]
                if item["condition_id"] not in conditions
            ),
        },
        "disclaimer": DISCLAIMER,
    }


def format_observation(report: dict[str, Any]) -> str:
    market = report["market_outcome"]
    lines = [
        f"{report['ticker']} v{report['underwriting']['version']} | {report['observation_id']}",
        f"Underwriting as-of: {report['underwriting']['as_of_date']} | frozen price: {market['frozen_starting_price']}",
        f"Observation: {report['observation']['observation_date']} | {report['observation']['horizon']} | elapsed days: {report['elapsed']['days_since_underwriting_as_of']}",
        f"MARKET_OUTCOME: {canonical_json(market['observed'])}",
        f"Total price return: {market['total_price_return']} | annualized price return: {market['annualized_price_return']}",
        market["annualization_reason"],
        f"Price scenario comparison: {market['comparison']['status']} | {market['comparison']['reason']}",
        f"Frozen year-5 scenario prices: {canonical_json(market['comparison']['scenario_values'])}",
    ]
    for item in report["fundamental_outcomes"]:
        lines.extend(
            [
                f"FUNDAMENTAL_OUTCOME {item['observed']['forecast']['id']}: {item['observed']['value']} {item['observed']['unit']} | {item['status']}",
                f"Frozen belief: {canonical_json(item['frozen_belief'])}",
                f"Nearest scenario values (descriptive): {', '.join(item['nearest_scenarios']) or 'NOT DETERMINED'}",
                item["reason"],
            ]
        )
    lines.extend(
        [f"Sources: {canonical_json(report['observation']['references'])}", DISCLAIMER]
    )
    return "\n".join(lines)


def format_comparison(report: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            f"{report['forecast']['ticker']} v{report['forecast']['version']} forecast vs outcomes",
            *(format_observation(item) for item in report["observations"]),
            f"Missing observations (not manufactured): {canonical_json(report['missing_observations'])}",
            DISCLAIMER,
        ]
    )

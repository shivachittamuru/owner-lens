"""Manual evidence events and explicit approvals over immutable underwriting beliefs."""

from __future__ import annotations

import json
import math
import operator
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from owner_lens.decisions import read_decision
from owner_lens.opportunity_comparison import UnderwritingSelection, load_opportunity
from owner_lens.persistence import SqliteStore
from owner_lens.position_sizing import canonical_json
from owner_lens.underwriting import (
    UnderwritingSnapshot,
    _object,
    _references,
    _text,
    condition_data,
)

MODEL_VERSION = "manual-change-assessment-v1.1"


class ChangeError(ValueError):
    """Event, approval or condition linkage is invalid."""


class ChangeClassification(StrEnum):
    NOISE = "NOISE"
    EVIDENCE = "EVIDENCE"
    THESIS_UPDATE = "THESIS_UPDATE"
    THESIS_BREAK = "THESIS_BREAK"


class ConditionResult(StrEnum):
    CONDITION_MET = "CONDITION_MET"
    CONDITION_BREACHED = "CONDITION_BREACHED"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _time(value: Any, label: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, label))
    if parsed.tzinfo is None:
        raise ChangeError(f"{label} requires an explicit timezone.")
    return parsed.astimezone(UTC)


def _date(value: Any, label: str) -> date:
    text = _text(value, label)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ChangeError(f"{label} must be YYYY-MM-DD.")
    return parsed


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ChangeError(f"{label} must be an explicit list.")
    values = [_text(item, label) for item in value]
    if len(set(values)) != len(values):
        raise ChangeError(f"{label} cannot contain duplicates.")
    return values


def parse_event(data: Any, *, recorded_at: str) -> dict[str, Any]:
    fields = {
        "event_date",
        "observed_at",
        "observation",
        "interpretation",
        "condition_id",
        "affected_beliefs",
        "affected_binding_constraints",
    }
    obj = _object(
        data,
        "change input",
        fields,
        fields - {"condition_id", "affected_binding_constraints"},
    )
    recorded = _time(recorded_at, "recorded_at")
    observed = _time(obj["observed_at"], "observed_at")
    event_date = _date(obj["event_date"], "event_date")
    if observed > recorded or event_date > observed.date():
        raise ChangeError(
            "Event/source cannot look ahead of observed_at or recorded_at."
        )
    observation = _object(
        obj["observation"],
        "observation",
        {"category", "statement", "references", "verification_note", "metric"},
        {"category", "statement", "references"},
    )
    if observation["category"] not in ("FACT", "EXPECTATION", "JUDGMENT"):
        raise ChangeError("Observation category must be FACT, EXPECTATION or JUDGMENT.")
    refs = _references(observation["references"])
    for ref in refs:
        if ref.observed_at:
            source_time = (
                _time(ref.observed_at, "reference observed_at")
                if "T" in ref.observed_at
                else datetime.combine(
                    _date(ref.observed_at, "reference observed_at"),
                    datetime.min.time(),
                    UTC,
                )
            )
            if source_time > observed:
                raise ChangeError(
                    "Source observation exceeds event observation cutoff."
                )
    note = observation.get("verification_note")
    if note is not None:
        note = _text(note, "verification_note")
    if observation["category"] == "FACT" and (
        not note or not any(ref.uri or ref.title for ref in refs)
    ):
        raise ChangeError(
            "FACT requires source metadata and an explicit manual verification_note; no automatic verification."
        )
    metric = observation.get("metric")
    if metric is not None:
        metric = _object(
            metric,
            "event metric",
            {"observable", "value", "unit", "cadence", "source_family"},
            {"observable", "value", "unit", "cadence"},
        )
        metric = dict(metric)
        for field in ("observable", "unit", "cadence"):
            if metric[field] is not None:
                metric[field] = _text(metric[field], field)
        if "source_family" in metric and metric["source_family"] is not None:
            metric["source_family"] = _text(metric["source_family"], "source_family")
        if metric["value"] is not None:
            if isinstance(metric["value"], bool) or not isinstance(
                metric["value"], (int, float)
            ):
                raise ChangeError("Metric value must be finite numeric or null.")
            if not math.isfinite(float(metric["value"])):
                raise ChangeError("Metric value must be finite.")
    interpretation = _object(
        obj["interpretation"],
        "interpretation",
        {"category", "text"},
        {"category", "text"},
    )
    if interpretation["category"] != "JUDGMENT":
        raise ChangeError("Investor interpretation must remain JUDGMENT.")
    return {
        "event_date": event_date.isoformat(),
        "observed_at": observed.isoformat(),
        "observation": {
            "category": observation["category"],
            "statement": _text(observation["statement"], "event statement"),
            "references": [asdict(ref) for ref in refs],
            "verification_note": note,
            "metric": metric,
        },
        "interpretation": {
            "category": "JUDGMENT",
            "text": _text(interpretation["text"], "interpretation"),
        },
        "condition_id": _text(obj["condition_id"], "condition_id")
        if obj.get("condition_id") is not None
        else None,
        "affected_beliefs": _strings(obj["affected_beliefs"], "affected_beliefs"),
        "affected_binding_constraints": _strings(
            obj.get("affected_binding_constraints", []), "affected_binding_constraints"
        ),
    }


def condition_assessment(
    event: dict[str, Any], condition: dict[str, Any] | None, kind: str | None
) -> dict[str, Any]:
    """Strict literal metric matching; never parse qualitative prose or normalize units."""

    def result(
        status: ConditionResult,
        reason: str,
        candidate: ChangeClassification | None = None,
        predicate: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "result": status,
            "reason": reason,
            "candidate_classification": candidate,
            "predicate_satisfied": predicate,
            "condition_kind": kind,
            "condition": condition,
            "model_version": MODEL_VERSION,
            "category": "CALCULATION",
        }

    if condition is None:
        return result(
            ConditionResult.INSUFFICIENT_DATA,
            "No structured condition linked; manual classification required.",
        )
    metric = event["observation"]["metric"]
    if metric is None or any(
        metric.get(field) is None for field in ("observable", "value", "unit")
    ):
        return result(
            ConditionResult.INSUFFICIENT_DATA,
            "Metric, value, observable or unit missing.",
        )
    if event["observation"]["category"] != "FACT":
        return result(
            ConditionResult.INSUFFICIENT_DATA,
            "Threshold candidate requires a manually verified FACT, not expectation/judgment.",
        )
    if condition["observable"] is None or condition["threshold"] is None:
        return result(
            ConditionResult.INSUFFICIENT_DATA, "Condition observable/threshold missing."
        )
    if metric["observable"] != condition["observable"]:
        return result(
            ConditionResult.NOT_COMPARABLE,
            "Observable/definition differs; no fuzzy matching.",
        )
    structured = condition.get("operator") is not None
    if structured:
        op = {"GT": ">", "GTE": ">=", "LT": "<", "LTE": "<=", "EQ": "=="}[condition["operator"]]
        threshold = condition["threshold"]
        unit = condition["unit"]
        cadence = condition["cadence"]
        if metric.get("source_family") is None:
            return result(ConditionResult.INSUFFICIENT_DATA, "Required metric source_family missing.")
        if metric["source_family"] != condition["source_family"]:
            return result(ConditionResult.NOT_COMPARABLE, "Source family differs; no inferred provenance equivalence.")
    else:
        match = re.fullmatch(
            r"(>=|<=|>|<|==)\s*(-?(?:\d+(?:\.\d+)?|\.\d+))\s*(%|[A-Za-z][A-Za-z0-9_]*)",
            condition["threshold"],
        )
        if match is None:
            return result(
                ConditionResult.NOT_COMPARABLE,
                "Threshold is not a supported explicit numeric operator/value/unit.",
            )
        op, number, unit = match.groups()
        threshold = float(number)
        cadence = condition["monitoring_cadence"]
    if metric["unit"] != unit:
        return result(
            ConditionResult.NOT_COMPARABLE,
            "Units differ; no ratio/percent/currency conversion.",
        )
    if cadence is not None:
        if metric["cadence"] is None:
            return result(
                ConditionResult.INSUFFICIENT_DATA,
                "Required observation cadence missing.",
            )
        if metric["cadence"] != cadence:
            return result(
                ConditionResult.NOT_COMPARABLE,
                "Cadence differs; no annualizing or persistence inference.",
            )
    if (
        condition["monitoring_date"]
        and event["event_date"] < condition["monitoring_date"]
    ):
        return result(
            ConditionResult.INSUFFICIENT_DATA, "Condition monitoring date not reached."
        )
    required_refs = condition["sources"]
    if required_refs:
        supplied = event["observation"]["references"]
        if not supplied:
            return result(
                ConditionResult.INSUFFICIENT_DATA, "Required source metadata missing."
            )
        if not any(
            (
                ref["uri"] == supplied_ref["uri"]
                if ref["uri"]
                else bool(ref["title"]) and ref["title"] == supplied_ref["title"]
            )
            for ref in required_refs
            for supplied_ref in supplied
        ):
            return result(
                ConditionResult.NOT_COMPARABLE,
                "Source does not match an explicitly linked source URI/title.",
            )
    if not math.isfinite(threshold):
        return result(
            ConditionResult.NOT_COMPARABLE, "Threshold outside finite numeric range."
        )
    satisfied = {
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
        "==": operator.eq,
    }[op](metric["value"], threshold)
    breached = satisfied if kind == "BREAKER" else not satisfied
    status = (
        ConditionResult.CONDITION_BREACHED
        if breached
        else ConditionResult.CONDITION_MET
    )
    candidate = (
        (
            ChangeClassification.THESIS_BREAK
            if kind == "BREAKER"
            else ChangeClassification.THESIS_UPDATE
        )
        if breached
        else ChangeClassification.EVIDENCE
    )
    return result(
        status,
        "Breaker predicate triggered."
        if breached and kind == "BREAKER"
        else "Dependency predicate failed."
        if breached
        else "No linked condition breach.",
        candidate,
        satisfied,
    )


def _beliefs(
    snapshot: UnderwritingSnapshot, pointers: list[str]
) -> list[dict[str, Any]]:
    data = json.loads(snapshot.to_json())
    allowed = {
        "/manual/scenarios/": ("assumption", "ASSUMPTION"),
        "/manual/probability_distribution/": ("probability", "JUDGMENT"),
        "/manual/thesis/": ("thesis", "JUDGMENT"),
        "/manual/business_drivers/": ("thesis", "JUDGMENT"),
        "/manual/forward_assumptions/": ("assumption", "ASSUMPTION"),
    }
    result = []
    for pointer in pointers:
        group = next(
            (value for prefix, value in allowed.items() if pointer.startswith(prefix)),
            None,
        )
        if group is None:
            raise ChangeError(
                f"Affected belief must reference a frozen assumption/probability/thesis: {pointer}"
            )
        try:
            value: Any = data
            for token in pointer[1:].split("/"):
                key = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", key):
                        raise KeyError(key)
                    value = value[int(key)]
                else:
                    value = value[key]
            if value is None:
                raise KeyError(pointer)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChangeError(f"Unresolved/missing affected belief: {pointer}") from exc
        result.append(
            {
                "pointer": pointer,
                "kind": group[0],
                "category": group[1],
                "previous_belief": value,
            }
        )
    return result


def _contexts(
    store: SqliteStore, security_id: int, cutoff: datetime
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    decisions = [
        read_decision(item)
        for item in store.list_decisions()
        if item.security_id == security_id
    ]
    available = [
        item
        for item in decisions
        if _time(item.recorded_at, "decision recorded_at") <= cutoff
        and _time(item.decision_at, "decision_at") <= cutoff
    ]
    latest = max(
        available,
        key=lambda item: (_time(item.recorded_at, "recorded_at"), item.decision_id),
        default=None,
    )
    sizing = [
        item
        for item in store.list_sizing_analyses()
        if _time(item.created_at, "sizing created_at") <= cutoff
        and json.loads(item.report_json)["security_id"] == security_id
    ]
    analysis = max(
        sizing,
        key=lambda item: (_time(item.created_at, "created_at"), item.analysis_id),
        default=None,
    )
    return (
        json.loads(latest.to_json()) if latest else None,
        {
            "analysis_id": analysis.analysis_id,
            "created_at": analysis.created_at,
            "report": json.loads(analysis.report_json),
        }
        if analysis
        else None,
    )


def build_event(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    event_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    event = parse_event(data, recorded_at=recorded_at)
    opportunity = load_opportunity(store, selection)
    record = next(
        item
        for item in store.list_underwriting(selection.ticker)
        if item.underwriting_id == opportunity.summary.underwriting_id
    )
    if _time(record.created_at, "underwriting created_at") > _time(
        event["observed_at"], "observed_at"
    ):
        raise ChangeError(
            "New event must have been observed after the selected underwriting existed."
        )
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    conditions = [
        (kind, condition_data(condition))
        for kind, values in (
            ("DEPENDENCY", snapshot.manual.thesis.monitoring_dependencies),
            ("BREAKER", snapshot.manual.thesis.monitoring_breakers),
        )
        for condition in values
    ]
    matches = [
        (kind, condition)
        for kind, condition in conditions
        if condition["condition_id"] == event["condition_id"]
    ]
    if event["condition_id"] is not None and len(matches) != 1:
        raise ChangeError(
            "Condition ID must resolve uniquely in the exact frozen underwriting."
        )
    kind, condition = matches[0] if matches else (None, None)
    affected = _beliefs(snapshot, event["affected_beliefs"])
    decision, sizing = _contexts(
        store, record.security_id, _time(recorded_at, "recorded_at")
    )
    bindings = event["affected_binding_constraints"]
    if bindings and (
        sizing is None
        or not set(bindings) <= set(sizing["report"]["binding_constraints"])
    ):
        raise ChangeError(
            "Affected binding constraints must reference the frozen linked sizing analysis."
        )
    assessment = condition_assessment(event, condition, kind)
    return {
        "event_id": _text(event_id, "event_id"),
        "recorded_at": recorded_at,
        "ticker": record.ticker,
        "security_id": record.security_id,
        "underwriting": asdict(record),
        "event": event,
        "assessment": assessment,
        "affected_beliefs": affected,
        "decision_context": decision,
        "sizing_context": sizing,
        "sizing_binding_effect": {
            "status": "INVESTOR_IDENTIFIED" if bindings else "NOT_DETERMINED",
            "binding_constraints": bindings,
            "category": "JUDGMENT",
            "note": "Manual interpretation only; no sizing recalculation or resolved-constraint inference.",
        },
        "model_version": MODEL_VERSION,
    }


def create_event(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    recorded = now or datetime.now(UTC)
    if recorded.tzinfo is None:
        raise ChangeError("Recording time requires timezone.")
    try:
        event = build_event(
            store,
            selection,
            data,
            event_id=str(uuid4()),
            recorded_at=recorded.astimezone(UTC).isoformat(),
        )
        store.save_change_event(canonical_json(event))
        return event
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        if isinstance(exc, ChangeError):
            raise
        raise ChangeError(f"Cannot record change event: {exc}") from exc


def validate_event_sources(store: SqliteStore, event: dict[str, Any]) -> None:
    record = event["underwriting"]
    expected = build_event(
        store,
        UnderwritingSelection(record["ticker"], record["version"]),
        event["event"],
        event_id=event["event_id"],
        recorded_at=event["recorded_at"],
    )
    if canonical_json(event) != canonical_json(expected):
        raise ChangeError(
            "Event differs from exact source identity, frozen context or deterministic assessment."
        )


def trigger(classification: str) -> str:
    selected = ChangeClassification(classification)
    return (
        "NEW_UNDERWRITING_REQUIRED"
        if selected
        in (ChangeClassification.THESIS_UPDATE, ChangeClassification.THESIS_BREAK)
        else "REVIEW_RECOMMENDED"
        if selected == ChangeClassification.EVIDENCE
        else "NO_REUNDERWRITING_REQUIRED"
    )


def approve_event(
    store: SqliteStore,
    event_id: str,
    classification: str,
    rationale: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    event = json.loads(store.get_change_event(event_id).snapshot_json)
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp < _time(
        event["recorded_at"], "recorded_at"
    ):
        raise ChangeError(
            "Approval cannot precede event recording and requires timezone."
        )
    approval = {
        "approval_id": str(uuid4()),
        "event_id": event_id,
        "approved_at": timestamp.astimezone(UTC).isoformat(),
        "approved_classification": ChangeClassification(classification).value,
        "rationale": _text(rationale, "approval rationale"),
        "category": "JUDGMENT",
        "reunderwriting_trigger": trigger(classification),
        "model_version": MODEL_VERSION,
    }
    store.save_change_approval(canonical_json(approval))
    return approval


def assess_event(store: SqliteStore, event_id: str) -> dict[str, Any]:
    """Return frozen assessment plus append-only approval, never re-run a newer model."""
    event = json.loads(store.get_change_event(event_id).snapshot_json)
    approval_record = next(
        (item for item in store.list_change_approvals() if item.event_id == event_id),
        None,
    )
    approval = json.loads(approval_record.snapshot_json) if approval_record else None
    decision = event["decision_context"]
    approved = approval["approved_classification"] if approval else None
    return {
        **event,
        "approval": approval,
        "approved_classification": approved,
        "history_status": "APPROVED" if approval else "PENDING_APPROVAL",
        "reunderwriting_trigger": approval["reunderwriting_trigger"]
        if approval
        else None,
        "decision_implication": (
            f"Recorded {decision['judgment']['action']} decision should be revisited."
            if decision and approved in ("THESIS_UPDATE", "THESIS_BREAK", "EVIDENCE")
            else "No automatic decision change; pending investor approval."
            if not approval
            else "No automatic decision change."
        ),
    }


def change_history(store: SqliteStore, ticker: str) -> list[dict[str, Any]]:
    underwriting = store.list_underwriting(ticker)
    if not underwriting:
        raise ChangeError(f"No underwriting exists for {ticker}.")
    security_id = underwriting[0].security_id
    return [
        assess_event(store, item.event_id)
        for item in store.list_change_events()
        if item.security_id == security_id
    ]


def current_change_state(store: SqliteStore, ticker: str) -> dict[str, Any]:
    records = store.list_underwriting(ticker)
    if not records:
        raise ChangeError(f"No underwriting exists for {ticker}.")
    latest = records[-1]
    history = change_history(store, ticker)
    # Events linked to older versions but observed since this version still matter.
    since = [
        item
        for item in history
        if _time(item["event"]["observed_at"], "observed_at")
        >= _time(latest.created_at, "created_at")
    ]
    approved = [item["approval"] for item in since if item["approval"] is not None]
    pending = [item for item in since if item["approval"] is None]
    counts = {
        classification.value: sum(
            approval["approved_classification"] == classification for approval in approved
        )
        for classification in ChangeClassification
    }
    decision, sizing = _contexts(store, latest.security_id, datetime.now(UTC))
    return {
        "ticker": latest.ticker,
        "security_id": latest.security_id,
        "latest_underwriting": {
            "underwriting_id": latest.underwriting_id,
            "version": latest.version,
        },
        "latest_decision": decision,
        "latest_sizing": sizing,
        "since_underwriting": counts,
        "pending_approval": len(pending),
        "pending_non_comparable": sum(item["assessment"]["result"] == ConditionResult.NOT_COMPARABLE for item in pending),
        "included_event_ids": [item["event_id"] for item in since],
        "status": "REUNDERWRITING_REQUIRED"
        if counts["THESIS_UPDATE"] or counts["THESIS_BREAK"]
        else "REVIEW_PENDING"
        if pending
        else "REVIEW_RECOMMENDED"
        if counts["EVIDENCE"]
        else "NO_REUNDERWRITING_REQUIRED",
        "scope": "All events observed since latest underwriting creation, including links to older versions; pending events counted separately.",
    }


def format_assessment(report: dict[str, Any]) -> str:
    decision, sizing = report["decision_context"], report["sizing_context"]
    condition = report["assessment"]["condition"]
    lines = [
        f"{report['ticker']} v{report['underwriting']['version']} | {report['event_id']}",
        f"Observed evidence: {report['event']['observation']['statement']}",
        f"Observed metric: {canonical_json(report['event']['observation']['metric'])}",
        f"Event date / observed / recorded: {report['event']['event_date']} / {report['event']['observed_at']} / {report['recorded_at']}",
        f"Dependency / threshold: {condition['statement']} / {condition.get('operator') or ''} {condition['threshold']} {condition.get('unit') or ''}"
        if condition
        else "Dependency / threshold: MISSING",
        f"Condition result: {report['assessment']['result']} ({report['assessment']['reason']})",
        f"Candidate: {report['assessment']['candidate_classification'] or 'NOT DETERMINED'}",
        f"Approved classification: {report['approved_classification'] or 'PENDING_APPROVAL'}",
        f"Re-underwriting: {report['reunderwriting_trigger'] or 'PENDING_APPROVAL'}",
        "Previous / affected beliefs: "
        + (
            canonical_json(report["affected_beliefs"])
            if report["affected_beliefs"]
            else "NONE LINKED (not assumed unaffected)"
        ),
        f"Interpretation [JUDGMENT]: {report['event']['interpretation']['text']}",
        f"Decision implication: {report['decision_implication']}",
        f"Latest recorded decision at event recording: {decision['judgment']['action']} | {decision['decision_at']} | underwriting v{decision['chosen']['underwriting']['version']} | {decision['judgment']['what_would_change_decision']}"
        if decision
        else "Decision context: MISSING",
        f"Historical sizing: {sizing['analysis_id']} | underwriting v{sizing['report']['underwriting']['version']} | {sizing['report']['status']} | ceiling {sizing['report']['target_range'][1]:.2%} | bindings {', '.join(sizing['report']['binding_constraints'])} | binding effect {report['sizing_binding_effect']['status']}"
        if sizing
        else "Sizing context: MISSING",
        "No assumption, probability, decision or sizing changed. No new underwriting saved.",
    ]
    return "\n".join(lines)


def format_current_state(report: dict[str, Any]) -> str:
    decision, sizing = report["latest_decision"], report["latest_sizing"]
    return "\n".join(
        [
            f"Latest underwriting: {report['ticker']} v{report['latest_underwriting']['version']}",
            f"Latest recorded decision: {decision['judgment']['action']} ({decision['decision_at']})"
            if decision
            else "Latest decision: MISSING",
            f"What would change decision: {decision['judgment']['what_would_change_decision']}"
            if decision
            else "Decision change rule: MISSING",
            f"Latest historical sizing: {sizing['report']['status']} | ceiling {sizing['report']['target_range'][1]:.2%} | {sizing['analysis_id']}"
            if sizing
            else "Latest sizing: MISSING",
            "Since underwriting:",
            *(
                f"  {count} {classification}"
                for classification, count in report["since_underwriting"].items()
            ),
            f"Pending approval: {report['pending_approval']}",
            f"Pending non-comparable assessment: {report['pending_non_comparable']}",
            f"Status: {report['status']}",
            report["scope"],
            "Historical context only. No automatic decision or sizing changes.",
        ]
    )

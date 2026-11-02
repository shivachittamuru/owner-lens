"""Investor-authored decisions and counterfactual starts, never execution or sizing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import uuid4

from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
    load_opportunity,
)
from owner_lens.persistence import SqliteStore, UnderwritingRecord, compute_content_hash
from owner_lens.persistence.records import DecisionRecord
from owner_lens.underwriting import SemanticType, _object

DECISION_MODEL_VERSION = "decision-record-v1"
SHADOW_MODEL_VERSION = "shadow-entry-v1"
DISCLAIMER = (
    "Investor judgment, not a recommendation or execution record. "
    "Shadow entries are independent $100 counterfactuals, not portfolio weights. "
    "Outcome is not decision quality; no process, skill or luck assessment is made."
)


class DecisionError(ValueError):
    """Invalid judgment, identity, point-in-time state or shadow configuration."""


class DecisionAction(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    WATCH = "WATCH"
    PASS = "PASS"
    TRIM = "TRIM"
    EXIT = "EXIT"


class Confidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlternativeDisposition(StrEnum):
    PREFERRED = "PREFERRED"
    DEFERRED = "DEFERRED"
    PASSED_OVER = "PASSED_OVER"


class ShadowRole(StrEnum):
    ACTUAL_CHOICE = "ACTUAL_CHOICE"
    BEST_ALTERNATIVE = "BEST_ALTERNATIVE"
    PASS_CANDIDATE = "PASS_CANDIDATE"
    BENCHMARK = "BENCHMARK"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionError(f"{label} must be non-empty text.")
    return value


def load_decision_json(payload: str) -> Any:
    """Reject duplicate keys and non-finite constants instead of silently replacing input."""

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DecisionError(f"Duplicate decision JSON field: {key}.")
            result[key] = value
        return result

    def invalid_constant(value: str) -> Any:
        raise DecisionError(f"Non-finite decision JSON constant: {value}.")

    return json.loads(
        payload, object_pairs_hook=unique_keys, parse_constant=invalid_constant
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise DecisionError("Decision timestamps must include an explicit timezone.")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class DecisionJudgment:
    action: DecisionAction
    rationale: str
    confidence: Confidence
    primary_reason: str
    biggest_risk: str
    what_would_change_decision: str
    category: SemanticType = SemanticType.JUDGMENT

    @classmethod
    def from_data(cls, data: Any) -> DecisionJudgment:
        fields = set(cls.__dataclass_fields__)
        obj = _object(data, "decision judgment", fields, fields)
        if obj["category"] != "JUDGMENT":
            raise DecisionError("Decision content must be JUDGMENT.")
        return cls(
            DecisionAction(obj["action"]),
            _text(obj["rationale"], "rationale"),
            Confidence(obj["confidence"]),
            _text(obj["primary_reason"], "primary_reason"),
            _text(obj["biggest_risk"], "biggest_risk"),
            _text(obj["what_would_change_decision"], "what_would_change_decision"),
        )


@dataclass(frozen=True)
class FrozenOpportunity:
    """Copy both original source bytes and the Feature 9A evidence projection."""

    underwriting: UnderwritingRecord
    opportunity_json: str

    @property
    def label(self) -> str:
        return f"{self.underwriting.ticker}:{self.underwriting.version}"

    @property
    def summary(self) -> dict[str, Any]:
        return json.loads(self.opportunity_json)["summary"]

    def to_data(self) -> dict[str, Any]:
        return {
            "underwriting": asdict(self.underwriting),
            "opportunity": json.loads(self.opportunity_json),
        }

    @classmethod
    def from_data(cls, data: Any) -> FrozenOpportunity:
        obj = _object(
            data,
            "frozen opportunity",
            {"underwriting", "opportunity"},
            {"underwriting", "opportunity"},
        )
        fields = set(UnderwritingRecord.__dataclass_fields__)
        record_data = _object(
            obj["underwriting"], "underwriting identity", fields, fields
        )
        for field in ("security_id", "version"):
            if type(record_data[field]) is not int or record_data[field] < 1:
                raise DecisionError(f"{field} must be a positive integer.")
        for field in fields - {"security_id", "version"}:
            _text(record_data[field], field)
        record = UnderwritingRecord(**record_data)
        if compute_content_hash(record.snapshot_json.encode()) != record.content_hash:
            raise DecisionError("Frozen underwriting content hash mismatch.")
        summary = obj["opportunity"]["summary"]
        if (
            summary["underwriting_id"] != record.underwriting_id
            or summary["underwriting_version"] != record.version
            or summary["underwriting_content_hash"] != record.content_hash
            or summary["ticker"] != record.ticker
        ):
            raise DecisionError("Frozen opportunity identity mismatch.")
        return cls(record, _json(obj["opportunity"]))


@dataclass(frozen=True)
class DecisionAlternative:
    opportunity: FrozenOpportunity
    disposition: AlternativeDisposition
    reason: str
    category: SemanticType = SemanticType.JUDGMENT

    def to_data(self) -> dict[str, Any]:
        return {
            "opportunity": self.opportunity.to_data(),
            "disposition": self.disposition,
            "reason": self.reason,
            "category": self.category,
        }


@dataclass(frozen=True)
class ShadowEntry:
    shadow_id: str
    decision_id: str
    decision_at: str
    as_of_date: str
    security_id: int | None
    ticker: str
    underwriting_id: str | None
    underwriting_version: int | None
    underwriting_content_hash: str | None
    role: ShadowRole
    action: DecisionAction
    frozen_price: float | None
    market_date: str | None
    missing_reason: str | None
    model_version: str = SHADOW_MODEL_VERSION
    state: str = "DECISION_STATE"
    price_category: SemanticType = SemanticType.FACT
    price_basis: str = "FROZEN_UNDERWRITING"
    basis: str = "INDEPENDENT_HYPOTHETICAL_100_USD"
    notional_usd: int = 100
    currency: str = "USD"
    outcome_state: str = "NOT_OBSERVED"

    def to_json(self) -> str:
        return _json(asdict(self))

    @classmethod
    def from_data(cls, data: Any) -> ShadowEntry:
        fields = set(cls.__dataclass_fields__)
        obj = _object(data, "shadow entry", fields, fields)
        return cls(
            **{
                **obj,
                "shadow_id": _text(obj["shadow_id"], "shadow_id"),
                "decision_id": _text(obj["decision_id"], "decision_id"),
                "role": ShadowRole(obj["role"]),
                "action": DecisionAction(obj["action"]),
                "price_category": SemanticType(obj["price_category"]),
            }
        )


@dataclass(frozen=True)
class DecisionSnapshot:
    decision_id: str
    recorded_at: str
    decision_at: str
    as_of_date: str
    judgment: DecisionJudgment
    chosen: FrozenOpportunity
    alternatives: tuple[DecisionAlternative, ...]
    comparison_json: str | None
    shadows: tuple[ShadowEntry, ...]
    shadow_requested: bool
    model_version: str = DECISION_MODEL_VERSION
    state: str = "DECISION_STATE"

    def to_json(self) -> str:
        return _json(
            {
                "decision_id": self.decision_id,
                "recorded_at": self.recorded_at,
                "decision_at": self.decision_at,
                "as_of_date": self.as_of_date,
                "judgment": asdict(self.judgment),
                "chosen": self.chosen.to_data(),
                "alternatives": [item.to_data() for item in self.alternatives],
                "alternatives_status": "RECORDED"
                if self.alternatives
                else "NONE_RECORDED",
                "comparison": json.loads(self.comparison_json)
                if self.comparison_json
                else None,
                "comparison_status": "FROZEN"
                if self.comparison_json
                else "NOT_PROVIDED",
                "shadows": [asdict(item) for item in self.shadows],
                "shadow_requested": self.shadow_requested,
                "model_version": self.model_version,
                "state": self.state,
            }
        )

    @classmethod
    def from_json(cls, payload: str) -> DecisionSnapshot:
        try:
            data = load_decision_json(payload)
            fields = {
                "decision_id",
                "recorded_at",
                "decision_at",
                "as_of_date",
                "judgment",
                "chosen",
                "alternatives",
                "alternatives_status",
                "comparison",
                "comparison_status",
                "shadows",
                "shadow_requested",
                "model_version",
                "state",
            }
            data = _object(data, "decision snapshot", fields, fields)
            if (
                data["model_version"] != DECISION_MODEL_VERSION
                or data["state"] != "DECISION_STATE"
            ):
                raise DecisionError("Unsupported decision state/model version.")
            if type(data["shadow_requested"]) is not bool:
                raise DecisionError("shadow_requested must be boolean.")
            alternatives = []
            for item in data["alternatives"]:
                obj = _object(
                    item,
                    "alternative",
                    {"opportunity", "disposition", "reason", "category"},
                    {"opportunity", "disposition", "reason", "category"},
                )
                if obj["category"] != "JUDGMENT":
                    raise DecisionError("Alternative reasons must be JUDGMENT.")
                alternatives.append(
                    DecisionAlternative(
                        FrozenOpportunity.from_data(obj["opportunity"]),
                        AlternativeDisposition(obj["disposition"]),
                        _text(obj["reason"], "alternative reason"),
                    )
                )
            result = cls(
                _text(data["decision_id"], "decision_id"),
                data["recorded_at"],
                data["decision_at"],
                data["as_of_date"],
                DecisionJudgment.from_data(data["judgment"]),
                FrozenOpportunity.from_data(data["chosen"]),
                tuple(alternatives),
                _json(data["comparison"]) if data["comparison"] is not None else None,
                tuple(ShadowEntry.from_data(item) for item in data["shadows"]),
                data["shadow_requested"],
            )
            result.validate()
            if json.loads(result.to_json()) != data:
                raise DecisionError(
                    "Decision snapshot status or serialized fields are inconsistent."
                )
            return result
        except (ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, DecisionError):
                raise
            raise DecisionError(f"Invalid decision snapshot: {exc}") from exc

    def validate(self) -> None:
        cutoff = _decision_cutoff(self.decision_at, self.as_of_date, self.recorded_at)
        opportunities = (self.chosen, *(item.opportunity for item in self.alternatives))
        identities = [item.underwriting.underwriting_id for item in opportunities]
        if len(set(identities)) != len(identities):
            raise DecisionError("Duplicate chosen/alternative underwriting identity.")
        for item in opportunities:
            if (
                _timestamp(item.underwriting.created_at) > cutoff
                or date.fromisoformat(item.underwriting.as_of_date) > cutoff.date()
            ):
                raise DecisionError(
                    f"{item.label} was not available at the decision cutoff."
                )
        if self.comparison_json is not None:
            comparison = json.loads(self.comparison_json)
            frozen = {
                item["summary"]["underwriting_id"]: item
                for item in comparison["opportunities"]
            }
            if set(frozen) != set(identities) or len(frozen) != len(
                comparison["opportunities"]
            ):
                raise DecisionError(
                    "Comparison must contain exactly the chosen and considered alternatives."
                )
            for item in opportunities:
                if frozen[item.underwriting.underwriting_id]["summary"] != item.summary:
                    raise DecisionError(
                        "Comparison summary differs from frozen decision evidence."
                    )
        _validate_shadows(self)


def _decision_cutoff(decision_at: str, as_of_date: str, recorded_at: str) -> datetime:
    decided, recorded = _timestamp(decision_at), _timestamp(recorded_at)
    as_of = date.fromisoformat(as_of_date)
    if as_of.isoformat() != as_of_date:
        raise DecisionError("as_of_date must be YYYY-MM-DD.")
    if decided > recorded or as_of > decided.date():
        raise DecisionError(
            "Decision time/as-of cannot exceed recording time/decision date."
        )
    return min(decided, datetime.combine(as_of, time.max, UTC))


def _freeze(
    store: SqliteStore, selection: UnderwritingSelection, cutoff: datetime
) -> FrozenOpportunity:
    opportunity = load_opportunity(store, selection)
    record = next(
        item
        for item in store.list_underwriting(selection.ticker)
        if item.underwriting_id == opportunity.summary.underwriting_id
    )
    if (
        _timestamp(record.created_at) > cutoff
        or date.fromisoformat(record.as_of_date) > cutoff.date()
    ):
        raise DecisionError(
            f"{selection.ticker}:{selection.version} was not available at the decision cutoff."
        )
    return FrozenOpportunity(record, _json(asdict(opportunity)))


def _shadow(
    decision_id: str,
    decision_at: str,
    as_of_date: str,
    action: DecisionAction,
    opportunity: FrozenOpportunity | None,
    role: ShadowRole,
    *,
    shadow_id: str | None = None,
) -> ShadowEntry:
    record = opportunity.underwriting if opportunity else None
    summary = opportunity.summary if opportunity else None
    return ShadowEntry(
        shadow_id if shadow_id is not None else str(uuid4()),
        decision_id,
        decision_at,
        as_of_date,
        record.security_id if record else None,
        record.ticker if record else "^GSPC",
        record.underwriting_id if record else None,
        record.version if record else None,
        record.content_hash if record else None,
        role,
        action,
        summary["current_price"] if summary else None,
        summary["market_date"] if summary else None,
        None
        if record
        else "S&P 500 reference only; no decision-time benchmark price captured.",
        price_basis="FROZEN_UNDERWRITING" if record else "BENCHMARK_PLACEHOLDER",
    )


def _validate_shadows(snapshot: DecisionSnapshot) -> None:
    if not snapshot.shadow_requested:
        if snapshot.shadows:
            raise DecisionError("Shadow entries exist without an explicit request.")
        return
    roles: dict[str, int] = {}
    seen = set()
    shadow_ids = set()
    alternatives = {
        item.opportunity.underwriting.underwriting_id: item
        for item in snapshot.alternatives
    }
    for entry in snapshot.shadows:
        if entry.shadow_id in shadow_ids:
            raise DecisionError("Duplicate shadow entry id.")
        shadow_ids.add(entry.shadow_id)
        roles[entry.role] = roles.get(entry.role, 0) + 1
        if (
            entry.decision_id != snapshot.decision_id
            or entry.decision_at != snapshot.decision_at
            or entry.as_of_date != snapshot.as_of_date
            or entry.action != snapshot.judgment.action
            or entry.model_version != SHADOW_MODEL_VERSION
            or entry.state != "DECISION_STATE"
            or entry.price_category != SemanticType.FACT
            or entry.basis != "INDEPENDENT_HYPOTHETICAL_100_USD"
            or type(entry.notional_usd) is not int
            or entry.notional_usd != 100
            or entry.currency != "USD"
            or entry.outcome_state != "NOT_OBSERVED"
        ):
            raise DecisionError("Inconsistent shadow decision state or unit basis.")
        if entry.role == ShadowRole.BENCHMARK:
            expected = _shadow(
                snapshot.decision_id,
                snapshot.decision_at,
                snapshot.as_of_date,
                snapshot.judgment.action,
                None,
                ShadowRole.BENCHMARK,
                shadow_id=entry.shadow_id,
            )
        else:
            identity = entry.underwriting_id
            if identity in seen:
                raise DecisionError(
                    "Duplicate/inconsistent shadow roles for an underwriting."
                )
            seen.add(identity)
            if entry.role == ShadowRole.ACTUAL_CHOICE:
                opportunity = snapshot.chosen
            else:
                alternative = alternatives.get(identity or "")
                if alternative is None:
                    raise DecisionError(
                        "Shadow alternative was not explicitly considered."
                    )
                if (
                    entry.role == ShadowRole.PASS_CANDIDATE
                    and alternative.disposition != AlternativeDisposition.PASSED_OVER
                ):
                    raise DecisionError(
                        "PASS_CANDIDATE requires a PASSED_OVER alternative."
                    )
                if (
                    entry.role == ShadowRole.BEST_ALTERNATIVE
                    and alternative.disposition == AlternativeDisposition.PASSED_OVER
                ):
                    raise DecisionError("BEST_ALTERNATIVE cannot be PASSED_OVER.")
                opportunity = alternative.opportunity
            expected = _shadow(
                snapshot.decision_id,
                snapshot.decision_at,
                snapshot.as_of_date,
                snapshot.judgment.action,
                opportunity,
                entry.role,
                shadow_id=entry.shadow_id,
            )
        if asdict(expected) != asdict(entry):
            raise DecisionError(
                "Shadow price/identity differs from frozen decision evidence."
            )
    if roles.get(ShadowRole.ACTUAL_CHOICE, 0) != 1:
        raise DecisionError("Shadow requires exactly one ACTUAL_CHOICE.")
    if (
        roles.get(ShadowRole.BEST_ALTERNATIVE, 0) > 1
        or roles.get(ShadowRole.BENCHMARK, 0) > 1
    ):
        raise DecisionError("At most one BEST_ALTERNATIVE and BENCHMARK per decision.")


def create_decision(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    now: datetime | None = None,
) -> DecisionSnapshot:
    """Validate investor input and atomically append one decision and its shadows."""
    try:
        judgment_fields = set(DecisionJudgment.__dataclass_fields__)
        fields = judgment_fields | {
            "decision_at",
            "as_of_date",
            "alternatives",
            "comparison",
            "shadow",
        }
        obj = _object(data, "decision input", fields, judgment_fields)
        judgment = DecisionJudgment.from_data(
            {key: obj[key] for key in judgment_fields}
        )
        recorded = now or datetime.now(UTC)
        if recorded.tzinfo is None:
            raise DecisionError("Recording time must be timezone-aware.")
        recorded_at = recorded.astimezone(UTC).isoformat()
        decided = _timestamp(obj.get("decision_at", recorded_at))
        decision_at = decided.isoformat()
        as_of = obj.get("as_of_date", decided.date().isoformat())
        cutoff = _decision_cutoff(decision_at, as_of, recorded_at)
        chosen = _freeze(store, selection, cutoff)
        alternative_inputs = obj.get("alternatives", [])
        if not isinstance(alternative_inputs, list):
            raise DecisionError(
                "alternatives must be a list; use [] for none recorded."
            )
        alternatives = []
        selections = [selection]
        for raw in alternative_inputs:
            alt = _object(
                raw,
                "alternative input",
                {"underwriting", "disposition", "reason"},
                {"underwriting", "disposition", "reason"},
            )
            alternative_selection = UnderwritingSelection.parse(alt["underwriting"])
            alternatives.append(
                DecisionAlternative(
                    _freeze(store, alternative_selection, cutoff),
                    AlternativeDisposition(alt["disposition"]),
                    _text(alt["reason"], "alternative reason"),
                )
            )
            selections.append(alternative_selection)
        comparison_json = None
        if obj.get("comparison") is not None:
            report = compare_underwritings(store, tuple(selections))
            if json.loads(report.to_json()) != obj["comparison"]:
                raise DecisionError(
                    "Supplied comparison does not match these exact underwriting versions and 9A rules."
                )
            comparison_json = report.to_json()
        identifier = str(uuid4())
        shadows = []
        if obj.get("shadow") is not None:
            shadow_input = _object(
                obj["shadow"],
                "shadow input",
                {"alternatives", "include_benchmark"},
                {"alternatives", "include_benchmark"},
            )
            if type(shadow_input["include_benchmark"]) is not bool or not isinstance(
                shadow_input["alternatives"], list
            ):
                raise DecisionError(
                    "Shadow requires alternatives list and boolean include_benchmark."
                )
            shadows.append(
                _shadow(
                    identifier,
                    decision_at,
                    as_of,
                    judgment.action,
                    chosen,
                    ShadowRole.ACTUAL_CHOICE,
                )
            )
            by_label = {
                item.opportunity.label: item.opportunity for item in alternatives
            }
            for raw in shadow_input["alternatives"]:
                entry = _object(
                    raw,
                    "shadow alternative",
                    {"underwriting", "role"},
                    {"underwriting", "role"},
                )
                selected = UnderwritingSelection.parse(entry["underwriting"])
                label = f"{selected.ticker}:{selected.version}"
                if label not in by_label:
                    raise DecisionError(
                        f"{label} is not an explicitly considered alternative."
                    )
                role = ShadowRole(entry["role"])
                if role not in (ShadowRole.BEST_ALTERNATIVE, ShadowRole.PASS_CANDIDATE):
                    raise DecisionError(
                        "Alternative shadow role must be BEST_ALTERNATIVE or PASS_CANDIDATE."
                    )
                shadows.append(
                    _shadow(
                        identifier,
                        decision_at,
                        as_of,
                        judgment.action,
                        by_label[label],
                        role,
                    )
                )
            if shadow_input["include_benchmark"]:
                shadows.append(
                    _shadow(
                        identifier,
                        decision_at,
                        as_of,
                        judgment.action,
                        None,
                        ShadowRole.BENCHMARK,
                    )
                )
        snapshot = DecisionSnapshot(
            identifier,
            recorded_at,
            decision_at,
            as_of,
            judgment,
            chosen,
            tuple(alternatives),
            comparison_json,
            tuple(shadows),
            obj.get("shadow") is not None,
        )
        snapshot.validate()
        # Round-trip validation also gates the storage boundary.
        snapshot = DecisionSnapshot.from_json(snapshot.to_json())
        store.save_decision(snapshot.to_json())
        return snapshot
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        if isinstance(exc, DecisionError):
            raise
        raise DecisionError(f"Cannot record decision: {exc}") from exc


def read_decision(record: DecisionRecord) -> DecisionSnapshot:
    """Read copied state only; never recalculate using current Feature 8/9A rules."""
    return DecisionSnapshot.from_json(record.snapshot_json)


def validate_decision_sources(store: SqliteStore, snapshot: DecisionSnapshot) -> None:
    """Gate persistence against exact store identities and Feature 9A evidence."""
    snapshot.validate()
    cutoff = _decision_cutoff(
        snapshot.decision_at, snapshot.as_of_date, snapshot.recorded_at
    )
    selections = []
    for item in (snapshot.chosen, *(alt.opportunity for alt in snapshot.alternatives)):
        record = item.underwriting
        selection = UnderwritingSelection(record.ticker, record.version)
        frozen = _freeze(store, selection, cutoff)
        if frozen != item:
            raise DecisionError(
                "Frozen decision evidence differs from the exact stored underwriting."
            )
        selections.append(selection)
    if snapshot.comparison_json is not None:
        report = compare_underwritings(store, tuple(selections))
        if report.to_json() != snapshot.comparison_json:
            raise DecisionError(
                "Comparison snapshot differs from exact Feature 9A outputs."
            )


def format_decision(snapshot: DecisionSnapshot) -> str:
    summary = snapshot.chosen.summary
    lines = [
        f"{snapshot.decision_id} | {snapshot.decision_at} | {snapshot.chosen.label}",
        f"Decision [JUDGMENT]: {snapshot.judgment.action} | confidence {snapshot.judgment.confidence}",
        f"Frozen price [FACT]: ${summary['current_price']:.2f} on {summary['market_date']} (not an execution price)",
        f"Expected CAGR [CALCULATION]: {summary['expected_5y_cagr']:.2%}",
        f"Required return [JUDGMENT]: {summary['investor_policy']['required_return']:.2%}",
        "Rationale: " + snapshot.judgment.rationale,
        "Primary reason: " + snapshot.judgment.primary_reason,
        "Biggest risk: " + snapshot.judgment.biggest_risk,
        "What changes decision: " + snapshot.judgment.what_would_change_decision,
        f"Alternatives: {'RECORDED' if snapshot.alternatives else 'NONE_RECORDED'}",
    ]
    lines.extend(
        f"{item.opportunity.label} {item.disposition}: {item.reason}"
        for item in snapshot.alternatives
    )
    lines += [
        f"Comparison: {'FROZEN' if snapshot.comparison_json else 'NOT_PROVIDED'}",
        f"Shadow: {'CREATED' if snapshot.shadow_requested else 'NOT_REQUESTED'}",
        DISCLAIMER,
    ]
    return "\n".join(lines)

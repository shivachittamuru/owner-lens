"""Contextual orchestration of existing comparison, sizing and decision services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from owner_lens.decisions import (
    DecisionError,
    DecisionSnapshot,
    create_decision,
    read_decision,
)
from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
)
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.records import SizingAnalysisRecord
from owner_lens.position_sizing import (
    PortfolioSnapshot,
    SizingPolicy,
    canonical_json,
    size_position,
    validate_sizing_sources,
)


@dataclass(frozen=True)
class SavedPolicy:
    source_analysis_id: str
    created_at: str
    content_hash: str
    policy_json: str


@dataclass(frozen=True)
class AllocationContext:
    portfolios: tuple[PortfolioSnapshot, ...]
    policies: tuple[SavedPolicy, ...]


def discover_allocation_context(store: SqliteStore) -> AllocationContext:
    """Policies live in saved 9C analyses, not a separate invented registry."""
    portfolios = tuple(
        sorted(
            (PortfolioSnapshot.from_json(item.snapshot_json)
             for item in store.list_portfolio_snapshots()),
            key=lambda item: (item.as_of_date, item.created_at, item.snapshot_id),
            reverse=True,
        )
    )
    policies = {}
    for analysis in reversed(store.list_sizing_analyses()):
        data = json.loads(analysis.report_json)["policy"]
        SizingPolicy.parse(data)
        payload = canonical_json(data)
        content_hash = compute_content_hash(payload.encode())
        if content_hash not in policies:
            policies[content_hash] = SavedPolicy(
                analysis.analysis_id, analysis.created_at, content_hash, payload
            )
    return AllocationContext(portfolios, tuple(policies.values()))


def validate_comparison_context(
    store: SqliteStore, comparison_json: str, selected: UnderwritingSelection
) -> dict[str, Any]:
    comparison = json.loads(comparison_json)
    selections = tuple(
        UnderwritingSelection(item["summary"]["ticker"], item["summary"]["underwriting_version"])
        for item in comparison["opportunities"]
    )
    if selected not in selections:
        raise DecisionError("Chosen underwriting is not in this frozen comparison.")
    if json.loads(compare_underwritings(store, selections).to_json()) != comparison:
        raise DecisionError("Comparison no longer matches its exact immutable sources.")
    return comparison


def record_allocation_decision(
    store: SqliteStore,
    selection: UnderwritingSelection,
    comparison_json: str,
    judgment: dict[str, Any],
    *,
    request_id: str,
    approved_at: datetime,
    sizing_report: dict[str, Any] | None,
) -> tuple[DecisionSnapshot, SizingAnalysisRecord | None]:
    """Append on explicit approval; retries resume sizing without duplicating decisions.

    The existing stores deliberately own separate transactions. A committed decision
    survives sizing persistence failure; the stable request identity resumes that step.
    """
    if approved_at.tzinfo is None:
        raise DecisionError("Approval timestamp must include a timezone.")
    approved_at = approved_at.astimezone(UTC)
    comparison = validate_comparison_context(store, comparison_json, selection)
    data = {
        **judgment,
        "comparison": comparison,
        "shadow": None,
        "decision_at": approved_at.astimezone(UTC).isoformat(),
    }
    if sizing_report is not None:
        sizing_report = json.loads(canonical_json(sizing_report))
        validate_sizing_sources(store, sizing_report, approved_at.isoformat())
        record = sizing_report["underwriting"]
        chosen = next(
            item["summary"] for item in comparison["opportunities"]
            if item["summary"]["ticker"] == selection.ticker
            and item["summary"]["underwriting_version"] == selection.version
        )
        if (
            record["underwriting_id"] != chosen["underwriting_id"]
            or record["content_hash"] != chosen["underwriting_content_hash"]
        ):
            raise DecisionError("Sizing assessment must match the exact compared underwriting.")
    existing = next(
        (item for item in store.list_decisions() if item.decision_id == request_id), None
    )
    if existing is None:
        decision = create_decision(
            store, selection, data, decision_id=request_id
        )
    else:
        decision = read_decision(existing)
        expected = {
            "category": str(decision.judgment.category),
            "action": str(decision.judgment.action),
            "confidence": str(decision.judgment.confidence),
            "rationale": decision.judgment.rationale,
            "primary_reason": decision.judgment.primary_reason,
            "biggest_risk": decision.judgment.biggest_risk,
            "what_would_change_decision": decision.judgment.what_would_change_decision,
            "alternatives": [
                {"underwriting": item.opportunity.label,
                 "disposition": str(item.disposition), "reason": item.reason}
                for item in decision.alternatives
            ],
        }
        if (
            judgment != expected
            or decision.chosen.label != f"{selection.ticker}:{selection.version}"
            or decision.comparison_json != canonical_json(comparison)
            or decision.decision_at != approved_at.isoformat()
        ):
            raise DecisionError("Retry differs from the already approved immutable decision.")
    linked = [
        item for item in store.list_sizing_analyses() if item.decision_id == request_id
    ]
    if sizing_report is None:
        if linked:
            raise DecisionError("Retry omitted the recorded allocation assessment.")
        return decision, None
    linked_report = size_position(
        store, selection, sizing_report["portfolio"]["snapshot_id"],
        sizing_report["policy"],
        context_data=sizing_report["opportunity_context"],
        proposed_increment=sizing_report["proposed_increment"],
        decision_id=decision.decision_id,
    )
    if linked:
        if len(linked) != 1 or linked[0].report_json != canonical_json(linked_report):
            raise DecisionError("Retry differs from the recorded allocation assessment.")
        return decision, linked[0]
    saved = store.save_sizing_analysis(
        canonical_json(linked_report), created_at=datetime.now(UTC).isoformat()
    )
    return decision, saved

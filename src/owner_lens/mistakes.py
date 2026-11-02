"""Investor-authorized post-mortems over exact immutable evidence, not attribution."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID, uuid4

from owner_lens.calibration import _pair, read_report
from owner_lens.changes import _date, _strings, _time
from owner_lens.decisions import Confidence, read_decision
from owner_lens.opportunity_comparison import (
    ComparisonError,
    UnderwritingSelection,
    load_opportunity,
)
from owner_lens.outcomes import MODEL_VERSION as OUTCOME_VERSION
from owner_lens.outcomes import frozen_forecast, parse_observation
from owner_lens.persistence import SqliteStore
from owner_lens.position_sizing import canonical_json
from owner_lens.underwriting import _object, _references, _text
from owner_lens.valuation import MODEL_VERSION as VALUATION_VERSION

MODEL_VERSION = "mistake-review-v1"
DISCLAIMER = (
    "Investor JUDGMENT, not skill, luck, attribution or decision-quality scoring. "
    "Candidates and process checks are not mistake conclusions. "
    "Market price outcomes are not investor realized returns. No automatic changes."
)
TAXONOMY_GROUPS = {
    "EVIDENCE_RESEARCH": (
        "MISSING_RELEVANT_EVIDENCE",
        "UNVERIFIED_EVIDENCE",
        "IGNORED_DISCONFIRMING_EVIDENCE",
        "STALE_EVIDENCE",
        "MISREAD_EVIDENCE",
    ),
    "ASSUMPTION_FORECAST": (
        "GROWTH_TOO_HIGH",
        "GROWTH_TOO_LOW",
        "MARGIN_TOO_HIGH",
        "MARGIN_TOO_LOW",
        "SHARE_COUNT_ASSUMPTION_WRONG",
        "TERMINAL_MULTIPLE_TOO_HIGH",
        "TERMINAL_MULTIPLE_TOO_LOW",
        "PROBABILITY_TOO_OPTIMISTIC",
        "PROBABILITY_TOO_PESSIMISTIC",
        "SCENARIO_RANGE_TOO_NARROW",
    ),
    "THESIS_CAUSAL_MODEL": (
        "WRONG_BUSINESS_DRIVER",
        "WRONG_CAUSAL_EXPLANATION",
        "MOAT_OVERESTIMATED",
        "MOAT_UNDERESTIMATED",
        "DISRUPTION_RISK_UNDERESTIMATED",
        "OPTIONALITY_UNDERESTIMATED",
        "TEMPORARY_VS_STRUCTURAL_MISREAD",
    ),
    "VALUATION": (
        "TERMINAL_ASSUMPTION_UNJUSTIFIED",
        "VALUATION_MODEL_INAPPROPRIATE",
        "RISK_NOT_REFLECTED_IN_SCENARIOS",
        "EXPECTED_RETURN_OVERSTATED",
    ),
    "DECISION_PROCESS": (
        "ACTED_WITHOUT_REQUIRED_EVIDENCE",
        "IGNORED_CHALLENGER_WARNING",
        "FAILED_TO_REUNDERWRITE",
        "CHANGED_THESIS_WITHOUT_NEW_EVIDENCE",
        "OVERREACTION_TO_NOISE",
        "INCONSISTENT_HURDLE",
    ),
    "PORTFOLIO_SIZING": (
        "POSITION_TOO_LARGE",
        "POSITION_TOO_SMALL",
        "THESIS_CONCENTRATION_IGNORED",
        "DOWNSIDE_BUDGET_IGNORED",
        "CASH_OPTIONALITY_IGNORED",
    ),
    "BEHAVIORAL": (
        "FOMO",
        "ANCHORING",
        "CONFIRMATION_BIAS",
        "LOSS_AVERSION",
        "ACTION_BIAS",
        "PATIENCE_FAILURE",
        "THESIS_ATTACHMENT",
        "RECENCY_BIAS",
    ),
    "NO_MISTAKE_EXTERNAL": (
        "NO_IDENTIFIED_MISTAKE",
        "ADVERSE_OUTCOME_WITH_REASONABLE_PROCESS",
        "FAVORABLE_OUTCOME_WITH_WEAK_PROCESS",
        "UNRESOLVED",
    ),
}
TAXONOMY = {code: group for group, codes in TAXONOMY_GROUPS.items() for code in codes}
MATERIAL_ERRORS = {
    "revenue_cagr": 0.01,
    "fcf_margin_year5": 0.01,
    "share_count_cagr": 0.01,
    "terminal_fcf_multiple": 1.0,
}
NUMERICAL_TOLERANCE = 1e-9
FORECAST_CODES = {
    "revenue_cagr": ("GROWTH_TOO_HIGH", "GROWTH_TOO_LOW"),
    "fcf_margin_year5": ("MARGIN_TOO_HIGH", "MARGIN_TOO_LOW"),
    "share_count_cagr": (
        "SHARE_COUNT_ASSUMPTION_WRONG",
        "SHARE_COUNT_ASSUMPTION_WRONG",
    ),
    "terminal_fcf_multiple": (
        "TERMINAL_MULTIPLE_TOO_HIGH",
        "TERMINAL_MULTIPLE_TOO_LOW",
    ),
}
LINK_FIELDS = {
    "decision_id",
    "observation_ids",
    "calibration_report_id",
    "change_event_ids",
    "sizing_analysis_id",
}


class MistakeError(ValueError):
    """Review authority, evidence or exact linkage is invalid."""


def _links(data: Any) -> dict[str, Any]:
    obj = _object(data, "review links", LINK_FIELDS, set())
    return {
        key: _strings(obj.get(key, []), key)
        if key in ("observation_ids", "change_event_ids")
        else _text(obj[key], key)
        if obj.get(key) is not None
        else None
        for key in sorted(LINK_FIELDS)
    }


def _references_at(data: Any, cutoff: datetime) -> list[dict[str, Any]]:
    refs = _references(data)
    for ref in refs:
        if ref.observed_at:
            stamp = (
                _time(ref.observed_at, "reference observed_at")
                if "T" in ref.observed_at
                else datetime.combine(
                    _date(ref.observed_at, "reference observed_at"), time.min, UTC
                )
            )
            if stamp > cutoff:
                raise MistakeError(
                    "Review evidence cannot look ahead of review date/recording."
                )
    return [asdict(ref) for ref in refs]


def _context(
    store: SqliteStore,
    selection: UnderwritingSelection,
    links: dict[str, Any],
    cutoff: datetime,
) -> dict[str, Any]:
    forecast = frozen_forecast(store, selection)
    uid = forecast["underwriting_id"]
    if (
        _time(forecast["created_at"], "underwriting created_at") > cutoff
        or _date(forecast["as_of_date"], "as_of_date") > cutoff.date()
    ):
        raise MistakeError("Underwriting was unavailable by review cutoff.")
    decision = None
    if links["decision_id"] is not None:
        decision_record = next(
            (
                item
                for item in store.list_decisions()
                if item.decision_id == links["decision_id"]
            ),
            None,
        )
        if decision_record is None:
            raise MistakeError("Selected decision not found.")
        decision = json.loads(read_decision(decision_record).to_json())
        if decision["chosen"]["underwriting"]["underwriting_id"] != uid:
            raise MistakeError("Decision must link to the exact underwriting version.")
        if any(
            _time(decision[key], key) > cutoff for key in ("recorded_at", "decision_at")
        ):
            raise MistakeError("Decision was unavailable by review cutoff.")
    outcomes = []
    for oid in sorted(links["observation_ids"]):
        stored = store.get_outcome_observation(oid)
        outcome = json.loads(stored.snapshot_json)
        if stored.underwriting_id != uid or canonical_json(
            outcome["forecast"]
        ) != canonical_json(forecast):
            raise MistakeError("Outcome must link to the exact frozen underwriting.")
        if outcome["model_version"] != OUTCOME_VERSION:
            raise MistakeError("Unsupported outcome model version.")
        if _time(outcome["recorded_at"], "outcome recorded_at") > cutoff:
            raise MistakeError("Outcome was unavailable by review cutoff.")
        parse_observation(outcome["observation"], recorded_at=outcome["recorded_at"])
        outcomes.append({"content_hash": stored.content_hash, "report": outcome})
    changes = []
    for eid in sorted(links["change_event_ids"]):
        stored_event = store.get_change_event(eid)
        if stored_event.underwriting_id != uid:
            raise MistakeError("Change event must link to the exact underwriting.")
        if _time(stored_event.recorded_at, "event recorded_at") > cutoff:
            raise MistakeError("Change event was unavailable by review cutoff.")
        approval = next(
            (
                item
                for item in store.list_change_approvals()
                if item.event_id == eid
                and _time(item.approved_at, "approved_at") <= cutoff
            ),
            None,
        )
        changes.append(
            {
                "content_hash": stored_event.content_hash,
                "event": json.loads(stored_event.snapshot_json),
                "approval": json.loads(approval.snapshot_json) if approval else None,
            }
        )
    sizing = None
    if links["sizing_analysis_id"] is not None:
        stored_sizing = store.get_sizing_analysis(links["sizing_analysis_id"])
        if stored_sizing.underwriting_id != uid:
            raise MistakeError("Sizing analysis must link to the exact underwriting.")
        if _time(stored_sizing.created_at, "sizing created_at") > cutoff:
            raise MistakeError("Sizing analysis was unavailable by review cutoff.")
        if (
            decision is not None
            and stored_sizing.decision_id != decision["decision_id"]
        ):
            raise MistakeError("Sizing must explicitly link to the selected decision.")
        sizing = {
            "analysis_id": stored_sizing.analysis_id,
            "created_at": stored_sizing.created_at,
            "content_hash": stored_sizing.content_hash,
            "report": json.loads(stored_sizing.report_json),
        }
    calibration = None
    if links["calibration_report_id"] is not None:
        calibration = read_report(store, links["calibration_report_id"])
        if _date(calibration["as_of_date"], "calibration as_of") > cutoff.date():
            raise MistakeError("Calibration cutoff cannot follow review cutoff.")
        if not any(
            item["underwriting_id"] == uid
            for item in calibration["input_underwritings"]
        ):
            raise MistakeError("Calibration must include the exact underwriting.")
        for source in calibration["input_observations"]:
            observation_record = store.get_outcome_observation(source["observation_id"])
            if (
                _time(observation_record.recorded_at, "calibration outcome recorded_at")
                > cutoff
                or observation_record.content_hash != source["content_hash"]
            ):
                raise MistakeError(
                    "Calibration input evidence exceeds review cutoff or differs from exact source."
                )
        for identity in calibration["input_underwritings"]:
            source_record = next(
                (
                    item
                    for item in store.list_underwriting(identity["ticker"])
                    if item.underwriting_id == identity["underwriting_id"]
                ),
                None,
            )
            if (
                source_record is None
                or _time(
                    source_record.created_at, "calibration underwriting created_at"
                )
                > cutoff
                or source_record.content_hash != identity["content_hash"]
            ):
                raise MistakeError(
                    "Calibration underwriting exceeds review cutoff or differs from exact source."
                )
    followups = []
    excluded_followups = []
    for record in store.list_underwriting(selection.ticker):
        if (
            record.security_id != forecast["security_id"]
            or record.version <= forecast["version"]
        ):
            continue
        if (
            _time(record.created_at, "underwriting created_at") > cutoff
            or _date(record.as_of_date, "underwriting as_of") > cutoff.date()
        ):
            continue
        # A draft alone does not establish that re-underwriting was completed.
        if store.get_valuation(record.underwriting_id, VALUATION_VERSION) is None:
            excluded_followups.append(
                {
                    "underwriting_id": record.underwriting_id,
                    "version": record.version,
                    "reason": "No saved valuation; not completed.",
                }
            )
            continue
        try:
            load_opportunity(
                store, UnderwritingSelection(record.ticker, record.version)
            )
        except ComparisonError as exc:
            excluded_followups.append(
                {
                    "underwriting_id": record.underwriting_id,
                    "version": record.version,
                    "reason": str(exc),
                }
            )
            continue
        followups.append(
            {
                key: getattr(record, key)
                for key in (
                    "underwriting_id",
                    "version",
                    "content_hash",
                    "created_at",
                    "as_of_date",
                )
            }
        )
    return {
        "forecast": forecast,
        "decision": decision,
        "outcomes": outcomes,
        "changes": changes,
        "sizing": sizing,
        "calibration": calibration,
        "completed_followup_underwritings": followups,
        "excluded_followup_underwritings": excluded_followups,
    }


def _check(code: str, status: str, question: str, detail: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "question": question,
        "detail": detail,
        "category": "CALCULATION",
    }


def _process(context: dict[str, Any]) -> list[dict[str, Any]]:
    manual = context["forecast"]["snapshot"]["manual"]
    decision = context["decision"]
    checks = [
        _check(
            "SUPPORTING_EVIDENCE_VERIFIED",
            "UNRESOLVED",
            "Was supporting evidence verified?",
            "Source presence and FACT category do not encode a verification audit; investor review required.",
        ),
        _check(
            "DISCONFIRMING_EVIDENCE_PRESENT",
            "SATISFIED" if manual["disconfirming_evidence"] else "EXCEPTION",
            "Was disconfirming evidence present?",
            "Presence only, not adequacy or whether it was heeded.",
        ),
        _check(
            "VARIANT_VIEW_DOCUMENTED",
            "SATISFIED" if manual.get("variant_rationales") else "UNRESOLVED",
            "Was the variant view documented?",
            "Documentation presence is not correctness.",
        ),
    ]
    questions = (
        decision["chosen"]["opportunity"]["quality"]["major_unresolved_questions"]
        if decision
        else None
    )
    checks.append(
        _check(
            "CHALLENGER_QUESTIONS",
            "UNRESOLVED",
            "Were challenger questions unresolved?",
            "Frozen decision questions: " + canonical_json(questions)
            if questions is not None
            else "No selected decision; no resolution/ignored-warning inference.",
        )
    )
    summary = decision["chosen"]["opportunity"]["summary"] if decision else None
    acting = decision is not None and decision["judgment"]["action"] in ("BUY", "ADD")
    hurdle_exception = acting and summary is not None and summary["return_spread"] < 0
    checks.append(
        _check(
            "HURDLE_CONSISTENCY",
            "EXCEPTION"
            if hurdle_exception
            else "SATISFIED"
            if summary and acting
            else "UNRESOLVED",
            "Was the decision consistent with the hurdle?",
            "BUY/ADD judgment below the frozen hurdle."
            if hurdle_exception
            else "Only BUY/ADD economic consistency is tested; no execution or decision-quality inference.",
        )
    )
    sizing = context["sizing"]
    if sizing is None:
        sizing_status, detail = (
            "UNRESOLVED",
            "No exact Feature 9C sizing context selected.",
        )
    else:
        report = sizing["report"]
        target = report["proposed_target_weight"]
        excess = target is not None and target > report["target_range"][1] + 1e-9
        sizing_status = (
            "EXCEPTION"
            if excess
            else "UNRESOLVED"
            if target is None or report["missing_dimensions"]
            else "SATISFIED"
        )
        detail = (
            "Proposed (not executed) target vs explicit frozen cap: "
            + canonical_json(
                {
                    "target": target,
                    "cap": report["target_range"][1],
                    "warnings": report["warnings"],
                    "missing": report["missing_dimensions"],
                }
            )
        )
    checks.append(
        _check(
            "SIZING_WITHIN_POLICY", sizing_status, "Was sizing within policy?", detail
        )
    )
    required = [
        item
        for item in context["changes"]
        if item["approval"] is not None
        and item["approval"]["approved_classification"]
        in ("THESIS_UPDATE", "THESIS_BREAK")
    ]
    outstanding = [
        item["event"]["event_id"]
        for item in required
        if not any(
            _time(record["created_at"], "followup created_at")
            > _time(item["approval"]["approved_at"], "approved_at")
            for record in context["completed_followup_underwritings"]
        )
    ]
    checks.append(
        _check(
            "REUNDERWRITING_PERFORMED",
            "EXCEPTION" if outstanding else "SATISFIED" if required else "UNRESOLVED",
            "Was a required re-underwriting performed?",
            "Approved changes without a later completed underwriting: "
            + canonical_json(outstanding)
            if outstanding
            else "No outstanding selected approved change; pending events cannot require re-underwriting.",
        )
    )
    return checks


def _candidate(code: str, rationale: str, refs: list[str]) -> dict[str, Any]:
    return {
        "code": code,
        "category": TAXONOMY[code],
        "confidence": "MEDIUM",
        "rationale": rationale,
        "evidence_references": refs,
        "machine_suggested": True,
        "investor_approved": False,
        "semantic_category": "JUDGMENT",
    }


def _analysis(
    store: SqliteStore,
    selection: UnderwritingSelection,
    context: dict[str, Any],
    review_date: str,
) -> dict[str, Any]:
    forecast = context["forecast"]
    record = next(
        item
        for item in store.list_underwriting(selection.ticker)
        if item.underwriting_id == forecast["underwriting_id"]
    )
    checks = _process(context)
    candidates = []
    pairs = []
    returns = []
    for linked in context["outcomes"]:
        outcome = linked["report"]
        oid = outcome["observation_id"]
        market = outcome["market_outcome"]
        if market["total_price_return"] is not None:
            returns.append(market["total_price_return"])
        pairs.append(_pair(record, forecast, outcome, "market_price", None))
        for fundamental in outcome["fundamental_outcomes"]:
            metric = fundamental["observed"]["forecast"]["id"]
            pair = _pair(record, forecast, outcome, metric, fundamental)
            pairs.append(pair)
            if pair["status"] != "ELIGIBLE" or metric not in MATERIAL_ERRORS:
                continue
            error = pair["forecast_error"]
            if abs(error) > MATERIAL_ERRORS[metric] + NUMERICAL_TOLERANCE:
                code = FORECAST_CODES[metric][int(error > 0)]
                candidates.append(
                    _candidate(
                        code,
                        f"Comparable {metric}: observed minus Base = {error}; "
                        f"material threshold > {MATERIAL_ERRORS[metric]} native units. Forecast miss, not proof of process failure.",
                        [oid],
                    )
                )
            values = fundamental["frozen_belief"]["scenario_values"].values()
            if (
                pair["observed"]
                < min(values) - MATERIAL_ERRORS[metric] - NUMERICAL_TOLERANCE
                or pair["observed"]
                > max(values) + MATERIAL_ERRORS[metric] + NUMERICAL_TOLERANCE
            ):
                candidates.append(
                    _candidate(
                        "SCENARIO_RANGE_TOO_NARROW",
                        f"Comparable {metric} outside the frozen scenario span by more than the materiality threshold.",
                        [oid],
                    )
                )
    reunderwrite = next(
        item for item in checks if item["code"] == "REUNDERWRITING_PERFORMED"
    )
    overdue = [
        item
        for item in context["changes"]
        if item["approval"] is not None
        and item["approval"]["approved_classification"]
        in ("THESIS_UPDATE", "THESIS_BREAK")
        and _time(item["approval"]["approved_at"], "approved_at").date().isoformat()
        < review_date
        and not any(
            _time(record["created_at"], "created_at")
            > _time(item["approval"]["approved_at"], "approved_at")
            for record in context["completed_followup_underwritings"]
        )
    ]
    if reunderwrite["status"] == "EXCEPTION" and overdue:
        candidates.append(
            _candidate(
                "FAILED_TO_REUNDERWRITE",
                "Selected approved thesis change predates review day; no later completed underwriting recorded. "
                "No deadline is encoded: investor must assess timing and whether work occurred outside OwnerLens.",
                [item["event"]["event_id"] for item in overdue],
            )
        )
    if context["sizing"] is not None:
        report = context["sizing"]["report"]
        target = report["proposed_target_weight"]
        if target is not None:
            refs = [context["sizing"]["analysis_id"]]
            if target > report["target_range"][1] + 1e-9:
                candidates.append(
                    _candidate(
                        "POSITION_TOO_LARGE",
                        "Recorded proposal exceeds its explicit frozen cap; not evidence of execution.",
                        refs,
                    )
                )
            for code, breached in (
                (
                    "THESIS_CONCENTRATION_IGNORED",
                    any(
                        report["thesis_weights"].get(tag, 0)
                        + report["proposed_increment"]
                        > report["policy"]["max_thesis_weight"] + NUMERICAL_TOLERANCE
                        for tag in report["opportunity_context"]["exposure_tags"] or ()
                    ),
                ),
                (
                    "DOWNSIDE_BUDGET_IGNORED",
                    report["proposed_bear_loss_contribution"] is not None
                    and report["proposed_bear_loss_contribution"]
                    > report["policy"]["max_portfolio_bear_loss_contribution"] + 1e-9,
                ),
                (
                    "CASH_OPTIONALITY_IGNORED",
                    report["cash_weight"] is not None
                    and report["cash_weight"] - report["proposed_increment"]
                    < report["policy"]["min_cash_reserve"] - 1e-9,
                ),
            ):
                if breached:
                    candidates.append(
                        _candidate(
                            code,
                            "Recorded proposal breaches the corresponding explicit policy; "
                            "investor must assess intent, not inferred from price.",
                            refs,
                        )
                    )
    merged: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if item["code"] not in merged:
            merged[item["code"]] = item
        else:
            previous = merged[item["code"]]
            previous["evidence_references"] = sorted(
                set(previous["evidence_references"] + item["evidence_references"])
            )
            previous["rationale"] += " " + item["rationale"]
    eligible = [item for item in pairs if item["status"] == "ELIGIBLE"]
    states = {item["status"] for item in pairs}
    forecast_pairs = [item for item in eligible if item["metric"] in MATERIAL_ERRORS]
    outcome_quality = (
        "FAVORABLE"
        if returns
        and len(returns) == len(context["outcomes"])
        and all(value > 0 for value in returns)
        else "ADVERSE"
        if returns
        and len(returns) == len(context["outcomes"])
        and all(value < 0 for value in returns)
        else "UNRESOLVED"
    )
    missed = any(
        abs(item["forecast_error"])
        > MATERIAL_ERRORS[item["metric"]] + NUMERICAL_TOLERANCE
        for item in forecast_pairs
    )
    forecast_quality = (
        "MISSED" if missed else "SUPPORTED" if forecast_pairs else "UNRESOLVED"
    )
    process_quality = (
        "EXCEPTIONS"
        if any(item["status"] == "EXCEPTION" for item in checks)
        else "COMPLIANT"
        if all(item["status"] == "SATISFIED" for item in checks)
        else "UNRESOLVED"
    )
    return {
        "evidence_state": "REVIEWABLE"
        if eligible or merged
        else "INTERIM_ONLY"
        if "INTERIM_ONLY" in states
        else "NOT_COMPARABLE"
        if "NOT_COMPARABLE" in states
        else "INSUFFICIENT_EVIDENCE",
        "process_checks": checks,
        "candidate_labels": [merged[key] for key in sorted(merged)],
        "comparison_evidence": pairs,
        "quality": {
            "outcome_quality": outcome_quality,
            "forecast_quality": forecast_quality,
            "process_quality": process_quality,
            "decision_quality": "NOT_ASSESSED_HERE",
            "category": "CALCULATION",
            "basis": "Outcome: sign of selected price-only returns (mixed/zero unresolved). "
            "Forecast: comparable fundamental Base errors at explicit material thresholds only. "
            "Process: documented checks only; unresolved checks prevent compliance conclusion.",
        },
    }


def suggest_review(
    store: SqliteStore,
    selection: UnderwritingSelection,
    *,
    links: Any = None,
    review_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise MistakeError("Review recording requires timezone.")
    day = _date(review_date or clock.astimezone(UTC).date().isoformat(), "review_date")
    cutoff = min(clock.astimezone(UTC), datetime.combine(day, time.max, UTC))
    if day > clock.astimezone(UTC).date():
        raise MistakeError("Review date cannot look ahead of recording.")
    if links is None:
        forecast = frozen_forecast(store, selection)
        uid = forecast["underwriting_id"]
        links = {
            "observation_ids": [
                item.observation_id
                for item in store.list_outcome_observations()
                if item.underwriting_id == uid
                and _time(item.recorded_at, "recorded_at") <= cutoff
            ],
            "change_event_ids": [
                item.event_id
                for item in store.list_change_events()
                if item.underwriting_id == uid
                and _time(item.recorded_at, "recorded_at") <= cutoff
            ],
        }
    selected_links = _links(links)
    context = _context(store, selection, selected_links, cutoff)
    return {
        "model_version": MODEL_VERSION,
        "review_date": day.isoformat(),
        "links": selected_links,
        "context": context,
        "approved_labels": [],
        **_analysis(store, selection, context, day.isoformat()),
        "rules": {
            "material_errors_native_units": MATERIAL_ERRORS,
            "numerical_tolerance": NUMERICAL_TOLERANCE,
            "approval": "EXPLICIT_INVESTOR_ONLY",
        },
        "disclaimer": DISCLAIMER,
    }


def _approve_labels(
    data: Any, suggestion: dict[str, Any], cutoff: datetime
) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise MistakeError("approved_labels must be an explicit list; [] is valid.")
    approved: list[dict[str, Any]] = []
    candidates = {item["code"] for item in suggestion["candidate_labels"]}
    eligible = [
        item
        for item in suggestion["comparison_evidence"]
        if item["status"] == "ELIGIBLE"
    ]
    for raw in data:
        fields = {
            "code",
            "confidence",
            "rationale",
            "evidence_references",
            "investor_approved",
        }
        obj = _object(raw, "approved label", fields, fields)
        code = obj["code"]
        if not isinstance(code, str) or code not in TAXONOMY:
            raise MistakeError("Unknown taxonomy code.")
        if any(item["code"] == code for item in approved):
            raise MistakeError("Duplicate approved taxonomy code.")
        if obj["investor_approved"] is not True:
            raise MistakeError(
                "Every label, including behavioral labels, requires explicit investor_approved: true."
            )
        group = TAXONOMY[code]
        if group == "ASSUMPTION_FORECAST":
            relevant = [
                item
                for item in eligible
                if item["metric"] in FORECAST_CODES
                and code in FORECAST_CODES[item["metric"]]
            ]
            if code == "SCENARIO_RANGE_TOO_NARROW":
                relevant = [
                    item for item in eligible if item["metric"] in MATERIAL_ERRORS
                ]
            if code.startswith("PROBABILITY_"):
                report = suggestion["context"]["calibration"]
                uid = suggestion["context"]["forecast"]["underwriting_id"]
                if (
                    report is None
                    or report["probability_calibration"]["status"]
                    != "CALIBRATION_AVAILABLE"
                    or not any(
                        item["underwriting"]["underwriting_id"] == uid
                        for item in report["probability_calibration"]["raw_scores"]
                    )
                ):
                    raise MistakeError(
                        "Probability labels require sufficient linked comparable calibration evidence."
                    )
            elif not relevant:
                raise MistakeError(
                    "Forecast labels require a linked comparable completed metric, not interim price evidence."
                )
        if group == "PORTFOLIO_SIZING" and suggestion["context"]["sizing"] is None:
            raise MistakeError(
                "Sizing labels require exact Feature 9C context; price outcomes are insufficient."
            )
        refs = _references_at(obj["evidence_references"], cutoff)
        if not refs or not any(item["uri"] or item["title"] for item in refs):
            raise MistakeError("Approved labels require explicit evidence references.")
        approved.append(
            {
                "code": code,
                "category": group,
                "confidence": Confidence(obj["confidence"]).value,
                "rationale": _text(obj["rationale"], "label rationale"),
                "evidence_references": refs,
                "machine_suggested": code in candidates,
                "investor_approved": True,
                "semantic_category": "JUDGMENT",
            }
        )
    codes = {item["code"] for item in approved}
    if "NO_IDENTIFIED_MISTAKE" in codes and any(
        TAXONOMY[code] != "NO_MISTAKE_EXTERNAL" for code in codes
    ):
        raise MistakeError(
            "NO_IDENTIFIED_MISTAKE cannot coexist with an approved mistake."
        )
    return sorted(approved, key=lambda item: item["code"])


def build_review(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    review_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    UUID(review_id)
    fields = {
        "review_date",
        "category",
        "reviewer",
        "rationale",
        "evidence_references",
        "links",
        "approved_labels",
        "primary_mistake",
        "confidence",
        "unresolved_questions",
    }
    obj = _object(data, "mistake review", fields, fields - {"primary_mistake"})
    if obj["category"] != "JUDGMENT":
        raise MistakeError("Review must be JUDGMENT.")
    recorded = _time(recorded_at, "recorded_at")
    suggestion = suggest_review(
        store,
        selection,
        links=obj["links"],
        review_date=obj["review_date"],
        now=recorded,
    )
    cutoff = min(
        recorded,
        datetime.combine(_date(obj["review_date"], "review_date"), time.max, UTC),
    )
    approved = _approve_labels(obj["approved_labels"], suggestion, cutoff)
    primary = obj.get("primary_mistake")
    if primary is not None and (
        not isinstance(primary, str)
        or primary not in {item["code"] for item in approved}
    ):
        raise MistakeError(
            "Optional primary_mistake must be an explicitly approved label."
        )
    judgment = {
        "review_date": suggestion["review_date"],
        "category": "JUDGMENT",
        "reviewer": _text(obj["reviewer"], "reviewer"),
        "rationale": _text(obj["rationale"], "review rationale"),
        "evidence_references": _references_at(obj["evidence_references"], cutoff),
        "links": suggestion["links"],
        "approved_labels": [
            {
                key: item[key]
                for key in (
                    "code",
                    "confidence",
                    "rationale",
                    "evidence_references",
                    "investor_approved",
                )
            }
            for item in approved
        ],
        "primary_mistake": primary,
        "confidence": Confidence(obj["confidence"]).value,
        "unresolved_questions": _strings(
            obj["unresolved_questions"], "unresolved_questions"
        ),
    }
    forecast = suggestion["context"]["forecast"]
    return {
        **suggestion,
        "review_id": review_id,
        "recorded_at": recorded.isoformat(),
        "category": "JUDGMENT",
        "judgment": judgment,
        "security_id": forecast["security_id"],
        "ticker": forecast["ticker"],
        "underwriting": {
            key: forecast[key] for key in ("underwriting_id", "version", "content_hash")
        },
        "approved_labels": approved,
        "primary_mistake": primary,
        "secondary_mistakes": [
            item["code"] for item in approved if item["code"] != primary
        ],
    }


def create_review(
    store: SqliteStore,
    selection: UnderwritingSelection,
    data: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise MistakeError("Recording time requires timezone.")
    report = build_review(
        store,
        selection,
        data,
        review_id=str(uuid4()),
        recorded_at=clock.astimezone(UTC).isoformat(),
    )
    store.save_mistake_review(canonical_json(report))
    return report


def read_review(store: SqliteStore, review_id: str) -> dict[str, Any]:
    return json.loads(store.get_mistake_review(review_id))


def review_history(store: SqliteStore, ticker: str) -> list[dict[str, Any]]:
    records = store.list_underwriting(ticker)
    if not records:
        raise MistakeError(f"No underwriting exists for {ticker}.")
    security_id = records[0].security_id
    return [
        item
        for item in (json.loads(payload) for payload in store.list_mistake_reviews())
        if item["security_id"] == security_id
    ]


def review_summary(store: SqliteStore) -> dict[str, Any]:
    reviews = [json.loads(payload) for payload in store.list_mistake_reviews()]
    labeled = [item for item in reviews if item["approved_labels"]]
    categories: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    for review in labeled:
        labels.update(item["code"] for item in review["approved_labels"])
        categories.update({item["category"] for item in review["approved_labels"]})
    return {
        "model_version": MODEL_VERSION,
        "category": "CALCULATION",
        "review_count": len(reviews),
        "approved_review_count": len(labeled),
        "approved_mistake_review_count": sum(
            any(
                item["category"] != "NO_MISTAKE_EXTERNAL"
                for item in review["approved_labels"]
            )
            for review in labeled
        ),
        "categories": dict(
            sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        "approved_labels": dict(
            sorted(labels.items(), key=lambda item: (-item[1], item[0]))
        ),
        "review_ids": [item["review_id"] for item in reviews],
        "sample_warning": "INSUFFICIENT_REVIEW_HISTORY"
        if len(labeled) < 5
        else "DESCRIPTIVE_ONLY",
        "disclaimer": "Counts are review occurrences, not independent trials or statistically significant tendencies. "
        "Multiple reviews of the same version are counted separately. " + DISCLAIMER,
    }


def format_review(report: dict[str, Any]) -> str:
    return canonical_json(report)

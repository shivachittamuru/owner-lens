"""Layered immutable attribution: arithmetic and reviewed explanations, never skill."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID, uuid4

from owner_lens.calibration import _pair
from owner_lens.changes import _date, _strings, _time
from owner_lens.decisions import Confidence
from owner_lens.mistakes import (
    MATERIAL_ERRORS,
    NUMERICAL_TOLERANCE,
    _context,
    _links,
    _process,
    _references_at,
)
from owner_lens.mistakes import (
    read_review as read_mistake_review,
)
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import SCENARIO_METRICS
from owner_lens.persistence import SqliteStore
from owner_lens.position_sizing import canonical_json
from owner_lens.underwriting import _object, _policy_number, _text

MODEL_VERSION = "layered-attribution-v1"
DISCLAIMER = (
    "Descriptive ATTRIBUTION, not skill, luck, persistent alpha, optimal sizing or causation. "
    "Process consistency does not establish that process caused returns. "
    "Price-only arithmetic excludes dividends, fees and taxes. Shadow/sizing proposals are not executions."
)
AUDIT_CODES = (
    "SUPPORTING_EVIDENCE_VERIFIED",
    "DISCONFIRMING_EVIDENCE_PRESENT",
    "DISCONFIRMING_EVIDENCE_CONSIDERED",
    "VARIANT_VIEW_DOCUMENTED",
    "CHALLENGER_QUESTIONS",
    "HURDLE_CONSISTENCY",
    "SIZING_WITHIN_POLICY",
    "REUNDERWRITING_PERFORMED",
)


class AttributionError(ValueError):
    """Attribution identity, evidence or authority is invalid."""


def _reviewed(
    data: Any, label: str, fields: set[str], cutoff: datetime
) -> dict[str, Any]:
    required = fields | {"rationale", "evidence_references", "investor_reviewed"}
    obj = dict(_object(data, label, required, required))
    if obj["investor_reviewed"] is not True:
        raise AttributionError(f"{label} requires explicit investor_reviewed: true.")
    obj["rationale"] = _text(obj["rationale"], f"{label} rationale")
    obj["evidence_references"] = _references_at(obj["evidence_references"], cutoff)
    if not any(item["title"] or item["uri"] for item in obj["evidence_references"]):
        raise AttributionError(f"{label} requires evidence references.")
    return obj


def _process_layer(
    context: dict[str, Any], audits: Any, cutoff: datetime
) -> dict[str, Any]:
    if not isinstance(audits, list):
        raise AttributionError("process_reviews must be an explicit list.")
    checks = _process(context)
    checks.insert(
        2,
        {
            "code": "DISCONFIRMING_EVIDENCE_CONSIDERED",
            "status": "UNRESOLVED",
            "question": "Was disconfirming evidence considered, not merely present?",
            "detail": "Requires investor-reviewed audit evidence.",
            "category": "CALCULATION",
        },
    )
    by_code = {item["code"]: item for item in checks}
    seen = set()
    parsed = []
    for raw in audits:
        audit = _reviewed(
            raw, "process review", {"code", "status", "performed_at"}, cutoff
        )
        code = audit["code"]
        if not isinstance(code, str) or code not in AUDIT_CODES or code in seen:
            raise AttributionError("Unknown or duplicate process check code.")
        if audit["status"] not in (
            "SATISFIED",
            "EXCEPTION",
            "UNRESOLVED",
            "NOT_APPLICABLE",
        ):
            raise AttributionError("Invalid process-review status.")
        performed = _time(audit["performed_at"], "process performed_at")
        if performed > cutoff:
            raise AttributionError("Process evidence cannot follow attribution cutoff.")
        _references_at(audit["evidence_references"], performed)
        decision = context["decision"]
        if (
            decision
            and code not in ("REUNDERWRITING_PERFORMED", "SIZING_WITHIN_POLICY")
            and performed > _time(decision["decision_at"], "decision_at")
        ):
            raise AttributionError(
                "Decision-time process completion cannot be supplied by later work."
            )
        check = by_code[code]
        if check["status"] == "EXCEPTION" and audit["status"] != "EXCEPTION":
            raise AttributionError(
                "Investor audit cannot erase a documented mechanical exception."
            )
        check["investor_review"] = audit
        check["status"] = audit["status"]
        parsed.append(audit)
        seen.add(code)
    statuses = {item["status"] for item in checks}
    return {
        "status": "PROCESS_EXCEPTIONS"
        if "EXCEPTION" in statuses
        else "PROCESS_COMPLIANT"
        if statuses <= {"SATISFIED", "NOT_APPLICABLE"}
        else "PROCESS_UNRESOLVED",
        "checks": checks,
        "investor_reviews": sorted(parsed, key=lambda item: item["code"]),
        "category": "CALCULATION",
        "note": "Mechanical checks plus explicit investor audit judgments; no causal return inference.",
    }


def _forecast_layer(
    store: SqliteStore, context: dict[str, Any], ticker: str
) -> dict[str, Any]:
    forecast = context["forecast"]
    record = next(
        item
        for item in store.list_underwriting(ticker)
        if item.underwriting_id == forecast["underwriting_id"]
    )
    rows = []
    seen = set()
    for linked in context["outcomes"]:
        outcome = linked["report"]
        for fundamental in outcome["fundamental_outcomes"]:
            metric = fundamental["observed"]["forecast"]["id"]
            pair = _pair(record, forecast, outcome, metric, fundamental)
            status = (
                "NOT_MATURE"
                if pair["status"] == "INTERIM_ONLY"
                else "NOT_COMPARABLE"
                if pair["status"] in ("NOT_COMPARABLE", "NOT_ELIGIBLE")
                else "INSUFFICIENT_DATA"
            )
            if pair["status"] == "ELIGIBLE" and metric in MATERIAL_ERRORS:
                error = pair["forecast_error"]
                tolerance = MATERIAL_ERRORS[metric] + NUMERICAL_TOLERANCE
                status = (
                    "MISSED_LOW"
                    if error < -tolerance
                    else "MISSED_HIGH"
                    if error > tolerance
                    else "SUPPORTED"
                )
            rows.append(
                {
                    **pair,
                    "status": status,
                    "eligibility": pair["status"],
                    "category": "CALCULATION",
                }
            )
            if fundamental["observed"]["forecast"]["kind"] == "SCENARIO":
                seen.add(metric)
        pair = _pair(record, forecast, outcome, "market_price", None)
        rows.append(
            {
                **pair,
                "status": (
                    "MISSED_LOW"
                    if pair.get("comparison_status") == "BELOW_BEAR"
                    else "MISSED_HIGH"
                    if pair.get("comparison_status") == "ABOVE_BULL"
                    else "SUPPORTED"
                    if pair.get("comparison_status") == "NEAR_BASE"
                    else "NOT_COMPARABLE"
                )
                if pair["status"] == "ELIGIBLE"
                else "NOT_MATURE"
                if pair["status"] == "INTERIM_ONLY"
                else "NOT_COMPARABLE"
                if pair["status"] == "NOT_COMPARABLE"
                else "INSUFFICIENT_DATA",
                "eligibility": pair["status"],
                "category": "CALCULATION",
                "note": "Terminal price outside anchors is MISSED_LOW/HIGH, numerical Base match SUPPORTED; between-anchor regions remain ambiguous/NOT_COMPARABLE. Not a scenario winner.",
            }
        )
    for metric in SCENARIO_METRICS:
        if metric not in seen:
            rows.append(
                {
                    "metric": metric,
                    "status": "INSUFFICIENT_DATA",
                    "observation_id": None,
                    "reason": "No selected measurement; no observation manufactured.",
                    "category": "CALCULATION",
                }
            )
    if not context["outcomes"]:
        rows.append(
            {
                "metric": "market_price",
                "status": "INSUFFICIENT_DATA",
                "observation_id": None,
                "category": "CALCULATION",
            }
        )
    calibration = context["calibration"]
    return {
        "forecasts": rows,
        "probability_calibration": calibration["probability_calibration"]
        if calibration
        else None,
        "probability_status": calibration["probability_calibration"]["status"]
        if calibration
        else "INSUFFICIENT_DATA",
        "direction_definition": "MISSED_LOW/HIGH means realized minus frozen Base is negative/positive, not economic desirability.",
        "rules": {
            "material_errors": MATERIAL_ERRORS,
            "numerical_tolerance": NUMERICAL_TOLERANCE,
        },
        "category": "CALCULATION",
    }


def _decision_layer(
    context: dict[str, Any], review: Any, cutoff: datetime
) -> dict[str, Any]:
    decision = context["decision"]
    result: dict[str, Any] = {
        "status": "DECISION_CONTEXT_INCOMPLETE",
        "category": "CALCULATION",
        "action": decision["judgment"]["action"] if decision else None,
        "investor_framework_review": None,
        "reasons": [],
    }
    if review is not None:
        result["investor_framework_review"] = _reviewed(
            review, "decision framework review", {"basis"}, cutoff
        )
        if review["basis"] not in (
            "HURDLE",
            "EVIDENCE_INSUFFICIENT",
            "UNRESOLVED_RISK",
        ):
            raise AttributionError(
                "Decision review basis must be HURDLE, EVIDENCE_INSUFFICIENT or UNRESOLVED_RISK."
            )
    if decision is None:
        result["reasons"] = [
            "No exact decision selected; underwriting opinion is not an executed decision."
        ]
        return result
    chosen = decision["chosen"]["opportunity"]
    summary, quality = chosen["summary"], chosen["quality"]
    action = decision["judgment"]["action"]
    if action in ("BUY", "ADD"):
        result["status"] = (
            "CONSISTENT_WITH_RECORDED_FRAMEWORK"
            if summary["return_spread"] >= -NUMERICAL_TOLERANCE
            else "INCONSISTENT_WITH_RECORDED_FRAMEWORK"
        )
        result["reasons"].append(
            "BUY/ADD compared with its original frozen expected return and hurdle."
        )
        sizing = context["sizing"]
        if sizing and _time(sizing["created_at"], "sizing created_at") <= _time(
            decision["decision_at"], "decision_at"
        ):
            report = sizing["report"]
            if (
                report["proposed_target_weight"] is not None
                and report["proposed_target_weight"]
                > report["target_range"][1] + NUMERICAL_TOLERANCE
            ):
                result["status"] = "INCONSISTENT_WITH_RECORDED_FRAMEWORK"
                result["reasons"].append(
                    "Decision-linked proposal exceeded its explicit cap at decision time."
                )
    elif (
        action in ("WATCH", "PASS") and result["investor_framework_review"] is not None
    ):
        basis = result["investor_framework_review"]["basis"]
        if (
            basis == "HURDLE"
            and summary["return_spread"] < 0
            or basis == "EVIDENCE_INSUFFICIENT"
            and quality["missing_dimensions"]
            or basis == "UNRESOLVED_RISK"
            and quality["major_unresolved_questions"]
        ):
            result["status"] = "CONSISTENT_WITH_RECORDED_FRAMEWORK"
            result["reasons"].append(
                "Investor-reviewed decision basis is supported by original frozen context; prose was not machine interpreted."
            )
    if result["status"] == "DECISION_CONTEXT_INCOMPLETE":
        result["reasons"].append(
            "No encoded rule establishes consistency for this action/basis; no hindsight inference."
        )
    result["scope"] = (
        "Bounded recorded hurdle/policy consistency only, not overall investment or decision quality."
    )
    return result


def _market_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    forecast = context["forecast"]
    return [
        {
            "kind": "ACTUAL_DECISION_OUTCOME",
            "basis": "FROZEN_UNDERWRITING_MARKET_PRICE_ONLY",
            "observation_id": item["report"]["observation_id"],
            "start_date": forecast["valuation"]["market_date"],
            "end_date": item["report"]["observation"]["observation_date"],
            "price_return": item["report"]["market_outcome"]["total_price_return"],
            "annualized_price_return": item["report"]["market_outcome"][
                "annualized_price_return"
            ],
            "category": "CALCULATION",
            "execution_established": False,
        }
        for item in context["outcomes"]
    ]


def _portfolio_layer(
    context: dict[str, Any], position: Any, cutoff: datetime
) -> dict[str, Any]:
    sizing = context["sizing"]
    decision = context["decision"]
    action = decision["judgment"]["action"] if decision else None
    markets = _market_rows(context)
    policy_check = next(
        item for item in _process(context) if item["code"] == "SIZING_WITHIN_POLICY"
    )
    result: dict[str, Any] = {
        "status": "HYPOTHETICAL_ONLY"
        if sizing or decision and decision["shadows"]
        else "INSUFFICIENT_DATA",
        "policy_status": "POLICY_EXCEPTIONS"
        if policy_check["status"] == "EXCEPTION"
        else "WITHIN_POLICY"
        if policy_check["status"] == "SATISFIED"
        else "POLICY_UNRESOLVED",
        "policy_basis": "SELECTED_SIZING_PROPOSAL_ONLY; not proof of actual executed policy compliance.",
        "actual_policy_status": "POLICY_UNRESOLVED",
        "actual_capital_outcome": "NOT_DEPLOYED"
        if action in ("WATCH", "PASS")
        else "NOT_ESTABLISHED",
        "capital_basis": "Recorded WATCH/PASS, no selected execution; not proof of account cash balance or cash return.",
        "actual_position_evidence": None,
        "position_contribution": None,
        "portfolio_contribution": None,
        "market_outcomes": markets,
        "hypothetical_contributions": [],
        "category": "CALCULATION",
    }
    if sizing:
        report = sizing["report"]
        weight = report["proposed_target_weight"]
        result["exposure_context"] = {
            key: report[key]
            for key in (
                "current_weight",
                "cash_weight",
                "thesis_weights",
                "sector_weights",
                "warnings",
                "missing_dimensions",
            )
        }
        result["hypothetical_contributions"] = [
            {
                "observation_id": row["observation_id"],
                "assumed_constant_weight": weight,
                "contribution": weight * row["price_return"]
                if weight is not None and row["price_return"] is not None
                else None,
                "basis": "PROPOSED_CONSTANT_START_WEIGHT_TIMES_PRICE_RETURN; not actual portfolio performance",
            }
            for row in markets
        ]
    if position is None:
        return result
    if decision is None:
        raise AttributionError(
            "Actual position evidence requires an exact decision link."
        )
    evidence = _reviewed(
        position,
        "actual position evidence",
        {
            "category",
            "units",
            "entry_price",
            "entry_at",
            "currency",
            "starting_portfolio_value",
            "end_observation_id",
            "constant_units_no_flows",
            "basis",
        },
        cutoff,
    )
    if (
        evidence["category"] != "FACT"
        or evidence["constant_units_no_flows"] is not True
        or evidence["basis"] != "EOD_CLOSE_SAME_SHARE_BASIS"
    ):
        raise AttributionError(
            "Actual position requires verified FACT, same-share price basis and explicit constant-units/no-flows attestation."
        )
    for field in ("units", "entry_price", "starting_portfolio_value"):
        evidence[field] = _policy_number(evidence[field], field)
        if evidence[field] <= 0:
            raise AttributionError(
                "Actual units, entry price and starting portfolio value must be positive."
            )
    entry = _time(evidence["entry_at"], "entry_at")
    if entry < _time(decision["decision_at"], "decision_at") or entry > cutoff:
        raise AttributionError(
            "Execution evidence must follow the linked decision and precede cutoff."
        )
    outcome = next(
        (
            item["report"]
            for item in context["outcomes"]
            if item["report"]["observation_id"] == evidence["end_observation_id"]
        ),
        None,
    )
    if outcome is None:
        raise AttributionError(
            "Actual position must use a selected exact outcome observation."
        )
    market = outcome["observation"]["market"]
    if (
        market is None
        or outcome["market_outcome"]["total_price_return"] is None
        or evidence["currency"] != market["currency"]
        or entry.date() >= _date(outcome["observation"]["observation_date"], "end date")
    ):
        raise AttributionError(
            "Actual position needs comparable currency/share-basis evidence and a later end date."
        )
    cost = evidence["units"] * evidence["entry_price"]
    if cost > evidence["starting_portfolio_value"] + NUMERICAL_TOLERANCE:
        raise AttributionError(
            "Unlevered position cost cannot exceed starting portfolio value."
        )
    gain = evidence["units"] * (market["price"] - evidence["entry_price"])
    result.update(
        status="ACTUAL_POSITION_MARK_TO_MARKET",
        actual_capital_outcome="DEPLOYED",
        actual_position_evidence=evidence,
        position_contribution=gain,
        portfolio_contribution=gain / evidence["starting_portfolio_value"],
        position_price_return=market["price"] / evidence["entry_price"] - 1,
        start_weight=cost / evidence["starting_portfolio_value"],
        start_date=entry.date().isoformat(),
        end_date=outcome["observation"]["observation_date"],
        currency=evidence["currency"],
        capital_basis="Investor-verified opening execution/position evidence; constant units, no flows. "
        "Mark-to-market gain, not realized P&L or full portfolio return; excludes dividends/costs/taxes.",
    )
    if sizing:
        report = sizing["report"]
        if (
            _time(sizing["created_at"], "sizing created_at") <= entry
            and report["portfolio"]["as_of_date"] == entry.date().isoformat()
            and not report["missing_dimensions"]
        ):
            result["actual_policy_status"] = (
                "POLICY_EXCEPTIONS"
                if result["start_weight"]
                > report["target_range"][1] + NUMERICAL_TOLERANCE
                else "WITHIN_POLICY"
            )
            result["actual_policy_basis"] = (
                "Opening actual weight vs contemporaneous explicit cap only; no optimal-size or subsequent exposure inference."
            )
    return result


def _comparisons(
    context: dict[str, Any],
    data: Any,
    cutoff: datetime,
    portfolio: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise AttributionError("relative_outcomes must be an explicit list.")
    decision = context["decision"]
    rows = []
    seen = set()
    for raw in data:
        if decision is None:
            raise AttributionError(
                "Relative outcomes require an exact decision with a recorded shadow."
            )
        obj = _reviewed(
            raw,
            "relative outcome evidence",
            {
                "shadow_id",
                "observation_id",
                "start_date",
                "end_date",
                "start_price",
                "end_price",
                "currency",
                "basis",
                "return_basis",
            },
            cutoff,
        )
        shadow = next(
            (
                item
                for item in decision["shadows"]
                if item["shadow_id"] == obj["shadow_id"]
            ),
            None,
        )
        if shadow is None or shadow["role"] not in (
            "BENCHMARK",
            "BEST_ALTERNATIVE",
            "PASS_CANDIDATE",
        ):
            raise AttributionError(
                "Comparison must reference a recorded benchmark/alternative shadow, never an invented best alternative."
            )
        key = (obj["shadow_id"], obj["observation_id"])
        if key in seen:
            raise AttributionError("Duplicate shadow/observation comparison.")
        seen.add(key)
        outcome = next(
            (
                item["report"]
                for item in context["outcomes"]
                if item["report"]["observation_id"] == obj["observation_id"]
            ),
            None,
        )
        if outcome is None:
            raise AttributionError(
                "Relative comparison must link to a selected exact observation."
            )
        for field in ("start_price", "end_price"):
            obj[field] = _policy_number(obj[field], field)
        if obj["start_price"] <= 0 or obj["end_price"] < 0:
            raise AttributionError(
                "Comparison prices require positive start and nonnegative end."
            )
        start, end = (
            _date(obj["start_date"], "comparison start"),
            _date(obj["end_date"], "comparison end"),
        )
        if obj["return_basis"] not in ("UNDERWRITING_MARKET", "ACTUAL_POSITION"):
            raise AttributionError(
                "return_basis must be UNDERWRITING_MARKET or ACTUAL_POSITION."
            )
        actual = obj["return_basis"] == "ACTUAL_POSITION"
        if actual and portfolio["status"] != "ACTUAL_POSITION_MARK_TO_MARKET":
            raise AttributionError(
                "Actual relative outcome requires verified actual position evidence."
            )
        frozen_start = (
            portfolio["start_date"]
            if actual
            else context["forecast"]["valuation"]["market_date"]
        )
        if (
            start.isoformat() != frozen_start
            or end.isoformat() != outcome["observation"]["observation_date"]
            or start >= end
            or end > cutoff.date()
        ):
            raise AttributionError(
                "Relative outcomes require identical start/end measurement dates, not mixed horizons."
            )
        if (
            obj["currency"] != context["forecast"]["valuation"]["price_currency"]
            or obj["basis"] != "EOD_CLOSE_SAME_SHARE_BASIS"
        ):
            raise AttributionError(
                "Relative outcomes require compatible currency and price/share basis; no FX/split inference."
            )
        if (
            not actual
            and shadow["frozen_price"] is not None
            and (
                abs(obj["start_price"] - shadow["frozen_price"]) > NUMERICAL_TOLERANCE
                or obj["start_date"] != shadow["market_date"]
                or obj["currency"] != shadow["currency"]
            )
        ):
            raise AttributionError(
                "Alternative start must match its exact recorded shadow price/date/currency."
            )
        if shadow["frozen_price"] is None and shadow["role"] != "BENCHMARK":
            raise AttributionError(
                "Alternative has no frozen start; cannot manufacture its entry."
            )
        price_return = obj["end_price"] / obj["start_price"] - 1
        if actual and (
            portfolio["end_date"] != obj["end_date"]
            or portfolio["actual_position_evidence"]["end_observation_id"]
            != obj["observation_id"]
        ):
            raise AttributionError(
                "Actual relative outcome must use the exact position end date."
            )
        chosen_return = (
            portfolio["position_price_return"]
            if actual
            else outcome["market_outcome"]["total_price_return"]
        )
        rows.append(
            {
                "kind": "BENCHMARK_OUTCOME"
                if shadow["role"] == "BENCHMARK"
                else "SHADOW_ALTERNATIVE_OUTCOME",
                "semantic_role": "RELATIVE_OUTCOME",
                "category": "CALCULATION",
                "shadow": shadow,
                "evidence": obj,
                "price_return": price_return,
                "chosen_market_return": chosen_return,
                "difference": chosen_return - price_return
                if chosen_return is not None
                else None,
                "return_basis": obj["return_basis"],
                "basis": "Aligned price-return difference only, not persistent alpha or skill.",
                "benchmark_start_basis": "MANUALLY_VERIFIED_COMPARISON_START"
                if shadow["frozen_price"] is None or actual
                else "FROZEN_SHADOW_START",
            }
        )
    return rows


def _external(data: Any, cutoff: datetime) -> dict[str, Any]:
    obj = _reviewed(
        data, "external contribution review", {"status", "contributors"}, cutoff
    )
    if obj["status"] not in (
        "EXTERNAL_CONTRIBUTOR_RECORDED",
        "NO_EXTERNAL_CONTRIBUTOR_RECORDED",
        "UNRESOLVED",
    ):
        raise AttributionError("Invalid external-contribution status.")
    if not isinstance(obj["contributors"], list):
        raise AttributionError("External contributors must be a list.")
    contributors = []
    for raw in obj["contributors"]:
        contributor = _reviewed(
            raw, "external contributor", {"kind", "statement"}, cutoff
        )
        contributor["kind"] = _text(contributor["kind"], "external kind")
        contributor["statement"] = _text(contributor["statement"], "external statement")
        contributor["category"] = "JUDGMENT"
        contributors.append(contributor)
    if bool(contributors) != (obj["status"] == "EXTERNAL_CONTRIBUTOR_RECORDED"):
        raise AttributionError(
            "Recorded external status requires contributors; unresolved/none cannot imply a contributor."
        )
    return {**obj, "contributors": contributors, "category": "JUDGMENT"}


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
        "as_of_date",
        "category",
        "links",
        "reviewer",
        "interpretation",
        "confidence",
        "investor_reviewed",
        "evidence_references",
        "process_reviews",
        "decision_framework_review",
        "actual_position",
        "relative_outcomes",
        "external_review",
        "unresolved_questions",
    }
    obj = _object(data, "attribution review", fields, fields)
    recorded = _time(recorded_at, "recorded_at")
    day = _date(obj["as_of_date"], "as_of_date")
    if (
        day > recorded.date()
        or obj["category"] != "JUDGMENT"
        or obj["investor_reviewed"] is not True
    ):
        raise AttributionError(
            "Attribution requires nonfuture as-of, JUDGMENT and explicit investor review."
        )
    cutoff = min(recorded, datetime.combine(day, time.max, UTC))
    raw_links = _object(
        obj["links"],
        "attribution links",
        {
            "decision_id",
            "sizing_analysis_id",
            "observation_ids",
            "change_event_ids",
            "calibration_report_id",
            "mistake_review_id",
        },
        set(),
    )
    links = {
        **_links(
            {
                key: value
                for key, value in raw_links.items()
                if key != "mistake_review_id"
            }
        ),
        "mistake_review_id": raw_links.get("mistake_review_id"),
    }
    context = _context(
        store,
        selection,
        {key: value for key, value in links.items() if key != "mistake_review_id"},
        cutoff,
    )
    mistake = None
    if links["mistake_review_id"] is not None:
        _text(links["mistake_review_id"], "mistake_review_id")
        mistake = read_mistake_review(store, links["mistake_review_id"])
        if (
            mistake["underwriting"]["underwriting_id"]
            != context["forecast"]["underwriting_id"]
        ):
            raise AttributionError("Mistake review must link to exact underwriting.")
        if _time(mistake["recorded_at"], "mistake recorded_at") > cutoff:
            raise AttributionError("Mistake review unavailable by attribution cutoff.")
    context["mistake_review"] = (
        {"semantic_role": "MISTAKE_REVIEW", "review": mistake} if mistake else None
    )
    process = _process_layer(context, obj["process_reviews"], cutoff)
    forecasts = _forecast_layer(store, context, selection.ticker)
    decision = _decision_layer(context, obj["decision_framework_review"], cutoff)
    portfolio = _portfolio_layer(context, obj["actual_position"], cutoff)
    relative = _comparisons(context, obj["relative_outcomes"], cutoff, portfolio)
    external = _external(obj["external_review"], cutoff)
    refs = _references_at(obj["evidence_references"], cutoff)
    if not any(item["title"] or item["uri"] for item in refs):
        raise AttributionError(
            "Attribution interpretation requires evidence references."
        )
    markets = portfolio["market_outcomes"]
    returns = [row["price_return"] for row in markets]
    market_outcome = (
        "FAVORABLE"
        if returns and all(value is not None and value > 0 for value in returns)
        else "ADVERSE"
        if returns and all(value is not None and value < 0 for value in returns)
        else "UNRESOLVED"
    )
    actual_return = portfolio.get("position_price_return")
    outcome_basis = (
        "ACTUAL_POSITION_PRICE_ONLY"
        if actual_return is not None
        else "FROZEN_UNDERWRITING_MARKET_NOT_CAPITAL"
    )
    outcome = (
        (
            "FAVORABLE"
            if actual_return > 0
            else "ADVERSE"
            if actual_return < 0
            else "UNRESOLVED"
        )
        if actual_return is not None
        else market_outcome
    )
    judgment = {
        **obj,
        "links": links,
        "reviewer": _text(obj["reviewer"], "reviewer"),
        "interpretation": _text(obj["interpretation"], "interpretation"),
        "confidence": Confidence(obj["confidence"]).value,
        "evidence_references": refs,
        "process_reviews": process["investor_reviews"],
        "unresolved_questions": _strings(
            obj["unresolved_questions"], "unresolved_questions"
        ),
    }
    forecast = context["forecast"]
    return {
        "review_id": review_id,
        "recorded_at": recorded.isoformat(),
        "as_of_date": day.isoformat(),
        "model_version": MODEL_VERSION,
        "category": "JUDGMENT",
        "semantic_role": "ATTRIBUTION",
        "ticker": forecast["ticker"],
        "security_id": forecast["security_id"],
        "underwriting": {
            key: forecast[key] for key in ("underwriting_id", "version", "content_hash")
        },
        "judgment": judgment,
        "context": context,
        "process": process,
        "forecast": forecasts,
        "decision": decision,
        "portfolio": portfolio,
        "external": external,
        "relative_outcomes": relative,
        "outcome": outcome,
        "outcome_basis": outcome_basis,
        "market_outcome": market_outcome,
        "summary": {
            "process": process["status"],
            "decision": decision["status"],
            "sizing": portfolio["policy_status"],
            "capital": portfolio["status"],
            "external": external["status"],
            "outcome": outcome,
            "outcome_basis": outcome_basis,
            "interpretation": judgment["interpretation"],
        },
        "disclaimer": DISCLAIMER,
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
        raise AttributionError("Recording time requires timezone.")
    review = build_review(
        store,
        selection,
        data,
        review_id=str(uuid4()),
        recorded_at=clock.astimezone(UTC).isoformat(),
    )
    store.save_attribution_review(canonical_json(review))
    return review


def read_review(store: SqliteStore, review_id: str) -> dict[str, Any]:
    return json.loads(store.get_attribution_review(review_id))


def review_history(store: SqliteStore, ticker: str) -> list[dict[str, Any]]:
    records = store.list_underwriting(ticker)
    if not records:
        raise AttributionError(f"No underwriting exists for {ticker}.")
    return [
        json.loads(payload)
        for payload in store.list_attribution_reviews()
        if json.loads(payload)["security_id"] == records[0].security_id
    ]


def review_summary(store: SqliteStore) -> dict[str, Any]:
    reviews = [json.loads(payload) for payload in store.list_attribution_reviews()]
    # Prefer the earliest review with mature evidence; early unresolved reviews remain in history.
    cases: dict[str, dict[str, Any]] = {}
    for review in reviews:
        key = review["underwriting"]["underwriting_id"]
        mature = any(
            item.get("eligibility") == "ELIGIBLE"
            for item in review["forecast"]["forecasts"]
        )
        previous = cases.get(key)
        if previous is None or (
            mature
            and not any(
                item.get("eligibility") == "ELIGIBLE"
                for item in previous["forecast"]["forecasts"]
            )
        ):
            cases[key] = review
    rows = list(cases.values())
    process_known = [
        row for row in rows if row["process"]["status"] != "PROCESS_UNRESOLVED"
    ]
    benchmark = []
    for review in rows:
        mature_ids = {
            item["observation_id"]
            for item in review["forecast"]["forecasts"]
            if item["metric"] == "market_price"
            and item.get("eligibility") == "ELIGIBLE"
        }
        aligned = [
            item
            for item in review["relative_outcomes"]
            if item["kind"] == "BENCHMARK_OUTCOME"
            and item["difference"] is not None
            and item["return_basis"] == "UNDERWRITING_MARKET"
            and item["evidence"]["observation_id"] in mature_ids
        ]
        if aligned:
            timestamps = {
                linked["report"]["observation_id"]: _time(
                    linked["report"]["recorded_at"], "outcome recorded_at"
                )
                for linked in review["context"]["outcomes"]
            }
            earliest = min(
                aligned,
                key=lambda item: (
                    timestamps[item["evidence"]["observation_id"]],
                    item["evidence"]["observation_id"],
                    item["shadow"]["shadow_id"],
                ),
            )
            benchmark.append(earliest["difference"])
    misses: Counter[str] = Counter()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    missing_cohorts: Counter[str] = Counter()
    for row in rows:
        misses.update(
            {
                item["metric"] + ":" + item["status"]
                for item in row["forecast"]["forecasts"]
                if item["status"] in ("MISSED_LOW", "MISSED_HIGH")
            }
        )
        manual = row["context"]["forecast"]["snapshot"]["manual"]
        frozen_context = (
            row["context"]["forecast"]["snapshot"]["evidence"].get("feature7_context")
            or {}
        )
        for dimension, value in (
            ("decision_type", row["decision"]["action"]),
            ("setup_type", frozen_context.get("setup_type")),
            (
                "variant_view",
                "PRESENT" if manual.get("variant_rationales") else "ABSENT",
            ),
        ):
            if value is not None:
                groups[(dimension, value)].append(row)
            else:
                missing_cohorts[dimension] += 1
    return {
        "model_version": MODEL_VERSION,
        "category": "CALCULATION",
        "review_count": len(reviews),
        "case_count": len(rows),
        "review_ids": [row["review_id"] for row in rows],
        "sampling": "Earliest mature review per exact underwriting, otherwise earliest review; one earliest selected terminal benchmark comparison per case. Overlapping versions are not independent.",
        "sample_warning": "INSUFFICIENT_ATTRIBUTION_HISTORY"
        if len(rows) < 5
        else "DESCRIPTIVE_ONLY",
        "process_resolved_count": len(process_known),
        "process_compliance_rate": sum(
            row["process"]["status"] == "PROCESS_COMPLIANT" for row in process_known
        )
        / len(process_known)
        if len(process_known) >= 5
        else None,
        "forecast_misses": dict(sorted(misses.items())),
        "benchmark_comparison_count": len(benchmark),
        "benchmark_basis": "5Y terminal UNDERWRITING_MARKET price-return differences only; actual returns and interim horizons are not pooled.",
        "average_relative_market_outcome": math.fsum(benchmark) / len(benchmark)
        if len(benchmark) >= 5
        else None,
        "sizing_policy_exceptions": sum(
            row["portfolio"]["policy_status"] == "POLICY_EXCEPTIONS" for row in rows
        ),
        "actual_sizing_policy_exceptions": sum(
            row["portfolio"]["actual_policy_status"] == "POLICY_EXCEPTIONS"
            for row in rows
        ),
        "missing_cohort_dimensions": dict(sorted(missing_cohorts.items())),
        "cohorts": [
            {
                "dimension": dimension,
                "value": value,
                "case_count": len(items),
                "sample_warning": "INSUFFICIENT_ATTRIBUTION_HISTORY"
                if len(items) < 5
                else "DESCRIPTIVE_ONLY",
                "outcomes": {
                    basis: dict(
                        sorted(
                            Counter(
                                item["outcome"]
                                for item in items
                                if item["outcome_basis"] == basis
                            ).items()
                        )
                    )
                    for basis in sorted({item["outcome_basis"] for item in items})
                },
            }
            for (dimension, value), items in sorted(groups.items())
        ],
        "disclaimer": "Counts are descriptive, not statistical significance or causal evidence. "
        + DISCLAIMER,
    }

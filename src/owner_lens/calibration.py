"""Reproducible, sample-guarded calibration of immutable forecast/outcome pairs."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, time
from statistics import median
from typing import Any

from owner_lens.changes import _date, _time
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import (
    MODEL_VERSION as OUTCOME_VERSION,
)
from owner_lens.outcomes import (
    SCENARIO_METRICS,
    frozen_forecast,
    parse_observation,
    range_comparison,
)
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.records import UnderwritingRecord
from owner_lens.position_sizing import canonical_json

MODEL_VERSION = "forecast-calibration-v1"
MIN_HISTORY = 5
AVAILABLE_HISTORY = 20
MIN_BUCKET = 5
SCENARIOS = ("BEAR", "BASE", "BULL")
RANGE_STATES = {
    "BELOW_BEAR",
    "WITHIN_BEAR_BASE",
    "NEAR_BASE",
    "WITHIN_BASE_BULL",
    "ABOVE_BULL",
}
DISCLAIMER = (
    "Descriptive forecast calibration only, not skill, luck, mistake, investment or decision quality. "
    "Versions and companies may overlap; sample counts do not establish independence. "
    "Scenario probabilities were assigned to narratives, not explicit price bins; fixed region mapping "
    "is an operational diagnostic. Unambiguous-only frequencies/scores are selection-conditioned "
    "and must not be generalized to ambiguous or excluded outcomes."
)


class CalibrationError(ValueError):
    """Calibration inputs or report identity are invalid."""


def sample_status(count: int) -> str:
    if count < MIN_HISTORY:
        return "INSUFFICIENT_HISTORY_FOR_CALIBRATION"
    return "EARLY_SIGNAL_ONLY" if count < AVAILABLE_HISTORY else "CALIBRATION_AVAILABLE"


def realized_region(value: float, scenarios: dict[str, float]) -> dict[str, Any]:
    comparison = range_comparison(value, scenarios)
    bear, base, bull = (scenarios[name] for name in SCENARIOS)
    tolerance = 1e-9 * max(1.0, abs(base))
    region = None
    if bear + 2 * tolerance < base and base + 2 * tolerance < bull:
        if value <= bear + tolerance:
            region = "BEAR"
        elif abs(value - base) <= tolerance:
            region = "BASE"
        elif value >= bull - tolerance:
            region = "BULL"
    return {
        "comparison_status": comparison["status"],
        "realized_region": region,
        "reason": "Fixed disjoint terminal-price region."
        if region
        else "AMBIGUOUS_SCENARIO_REGION: between scenario anchors or non-distinct/unordered anchors.",
    }


def brier_score(probabilities: dict[str, float], region: str) -> float:
    if set(probabilities) != set(SCENARIOS) or region not in SCENARIOS:
        raise CalibrationError(
            "Brier requires exactly BEAR/BASE/BULL and one unambiguous realized class."
        )
    if any(
        isinstance(p, bool)
        or not isinstance(p, (int, float))
        or not math.isfinite(p)
        or not 0 <= p <= 1
        for p in probabilities.values()
    ):
        raise CalibrationError("Probabilities must be finite values in [0,1].")
    if abs(math.fsum(probabilities.values()) - 1) > 1e-9:
        raise CalibrationError("Probabilities must sum to 1; never normalized.")
    return math.fsum(
        (probabilities[name] - int(name == region)) ** 2 for name in SCENARIOS
    )


def _probabilities(forecast: dict[str, Any]) -> dict[str, float]:
    distribution = forecast["snapshot"]["manual"].get("probability_distribution")
    if distribution is None:
        raise CalibrationError("Required frozen scenario probabilities missing.")
    entries = distribution["scenarios"]
    probabilities = {item["name"]: item["probability"] for item in entries}
    if len(entries) != 3:
        raise CalibrationError(
            "Required frozen scenario probabilities missing/duplicated."
        )
    brier_score(probabilities, "BASE")
    return probabilities


def _dates(rows: list[dict[str, Any]]) -> dict[str, str | None]:
    dates = [item["observation_date"] for item in rows]
    return {
        "start": min(dates) if dates else None,
        "end": max(dates) if dates else None,
    }


def _probability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market = [item for item in rows if item["metric"] == "market_price"]
    scored = [item for item in market if item["realized_region"] is not None]
    count = len(scored)
    summary: dict[str, Any] = {
        "status": sample_status(count),
        "eligible_sample_count": count,
        "comparable_market_count": len(market),
        "ambiguous_count": len(market) - count,
        "date_range": _dates(scored),
        "horizon_type": "5Y_TERMINAL_MARKET",
        "scenario_frequency": [],
        "mean_brier": None,
        "brier_definition": "SUM_3_CLASS_UNNORMALIZED_V1: sum((p_i - one_hot_i)^2), range [0,2]; no division by 3 or 2.",
        "raw_scores": [
            {
                key: item[key]
                for key in (
                    "underwriting",
                    "observation_id",
                    "probabilities",
                    "realized_region",
                    "brier",
                )
            }
            for item in scored
        ],
        "excluded_from_scoring": [
            {
                "underwriting": item["underwriting"],
                "observation_id": item["observation_id"],
                "reason": item["region_reason"],
            }
            for item in market
            if item["realized_region"] is None
        ],
        "buckets": [],
        "suppressed_bucket_count": 0,
    }
    if count < MIN_HISTORY:
        return summary
    summary["mean_brier"] = math.fsum(item["brier"] for item in scored) / count
    summary["scenario_frequency"] = [
        {
            "scenario": name,
            "assigned_probability_average": math.fsum(
                item["probabilities"][name] for item in scored
            )
            / count,
            "observed_region_frequency": sum(
                item["realized_region"] == name for item in scored
            )
            / count,
            "sample_count": count,
        }
        for name in SCENARIOS
    ]
    for name in SCENARIOS:
        for index in range(5):
            bucket = [
                item
                for item in scored
                if min(int(item["probabilities"][name] * 5), 4) == index
            ]
            if len(bucket) < MIN_BUCKET:
                if bucket:
                    summary["suppressed_bucket_count"] += 1
                continue
            summary["buckets"].append(
                {
                    "scenario": name,
                    "lower": index / 5,
                    "upper": (index + 1) / 5,
                    "upper_inclusive": index == 4,
                    "sample_count": len(bucket),
                    "status": sample_status(len(bucket)),
                    "average_predicted_probability": math.fsum(
                        item["probabilities"][name] for item in bucket
                    )
                    / len(bucket),
                    "observed_frequency": sum(
                        item["realized_region"] == name for item in bucket
                    )
                    / len(bucket),
                }
            )
    return summary


def _continuous_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        if item["metric"] != "market_price":
            groups[item["metric"]].append(item)
    summaries = []
    for metric, items in sorted(groups.items()):
        errors = [item["forecast_error"] for item in items]
        count = len(errors)
        summary: dict[str, Any] = {
            "metric": metric,
            "unit": SCENARIO_METRICS[metric][0],
            "horizon_type": "5Y_FISCAL",
            "sample_count": count,
            "status": sample_status(count),
            "date_range": _dates(items),
            "mean_error": None,
            "median_error": None,
            "mean_absolute_error": None,
            "mean_error_pp": None,
            "directional_bias": None,
            "interpretation": None,
            "raw_errors": [
                {
                    key: item[key]
                    for key in (
                        "underwriting",
                        "observation_id",
                        "observed",
                        "base_forecast",
                        "forecast_error",
                    )
                }
                for item in items
            ],
        }
        if count >= MIN_HISTORY:
            mean = math.fsum(errors) / count
            bias = (
                "BASE_ABOVE_OBSERVED"
                if mean < -1e-9
                else "BASE_BELOW_OBSERVED"
                if mean > 1e-9
                else "NO_DIRECTIONAL_BIAS_DETECTED"
            )
            summary.update(
                mean_error=mean,
                median_error=median(errors),
                mean_absolute_error=math.fsum(abs(error) for error in errors) / count,
                mean_error_pp=mean * 100 if summary["unit"] == "ratio" else None,
                directional_bias=bias,
            )
            # Share dilution and terminal multiples do not have a universal optimistic direction.
            if count >= AVAILABLE_HISTORY:
                if metric in ("revenue_cagr", "fcf_margin_year5"):
                    summary["interpretation"] = (
                        "Base-case assumptions have tended to be optimistic (above observed)."
                        if mean < -1e-9
                        else "Base-case assumptions have tended to be pessimistic (below observed)."
                        if mean > 1e-9
                        else "No directional mean bias detected at the numerical tolerance."
                    )
                else:
                    summary["interpretation"] = (
                        "Direction describes the measured variable only, not economic desirability."
                    )
        summaries.append(summary)
    return summaries


def _cohorts(
    forecast: dict[str, Any], outcome: dict[str, Any]
) -> dict[str, str | None]:
    snapshot = forecast["snapshot"]
    context = snapshot["evidence"].get("feature7_context") or {}
    # Only use metadata actually frozen in this underwriting, never current universe enrichment.
    company = snapshot["evidence"].get("company") or {}
    measurement_dates = [outcome["observation"]["observation_date"]] + [
        item["period_end"]
        for item in outcome["observation"]["fundamentals"]
        if item["period_end"] is not None
    ]
    measurement_cutoff = datetime.combine(
        _date(min(measurement_dates), "measurement date"), time.min, UTC
    )
    decision_candidates = [
        item
        for item in outcome["record_context"]["decisions"]
        if _time(item["recorded_at"], "decision recorded_at")
        < _time(outcome["observation"]["observed_at"], "observed_at")
        and _time(item["decision_at"], "decision_at")
        < _time(outcome["observation"]["observed_at"], "observed_at")
        and _time(item["recorded_at"], "decision recorded_at") < measurement_cutoff
        and _time(item["decision_at"], "decision_at") < measurement_cutoff
    ]
    decision = min(
        decision_candidates,
        key=lambda item: (item["recorded_at"], item["decision_id"]),
        default=None,
    )
    return {
        "company": str(forecast["security_id"]),
        "setup_type": context.get("setup_type"),
        "sector": context.get("sector") or company.get("sector"),
        "industry": context.get("industry") or company.get("industry"),
        "forecast_horizon": "5Y",
        "decision_type": decision["judgment"]["action"] if decision else None,
        "variant_view": "PRESENT"
        if snapshot["manual"].get("variant_rationales")
        else "ABSENT",
    }


def _cohort_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        for dimension, value in item["cohorts"].items():
            if value is not None:
                groups[(dimension, value)].append(item)
    result = []
    for (dimension, value), items in sorted(groups.items()):
        count = len({item["underwriting"]["underwriting_id"] for item in items})
        result.append(
            {
                "dimension": dimension,
                "value": value,
                "eligible_sample_count": count,
                "status": sample_status(count),
                "suppressed": count < MIN_HISTORY,
                "probability": _probability_summary(items)
                if count >= MIN_HISTORY
                else None,
                "continuous": _continuous_summary(items)
                if count >= MIN_HISTORY
                else [],
                "date_range": _dates(items),
            }
        )
    return result


def _identity(record: UnderwritingRecord) -> dict[str, Any]:
    return {
        "underwriting_id": record.underwriting_id,
        "version": record.version,
        "content_hash": record.content_hash,
        "ticker": record.ticker,
        "security_id": record.security_id,
    }


def _pair(
    record: UnderwritingRecord,
    forecast: dict[str, Any],
    outcome: dict[str, Any],
    metric: str,
    fundamental: dict[str, Any] | None,
) -> dict[str, Any]:
    observation = outcome["observation"]
    pair: dict[str, Any] = {
        "underwriting": _identity(record),
        "observation_id": outcome["observation_id"],
        "observation_date": observation["observation_date"],
        "recorded_at": outcome["recorded_at"],
        "metric": metric,
        "horizon_type": "5Y",
        "status": "INSUFFICIENT_DATA",
        "reason": "No comparable observed value.",
        "cohorts": _cohorts(forecast, outcome),
        "probabilities": _probabilities(forecast),
    }
    if (
        fundamental is not None
        and fundamental["observed"]["forecast"]["kind"] != "SCENARIO"
    ):
        pair.update(
            status="NOT_ELIGIBLE",
            reason="No frozen scenario forecast/probabilities for a condition-only variable.",
        )
        return pair
    if metric == "market_price":
        comparison = outcome["market_outcome"]["comparison"]
        state = comparison["status"]
        pair["status"] = "INTERIM_ONLY" if state == "INTERIM_OBSERVATION" else state
        pair["reason"] = comparison["reason"]
        if state not in RANGE_STATES:
            return pair
        value = observation["market"]["price"]
        values = {
            item["assumptions"]["name"]: item["year5_value_per_share"]
            for item in forecast["valuation"]["scenarios"]
        }
        region = realized_region(value, values)
        pair.update(
            status="ELIGIBLE",
            reason="Comparable terminal market outcome.",
            comparison_status=state,
            observed=value,
            scenario_values=values,
            realized_region=region["realized_region"],
            region_reason=region["reason"],
            brier=brier_score(pair["probabilities"], region["realized_region"])
            if region["realized_region"]
            else None,
        )
        return pair
    if fundamental is None:
        return pair
    observed = fundamental["observed"]
    belief = fundamental["frozen_belief"]
    if observed["forecast"]["kind"] != "SCENARIO" or metric not in SCENARIO_METRICS:
        pair.update(
            status="NOT_ELIGIBLE",
            reason="No frozen scenario forecast/probabilities for a condition-only variable.",
        )
        return pair
    state = fundamental["status"]
    # Unordered metric anchors (e.g. share dilution) still support a continuous Base error.
    unit, basis = SCENARIO_METRICS[metric]
    aligned = (
        observed["value"] is not None
        and observed["observable"] == metric
        and observed["unit"] == unit
        and observed["basis"] == basis
        and observed["period_end"] is not None
        and observed["fiscal_year"] == forecast["valuation"]["latest_fiscal_year"] + 5
        and (
            basis != "FISCAL_CAGR"
            or observed["start_fiscal_year"]
            == forecast["valuation"]["latest_fiscal_year"]
        )
    )
    if not aligned:
        pair.update(
            status="INTERIM_ONLY"
            if state == "INTERIM_OBSERVATION"
            else state
            if state in ("NOT_COMPARABLE", "INSUFFICIENT_DATA")
            else "NOT_ELIGIBLE",
            reason=fundamental["reason"],
        )
        return pair
    base = belief["scenario_values"]["BASE"]
    pair.update(
        status="ELIGIBLE",
        reason="Comparable complete fiscal-horizon measurement.",
        observed=observed["value"],
        base_forecast=base,
        forecast_error=observed["value"] - base,
        unit=unit,
        comparison_status=state,
        realized_region=None,
        brier=None,
    )
    return pair


def build_report(
    store: SqliteStore, *, as_of: str, company: str | None = None
) -> dict[str, Any]:
    cutoff_date = _date(as_of, "as_of")
    cutoff = datetime.combine(cutoff_date, time.max, UTC)
    selected_company = (
        UnderwritingSelection(company.strip().upper(), 1).ticker if company else None
    )
    records = {
        item.underwriting_id: item
        for security in store.list_securities()
        for item in store.list_underwriting(security.symbol)
        if _time(item.created_at, "underwriting created_at") <= cutoff
        and _date(item.as_of_date, "underwriting as_of_date") <= cutoff_date
    }
    if selected_company is not None:
        matched = store.list_underwriting(selected_company)
        security_ids = {item.security_id for item in matched}
        records = {
            key: item
            for key, item in records.items()
            if item.security_id in security_ids
        }
    observations = [
        (item, json.loads(item.snapshot_json))
        for item in store.list_outcome_observations()
        if _time(item.recorded_at, "outcome recorded_at") <= cutoff
        and item.underwriting_id in records
    ]
    observations.sort(
        key=lambda item: (
            _time(item[0].recorded_at, "recorded_at"),
            item[1]["observation"]["observed_at"],
            item[0].observation_id,
        )
    )
    forecasts: dict[str, dict[str, Any]] = {}
    invalid: dict[str, str] = {}
    for key, record in sorted(records.items()):
        try:
            forecast = frozen_forecast(
                store, UnderwritingSelection(record.ticker, record.version)
            )
            _probabilities(forecast)
            forecasts[key] = forecast
        except ValueError as exc:
            invalid[key] = str(exc)
    candidates: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    covered: set[str] = set()
    for stored, outcome in observations:
        record = records[stored.underwriting_id]
        covered.add(record.underwriting_id)
        sources.append(
            {
                "observation_id": stored.observation_id,
                "content_hash": stored.content_hash,
                "underwriting": _identity(record),
            }
        )
        if record.underwriting_id in invalid:
            candidates.append(
                {
                    "underwriting": _identity(record),
                    "observation_id": stored.observation_id,
                    "metric": None,
                    "status": "NOT_ELIGIBLE",
                    "reason": invalid[record.underwriting_id],
                }
            )
            continue
        forecast = forecasts[record.underwriting_id]
        if outcome["model_version"] != OUTCOME_VERSION:
            candidates.append(
                {
                    "underwriting": _identity(record),
                    "observation_id": stored.observation_id,
                    "metric": None,
                    "status": "NOT_COMPARABLE",
                    "reason": "Unsupported outcome calculation version.",
                }
            )
            continue
        expected_identity = {
            key: forecast[key]
            for key in (
                "underwriting_id",
                "version",
                "content_hash",
                "as_of_date",
                "created_at",
            )
        }
        if outcome["underwriting"] != expected_identity or canonical_json(
            outcome["forecast"]
        ) != canonical_json(forecast):
            raise CalibrationError(
                "Outcome forecast identity/bytes differ from exact immutable underwriting."
            )
        # Revalidate availability and provenance without rebuilding or mutating the stored outcome.
        parse_observation(outcome["observation"], recorded_at=outcome["recorded_at"])
        if (
            _time(outcome["observation"]["observed_at"], "observed_at") > cutoff
            or _date(outcome["observation"]["observation_date"], "observation_date")
            > cutoff_date
        ):
            candidates.append(
                {
                    "underwriting": _identity(record),
                    "observation_id": stored.observation_id,
                    "metric": None,
                    "status": "NOT_ELIGIBLE",
                    "reason": "Outcome unavailable by report cutoff.",
                }
            )
            continue
        candidates.append(_pair(record, forecast, outcome, "market_price", None))
        for fundamental in outcome["fundamental_outcomes"]:
            metric = fundamental["observed"]["forecast"]["id"]
            candidates.append(_pair(record, forecast, outcome, metric, fundamental))
    for key, record in sorted(records.items()):
        if key not in covered:
            candidates.append(
                {
                    "underwriting": _identity(record),
                    "observation_id": None,
                    "metric": None,
                    "status": "NOT_ELIGIBLE" if key in invalid else "INSUFFICIENT_DATA",
                    "reason": invalid.get(
                        key, "NO_OUTCOME_OBSERVATION_AVAILABLE_BY_CUTOFF"
                    ),
                }
            )
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pair in candidates:
        if pair["status"] == "ELIGIBLE":
            pair_key = (pair["underwriting"]["underwriting_id"], pair["metric"])
            if pair_key in seen:
                pair.update(
                    status="NOT_ELIGIBLE",
                    reason="DUPLICATE_COMPLETED_PAIR: earliest eligible recorded observation retained.",
                )
            else:
                seen.add(pair_key)
                included.append(pair)
                continue
        excluded.append(pair)
    eligible_count = len({item["underwriting"]["underwriting_id"] for item in included})
    counts = Counter(item["status"] for item in excluded)
    forecast_dates = [
        records[item["underwriting"]["underwriting_id"]].as_of_date for item in included
    ]
    report: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "as_of_date": as_of,
        "company": selected_company,
        "category": "CALCULATION",
        "status": sample_status(eligible_count),
        "rules": {
            "minimum_history": MIN_HISTORY,
            "available_history": AVAILABLE_HISTORY,
            "minimum_bucket": MIN_BUCKET,
            "horizon": "5Y only; actual terminal/fiscal alignment from Feature 10A, not declared observation label.",
            "sampling": "At most one earliest eligible observation per exact underwriting and metric; versions may overlap.",
            "regions": "Distinct ordered price anchors: <=BEAR+t, abs(x-BASE)<=t, >=BULL-t; otherwise ambiguous; t=1e-9*max(1,abs(BASE)).",
        },
        "eligible_sample_count": eligible_count,
        "eligible_pair_count": len(included),
        "excluded_sample_count": len(excluded),
        "candidate_pair_count": len(candidates),
        "excluded_underwriting_count": len(
            set(records)
            - {item["underwriting"]["underwriting_id"] for item in included}
        ),
        "exclusion_counts": dict(sorted(counts.items())),
        "date_range": _dates(included),
        "forecast_date_range": {
            "start": min(forecast_dates) if forecast_dates else None,
            "end": max(forecast_dates) if forecast_dates else None,
        },
        "horizon_type": "5Y",
        "included_pairs": included,
        "exclusions": excluded,
        "input_observations": sources,
        "input_underwritings": [_identity(item) for _, item in sorted(records.items())],
        "probability_calibration": _probability_summary(included),
        "continuous_forecast_errors": _continuous_summary(included),
        "cohorts": _cohort_summaries(included),
        "missing_cohort_metadata": {
            dimension: len(
                {
                    item["underwriting"]["underwriting_id"]
                    for item in included
                    if item["cohorts"][dimension] is None
                }
            )
            for dimension in ("setup_type", "sector", "industry", "decision_type")
        },
        "warnings": [
            "Below 5 samples: aggregate calibration statistics withheld. At 5-19, descriptive early signals only.",
            "Each probability/continuous/cohort/bucket summary has its own sample guard; global count is not its denominator.",
            "Assigned probability averages and realized frequencies use only the same unambiguous terminal-market subset.",
            "Repeated versions and overlapping forecasts are not independent trials.",
        ],
        "disclaimer": DISCLAIMER,
    }
    report["report_id"] = compute_content_hash(canonical_json(report).encode())
    return report


def run_calibration(
    store: SqliteStore, *, as_of: str | None = None, company: str | None = None
) -> dict[str, Any]:
    report = build_report(
        store, as_of=as_of or datetime.now(UTC).date().isoformat(), company=company
    )
    store.save_calibration_report(canonical_json(report))
    return report


def read_report(store: SqliteStore, report_id: str) -> dict[str, Any]:
    return json.loads(store.get_calibration_report(report_id))


def format_report(report: dict[str, Any]) -> str:
    probability = report["probability_calibration"]
    return "\n".join(
        [
            f"Calibration {report['report_id']} | as of {report['as_of_date']} | {report['company'] or 'ALL'}",
            f"Status: {report['status']}",
            f"Eligible forecasts: {report['eligible_sample_count']} | eligible metric pairs: {report['eligible_pair_count']} | excluded pairs: {report['excluded_sample_count']}",
            f"Date range: {canonical_json(report['date_range'])} | horizon: {report['horizon_type']}",
            f"Probability status: {probability['status']} | unambiguous terminal samples: {probability['eligible_sample_count']} | ambiguous: {probability['ambiguous_count']}",
            f"Scenario frequencies: {canonical_json(probability['scenario_frequency'])}",
            f"Mean Brier: {probability['mean_brier']}",
            f"Continuous forecast errors: {canonical_json(report['continuous_forecast_errors'])}",
            f"Exclusions: {canonical_json(report['exclusions'])}",
            DISCLAIMER,
        ]
    )

"""Compact, sanitized research exports from already-resolved domain values."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from owner_lens.screening import DIMENSION_ORDER
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.workbench.data import CompanyDetail


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        # Manual commentary is untrusted export content; never expose local paths or credentials.
        text = re.sub(
            r"(?i)(?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+",
            "[REDACTED]",
            value,
        )
        text = re.sub(
            r"(?i)(?:https?://|file://)[^\s]+|[A-Z]:[\\/][^\n,;]+|(?<!\w)/(?:home|Users|tmp|var|data)/[^\s]+",
            "[reference omitted]",
            text,
        )
        text = re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+", "[REDACTED]", text)
        return text
    return value


def _fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: row.get(name) for name in fields}


def estimate_window(
    rows: list[dict[str, Any]],
    *,
    period: str,
    as_of: str,
) -> dict[str, Any]:
    """Nearest strictly future target dates; never extrapolate missing observations."""
    if period not in ("annual", "quarter", "quarterly"):
        raise ValueError(f"Unknown estimate period: {period}.")
    cutoff = datetime.fromisoformat(as_of).date()
    ordered = sorted(rows, key=lambda row: date.fromisoformat(row["target_date"]))
    eligible = [
        row for row in ordered if date.fromisoformat(row["target_date"]) > cutoff
    ]
    limit = 5 if period == "annual" else 4
    selected = eligible[:limit]
    notes: list[str] = []
    minimum = 3 if period == "annual" else 4
    if len(selected) < minimum:
        notes.append(
            f"Only {len(selected)} future {period} periods captured; target is {minimum}-{limit}."
        )
    if not selected:
        notes.append("No future estimates captured relative to this as-of date.")
    elif (date.fromisoformat(selected[0]["target_date"]) - cutoff).days > (
        366 if period == "annual" else 100
    ):
        notes.append(
            f"No nearer periods captured before {selected[0]['target_date']}; "
            "this does not establish that nearer FMP estimates do not exist."
        )
    return {
        "as_of": cutoff.isoformat(),
        "rows": selected,
        "missing": notes,
        "available_rows": ordered,
    }


def scenario_rows(projection: UnderwritingProjection | None) -> list[dict[str, Any]]:
    if projection is None or projection.snapshot is None:
        return []
    manual = projection.snapshot.manual
    probabilities = (
        {
            item.name: item.probability
            for item in manual.probability_distribution.scenarios
        }
        if manual.probability_distribution
        else {}
    )
    saved = (
        json.loads(projection.valuation_json)["scenarios"]
        if projection.valuation_json
        else []
    )
    valuations = {item["assumptions"]["name"]: item for item in saved}
    return [
        {
            "Scenario": scenario.name.value,
            "Probability [JUDGMENT]": probabilities.get(scenario.name),
            "Value/share [CALCULATION]": valuations.get(scenario.name, {}).get(
                "year5_value_per_share"
            ),
            "Implied CAGR [CALCULATION]": valuations.get(scenario.name, {}).get(
                "implied_5y_cagr"
            ),
        }
        for scenario in manual.scenarios
    ]


@dataclass(frozen=True)
class ResearchContext:
    markdown: str
    json_export: str


def build_research_context(
    detail: CompanyDetail, projection: UnderwritingProjection | None
) -> ResearchContext:
    result = detail.screening
    latest = detail.owner_economics[-1] if detail.owner_economics else None
    capital = detail.capital_efficiency[-1] if detail.capital_efficiency else None
    view = detail.long_term_compounding
    estimate_fields = (
        "target_date",
        "revenue_low",
        "revenue_average",
        "revenue_high",
        "revenue_analyst_count",
        "eps_low",
        "eps_average",
        "eps_high",
        "eps_analyst_count",
    )
    expectations: list[dict[str, Any]] = []
    price = (
        _fields(detail.eod_prices[0], ("close", "market_date"))
        if detail.eod_prices
        else None
    )
    data: dict[str, Any] = {
        "identity [FACT]": {
            "ticker": detail.company.ticker,
            "company": detail.company.company_name,
            "provider": detail.company.provider,
            "evidence_as_of": detail.company.fetched_at,
            "saved_price": price,
        },
        "screening [CALCULATION]": {
            "priority": result.bucket.value,
            "setup": result.setup_type.value,
            "coverage": result.coverage_class.value,
            "dimensions": {
                dimension.value: detail.dimension(dimension).band.value
                for dimension in DIMENSION_ORDER
            },
            "why_surfaced": [item.value for item in result.supporting_reasons],
            "holds_back": ([result.gate.value] if result.gate else [])
            + [item.value for item in result.limiting_reasons],
            "coverage_reasons": [item.value for item in result.coverage_reasons],
        },
        "economics [FACT/CALCULATION]": {
            "fiscal_year": latest.fiscal_year if latest else None,
            "revenue": latest.revenue.value if latest and latest.revenue else None,
            "FCF": latest.free_cash_flow if latest else None,
            "FCF_margin": latest.fcf_margin if latest else None,
            "FCF_per_share": latest.fcf_per_share if latest else None,
            "ROIC": capital.roic if capital else None,
            "net_cash_debt": capital.net_cash if capital else None,
            "historical_revenue_CAGR": view.revenue_cagr if view else None,
            "share_count_CAGR": view.diluted_share_cagr if view else None,
            "window": [view.start_fiscal_year, view.end_fiscal_year] if view else None,
            "annual_history": [
                {
                    "fiscal_year": row.fiscal_year,
                    "revenue": row.revenue.value if row.revenue else None,
                    "FCF_margin": row.fcf_margin,
                    "FCF_per_share": row.fcf_per_share,
                }
                for row in detail.owner_economics[-5:]
            ],
        },
    }
    if projection and projection.snapshot and projection.record:
        evidence = json.loads(projection.snapshot.evidence_json)
        frozen = evidence.get("eod_price", {}).get("value")
        data["identity [FACT]"]["underwriting_as_of"] = projection.record.as_of_date
        data["identity [FACT]"]["underwriting_frozen_price"] = (
            _fields(frozen, ("close", "market_date")) if frozen else None
        )
        for captured in evidence.get("market_expectations", {}).get("snapshots", []):
            expectations.append(
                {
                    "period": captured["source"]["period_type"],
                    "retrieved_at": captured["source"]["fetched_at"],
                    "source_endpoint": captured["source"]["source_endpoint"],
                    "snapshot_id": captured["source"]["snapshot_id"],
                    "content_hash": captured["source"]["content_hash"],
                    **estimate_window(
                        [_fields(row, estimate_fields) for row in captured["rows"]],
                        period=captured["source"]["period_type"],
                        as_of=projection.record.as_of_date,
                    ),
                }
            )
        manual = projection.snapshot.manual
        summary = projection.summary
        data["underwriting"] = {
            "version": projection.record.version,
            "as_of": projection.record.as_of_date,
            "status": projection.status,
            "frozen_starting_state [FACT with derived basis]": [
                {
                    "metric": item.name,
                    "value": item.value,
                    "unit": item.unit,
                    "fiscal_year": item.fiscal_year,
                    "basis": item.basis.value,
                }
                for item in projection.snapshot.starting_financial_state
            ],
            "scenarios [ASSUMPTION]": [asdict(item) for item in manual.scenarios],
            "outcomes [CALCULATION with JUDGMENT weights]": scenario_rows(projection),
            "return [CALCULATION]": {
                "expected_terminal_value_per_share": summary.expected_terminal_value_per_share
                if summary
                else None,
                "expected_CAGR": summary.expected_5y_cagr if summary else None,
                "required_return [JUDGMENT]": summary.investor_policy.required_return
                if summary
                else (
                    manual.investor_policy.required_return
                    if manual.investor_policy
                    else None
                ),
                "spread": summary.return_spread if summary else None,
                "classification": summary.classification if summary else None,
            },
            "probability_rationale [JUDGMENT]": manual.probability_distribution.rationale
            if manual.probability_distribution
            else None,
            "variant": projection.variant.conclusion if projection.variant else None,
            "drivers [JUDGMENT]": [item.text for item in manual.business_drivers],
            "biggest_uncertainty [JUDGMENT]": manual.thesis.biggest_uncertainty,
            "most_important_variable [JUDGMENT]": manual.thesis.most_important_variable,
            "dependencies [JUDGMENT]": list(manual.thesis.dependencies),
            "breakers [JUDGMENT]": list(manual.thesis.breakers),
            "monitoring [JUDGMENT]": [
                {
                    "statement": item.statement,
                    "observable": item.observable,
                    "condition": item.threshold,
                    "cadence": item.monitoring_cadence,
                    "date": item.monitoring_date,
                }
                for item in (
                    *manual.thesis.monitoring_dependencies,
                    *manual.thesis.monitoring_breakers,
                )
            ],
            "support [typed evidence]": [
                {
                    "category": item.category.value,
                    "claim": item.text,
                    "date": item.evidence_date,
                }
                for item in manual.supporting_evidence
            ],
            "disconfirmation [typed evidence]": [
                {
                    "category": item.category.value,
                    "claim": item.text,
                    "date": item.evidence_date,
                }
                for item in manual.disconfirming_evidence
            ],
            "next_evidence [JUDGMENT]": list(manual.thesis.next_evidence_to_collect),
            "historical_ranges [CALCULATION]": [
                {
                    "driver": item.name,
                    "minimum": item.minimum,
                    "maximum": item.maximum,
                    "latest": item.latest,
                }
                for item in projection.snapshot.historical_base_rates
            ],
            "missing": [
                {"section": item.section, "reason": item.reason}
                for item in projection.missing_evidence
            ],
        }
        if projection.variant:
            data["underwriting"]["sensitivities [CALCULATION]"] = [
                {
                    "driver": item.driver,
                    "band": item.sensitivity.band,
                    "perturbation": item.sensitivity.perturbation,
                    "CAGR_effect": item.sensitivity.cagr_delta,
                    "consensus": item.consensus.value,
                    "consensus_horizon_years": item.consensus.horizon_years,
                    "delta": item.absolute_delta,
                    "rationale [JUDGMENT]": item.rationale.text
                    if item.rationale
                    else None,
                }
                for item in sorted(
                    projection.variant.drivers,
                    key=lambda item: abs(item.sensitivity.cagr_delta),
                    reverse=True,
                )
            ]
        if projection.challenger_runs:
            output = json.loads(projection.challenger_runs[-1].output_json)
            data["underwriting"]["challenger [JUDGMENT]"] = {
                name: output[name]["text"]
                for name in (
                    "overall_assessment",
                    "strongest_argument_against",
                    "variant_view_challenge",
                )
            }
        else:
            data["underwriting"]["challenger [JUDGMENT]"] = "No saved challenger run."
    else:
        data["underwriting"] = "No immutable underwriting record."
        for dataset in sorted({row["dataset"] for row in detail.market_expectations}):
            rows = [
                row for row in detail.market_expectations if row["dataset"] == dataset
            ]
            period = "annual" if dataset == "annual_analyst_estimates" else "quarterly"
            fetched_at = rows[0]["fetched_at"]
            expectations.append(
                {
                    "period": period,
                    "retrieved_at": fetched_at,
                    **estimate_window(
                        [_fields(row, estimate_fields) for row in rows],
                        period=period,
                        as_of=fetched_at,
                    ),
                }
            )
    data["market_expectations [EXPECTATION]"] = expectations or "No captured estimates."
    safe = _safe(data)
    lines = [
        "# OwnerLens Research Context",
        "",
        "Evidence and judgments, not a buy/sell recommendation. No retrieval requested.",
        "Current persisted screening/economics may differ from the separately labeled frozen underwriting.",
        "Decimal ratios: 0.12 = 12%. Missing values are N/A. Excerpts are bounded; not the complete audit record.",
        "",
    ]

    def scalar(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def brief(value: Any) -> str:
        if isinstance(value, dict):
            return "; ".join(f"{key}: {brief(item)}" for key, item in value.items())
        if isinstance(value, list):
            return " | ".join(brief(item) for item in value) or "N/A (none recorded)"
        text = scalar(value)
        return text[:400] + (" [truncated]" if len(text) > 400 else "")

    identity = safe["identity [FACT]"]
    lines.extend(
        [
            f"## {identity['ticker']} - {identity['company']}",
            (
                f"FACT: provider {identity['provider']}; evidence as-of {identity['evidence_as_of']}; "
                f"saved price {brief(identity.get('saved_price'))}."
            ),
        ]
    )
    if projection and projection.record:
        suffix = (
            "; same saved price/date"
            if identity.get("underwriting_frozen_price") == identity.get("saved_price")
            else f"; frozen price {brief(identity.get('underwriting_frozen_price'))}"
        )
        lines.append(
            f"Frozen underwriting as-of {identity['underwriting_as_of']}{suffix}."
        )
    lines.extend(
        [
            "",
            "## Screening [CALCULATION]",
            brief(safe["screening [CALCULATION]"]),
            "",
            "## Latest economics and trends [FACT/CALCULATION]",
        ]
    )
    economics = safe["economics [FACT/CALCULATION]"]
    lines.append(
        brief(
            {key: value for key, value in economics.items() if key != "annual_history"}
        )
    )
    if economics["annual_history"]:
        first, last = economics["annual_history"][0], economics["annual_history"][-1]
        lines.append("Observed endpoints: " + brief(first) + " -> " + brief(last))
    lines.extend(["", "## Nearest market_expectations [EXPECTATION]"])
    for window in (
        safe["market_expectations [EXPECTATION]"]
        if isinstance(expectations, list) and expectations
        else []
    ):
        lines.append(
            f"{window['period']}; as-of {window['as_of']}; retrieved {window['retrieved_at']}"
        )
        for row in window["rows"]:
            lines.append(
                f"- {row['target_date']}: revenue low/avg/high "
                f"{scalar(row['revenue_low'])}/{scalar(row['revenue_average'])}/{scalar(row['revenue_high'])} "
                f"(analysts {scalar(row['revenue_analyst_count'])}); EPS low/avg/high "
                f"{scalar(row['eps_low'])}/{scalar(row['eps_average'])}/{scalar(row['eps_high'])} "
                f"(analysts {scalar(row['eps_analyst_count'])})"
            )
        lines.extend("- Missing: " + note for note in window["missing"])
    if not expectations:
        lines.append("N/A: No captured estimates.")
    lines.extend(["", "## Underwriting"])
    underwriting = safe["underwriting"]
    if isinstance(underwriting, str):
        lines.append(underwriting)
    else:
        lines.append(
            f"v{underwriting['version']} | {underwriting['as_of']} | {underwriting['status']}"
        )
        # Only show frozen state when it differs; avoid reprinting identical economics.
        facts = underwriting["frozen_starting_state [FACT with derived basis]"]
        current_metrics = {
            "revenue": "revenue",
            "fcf": "FCF",
            "fcf_margin": "FCF_margin",
            "fcf_per_share": "FCF_per_share",
            "roic": "ROIC",
            "net_cash_or_debt": "net_cash_debt",
        }
        if any(
            item["fiscal_year"] != economics["fiscal_year"]
            or item["value"] != economics[current_metrics[item["metric"]]]
            for item in facts
            if item["metric"] in current_metrics
        ):
            lines.append(
                "Frozen starting facts differ from current economics: " + brief(facts)
            )
        lines.append("ASSUMPTION scenarios / JUDGMENT weights / CALCULATION outcomes:")
        outcomes = {
            row["Scenario"]: row
            for row in underwriting["outcomes [CALCULATION with JUDGMENT weights]"]
        }
        for scenario in underwriting["scenarios [ASSUMPTION]"]:
            row = outcomes[scenario["name"]]
            lines.append(
                f"- {scenario['name']}: growth {scenario['revenue_cagr']}, FCF margin "
                f"{scenario['fcf_margin_year5']}, shares {scenario['share_count_cagr']}, "
                f"terminal {scenario['terminal_fcf_multiple']}x; "
                f"p {scalar(row['Probability [JUDGMENT]'])}, value/share "
                f"{scalar(row['Value/share [CALCULATION]'])}, CAGR {scalar(row['Implied CAGR [CALCULATION]'])}; "
                f"{brief(scenario['narrative'])}"
            )
        for key in (
            "return [CALCULATION]",
            "probability_rationale [JUDGMENT]",
            "variant",
            "sensitivities [CALCULATION]",
            "drivers [JUDGMENT]",
            "biggest_uncertainty [JUDGMENT]",
            "most_important_variable [JUDGMENT]",
            "dependencies [JUDGMENT]",
            "breakers [JUDGMENT]",
            "next_evidence [JUDGMENT]",
            "challenger [JUDGMENT]",
            "missing",
        ):
            lines.append(f"- {key}: {brief(underwriting.get(key))}")
        for key in ("support [typed evidence]", "disconfirmation [typed evidence]"):
            lines.append(f"- {key}: {brief(underwriting[key][:3])}")
    return ResearchContext(
        "\n".join(lines), json.dumps(safe, indent=2, sort_keys=True, allow_nan=False)
    )

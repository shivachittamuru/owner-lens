"""Independent historical research prompts, not financial risk classifications."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from itertools import pairwise
from statistics import median
from typing import Any

from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.errors import PersistenceError
from owner_lens.screening import (
    DEFAULT_SCREENING_THRESHOLDS,
    ScreeningDimension,
    ScreeningEvidence,
    ScreeningReason,
    ScreeningResult,
    assemble_screening_evidence,
)
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    load_canonical_history,
)

INCOMPATIBLE_SECTORS = {"Financials", "Financial Services", "Real Estate"}
COVERAGE_GATES = {
    ScreeningReason.COVERAGE_FAILED,
    ScreeningReason.TOO_FEW_EVALUABLE_DIMENSIONS,
}


def _at_least(value: float, threshold: float) -> bool:
    return value >= threshold or math.isclose(
        value, threshold, rel_tol=0, abs_tol=1e-12
    )


@dataclass(frozen=True)
class ReviewObservation:
    code: str
    explanation: str


@dataclass(frozen=True)
class UncertaintyFragilityReview:
    ticker: str
    priority: str
    existing_gate: str | None
    business: tuple[ReviewObservation, ...]
    financial_state: str
    financial: tuple[ReviewObservation, ...]
    limitations: tuple[ReviewObservation, ...]
    annual: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...] = ()

    @property
    def flagged(self) -> bool:
        return bool(
            self.business or self.financial or self.limitations or self.existing_gate
        )

    @property
    def research_direction(self) -> str:
        if self.existing_gate:
            return "Resolve the existing gate before underwriting; retain evidence limitations."
        if self.financial:
            return "Investigate cash generation, financing and dilution before price."
        if self.limitations:
            return "Resolve missingness and definitions; then test business durability."
        return "Research durability, competition and structural change; no safety conclusion."


def assess_uncertainty_fragility(
    evidence: ScreeningEvidence,
    result: ScreeningResult,
    *,
    sector: str | None,
) -> UncertaintyFragilityReview:
    """Use validated consecutive annual windows; never change a screening result."""
    rows = tuple(sorted(evidence.owner_economics, key=lambda row: row.fiscal_year)[-5:])
    business: list[ReviewObservation] = []
    financial: list[ReviewObservation] = []
    limits: list[ReviewObservation] = []
    annual: list[dict[str, Any]] = []
    valid = bool(rows) and len({row.fiscal_year for row in rows}) == len(rows)
    for row in rows:
        facts = (
            row.revenue,
            row.operating_cash_flow,
            row.capital_expenditures,
            row.diluted_shares,
        )
        periods = {fact.period_end for fact in facts if fact is not None}
        if len(periods) != 1 or any(fact is None for fact in facts):
            valid = False
        annual.append(
            {
                "fiscal_year": row.fiscal_year,
                "period_end": row.revenue.period_end.isoformat()
                if row.revenue
                else None,
                "FCF": row.free_cash_flow,
                "FCF/share": row.fcf_per_share,
                "FCF margin": row.fcf_margin,
                "revenue": row.revenue.value if row.revenue else None,
                "diluted shares": row.diluted_shares.value
                if row.diluted_shares
                else None,
                "CapEx": row.capital_expenditures.value
                if row.capital_expenditures
                else None,
                "filed": row.revenue.filed.isoformat()
                if row.revenue and row.revenue.filed
                else None,
            }
        )
    consecutive = valid and all(
        b.fiscal_year == a.fiscal_year + 1 for a, b in pairwise(rows)
    )
    if len(rows) < 5 or not consecutive:
        limits.append(
            ReviewObservation(
                "INCOMPLETE_ANNUAL_HISTORY",
                f"{len(rows)} annual rows; five consecutive aligned fiscal periods required for the direction check. "
                "Other indicators require the latest three consecutive aligned periods.",
            )
        )
    latest_three = rows[-3:]
    recent_valid = (
        len(latest_three) == 3
        and all(b.fiscal_year == a.fiscal_year + 1 for a, b in pairwise(latest_three))
        and all(
            row.revenue is not None
            and row.operating_cash_flow is not None
            and row.capital_expenditures is not None
            and row.diluted_shares is not None
            and len(
                {
                    fact.period_end
                    for fact in (
                        row.revenue,
                        row.operating_cash_flow,
                        row.capital_expenditures,
                        row.diluted_shares,
                    )
                    if fact is not None
                }
            )
            == 1
            for row in latest_three
        )
    )
    sector_ok = sector not in INCOMPATIBLE_SECTORS
    if not sector_ok:
        limits.append(
            ReviewObservation(
                "SECTOR_COMPARABILITY_NOT_VERIFIED",
                f"{sector}: ordinary FCF, ROIC and debt comparisons may be incompatible; "
                "historical business indicators suppressed, existing gates retained.",
            )
        )
    fps = [row.fcf_per_share for row in rows]
    if (
        sector_ok
        and len(rows) == 5
        and consecutive
        and all(v is not None and v > 0 for v in fps)
    ):
        values = [float(v) for v in fps if v is not None]
        changes = [b / a - 1 for a, b in pairwise(values)]
        if any(_at_least(v, 0.10) for v in changes) and any(
            _at_least(-v, 0.10) for v in changes
        ):
            business.append(
                ReviewObservation(
                    "FCF_SHARE_DIRECTION_REVERSAL",
                    f"FY{rows[0].fiscal_year}-{rows[-1].fiscal_year} FCF/share {values}; "
                    f"annual changes {changes}; at least one >=10% rise and one >=10% fall.",
                )
            )
    if sector_ok and recent_valid:
        recent_fps = [row.fcf_per_share for row in latest_three]
        if all(v is not None and v > 0 for v in recent_fps):
            values = [float(v) for v in recent_fps if v is not None]
            reference = median(values)
            if values[-1] > 1.5 * reference:
                business.append(
                    ReviewObservation(
                        "FCF_SHARE_NORMALIZATION_SENSITIVITY",
                        f"FY{[r.fiscal_year for r in latest_three]} FCF/share {values}; "
                        f"latest / three-year median = {values[-1] / reference:.4f} >1.50. Durability unproven.",
                    )
                )
        margins = [row.fcf_margin for row in latest_three]
        if all(v is not None for v in margins):
            values = [float(v) for v in margins if v is not None]
            if _at_least(values[-2] - values[-1], 0.03) or _at_least(
                max(values) - min(values), 0.10
            ):
                business.append(
                    ReviewObservation(
                        "FCF_MARGIN_CHANGE",
                        f"FY{[r.fiscal_year for r in latest_three]} margins {values}; "
                        "latest annual decline >=3 percentage points or three-year range >=10 points.",
                    )
                )
        revenues = [row.revenue.value if row.revenue else None for row in latest_three]
        if all(v is not None and v > 0 for v in revenues):
            values = [float(v) for v in revenues if v is not None]
            growth = [b / a - 1 for a, b in pairwise(values)]
            if _at_least(growth[-2] - growth[-1], 0.10):
                business.append(
                    ReviewObservation(
                        "REVENUE_GROWTH_DECELERATION",
                        f"FY{[r.fiscal_year for r in latest_three]} revenue {values}; "
                        f"growth {growth}; latest growth deceleration >=10 percentage points.",
                    )
                )
    latest = rows[-1] if rows else None
    capital = evidence.latest_capital_efficiency
    net_cash = capital.net_cash if capital else None
    if latest is None or latest.free_cash_flow is None:
        limits.append(
            ReviewObservation(
                "FCF_INSUFFICIENT_EVIDENCE",
                "Latest canonical FCF unavailable; cash burn is not assumed.",
            )
        )
    if (
        latest is None
        or latest.diluted_shares is None
        or any(r.fcf_per_share is None for r in rows)
    ):
        limits.append(
            ReviewObservation(
                "PER_SHARE_INSUFFICIENT_EVIDENCE",
                "Missing diluted shares or annual FCF/share; unavailable values are not zero.",
            )
        )
    if net_cash is None:
        limits.append(
            ReviewObservation(
                "BALANCE_SHEET_INSUFFICIENT_EVIDENCE",
                "Canonical cash/debt position unavailable; leverage checks may be skipped.",
            )
        )
    if not evidence.capital_efficiency:
        limits.append(
            ReviewObservation(
                "CAPITAL_EFFICIENCY_UNSUPPORTED",
                "Capital-efficiency metrics unavailable.",
            )
        )
    if latest and latest.free_cash_flow is not None and latest.free_cash_flow <= 0:
        financial.append(
            ReviewObservation(
                "NONPOSITIVE_LATEST_FCF",
                f"FY{latest.fiscal_year} canonical FCF={latest.free_cash_flow}; <=0.",
            )
        )
    if (
        latest
        and net_cash is not None
        and net_cash < 0
        and latest.free_cash_flow
        and latest.free_cash_flow > 0
    ):
        multiple = -net_cash / latest.free_cash_flow
        if multiple > DEFAULT_SCREENING_THRESHOLDS.net_debt_to_fcf_adequate:
            financial.append(
                ReviewObservation(
                    "NET_DEBT_RELATIVE_TO_FCF",
                    f"Canonical net cash={net_cash}; latest FCF={latest.free_cash_flow}; "
                    f"net debt/FCF={multiple:.4f} > existing adequate threshold 2.0.",
                )
            )
    if (
        latest
        and net_cash is not None
        and net_cash < 0
        and latest.revenue
        and latest.revenue.value > 0
        and latest.capital_expenditures
    ):
        burden = abs(latest.capital_expenditures.value) / latest.revenue.value
        if burden >= 0.20:
            financial.append(
                ReviewObservation(
                    "CAPITAL_INTENSITY_WITH_NET_DEBT",
                    f"FY{latest.fiscal_year} PP&E CapEx/revenue={burden:.4f} >=20%; "
                    f"canonical net cash={net_cash}. Financing context, not a runway estimate.",
                )
            )
    if ScreeningReason.MATERIAL_DILUTION in result.limiting_reasons:
        financial.append(
            ReviewObservation(
                "EXISTING_MATERIAL_DILUTION",
                "Feature 7 MATERIAL_DILUTION: "
                + "; ".join(
                    result.dimensions[ScreeningDimension.PER_SHARE_COMPOUNDING].evidence
                ),
            )
        )
    for reason in result.coverage_reasons:
        limits.append(
            ReviewObservation(reason.value, "Existing Feature 7 coverage limitation.")
        )
    for metric in evidence.unavailable_metrics:
        limits.append(ReviewObservation("UNSUPPORTED_METRIC", metric))
    for layer in evidence.blocked_layers:
        limits.append(ReviewObservation("UNSUPPORTED_LAYER", layer))
    gate = result.gate
    if gate is not None and gate not in COVERAGE_GATES:
        state = "ACTIVATED_EXISTING_GATE"
        financial.insert(
            0,
            ReviewObservation(
                gate.value,
                "Existing Feature 7 survival gate; see unchanged dimension measurements and annual history.",
            ),
        )
    elif financial:
        state = "OBSERVED_FINANCIAL_WARNING"
    elif (
        gate in COVERAGE_GATES
        or not latest
        or latest.free_cash_flow is None
        or net_cash is None
        or latest.diluted_shares is None
        or latest.fcf_per_share is None
        or capital is None
        or capital.roic is None
        or not consecutive
        or len(rows) < 5
        or not sector_ok
    ):
        state = "INSUFFICIENT_EVIDENCE"
    else:
        state = "NO_FLAG_FROM_CURRENT_CHECKS"
    return UncertaintyFragilityReview(
        result.ticker,
        result.bucket.value,
        gate.value if gate else None,
        tuple(business),
        state,
        tuple(financial),
        tuple(limits),
        tuple(annual),
    )


def load_canonical_uncertainty_fragility(
    source: WorkbenchSource,
    company: PersistedCompany,
    result: ScreeningResult,
) -> tuple[UncertaintyFragilityReview, bool]:
    """Assess canonical evidence and indicate whether its history was available."""
    try:
        history = load_canonical_history(source, company)
    except WorkbenchError as exc:
        gate = result.gate
        return UncertaintyFragilityReview(
            company.ticker,
            result.bucket.value,
            result.gate.value if result.gate else None,
            (),
            "ACTIVATED_EXISTING_GATE"
            if gate is not None and gate not in COVERAGE_GATES
            else "INSUFFICIENT_EVIDENCE",
            (
                ReviewObservation(
                    gate.value, "Existing gate retained; current history unavailable."
                ),
            )
            if gate is not None
            else (),
            (ReviewObservation("HISTORY_NOT_VERIFIED", str(exc)),),
            (),
        ), False
    return assess_uncertainty_fragility(
        assemble_screening_evidence(history),
        result,
        sector=company.sector,
    ), True


def load_uncertainty_fragility(
    source: WorkbenchSource,
    company: PersistedCompany,
    result: ScreeningResult,
) -> UncertaintyFragilityReview:
    """Read canonical-linked raw evidence only; no prices, refresh or writes."""
    review, history_available = load_canonical_uncertainty_fragility(
        source, company, result
    )
    if not history_available:
        return review
    limits = list(review.limitations)
    sources: list[dict[str, Any]] = []
    if (
        company.provider == "fmp"
        and isinstance(source.store, SqliteStore)
        and company.security_id is not None
    ):
        stored = source.store.get_fmp_security_evidence(company.security_id)
        wanted = {
            "annual_income_statement",
            "annual_cash_flow_statement",
            "annual_balance_sheet_statement",
        }
        ends = {
            row["period_end"] for row in review.annual if row["period_end"] is not None
        }
        for snapshot in stored["annual_sources"]:
            if snapshot["dataset"] not in wanted:
                continue
            provenance = {
                k: snapshot[k]
                for k in (
                    "snapshot_id",
                    "dataset",
                    "source_endpoint",
                    "fetched_at",
                    "content_hash",
                )
            }
            sources.append(provenance)
            try:
                body = source.raw_store.get(snapshot["content_hash"])
                if compute_content_hash(body) != snapshot["content_hash"]:
                    raise ValueError("Content hash mismatch.")
                rows = json.loads(body)
                if not isinstance(rows, list) or any(
                    not isinstance(row, dict) for row in rows
                ):
                    raise ValueError("Expected a list of source observations.")
                if any(row.get("symbol") != company.ticker for row in rows):
                    raise ValueError("Source identity mismatch.")
                matched_dates = [
                    row.get("date") for row in rows if row.get("date") in ends
                ]
                if len(matched_dates) != len(set(matched_dates)):
                    raise ValueError("Duplicate annual source period.")
                missing = ends - set(matched_dates)
                if missing:
                    limits.append(
                        ReviewObservation(
                            "DEFINITIONS_NOT_VERIFIED",
                            f"{snapshot['dataset']}: missing periods {sorted(missing)}; snapshot {snapshot['snapshot_id']}.",
                        )
                    )
                for row in rows:
                    if row.get("date") not in ends:
                        continue
                    if row.get("reportedCurrency") != "USD":
                        limits.append(
                            ReviewObservation(
                                "DEFINITION_CURRENCY_NOT_VERIFIED",
                                f"{row['date']}: {snapshot['dataset']} currency not verified USD; definition comparison suppressed.",
                            )
                        )
                        continue
                    if snapshot["dataset"] == "annual_income_statement":
                        continue
                    pairs = (
                        [
                            (
                                "investmentsInPropertyPlantAndEquipment",
                                "capitalExpenditure",
                                "CAPEX_DEFINITION",
                            )
                        ]
                        if snapshot["dataset"] == "annual_cash_flow_statement"
                        else [("shortTermDebt", "longTermDebt", "DEBT_DEFINITION")]
                    )
                    for a, b, code in pairs:
                        left, right = row.get(a), row.get(b)
                        total = (
                            row.get("totalDebt") if code == "DEBT_DEFINITION" else None
                        )
                        numbers = [left, right] + (
                            [total] if code == "DEBT_DEFINITION" else []
                        )
                        if any(
                            isinstance(v, bool)
                            or not isinstance(v, (int, float))
                            or not math.isfinite(v)
                            for v in numbers
                        ):
                            limits.append(
                                ReviewObservation(
                                    code + "_NOT_VERIFIED",
                                    f"{row['date']}: source fields missing/malformed; snapshot {snapshot['snapshot_id']}.",
                                )
                            )
                            continue
                        if total is None and code == "DEBT_DEFINITION":
                            continue
                        if left is None or right is None:
                            continue
                        first = (
                            float(left) + float(right)
                            if code == "DEBT_DEFINITION"
                            else abs(float(left))
                        )
                        second = (
                            float(total)
                            if total is not None and code == "DEBT_DEFINITION"
                            else abs(float(right))
                        )
                        difference = abs(first - second)
                        scale = max(abs(first), abs(second))
                        if difference > 0 and difference >= 0.05 * scale:
                            limits.append(
                                ReviewObservation(
                                    code + "_DIFFERENCE",
                                    f"{row['date']}: {a}={left}, {b}={right}"
                                    + (
                                        f", totalDebt={total}"
                                        if total is not None
                                        else ""
                                    )
                                    + f"; difference={difference} >=5% of larger definition; "
                                    f"snapshot {snapshot['snapshot_id']}. Economic inclusion NOT_VERIFIED, not distress.",
                                )
                            )
            except (PersistenceError, ValueError, TypeError) as exc:
                limits.append(
                    ReviewObservation(
                        "SOURCE_NOT_VERIFIED", f"{snapshot['dataset']}: {exc}"
                    )
                )
        if wanted - {s["dataset"] for s in sources}:
            limits.append(
                ReviewObservation(
                    "DEFINITIONS_NOT_VERIFIED",
                    "Missing canonical-linked annual cash-flow/balance snapshots.",
                )
            )
    elif company.provider == "fmp":
        raise WorkbenchError("FMP review requires stable persisted security identity.")
    else:
        limits.append(
            ReviewObservation(
                "PROVIDER_DEFINITIONS_NOT_VERIFIED",
                "FMP alternate definition checks unavailable for this provider.",
            )
        )
    return replace(review, limitations=tuple(limits), sources=tuple(sources))

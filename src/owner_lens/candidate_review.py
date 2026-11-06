"""Bounded, offline research worksheets; no valuation model or ranking changes."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import median
from typing import Any

from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.persistence.errors import PersistenceError
from owner_lens.research_context import build_research_context
from owner_lens.screening import (
    DIMENSION_ORDER,
    DimensionBand,
    ScreeningBucket,
    ScreeningDimension,
    ScreeningReason,
    ScreeningResult,
    SetupType,
    assemble_screening_evidence,
    screen_company,
)
from owner_lens.underwriting import UnderwritingError
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    company_detail,
    improving_economics_observations,
    improving_economics_review_candidates,
    load_canonical_history,
    load_persisted_companies,
)

COHORT_SIZES = {
    "COMPOUNDERS": 8,
    "IMPROVING": 8,
    "FRAGILE_CONTROLS": 4,
    "NORMALIZATION_CONTROLS": 4,
}
INCOMPARABLE_SECTORS = ("Financials", "Financial Services", "Real Estate")
FINANCIAL_GATES = {
    ScreeningReason.PERSISTENT_CASH_BURN,
    ScreeningReason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW,
    ScreeningReason.NET_DEBT_WITHOUT_CASH_FLOW,
    ScreeningReason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL,
    ScreeningReason.PERSISTENT_MATERIAL_DILUTION,
}
HANDOFF = """## Investor-led research handoff

Use the supplied OwnerLens Copy Research Context and candidate worksheet.
Treat FACT as sourced evidence, CALCULATION as a reproducible transformation,
and HYPOTHESIS/JUDGMENT as unverified. Do not rewrite sourced facts or fill gaps.

1. Investigate business economics, moat, and industry comparability.
2. Compare temporary pressure with structural deterioration and impairment.
3. Assess liquidity, refinancing, covenants, cash conversion, dilution, SBC,
   capital intensity, and all existing survival gates. Net cash is not safety.
4. Identify evidence for forward growth, margins, reinvestment, and dilution.
5. Separate captured market expectations from explicit investor assumptions.
   Do not invent forecasts, probabilities, or universal terminal multiples.
6. Present competing hypotheses, disconfirming evidence, and needed sources.
7. Explain whether full Feature 8 underwriting is justified. Do not approve
   probabilities, revise frozen records, or create investment decisions.

This is retrospective research attention, not a Buy/Sell recommendation.
Unverified currency, adjustment basis, or conflicting definitions remain
unresolved. A three-year median is a sensitivity reference, not intrinsic value.
"""


@dataclass(frozen=True)
class CandidateSelection:
    cohort: str
    company: PersistedCompany
    screening: ScreeningResult
    selection_reason: str


def select_candidates(
    source: WorkbenchSource,
) -> tuple[tuple[CandidateSelection, ...], tuple[str, ...]]:
    companies = load_persisted_companies(source, "fmp")
    results: list[ScreeningResult] = []
    owners: dict[str, Any] = {}
    errors: list[str] = []
    by_ticker = {company.ticker: company for company in companies}
    for company in companies:
        try:
            evidence = assemble_screening_evidence(
                load_canonical_history(source, company)
            )
            results.append(screen_company(evidence))
            owners[company.ticker] = evidence.owner_economics
        except WorkbenchError as exc:
            errors.append(f"{company.ticker}: {exc}")
    ordered = sorted(results, key=lambda result: result.rank_key)
    selected: list[CandidateSelection] = []
    used: set[str] = set()

    def add(cohort: str, result: ScreeningResult, reason: str) -> None:
        selected.append(
            CandidateSelection(cohort, by_ticker[result.ticker], result, reason)
        )
        used.add(result.ticker)

    controls = (
        ("Real Estate", None, "Real Estate accounting/comparability control"),
        (
            "Financial Services",
            None,
            "Financial-services cash-flow/debt comparability control",
        ),
        (
            None,
            ScreeningReason.QUESTIONABLE_CAPITAL_ALLOCATION,
            "Questionable capital allocation normalization control",
        ),
        (
            None,
            ScreeningReason.RETURNS_BELOW_QUALITY_THRESHOLD,
            "Below-quality returns normalization control",
        ),
    )
    for sector, reason, label in controls:
        matches = [
            result
            for result in ordered
            if result.ticker not in used
            and (
                by_ticker[result.ticker].sector == sector
                if sector is not None
                else reason in result.limiting_reasons
            )
        ]
        if matches:
            add("NORMALIZATION_CONTROLS", matches[0], label)
        else:
            errors.append(f"Unfilled normalization slot: {label}.")
    for result in ordered:
        if (
            result.ticker not in used
            and result.gate in FINANCIAL_GATES
            and sum(s.cohort == "FRAGILE_CONTROLS" for s in selected) < 4
        ):
            add("FRAGILE_CONTROLS", result, "Existing financial survival gate")
    for result in ordered:
        if (
            result.ticker not in used
            and by_ticker[result.ticker].sector not in INCOMPARABLE_SECTORS
            and result.gate is None
            and result.setup_type is SetupType.COMPOUNDER
            and result.bucket
            in (ScreeningBucket.HIGH_PRIORITY, ScreeningBucket.WORTH_UNDERWRITING)
            and all(
                result.band(dimension) is DimensionBand.STRONG
                for dimension in (
                    ScreeningDimension.BUSINESS_QUALITY,
                    ScreeningDimension.CAPITAL_EFFICIENCY,
                    ScreeningDimension.PER_SHARE_COMPOUNDING,
                )
            )
            and sum(s.cohort == "COMPOUNDERS" for s in selected) < 8
        ):
            add(
                "COMPOUNDERS",
                result,
                "Existing queue; strong quality/ROIC/per-share bands",
            )
    for improving in improving_economics_review_candidates(companies, results, owners):
        result = improving.screening
        if (
            result.ticker not in used
            and by_ticker[result.ticker].sector not in INCOMPARABLE_SECTORS
            and sum(s.cohort == "IMPROVING" for s in selected) < 8
        ):
            add("IMPROVING", result, "Existing Improving Economics review filter")
    for cohort, count in COHORT_SIZES.items():
        actual = sum(item.cohort == cohort for item in selected)
        if actual < count:
            errors.append(f"{cohort}: {actual}/{count}; no ineligible fillers.")
    return tuple(selected), tuple(errors)


def _number(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Invalid numeric field {field}: {value!r}.")
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite field {field}.")
    return float(value)


def _rows(
    source: WorkbenchSource, snapshot: dict[str, Any], symbol: str
) -> list[dict[str, Any]]:
    raw = source.raw_store.get(snapshot["content_hash"])
    if compute_content_hash(raw) != snapshot["content_hash"]:
        raise ValueError(f"{symbol}: snapshot hash mismatch.")
    rows = json.loads(raw)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{symbol}: snapshot is not a list of objects.")
    if any(row.get("symbol") != symbol for row in rows):
        raise ValueError(f"{symbol}: source symbol mismatch.")
    return rows


def _period(rows: list[dict[str, Any]], period_end: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get("date") == period_end]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one statement row for {period_end}; got {len(matches)}."
        )
    return matches[0]


def _provenance(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        field: snapshot[field]
        for field in ("snapshot_id", "source_endpoint", "fetched_at", "content_hash")
    }


def candidate_worksheet(
    source: WorkbenchSource, selection: CandidateSelection, *, market_date: date
) -> dict[str, Any]:
    detail = company_detail(source, selection.company)
    symbol = selection.company.ticker
    snapshots = {row["dataset"]: row for row in detail.evidence_snapshots}
    annual = {row["dataset"]: row for row in detail.annual_provenance}
    warnings = list(detail.evidence_errors)
    references: list[dict[str, Any]] = []
    for owner in reversed(detail.owner_economics[-3:]):
        if owner.revenue is None:
            warnings.append(f"FY{owner.fiscal_year}: missing revenue period.")
            continue
        end = owner.revenue.period_end.isoformat()
        cash_snapshot = annual.get("annual_cash_flow_statement")
        income_snapshot = annual.get("annual_income_statement")
        if cash_snapshot is None or income_snapshot is None:
            warnings.append("Missing canonical-linked statement snapshots.")
            continue
        cash = _period(_rows(source, cash_snapshot, symbol), end)
        income = _period(_rows(source, income_snapshot, symbol), end)
        if (
            owner.diluted_shares is not None
            and _number(income, "weightedAverageShsOutDil")
            != owner.diluted_shares.value
        ):
            raise ValueError(
                f"{end}: canonical shares disagree with linked raw evidence."
            )
        if (
            owner.operating_cash_flow is not None
            and _number(cash, "netCashProvidedByOperatingActivities")
            != owner.operating_cash_flow.value
        ):
            raise ValueError(
                f"{end}: canonical operating cash flow disagrees with raw evidence."
            )
        currency_ok = (
            cash.get("reportedCurrency") == income.get("reportedCurrency") == "USD"
        )
        provider_fcf = _number(cash, "freeCashFlow")
        capex = _number(cash, "capitalExpenditure")
        pp_e = _number(cash, "investmentsInPropertyPlantAndEquipment")
        for fact in (
            owner.operating_cash_flow,
            owner.capital_expenditures,
            owner.diluted_shares,
        ):
            if fact is not None and fact.period_end.isoformat() != end:
                raise ValueError(f"{end}: canonical denominator period mismatch.")
        if owner.capital_expenditures is not None and (
            pp_e is None or abs(pp_e) != owner.capital_expenditures.value
        ):
            raise ValueError(
                f"{end}: canonical PP&E spending disagrees with raw evidence."
            )
        conflict = capex is not None and pp_e is not None and abs(capex) != abs(pp_e)
        if conflict:
            warnings.append(f"{end}: CONFLICTING_CAPEX_DEFINITIONS.")
        source_ocf = _number(cash, "netCashProvidedByOperatingActivities")
        provider_conflict = (
            provider_fcf is not None
            and source_ocf is not None
            and capex is not None
            and provider_fcf != source_ocf - abs(capex)
        )
        if provider_conflict:
            warnings.append(f"{end}: PROVIDER_FCF_RECONCILIATION_CONFLICT.")
        filings = [cash.get("filingDate"), income.get("filingDate")]
        available = all(
            isinstance(filed, str) and date.fromisoformat(filed) < market_date
            for filed in filings
        )
        if not available:
            warnings.append(
                f"{end}: filing availability UNKNOWN or not before market date."
            )
        if not currency_ok:
            warnings.append(f"{end}: financial currency NOT_VERIFIED.")
        references.append(
            {
                "fiscal_year": owner.fiscal_year,
                "period_end": end,
                "canonical_fcf": owner.free_cash_flow,
                "canonical_fcf_per_share": owner.fcf_per_share,
                "diluted_weighted_average_shares": (
                    owner.diluted_shares.value if owner.diluted_shares else None
                ),
                "provider_fcf_per_share": (
                    provider_fcf / owner.diluted_shares.value
                    if provider_fcf is not None
                    and owner.diluted_shares
                    and owner.diluted_shares.value > 0
                    else None
                ),
                "canonical_capex_field": "investmentsInPropertyPlantAndEquipment",
                "canonical_capex": abs(pp_e) if pp_e is not None else None,
                "provider_capitalExpenditure": capex,
                "definition_conflict": conflict,
                "provider_fcf_reconciliation_conflict": provider_conflict,
                "financial_currency_verified": currency_ok,
                "filing_dates": filings,
                "acceptance_dates": [
                    cash.get("acceptedDate"),
                    income.get("acceptedDate"),
                ],
                "filed_before_market_date": available,
                "cash_source": _provenance(cash_snapshot),
                "share_source": _provenance(income_snapshot),
            }
        )
    profile_snapshot = snapshots.get("candidate_profile", snapshots.get("profile"))
    profile_rows = _rows(source, profile_snapshot, symbol) if profile_snapshot else []
    if len(profile_rows) > 1:
        raise ValueError(f"{symbol}: multiple profile identities.")
    profile = profile_rows[0] if profile_rows else {}
    cik = profile.get("cik")
    if (
        cik is not None
        and selection.company.cik
        and str(cik).zfill(10) != selection.company.cik
    ):
        raise ValueError(f"{symbol}: profile CIK mismatch.")
    if not profile_rows:
        warnings.append("No saved profile: currency/exchange identity NOT_VERIFIED.")
    # Candidate quotes are isolated raw evidence, not replacement latest-price records.
    if (
        not isinstance(source.store, SqliteStore)
        or selection.company.security_id is None
    ):
        raise ValueError("Candidate review requires persisted FMP security identity.")
    quote_snapshot: dict[str, Any] | None = None
    quote_rows: list[dict[str, Any]] = []
    historical_values: set[float] = set()
    for dataset in ("candidate_price", "historical_price", "eod_price"):
        for snapshot in source.store.list_fmp_evidence_snapshots(
            selection.company.security_id, dataset
        ):
            rows = _rows(source, snapshot, symbol)
            matching = [
                row for row in rows if row.get("date") == market_date.isoformat()
            ]
            if not matching:
                continue
            if quote_snapshot is None:
                quote_snapshot, quote_rows = snapshot, rows
            for row in matching:
                field = "close" if row.get("close") is not None else "price"
                value = _number(row, field)
                if value is None or value <= 0:
                    raise ValueError(f"{symbol}: invalid matching price.")
                historical_values.add(value)
    price_conflict = len(historical_values) > 1
    if price_conflict:
        warnings.append(
            f"PRICE_REVISION_CONFLICT: {sorted(historical_values)}; comparisons blocked."
        )
    prices: dict[str, float] = {}
    bar_currency: dict[str, Any] = {}
    for row in quote_rows:
        raw_day = row.get("date")
        if not isinstance(raw_day, str):
            raise TypeError(f"{symbol}: price date must be an ISO date string.")
        day = date.fromisoformat(raw_day).isoformat()
        if day != raw_day:
            raise ValueError(f"{symbol}: price date must use YYYY-MM-DD.")
        field = "close" if row.get("close") is not None else "price"
        value = _number(row, field)
        if value is None or value <= 0 or day in prices:
            raise ValueError(f"{symbol}: invalid or duplicate price on {day}.")
        prices[day] = value
        bar_currency[day] = row.get("currency")
    close = prices.get(market_date.isoformat())
    currency = bar_currency.get(market_date.isoformat())
    currency_basis = (
        "VERIFIED_BAR"
        if currency == "USD"
        else "INFERRED_CURRENT_PROFILE"
        if currency is None and profile.get("currency") == "USD"
        else "NOT_VERIFIED"
    )
    if close is None:
        warnings.append(
            "No saved price on the requested date; no silent date substitution."
        )
    if currency_basis == "NOT_VERIFIED":
        warnings.append("Quote currency NOT_VERIFIED; no price/FCF arithmetic.")
    split_snapshot = snapshots.get("candidate_splits", snapshots.get("splits"))
    split_rows = _rows(source, split_snapshot, symbol) if split_snapshot else []
    splits = {
        "events": [
            {key: row.get(key) for key in ("date", "numerator", "denominator")}
            for row in split_rows
        ],
        "source": _provenance(split_snapshot) if split_snapshot else None,
        "basis": "UNVERIFIED; no adjustment applied to financial shares or prices",
    }
    normalization = selection.cohort == "NORMALIZATION_CONTROLS"
    if selection.company.sector in INCOMPARABLE_SECTORS:
        warnings.append("SECTOR_INCOMPARABILITY: ordinary FCF/debt may mislead.")
    latest = references[0] if references else None
    median_fps = (
        median(row["canonical_fcf_per_share"] for row in references)
        if len(references) == 3
        and all(row["canonical_fcf_per_share"] is not None for row in references)
        else None
    )
    if median_fps is None:
        warnings.append(
            "Three-year reference UNKNOWN: fewer than three usable annual denominators."
        )
    elif median_fps <= 0:
        warnings.append("Nonpositive median FCF/share: price/FCF comparison blocked.")
    if latest and latest["canonical_fcf_per_share"] is not None:
        if latest["canonical_fcf_per_share"] <= 0:
            warnings.append(
                "Nonpositive latest FCF/share: price/FCF comparison blocked."
            )
        elif median_fps is not None and median_fps > 0:
            warnings.append(
                f"Latest FCF/share / three-year median = "
                f"{latest['canonical_fcf_per_share'] / median_fps:.4f}; sustainability unproven."
            )

    def ratio(denominator: float | None, refs: list[dict[str, Any]]) -> float | None:
        if (
            close is None
            or denominator is None
            or denominator <= 0
            or currency_basis == "NOT_VERIFIED"
            or price_conflict
            or selection.company.sector in INCOMPARABLE_SECTORS
            or not refs
            or any(
                ref["definition_conflict"]
                or ref["provider_fcf_reconciliation_conflict"]
                or not ref["financial_currency_verified"]
                or not ref["filed_before_market_date"]
                for ref in refs
            )
        ):
            return None
        return close / denominator

    balance_snapshot = annual.get("annual_balance_sheet_statement")
    debt: dict[str, Any] = {}
    if balance_snapshot and latest:
        balance = _period(_rows(source, balance_snapshot, symbol), latest["period_end"])
        cash_balance = _number(balance, "cashAndCashEquivalents")
        investments = _number(balance, "shortTermInvestments")
        short = _number(balance, "shortTermDebt")
        long = _number(balance, "longTermDebt")
        total = _number(balance, "totalDebt")
        components = short + long if short is not None and long is not None else None
        debt = {
            "period_end": latest["period_end"],
            "short_plus_long_debt": components,
            "provider_total_debt": total,
            "cash": cash_balance,
            "short_term_investments": investments,
            "net_cash_using_total_debt": (
                cash_balance + investments - total
                if cash_balance is not None
                and investments is not None
                and total is not None
                else None
            ),
            "source": _provenance(balance_snapshot),
            "filing_date": balance.get("filingDate"),
        }
        if components is not None and total is not None and components != total:
            warnings.append("CONFLICTING_DEBT_DEFINITIONS; composition unresolved.")
    capital = detail.capital_efficiency[-1] if detail.capital_efficiency else None
    allocation = detail.latest_capital_allocation
    latest_owner = detail.owner_economics[-1] if detail.owner_economics else None
    improving = improving_economics_observations(detail.owner_economics)
    try:
        context = build_research_context(
            detail, project_underwriting(source.store, symbol)
        )
    except KeyError as exc:
        raise ValueError(
            f"{symbol}: existing Copy Research Context missing required field {exc}."
        ) from exc
    result = detail.screening
    questions = [
        "Is recent cash generation durable or working-capital/collection timing?",
        "What refinancing, covenant, liquidity, or impairment risks are missing?",
        "What growth/margin/reinvestment expectations does the dated price imply?",
        "What disconfirming evidence would invalidate deeper underwriting?",
    ]
    if result.gate is not None:
        questions.insert(
            0, f"What evidence resolves the existing {result.gate.value} gate?"
        )
    if any("CONFLICTING_CAPEX" in warning for warning in warnings):
        questions.append(
            "Reconcile PP&E spending with provider capitalExpenditure before interpreting multiples."
        )
    if any("CONFLICTING_DEBT" in warning for warning in warnings):
        questions.append("Reconcile debt components with provider totalDebt.")
    if normalization:
        questions.append(
            "Which sector-specific or expenditure definition should replace ordinary FCF?"
        )
    return {
        "ticker": symbol,
        "sector": selection.company.sector,
        "security_id": selection.company.security_id,
        "cik": selection.company.cik,
        "cohort": selection.cohort,
        "selection_reason": selection.selection_reason,
        "universe_observed_at": selection.company.universe_observed_at,
        "financial_observed_at": selection.company.fetched_at,
        "screening": {
            "priority": result.bucket.value,
            "coverage": result.coverage_class.value,
            "setup": result.setup_type.value,
            "gate": result.gate.value if result.gate else None,
            "rank_key": result.rank_key,
            "supporting_reasons": [r.value for r in result.supporting_reasons],
            "dimensions": {d.value: result.band(d).name for d in DIMENSION_ORDER},
            "limiting_reasons": [r.value for r in result.limiting_reasons],
            "coverage_reasons": [r.value for r in result.coverage_reasons],
        },
        "financial_references": references,
        "improvement_indicators": {
            "existing_review_financial_criteria": "MET"
            if improving
            else "NOT_MET_OR_INSUFFICIENT",
            "qualifying_fiscal_years": [row.fiscal_year for row in improving]
            if improving
            else [],
        },
        "latest_fcf_per_share": latest["canonical_fcf_per_share"] if latest else None,
        "three_year_median_fcf_per_share": median_fps,
        "latest_fcf_per_share_growth": latest_owner.fcf_per_share_growth
        if latest_owner
        else None,
        "annual_revenue": [
            {
                "period_end": row.revenue.period_end.isoformat(),
                "revenue": row.revenue.value,
            }
            for row in detail.owner_economics
            if row.revenue
        ],
        "latest_roic": capital.roic if capital else None,
        "sbc_to_fcf": allocation.sbc_over_fcf if allocation else None,
        "diluted_share_growth": latest_owner.diluted_share_growth
        if latest_owner
        else None,
        "canonical_net_cash_or_debt": capital.net_cash if capital else None,
        "capex_to_revenue": (
            latest_owner.capital_expenditures.value / latest_owner.revenue.value
            if latest_owner
            and latest_owner.capital_expenditures
            and latest_owner.revenue
            and latest_owner.revenue.value > 0
            else None
        ),
        "debt": debt,
        "splits": splits,
        "quote": {
            "market_date": market_date.isoformat(),
            "close": close,
            "bar_currency": currency,
            "currency_basis": currency_basis,
            "adjustment_basis": "UNVERIFIED",
            "source": _provenance(quote_snapshot) if quote_snapshot else None,
            "profile_currency": profile.get("currency"),
            "profile_exchange": profile.get("exchange"),
            "profile_source": _provenance(profile_snapshot)
            if profile_snapshot
            else None,
        },
        "latest_price_to_fcf": ratio(
            latest["canonical_fcf_per_share"] if latest else None,
            [latest] if latest else [],
        ),
        "median_price_to_fcf": ratio(median_fps, references),
        "valuation_status": "NOT_VERIFIED",
        "warnings": warnings,
        "research_questions": questions,
        "copy_research_context": json.loads(context.json_export),
        "research_handoff": HANDOFF,
    }


def build_candidate_report(
    source: WorkbenchSource, *, market_date: date
) -> dict[str, Any]:
    if market_date > datetime.now(UTC).date():
        raise ValueError("Market date cannot be in the future.")
    selections, selection_errors = select_candidates(source)
    cards: list[dict[str, Any]] = []
    for selection in selections:
        try:
            cards.append(
                candidate_worksheet(source, selection, market_date=market_date)
            )
        except (
            ValueError,
            TypeError,
            WorkbenchError,
            PersistenceError,
            UnderwritingError,
        ) as exc:
            cards.append(
                {
                    "ticker": selection.company.ticker,
                    "cohort": selection.cohort,
                    "error": str(exc),
                    "valuation_status": "NOT_VERIFIED",
                    "screening": {
                        "priority": selection.screening.bucket.value,
                        "gate": selection.screening.gate.value
                        if selection.screening.gate
                        else None,
                    },
                }
            )
    candidates = [
        card["ticker"]
        for card in cards
        if "error" not in card
        and card["cohort"] in ("COMPOUNDERS", "IMPROVING")
        and card["screening"]["gate"] is None
        and card["latest_fcf_per_share"] is not None
        and card["latest_fcf_per_share"] > 0
    ][:5]
    return {
        "market_date": market_date.isoformat(),
        "selection_errors": list(selection_errors),
        "selection_policy": (
            "Distinct controls reserved first, then financial gates, strong compounders, "
            "existing Improving Economics review; original Feature 7 rank_key within each. "
            "No price ranking, no fillers. Up to five ungated positive-FCF research cases, "
            "compounders before improving, not verified price opportunities."
        ),
        "limitations": (
            "Selection uses current persisted annual evidence, not historical-as-of evidence. "
            "No gate does not establish safety; a gate does not prove insolvency. "
            "Quarterly changes, refinancing/covenants, capitalized intangibles, and durable "
            "cash conversion require investigation. Price basis is explicitly UNVERIFIED."
        ),
        "research_candidates": candidates,
        "cards": cards,
        "handoff": HANDOFF,
    }


def format_candidate_report(report: dict[str, Any]) -> str:
    def fmt(value: Any) -> str:
        return (
            "UNKNOWN"
            if value is None
            else f"{value:,.4f}"
            if isinstance(value, float)
            else str(value)
        )

    sources: dict[int, dict[str, Any]] = {}

    def source_id(source: dict[str, Any] | None) -> str:
        if source is None:
            return "UNKNOWN"
        sources[source["snapshot_id"]] = source
        return str(source["snapshot_id"])

    def millions(value: float | None) -> str:
        return fmt(value / 1_000_000) if value is not None else "UNKNOWN"

    def percent(value: float | None) -> str:
        return f"{value * 100:.2f}%" if value is not None else "UNKNOWN"

    lines = [
        "---",
        "title: Price-Aware Candidate Review",
        "description: Bounded retrospective research worksheets with unresolved valuation evidence.",
        "---",
        "",
        "## Research scope",
        "",
        f"Requested market date: {report['market_date']}. Retrospective persisted evidence.",
        "FACT = source observation; CALCULATION = canonical engine or explicit ratio.",
        "All valuation comparisons NOT_VERIFIED. No Buy/Sell or intrinsic-value claim.",
        "Six-dimension band order: "
        + " / ".join(d.value for d in DIMENSION_ORDER)
        + ".",
        (
            "Amounts marked m are millions. In denominator tables, identical cash/income "
            "filing or acceptance dates appear once; source IDs remain separate."
        ),
        report["limitations"],
        "",
        report["selection_policy"],
        "",
        "Research attention (economics, NOT verified attractiveness): "
        + ", ".join(report["research_candidates"]),
    ]
    if report["selection_errors"]:
        lines.append("")
        lines.extend(
            f"- Selection limitation: {error}" for error in report["selection_errors"]
        )
    for cohort in (
        "FRAGILE_CONTROLS",
        "COMPOUNDERS",
        "IMPROVING",
        "NORMALIZATION_CONTROLS",
    ):
        lines.extend(["", f"## {cohort}", ""])
        lines.extend(
            [
                "| Company | Existing priority / gate | Close | Latest FCF/share | Median FCF/share | Latest / median P/FCF |",
                "| --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for card in report["cards"]:
            if card["cohort"] != cohort:
                continue
            s = card["screening"]
            if "error" in card:
                lines.append(
                    f"| {card['ticker']} | {s['priority']} / {s['gate'] or 'none'} | UNKNOWN | UNKNOWN | UNKNOWN | NOT_VERIFIED |"
                )
            else:
                lines.append(
                    f"| {card['ticker']} | {s['priority']} / {s['gate'] or 'none'} | "
                    f"{fmt(card['quote']['close'])} | {fmt(card['latest_fcf_per_share'])} | "
                    f"{fmt(card['three_year_median_fcf_per_share'])} | "
                    f"{fmt(card['latest_price_to_fcf'])} / {fmt(card['median_price_to_fcf'])} (NOT_VERIFIED) |"
                )
        lines.append("")
        for card in report["cards"]:
            if card["cohort"] != cohort:
                continue
            lines.extend([f"### {card['ticker']}", ""])
            if "error" in card:
                lines.append(
                    f"NOT_VERIFIED: {card['error']}; screening {card['screening']}."
                )
                continue
            s, q = card["screening"], card["quote"]
            lines.extend(
                [
                    f"- FACT: security ID {card['security_id']}; issuer CIK {card['cik'] or 'UNKNOWN'}.",
                    f"- CALCULATION: {s['priority']} / {s['coverage']}; gate {s['gate'] or 'none'}.",
                    "- Six dimensions: " + " / ".join(s["dimensions"].values()),
                    f"- CALCULATION: ROIC {percent(card['latest_roic'])}; SBC/FCF {percent(card['sbc_to_fcf'])}.",
                    (
                        f"- CALCULATION: existing improvement financial criteria "
                        f"{card['improvement_indicators']['existing_review_financial_criteria']}; "
                        f"qualifying years {card['improvement_indicators']['qualifying_fiscal_years']}; "
                        f"latest FCF/share growth {percent(card['latest_fcf_per_share_growth'])}."
                    ),
                    (
                        f"- CALCULATION: share growth {percent(card['diluted_share_growth'])}; "
                        f"CapEx/revenue {percent(card['capex_to_revenue'])}; "
                        f"canonical net cash/debt {millions(card['canonical_net_cash_or_debt'])}m."
                    ),
                    "- FACT: annual revenue (USD millions): "
                    + "; ".join(
                        f"{r['period_end']}={millions(r['revenue'])}"
                        for r in card["annual_revenue"]
                    ),
                    (
                        f"- FACT/CALCULATION: debt components {millions(card['debt'].get('short_plus_long_debt'))}m; "
                        f"provider totalDebt {millions(card['debt'].get('provider_total_debt'))}m; "
                        f"net cash using totalDebt {millions(card['debt'].get('net_cash_using_total_debt'))}m; "
                        f"period {card['debt'].get('period_end', 'UNKNOWN')}; "
                        f"filed {card['debt'].get('filing_date', 'UNKNOWN')}; "
                        f"source {source_id(card['debt'].get('source'))}."
                    ),
                    (
                        f"- FACT: close {fmt(q['close'])} on {q['market_date']}; "
                        f"bar currency {q['bar_currency'] or 'UNKNOWN'} ({q['currency_basis']}); adjustment UNVERIFIED; "
                        f"source {source_id(q['source'])}. Current profile "
                        f"{q['profile_currency'] or 'UNKNOWN'}/{q['profile_exchange'] or 'UNKNOWN'} "
                        f"(source {source_id(q['profile_source'])}), not historical attributes."
                    ),
                    "- FACT: split events "
                    + (
                        json.dumps(card["splits"]["events"])
                        if card["splits"]["source"] is not None
                        else "NOT_CAPTURED"
                    )
                    + f"; source {source_id(card['splits']['source'])}; no adjustment applied.",
                    "- Warnings: "
                    + "; ".join(
                        [
                            *s["limiting_reasons"],
                            *s["coverage_reasons"],
                            *card["warnings"],
                        ]
                    ),
                    "- HYPOTHESIS: further research may be useful, not evidence of cheapness. "
                    + " ".join(
                        question
                        for question in card["research_questions"]
                        if question
                        not in (
                            "Is recent cash generation durable or working-capital/collection timing?",
                            "What refinancing, covenant, liquidity, or impairment risks are missing?",
                            "What growth/margin/reinvestment expectations does the dated price imply?",
                            "What disconfirming evidence would invalidate deeper underwriting?",
                        )
                    )
                    + " Test durability, liquidity, expectations and disconfirming evidence using the handoff.",
                ]
            )
            lines.extend(
                [
                    "",
                    "| Fiscal year / end | FCF m / diluted shares m | Canonical / provider FCF/share | PP&E / provider CapEx m | Filed; accepted (cash/income) | Cash / income sources |",
                    "| --- | ---: | ---: | ---: | --- | --- |",
                ]
            )
            for ref in card["financial_references"]:
                lines.append(
                    f"| FY{ref['fiscal_year']} / {ref['period_end']} | "
                    f"{millions(ref['canonical_fcf'])} / {millions(ref['diluted_weighted_average_shares'])} | "
                    f"{fmt(ref['canonical_fcf_per_share'])} / {fmt(ref['provider_fcf_per_share'])} | "
                    f"{millions(ref['canonical_capex'])} / {millions(ref['provider_capitalExpenditure'])} | "
                    + " / ".join(
                        fmt(value) for value in dict.fromkeys(ref["filing_dates"])
                    )
                    + "; "
                    + " / ".join(
                        fmt(value) for value in dict.fromkeys(ref["acceptance_dates"])
                    )
                    + f" | {source_id(ref['cash_source'])} / {source_id(ref['share_source'])} |"
                )
            lines.append("")
    lines.extend(
        [
            "## Evidence source index",
            "",
            "Retrieval times below are distinct from filing dates and market dates.",
            "Acceptance timestamp timezones and contemporaneous financial vintages are not verified.",
            "",
            "| Snapshot | Endpoint | Retrieved UTC | SHA-256 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for snapshot_id, source in sorted(sources.items()):
        lines.append(
            f"| {snapshot_id} | {source['source_endpoint']} | "
            f"{source['fetched_at']} | {source['content_hash']} |"
        )
    lines.extend(["", report["handoff"]])
    return "\n".join(lines) + "\n"

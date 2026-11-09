"""Existing economic eligibility with independent conditional valuation attention."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, TypeGuard

from owner_lens.candidate_review import (
    INCOMPARABLE_SECTORS,
    CandidateSelection,
    _rows,
    candidate_worksheet,
)
from owner_lens.canonical import CanonicalDataError
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.screening import (
    DimensionBand,
    ScreeningBucket,
    ScreeningDimension,
    ScreeningResult,
    SetupType,
)
from owner_lens.uncertainty_fragility import COVERAGE_GATES, UncertaintyFragilityReview
from owner_lens.underwriting import UnderwritingError
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    improving_economics_review_candidates,
)

DISPLAY_LIMIT = 8


@dataclass(frozen=True)
class ValuationAttention:
    latest_multiple: float | None
    median_multiple: float | None
    latest_yield: float | None
    median_yield: float | None
    denominator_ratio: float | None
    ordering_eligible: bool
    reason: str


def _positive(value: Any) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def valuation_attention(
    selection: CandidateSelection,
    card: dict[str, Any],
    review: UncertaintyFragilityReview | None,
    market_date: str | None,
) -> ValuationAttention:
    """Conditional arithmetic and strict three-year ordering eligibility."""
    latest = card.get("latest_price_to_fcf")
    normalized = card.get("median_price_to_fcf")
    latest = float(latest) if _positive(latest) else None
    normalized = float(normalized) if _positive(normalized) else None
    fps = card.get("latest_fcf_per_share")
    median_fps = card.get("three_year_median_fcf_per_share")
    sensitivity = fps / median_fps if _positive(fps) and _positive(median_fps) else None
    refs = card.get("financial_references", [])
    years = sorted(ref["fiscal_year"] for ref in refs)
    history_ok = (
        len(refs) == 3
        and len(set(years)) == 3
        and years[-1] - years[0] == 2
        and all(_positive(ref.get("canonical_fcf_per_share")) for ref in refs)
    )
    if not _positive(fps):
        latest = None
    if not history_ok or not _positive(median_fps):
        normalized = None
    if (
        selection.screening.gate is not None
        or selection.company.sector in INCOMPARABLE_SECTORS
        or not selection.company.sector
    ):
        latest = normalized = None
    quote = card.get("quote", {})
    eligible = False
    if selection.screening.gate is not None:
        reason = "Unranked: existing gate; survival review first."
    elif (
        selection.company.sector in INCOMPARABLE_SECTORS or not selection.company.sector
    ):
        reason = "Unranked: generic FCF sector comparability unsupported or unknown."
    elif "error" in card:
        reason = "Unranked: " + card["error"]
    elif review is None or review.financial_state == "INSUFFICIENT_EVIDENCE":
        reason = "Unranked: insufficient financial-resilience evidence."
    elif quote.get("currency_basis") not in (
        "VERIFIED_BAR",
        "INFERRED_CURRENT_PROFILE",
    ):
        reason = "Unranked: currency compatibility not supported."
    elif not history_ok:
        reason = (
            "Unranked: three consecutive positive annual FCF/share references required."
        )
    elif normalized is None or latest is None:
        reason = "Unranked: supported latest and median comparisons required; inspect definition/filing conflicts."
    elif market_date is None or quote.get("market_date") != market_date:
        reason = "Unranked: price date differs from the common attention date."
    else:
        eligible = True
        reason = "Conditional ordering: lower three-year-median P/FCF within sector; not undervaluation."
    return ValuationAttention(
        latest,
        normalized,
        1 / latest if latest else None,
        1 / normalized if normalized else None,
        sensitivity,
        eligible,
        reason,
    )


def attention_date(cards: Mapping[str, dict[str, Any]]) -> str | None:
    """Most recent persisted opportunity quote date; older quotes stay unranked."""
    dates = [
        card["quote"]["market_date"]
        for card in cards.values()
        if "error" not in card and card.get("quote", {}).get("close") is not None
    ]
    return max(dates) if dates else None


def attention_order(
    selections: Sequence[CandidateSelection],
    cards: Mapping[str, dict[str, Any]],
    reviews: Mapping[str, UncertaintyFragilityReview],
    market_date: str | None,
) -> tuple[CandidateSelection, ...]:
    """Rank supported cases within sector, then retain unranked original order."""

    def key(item: CandidateSelection) -> tuple[Any, ...]:
        assessment = valuation_attention(
            item,
            cards.get(item.company.ticker, {"error": "No saved valuation worksheet."}),
            reviews.get(item.company.ticker),
            market_date,
        )
        return (
            (
                0,
                item.company.sector,
                assessment.median_multiple,
                item.screening.rank_key,
            )
            if assessment.ordering_eligible
            else (1, "", 0, item.screening.rank_key)
        )

    return tuple(sorted(selections, key=key))


@dataclass(frozen=True)
class DiscoveryLanes:
    compounders: tuple[CandidateSelection, ...]
    improving: tuple[CandidateSelection, ...]
    fragility: tuple[CandidateSelection, ...]


def discovery_lanes(
    companies: Sequence[PersistedCompany],
    results: Sequence[ScreeningResult],
    owners: Mapping[str, Sequence[OwnerEconomicsRow]],
) -> DiscoveryLanes:
    """Reuse M2-A3 compounder criteria and M2-A1 eligibility; gates never qualify."""
    by_ticker = {company.ticker: company for company in companies}
    compounders: list[CandidateSelection] = []
    fragility: list[CandidateSelection] = []
    for result in sorted(results, key=lambda item: item.rank_key):
        company = by_ticker[result.ticker]
        if result.gate is not None and result.gate not in COVERAGE_GATES:
            fragility.append(
                CandidateSelection(
                    "FRAGILE_CONTROLS", company, result, "Existing survival gate"
                )
            )
        elif (
            result.gate is None
            and company.sector not in INCOMPARABLE_SECTORS
            and result.setup_type is SetupType.COMPOUNDER
            and result.bucket
            in (ScreeningBucket.HIGH_PRIORITY, ScreeningBucket.WORTH_UNDERWRITING)
            and all(
                result.band(d) is DimensionBand.STRONG
                for d in (
                    ScreeningDimension.BUSINESS_QUALITY,
                    ScreeningDimension.CAPITAL_EFFICIENCY,
                    ScreeningDimension.PER_SHARE_COMPOUNDING,
                )
            )
        ):
            compounders.append(
                CandidateSelection(
                    "COMPOUNDERS",
                    company,
                    result,
                    "Strong quality, capital returns and per-share economics",
                )
            )
    improving = tuple(
        CandidateSelection(
            "IMPROVING",
            item.company,
            item.screening,
            "Rising recent cash flow and cash flow per share",
        )
        for item in improving_economics_review_candidates(companies, results, owners)
        if item.screening.gate is None
        and item.company.sector not in INCOMPARABLE_SECTORS
    )
    return DiscoveryLanes(tuple(compounders), improving, tuple(fragility))


def discovery_price_card(
    source: WorkbenchSource,
    selection: CandidateSelection,
) -> dict[str, Any]:
    """Use latest saved market date, disclosing per-company dates and conflicts."""
    if selection.company.provider != "fmp":
        return {
            "error": "Candidate price/share comparability is supported here only for persisted FMP evidence."
        }
    if (
        not isinstance(source.store, SqliteStore)
        or selection.company.security_id is None
    ):
        raise WorkbenchError("Discovery requires persisted security identity.")
    dates: list[date] = []
    try:
        for dataset in ("candidate_price", "historical_price", "eod_price"):
            for snapshot in source.store.list_fmp_evidence_snapshots(
                selection.company.security_id, dataset
            ):
                for row in _rows(source, snapshot, selection.company.ticker):
                    raw = row.get("date")
                    if not isinstance(raw, str):
                        raise TypeError("Saved price date is missing or malformed.")
                    day = date.fromisoformat(raw)
                    if day.isoformat() != raw:
                        raise ValueError("Saved price date is not YYYY-MM-DD.")
                    if day <= datetime.now(UTC).date():
                        dates.append(day)
        if not dates:
            return {
                "error": "No persisted dated price; economics only, valuation unresolved."
            }
        return candidate_worksheet(source, selection, market_date=max(dates))
    except (
        CanonicalDataError,
        PersistenceError,
        WorkbenchError,
        UnderwritingError,
        ValueError,
        TypeError,
    ) as exc:
        return {"error": f"Price/valuation evidence unresolved: {exc}"}


def price_summary(card: dict[str, Any]) -> str:
    """Never convert a conditional multiple into a cheap/expensive verdict."""
    if "error" in card:
        return card["error"]
    quote = card["quote"]
    close = quote["close"]
    currency = (
        "USD (inferred)"
        if quote.get("currency_basis") == "INFERRED_CURRENT_PROFILE"
        else quote.get("bar_currency") or "currency unverified"
    )
    summary = (
        f"{quote['market_date']}: close {close:,.2f} {currency}"
        if close is not None
        else f"{quote['market_date']}: close unavailable"
    )
    latest, median = card["latest_price_to_fcf"], card["median_price_to_fcf"]
    if latest is None and median is None:
        return summary + "; price/FCF unresolved"
    ratios = []
    if latest is not None:
        ratios.append(f"latest {latest:.1f}x")
    if median is not None:
        ratios.append(f"3yr median {median:.1f}x")
    return summary + "; conditional P/FCF " + ", ".join(ratios) + " (unverified)"

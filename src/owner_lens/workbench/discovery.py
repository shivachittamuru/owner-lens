"""Bounded discovery presentation of existing criteria, never a new ranking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from owner_lens.candidate_review import (
    INCOMPARABLE_SECTORS,
    CandidateSelection,
    _rows,
    candidate_worksheet,
)
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
from owner_lens.uncertainty_fragility import COVERAGE_GATES
from owner_lens.underwriting import UnderwritingError
from owner_lens.workbench.data import (
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    improving_economics_review_candidates,
)

DISPLAY_LIMIT = 8


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
    summary = (
        f"{quote['market_date']}: close {close:,.2f}"
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

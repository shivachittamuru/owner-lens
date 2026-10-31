"""FMP S&P 500 membership refresh orchestration for Feature 8A1."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from owner_lens.fmp import FmpClient, FmpConstituents, FmpError
from owner_lens.persistence import (
    PersistenceError,
    SqliteStore,
    UniverseConstituentRecord,
    UniverseRefreshRunRecord,
    UniverseSnapshotRecord,
    compute_content_hash,
)

__all__ = [
    "SP500_PROVIDER",
    "SP500_REFRESH_DATASETS",
    "UniverseRefreshError",
    "UniverseRefreshSummary",
    "refresh_sp500_universe",
]

SP500_PROVIDER = "fmp"
SP500_REFRESH_DATASETS = (
    "annual_income_statement",
    "annual_balance_sheet_statement",
    "annual_cash_flow_statement",
    "quarterly_income_statement",
    "quarterly_balance_sheet_statement",
    "quarterly_cash_flow_statement",
    "eod_price",
    "annual_analyst_estimates",
    "quarterly_analyst_estimates",
)
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.\-]*")


class UniverseRefreshError(ValueError):
    """Raised when a requested bounded refresh does not match the universe."""


@dataclass(frozen=True)
class UniverseRefreshSummary:
    """Summary of a completed FMP S&P 500 universe refresh."""

    run_id: str
    snapshot_id: int
    content_hash: str
    member_count: int
    state_symbol_count: int
    state_row_count: int
    new_snapshot: bool


def _normalize_requested_symbols(symbols: tuple[str, ...] | None) -> tuple[str, ...]:
    if symbols is None:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise UniverseRefreshError(f"Invalid ticker symbol: {raw_symbol!r}.")
        if symbol in seen:
            raise UniverseRefreshError(f"Duplicate ticker symbol: {symbol}.")
        normalized.append(symbol)
        seen.add(symbol)
    if not normalized:
        raise UniverseRefreshError("Provide at least one ticker with --tickers.")
    return tuple(normalized)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def refresh_sp500_universe(
    *,
    client: FmpClient,
    store: SqliteStore,
    tickers: tuple[str, ...] | None = None,
) -> UniverseRefreshSummary:
    """Fetch and persist one immutable S&P 500 membership version.

    A ticker subset limits which securities receive initial future dataset
    refresh-state rows. The complete provider membership response is always
    validated and persisted.
    """
    requested = _normalize_requested_symbols(tickers)
    run_id = str(uuid.uuid4())
    store.start_universe_refresh_run(
        UniverseRefreshRunRecord(
            run_id=run_id,
            started_at=_now(),
            requested_symbols=requested,
        )
    )
    snapshot_id: int | None = None
    try:
        response: FmpConstituents = client.get_sp500_constituents(refresh=True)
        members = tuple(
            UniverseConstituentRecord(
                symbol=member.symbol,
                name=member.name,
                cik=member.cik,
                sector=member.sector,
                subsector=member.subsector,
            )
            for member in response.members
        )
        member_symbols = {member.symbol for member in members}
        missing = sorted(set(requested) - member_symbols)
        if missing:
            raise UniverseRefreshError(
                f"Requested tickers are not in the current FMP S&P 500 response: "
                f"{', '.join(missing)}."
            )

        observed_at = _now()
        raw_payload = response.raw_payload
        content_hash = compute_content_hash(raw_payload)
        snapshot = UniverseSnapshotRecord(
            provider=SP500_PROVIDER,
            observed_at=observed_at,
            source_uri=response.source_url,
            content_hash=content_hash,
        )
        state_symbols = requested or tuple(member.symbol for member in members)
        snapshot_id, new_snapshot, state_row_count = store.save_universe_snapshot(
            snapshot,
            members,
            raw_payload=raw_payload,
            state_symbols=state_symbols,
            datasets=SP500_REFRESH_DATASETS,
            created_at=observed_at,
        )
        store.finish_universe_refresh_run(
            run_id,
            status="SUCCEEDED",
            completed_at=_now(),
            snapshot_id=snapshot_id,
        )
        return UniverseRefreshSummary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
            member_count=len(members),
            state_symbol_count=len(state_symbols),
            state_row_count=state_row_count,
            new_snapshot=new_snapshot,
        )
    except (FmpError, PersistenceError, UniverseRefreshError) as exc:
        store.finish_universe_refresh_run(
            run_id,
            status="FAILED",
            completed_at=_now(),
            snapshot_id=snapshot_id,
            error=str(exc),
        )
        raise

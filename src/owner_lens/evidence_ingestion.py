"""Persisted FMP Premium evidence acquisition for Feature 8A2."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, overload

from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.fmp import (
    FMP_BASE_URL,
    FmpAuthenticationError,
    FmpClient,
    FmpConstituent,
    FmpError,
    FmpEvidencePayload,
    FmpPlanRestrictionError,
    FmpRateLimitError,
    FmpStatements,
    MalformedFmpResponseError,
    _validate_estimate_rows,
    _validate_historical_price_rows,
    _validate_historical_range,
    _validate_market_rows,
    _validate_period_rows,
)
from owner_lens.fmp_adapter import FMP_FIELD_MAP, canonical_history_from_fmp
from owner_lens.persistence import (
    FmpCanonicalCoverageRecord,
    FmpCanonicalFactRecord,
    FmpCanonicalHistoryRecord,
    FmpEodPriceRecord,
    FmpEstimateRecord,
    FmpEvidenceSnapshotRecord,
    FmpHistoricalPriceRecord,
    PersistenceError,
    SqliteStore,
    compute_content_hash,
)

__all__ = [
    "ANNUAL_ESTIMATE_LIMIT",
    "ANNUAL_STATEMENT_LIMIT",
    "QUARTERLY_ESTIMATE_LIMIT",
    "QUARTERLY_STATEMENT_LIMIT",
    "EvidenceRefreshSummary",
    "HistoricalPricePilotResult",
    "refresh_sp500_evidence",
    "retrieve_candidate_prices",
    "run_historical_price_pilot",
]

ANNUAL_STATEMENT_LIMIT = 15
QUARTERLY_STATEMENT_LIMIT = 8
ANNUAL_ESTIMATE_LIMIT = 3
QUARTERLY_ESTIMATE_LIMIT = 4
_STATEMENT_FRESHNESS = timedelta(days=30)
_DAILY_FRESHNESS = timedelta(hours=24)
_STATEMENT_NAMES = ("income", "balance_sheet", "cash_flow")
_FMP_PERIOD_BY_DATASET_PERIOD = {
    "annual": "annual",
    "quarterly": "quarter",
}
HISTORICAL_PRICE_PILOT_SYMBOLS = ("TYL", "ADSK", "NVDA")


@dataclass(frozen=True)
class EvidenceRefreshSummary:
    """Counts for one bounded or full-universe FMP evidence refresh."""

    securities: int
    refreshed: int
    skipped: int
    unsupported: int
    failed: int
    canonical_histories: int

    @property
    def partial(self) -> bool:
        return self.failed > 0 or self.unsupported > 0


@dataclass(frozen=True)
class HistoricalPricePilotResult:
    """Auditable outcome for one member of the three-symbol historical-price pilot."""

    symbol: str
    security_id: int
    observation_count: int
    first_market_date: str | None
    last_market_date: str | None
    historical_snapshot_id: int
    historical_content_hash: str
    profile_snapshot_id: int
    profile_content_hash: str
    splits_snapshot_id: int
    splits_content_hash: str
    split_events: tuple[tuple[str, int, int], ...]
    overlap_matches: int
    overlap_conflicts: tuple[str, ...]
    revision_conflicts: tuple[str, ...]


@dataclass(frozen=True)
class _TaskResult:
    dataset: str
    status: str
    snapshot: FmpEvidenceSnapshotRecord | None
    rows: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    fetched: bool = False
    authentication_failed: bool = False
    rate_limit_failed: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _fresh(snapshot: FmpEvidenceSnapshotRecord, max_age: timedelta) -> bool:
    age = _now() - _parse_timestamp(snapshot.fetched_at)
    return timedelta(0) <= age < max_age


def _params_json(payload: FmpEvidencePayload) -> str:
    return json.dumps(
        dict(payload.request_parameters), sort_keys=True, separators=(",", ":")
    )


def _source_url(snapshot: FmpEvidenceSnapshotRecord) -> str:
    params = json.loads(snapshot.request_parameters)
    query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    return f"{FMP_BASE_URL}/{snapshot.source_endpoint}?{query}&apikey=<redacted>"


def _stored_payload(
    store: SqliteStore,
    snapshot: FmpEvidenceSnapshotRecord,
    *,
    symbol: str,
) -> FmpEvidencePayload:
    raw_payload = store.get_raw_snapshot(snapshot.content_hash)
    try:
        payload = json.loads(raw_payload)
    except (ValueError, TypeError):
        raise MalformedFmpResponseError(
            f"Stored FMP payload {snapshot.content_hash} is not valid JSON."
        ) from None
    if snapshot.dataset.endswith("_statement"):
        rows = _validate_period_rows(
            payload,
            snapshot.source_endpoint,
            symbol,
            snapshot.period_type,
            allow_empty=True,
        )
    elif snapshot.dataset == "eod_price":
        rows = _validate_market_rows(payload, snapshot.source_endpoint, symbol)
    else:
        rows = _validate_estimate_rows(
            payload, snapshot.source_endpoint, symbol, allow_empty=True
        )
    return FmpEvidencePayload(
        endpoint=snapshot.source_endpoint,
        request_parameters=tuple(
            sorted(
                (str(key), str(value))
                for key, value in json.loads(snapshot.request_parameters).items()
            )
        ),
        source_url=_source_url(snapshot),
        fetched_at=snapshot.fetched_at,
        rows=rows,
        raw_payload=raw_payload,
    )


def _evidence_record(
    security_id: int,
    dataset: str,
    period_type: str,
    payload: FmpEvidencePayload,
    *,
    evidence_kind: str = "FACT",
) -> FmpEvidenceSnapshotRecord:
    return FmpEvidenceSnapshotRecord(
        security_id=security_id,
        dataset=dataset,
        period_type=period_type,
        source_endpoint=payload.endpoint,
        request_parameters=_params_json(payload),
        fetched_at=payload.fetched_at,
        content_hash=compute_content_hash(payload.raw_payload),
        evidence_kind=evidence_kind,
    )


def _load_statement(
    store: SqliteStore,
    security_id: int,
    symbol: str,
    period: str,
    statement: str,
) -> tuple[FmpEvidenceSnapshotRecord | None, tuple[dict[str, Any], ...]]:
    dataset = f"{period}_{statement}_statement"
    snapshot = store.get_latest_fmp_evidence_snapshot(security_id, dataset)
    if snapshot is None:
        return None, ()
    payload = _stored_payload(store, snapshot, symbol=symbol)
    return snapshot, payload.rows


def _update_state(
    store: SqliteStore,
    security_id: int,
    dataset: str,
    status: str,
    *,
    error: str | None = None,
) -> None:
    store.update_security_refresh_state(
        security_id,
        dataset,
        status=status,
        updated_at=_iso(_now()),
        last_error=error,
    )


def _refresh_task(
    *,
    client: FmpClient,
    store: SqliteStore,
    security_id: int,
    symbol: str,
    dataset: str,
    period_type: str,
    force: bool,
    loader: Callable[[], FmpEvidencePayload],
    freshness: timedelta,
    evidence_kind: str = "FACT",
    globally_restricted: set[str],
) -> _TaskResult:
    latest = store.get_latest_fmp_evidence_snapshot(security_id, dataset)
    state = store.get_security_refresh_state(security_id, dataset)
    if state is not None and state.status == "RUNNING":
        _update_state(
            store,
            security_id,
            dataset,
            "PENDING",
            error="Recovered an interrupted refresh attempt.",
        )
    if dataset in globally_restricted:
        restriction_reason = "FMP plan does not provide this evidence endpoint."
        try:
            rows = (
                _stored_payload(store, latest, symbol=symbol).rows
                if latest is not None
                else ()
            )
        except (MalformedFmpResponseError, PersistenceError) as exc:
            _update_state(store, security_id, dataset, "FAILED", error=str(exc))
            return _TaskResult(dataset, "FAILED", latest, error=str(exc))
        _update_state(
            store, security_id, dataset, "UNSUPPORTED", error=restriction_reason
        )
        return _TaskResult(
            dataset, "UNSUPPORTED", latest, rows, error=restriction_reason
        )

    if latest is not None and not force and _fresh(latest, freshness):
        cache_error: str | None = None
        try:
            cached = _stored_payload(store, latest, symbol=symbol)
        except (MalformedFmpResponseError, PersistenceError) as exc:
            cached = None
            cache_error = str(exc)
        if cached is not None:
            status = "UNSUPPORTED" if not cached.rows else "SUCCEEDED"
            cached_reason: str | None = (
                "Provider returned no rows." if not cached.rows else None
            )
            _update_state(store, security_id, dataset, status, error=cached_reason)
            return _TaskResult(dataset, status, latest, cached.rows, fetched=False)
        if cache_error is not None:
            _update_state(store, security_id, dataset, "FAILED", error=cache_error)

    _update_state(store, security_id, dataset, "RUNNING")
    try:
        payload: FmpEvidencePayload = loader()
        record = _evidence_record(
            security_id,
            dataset,
            period_type,
            payload,
            evidence_kind=evidence_kind,
        )
        _snapshot_id, _inserted, persisted = store.save_fmp_evidence_snapshot(
            record, raw_payload=payload.raw_payload
        )
        status = "UNSUPPORTED" if not payload.rows else "SUCCEEDED"
        fetch_reason: str | None = (
            "Provider returned no rows." if not payload.rows else None
        )
        _update_state(store, security_id, dataset, status, error=fetch_reason)
        return _TaskResult(dataset, status, persisted, payload.rows, fetched=True)
    except FmpPlanRestrictionError as exc:
        globally_restricted.add(dataset)
        _update_state(store, security_id, dataset, "UNSUPPORTED", error=str(exc))
        return _TaskResult(dataset, "UNSUPPORTED", latest, error=str(exc), fetched=True)
    except FmpAuthenticationError as exc:
        _update_state(store, security_id, dataset, "FAILED", error=str(exc))
        return _TaskResult(
            dataset,
            "FAILED",
            latest,
            error=str(exc),
            fetched=True,
            authentication_failed=True,
        )
    except FmpRateLimitError as exc:
        _update_state(store, security_id, dataset, "FAILED", error=str(exc))
        return _TaskResult(
            dataset,
            "FAILED",
            latest,
            error=str(exc),
            fetched=True,
            rate_limit_failed=True,
        )
    except FmpError as exc:
        _update_state(store, security_id, dataset, "FAILED", error=str(exc))
        return _TaskResult(dataset, "FAILED", latest, error=str(exc), fetched=True)


@overload
def _numeric(
    row: dict[str, Any], key: str, *, integer: Literal[True]
) -> int | None: ...


@overload
def _numeric(
    row: dict[str, Any], key: str, *, integer: Literal[False] = False
) -> float | None: ...


def _numeric(
    row: dict[str, Any], key: str, *, integer: bool = False
) -> float | int | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedFmpResponseError(
            f"FMP analyst estimate field {key} is not numeric: {value!r}."
        )
    if not math.isfinite(float(value)):
        raise MalformedFmpResponseError(
            f"FMP analyst estimate field {key} is not finite."
        )
    if integer:
        if not float(value).is_integer() or value < 0:
            raise MalformedFmpResponseError(
                f"FMP analyst estimate field {key} is not a non-negative integer."
            )
        return int(value)
    return float(value)


def _estimate_records(
    snapshot_id: int,
    rows: tuple[dict[str, Any], ...],
    period: str,
) -> tuple[FmpEstimateRecord, ...]:
    today = _now().date()
    limit = ANNUAL_ESTIMATE_LIMIT if period == "annual" else QUARTERLY_ESTIMATE_LIMIT
    eligible = sorted(
        (row for row in rows if date.fromisoformat(str(row["date"])) >= today),
        key=lambda row: str(row["date"]),
    )[:limit]
    estimates: list[FmpEstimateRecord] = []
    for row in eligible:
        estimates.append(
            FmpEstimateRecord(
                snapshot_id=snapshot_id,
                target_date=str(row["date"]),
                revenue_low=_numeric(row, "revenueLow"),
                revenue_average=_numeric(row, "revenueAvg"),
                revenue_high=_numeric(row, "revenueHigh"),
                revenue_analyst_count=_numeric(row, "numAnalystsRevenue", integer=True),
                eps_low=_numeric(row, "epsLow"),
                eps_average=_numeric(row, "epsAvg"),
                eps_high=_numeric(row, "epsHigh"),
                eps_analyst_count=_numeric(row, "numAnalystsEps", integer=True),
            )
        )
    return tuple(estimates)


def _save_price(
    store: SqliteStore,
    security_id: int,
    snapshot_id: int,
    rows: tuple[dict[str, Any], ...],
) -> bool:
    today = _now().date()
    valid: list[tuple[date, float, str, str | None]] = []
    for row in rows:
        market_date = date.fromisoformat(str(row["date"]))
        if market_date > today:
            raise MalformedFmpResponseError(
                f"FMP EOD price has future market date {market_date}."
            )
        source_field = "close" if row.get("close") is not None else "price"
        value = row.get(source_field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise MalformedFmpResponseError(
                f"FMP EOD close for {market_date} is invalid: {value!r}."
            )
        currency = row.get("currency", row.get("reportedCurrency"))
        if currency is not None and not isinstance(currency, str):
            raise MalformedFmpResponseError("FMP EOD price currency is invalid.")
        valid.append((market_date, float(value), source_field, currency))
    if not valid:
        return False
    market_date, close, source_field, currency = max(valid, key=lambda item: item[0])
    store.save_fmp_eod_price(
        FmpEodPriceRecord(
            snapshot_id=snapshot_id,
            security_id=security_id,
            market_date=market_date.isoformat(),
            close=close,
            source_field=source_field,
            currency=currency,
        )
    )
    return True


def _pilot_members_and_ids(
    store: SqliteStore,
) -> dict[str, tuple[FmpConstituent, int]]:
    snapshot = store.get_latest_universe_snapshot("fmp")
    if snapshot is None or snapshot.snapshot_id is None:
        raise PersistenceError("No persisted FMP S&P 500 snapshot is available.")
    records = store.list_universe_members(snapshot.snapshot_id)
    security_ids = store.universe_security_ids(snapshot.snapshot_id)
    members = {
        record.symbol: (
            FmpConstituent(
                symbol=record.symbol,
                name=record.name,
                cik=record.cik,
                sector=record.sector,
                subsector=record.subsector,
            ),
            security_ids[record.symbol],
        )
        for record in records
        if record.symbol in HISTORICAL_PRICE_PILOT_SYMBOLS
    }
    missing = set(HISTORICAL_PRICE_PILOT_SYMBOLS) - set(members)
    if missing:
        raise PersistenceError(
            "Pilot symbols are missing from the persisted FMP universe: "
            + ", ".join(sorted(missing))
        )
    return members


def _profile_cik(row: dict[str, Any], symbol: str) -> str | None:
    value = row.get("cik")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedFmpResponseError(
            f"FMP profile CIK for {symbol} is invalid: {value!r}."
        )
    digits = str(value).strip()
    if not digits.isdigit() or len(digits) > 10:
        raise MalformedFmpResponseError(
            f"FMP profile CIK for {symbol} is invalid: {value!r}."
        )
    return digits.zfill(10)


def _validated_pilot_prices(
    symbol: str,
    rows: tuple[dict[str, Any], ...],
    *,
    start_date: date,
    end_date: date,
) -> tuple[tuple[str, float, str], ...]:
    _validate_historical_range(start_date, end_date)
    validated = _validate_historical_price_rows(
        list(rows),
        "historical-price-eod/full",
        symbol,
        start_date,
        end_date,
    )
    records: list[tuple[str, float, str]] = []
    for row in validated:
        market_date = date.fromisoformat(str(row["date"])).isoformat()
        source_field = "close" if row.get("close") is not None else "price"
        records.append((market_date, float(row[source_field]), source_field))
    return tuple(records)


def _validate_pilot_payload_symbol(payload: FmpEvidencePayload, symbol: str) -> None:
    for row in payload.rows:
        row_symbol = row.get("symbol")
        if not isinstance(row_symbol, str) or row_symbol.strip().upper() != symbol:
            raise MalformedFmpResponseError(
                f"FMP {payload.endpoint} row identifies {row_symbol!r}, not {symbol}."
            )


def _persist_pilot_snapshot(
    store: SqliteStore,
    *,
    security_id: int,
    dataset: str,
    period_type: str,
    payload: FmpEvidencePayload,
) -> FmpEvidenceSnapshotRecord:
    _snapshot_id, _inserted, snapshot = store.save_fmp_evidence_snapshot(
        _evidence_record(security_id, dataset, period_type, payload),
        raw_payload=payload.raw_payload,
    )
    return snapshot


def _existing_eod_prices(
    store: SqliteStore, security_id: int, symbol: str
) -> dict[str, float]:
    snapshot = store.get_latest_fmp_evidence_snapshot(security_id, "eod_price")
    if snapshot is None:
        return {}
    try:
        raw = store.get_raw_snapshot(snapshot.content_hash)
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise MalformedFmpResponseError(
            f"Stored EOD snapshot {snapshot.content_hash} is invalid JSON: {exc}."
        ) from None
    rows = _validate_market_rows(payload, snapshot.source_endpoint, symbol)
    prices: dict[str, float] = {}
    for row in rows:
        market_date = date.fromisoformat(str(row["date"])).isoformat()
        price = row.get("price", row.get("close"))
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(float(price))
            or price <= 0
        ):
            raise MalformedFmpResponseError(
                f"Stored EOD price for {symbol} on {market_date} is invalid."
            )
        prices[market_date] = float(price)
    return prices


def run_historical_price_pilot(
    *,
    client: FmpClient,
    store: SqliteStore,
    start_date: date,
    end_date: date,
) -> tuple[HistoricalPricePilotResult, ...]:
    """Persist bounded historical price evidence for TYL, ADSK, and NVDA only."""
    members = _pilot_members_and_ids(store)
    results: list[HistoricalPricePilotResult] = []
    for symbol in HISTORICAL_PRICE_PILOT_SYMBOLS:
        member, security_id = members[symbol]
        profile_payload = client.get_profile_evidence(symbol)
        _validate_pilot_payload_symbol(profile_payload, symbol)
        if len(profile_payload.rows) != 1:
            raise MalformedFmpResponseError(
                f"FMP profile for {symbol} did not return exactly one row."
            )
        current_cik = _profile_cik(profile_payload.rows[0], symbol)
        if (
            member.cik is not None
            and current_cik is not None
            and member.cik != current_cik
        ):
            raise MalformedFmpResponseError(
                f"FMP profile CIK for {symbol} ({current_cik}) does not match "
                f"persisted security CIK ({member.cik})."
            )
        profile_snapshot = _persist_pilot_snapshot(
            store,
            security_id=security_id,
            dataset="profile",
            period_type="current",
            payload=profile_payload,
        )

        splits_payload = client.get_splits_evidence(
            symbol, start_date=start_date, end_date=end_date
        )
        _validate_pilot_payload_symbol(splits_payload, symbol)
        splits_snapshot = _persist_pilot_snapshot(
            store,
            security_id=security_id,
            dataset="splits",
            period_type="historical",
            payload=splits_payload,
        )

        historical_payload = client.get_historical_price_evidence(
            symbol, start_date=start_date, end_date=end_date
        )
        _validate_pilot_payload_symbol(historical_payload, symbol)
        price_records = _validated_pilot_prices(
            symbol,
            historical_payload.rows,
            start_date=start_date,
            end_date=end_date,
        )
        historical_snapshot = _persist_pilot_snapshot(
            store,
            security_id=security_id,
            dataset="historical_price",
            period_type="historical",
            payload=historical_payload,
        )
        prior_history = store.list_fmp_historical_prices(security_id)
        prior_prices_by_date: dict[str, set[float]] = {}
        for prior in prior_history:
            prior_prices_by_date.setdefault(prior.market_date, set()).add(prior.price)
        revision_conflicts_list: list[str] = []
        for market_date, price, _source_field in price_records:
            prior_prices = prior_prices_by_date.get(market_date)
            if prior_prices is not None and prior_prices != {price}:
                revision_conflicts_list.append(
                    f"{market_date}: previous {sorted(prior_prices)} vs new {price}"
                )
        revision_conflicts = tuple(sorted(revision_conflicts_list))
        store.save_fmp_historical_prices(
            tuple(
                FmpHistoricalPriceRecord(
                    snapshot_id=_snapshot_id(historical_snapshot),
                    security_id=security_id,
                    market_date=market_date,
                    price=price,
                    source_field=source_field,
                )
                for market_date, price, source_field in price_records
            )
        )

        old_prices = _existing_eod_prices(store, security_id, symbol)
        fetched_prices = {
            market_date: price for market_date, price, _field in price_records
        }
        overlapping_dates = set(old_prices) & set(fetched_prices)
        conflicts = tuple(
            sorted(
                market_date
                for market_date in overlapping_dates
                if old_prices[market_date] != fetched_prices[market_date]
            )
        )
        split_events = tuple(
            sorted(
                (
                    str(row["date"]),
                    int(row["numerator"]),
                    int(row["denominator"]),
                )
                for row in splits_payload.rows
            )
        )
        ordered_dates = sorted(fetched_prices)
        results.append(
            HistoricalPricePilotResult(
                symbol=symbol,
                security_id=security_id,
                observation_count=len(price_records),
                first_market_date=ordered_dates[0] if ordered_dates else None,
                last_market_date=ordered_dates[-1] if ordered_dates else None,
                historical_snapshot_id=_snapshot_id(historical_snapshot),
                historical_content_hash=historical_snapshot.content_hash,
                profile_snapshot_id=_snapshot_id(profile_snapshot),
                profile_content_hash=profile_snapshot.content_hash,
                splits_snapshot_id=_snapshot_id(splits_snapshot),
                splits_content_hash=splits_snapshot.content_hash,
                split_events=split_events,
                overlap_matches=len(overlapping_dates) - len(conflicts),
                overlap_conflicts=conflicts,
                revision_conflicts=revision_conflicts,
            )
        )
    return tuple(results)


def _save_estimates(
    store: SqliteStore,
    snapshot_id: int,
    rows: tuple[dict[str, Any], ...],
    period: str,
) -> bool:
    estimates = _estimate_records(snapshot_id, rows, period)
    store.save_fmp_estimates(estimates)
    return any(
        value is not None
        for estimate in estimates
        for value in (
            estimate.revenue_low,
            estimate.revenue_average,
            estimate.revenue_high,
            estimate.eps_low,
            estimate.eps_average,
            estimate.eps_high,
        )
    )


def _build_annual_history(
    store: SqliteStore,
    security_id: int,
    symbol: str,
    tasks: dict[str, _TaskResult],
) -> bool:
    snapshots: dict[str, FmpEvidenceSnapshotRecord] = {}
    statement_rows: dict[str, tuple[dict[str, Any], ...]] = {}
    for statement in _STATEMENT_NAMES:
        dataset = f"annual_{statement}_statement"
        result = tasks.get(dataset)
        if result is None or result.snapshot is None or result.status == "FAILED":
            snapshot, rows = _load_statement(
                store, security_id, symbol, "annual", statement
            )
        else:
            snapshot = result.snapshot
            rows = result.rows
        if snapshot is None:
            return False
        snapshots[statement] = snapshot
        statement_rows[statement] = rows

    combined = FmpStatements(
        symbol=symbol,
        limit=ANNUAL_STATEMENT_LIMIT,
        income=statement_rows["income"],
        balance_sheet=statement_rows["balance_sheet"],
        cash_flow=statement_rows["cash_flow"],
        source_urls=tuple(
            _source_url(snapshots[statement]) for statement in _STATEMENT_NAMES
        ),
    )
    history: CanonicalFinancialHistory = canonical_history_from_fmp(
        combined, max_years=ANNUAL_STATEMENT_LIMIT
    )
    fact_records: list[FmpCanonicalFactRecord] = []
    for series in history.series:
        source_statement = FMP_FIELD_MAP[series.metric].statement
        source_snapshot_id = snapshots[source_statement].snapshot_id
        if source_snapshot_id is None:
            return False
        fact_records.extend(
            FmpCanonicalFactRecord(
                metric=fact.metric,
                value=fact.value,
                unit=fact.unit,
                fiscal_year=fact.fiscal_year,
                period_end=fact.period_end.isoformat(),
                provider_field=fact.provider_field,
                snapshot_id=source_snapshot_id,
            )
            for fact in series.observations
        )
    input_hash = compute_content_hash(
        "|".join(
            f"{statement}:{snapshots[statement].content_hash}"
            for statement in _STATEMENT_NAMES
        ).encode()
    )
    record = FmpCanonicalHistoryRecord(
        security_id=security_id,
        input_hash=input_hash,
        observed_at=max(snapshot.fetched_at for snapshot in snapshots.values()),
        max_years=ANNUAL_STATEMENT_LIMIT,
        facts=tuple(fact_records),
        coverage=tuple(
            FmpCanonicalCoverageRecord(
                metric=series.metric,
                status=series.status.value,
                reason=series.reason,
            )
            for series in history.series
        ),
    )
    store.save_fmp_canonical_history(record)
    return True


def _statement_loader(
    client: FmpClient,
    symbol: str,
    statement: str,
    period: str,
    limit: int,
) -> Callable[[], FmpEvidencePayload]:
    def load() -> FmpEvidencePayload:
        return client.get_statement_evidence(
            statement, symbol, period=period, limit=limit
        )

    return load


def _eod_loader(client: FmpClient, symbol: str) -> Callable[[], FmpEvidencePayload]:
    def load() -> FmpEvidencePayload:
        return client.get_eod_price_evidence(symbol)

    return load


def _estimate_loader(
    client: FmpClient, symbol: str, period: str, limit: int
) -> Callable[[], FmpEvidencePayload]:
    def load() -> FmpEvidencePayload:
        return client.get_analyst_estimates_evidence(symbol, period=period, limit=limit)

    return load


def _snapshot_id(snapshot: FmpEvidenceSnapshotRecord) -> int:
    if snapshot.snapshot_id is None:
        raise PersistenceError(
            f"FMP evidence snapshot {snapshot.dataset} has no persisted ID."
        )
    return snapshot.snapshot_id


def _members_and_ids(store: SqliteStore) -> tuple[tuple[FmpConstituent, int], ...]:
    snapshot = store.get_latest_universe_snapshot("fmp")
    if snapshot is None or snapshot.snapshot_id is None:
        raise PersistenceError("No persisted FMP S&P 500 snapshot is available.")
    records = store.list_universe_members(snapshot.snapshot_id)
    security_ids = store.universe_security_ids(snapshot.snapshot_id)
    return tuple(
        (
            FmpConstituent(
                symbol=record.symbol,
                name=record.name,
                cik=record.cik,
                sector=record.sector,
                subsector=record.subsector,
            ),
            security_ids[record.symbol],
        )
        for record in records
    )


def retrieve_candidate_prices(
    *,
    client: FmpClient,
    store: SqliteStore,
    symbols: tuple[str, ...],
    market_date: date,
) -> tuple[dict[str, Any], ...]:
    """Explicit bounded acquisition; never refresh fundamentals or latest quotes."""
    if not symbols or len(symbols) > 24 or len(set(symbols)) != len(symbols):
        raise ValueError("Candidate acquisition requires 1-24 distinct symbols.")
    start_date = market_date - timedelta(days=14)
    _validate_historical_range(start_date, market_date)
    members = {member.symbol: (member, sid) for member, sid in _members_and_ids(store)}
    missing = set(symbols) - set(members)
    if missing:
        raise ValueError(f"Candidate symbols outside persisted universe: {sorted(missing)}.")
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        member, security_id = members[symbol]
        try:
            profile = client.get_profile_evidence(symbol)
            _validate_pilot_payload_symbol(profile, symbol)
            if len(profile.rows) != 1:
                raise MalformedFmpResponseError(f"{symbol}: profile is not one identity.")
            cik = _profile_cik(profile.rows[0], symbol)
            if cik is not None and member.cik is not None and cik != member.cik:
                raise MalformedFmpResponseError(f"{symbol}: profile CIK mismatch.")
            splits = client.get_splits_evidence(
                symbol, start_date=market_date - timedelta(days=1095), end_date=market_date
            )
            _validate_pilot_payload_symbol(splits, symbol)
            prices = client.get_historical_price_evidence(
                symbol, start_date=start_date, end_date=market_date
            )
            _validate_pilot_payload_symbol(prices, symbol)
            validated = _validated_pilot_prices(
                symbol, prices.rows, start_date=start_date, end_date=market_date
            )
            saved: list[dict[str, Any]] = []
            with store.transaction():
                for dataset, period, payload in (
                    ("candidate_profile", "profile", profile),
                    ("candidate_splits", "corporate_action", splits),
                    ("candidate_price", "historical", prices),
                ):
                    snapshot = _persist_pilot_snapshot(
                        store, security_id=security_id, dataset=dataset,
                        period_type=period, payload=payload,
                    )
                    saved.append({
                        "dataset": dataset, "snapshot_id": snapshot.snapshot_id,
                        "content_hash": snapshot.content_hash,
                        "fetched_at": snapshot.fetched_at,
                    })
            status = "SUCCEEDED" if any(
                day == market_date.isoformat() for day, _price, _field in validated
            ) else "UNSUPPORTED"
            results.append({
                "symbol": symbol, "status": status, "snapshots": saved,
                "reason": None if status == "SUCCEEDED" else "No quote on requested market date.",
            })
        except (FmpAuthenticationError, FmpRateLimitError):
            raise
        except FmpPlanRestrictionError as exc:
            results.append({"symbol": symbol, "status": "UNSUPPORTED", "reason": str(exc)})
        except (FmpError, PersistenceError) as exc:
            results.append({"symbol": symbol, "status": "FAILED", "reason": str(exc)})
    return tuple(results)


def _record_task_result(counts: dict[str, int], result: _TaskResult) -> None:
    if result.status == "FAILED":
        counts["failed"] += 1
    elif result.status == "UNSUPPORTED":
        counts["unsupported"] += 1
    elif result.fetched:
        counts["refreshed"] += 1
    elif result.snapshot is not None:
        counts["skipped"] += 1


def refresh_sp500_evidence(
    *,
    client: FmpClient,
    store: SqliteStore,
    tickers: tuple[str, ...] | None = None,
    force: bool = False,
) -> EvidenceRefreshSummary:
    """Refresh persisted per-security FMP fundamentals, EOD price, and estimates."""
    members = _members_and_ids(store)
    selected_symbols = (
        {symbol.strip().upper() for symbol in tickers}
        if tickers
        else {member.symbol for member, _security_id in members}
    )
    current_symbols = {member.symbol for member, _security_id in members}
    missing = selected_symbols - current_symbols
    if missing:
        raise ValueError(
            f"Requested tickers are not in the persisted S&P 500 snapshot: "
            f"{', '.join(sorted(missing))}."
        )
    selected = tuple(
        (member, security_id)
        for member, security_id in members
        if member.symbol in selected_symbols
    )
    counts = {
        "refreshed": 0,
        "skipped": 0,
        "unsupported": 0,
        "failed": 0,
        "canonical": 0,
    }
    globally_restricted: set[str] = set()
    authentication_failed = False
    rate_limit_failed = False
    for member, security_id in selected:
        task_results: dict[str, _TaskResult] = {}
        statement_limit = {
            "annual": ANNUAL_STATEMENT_LIMIT,
            "quarterly": QUARTERLY_STATEMENT_LIMIT,
        }
        for dataset_period, limit in statement_limit.items():
            provider_period = _FMP_PERIOD_BY_DATASET_PERIOD[dataset_period]
            for statement in _STATEMENT_NAMES:
                dataset = f"{dataset_period}_{statement}_statement"
                result = _refresh_task(
                    client=client,
                    store=store,
                    security_id=security_id,
                    symbol=member.symbol,
                    dataset=dataset,
                    period_type=provider_period,
                    force=force,
                    loader=_statement_loader(
                        client, member.symbol, statement, provider_period, limit
                    ),
                    freshness=_STATEMENT_FRESHNESS,
                    globally_restricted=globally_restricted,
                )
                task_results[dataset] = result
                _record_task_result(counts, result)
                if result.authentication_failed:
                    authentication_failed = True
                    break
                if result.rate_limit_failed:
                    rate_limit_failed = True
                    break
            if authentication_failed:
                break
            if rate_limit_failed:
                break

        if not authentication_failed and not rate_limit_failed:
            eod = _refresh_task(
                client=client,
                store=store,
                security_id=security_id,
                symbol=member.symbol,
                dataset="eod_price",
                period_type="eod",
                force=force,
                loader=_eod_loader(client, member.symbol),
                freshness=_DAILY_FRESHNESS,
                globally_restricted=globally_restricted,
            )
            if eod.snapshot is not None and eod.status != "FAILED":
                try:
                    price_exists = _save_price(
                        store, security_id, _snapshot_id(eod.snapshot), eod.rows
                    )
                except (FmpError, PersistenceError) as exc:
                    _update_state(
                        store, security_id, "eod_price", "FAILED", error=str(exc)
                    )
                    eod = _TaskResult(
                        "eod_price",
                        "FAILED",
                        eod.snapshot,
                        error=str(exc),
                        fetched=eod.fetched,
                    )
                    price_exists = False
                if not price_exists and eod.status == "SUCCEEDED":
                    _update_state(
                        store,
                        security_id,
                        "eod_price",
                        "UNSUPPORTED",
                        error="No reliable EOD close was available.",
                    )
                    eod = _TaskResult(
                        "eod_price",
                        "UNSUPPORTED",
                        eod.snapshot,
                        rows=eod.rows,
                        fetched=eod.fetched,
                    )
            _record_task_result(counts, eod)
            rate_limit_failed = eod.rate_limit_failed

        if not authentication_failed and not rate_limit_failed:
            for dataset_period, limit in (
                ("annual", ANNUAL_ESTIMATE_LIMIT),
                ("quarterly", QUARTERLY_ESTIMATE_LIMIT),
            ):
                dataset = f"{dataset_period}_analyst_estimates"
                provider_period = _FMP_PERIOD_BY_DATASET_PERIOD[dataset_period]
                result = _refresh_task(
                    client=client,
                    store=store,
                    security_id=security_id,
                    symbol=member.symbol,
                    dataset=dataset,
                    period_type=provider_period,
                    force=force,
                    loader=_estimate_loader(
                        client, member.symbol, provider_period, limit
                    ),
                    freshness=_DAILY_FRESHNESS,
                    evidence_kind="EXPECTATION",
                    globally_restricted=globally_restricted,
                )
                if result.snapshot is not None and result.status != "FAILED":
                    try:
                        has_estimates = _save_estimates(
                            store,
                            _snapshot_id(result.snapshot),
                            result.rows,
                            provider_period,
                        )
                    except (FmpError, PersistenceError) as exc:
                        _update_state(
                            store, security_id, dataset, "FAILED", error=str(exc)
                        )
                        result = _TaskResult(
                            dataset,
                            "FAILED",
                            result.snapshot,
                            error=str(exc),
                            fetched=result.fetched,
                        )
                    else:
                        if not has_estimates and result.status == "SUCCEEDED":
                            reason = "No future analyst estimates were available."
                            _update_state(
                                store, security_id, dataset, "UNSUPPORTED", error=reason
                            )
                            result = _TaskResult(
                                dataset,
                                "UNSUPPORTED",
                                result.snapshot,
                                rows=result.rows,
                                error=reason,
                                fetched=result.fetched,
                            )
                _record_task_result(counts, result)
                if result.authentication_failed:
                    authentication_failed = True
                    break
                if result.rate_limit_failed:
                    rate_limit_failed = True
                    break

        if not authentication_failed and not rate_limit_failed:
            if _build_annual_history(store, security_id, member.symbol, task_results):
                counts["canonical"] += 1
        else:
            break
    return EvidenceRefreshSummary(
        securities=len(selected),
        refreshed=counts["refreshed"],
        skipped=counts["skipped"],
        unsupported=counts["unsupported"],
        failed=counts["failed"],
        canonical_histories=counts["canonical"],
    )

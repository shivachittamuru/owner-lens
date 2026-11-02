"""Fixture-only tests for FMP Premium evidence ingestion."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from owner_lens.evidence_ingestion import refresh_sp500_evidence
from owner_lens.fmp import (
    FMP_ANALYST_ESTIMATES_ENDPOINT,
    FMP_EOD_LIGHT_ENDPOINT,
    FMP_STATEMENT_ENDPOINTS,
    FmpAuthenticationError,
    FmpConstituent,
    FmpConstituents,
    FmpEvidencePayload,
    FmpPlanRestrictionError,
    FmpRateLimitError,
)
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.universe_ingestion import refresh_sp500_universe

_SYMBOL = "ADBE"
_STATEMENT_FIELDS = {
    "income": {
        "revenue": 1000,
        "operatingIncome": 100,
        "netIncome": 75,
        "weightedAverageShsOutDil": 50,
        "incomeTaxExpense": 20,
        "incomeBeforeTax": 95,
    },
    "balance_sheet": {
        "cashAndCashEquivalents": 10,
        "shortTermInvestments": 0,
        "shortTermDebt": 5,
        "longTermDebt": 10,
        "totalAssets": 100,
        "totalStockholdersEquity": 70,
    },
    "cash_flow": {
        "netCashProvidedByOperatingActivities": 90,
        "investmentsInPropertyPlantAndEquipment": -20,
        "commonStockRepurchased": -3,
        "stockBasedCompensation": 2,
        "commonDividendsPaid": -1,
    },
}


def _quarter_ends(count: int, *, start_after: date | None = None) -> list[date]:
    today = start_after or datetime.now(UTC).date()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    result: list[date] = []
    while len(result) < count:
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
        month = quarter * 3
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        end = date.fromordinal(next_month.toordinal() - 1)
        result.append(end)
    return result


def _rows(period: str, statement: str) -> list[dict[str, Any]]:
    count = 15 if period == "annual" else 8
    if period == "annual":
        ends = [
            date(datetime.now(UTC).year - index, 12, 31)
            for index in range(1, count + 1)
        ]
    else:
        ends = sorted(_quarter_ends(count), reverse=True)
    rows = []
    for index, end in enumerate(ends):
        row: dict[str, Any] = {
            "symbol": _SYMBOL,
            "date": end.isoformat(),
            "fiscalYear": str(end.year),
            "period": "FY" if period == "annual" else f"Q{(end.month - 1) // 3 + 1}",
            "reportedCurrency": "USD",
        }
        row.update(_STATEMENT_FIELDS[statement])
        if statement == "income" and index == 1:
            row["operatingIncome"] = 0
        if statement == "income" and index == 2:
            row.pop("incomeTaxExpense")
        rows.append(row)
    return rows


def _estimate_rows(period: str, *, average_delta: float = 0) -> list[dict[str, Any]]:
    limit = 3 if period == "annual" else 4
    dates = (
        [date(datetime.now(UTC).year + i, 12, 31) for i in range(1, limit + 1)]
        if period == "annual"
        else _quarter_ends(limit)
    )
    return [
        {
            "symbol": _SYMBOL,
            "date": target.isoformat(),
            "revenueLow": 900.0,
            "revenueAvg": 1000.0 + average_delta,
            "revenueHigh": 1100.0,
            "numAnalystsRevenue": 5,
            "epsLow": 1.0,
            "epsAvg": 1.5 + average_delta,
            "epsHigh": 2.0,
            "numAnalystsEps": 4,
        }
        for target in dates
    ]


def _payload(
    endpoint: str,
    parameters: dict[str, str],
    rows: list[dict[str, Any]],
    *,
    fetched_at: str = "2026-01-01T00:00:00+00:00",
) -> FmpEvidencePayload:
    raw = json.dumps(rows, sort_keys=True).encode()
    return FmpEvidencePayload(
        endpoint=endpoint,
        request_parameters=tuple(sorted(parameters.items())),
        source_url=f"https://financialmodelingprep.com/stable/{endpoint}?fixture",
        fetched_at=fetched_at,
        rows=tuple(rows),
        raw_payload=raw,
    )


class FixtureClient:
    def __init__(
        self,
        *,
        restricted_estimates: bool = False,
        rate_limit_once: bool = False,
    ) -> None:
        self.restricted_estimates = restricted_estimates
        self.rate_limit_once = rate_limit_once
        self.calls: list[tuple[str, str, str]] = []
        self.estimate_average_delta = 0.0
        self.fetched_at = "2026-01-01T00:00:00+00:00"
        self._did_rate_limit = False

    def get_statement_evidence(
        self, statement: str, symbol: str, *, period: str, limit: int
    ) -> FmpEvidencePayload:
        self.calls.append((period, statement, symbol))
        if self.rate_limit_once and not self._did_rate_limit:
            self._did_rate_limit = True
            raise FmpRateLimitError("fixture rate limit", status_code=429)
        endpoint = FMP_STATEMENT_ENDPOINTS[statement]
        return _payload(
            endpoint,
            {"symbol": symbol, "period": period, "limit": str(limit)},
            _rows(period, statement),
            fetched_at=self.fetched_at,
        )

    def get_eod_price_evidence(self, symbol: str) -> FmpEvidencePayload:
        self.calls.append(("eod", "price", symbol))
        today = datetime.now(UTC).date()
        return _payload(
            FMP_EOD_LIGHT_ENDPOINT,
            {"symbol": symbol, "to": today.isoformat()},
            [{"symbol": symbol, "date": today.isoformat(), "price": 123.45}],
            fetched_at=self.fetched_at,
        )

    def get_analyst_estimates_evidence(
        self, symbol: str, *, period: str, limit: int
    ) -> FmpEvidencePayload:
        self.calls.append((period, "estimates", symbol))
        if self.restricted_estimates and period == "annual":
            raise FmpPlanRestrictionError("fixture entitlement unavailable", status_code=402)
        return _payload(
            FMP_ANALYST_ESTIMATES_ENDPOINT,
            {"symbol": symbol, "period": period, "page": "0", "limit": str(limit)},
            _estimate_rows(period, average_delta=self.estimate_average_delta),
            fetched_at=self.fetched_at,
        )


class UniverseClient:
    def get_sp500_constituents(self, *, refresh: bool) -> FmpConstituents:
        assert refresh
        rows = [
            {
                "symbol": _SYMBOL,
                "name": "Adobe Inc.",
                "cik": "0000796343",
                "sector": "Technology",
                "subSector": "Software",
            }
        ]
        return FmpConstituents(
            members=(
                FmpConstituent(
                    symbol=_SYMBOL,
                    name="Adobe Inc.",
                    cik="0000796343",
                    sector="Technology",
                    subsector="Software",
                ),
            ),
            source_url="https://financialmodelingprep.com/stable/sp500-constituent",
            raw_payload=json.dumps(rows).encode(),
        )


def _store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(
        tmp_path / "ownerlens.sqlite",
        raw_store=FilesystemRawSnapshotStore(tmp_path / "raw"),
    )
    store.initialize()
    refresh_sp500_universe(client=UniverseClient(), store=store)
    return store


def test_refresh_persists_15_annual_and_8_quarterly_periods_separately(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    client = FixtureClient()
    summary = refresh_sp500_evidence(client=client, store=store)

    assert summary.securities == 1
    assert summary.failed == 0
    assert len(store.list_security_refresh_state(1)) == 9
    statement_periods = {
        (period, statement)
        for period, statement, _symbol in client.calls
        if statement in {"income", "balance_sheet", "cash_flow"}
    }
    assert statement_periods == {
        ("annual", "income"),
        ("annual", "balance_sheet"),
        ("annual", "cash_flow"),
        ("quarter", "income"),
        ("quarter", "balance_sheet"),
        ("quarter", "cash_flow"),
    }
    for period, expected in (("annual", 15), ("quarterly", 8)):
        statement_snapshots = store._conn.execute(
            "SELECT dataset, content_hash, request_parameters "
            "FROM fmp_evidence_snapshots "
            "WHERE security_id = 1 AND dataset LIKE ? AND dataset LIKE '%_statement'",
            (f"{period}_%",),
        ).fetchall()
        assert len(statement_snapshots) == 3
        for snapshot in statement_snapshots:
            expected_period = "annual" if period == "annual" else "quarter"
            assert json.loads(snapshot["request_parameters"])["period"] == expected_period
            rows = json.loads(store.get_raw_snapshot(snapshot["content_hash"]))
            assert len(rows) == expected

    history_id = store._conn.execute(
        "SELECT history_id FROM fmp_canonical_histories"
    ).fetchone()[0]
    canonical_snapshots = {
        row[0]
        for row in store._conn.execute(
            "SELECT DISTINCT snapshot_id FROM fmp_canonical_facts WHERE history_id = ?",
            (history_id,),
        )
    }
    assert canonical_snapshots
    assert store._conn.execute(
        "SELECT DISTINCT provider FROM fmp_canonical_histories"
    ).fetchone()[0] == "fmp"
    assert all(
        store._conn.execute(
            "SELECT period_type FROM fmp_evidence_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0]
        == "annual"
        for snapshot_id in canonical_snapshots
    )
    assert store._conn.execute("SELECT COUNT(*) FROM fmp_eod_prices").fetchone()[0] == 1
    price = store._conn.execute(
        "SELECT market_date, close, source_field FROM fmp_eod_prices"
    ).fetchone()
    assert price["close"] == 123.45
    assert price["source_field"] == "price"
    assert store._conn.execute("SELECT COUNT(*) FROM fmp_estimates").fetchone()[0] == 7
    store.close()


def test_raw_provenance_missing_and_explicit_zero_are_preserved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    refresh_sp500_evidence(client=FixtureClient(), store=store)
    snapshot = store.get_latest_fmp_evidence_snapshot(1, "annual_income_statement")

    assert snapshot is not None
    assert snapshot.source_endpoint == "income-statement"
    assert json.loads(snapshot.request_parameters)["period"] == "annual"
    raw_rows = json.loads(store.get_raw_snapshot(snapshot.content_hash))
    assert raw_rows[1]["operatingIncome"] == 0
    assert "incomeTaxExpense" not in raw_rows[2]
    assert snapshot.raw_object_ref is not None
    zero_year = datetime.now(UTC).year - 2
    missing_year = datetime.now(UTC).year - 3
    assert store._conn.execute(
        "SELECT value FROM fmp_canonical_facts "
        "WHERE metric = 'operating_income' AND fiscal_year = ?",
        (zero_year,),
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM fmp_canonical_facts "
        "WHERE metric = 'income_tax_expense' AND fiscal_year = ?",
        (missing_year,),
    ).fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM reported_facts").fetchone()[0] == 0
    store.close()


def test_estimate_snapshots_are_versioned_and_prior_expectations_remain(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    client = FixtureClient()
    first_fetch = datetime.now(UTC) - timedelta(seconds=2)
    client.fetched_at = first_fetch.isoformat(timespec="microseconds")
    refresh_sp500_evidence(client=client, store=store)
    first = store.get_latest_fmp_evidence_snapshot(1, "annual_analyst_estimates")
    assert first is not None

    client.fetched_at = (first_fetch + timedelta(seconds=1)).isoformat(
        timespec="microseconds"
    )
    refresh_sp500_evidence(client=client, store=store, force=True)
    assert store._conn.execute(
        "SELECT COUNT(*) FROM fmp_estimates"
    ).fetchone()[0] == 14

    client.estimate_average_delta = 25.0
    client.fetched_at = (first_fetch + timedelta(seconds=2)).isoformat(
        timespec="microseconds"
    )
    refresh_sp500_evidence(client=client, store=store, force=True)
    second = store.get_latest_fmp_evidence_snapshot(1, "annual_analyst_estimates")
    assert second is not None
    assert second.snapshot_id != first.snapshot_id
    assert store._conn.execute(
        "SELECT COUNT(*) FROM fmp_estimates"
    ).fetchone()[0] == 21
    assert store._conn.execute(
        "SELECT DISTINCT evidence_kind FROM fmp_evidence_snapshots "
        "WHERE dataset LIKE '%analyst_estimates'"
    ).fetchall()[0][0] == "EXPECTATION"
    store.close()


def test_estimate_entitlement_failure_is_explicit_and_partial(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    summary = refresh_sp500_evidence(
        client=FixtureClient(restricted_estimates=True), store=store
    )

    assert summary.partial
    assert summary.unsupported == 1
    states = {
        state.dataset: state.status for state in store.list_security_refresh_state(1)
    }
    assert states["annual_analyst_estimates"] == "UNSUPPORTED"
    assert states["quarterly_analyst_estimates"] == "SUCCEEDED"
    store.close()


def test_rate_limit_stops_refresh_and_rerun_resumes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FixtureClient(rate_limit_once=True)
    first = refresh_sp500_evidence(client=client, store=store)
    assert first.failed == 1
    assert len(client.calls) == 1

    resumed = refresh_sp500_evidence(client=client, store=store)
    assert resumed.failed == 0
    assert resumed.canonical_histories == 1
    assert store._conn.execute("SELECT COUNT(*) FROM fmp_eod_prices").fetchone()[0] == 1
    store.close()


def test_interrupted_running_dataset_recovers_from_persisted_evidence(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    client = FixtureClient()
    client.fetched_at = datetime.now(UTC).isoformat(timespec="microseconds")
    refresh_sp500_evidence(client=client, store=store)
    calls_before_resume = len(client.calls)
    store.update_security_refresh_state(
        1,
        "quarterly_income_statement",
        status="RUNNING",
        updated_at="2026-10-30T00:00:00+00:00",
    )

    resumed = refresh_sp500_evidence(client=client, store=store)
    state = store.get_security_refresh_state(1, "quarterly_income_statement")

    assert resumed.failed == 0
    assert state is not None
    assert state.status == "SUCCEEDED"
    assert state.last_error is None
    assert len(client.calls) == calls_before_resume
    store.close()


def test_authentication_failure_stops_refresh_and_is_persisted(tmp_path: Path) -> None:
    class AuthenticationFailureClient(FixtureClient):
        def get_statement_evidence(
            self, statement: str, symbol: str, *, period: str, limit: int
        ) -> FmpEvidencePayload:
            super().get_statement_evidence(
                statement, symbol, period=period, limit=limit
            )
            raise FmpAuthenticationError("fixture auth failure", status_code=401)

    store = _store(tmp_path)
    client = AuthenticationFailureClient()
    summary = refresh_sp500_evidence(client=client, store=store)

    assert summary.failed == 1
    assert len(client.calls) == 1
    state = next(
        state
        for state in store.list_security_refresh_state(1)
        if state.dataset == "annual_income_statement"
    )
    assert state.status == "FAILED"
    assert "fixture auth failure" in (state.last_error or "")
    store.close()


def test_schema_v2_migration_preserves_refresh_state(tmp_path: Path) -> None:
    db_path = tmp_path / "migration.sqlite"
    store = SqliteStore(db_path)
    store.initialize()
    refresh_sp500_universe(client=UniverseClient(), store=store)
    store.update_security_refresh_state(
        1,
        "annual_income_statement",
        status="SUCCEEDED",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    store._conn.execute(
        "UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'"
    )
    store._conn.commit()
    store.close()

    migrated = SqliteStore(db_path)
    migrated.initialize()
    state = next(
        state
        for state in migrated.list_security_refresh_state(1)
        if state.dataset == "annual_income_statement"
    )
    assert state.status == "SUCCEEDED"
    assert migrated._conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()[0] == "12"
    migrated.close()


def test_refresh_rejects_nonmember_symbol_without_live_requests(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FixtureClient()
    with pytest.raises(ValueError, match="not in the persisted"):
        refresh_sp500_evidence(client=client, store=store, tickers=("NOTMEMBER",))
    assert client.calls == []
    store.close()


@pytest.mark.parametrize(
    ("aggregate", "children"),
    [
        (
            "annual_statements",
            (
                "annual_income_statement",
                "annual_balance_sheet_statement",
                "annual_cash_flow_statement",
            ),
        ),
        (
            "quarterly_statements",
            (
                "quarterly_income_statement",
                "quarterly_balance_sheet_statement",
                "quarterly_cash_flow_statement",
            ),
        ),
        (
            "analyst_estimates",
            ("annual_analyst_estimates", "quarterly_analyst_estimates"),
        ),
    ],
)
@pytest.mark.parametrize(
    ("first_status", "other_status", "expected"),
    [
        ("SUCCEEDED", "SUCCEEDED", "SUCCEEDED"),
        ("UNSUPPORTED", "UNSUPPORTED", "UNSUPPORTED"),
        ("PARTIAL", "PARTIAL", "PARTIAL"),
        ("PENDING", "PENDING", "PENDING"),
        ("FAILED", "SUCCEEDED", "FAILED"),
        ("UNSUPPORTED", "SUCCEEDED", "PARTIAL"),
        ("RUNNING", "SUCCEEDED", "RUNNING"),
        ("PENDING", "SUCCEEDED", "PARTIAL"),
        (None, "SUCCEEDED", "PARTIAL"),
        (None, None, "PENDING"),
        ("FAILED", "RUNNING", "FAILED"),
    ],
)
def test_legacy_aggregate_refresh_state_is_derived_without_writes(
    tmp_path: Path,
    aggregate: str,
    children: tuple[str, ...],
    first_status: str | None,
    other_status: str | None,
    expected: str,
) -> None:
    store = _store(tmp_path)
    attempted_at = "2026-10-31T00:00:00+00:00"
    store.update_security_refresh_state(
        1, aggregate, status="PENDING", updated_at="2026-01-01T00:00:00+00:00"
    )
    for index, child in enumerate(children):
        status = first_status if index == 0 else other_status
        if status is None:
            store._conn.execute(
                "DELETE FROM security_refresh_state WHERE security_id = 1 AND dataset = ?",
                (child,),
            )
        else:
            store.update_security_refresh_state(
                1,
                child,
                status=status,
                updated_at=attempted_at,
                last_error="fixture failure" if status == "FAILED" else None,
            )
    store._conn.commit()
    before = store._conn.total_changes

    state = store.get_security_refresh_state(1, aggregate)
    assert state is not None
    assert state.status == expected
    listed = next(
        item for item in store.list_security_refresh_state() if item.dataset == aggregate
    )
    assert listed == state
    assert store.list_evidence_status_counts()[aggregate] == {expected: 1}
    assert store.list_evidence_status_counts([1])[aggregate] == {expected: 1}
    assert store.list_evidence_status_counts([999]) == {}
    assert store.list_evidence_status_counts([]) == {}
    assert store._conn.total_changes == before
    assert store._conn.execute(
        "SELECT status FROM security_refresh_state WHERE security_id = 1 AND dataset = ?",
        (aggregate,),
    ).fetchone()[0] == "PENDING"
    if first_status is None and other_status is None:
        assert state.last_attempt_at is None
    else:
        assert state.last_attempt_at == attempted_at
    if expected == "SUCCEEDED":
        assert state.last_error is None
    elif expected == "FAILED":
        assert "fixture failure" in (state.last_error or "")

    for child in children:
        store.update_security_refresh_state(
            1, child, status="SUCCEEDED", updated_at=attempted_at
        )
    completed = store.get_security_refresh_state(1, aggregate)
    assert completed is not None
    assert completed.status == "SUCCEEDED"
    assert completed.last_error is None
    store.close()

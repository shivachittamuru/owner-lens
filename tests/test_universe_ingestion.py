"""Fixture-only tests for S&P 500 membership persistence and refresh behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from _fmp_universe_fixtures import sp500_payload

from owner_lens.fmp import FmpConstituent, FmpConstituents, FmpTransportError
from owner_lens.persistence import (
    FilesystemRawSnapshotStore,
    SchemaVersionError,
    SqliteStore,
    StorageWriteError,
)
from owner_lens.universe_ingestion import (
    SP500_PROVIDER,
    SP500_REFRESH_DATASETS,
    UniverseRefreshError,
    refresh_sp500_universe,
)


class FixtureClient:
    def __init__(self, response: FmpConstituents | Exception) -> None:
        self.response = response
        self.calls = 0

    def get_sp500_constituents(self, *, refresh: bool = True) -> FmpConstituents:
        assert refresh
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(*, sector_suffix: str = "") -> FmpConstituents:
    raw_payload = json.dumps(sp500_payload(sector_suffix=sector_suffix)).encode()
    return FmpConstituents(
        members=_parsed_members(sector_suffix),
        source_url="https://financialmodelingprep.com/stable/sp500-constituent",
        raw_payload=raw_payload,
    )


def _parsed_members(sector_suffix: str) -> tuple[FmpConstituent, ...]:
    return tuple(
        FmpConstituent(
            symbol=row["symbol"],
            name=row["name"],
            cik=row["cik"],
            sector=row["sector"],
            subsector=row["subSector"],
        )
        for row in sp500_payload(sector_suffix=sector_suffix)
    )


def _store(tmp_path: Path, filename: str = "ownerlens.db") -> SqliteStore:
    store = SqliteStore(
        tmp_path / filename,
        raw_store=FilesystemRawSnapshotStore(tmp_path / "raw"),
    )
    store.initialize()
    return store


def test_refresh_versions_snapshots_and_preserves_distinct_share_classes(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = refresh_sp500_universe(client=FixtureClient(_response()), store=store)
    repeat = refresh_sp500_universe(client=FixtureClient(_response()), store=store)
    changed = refresh_sp500_universe(
        client=FixtureClient(_response(sector_suffix=" Updated")), store=store
    )

    assert first.new_snapshot
    assert not repeat.new_snapshot
    assert changed.new_snapshot
    assert first.snapshot_id == repeat.snapshot_id
    assert changed.snapshot_id != first.snapshot_id
    assert first.member_count == 4
    assert first.state_row_count == 4 * len(SP500_REFRESH_DATASETS)
    assert repeat.state_row_count == 4 * len(SP500_REFRESH_DATASETS)

    security_ids = store.universe_security_ids(first.snapshot_id)
    assert security_ids["GOOG"] != security_ids["GOOGL"]
    assert security_ids == store.universe_security_ids(changed.snapshot_id)
    securities = {security.symbol: security for security in store.list_securities()}
    assert securities["GOOG"].cik == securities["GOOGL"].cik == "0001652044"
    assert len(store.list_universe_members(first.snapshot_id)) == 4
    assert len(store.list_universe_members(changed.snapshot_id)) == 4
    assert len(store.list_security_refresh_state()) == 4 * len(SP500_REFRESH_DATASETS)
    assert store._conn.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0] == 2
    assert store.get_latest_universe_snapshot(SP500_PROVIDER) == store.get_universe_snapshot(
        SP500_PROVIDER, changed.content_hash
    )

    raw = store._raw_store
    assert raw is not None
    assert raw.get(first.content_hash) == _response().raw_payload
    store.close()


def test_bounded_refresh_persists_full_membership_but_limits_pending_state(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    result = refresh_sp500_universe(
        client=FixtureClient(_response()),
        store=store,
        tickers=("adbe", "GOOG", "GOOGL"),
    )

    assert result.member_count == 4
    assert result.state_symbol_count == 3
    assert result.state_row_count == 3 * len(SP500_REFRESH_DATASETS)
    assert len(store.list_universe_members(result.snapshot_id)) == 4
    assert {security.symbol for security in store.list_securities()} == {
        "ADBE",
        "GOOG",
        "GOOGL",
        "MSFT",
    }
    store.close()


def test_unknown_or_duplicate_requested_tickers_fail_without_partial_snapshot(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    client = FixtureClient(_response())

    with pytest.raises(UniverseRefreshError, match="not in the current"):
        refresh_sp500_universe(client=client, store=store, tickers=("ZZZZ",))
    with pytest.raises(UniverseRefreshError, match="Duplicate ticker"):
        refresh_sp500_universe(
            client=client, store=store, tickers=("GOOG", "goog")
        )

    assert store.get_latest_universe_snapshot(SP500_PROVIDER) is None
    assert store._conn.execute(
        "SELECT COUNT(*) FROM universe_refresh_runs WHERE status = 'FAILED'"
    ).fetchone()[0] == 1
    store.close()


def test_failed_fetch_can_resume_and_preserves_refresh_state(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    failing = FixtureClient(FmpTransportError("fixture interruption"))
    with pytest.raises(FmpTransportError, match="fixture interruption"):
        refresh_sp500_universe(client=failing, store=store)

    resumed = refresh_sp500_universe(client=FixtureClient(_response()), store=store)
    run = store.get_universe_refresh_run(resumed.run_id)

    assert resumed.member_count == 4
    assert run is not None and run.status == "SUCCEEDED"
    assert store._conn.execute(
        "SELECT COUNT(*) FROM universe_refresh_runs WHERE status = 'FAILED'"
    ).fetchone()[0] == 1
    assert len(store.list_security_refresh_state()) == 4 * len(SP500_REFRESH_DATASETS)
    store.close()


def test_rerun_is_idempotent_after_snapshot_commit_before_run_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    save = store.save_universe_snapshot
    fail_once = True

    def persist_then_interrupt(*args, **kwargs):
        nonlocal fail_once
        result = save(*args, **kwargs)
        if fail_once:
            fail_once = False
            raise StorageWriteError("fixture interruption after snapshot commit")
        return result

    monkeypatch.setattr(store, "save_universe_snapshot", persist_then_interrupt)
    with pytest.raises(StorageWriteError, match="fixture interruption"):
        refresh_sp500_universe(client=FixtureClient(_response()), store=store)

    monkeypatch.setattr(store, "save_universe_snapshot", save)
    resumed = refresh_sp500_universe(client=FixtureClient(_response()), store=store)
    assert not resumed.new_snapshot
    assert store._conn.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM universe_members").fetchone()[0] == 4
    assert store._conn.execute(
        "SELECT COUNT(*) FROM universe_refresh_runs WHERE status = 'SUCCEEDED'"
    ).fetchone()[0] == 1
    store.close()


def test_schema_v1_migrates_additively_and_preserves_sec_company(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            CREATE TABLE companies (
                id INTEGER PRIMARY KEY,
                cik TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO companies VALUES (
                1, '0000796343', 'ADBE', 'Adobe Inc.', '2025-01-01'
            );
            """
        )

    store = _store(tmp_path, "legacy.sqlite")
    assert store.get_company("0000796343") is not None
    assert store._conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()[0] == "6"
    assert store._conn.execute(
        "SELECT COUNT(*) FROM securities"
    ).fetchone()[0] == 0
    store.close()


def test_future_schema_version_remains_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._conn.execute(
        "UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'"
    )
    store._conn.commit()
    store.close()

    reopened = SqliteStore(tmp_path / "ownerlens.db")
    with pytest.raises(SchemaVersionError):
        reopened.initialize()
    reopened.close()


def test_refresh_run_records_bounded_request_symbols(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = refresh_sp500_universe(
        client=FixtureClient(_response()), store=store, tickers=("GOOG", "GOOGL")
    )
    run = store.get_universe_refresh_run(result.run_id)

    assert run is not None
    assert run.requested_symbols == ("GOOG", "GOOGL")
    assert run.status == "SUCCEEDED"
    assert run.snapshot_id == result.snapshot_id
    assert run.error is None
    store.close()

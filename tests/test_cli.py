"""Tests for the OwnerLens command-line interface (Slice 4B)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from _fixtures import FakeSecClient
from _fmp_universe_fixtures import sp500_payload

import owner_lens
from owner_lens import cli, ingestion
from owner_lens.config import OwnerLensSettings
from owner_lens.evidence_ingestion import EvidenceRefreshSummary
from owner_lens.fmp import FmpConstituent, FmpConstituents
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.sec import CompanyResolutionError

_ADBE = "0000796343"
_STRUCTURED_TABLES = (
    "source_snapshots",
    "reported_facts",
    "derived_metrics",
    "analysis_results",
    "coverage_results",
)


def _settings(
    tmp_path: Path,
    user_agent: str | None = "OwnerLens test@example.com",
    fmp_api_key: str | None = None,
):
    return OwnerLensSettings(
        sec_user_agent=user_agent,
        db_path=str(tmp_path / "db.sqlite"),
        raw_data_path=str(tmp_path / "raw"),
        fmp_api_key=fmp_api_key,
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    facts=None,
    resolve_error: Exception | None = None,
    user_agent: str | None = "OwnerLens test@example.com",
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path, user_agent))
    monkeypatch.setattr(
        cli,
        "SecClient",
        lambda _ua: FakeSecClient(facts=facts, resolve_error=resolve_error),
    )


def _open(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(
        tmp_path / "db.sqlite",
        raw_store=FilesystemRawSnapshotStore(tmp_path / "raw"),
    )
    store.initialize()
    return store


def _counts(store: SqliteStore) -> dict[str, int]:
    return {
        table: store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _STRUCTURED_TABLES
    }


def test_ingest_complete_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    code = cli.main(["ingest", "ADBE"])
    out = capsys.readouterr().out
    assert code == 0
    assert "ADOBE INC." in out
    assert "reported facts:" in out


def test_ingest_partial_shows_reason_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    code = cli.main(["ingest", "V"])
    out = capsys.readouterr().out
    assert code == 0
    assert "diluted_shares" in out


def test_ingest_missing_user_agent_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, tmp_path, user_agent=None)
    assert cli.main(["ingest", "ADBE"]) == 2


def test_ingest_retrieval_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path, resolve_error=CompanyResolutionError("no match"))
    code = cli.main(["ingest", "ZZZZ"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED (retrieval)" in out


def test_unchanged_reingest_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    assert cli.main(["ingest", "ADBE"]) == 0
    capsys.readouterr()
    assert cli.main(["ingest", "ADBE"]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_force_reingest_is_non_duplicating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    store = _open(tmp_path)
    before = _counts(store)
    store.close()

    assert cli.main(["ingest", "ADBE", "--force"]) == 0
    store = _open(tmp_path)
    assert _counts(store) == before
    store.close()


def test_show_reports_persisted_company(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    capsys.readouterr()
    code = cli.main(["show", "ADBE"])
    out = capsys.readouterr().out
    assert code == 0
    assert _ADBE in out


def test_show_unknown_company_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, tmp_path)
    assert cli.main(["show", "ADBE"]) == 1


def test_cli_and_script_share_one_ingest_implementation() -> None:
    # The CLI, the package export, and the script must call the same function.
    assert cli.ingest_company is ingestion.ingest_company
    assert owner_lens.ingest_company is ingestion.ingest_company

    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "ingest_company_facts.py"
    )
    spec = importlib.util.spec_from_file_location("_ingest_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ingest_company is ingestion.ingest_company


def test_show_reports_the_screening_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    capsys.readouterr()

    assert cli.main(["show", "ADBE"]) == 0
    out = capsys.readouterr().out
    assert "Screening:" in out
    assert "coverage FULL" in out


def test_screen_ranks_every_persisted_company_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    cli.main(["ingest", "COST"])
    capsys.readouterr()
    # Any SEC call from here on is a defect: screening reads persisted data only.
    monkeypatch.setattr(
        cli, "SecClient", lambda _ua: pytest.fail("screen must not call SEC")
    )

    assert cli.main(["screen"]) == 0
    out = capsys.readouterr().out
    assert "ADBE" in out
    assert "COST" in out
    assert "Distribution:" in out


def test_screen_accepts_a_subset_of_tickers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    cli.main(["ingest", "COST"])
    capsys.readouterr()

    assert cli.main(["screen", "adbe"]) == 0
    out = capsys.readouterr().out
    assert "ADBE" in out
    assert "COST" not in out


def test_screen_detail_prints_the_full_justification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    capsys.readouterr()

    assert cli.main(["screen", "ADBE", "--detail"]) == 0
    out = capsys.readouterr().out
    assert "Opportunity Screening" in out
    assert "Why it ranks where it does:" in out


def test_screen_refuses_a_company_that_was_never_ingested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)
    cli.main(["ingest", "ADBE"])
    capsys.readouterr()

    assert cli.main(["screen", "ZZZZ"]) == 1
    assert "Not ingested: ZZZZ" in capsys.readouterr().err


def test_screen_on_an_empty_store_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, tmp_path)

    assert cli.main(["screen"]) == 1
    assert "No companies have been ingested." in capsys.readouterr().err


def test_screen_rejects_a_non_positive_history_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, tmp_path)

    assert cli.main(["screen", "--max-years", "0"]) == 2


class _FixtureFmpClient:
    def __init__(self, _api_key: str) -> None:
        rows = sp500_payload()
        self.response = FmpConstituents(
            members=tuple(
                FmpConstituent(
                    symbol=row["symbol"],
                    name=row["name"],
                    cik=row["cik"],
                    sector=row["sector"],
                    subsector=row["subSector"],
                )
                for row in rows
            ),
            source_url="https://financialmodelingprep.com/stable/sp500-constituent",
            raw_payload=json.dumps(rows).encode(),
        )

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_sp500_constituents(self, *, refresh: bool = True) -> FmpConstituents:
        assert refresh
        return self.response


def test_refresh_sp500_cli_persists_bounded_membership_without_live_fmp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: _settings(tmp_path, fmp_api_key="fixture-key"),
    )
    monkeypatch.setattr(cli, "FmpClient", _FixtureFmpClient)
    monkeypatch.setattr(
        cli,
        "refresh_sp500_evidence",
        lambda **_kwargs: EvidenceRefreshSummary(
            securities=3,
            refreshed=0,
            skipped=27,
            unsupported=0,
            failed=0,
            canonical_histories=0,
        ),
    )

    assert cli.main(
        ["refresh-sp500", "--tickers", "ADBE", "GOOG", "GOOGL"]
    ) == 0
    output = capsys.readouterr().out
    assert "S&P 500 refresh completed" in output
    assert "4 securities" in output
    assert "3 securities" in output

    store = _open(tmp_path)
    assert len(store.list_universe_members(1)) == 4
    assert len(store.list_security_refresh_state()) == 3 * 9
    store.close()

    monkeypatch.setattr(
        cli, "FmpClient", lambda _api_key: pytest.fail("evidence-status must be offline")
    )
    assert cli.main(["evidence-status", "--tickers", "ADBE"]) == 0
    status_output = capsys.readouterr().out
    assert "annual_income_statement: pending=1" in status_output


def test_refresh_sp500_cli_requires_an_fmp_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path))

    assert cli.main(["refresh-sp500"]) == 2
    assert "OWNER_LENS_FMP_API_KEY" in capsys.readouterr().err

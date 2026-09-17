"""Tests for the OwnerLens command-line interface (Slice 4B)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from _fixtures import FakeSecClient

import owner_lens
from owner_lens import cli, ingestion
from owner_lens.config import OwnerLensSettings
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


def _settings(tmp_path: Path, user_agent: str | None = "OwnerLens test@example.com"):
    return OwnerLensSettings(
        sec_user_agent=user_agent,
        db_path=str(tmp_path / "db.sqlite"),
        raw_data_path=str(tmp_path / "raw"),
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

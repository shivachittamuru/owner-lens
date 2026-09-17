"""Tests for the OwnerLens local-first configuration boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from owner_lens import CompanyRecord
from owner_lens.config import OwnerLensSettings, build_local_store, load_settings

_VARS = (
    "OWNER_LENS_SEC_USER_AGENT",
    "OWNER_LENS_DB_PATH",
    "OWNER_LENS_RAW_DATA_PATH",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)


def test_default_local_paths() -> None:
    settings = load_settings(env_file=None)
    assert settings.db_path == "data/ownerlens.db"
    assert settings.raw_data_path == "data/raw/sec/company_facts"
    assert settings.sec_user_agent is None


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_LENS_DB_PATH", "custom/o.db")
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", "custom/raw")
    monkeypatch.setenv("OWNER_LENS_SEC_USER_AGENT", "OwnerLens dev@example.com")
    settings = load_settings(env_file=None)
    assert settings.db_path == "custom/o.db"
    assert settings.raw_data_path == "custom/raw"
    assert settings.sec_user_agent == "OwnerLens dev@example.com"


def test_env_file_is_loaded(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OWNER_LENS_DB_PATH=fromfile/o.db\n", encoding="utf-8")
    settings = load_settings(env_file=str(env))
    assert settings.db_path == "fromfile/o.db"


def test_environment_takes_precedence_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("OWNER_LENS_DB_PATH=fromfile/o.db\n", encoding="utf-8")
    monkeypatch.setenv("OWNER_LENS_DB_PATH", "fromenv/o.db")
    settings = load_settings(env_file=str(env))
    assert settings.db_path == "fromenv/o.db"


def test_settings_is_immutable() -> None:
    settings = load_settings(env_file=None)
    with pytest.raises(AttributeError):
        settings.db_path = "mutated"  # type: ignore[misc]


def test_build_local_store_initializes_from_settings(tmp_path: Path) -> None:
    settings = OwnerLensSettings(
        sec_user_agent=None,
        db_path=str(tmp_path / "sub" / "ownerlens.db"),
        raw_data_path=str(tmp_path / "raw"),
    )
    store = build_local_store(settings)
    store.initialize()  # local SQLite + filesystem raw store are usable from settings
    store.save_company(CompanyRecord(cik="0000796343", ticker="ADBE", company_name="A"))
    assert store.get_company("0000796343") is not None
    assert (tmp_path / "sub").is_dir()  # parent dir created for the db path
    store.close()


def test_build_local_store_creates_raw_root(tmp_path: Path) -> None:
    settings = OwnerLensSettings(
        sec_user_agent=None,
        db_path=str(tmp_path / "ownerlens.db"),
        raw_data_path=str(tmp_path / "raw" / "sec" / "company_facts"),
    )
    build_local_store(settings)
    assert (tmp_path / "raw" / "sec" / "company_facts").is_dir()

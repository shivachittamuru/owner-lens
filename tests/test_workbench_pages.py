"""Rendering tests for the workbench pages (Feature 7D).

These run the real Streamlit script through ``AppTest``, with no browser and no
network, so a page that raises is a test failure rather than something only a
human clicking through would notice. The store is a temporary one built from the
offline golden payloads.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _fixtures import FakeSecClient

from owner_lens.ingestion import ingest_company
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore

pytest.importorskip("streamlit", reason="the workbench needs the streamlit group")

from streamlit.testing.v1 import AppTest

_APP = Path(__file__).resolve().parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
_TICKERS = ("ADBE", "V", "COST")
_PAGES = ("Overview", "Screener", "Company", "Compare", "Data Quality")


@pytest.fixture
def store_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A temporary store holding the golden companies, wired into the environment."""
    db_path = tmp_path / "db.sqlite"
    raw_path = tmp_path / "raw"
    store = SqliteStore(db_path, raw_store=FilesystemRawSnapshotStore(raw_path))
    store.initialize()
    with FakeSecClient() as client:
        for ticker in _TICKERS:
            ingest_company(ticker, sec_client=client, store=store)
    store.close()

    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(db_path))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(raw_path))
    yield db_path


def _run(page: str, **session: object) -> AppTest:
    app = AppTest.from_file(str(_APP), default_timeout=120)
    app.session_state["page"] = page
    for key, value in session.items():
        app.session_state[key] = value
    app.run()
    return app


def _assert_clean(app: AppTest, page: str) -> None:
    assert not app.exception, f"{page} raised: {[e.value for e in app.exception]}"
    assert not app.error, f"{page} reported an error: {[e.value for e in app.error]}"


@pytest.mark.parametrize("page", _PAGES)
def test_every_page_renders_without_raising(page: str, store_path: Path) -> None:
    session = {
        "selected_ticker": "ADBE",
        "quality_ticker": "V",
        "compare_tickers": ["ADBE", "COST"],
    }
    app = _run(page, **session)

    _assert_clean(app, page)
    assert app.title, f"{page} rendered no title"


def test_the_overview_shows_the_funnel_derived_from_the_store(store_path: Path) -> None:
    app = _run("Overview")
    _assert_clean(app, "Overview")

    labels = [metric.label for metric in app.metric]
    assert "Companies tracked" in labels
    tracked = next(m for m in app.metric if m.label == "Companies tracked")
    assert tracked.value == str(len(_TICKERS))
    assert any("Opportunity funnel" in h.value for h in app.subheader)


def test_the_screener_lists_every_screenable_company(store_path: Path) -> None:
    app = _run("Screener")
    _assert_clean(app, "Screener")

    assert any(f"of {len(_TICKERS)} companies match" in c.value for c in app.caption)


def test_the_company_page_shows_a_coverage_limited_company_honestly(
    store_path: Path,
) -> None:
    """Visa is PARTIAL, so the page must say what it cannot evaluate."""
    app = _run("Company", selected_ticker="V")
    _assert_clean(app, "Company")

    assert any("V" in t.value for t in app.title)
    coverage = next(m for m in app.metric if m.label == "Coverage")
    assert coverage.value == "PARTIAL"
    evaluable = next(m for m in app.metric if m.label == "Dimensions evaluable")
    assert evaluable.value != "6 of 6"
    assert app.info, "a partial company must explain what is not evaluable"


def test_the_compare_page_requires_at_least_two_companies(store_path: Path) -> None:
    app = _run("Compare", compare_tickers=["ADBE"])
    _assert_clean(app, "Compare")

    assert any("at least 2" in info.value for info in app.info)


def test_the_compare_page_renders_a_table_for_two_companies(store_path: Path) -> None:
    app = _run("Compare", compare_tickers=["ADBE", "V"])
    _assert_clean(app, "Compare")

    headings = [h.value for h in app.subheader]
    assert "Standing" in headings
    assert "Screening dimensions" in headings


def test_the_compare_page_shows_n_a_where_the_engine_refused_a_rate(
    store_path: Path,
) -> None:
    """Visa has no compounding view, so every compounding cell must read N/A."""
    app = _run("Compare", compare_tickers=["ADBE", "V"])
    _assert_clean(app, "Compare")

    frames = [element.value for element in app.dataframe]
    compounding = next(
        frame for frame in frames if "FCF/share CAGR" in frame.index
    )

    assert set(compounding["V"]) == {"N/A"}
    assert compounding.loc["FCF/share CAGR", "ADBE"] != "N/A"
    assert compounding.loc["Compounding window", "ADBE"].startswith("FY")


def test_the_compare_page_preserves_a_not_evaluable_dimension(
    store_path: Path,
) -> None:
    app = _run("Compare", compare_tickers=["ADBE", "V"])
    _assert_clean(app, "Compare")

    dimensions = next(
        frame.value
        for frame in app.dataframe
        if "Per-Share Compounding band" in frame.value.index
    )

    assert dimensions.loc["Per-Share Compounding band", "V"] == "NOT EVALUABLE"
    assert dimensions.loc["Business Quality band", "ADBE"] == "STRONG"


def test_the_data_quality_page_lists_every_company_and_diagnoses_one(
    store_path: Path,
) -> None:
    app = _run("Data Quality", quality_ticker="V")
    _assert_clean(app, "Data Quality")

    headings = [h.value for h in app.subheader]
    assert "Coverage across the store" in headings
    assert any("V —" in h.value for h in app.subheader)


def test_an_empty_store_explains_itself_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(tmp_path / "empty.sqlite"))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(tmp_path / "raw"))

    app = _run("Overview")

    _assert_clean(app, "Overview (empty store)")
    assert any("No company is persisted" in w.value for w in app.warning)


@pytest.mark.parametrize("page", _PAGES)
def test_a_corrupt_snapshot_does_not_blank_any_page(
    page: str, store_path: Path
) -> None:
    """One unreadable payload must degrade its own row, not the application."""
    import os

    raw_path = Path(os.environ["OWNER_LENS_RAW_DATA_PATH"])
    corrupt = next(raw_path.rglob("*.json"))
    corrupt.write_text("not json at all", encoding="utf-8")

    app = _run(
        page,
        selected_ticker="ADBE",
        quality_ticker="V",
        compare_tickers=["ADBE", "COST"],
    )

    assert not app.exception, f"{page} raised: {[e.value for e in app.exception]}"
    assert app.title, f"{page} rendered no title"


def test_an_unopenable_store_reports_an_error_rather_than_a_blank_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory where the database should be is the simplest unopenable store."""
    blocked = tmp_path / "not-a-database"
    blocked.mkdir()
    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(blocked))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(tmp_path / "raw"))

    app = _run("Overview")

    assert not app.exception, [e.value for e in app.exception]
    assert app.title
    assert any("could not be opened" in e.value for e in app.error)

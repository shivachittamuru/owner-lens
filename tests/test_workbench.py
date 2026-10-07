"""Tests for the OwnerLens workbench data service (Feature 7D).

The workbench's logic lives entirely in :mod:`owner_lens.workbench.data`, which
imports no Streamlit, so everything below runs without a browser. The fixtures
build a real local store from the offline golden payloads, so these tests
exercise the same persistence path the running application uses.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _fixtures import FakeSecClient

from owner_lens.canonical import MetricStatus
from owner_lens.cli import main as cli_main
from owner_lens.config import OwnerLensSettings
from owner_lens.ingestion import ingest_company
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.persistence.errors import StorageReadError
from owner_lens.screening import (
    DIMENSION_ORDER,
    CoverageClass,
    DimensionBand,
    ScreeningBucket,
    ScreeningDimension,
    screen_company_from_facts,
)
from owner_lens.sec_adapter import SEC_PROVIDER
from owner_lens.workbench import data as wb

_TICKERS = ("ADBE", "V", "COST")


@pytest.fixture
def source(tmp_path: Path) -> Iterator[wb.WorkbenchSource]:
    """A real local store holding the three golden companies."""
    settings = OwnerLensSettings(
        sec_user_agent="OwnerLens test@example.com",
        db_path=str(tmp_path / "db.sqlite"),
        raw_data_path=str(tmp_path / "raw"),
    )
    store = SqliteStore(
        Path(settings.db_path), raw_store=FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    )
    store.initialize()
    with FakeSecClient() as client:
        for ticker in _TICKERS:
            ingest_company(ticker, sec_client=client, store=store)
    store.close()

    opened = wb.open_source(settings)
    yield opened
    opened.close()


def _company(source: wb.WorkbenchSource, ticker: str) -> wb.PersistedCompany:
    return next(
        c for c in wb.load_persisted_companies(source) if c.ticker == ticker
    )


# --- 1. Persisted-company discovery --------------------------------------------


def test_persisted_companies_are_discovered_in_ticker_order(
    source: wb.WorkbenchSource,
) -> None:
    companies = wb.load_persisted_companies(source)

    assert [c.ticker for c in companies] == sorted(_TICKERS)
    assert all(c.available for c in companies)
    assert all(c.content_hash and c.cik and c.company_name for c in companies)


def test_a_company_without_a_readable_snapshot_is_listed_not_dropped(
    source: wb.WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing payload must be visible, so the UI can say so explicitly."""
    monkeypatch.setattr(source.raw_store, "exists", lambda _hash: False)
    companies = wb.load_persisted_companies(source)

    assert [c.ticker for c in companies] == sorted(_TICKERS)
    assert all(not c.available for c in companies)
    assert all(c.content_hash is None for c in companies)


def test_reading_a_company_with_no_snapshot_explains_how_to_fix_it(
    source: wb.WorkbenchSource,
) -> None:
    absent = wb.PersistedCompany(
        ticker="ZZZZ",
        company_name="Never Ingested",
        cik="0000000000",
        content_hash=None,
        fetched_at=None,
        processing_status=None,
    )

    with pytest.raises(wb.WorkbenchError, match="owner-lens ingest ZZZZ"):
        wb.load_raw_facts(source, absent)


# --- 2. Canonical-history reconstruction ---------------------------------------


def test_canonical_history_is_rebuilt_from_the_persisted_snapshot(
    source: wb.WorkbenchSource,
) -> None:
    history = wb.load_canonical_history(source, _company(source, "ADBE"))

    assert history.ticker == "ADBE"
    assert history.statuses()["revenue"] is MetricStatus.AVAILABLE
    assert history.providers() == frozenset({SEC_PROVIDER})


def test_history_reconstruction_honours_the_requested_window(
    source: wb.WorkbenchSource,
) -> None:
    history = wb.load_canonical_history(source, _company(source, "ADBE"), max_years=2)

    assert history.max_years == 2


# --- 3. Screening universe loading ---------------------------------------------


def test_screening_the_persisted_universe_returns_ranked_results(
    source: wb.WorkbenchSource,
) -> None:
    results = wb.screen_persisted_universe(source)

    assert [r.ticker for r in results] == sorted(
        [r.ticker for r in results],
        key=lambda t: next(r.rank_key for r in results if r.ticker == t),
    )
    assert {r.ticker for r in results} == set(_TICKERS)


def test_companies_without_a_snapshot_are_skipped_rather_than_screened_on_nothing(
    source: wb.WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source.raw_store, "exists", lambda _hash: False)

    assert wb.screen_persisted_universe(source) == ()


# --- 4. Overview counts derived dynamically ------------------------------------


def test_overview_counts_are_derived_from_the_data_supplied(
    source: wb.WorkbenchSource,
) -> None:
    companies = wb.load_persisted_companies(source)
    results = wb.screen_persisted_universe(source, companies)
    counts = wb.overview_counts(companies, results)

    assert counts.tracked == len(companies)
    assert counts.without_snapshot == 0
    assert sum(counts.by_coverage.values()) == len(results)
    assert sum(counts.by_bucket.values()) == len(results)
    assert counts.screened == len(results)


def test_overview_counts_track_a_smaller_universe(source: wb.WorkbenchSource) -> None:
    """Nothing is hard-coded: removing a company changes every headline count."""
    companies = wb.load_persisted_companies(source)
    subset = companies[:1]
    results = wb.screen_persisted_universe(source, subset)
    counts = wb.overview_counts(subset, results)

    assert counts.tracked == 1
    assert counts.screened == 1
    assert counts.funnel[0] == ("Companies tracked", 1)


def test_the_funnel_narrows_from_tracked_to_screenable_to_worth_underwriting(
    source: wb.WorkbenchSource,
) -> None:
    companies = wb.load_persisted_companies(source)
    counts = wb.overview_counts(
        companies, wb.screen_persisted_universe(source, companies)
    )
    stages = [count for _, count in counts.funnel]

    assert stages[0] >= stages[1] >= stages[2]
    assert counts.screenable == counts.screened - counts.by_bucket.get(
        ScreeningBucket.INSUFFICIENT_DATA, 0
    )


def test_the_research_queue_holds_only_the_two_highest_buckets(
    source: wb.WorkbenchSource,
) -> None:
    results = wb.screen_persisted_universe(source)
    queue = wb.research_queue(results)

    assert all(
        result.bucket
        in (ScreeningBucket.HIGH_PRIORITY, ScreeningBucket.WORTH_UNDERWRITING)
        for result in queue
    )
    assert [r.rank_key for r in queue] == sorted(r.rank_key for r in queue)


# --- 5. Company detail model ---------------------------------------------------


def test_company_detail_assembles_every_available_layer(
    source: wb.WorkbenchSource,
) -> None:
    detail = wb.company_detail(source, _company(source, "ADBE"))

    assert detail.company.ticker == "ADBE"
    assert detail.owner_economics
    assert detail.capital_efficiency
    assert detail.capital_allocation
    assert detail.snapshots
    assert detail.summary is not None
    assert detail.screening.coverage_class is CoverageClass.FULL
    assert set(detail.screening.dimensions) == set(ScreeningDimension)


def test_company_detail_explains_an_unavailable_layer_instead_of_emptying_it(
    source: wb.WorkbenchSource,
) -> None:
    """Visa files no diluted-share concept, so its economic value is blocked."""
    detail = wb.company_detail(source, _company(source, "V"))

    assert detail.screening.coverage_class is CoverageClass.PARTIAL
    assert not detail.snapshots
    assert detail.summary is None
    reason = detail.economic_value_unavailable_reason
    assert reason and "diluted" in reason.lower()
    assert detail.summary_unavailable_reason


def test_company_detail_reports_the_strongest_and_main_limiting_reasons(
    source: wb.WorkbenchSource,
) -> None:
    detail = wb.company_detail(source, _company(source, "ADBE"))

    assert wb.strongest_reason(detail.screening) in {
        reason.value for reason in detail.screening.supporting_reasons
    }
    limiting = wb.main_limiting_reason(detail.screening)
    assert limiting is None or isinstance(limiting, str)


# --- 6. Comparison model -------------------------------------------------------


def test_comparison_covers_every_documented_row_for_each_company(
    source: wb.WorkbenchSource,
) -> None:
    details = [wb.company_detail(source, _company(source, t)) for t in ("ADBE", "COST")]
    table = wb.build_comparison(details)

    assert table.tickers == ("ADBE", "COST")
    assert len(table.rows) == len({label for label, _ in table.rows})
    for label, _ in table.rows:
        for ticker in table.tickers:
            assert label in next(c for c in table.columns if c.ticker == ticker).values


def test_comparison_includes_every_screening_dimension(
    source: wb.WorkbenchSource,
) -> None:
    table = wb.build_comparison(
        [wb.company_detail(source, _company(source, t)) for t in ("ADBE", "V")]
    )
    labels = {label for label, _ in table.rows}

    for dimension in DIMENSION_ORDER:
        assert f"{wb.DIMENSION_LABEL[dimension]} band" in labels


# --- 7. Unavailable values preserved as None -----------------------------------


def test_unavailable_comparison_values_stay_none_and_render_as_not_available(
    source: wb.WorkbenchSource,
) -> None:
    """Visa has no per-share metrics; they must be None, never zero."""
    table = wb.build_comparison(
        [wb.company_detail(source, _company(source, t)) for t in ("ADBE", "V")]
    )

    assert table.value("FCF/share CAGR", "V") is None
    assert table.value("Diluted-share CAGR", "V") is None
    assert wb.format_comparison_value("FCF/share CAGR", None) == wb.NOT_AVAILABLE
    assert table.value("FCF/share CAGR", "ADBE") is not None


def test_a_not_evaluable_dimension_is_preserved_rather_than_filled(
    source: wb.WorkbenchSource,
) -> None:
    table = wb.build_comparison(
        [wb.company_detail(source, _company(source, t)) for t in ("ADBE", "V")]
    )
    label = f"{wb.DIMENSION_LABEL[ScreeningDimension.PER_SHARE_COMPOUNDING]} band"

    assert table.value(label, "V") is DimensionBand.NOT_EVALUABLE
    assert wb.BAND_LABEL[DimensionBand.NOT_EVALUABLE] == "NOT EVALUABLE"


def test_formatting_never_turns_a_missing_value_into_a_number() -> None:
    assert wb.format_ratio(None) == wb.NOT_AVAILABLE
    assert wb.format_money(None) == wb.NOT_AVAILABLE
    assert wb.format_per_share(None) == wb.NOT_AVAILABLE
    assert wb.format_count(None) == wb.NOT_AVAILABLE


def test_compounding_rates_come_from_the_engine_view_not_a_local_derivation(
    source: wb.WorkbenchSource,
) -> None:
    """The Compare page must never publish a rate the engine refused to derive.

    Visa has no diluted-share concept, so Feature 2B declines to build a
    compounding view for it. Every compounding row must therefore read N/A
    rather than a rate computed over some other window.
    """
    details = {
        t: wb.company_detail(source, _company(source, t)) for t in ("ADBE", "V")
    }
    table = wb.build_comparison(details.values())

    assert details["V"].long_term_compounding is None
    for label in (
        "Compounding window",
        "Revenue CAGR",
        "FCF CAGR",
        "FCF/share CAGR",
        "Diluted-share CAGR",
    ):
        assert table.value(label, "V") is None, label

    view = details["ADBE"].long_term_compounding
    assert view is not None
    assert table.value("Revenue CAGR", "ADBE") == view.revenue_cagr
    assert table.value("FCF/share CAGR", "ADBE") == view.fcf_per_share_cagr
    assert table.value("Compounding window", "ADBE") == (
        f"FY{view.start_fiscal_year}–FY{view.end_fiscal_year}"
    )


def test_a_corrupt_snapshot_degrades_one_company_not_the_whole_workbench(
    source: wb.WorkbenchSource, tmp_path: Path
) -> None:
    """A payload that exists but is unreadable must not blank every page."""
    adbe = _company(source, "ADBE")
    assert adbe.content_hash is not None
    corrupt = next(Path(source.raw_data_path).rglob(f"{adbe.content_hash}.json"))
    corrupt.write_text("not json at all", encoding="utf-8")

    with pytest.raises(wb.WorkbenchError, match="not valid JSON"):
        wb.load_raw_facts(source, adbe)

    results = wb.screen_persisted_universe(source)
    assert {r.ticker for r in results} == {"V", "COST"}

    standings = wb.coverage_standings(source, wb.load_persisted_companies(source))
    assert len(standings) == len(_TICKERS)
    assert next(s for s in standings if s.company.ticker == "ADBE").overall == "ERROR"


def test_a_payload_that_is_not_an_object_is_refused(
    source: wb.WorkbenchSource,
) -> None:
    adbe = _company(source, "ADBE")
    assert adbe.content_hash is not None
    path = next(Path(source.raw_data_path).rglob(f"{adbe.content_hash}.json"))
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(wb.WorkbenchError, match="not a Company Facts object"):
        wb.load_raw_facts(source, adbe)


def test_a_failed_store_initialization_closes_its_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SqliteStore connects eagerly, so a failed open must not leak a connection."""
    closed: list[bool] = []
    settings = OwnerLensSettings(
        sec_user_agent=None,
        db_path=str(tmp_path / "db.sqlite"),
        raw_data_path=str(tmp_path / "raw"),
    )

    def failing_initialize(self: SqliteStore) -> None:
        raise StorageReadError("schema is incompatible")

    original_close = SqliteStore.close

    def recording_close(self: SqliteStore) -> None:
        closed.append(True)
        original_close(self)

    monkeypatch.setattr(SqliteStore, "initialize", failing_initialize)
    monkeypatch.setattr(SqliteStore, "close", recording_close)

    with pytest.raises(StorageReadError):
        wb.open_source(settings)

    assert closed == [True]


# --- 8. FAILED companies visible in the data-quality view ----------------------


def test_data_quality_exposes_available_and_unusable_metrics(
    source: wb.WorkbenchSource,
) -> None:
    report = wb.data_quality_report(source, _company(source, "V"))

    assert report.available
    assert {m.metric for m in report.unsupported} == {"diluted_shares"}
    assert {m.metric for m in report.structurally_absent} >= {"short_term_investments"}
    assert set(report.layers) and all(
        isinstance(state, str) for state, _ in report.layers.values()
    )


def test_data_quality_carries_the_selected_concept_and_what_else_was_tried(
    source: wb.WorkbenchSource,
) -> None:
    report = wb.data_quality_report(source, _company(source, "ADBE"))
    revenue = next(m for m in report.metrics if m.metric == "revenue")

    assert revenue.available
    assert revenue.concept_used
    assert revenue.concepts_tried
    assert revenue.latest_fiscal_year is not None


def test_every_company_appears_in_the_coverage_standings(
    source: wb.WorkbenchSource,
) -> None:
    companies = wb.load_persisted_companies(source)
    standings = wb.coverage_standings(source, companies)

    assert [s.company.ticker for s in standings] == [c.ticker for c in companies]
    assert all(s.overall for s in standings)


def test_a_company_without_a_snapshot_still_appears_with_its_reason(
    source: wb.WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A company OwnerLens cannot use must never silently vanish from the grid."""
    monkeypatch.setattr(source.raw_store, "exists", lambda _hash: False)
    standings = wb.coverage_standings(source, wb.load_persisted_companies(source))

    assert len(standings) == len(_TICKERS)
    assert all(s.overall == "NO SNAPSHOT" for s in standings)
    assert all(s.primary_blocker for s in standings)


# --- 9. PARTIAL companies retain their missing dimensions ----------------------


def test_a_partial_company_keeps_its_unavailable_dimensions(
    source: wb.WorkbenchSource,
) -> None:
    detail = wb.company_detail(source, _company(source, "V"))
    result = detail.screening

    assert result.coverage_class is CoverageClass.PARTIAL
    assert ScreeningDimension.PER_SHARE_COMPOUNDING in result.unavailable_dimensions
    assert result.evaluable_dimensions < len(DIMENSION_ORDER)
    assert result.coverage_ceiling is not None
    assert all(
        detail.dimension(d).band is DimensionBand.NOT_EVALUABLE
        for d in result.unavailable_dimensions
    )


def test_a_partial_company_is_never_promoted_above_its_coverage_ceiling(
    source: wb.WorkbenchSource,
) -> None:
    results = {r.ticker: r for r in wb.screen_persisted_universe(source)}
    partial = results["V"]

    assert partial.coverage_ceiling is not None
    assert partial.bucket is not ScreeningBucket.HIGH_PRIORITY


# --- 10. No network call -------------------------------------------------------


def test_loading_the_workbench_makes_no_network_call(
    source: wb.WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every page's data is built with the transport layers disabled."""
    import httpx

    import owner_lens.sec as sec_module

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the workbench must not open a network connection")

    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "get", forbidden, raising=False)
    monkeypatch.setattr(sec_module.SecClient, "__init__", forbidden)

    companies = wb.load_persisted_companies(source)
    results = wb.screen_persisted_universe(source, companies)
    wb.overview_counts(companies, results)
    details = [wb.company_detail(source, company) for company in companies]
    wb.build_comparison(details[:2])
    for company in companies:
        wb.data_quality_report(source, company)
    wb.coverage_standings(source, companies)


# --- 11. Cache keys include the source content hash ----------------------------


def test_the_cache_fingerprint_is_the_content_hash_of_each_company(
    source: wb.WorkbenchSource,
) -> None:
    from owner_lens.workbench.cache import fingerprint

    companies = wb.load_persisted_companies(source)
    prints = fingerprint(companies)

    assert prints == tuple(
        (c.ticker, c.content_hash or "") for c in companies if c.available
    )
    assert all(content_hash for _, content_hash in prints)


def test_a_changed_snapshot_changes_the_cache_fingerprint(
    source: wb.WorkbenchSource,
) -> None:
    """A re-ingested payload must invalidate derived results, not reuse them."""
    from owner_lens.workbench.cache import fingerprint

    companies = wb.load_persisted_companies(source)
    before = fingerprint(companies)
    mutated = tuple(
        wb.PersistedCompany(
            ticker=c.ticker,
            company_name=c.company_name,
            cik=c.cik,
            content_hash=("changed" if c.ticker == "ADBE" else c.content_hash),
            fetched_at=c.fetched_at,
            processing_status=c.processing_status,
        )
        for c in companies
    )

    assert fingerprint(mutated) != before


def test_cached_entry_points_take_hashable_scalars_only() -> None:
    """A cache key must never capture a live store handle."""
    import inspect

    from owner_lens.workbench import cache

    for name in (
        "cached_screening",
        "cached_company_detail",
        "cached_comparison",
        "cached_data_quality",
        "cached_coverage_standings",
    ):
        signature = inspect.signature(getattr(cache, name).__wrapped__)
        for parameter in signature.parameters.values():
            assert parameter.annotation in {
                "str",
                "int",
                "tuple[tuple[str, str], ...]",
            }, f"{name}.{parameter.name} is {parameter.annotation}"


def test_the_company_list_is_never_cached_so_reingestion_self_invalidates() -> None:
    """Caching the list would freeze the fingerprint every other key is built from."""
    from owner_lens.workbench import cache

    assert not hasattr(cache, "cached_companies")
    assert "cached_companies" not in cache.__all__


def test_a_cached_result_refuses_a_payload_other_than_the_one_its_key_names(
    source: wb.WorkbenchSource,
) -> None:
    """A key names a snapshot; computing against a different one would mislabel it."""
    from owner_lens.workbench.cache import _one, _select

    with pytest.raises(wb.WorkbenchError, match="changed on disk"):
        _one(source, "ADBE", "a-hash-that-is-not-current")
    with pytest.raises(wb.WorkbenchError, match="changed on disk"):
        _select(source, (("ADBE", "a-hash-that-is-not-current"),))

    current = _company(source, "ADBE")
    assert current.content_hash is not None
    assert _one(source, "ADBE", current.content_hash) == current


def test_a_source_closes_its_connection_when_used_as_a_context_manager(
    tmp_path: Path,
) -> None:
    """A SQLite connection is thread-bound, so a source must not outlive its work."""
    settings = OwnerLensSettings(
        sec_user_agent=None,
        db_path=str(tmp_path / "db.sqlite"),
        raw_data_path=str(tmp_path / "raw"),
    )
    with wb.open_source(settings) as opened:
        assert wb.load_persisted_companies(opened) == ()

    with pytest.raises(StorageReadError):
        opened.store.list_companies()


# --- 12. Feature 7 conclusions are unchanged -----------------------------------


def test_the_workbench_reports_the_same_verdict_as_the_screening_engine(
    source: wb.WorkbenchSource,
) -> None:
    """The UI must never disagree with the CLI or the tests."""
    from _fixtures import adbe_facts, costco_facts, visa_facts

    direct = {
        "ADBE": screen_company_from_facts(adbe_facts(), ticker="ADBE"),
        "V": screen_company_from_facts(visa_facts(), ticker="V"),
        "COST": screen_company_from_facts(costco_facts(), ticker="COST"),
    }
    through_workbench = {r.ticker: r for r in wb.screen_persisted_universe(source)}

    assert set(through_workbench) == set(direct)
    for ticker, expected in direct.items():
        actual = through_workbench[ticker]
        assert actual.bucket is expected.bucket
        assert actual.setup_type is expected.setup_type
        assert actual.screening_score == expected.screening_score
        assert actual.limiting_factor is expected.limiting_factor
        assert {d: s.band for d, s in actual.dimensions.items()} == {
            d: s.band for d, s in expected.dimensions.items()
        }


def test_company_detail_agrees_with_the_screening_engine(
    source: wb.WorkbenchSource,
) -> None:
    from _fixtures import adbe_facts

    detail = wb.company_detail(source, _company(source, "ADBE"))
    expected = screen_company_from_facts(adbe_facts(), ticker="ADBE")

    assert detail.screening == expected


# --- CLI integration -----------------------------------------------------------


def test_the_workbench_command_reports_a_missing_streamlit_clearly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import builtins

    real_import = builtins.__import__

    def without_streamlit(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("streamlit"):
            raise ImportError("No module named 'streamlit'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_streamlit)

    assert cli_main(["workbench"]) == 2
    assert "Streamlit" in capsys.readouterr().err


def test_the_workbench_command_restores_argv_and_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both are process-wide, so an in-process caller must see them unchanged."""
    import os
    import sys as _sys

    captured: dict[str, Any] = {}

    def fake_main(prog_name: str | None = None) -> None:
        captured["argv"] = list(_sys.argv)
        captured["db"] = os.environ.get("OWNER_LENS_DB_PATH")

    _install_fake_streamlit_cli(monkeypatch, fake_main)
    monkeypatch.delenv("OWNER_LENS_DB_PATH", raising=False)
    argv_before = list(_sys.argv)

    db = str(tmp_path / "other.db")
    assert cli_main(["workbench", "--db", db, "--port", "8777", "--no-browser"]) == 0

    assert captured["db"] == db
    assert "run" in captured["argv"]
    assert captured["argv"][2].endswith("app.py")
    assert "8777" in captured["argv"]
    assert "--server.headless" in captured["argv"]
    assert _sys.argv == argv_before
    assert "OWNER_LENS_DB_PATH" not in os.environ


def test_the_workbench_command_restores_a_preexisting_store_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os

    _install_fake_streamlit_cli(monkeypatch, lambda prog_name=None: None)
    monkeypatch.setenv("OWNER_LENS_DB_PATH", "original.db")

    assert cli_main(["workbench", "--db", str(tmp_path / "other.db")]) == 0

    assert os.environ["OWNER_LENS_DB_PATH"] == "original.db"


def _install_fake_streamlit_cli(
    monkeypatch: pytest.MonkeyPatch, main: Any
) -> None:
    """Replace Streamlit's CLI so the command can be exercised without a server."""
    import sys as _sys
    import types

    module = types.ModuleType("streamlit.web.cli")
    module.main = main  # type: ignore[attr-defined]
    package = types.ModuleType("streamlit.web")
    package.cli = module  # type: ignore[attr-defined]
    root = types.ModuleType("streamlit")
    root.web = package  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "streamlit", root)
    monkeypatch.setitem(_sys.modules, "streamlit.web", package)
    monkeypatch.setitem(_sys.modules, "streamlit.web.cli", module)


def test_the_workbench_data_layer_imports_without_streamlit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests and scripts must be able to use the data layer with no UI stack."""
    import importlib
    import sys

    for name in [n for n in sys.modules if n.startswith("owner_lens.workbench.data")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    for name in [n for n in sys.modules if n.startswith("streamlit")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(
        sys, "meta_path", [_BlockStreamlit(), *sys.meta_path], raising=False
    )

    module = importlib.import_module("owner_lens.workbench.data")

    assert module.DEFAULT_MAX_YEARS == 5
    assert not any(name.startswith("streamlit") for name in sys.modules)


class _BlockStreamlit:
    """Import hook that refuses any Streamlit import."""

    def find_module(self, fullname: str, path: object = None) -> None:
        return None

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname.startswith("streamlit"):
            raise ImportError(f"{fullname} must not be imported by the data layer")

"""Offline full-universe FMP screening and workbench regression tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from _fixtures import FakeSecClient
from _fmp_fixtures import fmp_payloads, fmp_statements
from streamlit.testing.v1 import AppTest

from owner_lens.cli import main
from owner_lens.fmp_adapter import FMP_FIELD_MAP, canonical_history_from_fmp
from owner_lens.ingestion import ingest_company
from owner_lens.persistence import (
    FilesystemRawSnapshotStore,
    SqliteStore,
    compute_content_hash,
)
from owner_lens.persistence.records import (
    FmpCanonicalCoverageRecord,
    FmpCanonicalFactRecord,
    FmpCanonicalHistoryRecord,
    FmpEodPriceRecord,
    FmpEstimateRecord,
    FmpEvidenceSnapshotRecord,
    UniverseConstituentRecord,
    UniverseSnapshotRecord,
)
from owner_lens.screening import (
    CoverageClass,
    DimensionBand,
    screen_company_from_history,
)
from owner_lens.workbench import cache
from owner_lens.workbench.data import (
    WorkbenchSource,
    build_comparison,
    company_detail,
    data_quality_report,
    load_canonical_history,
    load_persisted_companies,
    open_source,
    overview_counts,
    screen_persisted_universe,
)

_AS_OF = "2026-06-01T00:00:00+00:00"
_APP = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
_SYMBOLS = ("ADBE", "GOOG", "GOOGL", "PARTIAL", "MISSING") + tuple(
    f"TEST{index:03}" for index in range(498)
)


def _snapshot(
    store: SqliteStore,
    security_id: int,
    dataset: str,
    period: str,
    rows: list[dict[str, object]],
    *,
    fetched_at: str = _AS_OF,
) -> int:
    payload = json.dumps(rows).encode()
    snapshot_id, _, _ = store.save_fmp_evidence_snapshot(
        FmpEvidenceSnapshotRecord(
            security_id,
            dataset,
            period,
            "/stable/fixture",
            json.dumps({"period": period}),
            fetched_at,
            compute_content_hash(payload),
            evidence_kind="EXPECTATION" if "estimates" in dataset else "FACT",
        ),
        raw_payload=payload,
    )
    store.update_security_refresh_state(
        security_id, dataset, status="SUCCEEDED", updated_at=fetched_at
    )
    return snapshot_id


@pytest.fixture(scope="module")
def fmp_paths(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("fmp-workbench")
    db, raw = root / "store.sqlite", root / "raw"
    store = SqliteStore(db, raw_store=FilesystemRawSnapshotStore(raw))
    store.initialize()
    members = tuple(
        UniverseConstituentRecord(symbol, symbol, "0000796343") for symbol in _SYMBOLS
    )
    payload = json.dumps(list(_SYMBOLS)).encode()
    store.save_universe_snapshot(
        UniverseSnapshotRecord(
            "fmp", _AS_OF, "/stable/sp500-constituent", compute_content_hash(payload)
        ),
        members,
        raw_payload=payload,
        state_symbols=_SYMBOLS,
        datasets=("annual_statements", "quarterly_statements", "analyst_estimates"),
        created_at=_AS_OF,
    )
    for security in store.list_securities():
        if security.symbol == "MISSING":
            store.update_security_refresh_state(
                security.security_id,
                "annual_income_statement",
                status="FAILED",
                updated_at=_AS_OF,
                last_error="Fixture statement unavailable",
            )
            continue
        payloads = fmp_payloads(security.symbol)
        if security.symbol == "PARTIAL":
            for row in payloads["income-statement"]:
                row.pop("incomeTaxExpense")
        history = canonical_history_from_fmp(
            fmp_statements(security.symbol, payloads), max_years=15
        )
        snapshots = {
            statement: _snapshot(
                store,
                security.security_id,
                f"annual_{statement}_statement",
                "annual",
                payloads[endpoint],
            )
            for statement, endpoint in (
                ("income", "income-statement"),
                ("balance_sheet", "balance-sheet-statement"),
                ("cash_flow", "cash-flow-statement"),
            )
        }
        store.save_fmp_canonical_history(
            FmpCanonicalHistoryRecord(
                security.security_id,
                compute_content_hash(json.dumps(payloads).encode()),
                _AS_OF,
                15,
                facts=tuple(
                    FmpCanonicalFactRecord(
                        series.metric,
                        fact.value,
                        fact.unit,
                        fact.fiscal_year,
                        fact.period_end.isoformat(),
                        fact.provider_field or "",
                        snapshots[FMP_FIELD_MAP[series.metric].statement],
                    )
                    for series in history.series
                    for fact in series.observations
                ),
                coverage=tuple(
                    FmpCanonicalCoverageRecord(
                        series.metric, series.status.value, series.reason
                    )
                    for series in history.series
                ),
            )
        )
    adbe = next(s for s in store.list_securities() if s.symbol == "ADBE")
    _snapshot(
        store,
        adbe.security_id,
        "quarterly_income_statement",
        "quarterly",
        [{"date": "2026-03-31", "revenue": 999999, "period": "Q1"}],
    )
    price_id = _snapshot(
        store,
        adbe.security_id,
        "eod_price",
        "eod",
        [{"date": "2026-05-29", "price": 123.5}],
    )
    store.save_fmp_eod_price(
        FmpEodPriceRecord(
            price_id, adbe.security_id, "2026-05-29", 123.5, "price", "USD"
        )
    )
    estimate_id = _snapshot(
        store,
        adbe.security_id,
        "annual_analyst_estimates",
        "annual",
        [{"date": "2027-11-30", "revenueAvg": 1e12}],
    )
    store.save_fmp_estimates(
        (
            FmpEstimateRecord(
                estimate_id,
                "2027-11-30",
                revenue_low=9e11,
                revenue_average=1e12,
                revenue_high=1.1e12,
                revenue_analyst_count=8,
            ),
        )
    )
    store.update_security_refresh_state(
        adbe.security_id,
        "quarterly_analyst_estimates",
        status="UNSUPPORTED",
        updated_at=_AS_OF,
        last_error="Fixture Premium entitlement unavailable",
    )
    with FakeSecClient() as client:
        ingest_company("ADBE", sec_client=client, store=store)
    store.close()
    return db, raw


@pytest.fixture
def fmp_source(
    fmp_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[WorkbenchSource]:
    db, raw = fmp_paths
    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(db))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(raw))
    monkeypatch.setenv("OWNER_LENS_WORKBENCH_PROVIDER", "sec")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Workbench navigation must not access the network")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    cache.clear_caches()
    with open_source() as source:
        yield source
    cache.clear_caches()


def test_fmp_full_universe_preserves_feature_seven(fmp_source: WorkbenchSource) -> None:
    companies = load_persisted_companies(fmp_source, "fmp")
    assert len(companies) == 503
    assert [company.ticker for company in load_persisted_companies(fmp_source)] == [
        "ADBE"
    ]
    results = screen_persisted_universe(fmp_source, companies)
    assert len(results) == 503
    adbe = next(result for result in results if result.ticker == "ADBE")
    assert adbe == screen_company_from_history(
        canonical_history_from_fmp(fmp_statements(), max_years=5)
    )
    by_symbol = {company.ticker: company for company in companies}
    assert by_symbol["GOOG"].security_id != by_symbol["GOOGL"].security_id
    assert by_symbol["GOOG"].cik == by_symbol["GOOGL"].cik
    missing = next(result for result in results if result.ticker == "MISSING")
    assert missing.coverage_class is CoverageClass.FAILED
    assert all(
        score.band is DimensionBand.NOT_EVALUABLE
        for score in missing.dimensions.values()
    )
    assert (
        next(result for result in results if result.ticker == "PARTIAL").coverage_class
        is CoverageClass.PARTIAL
    )
    counts = overview_counts(companies, results)
    assert counts.tracked == counts.screened == 503
    assert sum(counts.by_coverage.values()) == 503
    assert sum(counts.by_bucket.values()) == 503


def test_review_lane_owner_economics_reuses_persisted_fmp_without_refresh(
    fmp_source: WorkbenchSource,
) -> None:
    companies = load_persisted_companies(fmp_source, "fmp")
    results = screen_persisted_universe(fmp_source, companies)
    before = {result.ticker: result for result in results}

    economics = cache.cached_improving_economics_owner_economics(
        cache.fingerprint(companies),
        ("ADBE",),
        db_path=fmp_source.db_path,
    )

    after = {
        result.ticker: result
        for result in screen_persisted_universe(fmp_source, companies)
    }
    assert len(economics) == 1
    assert economics[0][0] == "ADBE"
    assert len(economics[0][1]) == 3
    assert after == before


def test_review_lane_view_renders_offline_from_short_fixture_history(
    fmp_source: WorkbenchSource,
) -> None:
    app = AppTest.from_file(str(_APP), default_timeout=120)
    app.session_state["provider"] = "fmp"
    app.session_state["page"] = "Screener"
    app.session_state["screener_view_mode"] = "Improving Economics - Review Only"
    app.run()

    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    assert any(
        title.value == "Improving Economics — Review Only; Not a Valuation Signal"
        for title in app.title
    )
    assert any(
        "No company matches the Improving Economics review filter" in item.value
        for item in app.info
    )


def test_separate_evidence_provenance_and_quality(fmp_source: WorkbenchSource) -> None:
    companies = {c.ticker: c for c in load_persisted_companies(fmp_source, "fmp")}
    detail = company_detail(fmp_source, companies["ADBE"])
    assert detail.quarterly_evidence[0]["revenue"] == 999999
    assert detail.eod_prices[0]["market_date"] == "2026-05-29"
    assert detail.market_expectations[0]["evidence_kind"] == "EXPECTATION"
    assert detail.market_expectations[0]["revenue_analyst_count"] == 8
    assert detail.market_expectations[0]["fetched_at"] == _AS_OF
    assert len(detail.annual_provenance) == 3
    assert all(
        snapshot["period_type"] == "annual" for snapshot in detail.annual_provenance
    )
    assert detail.screening == screen_company_from_history(
        canonical_history_from_fmp(fmp_statements(), max_years=5)
    )
    history = load_canonical_history(fmp_source, companies["ADBE"])
    assert all(
        fact.provider == "fmp" and fact.fiscal_period == "FY"
        for series in history.series
        for fact in series.observations
    )
    report = data_quality_report(fmp_source, companies["ADBE"])
    assert report.survey is None
    assert any(
        state.status == "UNSUPPORTED" and state.last_error
        for state in report.dataset_states
    )
    assert all(
        snapshot["content_hash"] and snapshot["source_endpoint"]
        for snapshot in report.evidence_snapshots
    )
    missing_report = data_quality_report(fmp_source, companies["MISSING"])
    assert missing_report.overall == "FAILED"
    assert missing_report.screening_reasons
    assert missing_report.dataset_states[0].last_error
    comparison = build_comparison(
        company_detail(fmp_source, companies[ticker])
        for ticker in ("ADBE", "GOOG", "GOOGL", "PARTIAL", "MISSING")
    )
    assert len(comparison.columns) == 5
    assert comparison.value("Latest ROIC", "MISSING") is None


def test_503_security_cache_reuses_histories(
    fmp_source: WorkbenchSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    companies = load_persisted_companies(fmp_source, "fmp")
    prints = cache.fingerprint(companies)
    calls = 0
    original = cache.load_canonical_history

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(cache, "load_canonical_history", counted)
    results = cache.cached_screening(prints, provider="fmp", db_path=fmp_source.db_path)
    assert len(results) == calls == 503
    assert (
        cache.cached_screening(prints, provider="fmp", db_path=fmp_source.db_path)
        == results
    )
    assert calls == 503
    standings = cache.cached_coverage_standings(
        prints, fmp_source.db_path, provider="fmp"
    )
    assert len(standings) == 503
    assert calls == 503
    assert all(standing.dataset_states for standing in standings)
    # Refresh-state changes invalidate that security, not every annual history.
    store = fmp_source.store
    assert isinstance(store, SqliteStore)
    target = next(c for c in companies if c.ticker == "GOOG")
    assert target.security_id is not None
    store.update_security_refresh_state(
        target.security_id,
        "quarterly_analyst_estimates",
        status="UNSUPPORTED",
        updated_at="2026-06-02T00:00:00+00:00",
        last_error="No entitlement",
    )
    new_prints = cache.fingerprint(load_persisted_companies(fmp_source, "fmp"))
    assert new_prints != prints
    assert (
        len(
            cache.cached_screening(
                new_prints, provider="fmp", db_path=fmp_source.db_path
            )
        )
        == 503
    )
    assert calls == 504


@pytest.mark.parametrize(
    "page", ("Overview", "Screener", "Company", "Compare", "Data Quality")
)
def test_full_universe_pages_offline(page: str, fmp_source: WorkbenchSource) -> None:
    app = AppTest.from_file(str(_APP), default_timeout=120)
    app.session_state["provider"] = "fmp"
    app.session_state["page"] = page
    app.session_state["selected_ticker"] = "ADBE"
    app.session_state["quality_ticker"] = "MISSING"
    app.session_state["compare_tickers"] = [
        "ADBE",
        "GOOG",
        "GOOGL",
        "PARTIAL",
        "MISSING",
    ]
    app.run()
    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    assert any("Provider: FMP" in caption.value for caption in app.caption)
    if page == "Overview":
        assert (
            next(
                metric.value
                for metric in app.metric
                if metric.label == "Companies tracked"
            )
            == "503"
        )
    elif page == "Screener":
        assert app.radio(key="screener_view_mode").value == "Standard Screener"
        assert any("503 of 503 companies match" in item.value for item in app.caption)
        assert any("Priority" in table.value.columns for table in app.dataframe)
    elif page == "Company":
        headings = [heading.value for heading in app.subheader]
        assert {"Quarterly evidence", "Latest EOD price", "Market Expectations"} <= set(
            headings
        )
    elif page == "Data Quality":
        assert app.warning
        assert any(len(table.value) == 503 for table in app.dataframe)


def test_screen_cli_explicit_provider(
    fmp_source: WorkbenchSource,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["screen", "--provider", "fmp", "ADBE", "MISSING"]) == 0
    output = capsys.readouterr().out
    assert "Provider: FMP" in output
    assert "ADBE" in output and "MISSING" in output and "FAILED" in output
    assert main(["screen", "--provider", "fmp", "NOT_IN_UNIVERSE"]) == 1
    assert "Not in persisted S&P 500" in capsys.readouterr().err
    assert main(["screen", "ADBE"]) == 0
    assert "Provider: FMP" not in capsys.readouterr().out


@pytest.mark.parametrize("payload", (b"not json", b"{}"))
def test_corrupt_quarterly_evidence_does_not_hide_annual_economics(
    fmp_source: WorkbenchSource,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    company = next(
        c for c in load_persisted_companies(fmp_source, "fmp") if c.ticker == "ADBE"
    )
    expected = company_detail(fmp_source, company)
    quarterly_hash = expected.quarterly_evidence[0]["content_hash"]
    original = fmp_source.raw_store.get
    monkeypatch.setattr(
        fmp_source.raw_store,
        "get",
        lambda content_hash: (
            payload if content_hash == quarterly_hash else original(content_hash)
        ),
    )
    actual = company_detail(fmp_source, company)
    assert actual.screening == expected.screening
    assert actual.owner_economics == expected.owner_economics
    assert actual.evidence_errors
    assert "quarterly_income_statement" in actual.evidence_errors[0]
    assert actual.quarterly_evidence == ()


def test_provider_switch_repairs_company_selection(fmp_source: WorkbenchSource) -> None:
    app = AppTest.from_file(str(_APP), default_timeout=120)
    app.session_state["provider"] = "fmp"
    app.session_state["page"] = "Company"
    app.session_state["selected_ticker"] = "GOOG"
    app.run()
    assert not app.exception and not app.error
    provider = next(
        widget for widget in app.selectbox if widget.label == "Evidence provider"
    )
    provider.set_value("sec").run()
    assert not app.exception and not app.error
    assert app.session_state["selected_ticker"] == "ADBE"
    assert any("Provider: SEC" in caption.value for caption in app.caption)

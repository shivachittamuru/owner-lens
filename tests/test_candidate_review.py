"""Fixture-only candidate reports and opt-in, isolated price evidence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from _fmp_fixtures import fmp_payloads, fmp_statements
from test_valuation import _persist
from test_variant import variant_snapshot

from owner_lens import candidate_review, cli
from owner_lens.candidate_review import (
    CandidateSelection,
    candidate_worksheet,
    format_candidate_report,
    select_candidates,
)
from owner_lens.evidence_ingestion import retrieve_candidate_prices
from owner_lens.fmp import FmpClient
from owner_lens.fmp_adapter import FMP_FIELD_MAP, canonical_history_from_fmp
from owner_lens.persistence import (
    FilesystemRawSnapshotStore,
    FmpCanonicalCoverageRecord,
    FmpCanonicalFactRecord,
    FmpCanonicalHistoryRecord,
    FmpEodPriceRecord,
    FmpEvidenceSnapshotRecord,
    FmpHistoricalPriceRecord,
    SqliteStore,
    StorageConnectionError,
    UniverseConstituentRecord,
    UniverseSnapshotRecord,
    compute_content_hash,
)
from owner_lens.research_context import build_research_context
from owner_lens.screening import (
    DimensionBand,
    ScreeningBucket,
    ScreeningReason,
    SetupType,
)
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.workbench.data import (
    WorkbenchSource,
    company_detail,
    load_persisted_companies,
)

DAY = date(2026, 10, 30)
FETCHED = "2026-11-06T05:00:00+00:00"


def save_payload(
    store: SqliteStore, dataset: str, rows: list, *, fetched: str = FETCHED
) -> int:
    body = json.dumps(rows).encode()
    return store.save_fmp_evidence_snapshot(
        FmpEvidenceSnapshotRecord(
            security_id=1,
            dataset=dataset,
            period_type="annual",
            source_endpoint=dataset,
            request_parameters='{"symbol":"ADBE"}',
            fetched_at=fetched,
            content_hash=compute_content_hash(body),
        ),
        raw_payload=body,
    )[0]


@pytest.fixture
def source(tmp_path: Path) -> WorkbenchSource:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    store = SqliteStore(tmp_path / "pilot.db", raw_store=raw)
    store.initialize()
    payload = b'[{"symbol":"ADBE"}]'
    store.save_universe_snapshot(
        UniverseSnapshotRecord(
            "fmp", FETCHED, "sp500-constituent", compute_content_hash(payload)
        ),
        (UniverseConstituentRecord("ADBE", "Adobe", "0000796343", "Technology"),),
        raw_payload=payload,
        state_symbols=("ADBE",),
        datasets=(),
        created_at=FETCHED,
    )
    data = fmp_payloads()
    for row in data["cash-flow-statement"]:
        row["freeCashFlow"] = row["operatingCashFlow"] + row["capitalExpenditure"]
    ids = {
        statement: save_payload(store, f"annual_{statement}_statement", data[endpoint])
        for statement, endpoint in (
            ("income", "income-statement"),
            ("cash_flow", "cash-flow-statement"),
            ("balance_sheet", "balance-sheet-statement"),
        )
    }
    history = canonical_history_from_fmp(fmp_statements(payloads=data), max_years=5)
    store.save_fmp_canonical_history(
        FmpCanonicalHistoryRecord(
            security_id=1,
            input_hash=compute_content_hash(json.dumps(data).encode()),
            observed_at=FETCHED,
            max_years=5,
            facts=tuple(
                FmpCanonicalFactRecord(
                    fact.metric,
                    fact.value,
                    fact.unit,
                    fact.fiscal_year,
                    fact.period_end.isoformat(),
                    fact.provider_field or "",
                    ids[FMP_FIELD_MAP[series.metric].statement],
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
    save_payload(
        store,
        "candidate_profile",
        [
            {
                "symbol": "ADBE",
                "cik": "0000796343",
                "currency": "USD",
                "exchange": "NASDAQ",
            }
        ],
    )
    save_payload(
        store,
        "candidate_price",
        [
            {"symbol": "ADBE", "date": "2026-09-30", "close": 200.0},
            {"symbol": "ADBE", "date": "2026-10-30", "close": 240.0},
        ],
    )
    with WorkbenchSource(
        store, raw, str(tmp_path / "pilot.db"), str(tmp_path / "raw")
    ) as result:
        yield result


def selection(source: WorkbenchSource) -> CandidateSelection:
    company = load_persisted_companies(source, "fmp")[0]
    return CandidateSelection(
        "COMPOUNDERS", company, company_detail(source, company).screening, "fixture"
    )


def test_offline_arithmetic_sources_and_unchanged_store(
    source: WorkbenchSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline"))
    before = source.store._conn.total_changes
    s = selection(source)
    card = candidate_worksheet(source, s, market_date=DAY)
    assert card["latest_fcf_per_share"] == pytest.approx(9852000000 / 427000000)
    assert card["latest_price_to_fcf"] == pytest.approx(
        240 / card["latest_fcf_per_share"]
    )
    assert card["median_price_to_fcf"] == pytest.approx(240 / (7873000000 / 449700000))
    assert card["quote"]["currency_basis"] == "INFERRED_CURRENT_PROFILE"
    assert card["quote"]["adjustment_basis"] == "UNVERIFIED"
    assert card["valuation_status"] == "NOT_VERIFIED"
    assert card["financial_references"][0]["period_end"] == "2025-11-30"
    assert card["financial_references"][0]["filing_dates"] == ["2026-01-15"] * 2
    assert card["quote"]["source"]["fetched_at"] == FETCHED
    assert source.store._conn.total_changes == before
    assert card["screening"]["priority"] == s.screening.bucket.value
    assert card["screening"]["gate"] == (
        s.screening.gate.value if s.screening.gate else None
    )
    assert "identity [FACT]" in card["copy_research_context"]


@pytest.mark.parametrize(
    "problem", ["missing_date", "foreign_currency", "missing_profile", "revision"]
)
def test_unverified_quote_states_do_not_get_ratios(
    source: WorkbenchSource, problem: str
) -> None:
    store = source.store
    if problem == "missing_date":
        day = date(2026, 10, 29)
    else:
        day = DAY
    if problem == "foreign_currency":
        save_payload(
            store,
            "candidate_profile",
            [{"symbol": "ADBE", "currency": "EUR", "cik": "0000796343"}],
            fetched="2026-11-07T00:00:00+00:00",
        )
    if problem == "missing_profile":
        store._conn.execute(
            "DELETE FROM fmp_evidence_snapshots WHERE dataset='candidate_profile'"
        )
    if problem == "revision":
        save_payload(
            store,
            "candidate_price",
            [{"symbol": "ADBE", "date": "2026-10-30", "close": 241.0}],
            fetched="2026-11-07T00:00:00+00:00",
        )
    card = candidate_worksheet(source, selection(source), market_date=day)
    assert card["latest_price_to_fcf"] is None
    assert card["median_price_to_fcf"] is None
    assert card["warnings"]


@pytest.mark.parametrize(
    "field",
    ["capitalExpenditure", "freeCashFlow", "investmentsInPropertyPlantAndEquipment"],
)
def test_definition_conflict_is_explicit(source: WorkbenchSource, field: str) -> None:
    snap = source.store.get_latest_fmp_evidence_snapshot(
        1, "annual_cash_flow_statement"
    )
    rows = json.loads(source.raw_store.get(snap.content_hash))
    rows[1][field] -= 10000000
    body = json.dumps(rows).encode()
    new_hash = compute_content_hash(body)
    source.raw_store.put(new_hash, body)
    source.store._conn.execute(
        "UPDATE fmp_evidence_snapshots SET content_hash=? WHERE snapshot_id=?",
        (new_hash, snap.snapshot_id),
    )
    if field == "investmentsInPropertyPlantAndEquipment":
        with pytest.raises(ValueError, match="canonical PP&E spending disagrees"):
            candidate_worksheet(source, selection(source), market_date=DAY)
        return
    card = candidate_worksheet(source, selection(source), market_date=DAY)
    assert card["latest_price_to_fcf"] is not None
    assert card["median_price_to_fcf"] is None
    assert any("CONFLICT" in message for message in card["warnings"])
    assert card["financial_references"][1]["provider_fcf_per_share"] is not None


def test_frozen_underwriting_context_is_reused_without_changes(
    source: WorkbenchSource,
) -> None:
    snapshot = variant_snapshot()
    evidence = json.loads(snapshot.evidence_json)
    for captured in evidence["market_expectations"]["snapshots"]:
        captured["source"]["period_type"] = "annual"
        captured["source"]["source_endpoint"] = "analyst-estimates"
    record = _persist(
        source.store, replace(snapshot, evidence_json=json.dumps(evidence))
    )
    before = source.store._conn.total_changes
    s = selection(source)
    card = candidate_worksheet(source, s, market_date=DAY)
    expected = build_research_context(
        company_detail(source, s.company), project_underwriting(source.store, "ADBE")
    )
    assert card["copy_research_context"] == json.loads(expected.json_export)
    assert source.store.list_underwriting("ADBE")[0] == record
    assert source.store._conn.total_changes == before


def test_incomplete_legacy_research_context_is_an_explicit_error(
    source: WorkbenchSource,
) -> None:
    _persist(source.store, variant_snapshot())
    with pytest.raises(
        ValueError, match="Copy Research Context missing required field"
    ):
        candidate_worksheet(source, selection(source), market_date=DAY)


@pytest.mark.parametrize("bad_date", [None, 20261029, "20261029"])
def test_malformed_price_dates_are_explicit(source: WorkbenchSource, bad_date) -> None:
    save_payload(
        source.store,
        "candidate_price",
        [
            {"symbol": "ADBE", "date": DAY.isoformat(), "close": 240.0},
            {"symbol": "ADBE", "date": bad_date, "close": 239.0},
        ],
        fetched="2026-11-07T00:00:00+00:00",
    )
    with pytest.raises((ValueError, TypeError), match="price date must"):
        candidate_worksheet(source, selection(source), market_date=DAY)


def test_future_publication_blocks_ratio(source: WorkbenchSource) -> None:
    save_payload(
        source.store,
        "candidate_price",
        [{"symbol": "ADBE", "date": "2025-12-01", "close": 200.0}],
        fetched="2026-11-07T00:00:00+00:00",
    )
    card = candidate_worksheet(source, selection(source), market_date=date(2025, 12, 1))
    assert not card["financial_references"][0]["filed_before_market_date"]
    assert card["latest_price_to_fcf"] is None


def test_incomparable_sector_and_missing_shares_stay_unresolved(
    source: WorkbenchSource,
) -> None:
    s = selection(source)
    card = candidate_worksheet(
        source,
        replace(s, company=replace(s.company, sector="Real Estate")),
        market_date=DAY,
    )
    assert card["latest_price_to_fcf"] is None
    assert any("SECTOR_INCOMPARABILITY" in warning for warning in card["warnings"])
    source.store._conn.execute(
        "DELETE FROM fmp_canonical_facts WHERE metric='diluted_shares'"
    )
    source.store._conn.execute(
        "UPDATE fmp_metric_coverage SET status='UNSUPPORTED',reason='Fixture missing shares' "
        "WHERE metric='diluted_shares'"
    )
    card = candidate_worksheet(source, s, market_date=DAY)
    assert card["latest_fcf_per_share"] is None
    assert card["latest_price_to_fcf"] is None
    assert card["median_price_to_fcf"] is None


def test_identity_and_hash_failures_are_explicit(source: WorkbenchSource) -> None:
    save_payload(
        source.store,
        "candidate_profile",
        [{"symbol": "ADBE", "currency": "USD", "cik": "0000000001"}],
        fetched="2026-11-07T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="CIK mismatch"):
        candidate_worksheet(source, selection(source), market_date=DAY)


def test_cohort_counts_order_gates_and_no_duplicate_fillers(
    source: WorkbenchSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = selection(source)
    owner = company_detail(source, base.company).owner_economics[-1]
    improving_rows = tuple(
        replace(
            owner,
            fiscal_year=2020 + i,
            free_cash_flow=100 + i,
            fcf_per_share=1.0 + i,
            revenue=replace(owner.revenue, value=100 + i),
        )
        for i in range(5)
    )
    companies = []
    results = {}
    for cohort, count in (("N", 4), ("F", 4), ("C", 8), ("I", 8)):
        for i in range(count):
            ticker = f"{cohort}{i}"
            company = replace(base.company, ticker=ticker, sector="Technology")
            result = replace(
                base.screening, ticker=ticker, gate=None, limiting_reasons=()
            )
            if cohort == "N":
                if i == 0:
                    company = replace(company, sector="Real Estate")
                elif i == 1:
                    company = replace(company, sector="Financial Services")
                else:
                    result = replace(
                        result,
                        limiting_reasons=(
                            ScreeningReason.QUESTIONABLE_CAPITAL_ALLOCATION
                            if i == 2
                            else ScreeningReason.RETURNS_BELOW_QUALITY_THRESHOLD,
                        ),
                    )
            elif cohort == "F":
                result = replace(result, gate=ScreeningReason.PERSISTENT_CASH_BURN)
            elif cohort == "C":
                result = replace(
                    result,
                    bucket=ScreeningBucket.HIGH_PRIORITY,
                    setup_type=SetupType.COMPOUNDER,
                    dimensions={
                        k: replace(v, band=DimensionBand.STRONG)
                        for k, v in result.dimensions.items()
                    },
                )
            else:
                result = replace(result, bucket=ScreeningBucket.WATCH)
            companies.append(company)
            results[ticker] = result
    monkeypatch.setattr(
        candidate_review,
        "load_persisted_companies",
        lambda *a: tuple(reversed(companies)),
    )
    monkeypatch.setattr(
        candidate_review,
        "load_canonical_history",
        lambda source, company: company.ticker,
    )
    monkeypatch.setattr(
        candidate_review,
        "assemble_screening_evidence",
        lambda ticker: SimpleNamespace(
            ticker=ticker,
            owner_economics=improving_rows,
        ),
    )
    monkeypatch.setattr(candidate_review, "screen_company", lambda e: results[e.ticker])
    selected, errors = select_candidates(source)
    assert not errors
    assert len(selected) == len({s.company.ticker for s in selected}) == 24
    assert {
        cohort: sum(s.cohort == cohort for s in selected)
        for cohort in candidate_review.COHORT_SIZES
    } == candidate_review.COHORT_SIZES
    assert all(s.screening is results[s.company.ticker] for s in selected)
    assert [s.company.ticker for s in selected if s.cohort == "COMPOUNDERS"] == [
        f"C{i}" for i in range(8)
    ]


def test_read_only_cli_and_handoff(
    source: WorkbenchSource, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("no network"))
    assert (
        cli.main(
            [
                "candidate-review",
                "report",
                "--db",
                source.db_path,
                "--raw-data",
                source.raw_data_path,
                "--date",
                DAY.isoformat(),
                "--format",
                "json",
            ]
        )
        == 1
    )  # The fixture universe cannot fill the pilot; it stays explicit.
    report = json.loads(capsys.readouterr().out)
    assert report["selection_errors"]
    text = format_candidate_report(report)
    assert "FRAGILE_CONTROLS" in text and "Do not approve" in text
    assert "Evidence source index" in text and "SHA-256" in text
    with pytest.raises(SystemExit):
        cli.main(
            [
                "candidate-review",
                "retrieve-prices",
                "--db",
                source.db_path,
                "--raw-data",
                source.raw_data_path,
                "--date",
                DAY.isoformat(),
            ]
        )


def test_read_only_store_rejects_writes_and_missing_paths(
    source: WorkbenchSource, tmp_path: Path
) -> None:
    store = SqliteStore(Path(source.db_path), read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store._conn.execute("DELETE FROM securities")
    finally:
        store.close()
    with pytest.raises(StorageConnectionError, match="Cannot open"):
        SqliteStore(tmp_path / "missing.db", read_only=True)
    assert not (tmp_path / "missing.db").exists()


def test_bounded_acquisition_only_raw_evidence(source: WorkbenchSource) -> None:
    seen = []
    latest_id = save_payload(
        source.store,
        "eod_price",
        [{"symbol": "ADBE", "date": DAY.isoformat(), "price": 240.0}],
    )
    source.store.save_fmp_eod_price(
        FmpEodPriceRecord(latest_id, 1, DAY.isoformat(), 240.0, "price")
    )
    historical_id = save_payload(
        source.store,
        "historical_price",
        [{"symbol": "ADBE", "date": "2026-09-30", "close": 200.0}],
    )
    source.store.save_fmp_historical_prices(
        (FmpHistoricalPriceRecord(historical_id, 1, "2026-09-30", 200.0, "close"),)
    )
    frozen = _persist(source.store, variant_snapshot())
    historical_before = source.store.list_fmp_historical_prices(1)
    latest_before = tuple(
        tuple(row) for row in source.store._conn.execute("SELECT * FROM fmp_eod_prices")
    )
    facts_before = tuple(
        tuple(row)
        for row in source.store._conn.execute("SELECT * FROM fmp_canonical_facts")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "profile":
            rows = [{"symbol": "ADBE", "cik": "0000796343", "currency": "USD"}]
        elif endpoint == "splits":
            rows = []
        else:
            rows = [{"symbol": "ADBE", "date": DAY.isoformat(), "close": 240.0}]
        return httpx.Response(200, json=rows)

    before = source.store._conn.execute(
        "SELECT COUNT(*) FROM fmp_eod_prices"
    ).fetchone()[0]
    with FmpClient(
        "fixture-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=None,
    ) as client:
        results = retrieve_candidate_prices(
            client=client, store=source.store, symbols=("ADBE",), market_date=DAY
        )
        saved = len(source.store.list_fmp_evidence_snapshots(1, "candidate_price"))
        retrieve_candidate_prices(
            client=client, store=source.store, symbols=("ADBE",), market_date=DAY
        )
        assert (
            len(source.store.list_fmp_evidence_snapshots(1, "candidate_price"))
            == saved + 1
        )
        vintages = source.store.list_fmp_evidence_snapshots(1, "candidate_price")
        assert vintages[0]["content_hash"] == vintages[1]["content_hash"]
    assert results[0]["status"] == "SUCCEEDED"
    assert len(seen) == 6
    assert (
        source.store._conn.execute("SELECT COUNT(*) FROM fmp_eod_prices").fetchone()[0]
        == before
    )
    assert source.store.list_fmp_historical_prices(1) == historical_before
    assert (
        tuple(
            tuple(row)
            for row in source.store._conn.execute("SELECT * FROM fmp_eod_prices")
        )
        == latest_before
    )
    assert (
        tuple(
            tuple(row)
            for row in source.store._conn.execute("SELECT * FROM fmp_canonical_facts")
        )
        == facts_before
    )
    assert source.store.list_underwriting("ADBE")[0] == frozen
    assert source.store.list_fmp_evidence_snapshots(1, "candidate_price")
    with pytest.raises(ValueError, match="1-24"):
        retrieve_candidate_prices(
            client=client, store=source.store, symbols=("ADBE",) * 25, market_date=DAY
        )


def test_acquisition_identity_mismatch_stops_before_prices(
    source: WorkbenchSource,
) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=[{"symbol": "ADBE", "cik": "0000000001"}])

    before = len(source.store.list_fmp_evidence_snapshots(1, "candidate_price"))
    with FmpClient(
        "fixture-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=None,
    ) as client:
        results = retrieve_candidate_prices(
            client=client, store=source.store, symbols=("ADBE",), market_date=DAY
        )
    assert results[0]["status"] == "FAILED"
    assert "CIK mismatch" in results[0]["reason"]
    assert len(seen) == 1
    assert len(source.store.list_fmp_evidence_snapshots(1, "candidate_price")) == before

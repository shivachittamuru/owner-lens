"""ADBE underwriting snapshots are typed, offline, immutable, and reproducible."""

from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from _fmp_fixtures import fmp_payloads, fmp_statements

from owner_lens.cli import main
from owner_lens.fmp_adapter import FMP_FIELD_MAP, canonical_history_from_fmp
from owner_lens.persistence import (
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
from owner_lens.underwriting import (
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    create_underwriting,
    load_manual_json,
    parse_manual_input,
)
from owner_lens.workbench.data import WorkbenchSource, open_source

_OBSERVED = "2026-06-01T12:00:00+00:00"
_NOW = datetime(2026, 6, 2, 12, tzinfo=UTC)
_SAMPLE = (
    Path(__file__).parents[1] / "docs" / "examples" / "adbe_underwriting.sample.json"
)


@pytest.fixture
def manual_data() -> dict[str, Any]:
    data = json.loads(_SAMPLE.read_text())
    data["as_of_date"] = "2026-06-02"
    data["forward_assumptions"][0]["value"] = 0.06
    data["forward_assumptions"][0]["confidence"] = "low"
    data["forward_assumptions"][0]["references"] = [
        {"title": "Fixture source", "uri": "fixture://basis"}
    ]
    data["supporting_evidence"] = [
        {
            "category": "FACT",
            "text": "Fixture statement",
            "references": [{"uri": "fixture://fact"}],
        },
        {"category": "EXPECTATION", "text": "Fixture consensus", "references": []},
        {"category": "CALCULATION", "text": "Fixture observed range", "references": []},
    ]
    data["disconfirming_evidence"] = [{"category": "JUDGMENT", "text": "Fixture risk"}]
    data["decision"] = {
        "category": "JUDGMENT",
        "text": "Collect more evidence; no recommendation.",
    }
    return data


def _save_snapshot(
    store: SqliteStore,
    dataset: str,
    payload: bytes,
    *,
    observed: str = _OBSERVED,
    period: str = "annual",
) -> int:
    return store.save_fmp_evidence_snapshot(
        FmpEvidenceSnapshotRecord(
            1,
            dataset,
            period,
            f"/stable/{dataset}",
            json.dumps({"symbol": "ADBE", "period": period}),
            observed,
            compute_content_hash(payload),
            evidence_kind="EXPECTATION" if "estimates" in dataset else "FACT",
        ),
        raw_payload=payload,
    )[0]


def _annual_history(
    store: SqliteStore, *, observed: str = _OBSERVED, revenue_delta: int = 0
) -> int:
    payloads = fmp_payloads()
    payloads["income-statement"][0]["revenue"] += revenue_delta
    ids = {
        statement: _save_snapshot(
            store,
            f"annual_{statement}_statement",
            json.dumps(payloads[endpoint]).encode(),
            observed=observed,
        )
        for statement, endpoint in (
            ("income", "income-statement"),
            ("balance_sheet", "balance-sheet-statement"),
            ("cash_flow", "cash-flow-statement"),
        )
    }
    history = canonical_history_from_fmp(
        fmp_statements(payloads=payloads), max_years=15
    )
    return store.save_fmp_canonical_history(
        FmpCanonicalHistoryRecord(
            1,
            compute_content_hash(json.dumps(payloads).encode()),
            observed,
            15,
            tuple(
                FmpCanonicalFactRecord(
                    series.metric,
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
            tuple(
                FmpCanonicalCoverageRecord(
                    series.metric, series.status.value, series.reason
                )
                for series in history.series
            ),
        )
    )[0]


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    db, raw = tmp_path / "store.sqlite", tmp_path / "raw"
    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(db))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(raw))
    monkeypatch.delenv("OWNER_LENS_FMP_API_KEY", raising=False)
    monkeypatch.setattr(
        httpx.Client,
        "send",
        lambda *a, **kw: pytest.fail("Underwriting must stay offline"),
    )
    with open_source() as source:
        store = source.store
        assert isinstance(store, SqliteStore)
        payload = b'[{"symbol":"ADBE"}]'
        store.save_universe_snapshot(
            UniverseSnapshotRecord(
                "fmp",
                _OBSERVED,
                "/stable/sp500-constituent",
                compute_content_hash(payload),
            ),
            (UniverseConstituentRecord("ADBE", "Adobe", "0000796343"),),
            raw_payload=payload,
            state_symbols=("ADBE",),
            datasets=(),
            created_at=_OBSERVED,
        )
        _annual_history(store)
        price_id = _save_snapshot(
            store, "eod_price", b'[{"date":"2026-06-01","price":123.45}]', period="eod"
        )
        store.save_fmp_eod_price(
            FmpEodPriceRecord(price_id, 1, "2026-06-01", 123.45, "price")
        )
        for period in ("annual", "quarterly"):
            estimate_id = _save_snapshot(
                store,
                f"{period}_analyst_estimates",
                b'[{"date":"2027-11-30","epsAvg":2.5}]',
                period=period,
            )
            store.save_fmp_estimates(
                (
                    FmpEstimateRecord(
                        estimate_id,
                        "2027-11-30",
                        100,
                        120,
                        140,
                        8,
                        2,
                        2.5,
                        3,
                        7,
                    ),
                )
            )
        yield source


def test_adbe_facts_semantics_provenance_and_exact_round_trip(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    record = create_underwriting(
        source, "adbe", parse_manual_input(manual_data), now=_NOW
    )
    assert record.version == 1 and record.ticker == "ADBE" and record.security_id == 1
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    assert snapshot.to_json() == record.snapshot_json
    assert snapshot.latest_fiscal_year == 2025
    starting = {item.name: item for item in snapshot.starting_financial_state}
    assert len(starting) == 8
    assert starting["revenue"].value == 23769_000_000
    assert starting["fcf"].value == (10031 - 179) * 1_000_000
    assert starting["fcf_per_share"].value == starting["fcf"].value / 427_000_000
    assert all(item.category is SemanticType.FACT for item in starting.values())
    assert starting["fcf"].basis is SemanticType.CALCULATION
    assert starting["revenue"].basis is SemanticType.FACT
    assert snapshot.manual.forward_assumptions[0].category is SemanticType.ASSUMPTION
    assert snapshot.manual.forward_assumptions[0].value == 0.06
    assert all(
        item.category is SemanticType.JUDGMENT
        for item in snapshot.manual.business_drivers
    )
    assert snapshot.manual.thesis.category is SemanticType.JUDGMENT
    assert snapshot.manual.decision.category is SemanticType.JUDGMENT
    assert {item.category for item in snapshot.manual.supporting_evidence} == {
        SemanticType.FACT,
        SemanticType.EXPECTATION,
        SemanticType.CALCULATION,
    }
    assert all(
        rate.category is SemanticType.CALCULATION
        for rate in snapshot.historical_base_rates
    )
    revenue_growth = snapshot.historical_base_rates[0]
    assert revenue_growth.latest == 23769 / 21505 - 1
    copied = json.loads(snapshot.evidence_json)
    assert copied["eod_price"]["value"]["market_date"] == "2026-06-01"
    assert copied["eod_price"]["value"]["close"] == 123.45
    assert len(copied["annual_sources"]) == 3
    source_ids = {item["snapshot_id"] for item in copied["annual_sources"]}
    assert {
        item["snapshot_id"] for item in copied["canonical_history"]["facts"]
    } <= source_ids
    for item in copied["market_expectations"]["snapshots"]:
        assert item["source"]["fetched_at"] == _OBSERVED
        assert all(
            row["snapshot_id"] == item["source"]["snapshot_id"] for row in item["rows"]
        )
        assert item["rows"][0]["revenue_low"] == 100
        assert item["rows"][0]["eps_average"] == 2.5
        assert item["rows"][0]["eps_analyst_count"] == 7
    assert snapshot.manual.forward_assumptions[0].references[0].uri == "fixture://basis"
    source.store.close()
    with open_source() as reopened:
        assert reopened.store.list_underwriting("ADBE")[0] == record


def test_revised_assumptions_and_new_evidence_do_not_change_old_records(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    store = source.store
    first = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    new_history_id = _annual_history(
        store, observed="2026-06-03T12:00:00+00:00", revenue_delta=1_000_000
    )
    new_estimate_id = _save_snapshot(
        store, "annual_analyst_estimates", b"[]", observed="2026-06-03T12:00:00+00:00"
    )
    store.save_fmp_estimates(
        (FmpEstimateRecord(new_estimate_id, "2027-11-30", revenue_average=999),)
    )
    manual_data["forward_assumptions"][0]["value"] = 0.09
    manual_data["as_of_date"] = "2026-06-04"
    revised = create_underwriting(
        source,
        "ADBE",
        parse_manual_input(manual_data),
        now=datetime(2026, 6, 4, 12, tzinfo=UTC),
    )
    assert revised.version == 2 and revised.underwriting_id != first.underwriting_id
    assert store.list_underwriting("ADBE")[0] == first
    assert (
        UnderwritingSnapshot.from_json(first.snapshot_json).to_json()
        == first.snapshot_json
    )
    new_snapshot = UnderwritingSnapshot.from_json(revised.snapshot_json)
    assert new_snapshot.manual.forward_assumptions[0].value == 0.09
    assert (
        json.loads(new_snapshot.evidence_json)["canonical_history"]["history_id"]
        == new_history_id
    )
    assert new_snapshot.starting_financial_state[0].value == 23770_000_000
    # A later-created record with an earlier evidence as-of never reads future snapshots.
    manual_data["as_of_date"] = "2026-06-02"
    retrospective = create_underwriting(
        source,
        "ADBE",
        parse_manual_input(manual_data),
        now=datetime(2026, 6, 4, 12, tzinfo=UTC),
    )
    assert retrospective.created_at != first.created_at
    old_evidence = json.loads(
        UnderwritingSnapshot.from_json(retrospective.snapshot_json).evidence_json
    )
    first_evidence = json.loads(
        UnderwritingSnapshot.from_json(first.snapshot_json).evidence_json
    )
    assert old_evidence.pop("cutoff") == "2026-06-02T23:59:59.999999+00:00"
    first_evidence.pop("cutoff")
    assert old_evidence == first_evidence


@pytest.mark.parametrize(
    "operation",
    (
        "UPDATE underwriting_records SET snapshot_json='{}'",
        "DELETE FROM underwriting_records",
        "INSERT OR REPLACE INTO underwriting_records SELECT * FROM underwriting_records",
    ),
)
def test_database_rejects_mutation(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
    operation: str,
) -> None:
    first = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        source.store._conn.execute(operation)
    source.store._conn.rollback()
    assert source.store.list_underwriting("ADBE") == (first,)


def test_missing_optional_fields_and_missing_expectations_stay_explicit(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    for key in (
        "as_of_date",
        "decision",
        "supporting_evidence",
        "disconfirming_evidence",
    ):
        manual_data.pop(key, None)
    for item in manual_data["forward_assumptions"]:
        item.pop("confidence", None)
        item.pop("references", None)
    source.store._conn.execute("DELETE FROM fmp_estimates")
    source.store._conn.execute("DELETE FROM fmp_eod_prices")
    source.store._conn.commit()
    record = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    assert snapshot.manual.decision is None
    assert snapshot.manual.supporting_evidence == ()
    copied = json.loads(snapshot.evidence_json)
    assert (
        copied["eod_price"]["value"] is None and copied["eod_price"]["missing_reason"]
    )
    assert all(
        item["rows"] == [] for item in copied["market_expectations"]["snapshots"]
    )
    assert snapshot.manual.forward_assumptions[0].confidence is None


@pytest.mark.parametrize(
    "change",
    (
        {"starting_financial_state": {"revenue": 1}},
        {"market_expectations": {"eps_average": 1}},
        {"probabilities": {"base": 1}},
    ),
)
def test_input_cannot_override_evidence_or_add_out_of_scope_fields(
    manual_data: dict[str, Any],
    change: dict[str, Any],
) -> None:
    with pytest.raises(UnderwritingError, match="unknown fields"):
        parse_manual_input({**manual_data, **change})


@pytest.mark.parametrize(
    "field", ("business_drivers", "forward_assumptions", "decision")
)
def test_semantic_substitution_is_rejected(
    manual_data: dict[str, Any], field: str
) -> None:
    if field == "decision":
        manual_data[field]["category"] = "FACT"
    else:
        manual_data[field][0]["category"] = "EXPECTATION"
    with pytest.raises(UnderwritingError):
        parse_manual_input(manual_data)


@pytest.mark.parametrize("value", (None, True, float("nan"), float("inf"), {}, "5%"))
def test_invalid_assumptions_rejected(manual_data: dict[str, Any], value: Any) -> None:
    manual_data["forward_assumptions"][0]["value"] = value
    with pytest.raises(UnderwritingError):
        parse_manual_input(manual_data)


def test_driver_count_duplicate_assumptions_and_dates(
    manual_data: dict[str, Any],
) -> None:
    invalid = copy.deepcopy(manual_data)
    invalid["business_drivers"] = invalid["business_drivers"][:2]
    with pytest.raises(UnderwritingError, match="3 to 5"):
        parse_manual_input(invalid)
    invalid = copy.deepcopy(manual_data)
    invalid["forward_assumptions"].append(invalid["forward_assumptions"][0])
    with pytest.raises(UnderwritingError, match="duplicate"):
        parse_manual_input(invalid)
    manual_data["as_of_date"] = "not a date"
    with pytest.raises(UnderwritingError, match="YYYY-MM-DD"):
        parse_manual_input(manual_data)


def test_future_asof_missing_history_and_unknown_security_fail_explicitly(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    with pytest.raises(UnderwritingError, match="identity"):
        create_underwriting(
            source, "UNKNOWN", parse_manual_input(manual_data), now=_NOW
        )
    manual_data["as_of_date"] = "2026-06-03"
    with pytest.raises(UnderwritingError, match="future"):
        create_underwriting(source, "ADBE", parse_manual_input(manual_data), now=_NOW)
    manual_data["as_of_date"] = "2026-05-01"
    with pytest.raises(UnderwritingError, match="observed"):
        create_underwriting(source, "ADBE", parse_manual_input(manual_data), now=_NOW)
    assert source.store.list_underwriting("ADBE") == ()


def test_atomic_versions_from_multiple_connections(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    first = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )

    def append(_: int) -> int:
        with SqliteStore(Path(source.db_path)) as store:
            return store.save_underwriting(
                security_id=1,
                ticker="ADBE",
                created_at=_NOW.isoformat(),
                as_of_date=first.as_of_date,
                snapshot_json=first.snapshot_json,
            ).version

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sorted(executor.map(append, range(4))) == [2, 3, 4, 5]
    assert len(source.store.list_underwriting("ADBE")) == 5


def test_additive_v3_migration_preserves_evidence(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    store = source.store
    counts_before = store._conn.execute(
        "SELECT COUNT(*) FROM fmp_canonical_facts"
    ).fetchone()[0]
    store._conn.execute("DROP TABLE underwriting_records")
    store._conn.execute("UPDATE schema_meta SET value='3' WHERE key='schema_version'")
    store._conn.commit()
    store.initialize()
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "10"
    )
    assert (
        store._conn.execute("SELECT COUNT(*) FROM fmp_canonical_facts").fetchone()[0]
        == counts_before
    )
    assert (
        create_underwriting(
            source, "ADBE", parse_manual_input(manual_data), now=_NOW
        ).version
        == 1
    )


def test_cli_create_show_history_and_revision_are_offline(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_file = tmp_path / "ADBE.json"
    input_file.write_text(json.dumps(manual_data), encoding="utf-8-sig")
    assert main(["underwriting", "create", "ADBE", "--file", str(input_file)]) == 0
    assert "v1" in capsys.readouterr().out
    assert main(["underwriting", "show", "ADBE"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert (
        first["snapshot"]["manual"]["forward_assumptions"][0]["category"]
        == "ASSUMPTION"
    )
    assert main(["underwriting", "create", "ADBE", "--file", str(input_file)]) == 0
    capsys.readouterr()
    assert main(["underwriting", "history", "ADBE"]) == 0
    assert [row["version"] for row in json.loads(capsys.readouterr().out)] == [1, 2]
    assert main(["underwriting", "show", "ADBE", "--version", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert main(["underwriting", "show", "ADBE", "--version", "999"]) == 1
    assert "not found" in capsys.readouterr().err
    assert main(["underwriting", "show", "UNKNOWN"]) == 1
    assert "No underwriting" in capsys.readouterr().err
    input_file.write_text('{"starting_financial_state":{}}')
    assert main(["underwriting", "create", "ADBE", "--file", str(input_file)]) == 1
    assert "unknown fields" in capsys.readouterr().err


def test_duplicate_json_keys_cannot_silently_replace_assumptions() -> None:
    with pytest.raises(UnderwritingError, match="Duplicate JSON field"):
        load_manual_json('{"forward_assumptions": [], "forward_assumptions": [1]}')


def test_market_date_and_retrieval_cutoffs_and_latest_empty_estimates(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    store = source.store
    later_price_id = _save_snapshot(
        store,
        "eod_price",
        b'[{"date":"2026-06-02","price":999}]',
        observed="2026-06-03T00:00:00+00:00",
        period="eod",
    )
    store.save_fmp_eod_price(
        FmpEodPriceRecord(later_price_id, 1, "2026-06-02", 999, "price")
    )
    future_price_id = _save_snapshot(
        store,
        "eod_price",
        b'[{"date":"2026-06-04","price":888}]',
        observed=_OBSERVED,
        period="eod",
    )
    store.save_fmp_eod_price(
        FmpEodPriceRecord(future_price_id, 1, "2026-06-04", 888, "price")
    )
    empty_id = _save_snapshot(
        store, "annual_analyst_estimates", b"[]", observed="2026-06-02T11:00:00+00:00"
    )
    record = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    copied = json.loads(
        UnderwritingSnapshot.from_json(record.snapshot_json).evidence_json
    )
    assert copied["eod_price"]["value"]["close"] == 123.45
    annual = next(
        item
        for item in copied["market_expectations"]["snapshots"]
        if item["source"]["dataset"] == "annual_analyst_estimates"
    )
    assert annual["source"]["snapshot_id"] == empty_id
    assert annual["rows"] == [] and annual["missing_reason"]


def test_unsupported_metric_is_not_filled_from_an_assumption(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    store = source.store
    original = store.get_fmp_canonical_history(1)
    coverage = tuple(
        replace(item, status="UNSUPPORTED", reason="Fixture tax missing")
        if item.metric == "income_tax_expense"
        else item
        for item in original.coverage
    )
    store.save_fmp_canonical_history(
        replace(
            original,
            history_id=None,
            input_hash=compute_content_hash(b"partial"),
            observed_at="2026-06-02T10:00:00+00:00",
            coverage=coverage,
            facts=tuple(
                fact for fact in original.facts if fact.metric != "income_tax_expense"
            ),
        )
    )
    manual_data["forward_assumptions"].append(
        {
            "name": "tax_rate",
            "value": 0.25,
            "unit": "ratio",
            "category": "ASSUMPTION",
            "rationale": "Fixture future tax assumption",
        }
    )
    record = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    roic = next(
        item for item in snapshot.starting_financial_state if item.name == "roic"
    )
    assert roic.value is None and "tax" in roic.missing_reason.lower()
    assert snapshot.manual.forward_assumptions[-1].value == 0.25
    assert next(
        rate for rate in snapshot.historical_base_rates if rate.name == "roic"
    ).missing_reason


def test_same_payload_creates_new_version_and_security_identity_survives_symbol_change(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    first = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    second = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    assert second.version == 2 and second.content_hash == first.content_hash
    source.store._conn.execute(
        "UPDATE securities SET symbol='ADBE.NEW' WHERE security_id=1"
    )
    source.store._conn.commit()
    revised = create_underwriting(
        source, "ADBE.NEW", parse_manual_input(manual_data), now=_NOW
    )
    assert revised.version == 3 and revised.security_id == first.security_id
    assert source.store.list_underwriting("ADBE.NEW")[0] == first
    assert source.store.list_underwriting("ADBE")[0].ticker == "ADBE"


def test_reload_never_recomputes_after_new_evidence_or_missing_raw_files(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    monkeypatch.setattr(
        source.raw_store,
        "get",
        lambda *args: pytest.fail("Reload must not read raw evidence"),
    )
    reloaded = source.store.list_underwriting("ADBE")[0]
    assert reloaded == first
    assert (
        UnderwritingSnapshot.from_json(reloaded.snapshot_json).to_json()
        == first.snapshot_json
    )


@pytest.mark.parametrize(
    "dataset", ("annual_income_statement", "eod_price", "annual_analyst_estimates")
)
def test_persisted_source_category_substitution_fails_explicitly(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
    dataset: str,
) -> None:
    category = "FACT" if "estimates" in dataset else "EXPECTATION"
    source.store._conn.execute(
        "UPDATE fmp_evidence_snapshots SET evidence_kind=? WHERE dataset=?",
        (category, dataset),
    )
    source.store._conn.commit()
    with pytest.raises(UnderwritingError, match="classified|provenance"):
        create_underwriting(source, "ADBE", parse_manual_input(manual_data), now=_NOW)
    assert source.store.list_underwriting("ADBE") == ()


def test_no_estimate_snapshots_does_not_fabricate_expectations(
    source: WorkbenchSource,
    manual_data: dict[str, Any],
) -> None:
    source.store._conn.execute("DELETE FROM fmp_estimates")
    source.store._conn.execute(
        "DELETE FROM fmp_evidence_snapshots WHERE dataset LIKE '%estimates'"
    )
    source.store._conn.commit()
    record = create_underwriting(
        source, "ADBE", parse_manual_input(manual_data), now=_NOW
    )
    expectations = json.loads(
        UnderwritingSnapshot.from_json(record.snapshot_json).evidence_json
    )["market_expectations"]
    assert expectations["category"] == "EXPECTATION"
    assert expectations["snapshots"] == [] and expectations["missing_reason"]


def test_cli_invalid_json_and_missing_input_file_fail_without_creating(
    source: WorkbenchSource,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file = tmp_path / "invalid.json"
    file.write_text("not JSON")
    assert main(["underwriting", "create", "ADBE", "--file", str(file)]) == 1
    assert "Error:" in capsys.readouterr().err
    assert (
        main(
            ["underwriting", "create", "ADBE", "--file", str(tmp_path / "missing.json")]
        )
        == 1
    )
    assert "Error:" in capsys.readouterr().err
    assert source.store.list_underwriting("ADBE") == ()

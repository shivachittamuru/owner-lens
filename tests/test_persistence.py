"""Deterministic tests for the OwnerLens Slice 4A persistence layer.

These tests persist the controlled ADBE/V/COST fixtures through the storage
boundary and read them back, covering schema/versioning, round-trip fidelity,
provenance, coverage semantics, idempotency, historical snapshots, cross-company
retrieval, and failure semantics. They use a temporary SQLite file per test and
never touch the network.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens import (
    CompanyIdentity,
    ConceptNotFoundError,
    FilesystemRawSnapshotStore,
    PersistenceError,
    SchemaVersionError,
    SqliteStore,
    StorageConnectionError,
    StorageReadError,
    StorageWriteError,
    capital_allocation_from_facts,
    capital_efficiency_from_facts,
    company_coverage,
    compounding_views_from_facts,
    economic_value_from_facts,
    economic_value_summary_from_facts,
    owner_economics_from_facts,
)
from owner_lens.persistence import (
    DerivedMetricRecord,
    SourceSnapshotRecord,
    analysis_result_records,
    company_record,
    compute_content_hash,
    coverage_result_records,
    derived_metric_records,
    reported_fact_records,
)

_CIKS = {"ADBE": "0000796343", "V": "0001403161", "COST": "0000909832"}
_NAMES = {"ADBE": "ADOBE INC.", "V": "VISA INC.", "COST": "COSTCO WHOLESALE CORP /NEW"}
_FACTS = {"ADBE": adbe_facts, "V": visa_facts, "COST": costco_facts}
_COMPUTED_AT = "2026-09-04T00:00:00"


def _payload(facts: dict[str, Any]) -> bytes:
    return json.dumps(facts, sort_keys=True).encode()


def _snapshot(ticker: str, facts: dict[str, Any]) -> SourceSnapshotRecord:
    cik = _CIKS[ticker]
    return SourceSnapshotRecord(
        cik=cik,
        source_provider="sec",
        source_type="company_facts",
        fetched_at="2026-09-04T00:00:00",
        source_uri=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        content_hash=compute_content_hash(_payload(facts)),
    )


def _persist(store: SqliteStore, ticker: str) -> SourceSnapshotRecord:
    """Compute the full pipeline for one fixture and persist every layer."""
    facts = _FACTS[ticker]()
    cik = _CIKS[ticker]
    identity = CompanyIdentity(ticker=ticker, company_name=_NAMES[ticker], cik=cik)

    owner_rows = owner_economics_from_facts(facts, ticker=ticker)
    capital_rows = capital_efficiency_from_facts(facts, ticker=ticker)
    snapshots = economic_value_from_facts(facts, ticker=ticker)
    compounding = compounding_views_from_facts(facts, ticker=ticker)
    capital_alloc = capital_allocation_from_facts(facts, ticker=ticker)
    summary = economic_value_summary_from_facts(facts, ticker=ticker)
    coverage = company_coverage(facts, ticker=ticker)

    snapshot = _snapshot(ticker, facts)
    store.save_company(company_record(identity))
    store.save_source_snapshot(snapshot, raw_payload=_payload(facts))
    store.save_reported_facts(
        reported_fact_records(cik, owner_rows, capital_rows), snapshot=snapshot
    )
    store.save_derived_metrics(
        derived_metric_records(cik, owner_rows, capital_rows, computed_at=_COMPUTED_AT),
        snapshot=snapshot,
    )
    for result in analysis_result_records(
        cik,
        annual_snapshots=snapshots,
        compounding_views=compounding,
        capital_allocation_rows=capital_alloc,
        summary=summary,
        computed_at=_COMPUTED_AT,
    ):
        store.save_analysis_result(result, snapshot=snapshot)
    store.save_coverage(coverage_result_records(cik, coverage), snapshot=snapshot)
    return snapshot


def _fresh_store(tmp_path: Path, name: str = "owner_lens.db") -> SqliteStore:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    store = SqliteStore(tmp_path / name, raw_store=raw)
    store.initialize()
    return store


# -- Slice 4B additive store support ----------------------------------------


def test_source_snapshot_exists_and_matches_versions(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    snapshot = _persist(store, "ADBE")
    cik = snapshot.cik
    assert store.source_snapshot_exists(cik, snapshot.content_hash)
    assert not store.source_snapshot_exists(cik, "deadbeef")
    assert not store.source_snapshot_exists("0000000000", snapshot.content_hash)
    assert store.snapshot_matches_versions(
        cik,
        snapshot.content_hash,
        calculation_version="1.0",
        analysis_rule_version="1.0",
    )
    assert not store.snapshot_matches_versions(
        cik,
        snapshot.content_hash,
        calculation_version="2.0",
        analysis_rule_version="1.0",
    )


def test_transaction_rolls_back_structured_writes(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    facts = adbe_facts()
    cik = _CIKS["ADBE"]
    identity = CompanyIdentity(ticker="ADBE", company_name=_NAMES["ADBE"], cik=cik)
    snapshot = _snapshot("ADBE", facts)
    store.save_company(company_record(identity))
    store.save_source_snapshot(snapshot, raw_payload=_payload(facts))
    fact_records = reported_fact_records(
        cik,
        owner_economics_from_facts(facts, ticker="ADBE"),
        capital_efficiency_from_facts(facts, ticker="ADBE"),
    )

    with pytest.raises(StorageWriteError), store.transaction():
        store.save_reported_facts(fact_records, snapshot=snapshot)
        raise StorageWriteError("boom")

    # The committed snapshot remains; the structured write was rolled back.
    assert store.source_snapshot_exists(cik, snapshot.content_hash)
    assert store.get_fact_provenance(cik, "revenue", 2025) is None


def test_set_snapshot_processing_status_updates_row(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    snapshot = _persist(store, "ADBE")
    store.set_snapshot_processing_status(snapshot.cik, snapshot.content_hash, "partial")
    stored = store.get_source_snapshot(snapshot.cik, snapshot.content_hash)
    assert stored is not None
    assert stored.processing_status == "partial"


# -- Raw snapshot store layout ----------------------------------------------


def test_filesystem_raw_store_uses_cik_subdir(tmp_path: Path) -> None:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    payload = json.dumps({"cik": 796343, "facts": {}}, sort_keys=True).encode()
    digest = compute_content_hash(payload)
    ref = Path(raw.put(digest, payload))
    assert ref.parent.name == "0000796343"  # CIK-grouped, not ticker
    assert ref.name == f"{digest}.json"
    # a fresh store resolves by content hash alone (no payload in hand)
    fresh = FilesystemRawSnapshotStore(tmp_path / "raw")
    assert fresh.exists(digest) is True
    assert fresh.get(digest) == payload
    # identical content is idempotent — no second file
    raw.put(digest, payload)
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1


# -- Schema (T016) ----------------------------------------------------------


def test_initialize_records_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "s.db"
    store = SqliteStore(db_path)
    store.initialize()
    store.close()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 1


def test_repeat_initialize_is_a_no_op(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    store.initialize()  # second time must not error or wipe data
    assert store.get_company(_CIKS["ADBE"]) is not None
    store.close()


def test_incompatible_schema_version_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "s.db"
    store = SqliteStore(db_path)
    store.initialize()
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
        conn.commit()
    reopened = SqliteStore(db_path)
    with pytest.raises(SchemaVersionError):
        reopened.initialize()


# -- Round trip and queries (T017, T018) ------------------------------------


def test_company_round_trips(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    company = store.get_company(_CIKS["ADBE"])
    assert company is not None
    assert company.ticker == "ADBE"
    assert company.company_name == "ADOBE INC."
    store.close()


def test_metric_history_matches_in_memory(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    expected = {
        row.fiscal_year: row.fcf_per_share
        for row in owner_economics_from_facts(adbe_facts(), ticker="ADBE")
        if row.fcf_per_share is not None
    }
    history = store.get_metric_history(_CIKS["ADBE"], "fcf_per_share", limit=5)
    assert [record.fiscal_year for record in history] == sorted(expected)
    for record in history:
        assert record.value_real == pytest.approx(expected[record.fiscal_year])
        assert record.unit == "per_share"
    store.close()


def test_latest_summary_preserves_ordered_drivers(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    summary = economic_value_summary_from_facts(adbe_facts(), ticker="ADBE")
    expected_codes = [
        driver.value
        for group in (
            summary.key_positive_drivers,
            summary.key_watch_drivers,
            summary.key_negative_drivers,
        )
        for driver in group
    ]
    stored = store.get_latest_summary(_CIKS["ADBE"])
    assert stored is not None
    assert stored.classification == summary.overall_economic_value_classification.value
    assert [driver.code for driver in stored.drivers] == expected_codes
    assert [driver.position for driver in stored.drivers] == list(
        range(len(expected_codes))
    )
    store.close()


def test_reported_facts_and_derived_metrics_are_separate(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    snapshot = _persist(store, "ADBE")
    provenance = store.get_fact_provenance(_CIKS["ADBE"], "revenue", 2025)
    assert provenance is not None
    assert provenance.value == 23769 * 1_000_000
    roic = store.get_metric_history(_CIKS["ADBE"], "roic")
    assert roic  # derived metric stored apart from the reported facts
    assert all(record.value_real is not None for record in roic)
    assert snapshot.content_hash
    store.close()


# -- Provenance (T021) ------------------------------------------------------


def test_cost_revenue_provenance_is_preserved(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "COST")
    fact = store.get_fact_provenance(_CIKS["COST"], "revenue", 2025)
    assert fact is not None
    assert fact.canonical_metric == "revenue"
    assert fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert fact.canonical_metric != fact.concept
    assert fact.form == "10-K"
    assert fact.filed == "2026-01-15"
    assert fact.accession == "RevenueFromContractWithCustomerExcludingAssessedTax-2025"
    store.close()


# -- Coverage semantics (T022) ----------------------------------------------


def test_visa_unsupported_diluted_shares_persists_as_unsupported(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "V")
    coverage = store.get_company_coverage(_CIKS["V"])
    inputs = {c.subject: c.state for c in coverage if c.subject_kind == "input"}
    assert inputs["diluted_shares"] == "UNSUPPORTED"
    store.close()


def test_visa_insufficient_layer_is_preserved(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "V")
    coverage = store.get_company_coverage(_CIKS["V"])
    layer_states = {c.state for c in coverage if c.subject_kind == "layer"}
    assert "INSUFFICIENT_DATA" in layer_states
    store.close()


def test_reported_zero_stays_zero_and_is_not_absence(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    zero_fact = store.get_fact_provenance(_CIKS["ADBE"], "current_debt", 2023)
    assert zero_fact is not None
    assert zero_fact.value == 0  # a real reported zero, not a missing row
    absent = store.get_fact_provenance(_CIKS["ADBE"], "current_debt", 1999)
    assert absent is None  # absence is a missing row, distinct from zero
    store.close()


def test_no_coverage_state_is_null(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "V")
    coverage = store.get_company_coverage(_CIKS["V"])
    assert coverage
    assert all(c.state for c in coverage)
    store.close()


# -- Idempotency and history (T024, T025, T026) -----------------------------


def _count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_repeated_persistence_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idem.db"
    store = _fresh_store(tmp_path, "idem.db")
    _persist(store, "ADBE")
    counts = {
        table: _count(db_path, table)
        for table in (
            "companies",
            "source_snapshots",
            "reported_facts",
            "derived_metrics",
            "analysis_results",
            "analysis_drivers",
            "coverage_results",
        )
    }
    _persist(store, "ADBE")  # identical repeat
    for table, before in counts.items():
        assert _count(db_path, table) == before
    store.close()


def test_distinct_snapshots_coexist(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    store = _fresh_store(tmp_path, "hist.db")
    facts = adbe_facts()
    cik = _CIKS["ADBE"]
    identity = CompanyIdentity(ticker="ADBE", company_name="ADOBE INC.", cik=cik)
    owner_rows = owner_economics_from_facts(facts, ticker="ADBE")
    capital_rows = capital_efficiency_from_facts(facts, ticker="ADBE")
    facts_records = reported_fact_records(cik, owner_rows, capital_rows)

    store.save_company(company_record(identity))
    first = _snapshot("ADBE", facts)
    store.save_source_snapshot(first)
    store.save_reported_facts(facts_records, snapshot=first)

    second = SourceSnapshotRecord(
        cik=cik,
        source_provider="sec",
        source_type="company_facts",
        fetched_at="2027-01-01T00:00:00",
        source_uri=first.source_uri,
        content_hash=compute_content_hash(_payload(facts) + b"\n"),
    )
    store.save_source_snapshot(second)
    store.save_reported_facts(facts_records, snapshot=second)

    assert _count(db_path, "source_snapshots") == 2
    with sqlite3.connect(db_path) as conn:
        per_snapshot = conn.execute(
            "SELECT snapshot_id, COUNT(*) FROM reported_facts GROUP BY snapshot_id"
        ).fetchall()
    assert len(per_snapshot) == 2
    assert all(count > 0 for _, count in per_snapshot)
    store.close()


def test_newer_calculation_version_coexists(tmp_path: Path) -> None:
    db_path = tmp_path / "ver.db"
    store = _fresh_store(tmp_path, "ver.db")
    snapshot = _persist(store, "ADBE")
    newer = DerivedMetricRecord(
        cik=_CIKS["ADBE"],
        metric_name="roic",
        fiscal_year=2025,
        value_real=0.99,
        unit="ratio",
        calculation_version="2.0",
        computed_at=_COMPUTED_AT,
    )
    store.save_derived_metrics([newer], snapshot=snapshot)
    with sqlite3.connect(db_path) as conn:
        versions = conn.execute(
            "SELECT calculation_version FROM derived_metrics "
            "WHERE metric_name = 'roic' AND fiscal_year = 2025"
        ).fetchall()
    assert {"1.0", "2.0"} <= {row[0] for row in versions}
    store.close()


def test_latest_roic_across_companies(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    for ticker in ("ADBE", "V", "COST"):
        _persist(store, ticker)
    latest = store.get_latest_metric_across_companies(
        "roic", [_CIKS["ADBE"], _CIKS["V"], _CIKS["COST"]]
    )
    assert set(latest) == {_CIKS["ADBE"], _CIKS["V"], _CIKS["COST"]}
    for record in latest.values():
        assert record.metric_name == "roic"
        assert record.value_real is not None
        assert record.fiscal_year == 2025
    store.close()


# -- Failure semantics (T027) -----------------------------------------------


def test_connection_failure_raises_storage_connection_error(tmp_path: Path) -> None:
    bad_path = tmp_path / "missing_dir" / "s.db"
    with pytest.raises(StorageConnectionError):
        SqliteStore(bad_path)


def test_dependent_write_before_company_raises_storage_write_error(
    tmp_path: Path,
) -> None:
    store = _fresh_store(tmp_path)
    orphan = _snapshot("ADBE", adbe_facts())
    with pytest.raises(StorageWriteError):
        store.save_source_snapshot(orphan)
    store.close()


def test_read_after_close_raises_storage_read_error(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    _persist(store, "ADBE")
    store.close()
    with pytest.raises(StorageReadError):
        store.get_company(_CIKS["ADBE"])


def test_unknown_company_returns_empty_not_error(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    assert store.get_company("0000000000") is None
    assert store.get_metric_history("0000000000", "roic") == ()
    assert store.get_company_coverage("0000000000") == ()
    assert store.get_latest_summary("0000000000") is None
    store.close()


def test_persistence_errors_are_not_financial_errors(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    orphan = _snapshot("ADBE", adbe_facts())
    with pytest.raises(PersistenceError) as excinfo:
        store.save_source_snapshot(orphan)
    assert not isinstance(excinfo.value, ConceptNotFoundError)
    store.close()

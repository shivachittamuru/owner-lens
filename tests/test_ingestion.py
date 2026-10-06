"""Tests for the persisted single-company ingestion workflow (Slice 4B)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from _fixtures import FIXTURE_FACTS, FakeSecClient, adbe_facts

from owner_lens.ingestion import (
    FailureClass,
    IngestionStatus,
    ProcessingStatus,
    ingest_company,
)
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.persistence.errors import StorageWriteError
from owner_lens.persistence.records import ReportedFactRecord, SourceSnapshotRecord
from owner_lens.sec import CompanyResolutionError

_ADBE = "0000796343"
_V = "0001403161"
_COST = "0000909832"
_STRUCTURED_TABLES = (
    "source_snapshots",
    "reported_facts",
    "derived_metrics",
    "analysis_results",
    "coverage_results",
)


def _store(tmp_path: Path, name: str = "ownerlens.db") -> SqliteStore:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    store = SqliteStore(tmp_path / name, raw_store=raw)
    store.initialize()
    return store


def _row_counts(store: SqliteStore) -> dict[str, int]:
    return {
        table: store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _STRUCTURED_TABLES
    }


# -- User Story 1: full ingestion + fresh-process durability -----------------


def test_full_ingestion_adbe_persists_every_layer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = ingest_company("ADBE", sec_client=FakeSecClient(), store=store)

    assert result.status is IngestionStatus.COMPLETE
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert result.company is not None and result.company.cik == _ADBE
    assert result.persisted_fact_count > 0
    assert result.persisted_metric_count > 0
    assert result.analysis_count > 0
    assert result.unsupported_items == ()

    assert result.source_snapshot is not None
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    assert raw.exists(result.source_snapshot.content_hash)
    assert store.get_company(_ADBE) is not None
    assert store.get_latest_summary(_ADBE) is not None
    assert store.get_company_coverage(_ADBE)
    store.close()


def test_full_ingestion_costco_is_complete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = ingest_company("COST", sec_client=FakeSecClient(), store=store)
    assert result.status is IngestionStatus.COMPLETE
    assert result.processing_status is ProcessingStatus.PROCESSED
    assert store.get_latest_summary(_COST) is not None
    store.close()


def test_persisted_state_survives_fresh_process(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ingest_company("ADBE", sec_client=FakeSecClient(), store=store)
    store.close()

    fresh = SqliteStore(
        tmp_path / "ownerlens.db",
        raw_store=FilesystemRawSnapshotStore(tmp_path / "raw"),
    )
    fresh.initialize()
    assert fresh.get_latest_summary(_ADBE) is not None
    assert fresh.get_company_coverage(_ADBE)
    provenance = fresh.get_fact_provenance(_ADBE, "revenue", 2025)
    assert isinstance(provenance, ReportedFactRecord)
    fresh.close()


# -- User Story 2: honest partial coverage + distinct failure classes --------


def test_partial_ingestion_visa_preserves_unsupported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = ingest_company("V", sec_client=FakeSecClient(), store=store)

    assert result.status is IngestionStatus.PARTIAL
    assert result.processing_status is ProcessingStatus.PARTIAL
    unsupported = {
        item.subject
        for item in result.unsupported_items
        if item.kind is FailureClass.UNSUPPORTED
    }
    assert "diluted_shares" in unsupported
    # Independent layers are still persisted; nothing is fabricated.
    assert store.get_company(_V) is not None
    assert store.get_company_coverage(_V)
    store.close()


def test_insufficient_data_is_soft_not_failed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = ingest_company("V", sec_client=FakeSecClient(), store=store)
    assert result.status is not IngestionStatus.FAILED
    kinds = {item.kind for item in result.unsupported_items}
    assert FailureClass.INSUFFICIENT_DATA in kinds
    store.close()


def test_unsupported_debt_preserves_owner_economics(tmp_path: Path) -> None:
    # MSFT/CRM scenario: current-debt concept absent, but owner-economics inputs
    # are all present. One unsupported branch must not discard the others.
    def adbe_without_current_debt() -> dict[str, Any]:
        facts = adbe_facts()
        del facts["facts"]["us-gaap"]["DebtCurrent"]
        return facts

    store = _store(tmp_path)
    facts_map: dict[str, Callable[[], dict[str, Any]]] = {"ADBE": adbe_without_current_debt}
    result = ingest_company("ADBE", sec_client=FakeSecClient(facts=facts_map), store=store)

    assert result.status is IngestionStatus.PARTIAL
    assert result.processing_status is ProcessingStatus.PARTIAL
    # Trustworthy owner-economics facts and metrics are still persisted.
    assert result.persisted_fact_count > 0
    assert result.persisted_metric_count > 0
    assert result.coverage is not None
    assert result.coverage.layers["owner_economics"].state.value == "AVAILABLE"
    assert result.coverage.layers["capital_efficiency"].state.value == "UNAVAILABLE"
    # The unsupported input is surfaced explicitly, nothing fabricated.
    unsupported = {
        item.subject
        for item in result.unsupported_items
        if item.kind is FailureClass.UNSUPPORTED
    }
    assert "current_debt" in unsupported
    assert store.get_fact_provenance(_ADBE, "revenue", 2025) is not None
    store.close()


def test_unsupported_representation_degrades_without_crash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    empty: dict[str, Callable[[], dict[str, Any]]] = {
        "ADBE": lambda: {
            "cik": 796343,
            "entityName": "ADOBE INC.",
            "facts": {"us-gaap": {}},
        }
    }
    result = ingest_company("ADBE", sec_client=FakeSecClient(facts=empty), store=store)

    # Nothing analytical could be produced, but ingestion does not crash.
    assert result.status is IngestionStatus.PARTIAL
    assert result.processing_status is ProcessingStatus.FETCHED
    assert result.persisted_fact_count == 0
    assert result.unsupported_items
    # Raw evidence is retained even though no analysis could be produced.
    assert result.source_snapshot is not None
    assert store.get_company(_ADBE) is not None
    assert store.source_snapshot_exists(_ADBE, result.source_snapshot.content_hash)
    store.close()


def test_retrieval_failure_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FakeSecClient(resolve_error=CompanyResolutionError("no match"))
    result = ingest_company("ZZZZ", sec_client=client, store=store)

    assert result.status is IngestionStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is FailureClass.RETRIEVAL
    assert result.company is None
    assert store.list_companies() == ()
    store.close()


class _FactWriteFailingStore(SqliteStore):
    """A store whose structured fact write fails, to exercise rollback."""

    def save_reported_facts(
        self, facts: object, *, snapshot: SourceSnapshotRecord
    ) -> None:
        raise StorageWriteError("simulated write failure")


def test_persistence_failure_rolls_back_structured_writes(tmp_path: Path) -> None:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    store = _FactWriteFailingStore(tmp_path / "ownerlens.db", raw_store=raw)
    store.initialize()

    result = ingest_company("ADBE", sec_client=FakeSecClient(), store=store)

    assert result.status is IngestionStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is FailureClass.PERSISTENCE
    # Raw evidence + company + snapshot are retained (raw-first).
    assert result.source_snapshot is not None
    assert store.get_company(_ADBE) is not None
    assert store.source_snapshot_exists(_ADBE, result.source_snapshot.content_hash)
    # Structured analytical writes rolled back.
    assert store.get_latest_summary(_ADBE) is None
    assert store.get_company_coverage(_ADBE) == ()
    store.close()


# -- User Story 3: idempotency + historical snapshots ------------------------


def test_reingesting_identical_content_is_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = FakeSecClient()
    ingest_company("ADBE", sec_client=client, store=store)
    before = _row_counts(store)

    second = ingest_company("ADBE", sec_client=client, store=store)
    assert second.status is IngestionStatus.UNCHANGED
    assert second.persisted_fact_count == 0
    assert second.persisted_metric_count == 0
    assert second.analysis_count == 0
    assert _row_counts(store) == before
    store.close()


def test_unchanged_requires_matching_versions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = ingest_company("ADBE", sec_client=FakeSecClient(), store=store)
    assert result.source_snapshot is not None
    content_hash = result.source_snapshot.content_hash

    assert store.snapshot_matches_versions(
        _ADBE, content_hash, calculation_version="1.0", analysis_rule_version="1.0"
    )
    # A different calculation version must not be treated as unchanged.
    assert not store.snapshot_matches_versions(
        _ADBE, content_hash, calculation_version="9.9", analysis_rule_version="1.0"
    )
    store.close()


def test_changed_content_creates_new_snapshot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ingest_company("ADBE", sec_client=FakeSecClient(), store=store)

    def adbe_amended() -> dict[str, Any]:
        facts = adbe_facts()
        facts["entityName"] = "ADOBE INC. (amended)"
        return facts

    amended: dict[str, Callable[[], dict[str, Any]]] = {**FIXTURE_FACTS, "ADBE": adbe_amended}
    second = ingest_company(
        "ADBE", sec_client=FakeSecClient(facts=amended), store=store
    )
    assert second.status in (IngestionStatus.COMPLETE, IngestionStatus.PARTIAL)

    snapshot_count = store._conn.execute(
        "SELECT COUNT(*) FROM source_snapshots s "
        "JOIN companies c ON c.id = s.company_id WHERE c.cik = ?",
        (_ADBE,),
    ).fetchone()[0]
    assert snapshot_count == 2
    store.close()


def test_ambiguous_revenue_restatement_degrades_instead_of_crashing(tmp_path: Path) -> None:
    # Slice 6A (PFE): revenue ambiguity errors are not AnnualNormalizationError
    # subclasses; ingestion must still degrade explicitly, never raise.
    def adbe_with_ambiguous_revenue() -> dict[str, Any]:
        facts = adbe_facts()
        entries = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        conflict = dict(entries[0])
        conflict["val"] += 1_000_000
        conflict["filed"] = "2030-01-01"
        entries.append(conflict)
        return facts

    store = _store(tmp_path)
    facts_map: dict[str, Callable[[], dict[str, Any]]] = {"ADBE": adbe_with_ambiguous_revenue}
    result = ingest_company("ADBE", sec_client=FakeSecClient(facts=facts_map), store=store)

    assert result.failure is None
    assert result.status is not IngestionStatus.COMPLETE
    assert result.source_snapshot is not None
    store.close()

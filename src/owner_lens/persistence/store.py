"""Local SQLite persistence store for OwnerLens Slice 4A.

``SqliteStore`` implements the domain-oriented storage boundary described in
``specs/013-persistence-storage-boundary/contracts/persistence-api.md`` using the
Python standard-library ``sqlite3`` module. It stores OwnerLens outputs only and
performs no normalization, calculation, or classification. Exact money and share
counts are stored as ``INTEGER``; derived ratios are stored as ``REAL`` (IEEE-754
floating point, approximate). Coverage states and reported zero are explicit and
never collapsed into SQL ``NULL``. Every fact, metric, analysis, and coverage row
references a source snapshot, so historical snapshots coexist. Failures surface
as the persistence-category errors in ``owner_lens.persistence.errors``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import uuid4

from owner_lens.persistence.errors import (
    PersistenceError,
    SchemaVersionError,
    StorageConnectionError,
    StorageReadError,
    StorageWriteError,
)
from owner_lens.persistence.raw import RawSnapshotStore, compute_content_hash
from owner_lens.persistence.records import (
    SCHEMA_VERSION,
    AnalysisDriverRecord,
    AnalysisResultRecord,
    ChallengerRunRecord,
    CompanyRecord,
    CoverageResultRecord,
    DecisionRecord,
    DerivedMetricRecord,
    FmpCanonicalCoverageRecord,
    FmpCanonicalFactRecord,
    FmpCanonicalHistoryRecord,
    FmpEodPriceRecord,
    FmpEstimateRecord,
    FmpEvidenceSnapshotRecord,
    PortfolioSnapshotRecord,
    ReportedFactRecord,
    SecurityRecord,
    SecurityRefreshStateRecord,
    ShadowEntryRecord,
    SizingAnalysisRecord,
    SourceSnapshotRecord,
    UnderwritingRecord,
    UniverseConstituentRecord,
    UniverseRefreshRunRecord,
    UniverseSnapshotRecord,
)

__all__ = ["OwnerLensStore", "SqliteStore"]

_AGGREGATE_REFRESH_DATASETS = {
    "annual_statements": (
        "annual_income_statement",
        "annual_balance_sheet_statement",
        "annual_cash_flow_statement",
    ),
    "quarterly_statements": (
        "quarterly_income_statement",
        "quarterly_balance_sheet_statement",
        "quarterly_cash_flow_statement",
    ),
    "analyst_estimates": (
        "annual_analyst_estimates",
        "quarterly_analyst_estimates",
    ),
}


def _resolve_aggregate_refresh_states(
    records: tuple[SecurityRefreshStateRecord, ...],
) -> tuple[SecurityRefreshStateRecord, ...]:
    by_key = {(record.security_id, record.dataset): record for record in records}
    resolved: list[SecurityRefreshStateRecord] = []
    for record in records:
        children = _AGGREGATE_REFRESH_DATASETS.get(record.dataset)
        if children is None:
            resolved.append(record)
            continue
        child_records = [by_key.get((record.security_id, child)) for child in children]
        statuses = [
            child.status if child is not None else "PENDING"
            for child in child_records
        ]
        if "FAILED" in statuses:
            status = "FAILED"
        elif "RUNNING" in statuses:
            status = "RUNNING"
        elif len(set(statuses)) == 1:
            status = statuses[0]
        else:
            status = "PARTIAL"
        attempts = [
            child.last_attempt_at
            for child in child_records
            if child is not None and child.last_attempt_at is not None
        ]
        details = [
            f"{name}: {child.status if child is not None else 'PENDING'}"
            + (f" ({child.last_error})" if child is not None and child.last_error else "")
            for name, child in zip(children, child_records, strict=True)
            if child is None or child.status != "SUCCEEDED"
        ]
        resolved.append(
            SecurityRefreshStateRecord(
                security_id=record.security_id,
                dataset=record.dataset,
                status=status,
                last_attempt_at=max(attempts) if attempts else None,
                last_error="; ".join(details) if details else None,
            )
        )
    return tuple(resolved)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS portfolio_no_update
BEFORE UPDATE ON portfolio_snapshots BEGIN
    SELECT RAISE(ABORT, 'Portfolio snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS portfolio_no_delete
BEFORE DELETE ON portfolio_snapshots BEGIN
    SELECT RAISE(ABORT, 'Portfolio snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS portfolio_no_replace
BEFORE INSERT ON portfolio_snapshots
WHEN EXISTS (SELECT 1 FROM portfolio_snapshots WHERE snapshot_id=NEW.snapshot_id)
BEGIN
    SELECT RAISE(ABORT, 'Portfolio snapshots are immutable');
END;
CREATE TABLE IF NOT EXISTS sizing_analyses (
    analysis_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    underwriting_id TEXT NOT NULL REFERENCES underwriting_records(underwriting_id),
    portfolio_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id),
    decision_id TEXT REFERENCES decision_records(decision_id),
    model_version TEXT NOT NULL,
    report_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS sizing_no_update
BEFORE UPDATE ON sizing_analyses BEGIN
    SELECT RAISE(ABORT, 'Sizing analyses are immutable');
END;
CREATE TRIGGER IF NOT EXISTS sizing_no_delete
BEFORE DELETE ON sizing_analyses BEGIN
    SELECT RAISE(ABORT, 'Sizing analyses are immutable');
END;
CREATE TRIGGER IF NOT EXISTS sizing_no_replace
BEFORE INSERT ON sizing_analyses
WHEN EXISTS (SELECT 1 FROM sizing_analyses WHERE analysis_id=NEW.analysis_id)
BEGIN
    SELECT RAISE(ABORT, 'Sizing analyses are immutable');
END;
CREATE TABLE IF NOT EXISTS decision_records (
    decision_id TEXT PRIMARY KEY,
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    ticker TEXT NOT NULL,
    underwriting_id TEXT NOT NULL REFERENCES underwriting_records(underwriting_id),
    underwriting_version INTEGER NOT NULL CHECK(underwriting_version > 0),
    decision_at TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_security ON decision_records(security_id, decision_at);
CREATE TRIGGER IF NOT EXISTS decision_no_update
BEFORE UPDATE ON decision_records BEGIN
    SELECT RAISE(ABORT, 'Decision records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS decision_no_delete
BEFORE DELETE ON decision_records BEGIN
    SELECT RAISE(ABORT, 'Decision records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS decision_no_replace
BEFORE INSERT ON decision_records
WHEN EXISTS (SELECT 1 FROM decision_records WHERE decision_id = NEW.decision_id)
BEGIN
    SELECT RAISE(ABORT, 'Decision records are immutable');
END;
CREATE TABLE IF NOT EXISTS shadow_entries (
    shadow_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decision_records(decision_id),
    underwriting_id TEXT REFERENCES underwriting_records(underwriting_id),
    role TEXT NOT NULL CHECK(role IN (
        'ACTUAL_CHOICE', 'BEST_ALTERNATIVE', 'PASS_CANDIDATE', 'BENCHMARK')),
    snapshot_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(decision_id, underwriting_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS shadow_single_role ON shadow_entries(decision_id, role)
WHERE role IN ('ACTUAL_CHOICE', 'BEST_ALTERNATIVE', 'BENCHMARK');
CREATE TRIGGER IF NOT EXISTS shadow_no_update
BEFORE UPDATE ON shadow_entries BEGIN
    SELECT RAISE(ABORT, 'Shadow entries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS shadow_no_delete
BEFORE DELETE ON shadow_entries BEGIN
    SELECT RAISE(ABORT, 'Shadow entries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS shadow_no_replace
BEFORE INSERT ON shadow_entries
WHEN EXISTS (SELECT 1 FROM shadow_entries WHERE shadow_id = NEW.shadow_id OR
    (decision_id = NEW.decision_id AND (
        underwriting_id = NEW.underwriting_id OR
        (role = NEW.role AND role IN ('ACTUAL_CHOICE', 'BEST_ALTERNATIVE', 'BENCHMARK')))))
BEGIN
    SELECT RAISE(ABORT, 'Shadow entries are immutable');
END;
CREATE TABLE IF NOT EXISTS challenger_runs (
    run_id TEXT PRIMARY KEY,
    underwriting_id TEXT NOT NULL REFERENCES underwriting_records(underwriting_id),
    underwriting_version INTEGER NOT NULL,
    underwriting_content_hash TEXT NOT NULL,
    challenger_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    input_content_hash TEXT NOT NULL,
    context_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    output_content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS challenger_underwriting ON challenger_runs(underwriting_id, created_at);
CREATE TRIGGER IF NOT EXISTS challenger_no_update
BEFORE UPDATE ON challenger_runs BEGIN
    SELECT RAISE(ABORT, 'Challenger runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS challenger_no_delete
BEFORE DELETE ON challenger_runs BEGIN
    SELECT RAISE(ABORT, 'Challenger runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS challenger_no_replace
BEFORE INSERT ON challenger_runs
WHEN EXISTS (SELECT 1 FROM challenger_runs WHERE run_id = NEW.run_id)
BEGIN
    SELECT RAISE(ABORT, 'Challenger runs are immutable');
END;
CREATE TABLE IF NOT EXISTS valuation_results (
    underwriting_id TEXT NOT NULL REFERENCES underwriting_records(underwriting_id),
    model_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(underwriting_id, model_version)
);
CREATE TRIGGER IF NOT EXISTS valuation_no_update
BEFORE UPDATE ON valuation_results BEGIN
    SELECT RAISE(ABORT, 'Valuation results are immutable');
END;
CREATE TRIGGER IF NOT EXISTS valuation_no_delete
BEFORE DELETE ON valuation_results BEGIN
    SELECT RAISE(ABORT, 'Valuation results are immutable');
END;
CREATE TRIGGER IF NOT EXISTS valuation_no_replace
BEFORE INSERT ON valuation_results
WHEN EXISTS (SELECT 1 FROM valuation_results WHERE
    underwriting_id = NEW.underwriting_id AND model_version = NEW.model_version)
BEGIN
    SELECT RAISE(ABORT, 'Valuation results are immutable');
END;
CREATE TABLE IF NOT EXISTS underwriting_records (
    underwriting_id TEXT PRIMARY KEY,
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    ticker TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(security_id, version)
);
CREATE TRIGGER IF NOT EXISTS underwriting_no_update
BEFORE UPDATE ON underwriting_records BEGIN
    SELECT RAISE(ABORT, 'Underwriting records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS underwriting_no_delete
BEFORE DELETE ON underwriting_records BEGIN
    SELECT RAISE(ABORT, 'Underwriting records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS underwriting_no_replace
BEFORE INSERT ON underwriting_records
WHEN EXISTS (SELECT 1 FROM underwriting_records WHERE
    underwriting_id = NEW.underwriting_id OR
    (security_id = NEW.security_id AND version = NEW.version))
BEGIN
    SELECT RAISE(ABORT, 'Underwriting records are immutable');
END;
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    id           INTEGER PRIMARY KEY,
    cik          TEXT NOT NULL UNIQUE,
    ticker       TEXT NOT NULL,
    company_name TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_snapshots (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id),
    source_provider   TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    fetched_at        TEXT NOT NULL,
    source_uri        TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    raw_object_ref    TEXT,
    processing_status TEXT,
    UNIQUE(company_id, source_provider, source_type, content_hash)
);
CREATE TABLE IF NOT EXISTS reported_facts (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    snapshot_id      INTEGER NOT NULL REFERENCES source_snapshots(id),
    canonical_metric TEXT NOT NULL,
    value            INTEGER NOT NULL,
    unit             TEXT NOT NULL,
    fact_kind        TEXT NOT NULL,
    fiscal_year      INTEGER NOT NULL,
    period_start     TEXT,
    period_end       TEXT NOT NULL,
    concept          TEXT NOT NULL,
    form             TEXT NOT NULL,
    filed            TEXT NOT NULL,
    accession        TEXT NOT NULL,
    UNIQUE(snapshot_id, canonical_metric, concept, fiscal_year, period_end)
);
CREATE TABLE IF NOT EXISTS derived_metrics (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    snapshot_id         INTEGER NOT NULL REFERENCES source_snapshots(id),
    metric_name         TEXT NOT NULL,
    fiscal_year         INTEGER NOT NULL,
    value_real          REAL,
    value_int           INTEGER,
    unit                TEXT,
    calculation_version TEXT NOT NULL,
    computed_at         TEXT NOT NULL,
    UNIQUE(snapshot_id, metric_name, fiscal_year, calculation_version)
);
CREATE TABLE IF NOT EXISTS analysis_results (
    id                    INTEGER PRIMARY KEY,
    company_id            INTEGER NOT NULL REFERENCES companies(id),
    snapshot_id           INTEGER NOT NULL REFERENCES source_snapshots(id),
    analysis_type         TEXT NOT NULL,
    analysis_period       TEXT NOT NULL,
    classification        TEXT NOT NULL,
    analysis_rule_version TEXT NOT NULL,
    computed_at           TEXT NOT NULL,
    UNIQUE(snapshot_id, analysis_type, analysis_period, analysis_rule_version)
);
CREATE TABLE IF NOT EXISTS analysis_drivers (
    id                 INTEGER PRIMARY KEY,
    analysis_result_id INTEGER NOT NULL REFERENCES analysis_results(id),
    position           INTEGER NOT NULL,
    code               TEXT NOT NULL,
    category           TEXT,
    UNIQUE(analysis_result_id, position)
);
CREATE TABLE IF NOT EXISTS coverage_results (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    snapshot_id    INTEGER NOT NULL REFERENCES source_snapshots(id),
    subject_kind   TEXT NOT NULL,
    subject        TEXT NOT NULL,
    state          TEXT NOT NULL,
    reason         TEXT,
    blocking_input TEXT,
    UNIQUE(snapshot_id, subject_kind, subject)
);
CREATE TABLE IF NOT EXISTS securities (
    security_id INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    cik         TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS universe_snapshots (
    snapshot_id     INTEGER PRIMARY KEY,
    provider        TEXT NOT NULL,
    observed_at     TEXT NOT NULL,
    source_uri      TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    raw_object_ref  TEXT,
    UNIQUE(provider, content_hash)
);
CREATE TABLE IF NOT EXISTS universe_members (
    snapshot_id INTEGER NOT NULL REFERENCES universe_snapshots(snapshot_id),
    security_id INTEGER NOT NULL REFERENCES securities(security_id),
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL,
    cik         TEXT,
    sector      TEXT,
    subsector   TEXT,
    PRIMARY KEY(snapshot_id, security_id),
    UNIQUE(snapshot_id, symbol)
);
CREATE TABLE IF NOT EXISTS universe_refresh_runs (
    run_id             TEXT PRIMARY KEY,
    started_at         TEXT NOT NULL,
    completed_at       TEXT,
    status             TEXT NOT NULL CHECK(status IN (
                           'RUNNING', 'SUCCEEDED', 'FAILED'
                       )),
    snapshot_id        INTEGER REFERENCES universe_snapshots(snapshot_id),
    requested_symbols  TEXT NOT NULL,
    error              TEXT
);
CREATE TABLE IF NOT EXISTS security_refresh_state (
    security_id      INTEGER NOT NULL REFERENCES securities(security_id),
    dataset          TEXT NOT NULL,
    status           TEXT NOT NULL CHECK(status IN (
                         'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED',
                         'PARTIAL', 'UNSUPPORTED'
                     )),
    last_attempt_at  TEXT,
    last_error       TEXT,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY(security_id, dataset)
);
CREATE TABLE IF NOT EXISTS fmp_evidence_snapshots (
    snapshot_id          INTEGER PRIMARY KEY,
    security_id          INTEGER NOT NULL REFERENCES securities(security_id),
    dataset              TEXT NOT NULL,
    period_type          TEXT NOT NULL,
    source_endpoint      TEXT NOT NULL,
    request_parameters   TEXT NOT NULL,
    fetched_at           TEXT NOT NULL,
    content_hash         TEXT NOT NULL,
    raw_object_ref        TEXT,
    evidence_kind        TEXT NOT NULL CHECK(evidence_kind IN ('FACT', 'EXPECTATION')),
    UNIQUE(security_id, dataset, request_parameters, content_hash, fetched_at)
);
CREATE INDEX IF NOT EXISTS fmp_evidence_by_dataset
    ON fmp_evidence_snapshots(security_id, dataset, fetched_at);
CREATE TABLE IF NOT EXISTS fmp_canonical_histories (
    history_id     INTEGER PRIMARY KEY,
    security_id    INTEGER NOT NULL REFERENCES securities(security_id),
    provider       TEXT NOT NULL CHECK(provider = 'fmp'),
    period_type    TEXT NOT NULL CHECK(period_type = 'annual'),
    input_hash     TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    max_years      INTEGER NOT NULL,
    UNIQUE(security_id, provider, period_type, input_hash)
);
CREATE TABLE IF NOT EXISTS fmp_canonical_facts (
    history_id    INTEGER NOT NULL REFERENCES fmp_canonical_histories(history_id),
    snapshot_id   INTEGER NOT NULL REFERENCES fmp_evidence_snapshots(snapshot_id),
    metric        TEXT NOT NULL,
    fiscal_year   INTEGER NOT NULL,
    period_end    TEXT NOT NULL,
    value         INTEGER NOT NULL,
    unit          TEXT NOT NULL,
    provider      TEXT NOT NULL CHECK(provider = 'fmp'),
    provider_field TEXT NOT NULL,
    PRIMARY KEY(history_id, metric, fiscal_year, period_end)
);
CREATE TABLE IF NOT EXISTS fmp_metric_coverage (
    history_id INTEGER NOT NULL REFERENCES fmp_canonical_histories(history_id),
    metric     TEXT NOT NULL,
    status     TEXT NOT NULL CHECK(status IN (
                   'AVAILABLE', 'STRUCTURALLY_ABSENT', 'UNSUPPORTED', 'INVALID'
               )),
    reason     TEXT,
    PRIMARY KEY(history_id, metric)
);
CREATE TABLE IF NOT EXISTS fmp_eod_prices (
    snapshot_id  INTEGER PRIMARY KEY REFERENCES fmp_evidence_snapshots(snapshot_id),
    security_id  INTEGER NOT NULL REFERENCES securities(security_id),
    market_date  TEXT NOT NULL,
    close        REAL NOT NULL CHECK(close > 0),
    source_field TEXT NOT NULL,
    currency     TEXT
);
CREATE TABLE IF NOT EXISTS fmp_estimates (
    snapshot_id            INTEGER NOT NULL REFERENCES fmp_evidence_snapshots(snapshot_id),
    target_date            TEXT NOT NULL,
    revenue_low            REAL,
    revenue_average        REAL,
    revenue_high           REAL,
    revenue_analyst_count  INTEGER,
    eps_low                REAL,
    eps_average            REAL,
    eps_high               REAL,
    eps_analyst_count      INTEGER,
    evidence_kind          TEXT NOT NULL CHECK(evidence_kind = 'EXPECTATION'),
    PRIMARY KEY(snapshot_id, target_date)
);
"""


class OwnerLensStore(Protocol):
    """Domain-oriented storage boundary for OwnerLens outputs."""

    def initialize(self) -> None: ...

    def save_company(self, company: CompanyRecord) -> None: ...

    def save_source_snapshot(
        self, snapshot: SourceSnapshotRecord, *, raw_payload: bytes | None = None
    ) -> None: ...

    def save_reported_facts(
        self, facts: Sequence[ReportedFactRecord], *, snapshot: SourceSnapshotRecord
    ) -> None: ...

    def save_derived_metrics(
        self, metrics: Sequence[DerivedMetricRecord], *, snapshot: SourceSnapshotRecord
    ) -> None: ...

    def save_analysis_result(
        self, result: AnalysisResultRecord, *, snapshot: SourceSnapshotRecord
    ) -> None: ...

    def save_coverage(
        self, coverage: Sequence[CoverageResultRecord], *, snapshot: SourceSnapshotRecord
    ) -> None: ...

    def source_snapshot_exists(self, cik: str, content_hash: str) -> bool: ...

    def get_source_snapshot(
        self, cik: str, content_hash: str
    ) -> SourceSnapshotRecord | None: ...

    def get_latest_source_snapshot(self, cik: str) -> SourceSnapshotRecord | None: ...

    def snapshot_matches_versions(
        self,
        cik: str,
        content_hash: str,
        *,
        calculation_version: str,
        analysis_rule_version: str,
    ) -> bool: ...

    def set_snapshot_processing_status(
        self, cik: str, content_hash: str, status: str
    ) -> None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def get_company(self, cik: str) -> CompanyRecord | None: ...

    def list_companies(self) -> tuple[CompanyRecord, ...]: ...

    def get_metric_history(
        self, cik: str, metric: str, *, limit: int | None = None
    ) -> tuple[DerivedMetricRecord, ...]: ...

    def get_fact_provenance(
        self, cik: str, canonical_metric: str, fiscal_year: int
    ) -> ReportedFactRecord | None: ...

    def get_latest_summary(self, cik: str) -> AnalysisResultRecord | None: ...

    def get_company_coverage(self, cik: str) -> tuple[CoverageResultRecord, ...]: ...

    def get_latest_metric_across_companies(
        self, metric: str, ciks: Sequence[str]
    ) -> dict[str, DerivedMetricRecord]: ...


class SqliteStore:
    """A local SQLite implementation of the OwnerLens storage boundary."""

    def __init__(
        self, db_path: Path, *, raw_store: RawSnapshotStore | None = None
    ) -> None:
        self._db_path = Path(db_path)
        self._raw_store = raw_store
        self._in_transaction = False
        try:
            self._conn = sqlite3.connect(self._db_path)
        except sqlite3.Error as exc:
            raise StorageConnectionError(
                f"Cannot open persistence store at {self._db_path}: {exc}"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            raise StorageConnectionError(
                f"Cannot configure persistence store: {exc}"
            ) from exc

    # -- Lifecycle -----------------------------------------------------------

    def initialize(self) -> None:
        try:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                self._conn.commit()
            else:
                stored = int(row["value"])
                if 1 <= stored < SCHEMA_VERSION:
                    self._migrate_to_current_schema(stored)
                    self._conn.execute(
                        "UPDATE schema_meta SET value = ? "
                        "WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )
                    self._conn.commit()
                elif stored != SCHEMA_VERSION:
                    raise SchemaVersionError(
                        f"Stored schema version {stored} is incompatible with "
                        f"expected version {SCHEMA_VERSION}."
                    )
        except sqlite3.Error as exc:
            raise StorageConnectionError(
                f"Cannot initialize persistence store: {exc}"
            ) from exc

    def _migrate_to_current_schema(self, stored_version: int) -> None:
        if stored_version in (3, 4, 5, 6, 7):
            return  # Additive tables and triggers are installed by _SCHEMA.
        if stored_version not in (1, 2):
            raise SchemaVersionError(
                f"No migration path from schema version {stored_version}."
            )
        try:
            with self.transaction():
                rows = self._conn.execute(
                    "SELECT security_id, dataset, status, last_attempt_at, "
                    "last_error, updated_at FROM security_refresh_state"
                ).fetchall()
                self._conn.execute("DROP TABLE security_refresh_state")
                self._conn.execute(
                    "CREATE TABLE security_refresh_state ("
                    "security_id INTEGER NOT NULL REFERENCES securities(security_id), "
                    "dataset TEXT NOT NULL, "
                    "status TEXT NOT NULL CHECK(status IN ("
                    "'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', "
                    "'PARTIAL', 'UNSUPPORTED')), "
                    "last_attempt_at TEXT, last_error TEXT, updated_at TEXT NOT NULL, "
                    "PRIMARY KEY(security_id, dataset))"
                )
                self._conn.executemany(
                    "INSERT INTO security_refresh_state(security_id, dataset, status, "
                    "last_attempt_at, last_error, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row["security_id"],
                            row["dataset"],
                            row["status"],
                            row["last_attempt_at"],
                            row["last_error"],
                            row["updated_at"],
                        )
                        for row in rows
                    ],
                )
        except sqlite3.Error as exc:
            raise StorageConnectionError(
                f"Cannot migrate persistence schema from version {stored_version}: {exc}"
            ) from exc

    def close(self) -> None:
        self._conn.close()

    def save_portfolio_snapshot(self, snapshot_json: str) -> PortfolioSnapshotRecord:
        from owner_lens.position_sizing import (
            PortfolioSnapshot,
            validate_portfolio_sources,
        )

        if self._in_transaction:
            raise StorageWriteError("Portfolio creation requires its own transaction.")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            snapshot = PortfolioSnapshot.from_json(snapshot_json)
            validate_portfolio_sources(self, snapshot)
            payload = snapshot.to_json()
            record = PortfolioSnapshotRecord(
                snapshot.snapshot_id, snapshot.created_at, snapshot.as_of_date,
                payload, compute_content_hash(payload.encode()),
            )
            self._conn.execute(
                "INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?, ?)",
                tuple(getattr(record, name) for name in record.__dataclass_fields__),
            )
            self._conn.commit()
            return record
        except (sqlite3.Error, PersistenceError, ValueError, KeyError, TypeError) as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot append portfolio snapshot: {exc}") from exc

    def list_portfolio_snapshots(self) -> tuple[PortfolioSnapshotRecord, ...]:
        from owner_lens.position_sizing import PortfolioSnapshot

        try:
            rows = self._conn.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY julianday(created_at), rowid"
            ).fetchall()
            records = tuple(PortfolioSnapshotRecord(**dict(row)) for row in rows)
            for record in records:
                snapshot = PortfolioSnapshot.from_json(record.snapshot_json)
                if (
                    compute_content_hash(record.snapshot_json.encode()) != record.content_hash
                    or (snapshot.snapshot_id, snapshot.created_at, snapshot.as_of_date)
                    != (record.snapshot_id, record.created_at, record.as_of_date)
                ):
                    raise StorageReadError("Portfolio failed identity/content integrity verification.")
            return records
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise StorageReadError(f"Cannot read portfolios: {exc}") from exc

    def get_portfolio_snapshot(self, snapshot_id: str) -> str:
        selected = next((item for item in self.list_portfolio_snapshots() if item.snapshot_id == snapshot_id), None)
        if selected is None:
            raise StorageReadError(f"Portfolio snapshot {snapshot_id} not found.")
        return selected.snapshot_json

    def save_sizing_analysis(self, report_json: str, *, created_at: str) -> SizingAnalysisRecord:
        from owner_lens.decisions import load_decision_json
        from owner_lens.position_sizing import canonical_json, validate_sizing_sources

        if self._in_transaction:
            raise StorageWriteError("Sizing persistence requires its own transaction.")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            report = load_decision_json(report_json)
            validate_sizing_sources(self, report, created_at)
            payload = canonical_json(report)
            record = SizingAnalysisRecord(
                str(uuid4()), created_at, report["underwriting"]["underwriting_id"],
                report["portfolio"]["snapshot_id"],
                report["decision_context"]["decision_id"] if report["decision_context"] is not None else None,
                report["model_version"], payload, compute_content_hash(payload.encode()),
            )
            self._conn.execute(
                "INSERT INTO sizing_analyses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(getattr(record, name) for name in record.__dataclass_fields__),
            )
            self._conn.commit()
            return record
        except (sqlite3.Error, PersistenceError, ValueError, KeyError, TypeError) as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot append sizing analysis: {exc}") from exc

    def list_sizing_analyses(self) -> tuple[SizingAnalysisRecord, ...]:
        try:
            rows = self._conn.execute(
                "SELECT * FROM sizing_analyses ORDER BY julianday(created_at), rowid"
            ).fetchall()
            records = tuple(SizingAnalysisRecord(**dict(row)) for row in rows)
            for record in records:
                report = json.loads(record.report_json)
                if (
                    compute_content_hash(record.report_json.encode()) != record.content_hash
                    or (record.underwriting_id, record.portfolio_id, record.model_version, record.decision_id)
                    != (report["underwriting"]["underwriting_id"], report["portfolio"]["snapshot_id"],
                        report["model_version"], report["decision_context"]["decision_id"] if report["decision_context"] is not None else None)
                ):
                    raise StorageReadError("Sizing analysis failed identity/content integrity verification.")
            return records
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise StorageReadError(f"Cannot read sizing analyses: {exc}") from exc

    def get_sizing_analysis(self, analysis_id: str) -> SizingAnalysisRecord:
        selected = next((item for item in self.list_sizing_analyses() if item.analysis_id == analysis_id), None)
        if selected is None:
            raise StorageReadError(f"Sizing analysis {analysis_id} not found.")
        return selected

    def save_decision(self, snapshot_json: str) -> DecisionRecord:
        """Append a validated decision and all shadow starts in one transaction."""
        from owner_lens.decisions import DecisionSnapshot, validate_decision_sources

        if self._in_transaction:
            raise StorageWriteError("Decision creation requires its own transaction.")
        try:
            snapshot = DecisionSnapshot.from_json(snapshot_json)
            self._conn.execute("BEGIN IMMEDIATE")
            validate_decision_sources(self, snapshot)
            underwriting = snapshot.chosen.underwriting
            record = DecisionRecord(
                snapshot.decision_id, underwriting.security_id, underwriting.ticker,
                underwriting.underwriting_id, underwriting.version,
                snapshot.decision_at, snapshot.as_of_date, snapshot.to_json(),
                compute_content_hash(snapshot.to_json().encode()),
            )
            self._conn.execute(
                "INSERT INTO decision_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(getattr(record, name) for name in record.__dataclass_fields__),
            )
            for entry in snapshot.shadows:
                self._conn.execute(
                    "INSERT INTO shadow_entries VALUES (?, ?, ?, ?, ?, ?)",
                    (entry.shadow_id, entry.decision_id, entry.underwriting_id,
                     entry.role, entry.to_json(), compute_content_hash(entry.to_json().encode())),
                )
            self._conn.commit()
            return record
        except (sqlite3.Error, PersistenceError, ValueError, KeyError, TypeError) as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot append decision/shadow state: {exc}") from exc

    def list_decisions(self, ticker: str | None = None) -> tuple[DecisionRecord, ...]:
        """Chronological decision history, optionally resolved by stable security."""
        from owner_lens.decisions import DecisionSnapshot

        try:
            if ticker is None:
                rows = self._conn.execute(
                    "SELECT * FROM decision_records ORDER BY julianday(decision_at), rowid"
                ).fetchall()
            else:
                # This also rejects ambiguous historical aliases.
                underwritings = self.list_underwriting(ticker.strip().upper())
                if not underwritings:
                    return ()
                rows = self._conn.execute(
                    "SELECT * FROM decision_records WHERE security_id=? "
                    "ORDER BY julianday(decision_at), rowid",
                    (underwritings[0].security_id,),
                ).fetchall()
            result = tuple(DecisionRecord(**dict(row)) for row in rows)
            for record in result:
                if compute_content_hash(record.snapshot_json.encode()) != record.content_hash:
                    raise StorageReadError("Decision failed content integrity verification.")
                snapshot = DecisionSnapshot.from_json(record.snapshot_json)
                chosen = snapshot.chosen.underwriting
                if (
                    (record.decision_id, record.security_id, record.ticker,
                     record.underwriting_id, record.underwriting_version, record.decision_at, record.as_of_date)
                    != (snapshot.decision_id, chosen.security_id, chosen.ticker,
                        chosen.underwriting_id, chosen.version, snapshot.decision_at, snapshot.as_of_date)
                ):
                    raise StorageReadError("Decision index differs from immutable snapshot.")
            return result
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise StorageReadError(f"Cannot read decisions: {exc}") from exc

    def list_shadow_entries(self, decision_id: str | None = None) -> tuple[ShadowEntryRecord, ...]:
        """Read verified frozen starts only, never current market observations."""
        from owner_lens.decisions import read_decision

        try:
            decisions = {record.decision_id: read_decision(record) for record in self.list_decisions()}
            if decision_id is not None and decision_id not in decisions:
                raise StorageReadError(f"Decision {decision_id} not found.")
            rows = self._conn.execute(
                "SELECT s.* FROM shadow_entries s JOIN decision_records d "
                "ON s.decision_id=d.decision_id WHERE (? IS NULL OR s.decision_id=?) "
                "ORDER BY julianday(d.decision_at), d.rowid, s.rowid",
                (decision_id, decision_id),
            ).fetchall()
            result = tuple(ShadowEntryRecord(**dict(row)) for row in rows)
            expected = {
                entry.shadow_id: entry
                for identifier, snapshot in decisions.items()
                if decision_id is None or identifier == decision_id
                for entry in snapshot.shadows
            }
            if set(expected) != {record.shadow_id for record in result}:
                raise StorageReadError("Shadow entries differ from the decision bundle.")
            for record in result:
                entry = expected[record.shadow_id]
                if (
                    compute_content_hash(record.snapshot_json.encode()) != record.content_hash
                    or record.snapshot_json != entry.to_json()
                    or (record.decision_id, record.underwriting_id, record.role)
                    != (entry.decision_id, entry.underwriting_id, entry.role)
                ):
                    raise StorageReadError("Shadow failed identity/content integrity verification.")
            return result
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise StorageReadError(f"Cannot read shadow entries: {exc}") from exc

    def save_underwriting(
        self, *, security_id: int, ticker: str, created_at: str,
        as_of_date: str, snapshot_json: str,
        expected_latest_version: int | None = None,
    ) -> UnderwritingRecord:
        """Allocate a version and append atomically, never updating a prior record."""
        if self._in_transaction:
            raise StorageWriteError("Underwriting creation requires its own transaction.")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS version "
                "FROM underwriting_records WHERE security_id = ?", (security_id,),
            ).fetchone()
            if expected_latest_version is not None and int(row["version"]) != expected_latest_version + 1:
                self._conn.rollback()
                raise StorageWriteError(
                    "Underwriting history changed since review. Review the latest version before saving."
                )
            record = UnderwritingRecord(
                str(uuid4()), security_id, ticker, int(row["version"]),
                created_at, as_of_date, snapshot_json,
                compute_content_hash(snapshot_json.encode()),
            )
            self._conn.execute(
                "INSERT INTO underwriting_records(underwriting_id, security_id, ticker, "
                "version, created_at, as_of_date, snapshot_json, content_hash) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (record.underwriting_id, record.security_id, record.ticker,
                 record.version, record.created_at, record.as_of_date,
                 record.snapshot_json, record.content_hash),
            )
            self._conn.commit()
            return record
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot append underwriting record: {exc}") from exc

    def list_underwriting(self, ticker: str) -> tuple[UnderwritingRecord, ...]:
        """Resolve by current security symbol or historical recorded symbol."""
        try:
            rows = self._conn.execute(
                "SELECT u.* FROM underwriting_records u WHERE u.security_id IN ("
                "SELECT security_id FROM securities WHERE symbol = ? UNION "
                "SELECT security_id FROM underwriting_records WHERE ticker = ?) "
                "ORDER BY version", (ticker, ticker),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read underwriting history: {exc}") from exc
        records = tuple(UnderwritingRecord(**dict(row)) for row in rows)
        if len({record.security_id for record in records}) > 1:
            raise StorageReadError(f"Ambiguous historical security symbol: {ticker}.")
        for record in records:
            if compute_content_hash(record.snapshot_json.encode()) != record.content_hash:
                raise StorageReadError(f"Underwriting {record.underwriting_id} failed integrity verification.")
        return records

    def get_valuation(self, underwriting_id: str, model_version: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT result_json, content_hash FROM valuation_results "
                "WHERE underwriting_id=? AND model_version=?",
                (underwriting_id, model_version),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read valuation: {exc}") from exc
        if row is None:
            return None
        if compute_content_hash(row["result_json"].encode()) != row["content_hash"]:
            raise StorageReadError("Valuation result failed integrity verification.")
        return str(row["result_json"])

    def save_challenger_run(
        self, record: UnderwritingRecord, *, challenger_version: str, model_version: str,
        created_at: str, context_json: str, output_json: str,
    ) -> ChallengerRunRecord:
        if self._in_transaction:
            raise StorageWriteError("Challenger persistence requires its own transaction.")
        try:
            context = json.loads(context_json)
            output = json.loads(output_json)
            identity = context["record"]
            if (identity["underwriting_id"] != record.underwriting_id
                    or identity["version"] != record.version
                    or identity["content_hash"] != record.content_hash
                    or context["snapshot"] != json.loads(record.snapshot_json)
                    or output["category"] != "JUDGMENT"):
                raise StorageWriteError("Challenger context/output does not match immutable underwriting.")
            self._conn.execute("BEGIN IMMEDIATE")
            saved = self._conn.execute(
                "SELECT version, content_hash FROM underwriting_records WHERE underwriting_id=?",
                (record.underwriting_id,),
            ).fetchone()
            if saved is None or (saved["version"], saved["content_hash"]) != (record.version, record.content_hash):
                raise StorageWriteError("Challenger underwriting identity/hash not found in store.")
            run = ChallengerRunRecord(
                str(uuid4()), record.underwriting_id, record.version, record.content_hash,
                challenger_version, model_version, created_at,
                compute_content_hash(context_json.encode()), context_json, output_json,
                compute_content_hash(output_json.encode()),
            )
            self._conn.execute(
                "INSERT INTO challenger_runs VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(getattr(run, name) for name in run.__dataclass_fields__),
            )
            self._conn.commit()
            return run
        except (sqlite3.Error, PersistenceError, ValueError, KeyError, TypeError) as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot persist challenger run: {exc}") from exc

    def list_challenger_runs(self, underwriting_id: str) -> tuple[ChallengerRunRecord, ...]:
        try:
            rows = self._conn.execute(
                "SELECT r.* FROM challenger_runs r WHERE underwriting_id=? ORDER BY julianday(created_at), rowid",
                (underwriting_id,),
            ).fetchall()
            original = self._conn.execute(
                "SELECT version, content_hash FROM underwriting_records WHERE underwriting_id=?",
                (underwriting_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read challenger runs: {exc}") from exc
        runs = tuple(ChallengerRunRecord(**dict(row)) for row in rows)
        for run in runs:
            if (original is None
                    or (run.underwriting_version, run.underwriting_content_hash) != (original["version"], original["content_hash"])
                    or compute_content_hash(run.context_json.encode()) != run.input_content_hash
                    or compute_content_hash(run.output_json.encode()) != run.output_content_hash):
                raise StorageReadError("Challenger run failed identity/content integrity verification.")
        return runs

    def save_valuation(self, underwriting_id: str, model_version: str, result_json: str) -> str:
        if self._in_transaction:
            raise StorageWriteError("Valuation persistence requires its own transaction.")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            existing = self.get_valuation(underwriting_id, model_version)
            if existing is not None:
                if existing != result_json:
                    raise StorageWriteError("Saved valuation differs for the same underwriting/model version.")
            else:
                self._conn.execute(
                    "INSERT INTO valuation_results VALUES(?, ?, ?, ?)",
                    (underwriting_id, model_version, result_json, compute_content_hash(result_json.encode())),
                )
            self._conn.commit()
            return existing if existing is not None else result_json
        except (sqlite3.Error, PersistenceError) as exc:
            self._conn.rollback()
            raise StorageWriteError(f"Cannot persist valuation: {exc}") from exc

    def get_underwriting_evidence(
        self, security_id: int, *, cutoff: str, as_of_date: str,
    ) -> dict[str, Any]:
        """Read only evidence actually retrieved by the belief snapshot cutoff."""
        try:
            history = self._conn.execute(
                "SELECT history_id FROM fmp_canonical_histories WHERE security_id = ? "
                "AND julianday(observed_at) <= julianday(?) "
                "ORDER BY julianday(observed_at) DESC, history_id DESC LIMIT 1",
                (security_id, cutoff),
            ).fetchone()
            snapshots = self._conn.execute(
                "SELECT s.* FROM fmp_evidence_snapshots s WHERE security_id = ? "
                "AND dataset IN ('annual_analyst_estimates', 'quarterly_analyst_estimates') "
                "AND julianday(fetched_at) <= julianday(?) AND snapshot_id = ("
                "SELECT snapshot_id FROM fmp_evidence_snapshots WHERE security_id = s.security_id "
                "AND dataset = s.dataset AND julianday(fetched_at) <= julianday(?) "
                "ORDER BY julianday(fetched_at) DESC, snapshot_id DESC LIMIT 1) "
                "ORDER BY dataset", (security_id, cutoff, cutoff),
            ).fetchall()
            estimates = [
                tuple(dict(row) for row in self._conn.execute(
                    "SELECT * FROM fmp_estimates WHERE snapshot_id = ? ORDER BY target_date",
                    (snapshot["snapshot_id"],),
                ).fetchall())
                for snapshot in snapshots
            ]
            price = self._conn.execute(
                "SELECT p.*, s.fetched_at, s.content_hash, s.source_endpoint, "
                "s.request_parameters, s.raw_object_ref, s.evidence_kind FROM fmp_eod_prices p "
                "JOIN fmp_evidence_snapshots s USING(snapshot_id) "
                "WHERE p.security_id = ? AND p.market_date <= ? "
                "AND julianday(s.fetched_at) <= julianday(?) "
                "ORDER BY p.market_date DESC, julianday(s.fetched_at) DESC, s.snapshot_id DESC LIMIT 1",
                (security_id, as_of_date, cutoff),
            ).fetchone()
            sources = self._conn.execute(
                "SELECT DISTINCT s.* FROM fmp_evidence_snapshots s "
                "JOIN fmp_canonical_facts f USING(snapshot_id) WHERE f.history_id = ? "
                "ORDER BY s.dataset, s.snapshot_id",
                (history["history_id"] if history else None,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read point-in-time underwriting evidence: {exc}") from exc
        return {
            "history_id": history["history_id"] if history else None,
            "sources": tuple(dict(row) for row in sources),
            "price": dict(price) if price else None,
            "expectations": tuple(
                {"source": dict(snapshot), "rows": rows}
                for snapshot, rows in zip(snapshots, estimates, strict=True)
            ),
        }

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _commit(self) -> None:
        if not self._in_transaction:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group structured writes into one atomic unit.

        Per-call commits are deferred until clean exit; any exception rolls the
        whole group back. Used outside this context, ``save_*`` keep committing
        immediately, so Slice 4A behavior is unchanged.
        """
        if self._in_transaction:
            yield
            return
        self._in_transaction = True
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._in_transaction = False

    # -- Internal resolution -------------------------------------------------

    def _company_id(self, cik: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM companies WHERE cik = ?", (cik,)
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _require_company_id(self, cik: str) -> int:
        company_id = self._company_id(cik)
        if company_id is None:
            raise StorageWriteError(
                f"Company {cik} must be saved before dependent records."
            )
        return company_id

    def _snapshot_id(self, snapshot: SourceSnapshotRecord) -> int | None:
        company_id = self._company_id(snapshot.cik)
        if company_id is None:
            return None
        row = self._conn.execute(
            "SELECT id FROM source_snapshots WHERE company_id = ? AND "
            "source_provider = ? AND source_type = ? AND content_hash = ?",
            (
                company_id,
                snapshot.source_provider,
                snapshot.source_type,
                snapshot.content_hash,
            ),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def _require_snapshot_id(self, snapshot: SourceSnapshotRecord) -> int:
        snapshot_id = self._snapshot_id(snapshot)
        if snapshot_id is None:
            raise StorageWriteError(
                f"Source snapshot {snapshot.content_hash} for {snapshot.cik} must "
                "be saved before dependent records."
            )
        return snapshot_id

    def _latest_snapshot_id(self, cik: str) -> int | None:
        company_id = self._company_id(cik)
        if company_id is None:
            return None
        row = self._conn.execute(
            "SELECT id FROM source_snapshots WHERE company_id = ? "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (company_id,),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    # -- Writes --------------------------------------------------------------

    def save_company(self, company: CompanyRecord) -> None:
        try:
            self._conn.execute(
                "INSERT INTO companies(cik, ticker, company_name, updated_at) "
                "VALUES(?, ?, ?, datetime('now')) "
                "ON CONFLICT(cik) DO UPDATE SET ticker = excluded.ticker, "
                "company_name = excluded.company_name, updated_at = datetime('now')",
                (company.cik, company.ticker, company.company_name),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"Cannot save company {company.cik}: {exc}") from exc

    def save_source_snapshot(
        self, snapshot: SourceSnapshotRecord, *, raw_payload: bytes | None = None
    ) -> None:
        company_id = self._require_company_id(snapshot.cik)
        raw_object_ref = snapshot.raw_object_ref
        if raw_payload is not None and self._raw_store is not None:
            raw_object_ref = self._raw_store.put(snapshot.content_hash, raw_payload)
        try:
            self._conn.execute(
                "INSERT INTO source_snapshots(company_id, source_provider, "
                "source_type, fetched_at, source_uri, content_hash, raw_object_ref, "
                "processing_status) VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(company_id, source_provider, source_type, content_hash) "
                "DO NOTHING",
                (
                    company_id,
                    snapshot.source_provider,
                    snapshot.source_type,
                    snapshot.fetched_at,
                    snapshot.source_uri,
                    snapshot.content_hash,
                    raw_object_ref,
                    snapshot.processing_status,
                ),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save source snapshot for {snapshot.cik}: {exc}"
            ) from exc

    def save_reported_facts(
        self, facts: Sequence[ReportedFactRecord], *, snapshot: SourceSnapshotRecord
    ) -> None:
        snapshot_id = self._require_snapshot_id(snapshot)
        company_id = self._require_company_id(snapshot.cik)
        try:
            self._conn.executemany(
                "INSERT INTO reported_facts(company_id, snapshot_id, "
                "canonical_metric, value, unit, fact_kind, fiscal_year, "
                "period_start, period_end, concept, form, filed, accession) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_id, canonical_metric, concept, fiscal_year, "
                "period_end) DO NOTHING",
                [
                    (
                        company_id,
                        snapshot_id,
                        fact.canonical_metric,
                        fact.value,
                        fact.unit,
                        fact.fact_kind,
                        fact.fiscal_year,
                        fact.period_start,
                        fact.period_end,
                        fact.concept,
                        fact.form,
                        fact.filed,
                        fact.accession,
                    )
                    for fact in facts
                ],
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save reported facts for {snapshot.cik}: {exc}"
            ) from exc

    def save_derived_metrics(
        self, metrics: Sequence[DerivedMetricRecord], *, snapshot: SourceSnapshotRecord
    ) -> None:
        snapshot_id = self._require_snapshot_id(snapshot)
        company_id = self._require_company_id(snapshot.cik)
        try:
            self._conn.executemany(
                "INSERT INTO derived_metrics(company_id, snapshot_id, metric_name, "
                "fiscal_year, value_real, value_int, unit, calculation_version, "
                "computed_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_id, metric_name, fiscal_year, "
                "calculation_version) DO NOTHING",
                [
                    (
                        company_id,
                        snapshot_id,
                        metric.metric_name,
                        metric.fiscal_year,
                        metric.value_real,
                        metric.value_int,
                        metric.unit,
                        metric.calculation_version,
                        metric.computed_at,
                    )
                    for metric in metrics
                ],
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save derived metrics for {snapshot.cik}: {exc}"
            ) from exc

    def save_analysis_result(
        self, result: AnalysisResultRecord, *, snapshot: SourceSnapshotRecord
    ) -> None:
        snapshot_id = self._require_snapshot_id(snapshot)
        company_id = self._require_company_id(snapshot.cik)
        try:
            cursor = self._conn.execute(
                "INSERT INTO analysis_results(company_id, snapshot_id, analysis_type, "
                "analysis_period, classification, analysis_rule_version, computed_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_id, analysis_type, analysis_period, "
                "analysis_rule_version) DO NOTHING",
                (
                    company_id,
                    snapshot_id,
                    result.analysis_type,
                    result.analysis_period,
                    result.classification,
                    result.analysis_rule_version,
                    result.computed_at,
                ),
            )
            if cursor.rowcount:
                analysis_result_id = int(cursor.lastrowid or 0)
                self._conn.executemany(
                    "INSERT INTO analysis_drivers(analysis_result_id, position, code, "
                    "category) VALUES(?, ?, ?, ?) "
                    "ON CONFLICT(analysis_result_id, position) DO NOTHING",
                    [
                        (analysis_result_id, driver.position, driver.code, driver.category)
                        for driver in result.drivers
                    ],
                )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save analysis result for {snapshot.cik}: {exc}"
            ) from exc

    def save_coverage(
        self, coverage: Sequence[CoverageResultRecord], *, snapshot: SourceSnapshotRecord
    ) -> None:
        snapshot_id = self._require_snapshot_id(snapshot)
        company_id = self._require_company_id(snapshot.cik)
        try:
            self._conn.executemany(
                "INSERT INTO coverage_results(company_id, snapshot_id, subject_kind, "
                "subject, state, reason, blocking_input) VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_id, subject_kind, subject) DO NOTHING",
                [
                    (
                        company_id,
                        snapshot_id,
                        result.subject_kind,
                        result.subject,
                        result.state,
                        result.reason,
                        result.blocking_input,
                    )
                    for result in coverage
                ],
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save coverage for {snapshot.cik}: {exc}"
            ) from exc

    # -- Reads ---------------------------------------------------------------

    def get_company(self, cik: str) -> CompanyRecord | None:
        try:
            row = self._conn.execute(
                "SELECT cik, ticker, company_name FROM companies WHERE cik = ?",
                (cik,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read company {cik}: {exc}") from exc
        if row is None:
            return None
        return CompanyRecord(
            cik=row["cik"], ticker=row["ticker"], company_name=row["company_name"]
        )

    def list_companies(self) -> tuple[CompanyRecord, ...]:
        try:
            rows = self._conn.execute(
                "SELECT cik, ticker, company_name FROM companies ORDER BY ticker ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot list companies: {exc}") from exc
        return tuple(
            CompanyRecord(
                cik=row["cik"], ticker=row["ticker"], company_name=row["company_name"]
            )
            for row in rows
        )

    def _metric_from_row(self, row: sqlite3.Row) -> DerivedMetricRecord:
        return DerivedMetricRecord(
            cik=row["cik"],
            metric_name=row["metric_name"],
            fiscal_year=int(row["fiscal_year"]),
            value_int=row["value_int"],
            value_real=row["value_real"],
            unit=row["unit"],
            calculation_version=row["calculation_version"],
            computed_at=row["computed_at"],
        )

    def get_metric_history(
        self, cik: str, metric: str, *, limit: int | None = None
    ) -> tuple[DerivedMetricRecord, ...]:
        snapshot_id = self._latest_snapshot_id(cik)
        if snapshot_id is None:
            return ()
        try:
            rows = self._conn.execute(
                "SELECT c.cik AS cik, m.metric_name, m.fiscal_year, m.value_int, "
                "m.value_real, m.unit, m.calculation_version, m.computed_at "
                "FROM derived_metrics m JOIN companies c ON c.id = m.company_id "
                "WHERE c.cik = ? AND m.metric_name = ? AND m.snapshot_id = ? "
                "ORDER BY m.fiscal_year ASC",
                (cik, metric, snapshot_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read metric history for {cik}/{metric}: {exc}"
            ) from exc
        records = tuple(self._metric_from_row(row) for row in rows)
        if limit is not None and len(records) > limit:
            records = records[-limit:]
        return records

    def get_fact_provenance(
        self, cik: str, canonical_metric: str, fiscal_year: int
    ) -> ReportedFactRecord | None:
        snapshot_id = self._latest_snapshot_id(cik)
        if snapshot_id is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT c.cik AS cik, f.canonical_metric, f.value, f.unit, "
                "f.fact_kind, f.fiscal_year, f.period_start, f.period_end, f.concept, "
                "f.form, f.filed, f.accession FROM reported_facts f "
                "JOIN companies c ON c.id = f.company_id "
                "WHERE c.cik = ? AND f.canonical_metric = ? AND f.fiscal_year = ? "
                "AND f.snapshot_id = ?",
                (cik, canonical_metric, fiscal_year, snapshot_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read provenance for {cik}/{canonical_metric}: {exc}"
            ) from exc
        if row is None:
            return None
        return ReportedFactRecord(
            cik=row["cik"],
            canonical_metric=row["canonical_metric"],
            value=int(row["value"]),
            unit=row["unit"],
            fact_kind=row["fact_kind"],
            fiscal_year=int(row["fiscal_year"]),
            period_end=row["period_end"],
            period_start=row["period_start"],
            concept=row["concept"],
            form=row["form"],
            filed=row["filed"],
            accession=row["accession"],
        )

    def get_latest_summary(self, cik: str) -> AnalysisResultRecord | None:
        snapshot_id = self._latest_snapshot_id(cik)
        if snapshot_id is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT r.id AS id, c.cik AS cik, r.analysis_type, r.analysis_period, "
                "r.classification, r.analysis_rule_version, r.computed_at "
                "FROM analysis_results r JOIN companies c ON c.id = r.company_id "
                "WHERE c.cik = ? AND r.analysis_type = 'economic_value_summary' "
                "AND r.snapshot_id = ?",
                (cik, snapshot_id),
            ).fetchone()
            if row is None:
                return None
            driver_rows = self._conn.execute(
                "SELECT position, code, category FROM analysis_drivers "
                "WHERE analysis_result_id = ? ORDER BY position ASC",
                (int(row["id"]),),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read latest summary for {cik}: {exc}") from exc
        drivers = tuple(
            AnalysisDriverRecord(
                position=int(d["position"]), code=d["code"], category=d["category"]
            )
            for d in driver_rows
        )
        return AnalysisResultRecord(
            cik=row["cik"],
            analysis_type=row["analysis_type"],
            analysis_period=row["analysis_period"],
            classification=row["classification"],
            drivers=drivers,
            analysis_rule_version=row["analysis_rule_version"],
            computed_at=row["computed_at"],
        )

    def get_company_coverage(self, cik: str) -> tuple[CoverageResultRecord, ...]:
        snapshot_id = self._latest_snapshot_id(cik)
        if snapshot_id is None:
            return ()
        try:
            rows = self._conn.execute(
                "SELECT c.cik AS cik, v.subject_kind, v.subject, v.state, v.reason, "
                "v.blocking_input FROM coverage_results v "
                "JOIN companies c ON c.id = v.company_id "
                "WHERE c.cik = ? AND v.snapshot_id = ? "
                "ORDER BY v.subject_kind ASC, v.subject ASC",
                (cik, snapshot_id),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read coverage for {cik}: {exc}") from exc
        return tuple(
            CoverageResultRecord(
                cik=row["cik"],
                subject_kind=row["subject_kind"],
                subject=row["subject"],
                state=row["state"],
                reason=row["reason"],
                blocking_input=row["blocking_input"],
            )
            for row in rows
        )

    def get_latest_metric_across_companies(
        self, metric: str, ciks: Sequence[str]
    ) -> dict[str, DerivedMetricRecord]:
        result: dict[str, DerivedMetricRecord] = {}
        for cik in ciks:
            history = self.get_metric_history(cik, metric)
            if history:
                result[cik] = history[-1]
        return result

    # -- Snapshot identity / idempotency support -----------------------------

    def get_source_snapshot(
        self, cik: str, content_hash: str
    ) -> SourceSnapshotRecord | None:
        company_id = self._company_id(cik)
        if company_id is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT source_provider, source_type, fetched_at, source_uri, "
                "content_hash, raw_object_ref, processing_status "
                "FROM source_snapshots WHERE company_id = ? AND content_hash = ?",
                (company_id, content_hash),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read source snapshot for {cik}: {exc}"
            ) from exc
        if row is None:
            return None
        return SourceSnapshotRecord(
            cik=cik,
            source_provider=row["source_provider"],
            source_type=row["source_type"],
            fetched_at=row["fetched_at"],
            source_uri=row["source_uri"],
            content_hash=row["content_hash"],
            raw_object_ref=row["raw_object_ref"],
            processing_status=row["processing_status"],
        )

    def source_snapshot_exists(self, cik: str, content_hash: str) -> bool:
        return self.get_source_snapshot(cik, content_hash) is not None

    def get_latest_source_snapshot(self, cik: str) -> SourceSnapshotRecord | None:
        """The most recently fetched snapshot for a company, or None if there is none.

        Ordered by ``fetched_at`` and then by insertion order, so a re-fetch that
        produced an identical payload on the same timestamp still resolves to one
        deterministic record.
        """
        company_id = self._company_id(cik)
        if company_id is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT source_provider, source_type, fetched_at, source_uri, "
                "content_hash, raw_object_ref, processing_status "
                "FROM source_snapshots WHERE company_id = ? "
                "ORDER BY fetched_at DESC, id DESC LIMIT 1",
                (company_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read the latest source snapshot for {cik}: {exc}"
            ) from exc
        if row is None:
            return None
        return SourceSnapshotRecord(
            cik=cik,
            source_provider=row["source_provider"],
            source_type=row["source_type"],
            fetched_at=row["fetched_at"],
            source_uri=row["source_uri"],
            content_hash=row["content_hash"],
            raw_object_ref=row["raw_object_ref"],
            processing_status=row["processing_status"],
        )

    def snapshot_matches_versions(
        self,
        cik: str,
        content_hash: str,
        *,
        calculation_version: str,
        analysis_rule_version: str,
    ) -> bool:
        company_id = self._company_id(cik)
        if company_id is None:
            return False
        try:
            row = self._conn.execute(
                "SELECT s.id FROM source_snapshots s WHERE s.company_id = ? "
                "AND s.content_hash = ? AND EXISTS (SELECT 1 FROM derived_metrics m "
                "WHERE m.snapshot_id = s.id AND m.calculation_version = ?) "
                "AND EXISTS (SELECT 1 FROM analysis_results r "
                "WHERE r.snapshot_id = s.id AND r.analysis_rule_version = ?)",
                (company_id, content_hash, calculation_version, analysis_rule_version),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read snapshot versions for {cik}: {exc}"
            ) from exc
        return row is not None

    def set_snapshot_processing_status(
        self, cik: str, content_hash: str, status: str
    ) -> None:
        company_id = self._require_company_id(cik)
        try:
            self._conn.execute(
                "UPDATE source_snapshots SET processing_status = ? "
                "WHERE company_id = ? AND content_hash = ?",
                (status, company_id, content_hash),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot update processing status for {cik}: {exc}"
            ) from exc

    def start_universe_refresh_run(
        self, run: UniverseRefreshRunRecord
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO universe_refresh_runs(run_id, started_at, status, "
                "requested_symbols) VALUES(?, ?, 'RUNNING', ?)",
                (
                    run.run_id,
                    run.started_at,
                    json.dumps(run.requested_symbols, separators=(",", ":")),
                ),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot start universe refresh run {run.run_id}: {exc}"
            ) from exc

    def finish_universe_refresh_run(
        self,
        run_id: str,
        *,
        status: str,
        completed_at: str,
        snapshot_id: int | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError(f"Invalid completed refresh-run status: {status!r}.")
        try:
            cursor = self._conn.execute(
                "UPDATE universe_refresh_runs SET status = ?, completed_at = ?, "
                "snapshot_id = ?, error = ? WHERE run_id = ? AND status = 'RUNNING'",
                (status, completed_at, snapshot_id, error, run_id),
            )
            if cursor.rowcount != 1:
                raise StorageWriteError(
                    f"Refresh run {run_id} is missing or is no longer running."
                )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot finish universe refresh run {run_id}: {exc}"
            ) from exc

    def save_universe_snapshot(
        self,
        snapshot: UniverseSnapshotRecord,
        members: Sequence[UniverseConstituentRecord],
        *,
        raw_payload: bytes,
        state_symbols: Sequence[str],
        datasets: Sequence[str],
        created_at: str,
    ) -> tuple[int, bool, int]:
        """Persist raw evidence, immutable membership, security identities, and pending work."""
        if compute_content_hash(raw_payload) != snapshot.content_hash:
            raise StorageWriteError(
                "Universe snapshot content hash does not match its raw payload."
            )
        raw_object_ref = snapshot.raw_object_ref
        if self._raw_store is not None:
            raw_object_ref = self._raw_store.put(snapshot.content_hash, raw_payload)

        wanted = set(state_symbols)
        if not wanted.issubset({member.symbol for member in members}):
            raise StorageWriteError(
                "Refresh state requested for a symbol outside the universe snapshot."
            )
        try:
            with self.transaction():
                self._conn.execute(
                    "INSERT INTO universe_snapshots(provider, observed_at, source_uri, "
                    "content_hash, raw_object_ref) VALUES(?, ?, ?, ?, ?) "
                    "ON CONFLICT(provider, content_hash) DO NOTHING",
                    (
                        snapshot.provider,
                        snapshot.observed_at,
                        snapshot.source_uri,
                        snapshot.content_hash,
                        raw_object_ref,
                    ),
                )
                snapshot_row = self._conn.execute(
                    "SELECT snapshot_id FROM universe_snapshots "
                    "WHERE provider = ? AND content_hash = ?",
                    (snapshot.provider, snapshot.content_hash),
                ).fetchone()
                if snapshot_row is None:
                    raise StorageWriteError(
                        "Universe snapshot insert did not produce a readable row."
                    )
                snapshot_id = int(snapshot_row["snapshot_id"])
                inserted_snapshot = self._conn.execute(
                    "SELECT COUNT(*) AS count FROM universe_members "
                    "WHERE snapshot_id = ?",
                    (snapshot_id,),
                ).fetchone()["count"] == 0
                if inserted_snapshot:
                    for member in members:
                        self._conn.execute(
                            "INSERT INTO securities(symbol, name, cik, created_at, "
                            "updated_at) VALUES(?, ?, ?, ?, ?) "
                            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, "
                            "cik = excluded.cik, updated_at = excluded.updated_at",
                            (
                                member.symbol,
                                member.name,
                                member.cik,
                                created_at,
                                created_at,
                            ),
                        )
                        security_id_row = self._conn.execute(
                            "SELECT security_id FROM securities WHERE symbol = ?",
                            (member.symbol,),
                        ).fetchone()
                        if security_id_row is None:
                            raise StorageWriteError(
                                f"Cannot resolve security identity for {member.symbol}."
                            )
                        security_id = int(security_id_row["security_id"])
                        self._conn.execute(
                            "INSERT INTO universe_members(snapshot_id, security_id, "
                            "symbol, name, cik, sector, subsector) "
                            "VALUES(?, ?, ?, ?, ?, ?, ?)",
                            (
                                snapshot_id,
                                security_id,
                                member.symbol,
                                member.name,
                                member.cik,
                                member.sector,
                                member.subsector,
                            ),
                        )
                else:
                    for member in members:
                        self._conn.execute(
                            "INSERT INTO securities(symbol, name, cik, created_at, "
                            "updated_at) VALUES(?, ?, ?, ?, ?) "
                            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, "
                            "cik = excluded.cik, updated_at = excluded.updated_at",
                            (
                                member.symbol,
                                member.name,
                                member.cik,
                                created_at,
                                created_at,
                            ),
                        )

                state_count = 0
                for symbol in state_symbols:
                    row = self._conn.execute(
                        "SELECT security_id FROM securities WHERE symbol = ?",
                        (symbol,),
                    ).fetchone()
                    if row is None:
                        raise StorageWriteError(
                            f"Cannot resolve security refresh state for {symbol}."
                        )
                    security_id = int(row["security_id"])
                    for dataset in datasets:
                        cursor = self._conn.execute(
                            "INSERT INTO security_refresh_state("
                            "security_id, dataset, status, updated_at) "
                            "VALUES(?, ?, 'PENDING', ?) "
                            "ON CONFLICT(security_id, dataset) DO UPDATE SET "
                            "updated_at = excluded.updated_at",
                            (security_id, dataset, created_at),
                        )
                        state_count += cursor.rowcount
                return snapshot_id, inserted_snapshot, state_count
        except StorageWriteError:
            raise
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save universe snapshot {snapshot.content_hash}: {exc}"
            ) from exc

    def get_universe_snapshot(
        self, provider: str, content_hash: str
    ) -> UniverseSnapshotRecord | None:
        try:
            row = self._conn.execute(
                "SELECT snapshot_id, provider, observed_at, source_uri, content_hash, "
                "raw_object_ref FROM universe_snapshots "
                "WHERE provider = ? AND content_hash = ?",
                (provider, content_hash),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read universe snapshot {provider}/{content_hash}: {exc}"
            ) from exc
        if row is None:
            return None
        return UniverseSnapshotRecord(
            snapshot_id=int(row["snapshot_id"]),
            provider=row["provider"],
            observed_at=row["observed_at"],
            source_uri=row["source_uri"],
            content_hash=row["content_hash"],
            raw_object_ref=row["raw_object_ref"],
        )

    def get_latest_universe_snapshot(
        self, provider: str
    ) -> UniverseSnapshotRecord | None:
        try:
            row = self._conn.execute(
                "SELECT snapshot_id, provider, observed_at, source_uri, content_hash, "
                "raw_object_ref FROM universe_snapshots WHERE provider = ? "
                "ORDER BY observed_at DESC, snapshot_id DESC LIMIT 1",
                (provider,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read latest universe snapshot for {provider}: {exc}"
            ) from exc
        if row is None:
            return None
        return UniverseSnapshotRecord(
            snapshot_id=int(row["snapshot_id"]),
            provider=row["provider"],
            observed_at=row["observed_at"],
            source_uri=row["source_uri"],
            content_hash=row["content_hash"],
            raw_object_ref=row["raw_object_ref"],
        )

    def list_universe_members(
        self, snapshot_id: int
    ) -> tuple[UniverseConstituentRecord, ...]:
        try:
            rows = self._conn.execute(
                "SELECT symbol, name, cik, sector, subsector FROM universe_members "
                "WHERE snapshot_id = ? ORDER BY symbol",
                (snapshot_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot list members for universe snapshot {snapshot_id}: {exc}"
            ) from exc
        return tuple(
            UniverseConstituentRecord(
                symbol=row["symbol"],
                name=row["name"],
                cik=row["cik"],
                sector=row["sector"],
                subsector=row["subsector"],
            )
            for row in rows
        )

    def list_securities(self) -> tuple[SecurityRecord, ...]:
        try:
            rows = self._conn.execute(
                "SELECT security_id, symbol, name, cik FROM securities "
                "ORDER BY symbol"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot list securities: {exc}") from exc
        return tuple(
            SecurityRecord(
                security_id=int(row["security_id"]),
                symbol=row["symbol"],
                name=row["name"],
                cik=row["cik"],
            )
            for row in rows
        )

    def list_security_refresh_state(
        self, security_id: int | None = None
    ) -> tuple[SecurityRefreshStateRecord, ...]:
        query = (
            "SELECT security_id, dataset, status, last_attempt_at, last_error "
            "FROM security_refresh_state"
        )
        params: tuple[int, ...] = ()
        if security_id is not None:
            query += " WHERE security_id = ?"
            params = (security_id,)
        query += " ORDER BY security_id, dataset"
        try:
            rows = self._conn.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot list security refresh state: {exc}") from exc
        return _resolve_aggregate_refresh_states(
            tuple(
                SecurityRefreshStateRecord(
                    security_id=int(row["security_id"]),
                    dataset=row["dataset"],
                    status=row["status"],
                    last_attempt_at=row["last_attempt_at"],
                    last_error=row["last_error"],
                )
                for row in rows
            )
        )

    def get_security_refresh_state(
        self, security_id: int, dataset: str
    ) -> SecurityRefreshStateRecord | None:
        if dataset in _AGGREGATE_REFRESH_DATASETS:
            return next(
                (
                    state
                    for state in self.list_security_refresh_state(security_id)
                    if state.dataset == dataset
                ),
                None,
            )
        try:
            row = self._conn.execute(
                "SELECT security_id, dataset, status, last_attempt_at, last_error "
                "FROM security_refresh_state WHERE security_id = ? AND dataset = ?",
                (security_id, dataset),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read refresh state for security {security_id}/{dataset}: {exc}"
            ) from exc
        if row is None:
            return None
        return SecurityRefreshStateRecord(
            security_id=int(row["security_id"]),
            dataset=row["dataset"],
            status=row["status"],
            last_attempt_at=row["last_attempt_at"],
            last_error=row["last_error"],
        )

    def get_universe_refresh_run(
        self, run_id: str
    ) -> UniverseRefreshRunRecord | None:
        try:
            row = self._conn.execute(
                "SELECT run_id, started_at, completed_at, status, snapshot_id, "
                "requested_symbols, error FROM universe_refresh_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read universe refresh run {run_id}: {exc}"
            ) from exc
        if row is None:
            return None
        return UniverseRefreshRunRecord(
            run_id=row["run_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            snapshot_id=row["snapshot_id"],
            requested_symbols=tuple(json.loads(row["requested_symbols"])),
            error=row["error"],
        )

    def universe_security_ids(
        self, snapshot_id: int
    ) -> dict[str, int]:
        try:
            rows = self._conn.execute(
                "SELECT symbol, security_id FROM universe_members "
                "WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot resolve security IDs for universe snapshot {snapshot_id}: {exc}"
            ) from exc
        return {row["symbol"]: int(row["security_id"]) for row in rows}

    def update_security_refresh_state(
        self,
        security_id: int,
        dataset: str,
        *,
        status: str,
        updated_at: str,
        last_error: str | None = None,
    ) -> None:
        if status not in {
            "PENDING",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "PARTIAL",
            "UNSUPPORTED",
        }:
            raise ValueError(f"Invalid security refresh status: {status!r}.")
        try:
            self._conn.execute(
                "INSERT INTO security_refresh_state(security_id, dataset, status, "
                "last_attempt_at, last_error, updated_at) VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(security_id, dataset) DO UPDATE SET "
                "status = excluded.status, last_attempt_at = excluded.last_attempt_at, "
                "last_error = excluded.last_error, updated_at = excluded.updated_at",
                (security_id, dataset, status, updated_at, last_error, updated_at),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot update refresh state for security {security_id}/{dataset}: {exc}"
            ) from exc

    def get_latest_fmp_evidence_snapshot(
        self, security_id: int, dataset: str
    ) -> FmpEvidenceSnapshotRecord | None:
        try:
            row = self._conn.execute(
                "SELECT snapshot_id, security_id, dataset, period_type, "
                "source_endpoint, request_parameters, fetched_at, content_hash, "
                "raw_object_ref, evidence_kind FROM fmp_evidence_snapshots "
                "WHERE security_id = ? AND dataset = ? "
                "ORDER BY fetched_at DESC, snapshot_id DESC LIMIT 1",
                (security_id, dataset),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageReadError(
                f"Cannot read latest FMP evidence for security {security_id}/{dataset}: {exc}"
            ) from exc
        if row is None:
            return None
        return FmpEvidenceSnapshotRecord(
            snapshot_id=int(row["snapshot_id"]),
            security_id=int(row["security_id"]),
            dataset=row["dataset"],
            period_type=row["period_type"],
            source_endpoint=row["source_endpoint"],
            request_parameters=row["request_parameters"],
            fetched_at=row["fetched_at"],
            content_hash=row["content_hash"],
            raw_object_ref=row["raw_object_ref"],
            evidence_kind=row["evidence_kind"],
        )

    def save_fmp_evidence_snapshot(
        self,
        snapshot: FmpEvidenceSnapshotRecord,
        *,
        raw_payload: bytes,
    ) -> tuple[int, bool, FmpEvidenceSnapshotRecord]:
        if compute_content_hash(raw_payload) != snapshot.content_hash:
            raise StorageWriteError(
                "FMP evidence content hash does not match its raw payload."
            )
        raw_object_ref = snapshot.raw_object_ref
        if self._raw_store is not None:
            raw_object_ref = self._raw_store.put(snapshot.content_hash, raw_payload)
        try:
            with self.transaction():
                self._conn.execute(
                    "INSERT INTO fmp_evidence_snapshots(security_id, dataset, "
                    "period_type, source_endpoint, request_parameters, fetched_at, "
                    "content_hash, raw_object_ref, evidence_kind) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(security_id, dataset, request_parameters, content_hash, "
                    "fetched_at) "
                    "DO NOTHING",
                    (
                        snapshot.security_id,
                        snapshot.dataset,
                        snapshot.period_type,
                        snapshot.source_endpoint,
                        snapshot.request_parameters,
                        snapshot.fetched_at,
                        snapshot.content_hash,
                        raw_object_ref,
                        snapshot.evidence_kind,
                    ),
                )
                row = self._conn.execute(
                    "SELECT snapshot_id, fetched_at, raw_object_ref, evidence_kind "
                    "FROM fmp_evidence_snapshots WHERE "
                    "security_id = ? AND dataset = ? AND request_parameters = ? "
                    "AND content_hash = ? AND fetched_at = ?",
                    (
                        snapshot.security_id,
                        snapshot.dataset,
                        snapshot.request_parameters,
                        snapshot.content_hash,
                        snapshot.fetched_at,
                    ),
                ).fetchone()
                if row is None:
                    raise StorageWriteError(
                        f"Cannot resolve FMP evidence snapshot for "
                        f"security {snapshot.security_id}/{snapshot.dataset}."
                    )
                inserted = self._conn.execute(
                    "SELECT changes() AS changed"
                ).fetchone()["changed"] == 1
                stored = FmpEvidenceSnapshotRecord(
                    snapshot_id=int(row["snapshot_id"]),
                    security_id=snapshot.security_id,
                    dataset=snapshot.dataset,
                    period_type=snapshot.period_type,
                    source_endpoint=snapshot.source_endpoint,
                    request_parameters=snapshot.request_parameters,
                    fetched_at=row["fetched_at"],
                    content_hash=snapshot.content_hash,
                    raw_object_ref=row["raw_object_ref"],
                    evidence_kind=row["evidence_kind"],
                )
                return int(row["snapshot_id"]), inserted, stored
        except StorageWriteError:
            raise
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save FMP evidence for security {snapshot.security_id}/"
                f"{snapshot.dataset}: {exc}"
            ) from exc

    def get_raw_snapshot(self, content_hash: str) -> bytes:
        if self._raw_store is None:
            raise StorageReadError(
                "Raw FMP evidence cannot be loaded because no raw snapshot store is configured."
            )
        return self._raw_store.get(content_hash)

    def list_fmp_universe_evidence(self) -> tuple[dict[str, Any], ...]:
        """Read current members and cache-invalidating evidence metadata in bulk."""
        try:
            rows = self._conn.execute(
                """
                SELECT m.security_id, m.symbol, m.name, m.cik, u.observed_at,
                       h.history_id, h.input_hash, h.observed_at AS history_observed_at
                FROM universe_members m
                JOIN universe_snapshots u ON u.snapshot_id = m.snapshot_id
                LEFT JOIN fmp_canonical_histories h ON h.history_id = (
                    SELECT history_id FROM fmp_canonical_histories
                    WHERE security_id = m.security_id
                    ORDER BY observed_at DESC, history_id DESC LIMIT 1
                )
                WHERE m.snapshot_id = (
                    SELECT snapshot_id FROM universe_snapshots WHERE provider = 'fmp'
                    ORDER BY observed_at DESC, snapshot_id DESC LIMIT 1
                )
                ORDER BY m.symbol
                """
            ).fetchall()
            evidence = self._conn.execute(
                "SELECT security_id, snapshot_id, dataset, fetched_at, content_hash "
                "FROM fmp_evidence_snapshots ORDER BY security_id, snapshot_id"
            ).fetchall()
            states = self.list_security_refresh_state()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read FMP universe evidence: {exc}") from exc
        signatures: dict[int, list[str]] = {}
        for item in evidence:
            signatures.setdefault(int(item["security_id"]), []).append(
                f"{item['snapshot_id']}:{item['dataset']}:{item['fetched_at']}:{item['content_hash']}"
            )
        for state in states:
            signatures.setdefault(state.security_id, []).append(
                f"{state.dataset}:{state.status}:{state.last_attempt_at}:{state.last_error}"
            )
        return tuple(
            {
                **dict(row),
                "evidence_hash": compute_content_hash(
                    "|".join(
                        [
                            str(row["input_hash"]),
                            *signatures.get(row["security_id"], []),
                        ]
                    ).encode()
                ),
            }
            for row in rows
        )

    def get_fmp_canonical_history(self, history_id: int) -> FmpCanonicalHistoryRecord:
        try:
            row = self._conn.execute(
                "SELECT * FROM fmp_canonical_histories WHERE history_id = ?",
                (history_id,),
            ).fetchone()
            if row is None:
                raise StorageReadError(
                    f"FMP canonical history {history_id} is missing."
                )
            facts = self._conn.execute(
                "SELECT * FROM fmp_canonical_facts WHERE history_id = ? "
                "ORDER BY metric, fiscal_year DESC",
                (history_id,),
            ).fetchall()
            coverage = self._conn.execute(
                "SELECT metric, status, reason FROM fmp_metric_coverage WHERE history_id = ?",
                (history_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read FMP canonical history: {exc}") from exc
        return FmpCanonicalHistoryRecord(
            security_id=int(row["security_id"]),
            history_id=history_id,
            input_hash=row["input_hash"],
            observed_at=row["observed_at"],
            max_years=int(row["max_years"]),
            facts=tuple(
                FmpCanonicalFactRecord(
                    metric=fact["metric"],
                    value=fact["value"],
                    unit=fact["unit"],
                    fiscal_year=fact["fiscal_year"],
                    period_end=fact["period_end"],
                    provider_field=fact["provider_field"],
                    snapshot_id=fact["snapshot_id"],
                )
                for fact in facts
            ),
            coverage=tuple(
                FmpCanonicalCoverageRecord(
                    metric=item["metric"], status=item["status"], reason=item["reason"]
                )
                for item in coverage
            ),
        )

    def get_fmp_security_evidence(self, security_id: int) -> dict[str, Any]:
        """Latest dataset provenance plus separately persisted prices and expectations."""
        try:
            snapshots = self._conn.execute(
                """
                SELECT s.* FROM fmp_evidence_snapshots s
                WHERE s.security_id = ? AND s.snapshot_id = (
                    SELECT snapshot_id FROM fmp_evidence_snapshots
                    WHERE security_id = s.security_id AND dataset = s.dataset
                    ORDER BY fetched_at DESC, snapshot_id DESC LIMIT 1
                ) ORDER BY s.dataset
                """,
                (security_id,),
            ).fetchall()
            prices = self._conn.execute(
                "SELECT p.*, s.fetched_at, s.source_endpoint, s.content_hash "
                "FROM fmp_eod_prices p JOIN fmp_evidence_snapshots s USING(snapshot_id) "
                "WHERE p.security_id = ? ORDER BY p.market_date DESC, s.fetched_at DESC LIMIT 1",
                (security_id,),
            ).fetchall()
            estimates = self._conn.execute(
                """
                SELECT e.*, s.dataset, s.fetched_at, s.content_hash FROM fmp_estimates e
                JOIN fmp_evidence_snapshots s USING(snapshot_id)
                WHERE s.security_id = ? AND s.snapshot_id = (
                    SELECT snapshot_id FROM fmp_evidence_snapshots
                    WHERE security_id = s.security_id AND dataset = s.dataset
                    ORDER BY fetched_at DESC, snapshot_id DESC LIMIT 1
                ) ORDER BY s.dataset, e.target_date
                """,
                (security_id,),
            ).fetchall()
            annual_sources = self._conn.execute(
                """
                SELECT DISTINCT s.* FROM fmp_evidence_snapshots s
                JOIN fmp_canonical_facts f ON f.snapshot_id = s.snapshot_id
                WHERE f.history_id = (
                    SELECT history_id FROM fmp_canonical_histories
                    WHERE security_id = ?
                    ORDER BY observed_at DESC, history_id DESC LIMIT 1
                ) ORDER BY s.dataset
                """,
                (security_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot read FMP security evidence: {exc}") from exc
        return {
            "snapshots": tuple(dict(row) for row in snapshots),
            "prices": tuple(dict(row) for row in prices),
            "estimates": tuple(dict(row) for row in estimates),
            "annual_sources": tuple(dict(row) for row in annual_sources),
        }

    def save_fmp_canonical_history(
        self, history: FmpCanonicalHistoryRecord
    ) -> tuple[int, bool]:
        try:
            with self.transaction():
                self._conn.execute(
                    "INSERT INTO fmp_canonical_histories(security_id, provider, "
                    "period_type, input_hash, observed_at, max_years) "
                    "VALUES(?, 'fmp', 'annual', ?, ?, ?) "
                    "ON CONFLICT(security_id, provider, period_type, input_hash) "
                    "DO NOTHING",
                    (
                        history.security_id,
                        history.input_hash,
                        history.observed_at,
                        history.max_years,
                    ),
                )
                row = self._conn.execute(
                    "SELECT history_id FROM fmp_canonical_histories "
                    "WHERE security_id = ? AND provider = 'fmp' "
                    "AND period_type = 'annual' AND input_hash = ?",
                    (history.security_id, history.input_hash),
                ).fetchone()
                if row is None:
                    raise StorageWriteError("Cannot resolve FMP canonical history.")
                history_id = int(row["history_id"])
                inserted_history = self._conn.execute(
                    "SELECT changes() AS changed"
                ).fetchone()["changed"] == 1
                if inserted_history:
                    self._conn.executemany(
                        "INSERT INTO fmp_canonical_facts(history_id, snapshot_id, metric, "
                        "fiscal_year, period_end, value, unit, provider, provider_field) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, 'fmp', ?)",
                        [
                            (
                                history_id,
                                fact.snapshot_id,
                                fact.metric,
                                fact.fiscal_year,
                                fact.period_end,
                                fact.value,
                                fact.unit,
                                fact.provider_field,
                            )
                            for fact in history.facts
                        ],
                    )
                    self._conn.executemany(
                        "INSERT INTO fmp_metric_coverage(history_id, metric, status, "
                        "reason) VALUES(?, ?, ?, ?)",
                        [
                            (history_id, metric.metric, metric.status, metric.reason)
                            for metric in history.coverage
                        ],
                    )
                return history_id, inserted_history
        except StorageWriteError:
            raise
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save annual FMP canonical history for security "
                f"{history.security_id}: {exc}"
            ) from exc

    def save_fmp_eod_price(self, price: FmpEodPriceRecord) -> None:
        try:
            self._conn.execute(
                "INSERT INTO fmp_eod_prices(snapshot_id, security_id, market_date, "
                "close, source_field, currency) VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_id) DO NOTHING",
                (
                    price.snapshot_id,
                    price.security_id,
                    price.market_date,
                    price.close,
                    price.source_field,
                    price.currency,
                ),
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"Cannot save EOD price for security {price.security_id}: {exc}"
            ) from exc

    def save_fmp_estimates(
        self, estimates: Sequence[FmpEstimateRecord]
    ) -> None:
        target_dates = [estimate.target_date for estimate in estimates]
        if len(set(target_dates)) != len(target_dates):
            raise StorageWriteError(
                "Duplicate target date in an FMP estimate snapshot."
            )
        try:
            self._conn.executemany(
                "INSERT OR IGNORE INTO fmp_estimates(snapshot_id, target_date, revenue_low, "
                "revenue_average, revenue_high, revenue_analyst_count, eps_low, "
                "eps_average, eps_high, eps_analyst_count, evidence_kind) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        estimate.snapshot_id,
                        estimate.target_date,
                        estimate.revenue_low,
                        estimate.revenue_average,
                        estimate.revenue_high,
                        estimate.revenue_analyst_count,
                        estimate.eps_low,
                        estimate.eps_average,
                        estimate.eps_high,
                        estimate.eps_analyst_count,
                        estimate.evidence_kind,
                    )
                    for estimate in estimates
                ],
            )
            self._commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"Cannot save FMP estimates: {exc}") from exc

    def list_evidence_status_counts(
        self, security_ids: Sequence[int] | None = None
    ) -> dict[str, dict[str, int]]:
        query = (
            "SELECT security_id, dataset, status, last_attempt_at, last_error "
            "FROM security_refresh_state"
        )
        params: tuple[int, ...] = ()
        if security_ids is not None:
            if not security_ids:
                return {}
            placeholders = ",".join("?" for _ in security_ids)
            query += f" WHERE security_id IN ({placeholders})"
            params = tuple(security_ids)
        query += " ORDER BY security_id, dataset"
        try:
            rows = self._conn.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise StorageReadError(f"Cannot summarize evidence status: {exc}") from exc
        result: dict[str, dict[str, int]] = {}
        records = tuple(
            SecurityRefreshStateRecord(
                security_id=int(row["security_id"]),
                dataset=row["dataset"],
                status=row["status"],
                last_attempt_at=row["last_attempt_at"],
                last_error=row["last_error"],
            )
            for row in rows
        )
        for record in _resolve_aggregate_refresh_states(records):
            states = result.setdefault(record.dataset, {})
            states[record.status] = states.get(record.status, 0) + 1
        return result

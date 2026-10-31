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
from typing import Protocol, Self

from owner_lens.persistence.errors import (
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
    CompanyRecord,
    CoverageResultRecord,
    DerivedMetricRecord,
    ReportedFactRecord,
    SecurityRecord,
    SecurityRefreshStateRecord,
    SourceSnapshotRecord,
    UniverseConstituentRecord,
    UniverseRefreshRunRecord,
    UniverseSnapshotRecord,
)

__all__ = ["OwnerLensStore", "SqliteStore"]

_SCHEMA = """
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
                         'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'
                     )),
    last_attempt_at  TEXT,
    last_error       TEXT,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY(security_id, dataset)
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
                if stored == 1 and SCHEMA_VERSION == 2:
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

    def close(self) -> None:
        self._conn.close()

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
        return tuple(
            SecurityRefreshStateRecord(
                security_id=int(row["security_id"]),
                dataset=row["dataset"],
                status=row["status"],
                last_attempt_at=row["last_attempt_at"],
                last_error=row["last_error"],
            )
            for row in rows
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

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
from owner_lens.persistence.raw import RawSnapshotStore
from owner_lens.persistence.records import (
    SCHEMA_VERSION,
    AnalysisDriverRecord,
    AnalysisResultRecord,
    CompanyRecord,
    CoverageResultRecord,
    DerivedMetricRecord,
    ReportedFactRecord,
    SourceSnapshotRecord,
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
                if stored != SCHEMA_VERSION:
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

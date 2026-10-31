"""OwnerLens persistence subpackage (Slice 4A).

Stores OwnerLens outputs — company identity, source-snapshot metadata, canonical
reported facts, derived metrics, Feature 2 analysis outputs, and coverage states
— in a local durable store, strictly downstream of the financial computation
layers. No financial module imports this subpackage.
"""

from __future__ import annotations

from owner_lens.persistence.adapters import (
    analysis_result_records,
    company_record,
    coverage_result_records,
    derived_metric_records,
    reported_fact_records,
)
from owner_lens.persistence.errors import (
    MissingProvenanceError,
    PersistenceError,
    SchemaVersionError,
    StorageConnectionError,
    StorageReadError,
    StorageWriteError,
)
from owner_lens.persistence.raw import (
    FilesystemRawSnapshotStore,
    RawSnapshotStore,
    compute_content_hash,
)
from owner_lens.persistence.records import (
    DEFAULT_ANALYSIS_RULE_VERSION,
    DEFAULT_CALCULATION_VERSION,
    SCHEMA_VERSION,
    AnalysisDriverRecord,
    AnalysisResultRecord,
    CompanyRecord,
    CoverageResultRecord,
    DerivedMetricRecord,
    FmpCanonicalCoverageRecord,
    FmpCanonicalFactRecord,
    FmpCanonicalHistoryRecord,
    FmpEodPriceRecord,
    FmpEstimateRecord,
    FmpEvidenceSnapshotRecord,
    ReportedFactRecord,
    SecurityRecord,
    SecurityRefreshStateRecord,
    SourceSnapshotRecord,
    UniverseConstituentRecord,
    UniverseRefreshRunRecord,
    UniverseSnapshotRecord,
)
from owner_lens.persistence.store import OwnerLensStore, SqliteStore

__all__ = [
    "DEFAULT_ANALYSIS_RULE_VERSION",
    "DEFAULT_CALCULATION_VERSION",
    "SCHEMA_VERSION",
    "AnalysisDriverRecord",
    "AnalysisResultRecord",
    "CompanyRecord",
    "CoverageResultRecord",
    "DerivedMetricRecord",
    "FilesystemRawSnapshotStore",
    "FmpCanonicalCoverageRecord",
    "FmpCanonicalFactRecord",
    "FmpCanonicalHistoryRecord",
    "FmpEodPriceRecord",
    "FmpEstimateRecord",
    "FmpEvidenceSnapshotRecord",
    "MissingProvenanceError",
    "OwnerLensStore",
    "PersistenceError",
    "RawSnapshotStore",
    "ReportedFactRecord",
    "SchemaVersionError",
    "SecurityRecord",
    "SecurityRefreshStateRecord",
    "SourceSnapshotRecord",
    "SqliteStore",
    "StorageConnectionError",
    "StorageReadError",
    "StorageWriteError",
    "UniverseConstituentRecord",
    "UniverseRefreshRunRecord",
    "UniverseSnapshotRecord",
    "analysis_result_records",
    "company_record",
    "compute_content_hash",
    "coverage_result_records",
    "derived_metric_records",
    "reported_fact_records",
]

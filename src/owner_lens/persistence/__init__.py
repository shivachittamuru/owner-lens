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
    ReportedFactRecord,
    SourceSnapshotRecord,
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
    "MissingProvenanceError",
    "OwnerLensStore",
    "PersistenceError",
    "RawSnapshotStore",
    "ReportedFactRecord",
    "SchemaVersionError",
    "SourceSnapshotRecord",
    "SqliteStore",
    "StorageConnectionError",
    "StorageReadError",
    "StorageWriteError",
    "analysis_result_records",
    "company_record",
    "compute_content_hash",
    "coverage_result_records",
    "derived_metric_records",
    "reported_fact_records",
]

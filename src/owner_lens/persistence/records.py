"""Persistence record dataclasses for OwnerLens Slice 4A.

These frozen dataclasses mirror the relational schema in
``specs/013-persistence-storage-boundary/data-model.md``. They carry data only,
with no behavior, and use the same Python types as the financial domain (``int``
for exact money and share counts, ``float`` for derived ratios) so the adapters
perform no lossy conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Store-level version awareness (minimum viable; no migration framework).
SCHEMA_VERSION: Final = 1
DEFAULT_CALCULATION_VERSION: Final = "1.0"
DEFAULT_ANALYSIS_RULE_VERSION: Final = "1.0"

__all__ = [
    "DEFAULT_ANALYSIS_RULE_VERSION",
    "DEFAULT_CALCULATION_VERSION",
    "SCHEMA_VERSION",
    "AnalysisDriverRecord",
    "AnalysisResultRecord",
    "CompanyRecord",
    "CoverageResultRecord",
    "DerivedMetricRecord",
    "ReportedFactRecord",
    "SourceSnapshotRecord",
]


@dataclass(frozen=True)
class CompanyRecord:
    """Stable SEC entity; identity is anchored on CIK."""

    cik: str
    ticker: str
    company_name: str


@dataclass(frozen=True)
class SourceSnapshotRecord:
    """A fetched SEC Company Facts payload event; references raw storage."""

    cik: str
    source_provider: str
    source_type: str
    fetched_at: str
    source_uri: str
    content_hash: str
    raw_object_ref: str | None = None
    processing_status: str | None = None


@dataclass(frozen=True)
class ReportedFactRecord:
    """One canonical normalized observation with SEC provenance."""

    cik: str
    canonical_metric: str
    value: int
    unit: str
    fact_kind: str
    fiscal_year: int
    period_end: str
    concept: str
    form: str
    filed: str
    accession: str
    period_start: str | None = None


@dataclass(frozen=True)
class DerivedMetricRecord:
    """One deterministic calculated value.

    Exactly one of ``value_int`` (exact currency/share integer) or ``value_real``
    (approximate ratio/growth float) is populated per record.
    """

    cik: str
    metric_name: str
    fiscal_year: int
    value_int: int | None = None
    value_real: float | None = None
    unit: str | None = None
    calculation_version: str = DEFAULT_CALCULATION_VERSION
    computed_at: str | None = None


@dataclass(frozen=True)
class AnalysisDriverRecord:
    """One ordered, structured reason code belonging to an analysis result."""

    position: int
    code: str
    category: str | None = None


@dataclass(frozen=True)
class AnalysisResultRecord:
    """One higher-level Feature 2 output with its ordered drivers."""

    cik: str
    analysis_type: str
    analysis_period: str
    classification: str
    drivers: tuple[AnalysisDriverRecord, ...] = ()
    analysis_rule_version: str = DEFAULT_ANALYSIS_RULE_VERSION
    computed_at: str | None = None


@dataclass(frozen=True)
class CoverageResultRecord:
    """One explicit coverage state for a company input or analytical layer."""

    cik: str
    subject_kind: str
    subject: str
    state: str
    reason: str | None = None
    blocking_input: str | None = None

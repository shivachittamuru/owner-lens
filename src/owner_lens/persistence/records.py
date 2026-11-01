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

# Store-level version awareness.
SCHEMA_VERSION: Final = 5
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
    "FmpCanonicalCoverageRecord",
    "FmpCanonicalFactRecord",
    "FmpCanonicalHistoryRecord",
    "FmpEodPriceRecord",
    "FmpEstimateRecord",
    "FmpEvidenceSnapshotRecord",
    "ReportedFactRecord",
    "SecurityRecord",
    "SecurityRefreshStateRecord",
    "SourceSnapshotRecord",
    "UnderwritingRecord",
    "UniverseConstituentRecord",
    "UniverseRefreshRunRecord",
    "UniverseSnapshotRecord",
]


@dataclass(frozen=True)
class UnderwritingRecord:
    """Append-only self-contained belief snapshot for one stable security."""

    underwriting_id: str
    security_id: int
    ticker: str
    version: int
    created_at: str
    as_of_date: str
    snapshot_json: str
    content_hash: str


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
class SecurityRecord:
    """Security identity independent of its optional, non-unique issuer CIK."""

    security_id: int
    symbol: str
    name: str
    cik: str | None


@dataclass(frozen=True)
class UniverseConstituentRecord:
    """One historical security membership row in a provider snapshot."""

    symbol: str
    name: str
    cik: str | None
    sector: str | None = None
    subsector: str | None = None


@dataclass(frozen=True)
class UniverseSnapshotRecord:
    """Immutable version of a provider's observed universe membership."""

    provider: str
    observed_at: str
    source_uri: str
    content_hash: str
    raw_object_ref: str | None = None
    snapshot_id: int | None = None


@dataclass(frozen=True)
class UniverseRefreshRunRecord:
    """One attempt to refresh a provider universe."""

    run_id: str
    started_at: str
    requested_symbols: tuple[str, ...] = ()
    status: str = "RUNNING"
    completed_at: str | None = None
    snapshot_id: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class SecurityRefreshStateRecord:
    """Pending or completed dataset refresh state for one stable security."""

    security_id: int
    dataset: str
    status: str
    last_attempt_at: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class FmpEvidenceSnapshotRecord:
    """Immutable raw evidence response and request provenance."""

    security_id: int
    dataset: str
    period_type: str
    source_endpoint: str
    request_parameters: str
    fetched_at: str
    content_hash: str
    evidence_kind: str = "FACT"
    raw_object_ref: str | None = None
    snapshot_id: int | None = None


@dataclass(frozen=True)
class FmpCanonicalFactRecord:
    """One FMP-derived annual canonical observation."""

    metric: str
    value: int
    unit: str
    fiscal_year: int
    period_end: str
    provider_field: str
    snapshot_id: int


@dataclass(frozen=True)
class FmpCanonicalCoverageRecord:
    """Explicit availability state for one annual FMP canonical metric."""

    metric: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class FmpCanonicalHistoryRecord:
    """Provider-isolated annual FMP history and its canonical coverage."""

    security_id: int
    input_hash: str
    observed_at: str
    max_years: int
    facts: tuple[FmpCanonicalFactRecord, ...]
    coverage: tuple[FmpCanonicalCoverageRecord, ...]
    history_id: int | None = None


@dataclass(frozen=True)
class FmpEodPriceRecord:
    """Latest persisted EOD closing price linked to one raw evidence snapshot."""

    snapshot_id: int
    security_id: int
    market_date: str
    close: float
    source_field: str
    currency: str | None = None


@dataclass(frozen=True)
class FmpEstimateRecord:
    """One time-stamped analyst expectation for a target fiscal period."""

    snapshot_id: int
    target_date: str
    revenue_low: float | None = None
    revenue_average: float | None = None
    revenue_high: float | None = None
    revenue_analyst_count: int | None = None
    eps_low: float | None = None
    eps_average: float | None = None
    eps_high: float | None = None
    eps_analyst_count: int | None = None
    evidence_kind: str = "EXPECTATION"


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

"""Persisted single-company ingestion for OwnerLens (Slice 4B).

``ingest_company`` is the one operational orchestration that turns a ticker into
durable, provenance-linked local state: it resolves the SEC identity, retrieves
and deterministically serializes the raw Company Facts, persists the raw payload
first, runs every Feature 1-3 layer the company honestly supports, persists all
trustworthy outputs against a single source snapshot inside one transaction, and
returns a deterministic :class:`IngestionResult`.

Dependencies (``sec_client`` and ``store``) are injected so the workflow is unit
testable offline. No financial calculation happens here and no write happens
inside a calculation function; ingestion only orchestrates existing layers and
the storage boundary. Retrieval and persistence problems are real ``FAILED``
outcomes; unsupported or insufficient data become explicit coverage and partial
status, never fabricated values.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum

from owner_lens._annual import AnnualNormalizationError
from owner_lens.canonical import CanonicalDataError
from owner_lens.capital_allocation import capital_allocation_from_history
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.compounding import (
    EconomicCompoundingView,
    compounding_views_from_history,
)
from owner_lens.coverage import (
    CompanyCoverage,
    LayerCoverage,
    MetricCoverage,
    company_coverage_from_history,
)
from owner_lens.economic_summary import economic_value_summary_from_history
from owner_lens.economic_value import economic_value_from_history
from owner_lens.operating_income import OperatingIncomeConceptNotFoundError
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.persistence.adapters import (
    analysis_result_records,
    company_record,
    coverage_result_records,
    derived_metric_records,
    reported_fact_records,
)
from owner_lens.persistence.errors import PersistenceError
from owner_lens.persistence.raw import compute_content_hash
from owner_lens.persistence.records import (
    DEFAULT_ANALYSIS_RULE_VERSION,
    DEFAULT_CALCULATION_VERSION,
    CompanyRecord,
    SourceSnapshotRecord,
)
from owner_lens.persistence.store import OwnerLensStore
from owner_lens.reported import ConceptNotFoundError
from owner_lens.revenue import RevenueConceptNotFoundError
from owner_lens.sec import (
    COMPANY_FACTS_URL_TEMPLATE,
    SecClient,
    SecError,
)
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = [
    "FailureClass",
    "IngestionFailure",
    "IngestionItem",
    "IngestionResult",
    "IngestionStatus",
    "ProcessingStatus",
    "ingest_company",
]

_SOURCE_PROVIDER = "sec"
_SOURCE_TYPE = "company_facts"

# A required input that raises one of these is unsupported, not a hard failure.
# CanonicalDataError covers every provider-neutral unsupported or invalid input,
# including revenue- and operating-income-specific ambiguity errors that are not
# AnnualNormalizationError subclasses (found in Slice 6A: an ambiguous revenue
# restatement previously crashed ingestion instead of degrading).
_CONCEPT_ERRORS = (
    AnnualNormalizationError,
    ConceptNotFoundError,
    RevenueConceptNotFoundError,
    OperatingIncomeConceptNotFoundError,
    CanonicalDataError,
)


class IngestionStatus(Enum):
    """Unambiguous outcome of one ingestion."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNCHANGED = "UNCHANGED"
    FAILED = "FAILED"


class ProcessingStatus(Enum):
    """Downstream handling state recorded on a source snapshot."""

    FETCHED = "fetched"
    PROCESSED = "processed"
    PARTIAL = "partial"
    FAILED = "failed"


class FailureClass(Enum):
    """Category of an unsuccessful or limited outcome; kept distinct."""

    RETRIEVAL = "retrieval"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_DATA = "insufficient_data"
    PERSISTENCE = "persistence"


@dataclass(frozen=True)
class IngestionItem:
    """One soft finding (unsupported or insufficient) surfaced to the caller."""

    kind: FailureClass
    subject: str
    reason: str | None = None


@dataclass(frozen=True)
class IngestionFailure:
    """A hard failure (retrieval or persistence) that aborted ingestion."""

    kind: FailureClass
    message: str


@dataclass(frozen=True)
class IngestionResult:
    """Deterministic outcome of one ``ingest_company`` call."""

    company: CompanyRecord | None
    source_snapshot: SourceSnapshotRecord | None
    status: IngestionStatus
    processing_status: ProcessingStatus
    persisted_fact_count: int
    persisted_metric_count: int
    analysis_count: int
    coverage: CompanyCoverage | None
    warnings: tuple[str, ...]
    unsupported_items: tuple[IngestionItem, ...]
    failure: IngestionFailure | None = None


def _to_processing_status(value: str | None) -> ProcessingStatus:
    try:
        return ProcessingStatus(value)
    except ValueError:
        return ProcessingStatus.FETCHED


def _coverage_findings(
    coverage: CompanyCoverage,
) -> tuple[tuple[IngestionItem, ...], tuple[str, ...]]:
    """Derive unsupported/insufficient items and warnings from coverage."""
    items: list[IngestionItem] = []
    warnings: list[str] = []
    for name, state in coverage.inputs.items():
        if state is MetricCoverage.UNSUPPORTED:
            items.append(IngestionItem(FailureClass.UNSUPPORTED, name))
    for name, result in coverage.layers.items():
        if result.state is LayerCoverage.UNAVAILABLE:
            items.append(
                IngestionItem(FailureClass.UNSUPPORTED, name, result.reason)
            )
        elif result.state in (LayerCoverage.INSUFFICIENT_DATA, LayerCoverage.PARTIAL):
            items.append(
                IngestionItem(FailureClass.INSUFFICIENT_DATA, name, result.reason)
            )
            if result.reason:
                warnings.append(f"{name}: {result.reason}")
    return tuple(items), tuple(warnings)


def ingest_company(
    ticker: str,
    *,
    sec_client: SecClient,
    store: OwnerLensStore,
    max_years: int = 5,
    force: bool = False,
) -> IngestionResult:
    """Ingest one company end-to-end and return a structured result.

    See ``specs/014-persisted-single-company-ingestion/contracts/ingestion-service.md``
    for the full behavioral contract.
    """
    # 1-2. Resolve identity and retrieve raw facts (retrieval failures are hard).
    try:
        identity = sec_client.resolve_company(ticker)
        raw_facts = sec_client.get_company_facts(identity)
    except SecError as exc:
        return IngestionResult(
            company=None,
            source_snapshot=None,
            status=IngestionStatus.FAILED,
            processing_status=ProcessingStatus.FAILED,
            persisted_fact_count=0,
            persisted_metric_count=0,
            analysis_count=0,
            coverage=None,
            warnings=(),
            unsupported_items=(),
            failure=IngestionFailure(FailureClass.RETRIEVAL, str(exc)),
        )

    company = company_record(identity)
    resolved_ticker = identity.ticker
    cik = identity.cik

    # 3-4. Deterministic serialization + content hash.
    payload = json.dumps(raw_facts, sort_keys=True).encode()
    content_hash = compute_content_hash(payload)
    now = datetime.now(UTC).isoformat()
    snapshot = SourceSnapshotRecord(
        cik=cik,
        source_provider=_SOURCE_PROVIDER,
        source_type=_SOURCE_TYPE,
        fetched_at=now,
        source_uri=COMPANY_FACTS_URL_TEMPLATE.format(cik=cik),
        content_hash=content_hash,
        processing_status=ProcessingStatus.FETCHED.value,
    )

    # 9. Idempotency: identical content AND compatible versions => UNCHANGED.
    if (
        not force
        and store.source_snapshot_exists(cik, content_hash)
        and store.snapshot_matches_versions(
            cik,
            content_hash,
            calculation_version=DEFAULT_CALCULATION_VERSION,
            analysis_rule_version=DEFAULT_ANALYSIS_RULE_VERSION,
        )
    ):
        stored = store.get_source_snapshot(cik, content_hash)
        processing = _to_processing_status(
            stored.processing_status if stored else None
        )
        return IngestionResult(
            company=company,
            source_snapshot=stored or snapshot,
            status=IngestionStatus.UNCHANGED,
            processing_status=processing,
            persisted_fact_count=0,
            persisted_metric_count=0,
            analysis_count=0,
            coverage=None,
            warnings=(),
            unsupported_items=(),
        )

    # 5-7. Raw-first persistence: record the source before downstream analysis.
    store.save_company(company)
    store.save_source_snapshot(snapshot, raw_payload=payload)

    # 8, 10-11. Map the SEC payload once into the provider-neutral canonical
    # history, then run supported layers (unsupported inputs degrade, never crash).
    history = canonical_history_from_sec(
        raw_facts, ticker=resolved_ticker, max_years=max_years
    )
    try:
        owner_rows = owner_economics_from_history(history)
    except _CONCEPT_ERRORS:
        owner_rows = ()
    try:
        capital_rows = capital_efficiency_from_history(history)
    except _CONCEPT_ERRORS:
        capital_rows = ()
    try:
        snapshots = economic_value_from_history(history)
    except _CONCEPT_ERRORS:
        snapshots = ()
    compounding: Sequence[EconomicCompoundingView]
    try:
        compounding = compounding_views_from_history(history)
    except _CONCEPT_ERRORS:
        compounding = ()
    try:
        capital_alloc = capital_allocation_from_history(history)
    except _CONCEPT_ERRORS:
        capital_alloc = ()
    try:
        summary = economic_value_summary_from_history(history)
    except _CONCEPT_ERRORS:
        summary = None
    try:
        coverage = company_coverage_from_history(history)
    except _CONCEPT_ERRORS:
        coverage = None

    # Build records from whatever branches computed. One unsupported branch never
    # discards the trustworthy output of the independent branches.
    facts = reported_fact_records(cik, owner_rows, capital_rows)
    metrics = derived_metric_records(cik, owner_rows, capital_rows, computed_at=now)
    analyses = analysis_result_records(
        cik,
        annual_snapshots=snapshots,
        compounding_views=compounding,
        capital_allocation_rows=capital_alloc,
        summary=summary,
        computed_at=now,
    )

    if coverage is not None:
        full = all(
            result.state is LayerCoverage.AVAILABLE
            for result in coverage.layers.values()
        )
        items, warnings = _coverage_findings(coverage)
    else:
        full = False
        items = (
            IngestionItem(
                FailureClass.UNSUPPORTED,
                "analysis",
                "coverage could not be computed for this source representation",
            ),
        )
        warnings = ()

    persisted_any = bool(facts or metrics or analyses)
    if full:
        status = IngestionStatus.COMPLETE
        processing = ProcessingStatus.PROCESSED
    elif persisted_any:
        status = IngestionStatus.PARTIAL
        processing = ProcessingStatus.PARTIAL
    else:
        # Raw evidence stored, but nothing trustworthy could be analyzed.
        status = IngestionStatus.PARTIAL
        processing = ProcessingStatus.FETCHED

    # 12. Structured writes are atomic: a mid-write failure rolls the set back.
    try:
        with store.transaction():
            store.save_reported_facts(facts, snapshot=snapshot)
            store.save_derived_metrics(metrics, snapshot=snapshot)
            for result in analyses:
                store.save_analysis_result(result, snapshot=snapshot)
            if coverage is not None:
                store.save_coverage(
                    coverage_result_records(cik, coverage), snapshot=snapshot
                )
            store.set_snapshot_processing_status(cik, content_hash, processing.value)
    except PersistenceError as exc:
        try:
            store.set_snapshot_processing_status(
                cik, content_hash, ProcessingStatus.FAILED.value
            )
        except PersistenceError:
            pass
        return IngestionResult(
            company=company,
            source_snapshot=replace(
                snapshot, processing_status=ProcessingStatus.FAILED.value
            ),
            status=IngestionStatus.FAILED,
            processing_status=ProcessingStatus.FAILED,
            persisted_fact_count=0,
            persisted_metric_count=0,
            analysis_count=0,
            coverage=coverage,
            warnings=warnings,
            unsupported_items=items,
            failure=IngestionFailure(FailureClass.PERSISTENCE, str(exc)),
        )

    # 13. Structured result.
    return IngestionResult(
        company=company,
        source_snapshot=replace(snapshot, processing_status=processing.value),
        status=status,
        processing_status=processing,
        persisted_fact_count=len(facts),
        persisted_metric_count=len(metrics),
        analysis_count=len(analyses),
        coverage=coverage,
        warnings=warnings,
        unsupported_items=items,
    )

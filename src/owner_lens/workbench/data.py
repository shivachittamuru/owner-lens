"""Deterministic data service for the OwnerLens workbench (Feature 7D).

This module is the whole of the workbench's logic. It is deliberately free of
Streamlit imports so every behaviour below can be unit tested without launching
a browser, and it is free of financial logic so the workbench can never disagree
with the CLI or the tests: every number it returns comes from an existing
OwnerLens entry point.

Three properties are load bearing:

* **It reads only persisted data.** Companies come from the configured store,
  raw payloads come from the content-addressed snapshot store, and canonical
  histories are rebuilt from those payloads. Nothing here opens a network
  connection, so opening or navigating the workbench can never fetch from SEC
  or FMP.
* **It preserves absence.** A metric OwnerLens could not derive stays ``None``,
  a dimension it could not evaluate stays ``NOT_EVALUABLE``, and a company that
  failed coverage stays visible with its reason. Nothing is defaulted to zero,
  dropped, or filled in.
* **It recomputes nothing.** Screening bands, buckets, coverage states, and
  economic-value classifications are read from Features 2, 6, and 7.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from owner_lens.canonical import (
    CanonicalDataError,
    CanonicalFinancialHistory,
    MetricStatus,
)
from owner_lens.capital_allocation import CapitalAllocationRow
from owner_lens.capital_efficiency import CapitalEfficiencyRow
from owner_lens.compounding import EconomicCompoundingView
from owner_lens.config import OwnerLensSettings, build_local_store, load_settings
from owner_lens.coverage import (
    CompanyCoverage,
    LayerCoverage,
    company_coverage_from_history,
)
from owner_lens.economic_summary import EconomicValueSummary
from owner_lens.economic_value import EconomicValueSnapshot
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.persistence import FilesystemRawSnapshotStore, OwnerLensStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.screening import (
    BUCKET_ORDER,
    DIMENSION_ORDER,
    CoverageClass,
    DimensionBand,
    DimensionScore,
    LimitingFactor,
    ScreeningBucket,
    ScreeningDimension,
    ScreeningResult,
    SetupType,
    assemble_screening_evidence,
    screen_company,
)
from owner_lens.sec_adapter import canonical_history_from_sec
from owner_lens.universe import CompanySurvey, MetricFinding, survey_company

__all__ = [
    "BAND_LABEL",
    "COMPARISON_ROWS",
    "DEFAULT_MAX_YEARS",
    "DIMENSION_LABEL",
    "LAYER_LABEL",
    "NOT_AVAILABLE",
    "CompanyDetail",
    "ComparisonColumn",
    "ComparisonTable",
    "CoverageStanding",
    "DataQualityMetric",
    "DataQualityReport",
    "OverviewCounts",
    "PersistedCompany",
    "WorkbenchError",
    "WorkbenchSource",
    "build_comparison",
    "company_detail",
    "coverage_standings",
    "data_quality_report",
    "format_comparison_value",
    "format_count",
    "format_money",
    "format_per_share",
    "format_ratio",
    "limiting_factor_label",
    "load_canonical_history",
    "load_persisted_companies",
    "load_raw_facts",
    "main_limiting_reason",
    "open_source",
    "overview_counts",
    "research_queue",
    "screen_persisted_universe",
    "strongest_reason",
]

DEFAULT_MAX_YEARS = 5
NOT_AVAILABLE = "N/A"


class WorkbenchError(Exception):
    """Raised when the workbench cannot serve a request from persisted data."""


@dataclass(frozen=True)
class PersistedCompany:
    """One company the local store knows about, with the snapshot that backs it.

    ``content_hash`` identifies the exact raw payload every derived result is
    built from. It is the cache key for everything downstream: a re-ingested
    company produces a new hash, which invalidates stale derived results instead
    of silently serving them.
    """

    ticker: str
    company_name: str
    cik: str
    content_hash: str | None
    fetched_at: str | None
    processing_status: str | None

    @property
    def available(self) -> bool:
        """Whether a raw snapshot exists to rebuild this company's history from."""
        return self.content_hash is not None


@dataclass(frozen=True)
class WorkbenchSource:
    """The persisted store and raw-snapshot store the workbench reads from.

    A source owns a SQLite connection, and SQLite connections are bound to the
    thread that created them. Streamlit reruns a script on whichever thread is
    free, so a source must never outlive one unit of work: open it, use it,
    close it. Opening a local SQLite connection is cheap, and everything
    expensive downstream is cached as plain data rather than as a live handle.
    """

    store: OwnerLensStore
    raw_store: FilesystemRawSnapshotStore
    db_path: str
    raw_data_path: str

    def close(self) -> None:
        close = getattr(self.store, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_source(settings: OwnerLensSettings | None = None) -> WorkbenchSource:
    """Open the configured local store. Performs no network call.

    If initialization fails, the half-open connection is closed before the error
    propagates: ``SqliteStore`` connects eagerly, so an unguarded failure would
    leak a connection on every Streamlit rerun.
    """
    resolved = settings if settings is not None else load_settings()
    store = build_local_store(resolved)
    try:
        store.initialize()
        raw_store = FilesystemRawSnapshotStore(Path(resolved.raw_data_path))
    except Exception:
        store.close()
        raise
    return WorkbenchSource(
        store=store,
        raw_store=raw_store,
        db_path=resolved.db_path,
        raw_data_path=resolved.raw_data_path,
    )


# --- Loading -------------------------------------------------------------------


def load_persisted_companies(source: WorkbenchSource) -> tuple[PersistedCompany, ...]:
    """Every company in the store, ticker-ordered, with its latest snapshot.

    A company whose raw payload is missing is still returned, with a
    ``content_hash`` of ``None``, so the workbench can say so explicitly rather
    than omitting it.
    """
    companies: list[PersistedCompany] = []
    for record in source.store.list_companies():
        snapshot = source.store.get_latest_source_snapshot(record.cik)
        usable = snapshot is not None and source.raw_store.exists(snapshot.content_hash)
        companies.append(
            PersistedCompany(
                ticker=record.ticker,
                company_name=record.company_name,
                cik=record.cik,
                content_hash=snapshot.content_hash if usable and snapshot else None,
                fetched_at=snapshot.fetched_at if snapshot else None,
                processing_status=snapshot.processing_status if snapshot else None,
            )
        )
    return tuple(sorted(companies, key=lambda company: company.ticker))


def load_raw_facts(source: WorkbenchSource, company: PersistedCompany) -> dict[str, Any]:
    """Read one company's stored raw payload. Raises rather than fetching it.

    A payload that exists but is unreadable or is not a JSON object becomes a
    ``WorkbenchError`` like any other per-company failure, so one corrupt
    snapshot degrades its own row instead of blanking the application.
    """
    if company.content_hash is None:
        raise WorkbenchError(
            f"{company.ticker} has no stored raw snapshot. "
            f"Run 'uv run owner-lens ingest {company.ticker}' to retrieve one."
        )
    try:
        payload = source.raw_store.get(company.content_hash)
        parsed = json.loads(payload)
    except PersistenceError as exc:
        raise WorkbenchError(
            f"{company.ticker} snapshot {company.content_hash[:8]} could not be read: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkbenchError(
            f"{company.ticker} snapshot {company.content_hash[:8]} is not valid JSON: "
            f"{exc}. Re-ingest the company to replace it."
        ) from exc
    if not isinstance(parsed, dict):
        raise WorkbenchError(
            f"{company.ticker} snapshot {company.content_hash[:8]} is not a Company "
            "Facts object. Re-ingest the company to replace it."
        )
    facts: dict[str, Any] = parsed
    return facts


def load_canonical_history(
    source: WorkbenchSource,
    company: PersistedCompany,
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> CanonicalFinancialHistory:
    """Rebuild one company's canonical history from its persisted raw snapshot."""
    return canonical_history_from_sec(
        load_raw_facts(source, company), ticker=company.ticker, max_years=max_years
    )


def screen_persisted_universe(
    source: WorkbenchSource,
    companies: Sequence[PersistedCompany] | None = None,
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> tuple[ScreeningResult, ...]:
    """Screen every company the store can serve, in the Feature 7 ranking order.

    A company with no usable snapshot is skipped rather than screened on
    nothing, and one whose payload cannot be read is skipped rather than
    allowed to blank the whole result. Callers surface both separately, so no
    company disappears without a reason being available somewhere.
    """
    selected = companies if companies is not None else load_persisted_companies(source)
    results: list[ScreeningResult] = []
    for company in selected:
        if not company.available:
            continue
        try:
            history = load_canonical_history(source, company, max_years=max_years)
        except WorkbenchError:
            continue
        results.append(screen_company(assemble_screening_evidence(history)))
    return tuple(sorted(results, key=lambda result: result.rank_key))


# --- Overview ------------------------------------------------------------------


@dataclass(frozen=True)
class OverviewCounts:
    """Universe counts derived from the data actually loaded, never hard-coded."""

    tracked: int
    without_snapshot: int
    by_coverage: dict[CoverageClass, int]
    by_bucket: dict[ScreeningBucket, int]
    by_setup: dict[SetupType, int]

    @property
    def screened(self) -> int:
        """Companies that produced a screening result at all."""
        return sum(self.by_bucket.values())

    @property
    def screenable(self) -> int:
        """Companies a verdict could be formed for, excluding insufficient data."""
        return self.screened - self.by_bucket.get(ScreeningBucket.INSUFFICIENT_DATA, 0)

    @property
    def worth_underwriting(self) -> int:
        """Companies in the two buckets that warrant expensive research time."""
        return self.by_bucket.get(ScreeningBucket.HIGH_PRIORITY, 0) + self.by_bucket.get(
            ScreeningBucket.WORTH_UNDERWRITING, 0
        )

    @property
    def funnel(self) -> tuple[tuple[str, int], ...]:
        """The opportunity funnel, widest stage first."""
        return (
            ("Companies tracked", self.tracked),
            ("Screenable", self.screenable),
            ("Worth deeper underwriting", self.worth_underwriting),
        )


def overview_counts(
    companies: Sequence[PersistedCompany], results: Sequence[ScreeningResult]
) -> OverviewCounts:
    """Derive every headline count from the companies and results supplied."""
    return OverviewCounts(
        tracked=len(companies),
        without_snapshot=sum(1 for company in companies if not company.available),
        by_coverage={
            coverage: sum(1 for r in results if r.coverage_class is coverage)
            for coverage in CoverageClass
        },
        by_bucket={
            bucket: sum(1 for r in results if r.bucket is bucket)
            for bucket in BUCKET_ORDER
        },
        by_setup={
            setup: sum(1 for r in results if r.setup_type is setup)
            for setup in SetupType
        },
    )


def research_queue(results: Sequence[ScreeningResult]) -> tuple[ScreeningResult, ...]:
    """The companies to look at next, in the Feature 7 ranking order."""
    return tuple(
        result
        for result in sorted(results, key=lambda r: r.rank_key)
        if result.bucket
        in (ScreeningBucket.HIGH_PRIORITY, ScreeningBucket.WORTH_UNDERWRITING)
    )


def strongest_reason(result: ScreeningResult) -> str | None:
    """The first supporting reason, which Feature 7 emits in fixed order."""
    return result.supporting_reasons[0].value if result.supporting_reasons else None


def main_limiting_reason(result: ScreeningResult) -> str | None:
    """The gate when one fired, else the first limiting or coverage reason."""
    if result.gate is not None:
        return result.gate.value
    if result.limiting_reasons:
        return result.limiting_reasons[0].value
    return result.coverage_reasons[0].value if result.coverage_reasons else None


# --- Company detail ------------------------------------------------------------


@dataclass(frozen=True)
class CompanyDetail:
    """Everything the Company view needs, assembled once from persisted data.

    Every optional member is ``None`` exactly when OwnerLens could not derive
    it, and the matching ``*_unavailable_reason`` explains why, so a view can
    show the reason instead of an empty chart.
    """

    company: PersistedCompany
    screening: ScreeningResult
    coverage: CompanyCoverage
    owner_economics: tuple[OwnerEconomicsRow, ...]
    capital_efficiency: tuple[CapitalEfficiencyRow, ...]
    capital_allocation: tuple[CapitalAllocationRow, ...]
    snapshots: tuple[EconomicValueSnapshot, ...]
    recent_compounding: EconomicCompoundingView | None
    long_term_compounding: EconomicCompoundingView | None
    summary: EconomicValueSummary | None

    def layer_reason(self, layer: str) -> str | None:
        """Why an analytical layer is unavailable, from the Feature 6 contract."""
        result = self.coverage.layers.get(layer)
        if result is None or result.state is LayerCoverage.AVAILABLE:
            return None
        return result.reason or f"{LAYER_LABEL.get(layer, layer)} is {result.state.value}"

    @property
    def capital_efficiency_unavailable_reason(self) -> str | None:
        return None if self.capital_efficiency else self.layer_reason("capital_efficiency")

    @property
    def capital_allocation_unavailable_reason(self) -> str | None:
        return None if self.capital_allocation else self.layer_reason("capital_allocation")

    @property
    def economic_value_unavailable_reason(self) -> str | None:
        return None if self.snapshots else self.layer_reason("economic_value")

    @property
    def summary_unavailable_reason(self) -> str | None:
        return None if self.summary else self.layer_reason("economic_summary")

    @property
    def latest_capital_allocation(self) -> CapitalAllocationRow | None:
        return self.capital_allocation[-1] if self.capital_allocation else None

    def dimension(self, dimension: ScreeningDimension) -> DimensionScore:
        return self.screening.dimensions[dimension]


def company_detail(
    source: WorkbenchSource,
    company: PersistedCompany,
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> CompanyDetail:
    """Assemble one company's full research view from persisted data only."""
    history = load_canonical_history(source, company, max_years=max_years)
    evidence = assemble_screening_evidence(history)
    return CompanyDetail(
        company=company,
        screening=screen_company(evidence),
        coverage=company_coverage_from_history(history),
        owner_economics=evidence.owner_economics,
        capital_efficiency=evidence.capital_efficiency,
        capital_allocation=evidence.capital_allocation,
        snapshots=evidence.snapshots,
        recent_compounding=evidence.recent_compounding,
        long_term_compounding=evidence.long_term_compounding,
        summary=evidence.summary,
    )


# --- Comparison ----------------------------------------------------------------

DIMENSION_LABEL: dict[ScreeningDimension, str] = {
    ScreeningDimension.BUSINESS_QUALITY: "Business Quality",
    ScreeningDimension.CAPITAL_EFFICIENCY: "Capital Efficiency",
    ScreeningDimension.PER_SHARE_COMPOUNDING: "Per-Share Compounding",
    ScreeningDimension.BALANCE_SHEET_STRENGTH: "Balance Sheet",
    ScreeningDimension.CAPITAL_ALLOCATION: "Capital Allocation",
    ScreeningDimension.ECONOMIC_MOMENTUM: "Economic Momentum",
}

# Comparison rows in display order, as (label, group). Dimension rows are
# suffixed so they never collide with the capital-allocation classification row.
# Comparison rows in display order, as (label, group). Dimension rows are
# suffixed so they never collide with the capital-allocation classification row.
_STANDING_ROWS: tuple[tuple[str, str], ...] = (
    ("Coverage", "Standing"),
    ("Screening bucket", "Standing"),
    ("Setup type", "Standing"),
    ("Screening score", "Standing"),
    ("Limiting factor", "Standing"),
)
# Compounding rates are read from the Feature 2B view, never re-derived here. A
# company whose compounding view the engine refused to build reports N/A rather
# than a rate computed over some other window.
_COMPOUNDING_ROWS: tuple[tuple[str, str], ...] = (
    ("Compounding window", "Compounding"),
    ("Revenue CAGR", "Compounding"),
    ("FCF CAGR", "Compounding"),
    ("FCF/share CAGR", "Compounding"),
    ("Diluted-share CAGR", "Compounding"),
)
_ECONOMICS_ROWS: tuple[tuple[str, str], ...] = (
    ("Latest ROIC", "Economics"),
    ("Latest operating margin", "Economics"),
    ("Latest FCF margin", "Economics"),
    ("Net cash / debt", "Economics"),
)
_ALLOCATION_ROWS: tuple[tuple[str, str], ...] = (
    ("SBC / FCF", "Capital allocation"),
    ("Repurchases / FCF", "Capital allocation"),
    ("Capital-allocation classification", "Capital allocation"),
)
_DIMENSION_ROW_LABEL: dict[ScreeningDimension, str] = {
    dimension: f"{DIMENSION_LABEL[dimension]} band" for dimension in DIMENSION_ORDER
}
COMPARISON_ROWS: tuple[tuple[str, str], ...] = (
    *_STANDING_ROWS,
    *_COMPOUNDING_ROWS,
    *_ECONOMICS_ROWS,
    *_ALLOCATION_ROWS,
    *(
        (_DIMENSION_ROW_LABEL[dimension], "Screening dimensions")
        for dimension in DIMENSION_ORDER
    ),
)


@dataclass(frozen=True)
class ComparisonColumn:
    """One company's column in the comparison table.

    ``values`` holds raw values, never formatted strings: an unavailable metric
    is ``None`` so a view renders an explicit "N/A" rather than a zero.
    """

    ticker: str
    values: dict[str, Any]


@dataclass(frozen=True)
class ComparisonTable:
    """A side-by-side comparison of two or more companies."""

    rows: tuple[tuple[str, str], ...]
    columns: tuple[ComparisonColumn, ...]

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(column.ticker for column in self.columns)

    def value(self, label: str, ticker: str) -> Any:
        column = next((c for c in self.columns if c.ticker == ticker), None)
        return column.values.get(label) if column is not None else None


def _latest_attribute(rows: Sequence[Any], attribute: str) -> Any:
    """The most recent non-None value of an attribute, or None."""
    for row in reversed(rows):
        value = getattr(row, attribute, None)
        if value is not None:
            return value
    return None


def _comparison_values(detail: CompanyDetail) -> dict[str, Any]:
    owner = detail.owner_economics
    allocation = detail.latest_capital_allocation
    # Compounding rates come from the Feature 2B view or not at all. Deriving
    # them here would let the Compare page publish a rate the Company page
    # reports as underivable, over a window nothing names.
    view = detail.long_term_compounding
    values: dict[str, Any] = {
        "Coverage": detail.screening.coverage_class,
        "Screening bucket": detail.screening.bucket,
        "Setup type": detail.screening.setup_type,
        "Screening score": detail.screening.screening_score,
        "Limiting factor": detail.screening.limiting_factor,
        "Compounding window": (
            f"FY{view.start_fiscal_year}–FY{view.end_fiscal_year}" if view else None
        ),
        "Revenue CAGR": view.revenue_cagr if view else None,
        "FCF CAGR": view.fcf_cagr if view else None,
        "FCF/share CAGR": view.fcf_per_share_cagr if view else None,
        "Diluted-share CAGR": view.diluted_share_cagr if view else None,
        "Latest ROIC": _latest_attribute(detail.capital_efficiency, "roic"),
        "Latest operating margin": _latest_attribute(owner, "operating_margin"),
        "Latest FCF margin": _latest_attribute(owner, "fcf_margin"),
        "Net cash / debt": _latest_attribute(detail.capital_efficiency, "net_cash"),
        "SBC / FCF": allocation.sbc_over_fcf if allocation else None,
        "Repurchases / FCF": allocation.repurchases_over_fcf if allocation else None,
        "Capital-allocation classification": (
            allocation.classification if allocation else None
        ),
    }
    for dimension in DIMENSION_ORDER:
        values[_DIMENSION_ROW_LABEL[dimension]] = detail.dimension(dimension).band
    return values


def build_comparison(details: Iterable[CompanyDetail]) -> ComparisonTable:
    """Build the side-by-side table, preserving every unavailable value as None."""
    return ComparisonTable(
        rows=COMPARISON_ROWS,
        columns=tuple(
            ComparisonColumn(
                ticker=detail.company.ticker, values=_comparison_values(detail)
            )
            for detail in details
        ),
    )


# --- Data quality --------------------------------------------------------------


@dataclass(frozen=True)
class DataQualityMetric:
    """One canonical metric's standing, with the evidence behind it."""

    metric: str
    status: MetricStatus
    diagnosis: str
    concept_used: str | None
    concepts_tried: tuple[str, ...]
    candidates: tuple[str, ...]
    latest_fiscal_year: int | None
    reason: str | None
    resolved_conflicts: tuple[str, ...]
    blocking: bool

    @property
    def available(self) -> bool:
        return self.status is MetricStatus.AVAILABLE


@dataclass(frozen=True)
class DataQualityReport:
    """What OwnerLens can and cannot see for one company, and why."""

    company: PersistedCompany
    survey: CompanySurvey
    metrics: tuple[DataQualityMetric, ...]

    @property
    def overall(self) -> str:
        return self.survey.overall.value

    def with_status(self, status: MetricStatus) -> tuple[DataQualityMetric, ...]:
        return tuple(metric for metric in self.metrics if metric.status is status)

    @property
    def available(self) -> tuple[DataQualityMetric, ...]:
        return self.with_status(MetricStatus.AVAILABLE)

    @property
    def unsupported(self) -> tuple[DataQualityMetric, ...]:
        return self.with_status(MetricStatus.UNSUPPORTED)

    @property
    def invalid(self) -> tuple[DataQualityMetric, ...]:
        return self.with_status(MetricStatus.INVALID)

    @property
    def structurally_absent(self) -> tuple[DataQualityMetric, ...]:
        return self.with_status(MetricStatus.STRUCTURALLY_ABSENT)

    @property
    def blocking(self) -> tuple[DataQualityMetric, ...]:
        return tuple(metric for metric in self.metrics if metric.blocking)

    @property
    def layers(self) -> dict[str, tuple[str, str | None]]:
        """Each analytical layer's state and the reason it is not available."""
        return {
            layer: (probe.state.value, probe.reason)
            for layer, probe in self.survey.layers.items()
        }


def _quality_metric(
    finding: MetricFinding, blocking: frozenset[str]
) -> DataQualityMetric:
    return DataQualityMetric(
        metric=finding.metric,
        status=finding.status,
        diagnosis=finding.diagnosis.value,
        concept_used=finding.concept_used,
        concepts_tried=finding.concepts_tried,
        candidates=finding.candidates,
        latest_fiscal_year=finding.latest_fiscal_year,
        reason=finding.reason or finding.note,
        resolved_conflicts=finding.resolved_conflicts,
        blocking=finding.metric in blocking,
    )


def data_quality_report(
    source: WorkbenchSource,
    company: PersistedCompany,
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> DataQualityReport:
    """Run the existing offline coverage survey and shape it for the workbench.

    The survey is the Feature 6 diagnosis engine; nothing about concept
    selection, staleness, or composition is re-decided here.
    """
    survey = survey_company(
        load_raw_facts(source, company),
        ticker=company.ticker,
        company_name=company.company_name,
        cik=company.cik,
        content_hash=company.content_hash,
        processing_status=company.processing_status,
        max_years=max_years,
    )
    blocking = frozenset(survey.blocking_metrics())
    metrics = tuple(
        _quality_metric(finding, blocking) for finding in survey.metrics.values()
    )
    return DataQualityReport(company=company, survey=survey, metrics=metrics)


@dataclass(frozen=True)
class CoverageStanding:
    """One row of the data-quality grid, including companies OwnerLens refused."""

    company: PersistedCompany
    overall: str
    unusable_metrics: tuple[str, ...]
    primary_blocker: str | None


def coverage_standings(
    source: WorkbenchSource,
    companies: Sequence[PersistedCompany],
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> tuple[CoverageStanding, ...]:
    """Per-company coverage standing for the data-quality grid.

    Every company appears, including the ones that failed: a company OwnerLens
    cannot use must stay visible with its reason rather than vanish.
    """
    standings: list[CoverageStanding] = []
    for company in companies:
        if not company.available:
            standings.append(
                CoverageStanding(company, "NO SNAPSHOT", (), "no stored raw snapshot")
            )
            continue
        try:
            report = data_quality_report(source, company, max_years=max_years)
        except (WorkbenchError, CanonicalDataError) as exc:
            standings.append(CoverageStanding(company, "ERROR", (), str(exc)))
            continue
        unusable = tuple(
            metric.metric
            for metric in report.metrics
            if metric.status in (MetricStatus.UNSUPPORTED, MetricStatus.INVALID)
        )
        standings.append(
            CoverageStanding(
                company, report.overall, unusable, report.survey.primary_blocker
            )
        )
    return tuple(standings)


# --- Shared display vocabulary -------------------------------------------------

BAND_LABEL: dict[DimensionBand, str] = {
    DimensionBand.STRONG: "STRONG",
    DimensionBand.ADEQUATE: "ADEQUATE",
    DimensionBand.WEAK: "WEAK",
    DimensionBand.POOR: "POOR",
    DimensionBand.NOT_EVALUABLE: "NOT EVALUABLE",
}

LAYER_LABEL: dict[str, str] = {
    "owner_economics": "Owner economics",
    "capital_efficiency": "Capital efficiency",
    "economic_value": "Economic value",
    "compounding": "Compounding",
    "capital_allocation": "Capital allocation",
    "economic_summary": "Economic summary",
}

_LIMITING_LABEL: dict[LimitingFactor, str] = {
    LimitingFactor.NONE: "—",
    LimitingFactor.FUNDAMENTALS: "Fundamentals",
    LimitingFactor.COVERAGE: "Coverage",
    LimitingFactor.BOTH: "Fundamentals + coverage",
}


def limiting_factor_label(factor: LimitingFactor) -> str:
    return _LIMITING_LABEL[factor]


def format_ratio(value: float | None, *, signed: bool = False) -> str:
    """Percentages are the only transformation the workbench applies to a number."""
    if value is None:
        return NOT_AVAILABLE
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"


def format_money(value: float | None) -> str:
    if value is None:
        return NOT_AVAILABLE
    if abs(value) >= 1e9:
        return f"{value / 1e9:+,.2f}B"
    return f"{value / 1e6:+,.0f}M"


def format_count(value: float | None) -> str:
    return NOT_AVAILABLE if value is None else f"{value:,.0f}"


def format_per_share(value: float | None) -> str:
    return NOT_AVAILABLE if value is None else f"{value:,.2f}"


def format_comparison_value(label: str, value: Any) -> str:
    """Render one comparison cell, keeping an unavailable value explicit."""
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, DimensionBand):
        return BAND_LABEL[value]
    if isinstance(value, LimitingFactor):
        return limiting_factor_label(value)
    if hasattr(value, "value"):
        return str(value.value)
    if label.endswith("CAGR"):
        return format_ratio(value, signed=True)
    if label in ("Latest ROIC", "Latest operating margin", "Latest FCF margin"):
        return format_ratio(value)
    if label in ("SBC / FCF", "Repurchases / FCF"):
        return format_ratio(value)
    if label == "Net cash / debt":
        return format_money(value)
    return str(value)

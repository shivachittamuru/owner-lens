"""Pure conversion of OwnerLens domain outputs into persistence records.

These functions are side-effect free: they read already-computed domain objects
and produce persistence records. No function here performs a write, and no
financial module imports this module, so the financial layers remain storage
independent. Absent values (``None``) yield no record; a genuine reported zero is
preserved as a fact with ``value == 0``.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from owner_lens._annual import AnnualObservation
from owner_lens.capital_allocation import CapitalAllocationRow
from owner_lens.capital_efficiency import CapitalEfficiencyRow
from owner_lens.compounding import EconomicCompoundingView
from owner_lens.coverage import CompanyCoverage
from owner_lens.economic_summary import EconomicValueSummary
from owner_lens.economic_value import EconomicValueSnapshot
from owner_lens.owner_economics import OwnerEconomicsRow
from owner_lens.persistence.records import (
    AnalysisDriverRecord,
    AnalysisResultRecord,
    CompanyRecord,
    CoverageResultRecord,
    DerivedMetricRecord,
    ReportedFactRecord,
)
from owner_lens.sec import CompanyIdentity

__all__ = [
    "analysis_result_records",
    "company_record",
    "coverage_result_records",
    "derived_metric_records",
    "reported_fact_records",
]

# Canonical reported facts carried on each domain row, with their fact kind.
_DURATION_FACTS = (
    "revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capital_expenditures",
    "diluted_shares",
)
_INSTANT_FACTS = (
    "cash",
    "short_term_investments",
    "current_debt",
    "long_term_debt",
    "total_assets",
    "total_equity",
)

# Derived metrics persisted as approximate ratios (REAL) versus exact integers.
_OWNER_RATIO_METRICS = (
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "fcf_growth",
    "fcf_per_share_growth",
    "diluted_share_growth",
)
_CAPITAL_RATIO_METRICS = ("effective_tax_rate", "roa", "roe", "roic")
_CAPITAL_INT_METRICS = (
    "cash_plus_sti",
    "total_debt",
    "net_cash",
    "nopat",
    "invested_capital",
)


def company_record(identity: CompanyIdentity) -> CompanyRecord:
    """Convert a resolved SEC identity into a company record."""
    return CompanyRecord(
        cik=identity.cik,
        ticker=identity.ticker,
        company_name=identity.company_name,
    )


def _fact_record(
    cik: str, metric: str, obs: AnnualObservation, kind: str
) -> ReportedFactRecord:
    return ReportedFactRecord(
        cik=cik,
        canonical_metric=metric,
        value=obs.value,
        unit=obs.unit,
        fact_kind=kind,
        fiscal_year=obs.fiscal_year,
        period_end=obs.period_end.isoformat(),
        period_start=obs.period_start.isoformat() if kind == "duration" else None,
        concept=obs.concept,
        form=obs.form,
        filed=obs.filed.isoformat(),
        accession=obs.accession,
    )


def reported_fact_records(
    cik: str,
    owner_rows: Sequence[OwnerEconomicsRow],
    capital_rows: Sequence[CapitalEfficiencyRow],
) -> tuple[ReportedFactRecord, ...]:
    """Extract canonical reported facts (with provenance) from domain rows."""
    records: list[ReportedFactRecord] = []
    for owner_row in owner_rows:
        for metric in _DURATION_FACTS:
            obs = getattr(owner_row, metric)
            if obs is not None:
                records.append(_fact_record(cik, metric, obs, "duration"))
    for capital_row in capital_rows:
        for metric in _INSTANT_FACTS:
            obs = getattr(capital_row, metric)
            if obs is not None:
                records.append(_fact_record(cik, metric, obs, "instant"))
    return tuple(records)


def derived_metric_records(
    cik: str,
    owner_rows: Sequence[OwnerEconomicsRow],
    capital_rows: Sequence[CapitalEfficiencyRow],
    *,
    computed_at: str,
) -> tuple[DerivedMetricRecord, ...]:
    """Extract deterministic derived metrics from domain rows."""
    records: list[DerivedMetricRecord] = []
    for owner_row in owner_rows:
        for metric in _OWNER_RATIO_METRICS:
            value = getattr(owner_row, metric)
            if value is not None:
                records.append(
                    DerivedMetricRecord(
                        cik=cik,
                        metric_name=metric,
                        fiscal_year=owner_row.fiscal_year,
                        value_real=float(value),
                        unit="ratio",
                        computed_at=computed_at,
                    )
                )
        if owner_row.fcf_per_share is not None:
            records.append(
                DerivedMetricRecord(
                    cik=cik,
                    metric_name="fcf_per_share",
                    fiscal_year=owner_row.fiscal_year,
                    value_real=float(owner_row.fcf_per_share),
                    unit="per_share",
                    computed_at=computed_at,
                )
            )
        if owner_row.free_cash_flow is not None:
            records.append(
                DerivedMetricRecord(
                    cik=cik,
                    metric_name="free_cash_flow",
                    fiscal_year=owner_row.fiscal_year,
                    value_int=owner_row.free_cash_flow,
                    unit="USD",
                    computed_at=computed_at,
                )
            )
    for capital_row in capital_rows:
        for metric in _CAPITAL_RATIO_METRICS:
            value = getattr(capital_row, metric)
            if value is not None:
                records.append(
                    DerivedMetricRecord(
                        cik=cik,
                        metric_name=metric,
                        fiscal_year=capital_row.fiscal_year,
                        value_real=float(value),
                        unit="ratio",
                        computed_at=computed_at,
                    )
                )
        for metric in _CAPITAL_INT_METRICS:
            value = getattr(capital_row, metric)
            if value is not None:
                records.append(
                    DerivedMetricRecord(
                        cik=cik,
                        metric_name=metric,
                        fiscal_year=capital_row.fiscal_year,
                        value_int=value,
                        unit="USD",
                        computed_at=computed_at,
                    )
                )
    return tuple(records)


def _drivers(codes: Sequence[Enum], category: str | None) -> list[AnalysisDriverRecord]:
    return [
        AnalysisDriverRecord(position=index, code=code.value, category=category)
        for index, code in enumerate(codes)
    ]

def analysis_result_records(
    cik: str,
    *,
    annual_snapshots: Sequence[EconomicValueSnapshot],
    compounding_views: Sequence[EconomicCompoundingView],
    capital_allocation_rows: Sequence[CapitalAllocationRow],
    summary: EconomicValueSummary | None,
    computed_at: str,
) -> tuple[AnalysisResultRecord, ...]:
    """Convert Feature 2 outputs into ordered analysis-result records."""
    records: list[AnalysisResultRecord] = []
    for snapshot in annual_snapshots:
        records.append(
            AnalysisResultRecord(
                cik=cik,
                analysis_type="annual_snapshot",
                analysis_period=str(snapshot.fiscal_year),
                classification=snapshot.classification.value,
                drivers=tuple(_drivers(snapshot.drivers, None)),
                computed_at=computed_at,
            )
        )
    for view in compounding_views:
        records.append(
            AnalysisResultRecord(
                cik=cik,
                analysis_type="compounding",
                analysis_period=f"FY{view.start_fiscal_year}-FY{view.end_fiscal_year}",
                classification=view.classification.value,
                drivers=tuple(_drivers(view.drivers, None)),
                computed_at=computed_at,
            )
        )
    for row in capital_allocation_rows:
        records.append(
            AnalysisResultRecord(
                cik=cik,
                analysis_type="capital_allocation",
                analysis_period=str(row.fiscal_year),
                classification=row.classification.value,
                drivers=tuple(_drivers(row.drivers, None)),
                computed_at=computed_at,
            )
        )
    if summary is not None:
        pairs: list[tuple[Enum, str]] = []
        pairs.extend((driver, "positive") for driver in summary.key_positive_drivers)
        pairs.extend((driver, "watch") for driver in summary.key_watch_drivers)
        pairs.extend((driver, "negative") for driver in summary.key_negative_drivers)
        summary_drivers = tuple(
            AnalysisDriverRecord(position=index, code=driver.value, category=category)
            for index, (driver, category) in enumerate(pairs)
        )
        records.append(
            AnalysisResultRecord(
                cik=cik,
                analysis_type="economic_value_summary",
                analysis_period=str(summary.latest_fiscal_year),
                classification=summary.overall_economic_value_classification.value,
                drivers=summary_drivers,
                computed_at=computed_at,
            )
        )
    return tuple(records)


def coverage_result_records(
    cik: str,
    coverage: CompanyCoverage,
) -> tuple[CoverageResultRecord, ...]:
    """Convert a company coverage picture into explicit coverage records."""
    records: list[CoverageResultRecord] = []
    for subject, state in coverage.inputs.items():
        records.append(
            CoverageResultRecord(
                cik=cik,
                subject_kind="input",
                subject=subject,
                state=state.value,
            )
        )
    for subject, result in coverage.layers.items():
        records.append(
            CoverageResultRecord(
                cik=cik,
                subject_kind="layer",
                subject=subject,
                state=result.state.value,
                reason=result.reason,
                blocking_input=result.blocking_input,
            )
        )
    return tuple(records)

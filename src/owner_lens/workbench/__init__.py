"""The OwnerLens local research workbench (Feature 7D).

A thin Streamlit interface over the existing deterministic engine. The
financial logic lives in :mod:`owner_lens.screening`, :mod:`owner_lens.coverage`
and the Feature 2 modules; this package only loads persisted data and renders
it. Importing this package does not import Streamlit — only
:mod:`owner_lens.workbench.app` and the view modules do — so
:mod:`owner_lens.workbench.data` stays importable and testable without a UI
stack installed.

Launch it with ``uv run owner-lens workbench``.
"""

from __future__ import annotations

from owner_lens.workbench.data import (
    DEFAULT_MAX_YEARS,
    CompanyDetail,
    ComparisonTable,
    CoverageStanding,
    DataQualityReport,
    OverviewCounts,
    PersistedCompany,
    WorkbenchError,
    WorkbenchSource,
    build_comparison,
    company_detail,
    coverage_standings,
    data_quality_report,
    load_canonical_history,
    load_persisted_companies,
    open_source,
    overview_counts,
    research_queue,
    screen_persisted_universe,
)

__all__ = [
    "DEFAULT_MAX_YEARS",
    "CompanyDetail",
    "ComparisonTable",
    "CoverageStanding",
    "DataQualityReport",
    "OverviewCounts",
    "PersistedCompany",
    "WorkbenchError",
    "WorkbenchSource",
    "build_comparison",
    "company_detail",
    "coverage_standings",
    "data_quality_report",
    "load_canonical_history",
    "load_persisted_companies",
    "open_source",
    "overview_counts",
    "research_queue",
    "screen_persisted_universe",
]

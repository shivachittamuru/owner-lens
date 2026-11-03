"""Read-only Workbench discovery of fully analyzed, comparison-eligible versions."""

from __future__ import annotations

from dataclasses import dataclass

from owner_lens.opportunity_comparison import (
    ComparisonError,
    UnderwritingSelection,
    load_opportunity,
)
from owner_lens.persistence import SqliteStore


@dataclass(frozen=True)
class ComparisonVersion:
    selection: UnderwritingSelection
    underwriting_id: str
    content_hash: str

    @property
    def label(self) -> str:
        return f"{self.selection.ticker}:{self.selection.version}"


@dataclass(frozen=True)
class ComparisonCompany:
    ticker: str
    name: str
    versions: tuple[ComparisonVersion, ...]
    latest_record_version: int

    @property
    def latest(self) -> ComparisonVersion:
        return self.versions[-1]


@dataclass(frozen=True)
class ComparisonCatalog:
    companies: tuple[ComparisonCompany, ...]
    excluded: tuple[str, ...]


def discover_comparison_companies(store: SqliteStore) -> ComparisonCatalog:
    """Resolve eligibility with 9A, requiring saved completion before discovery."""
    companies = []
    excluded = []
    seen = set()
    for security in store.list_securities():
        records = store.list_underwriting(security.symbol)
        versions = []
        for record in sorted(records, key=lambda item: item.version):
            if record.underwriting_id in seen:
                continue
            seen.add(record.underwriting_id)
            selection = UnderwritingSelection(record.ticker, record.version)
            label = f"{selection.ticker}:{selection.version}"
            if not store.list_challenger_runs(record.underwriting_id):
                excluded.append(f"{label}: analysis incomplete (no saved challenger run).")
                continue
            try:
                opportunity = load_opportunity(store, selection)
            except ComparisonError as exc:
                excluded.append(f"{label}: {exc}")
                continue
            versions.append(
                ComparisonVersion(
                    selection,
                    opportunity.summary.underwriting_id,
                    opportunity.summary.underwriting_content_hash,
                )
            )
        if versions:
            companies.append(
                ComparisonCompany(
                    versions[-1].selection.ticker,
                    security.name or security.symbol,
                    tuple(versions),
                    max(record.version for record in records),
                )
            )
    return ComparisonCatalog(
        tuple(sorted(companies, key=lambda item: item.ticker)), tuple(excluded)
    )

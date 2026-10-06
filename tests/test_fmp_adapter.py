"""Tests for the FMP -> canonical history adapter (Slice 5B). No network access."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from _fixtures import adbe_facts
from _fmp_fixtures import fmp_payloads, fmp_statements, with_field

from owner_lens.canonical import MetricStatus, MetricUnsupportedError
from owner_lens.capital_allocation import capital_allocation_from_history
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.compounding import compounding_views_from_history
from owner_lens.coverage import (
    LayerCoverage,
    MetricCoverage,
    company_coverage_from_history,
)
from owner_lens.economic_summary import economic_value_summary_from_history
from owner_lens.economic_value import economic_value_from_history
from owner_lens.fmp_adapter import (
    FMP_FIELD_MAP,
    FMP_PROVIDER,
    FmpInvalidMetricError,
    FmpUnsupportedMetricError,
    canonical_history_from_fmp,
)
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.persistence.adapters import reported_fact_records
from owner_lens.persistence.errors import MissingProvenanceError
from owner_lens.sec_adapter import canonical_history_from_sec

_M = 1_000_000


def _history(payloads: dict[str, list[dict[str, Any]]] | None = None, **kwargs: Any):
    return canonical_history_from_fmp(fmp_statements(payloads=payloads), **kwargs)


def _values(history: Any, metric: str) -> dict[int, int]:
    return {f.fiscal_year: f.value for f in history.series_for(metric).observations}


# --- Statement mapping --------------------------------------------------------


def test_income_statement_mapping() -> None:
    history = _history()
    assert _values(history, "revenue") == {2025: 23769 * _M, 2024: 21505 * _M, 2023: 19409 * _M}
    assert _values(history, "operating_income")[2025] == 8706 * _M
    assert _values(history, "net_income")[2025] == 7130 * _M
    assert _values(history, "pretax_income")[2025] == 8734 * _M
    assert _values(history, "income_tax_expense")[2025] == 1604 * _M
    assert _values(history, "diluted_shares")[2025] == 427000000


def test_balance_sheet_mapping() -> None:
    history = _history()
    assert _values(history, "cash")[2025] == 5431 * _M
    assert _values(history, "short_term_investments")[2025] == 1164 * _M
    assert _values(history, "current_debt") == {2025: 0, 2024: 1499 * _M, 2023: 0}
    assert _values(history, "long_term_debt")[2025] == 6210 * _M
    assert _values(history, "total_assets")[2025] == 29496 * _M
    assert _values(history, "total_equity")[2025] == 11623 * _M
    assert history.series_for("cash").observations[0].period_start is None


def test_cash_flow_mapping_normalizes_outflows_to_positive_magnitudes() -> None:
    history = _history()
    assert _values(history, "operating_cash_flow")[2025] == 10031 * _M
    assert _values(history, "capital_expenditures")[2025] == 179 * _M
    assert _values(history, "repurchases")[2025] == 11281 * _M
    assert _values(history, "stock_based_compensation")[2025] == 1942 * _M


def test_precomputed_fmp_metrics_are_never_mapped() -> None:
    mapped_fields = {m.field for m in FMP_FIELD_MAP.values()}
    assert not mapped_fields & {"freeCashFlow", "ebitda", "netDebt", "totalDebt", "eps"}
    # The standardized capex/OCF summary variants are not used either.
    assert not mapped_fields & {"capitalExpenditure", "operatingCashFlow"}
    owner = owner_economics_from_history(_history())
    # OwnerLens computes FCF itself; the fixture's freeCashFlow placeholder is 1M.
    assert owner[0].free_cash_flow == (10031 - 179) * _M


# --- Provenance ---------------------------------------------------------------


def test_provenance_records_fmp_fields_without_fabrication() -> None:
    history = _history()
    fact = history.series_for("repurchases").observations[0]
    assert fact.provider == FMP_PROVIDER == "fmp"
    assert fact.provider_field == "commonStockRepurchased"
    assert fact.fiscal_year == 2025
    assert fact.period_end == date(2025, 11, 30)
    assert fact.filed == date(2026, 1, 15)
    assert (fact.period_start, fact.form, fact.accession) == (None, None, None)
    assert history.providers() == frozenset({"fmp"})
    assert history.ticker == "ADBE"


def test_fmp_facts_are_not_persisted_without_filing_provenance() -> None:
    owner = owner_economics_from_history(_history())
    with pytest.raises(MissingProvenanceError, match="fmp"):
        reported_fact_records("0000796343", owner, ())


# --- Missing-data semantics ---------------------------------------------------


def test_missing_field_is_unsupported() -> None:
    history = _history(with_field("cash-flow-statement", "commonStockRepurchased", None))
    series = history.series_for("repurchases")
    assert series.status is MetricStatus.UNSUPPORTED
    assert isinstance(series.error, FmpUnsupportedMetricError)
    assert "commonStockRepurchased" in (series.reason or "")


def test_null_values_are_omitted_not_zeroed() -> None:
    history = _history(with_field("cash-flow-statement", "stockBasedCompensation", {2024: None}))
    assert _values(history, "stock_based_compensation").keys() == {2025, 2023}


def test_all_zero_dividends_are_structurally_absent() -> None:
    series = _history().series_for("dividends_paid")
    assert series.status is MetricStatus.STRUCTURALLY_ABSENT
    assert series.observations == ()


def test_partial_zero_dividends_remain_reported_values() -> None:
    history = _history(
        with_field("cash-flow-statement", "commonDividendsPaid", {2025: -500 * _M})
    )
    assert _values(history, "dividends_paid") == {2025: 500 * _M, 2024: 0, 2023: 0}


def test_zero_placeholder_for_implausible_metric_is_not_a_value() -> None:
    history = _history(with_field("income-statement", "weightedAverageShsOutDil", {2024: 0}))
    assert _values(history, "diluted_shares").keys() == {2025, 2023}
    all_zero = _history(
        with_field("income-statement", "weightedAverageShsOutDil", {2025: 0, 2024: 0, 2023: 0})
    )
    assert all_zero.series_for("diluted_shares").status is MetricStatus.UNSUPPORTED


@pytest.mark.parametrize(
    ("endpoint", "field", "values", "metric", "message"),
    [
        ("income-statement", "revenue", {2025: "23769"}, "revenue", "not numeric"),
        ("income-statement", "revenue", {2025: 1.5}, "revenue", "not a whole number"),
        ("cash-flow-statement", "commonStockRepurchased", {2025: 5 * _M}, "repurchases", "positive"),
        ("balance-sheet-statement", "reportedCurrency", {2025: "EUR"}, "cash", "not USD"),
    ],
)
def test_malformed_or_conflicting_data_is_invalid(
    endpoint: str, field: str, values: dict[int, Any], metric: str, message: str
) -> None:
    history = _history(with_field(endpoint, field, values))
    series = history.series_for(metric)
    assert series.status is MetricStatus.INVALID
    with pytest.raises(FmpInvalidMetricError, match=message):
        history.require(metric)


def test_conflicting_duplicate_fiscal_year_is_invalid() -> None:
    payloads = fmp_payloads()
    duplicate = dict(payloads["income-statement"][0])
    duplicate["netIncome"] += 1
    duplicate["filingDate"] = "2026-03-01"
    payloads["income-statement"].append(duplicate)
    history = _history(payloads)
    assert history.series_for("net_income").status is MetricStatus.INVALID
    assert history.series_for("revenue").status is MetricStatus.AVAILABLE


def test_standardized_variant_disagreement_does_not_invalidate() -> None:
    # Live ADBE FY2021: FMP's standardized capitalExpenditure differs from the
    # as-reported investmentsInPropertyPlantAndEquipment; OwnerLens uses the latter.
    history = _history(with_field("cash-flow-statement", "capitalExpenditure", {2023: -330 * _M}))
    assert history.series_for("capital_expenditures").status is MetricStatus.AVAILABLE
    assert _values(history, "capital_expenditures")[2023] == 360 * _M
    fact = history.series_for("capital_expenditures").observations[0]
    assert fact.provider_field == "investmentsInPropertyPlantAndEquipment"


def test_identical_duplicate_fiscal_year_collapses() -> None:
    payloads = fmp_payloads()
    payloads["income-statement"].append(dict(payloads["income-statement"][0]))
    assert len(_history(payloads).series_for("revenue").observations) == 3


def test_window_limits_duration_and_instant_years() -> None:
    history = _history(max_years=2)
    assert _values(history, "revenue").keys() == {2025, 2024}
    assert _values(history, "cash").keys() == {2025, 2024, 2023}


# --- Existing OwnerLens logic on FMP-backed history ---------------------------


def test_owner_economics_and_capital_efficiency_run_without_sec_data() -> None:
    history = _history()
    owner = owner_economics_from_history(history)
    capital = capital_efficiency_from_history(history)
    assert [row.fiscal_year for row in owner] == [2025, 2024, 2023]
    assert owner[0].fcf_per_share == pytest.approx((10031 - 179) * _M / 427000000)
    assert owner[0].revenue is not None and owner[0].revenue.provider == "fmp"
    assert capital[0].roic is not None


def test_feature2_and_coverage_run_without_sec_data() -> None:
    history = _history()
    assert economic_value_from_history(history)
    assert compounding_views_from_history(history)
    assert capital_allocation_from_history(history)
    summary = economic_value_summary_from_history(history)
    assert summary.ticker == "ADBE"
    coverage = company_coverage_from_history(history)
    assert coverage.inputs["dividends_paid"] is MetricCoverage.STRUCTURALLY_ABSENT
    assert all(r.state is LayerCoverage.AVAILABLE for r in coverage.layers.values())


def test_unsupported_fmp_metric_degrades_layers_like_sec() -> None:
    history = _history(with_field("balance-sheet-statement", "shortTermDebt", None))
    with pytest.raises(MetricUnsupportedError):
        capital_efficiency_from_history(history)
    coverage = company_coverage_from_history(history)
    assert coverage.layers["owner_economics"].state is LayerCoverage.AVAILABLE
    assert coverage.layers["capital_efficiency"].state is LayerCoverage.UNAVAILABLE


def test_same_reported_values_yield_same_owner_lens_outputs_across_providers() -> None:
    """Determinism check, not reconciliation: identical inputs, identical economics."""
    sec = canonical_history_from_sec(adbe_facts(), ticker="ADBE")
    fmp = _history()

    def derived(rows: Any, fields: tuple[str, ...]) -> list[tuple[Any, ...]]:
        return [tuple(getattr(row, f) for f in fields) for row in rows]

    owner_fields = ("fiscal_year", "free_cash_flow", "fcf_per_share", "operating_margin",
                    "fcf_margin", "fcf_growth", "diluted_share_growth")
    capital_fields = ("fiscal_year", "net_cash", "nopat", "invested_capital", "roic", "roe")
    assert derived(owner_economics_from_history(fmp), owner_fields) == derived(
        owner_economics_from_history(sec), owner_fields
    )
    assert derived(capital_efficiency_from_history(fmp), capital_fields) == derived(
        capital_efficiency_from_history(sec), capital_fields
    )
    assert [r.classification for r in capital_allocation_from_history(fmp)] == [
        r.classification for r in capital_allocation_from_history(sec)
    ]
    fmp_summary = economic_value_summary_from_history(fmp)
    sec_summary = economic_value_summary_from_history(sec)
    assert (
        fmp_summary.overall_economic_value_classification
        is sec_summary.overall_economic_value_classification
    )

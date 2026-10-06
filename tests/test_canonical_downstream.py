"""Downstream OwnerLens logic consuming canonical history (Slice 5A).

Synthetic histories use a non-SEC provider and no SEC payload, proving the
calculations depend only on the canonical model. Parity tests prove the
canonical entry points match the legacy SEC wrappers for the golden companies.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens.canonical import (
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalSeries,
    MetricInvalidError,
    MetricKind,
    MetricStatus,
    MetricUnsupportedError,
    metric_spec,
)
from owner_lens.capital_allocation import (
    capital_allocation_from_facts,
    capital_allocation_from_history,
)
from owner_lens.capital_efficiency import (
    capital_efficiency_from_facts,
    capital_efficiency_from_history,
)
from owner_lens.compounding import (
    compounding_views_from_facts,
    compounding_views_from_history,
)
from owner_lens.coverage import (
    LayerCoverage,
    MetricCoverage,
    company_coverage,
    company_coverage_from_history,
    company_output,
    company_output_from_history,
)
from owner_lens.economic_summary import (
    economic_value_summary_from_facts,
    economic_value_summary_from_history,
)
from owner_lens.economic_value import (
    economic_value_from_facts,
    economic_value_from_history,
)
from owner_lens.owner_economics import (
    owner_economics_from_facts,
    owner_economics_from_history,
)
from owner_lens.sec_adapter import canonical_history_from_sec

GOLDEN = [("ADBE", adbe_facts), ("V", visa_facts), ("COST", costco_facts)]

_DURATION: dict[str, dict[int, int]] = {
    "revenue": {2024: 1000, 2025: 1200},
    "operating_income": {2024: 200, 2025: 300},
    "net_income": {2024: 150, 2025: 240},
    "operating_cash_flow": {2024: 300, 2025: 400},
    "capital_expenditures": {2024: 50, 2025: 100},
    "diluted_shares": {2024: 100, 2025: 100},
    "income_tax_expense": {2024: 40, 2025: 60},
    "pretax_income": {2024: 200, 2025: 300},
    "repurchases": {2024: 100, 2025: 150},
    "stock_based_compensation": {2024: 20, 2025: 30},
}
_INSTANT: dict[str, dict[int, int]] = {
    "cash": {2023: 100, 2024: 150, 2025: 200},
    "short_term_investments": {2023: 50, 2024: 50, 2025: 50},
    "current_debt": {2023: 10, 2024: 10, 2025: 10},
    "long_term_debt": {2023: 100, 2024: 100, 2025: 100},
    "total_assets": {2023: 1000, 2024: 1000, 2025: 1000},
    "total_equity": {2023: 500, 2024: 500, 2025: 500},
}


def _fact(metric: str, year: int, value: int) -> CanonicalFact:
    spec = metric_spec(metric)
    duration = spec.kind is MetricKind.DURATION
    return CanonicalFact(
        metric=metric,
        value=value,
        unit=spec.unit,
        fiscal_year=year,
        fiscal_period="FY",
        period_end=date(year, 12, 31),
        period_start=date(year, 1, 1) if duration else None,
        provider="test",
        provider_field=f"test.{metric}",
        form="annual-report",
        filed=date(year + 1, 2, 15),
        accession=f"test-{metric}-{year}",
    )


def synthetic_history(
    *,
    drop: tuple[str, ...] = (),
    unsupported: tuple[str, ...] = (),
) -> CanonicalFinancialHistory:
    """Two years of round-number economics from a non-SEC provider."""
    excluded = set(drop) | set(unsupported)
    facts = [
        _fact(metric, year, value)
        for metric, values in (_DURATION | _INSTANT).items()
        if metric not in excluded
        for year, value in values.items()
    ]
    return CanonicalFinancialHistory.build(
        ticker="TEST",
        max_years=2,
        facts=facts,
        structurally_absent=("dividends_paid", *drop),
        unsupported={metric: f"{metric} not provided" for metric in unsupported},
    )


def test_owner_economics_from_synthetic_history() -> None:
    rows = owner_economics_from_history(synthetic_history())
    latest, prior = rows
    assert (latest.fiscal_year, prior.fiscal_year) == (2025, 2024)
    assert latest.free_cash_flow == 300 and prior.free_cash_flow == 250
    assert latest.fcf_per_share == pytest.approx(3.0)
    assert latest.operating_margin == pytest.approx(0.25)
    assert latest.net_margin == pytest.approx(0.20)
    assert latest.fcf_margin == pytest.approx(0.25)
    assert latest.fcf_growth == pytest.approx(0.20)
    assert latest.fcf_per_share_growth == pytest.approx(0.20)
    assert latest.diluted_share_growth == pytest.approx(0.0)
    assert latest.revenue is not None
    assert latest.revenue.provider == "test"
    assert latest.revenue.provider_field == "test.revenue"


def test_unsupported_diluted_shares_degrades_only_per_share_fields() -> None:
    latest = owner_economics_from_history(synthetic_history(unsupported=("diluted_shares",)))[0]
    assert latest.fcf_per_share is None
    assert latest.fcf_per_share_growth is None
    assert latest.diluted_shares is None
    assert latest.free_cash_flow == 300
    assert latest.operating_margin == pytest.approx(0.25)


def test_capital_efficiency_from_synthetic_history() -> None:
    rows = capital_efficiency_from_history(synthetic_history())
    latest, prior = rows
    assert (latest.fiscal_year, prior.fiscal_year) == (2025, 2024)
    assert latest.cash_plus_sti == 250
    assert latest.total_debt == 110
    assert latest.net_cash == 140
    assert latest.effective_tax_rate == pytest.approx(0.2)
    assert latest.nopat == 240
    assert latest.invested_capital == 360
    assert latest.roic == pytest.approx(240 / ((410 + 360) / 2))
    assert prior.roic == pytest.approx(160 / ((460 + 410) / 2))
    assert latest.roe == pytest.approx(240 / 500)
    assert latest.cash is not None and latest.cash.period_start is None


def test_unsupported_required_metric_fails_loudly() -> None:
    with pytest.raises(MetricUnsupportedError, match="current_debt not provided"):
        capital_efficiency_from_history(synthetic_history(unsupported=("current_debt",)))


@pytest.mark.parametrize(("ticker", "build"), GOLDEN)
def test_feature1_parity_with_sec_wrappers(ticker: str, build: Any) -> None:
    history = canonical_history_from_sec(build(), ticker=ticker)
    assert owner_economics_from_history(history) == owner_economics_from_facts(
        build(), ticker=ticker
    )
    assert capital_efficiency_from_history(history) == capital_efficiency_from_facts(
        build(), ticker=ticker
    )

# --- User Story 3: Feature 2 layers and coverage --------------------------


@pytest.mark.parametrize(("ticker", "build"), GOLDEN)
def test_feature2_and_coverage_parity_with_sec_wrappers(ticker: str, build: Any) -> None:
    history = canonical_history_from_sec(build(), ticker=ticker)
    assert economic_value_from_history(history) == economic_value_from_facts(
        build(), ticker=ticker
    )
    assert compounding_views_from_history(history) == compounding_views_from_facts(
        build(), ticker=ticker
    )
    assert capital_allocation_from_history(history) == capital_allocation_from_facts(
        build(), ticker=ticker
    )
    assert economic_value_summary_from_history(history) == economic_value_summary_from_facts(
        build(), ticker=ticker
    )
    coverage = company_coverage_from_history(history)
    assert coverage == company_coverage(build(), ticker=ticker)
    assert company_output_from_history(coverage, history) == company_output(
        coverage, build(), ticker=ticker
    )


def test_structurally_absent_dividends_mean_no_dividend_program() -> None:
    rows = capital_allocation_from_history(synthetic_history())
    latest = rows[0]
    assert latest.fiscal_year == 2025
    assert latest.dividends is None
    assert latest.capital_returned == latest.repurchases == 150
    assert latest.retained_fcf == 300 - 150


def test_coverage_maps_statuses_and_flags_unsupported_shares() -> None:
    coverage = company_coverage_from_history(synthetic_history(unsupported=("diluted_shares",)))
    assert coverage.ticker == "TEST"
    assert coverage.inputs["revenue"] is MetricCoverage.AVAILABLE
    assert coverage.inputs["dividends_paid"] is MetricCoverage.STRUCTURALLY_ABSENT
    assert coverage.inputs["diluted_shares"] is MetricCoverage.UNSUPPORTED
    owner_layer = coverage.layers["owner_economics"]
    assert owner_layer.state is LayerCoverage.PARTIAL
    assert owner_layer.blocking_input == "diluted_shares"


def test_coverage_marks_layer_unavailable_for_unsupported_required_input() -> None:
    coverage = company_coverage_from_history(synthetic_history(unsupported=("current_debt",)))
    assert coverage.layers["owner_economics"].state is LayerCoverage.AVAILABLE
    capital = coverage.layers["capital_efficiency"]
    assert capital.state is LayerCoverage.UNAVAILABLE
    assert capital.reason == "current_debt not provided"


def test_invalid_metric_reraises_from_coverage() -> None:
    base = synthetic_history()
    error = MetricInvalidError("FY2025 repurchases conflict")
    series = tuple(
        CanonicalSeries(s.metric, s.unit, MetricStatus.INVALID, reason=str(error), error=error)
        if s.metric == "repurchases"
        else s
        for s in base.series
    )
    history = CanonicalFinancialHistory(base.ticker, base.max_years, series)
    assert owner_economics_from_history(history)
    with pytest.raises(MetricInvalidError) as info:
        company_coverage_from_history(history)
    assert info.value is error

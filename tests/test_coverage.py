"""Tests for the golden-company coverage reporter (Slice 3C)."""

from __future__ import annotations

from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens import (
    LayerCoverage,
    MetricCoverage,
    company_coverage,
    company_output,
    format_coverage_report,
)


def test_adobe_full_coverage_all_layers_available() -> None:
    cov = company_coverage(adbe_facts(), ticker="ADBE")

    assert all(r.state is LayerCoverage.AVAILABLE for r in cov.layers.values())
    # The diluted-shares tolerance path is not taken for Adobe.
    assert cov.inputs["diluted_shares"] is MetricCoverage.AVAILABLE
    # Adobe pays no dividend: structurally absent, distinct from unsupported or zero.
    assert cov.inputs["dividends_paid"] is MetricCoverage.STRUCTURALLY_ABSENT


def test_costco_full_coverage_all_layers_available() -> None:
    cov = company_coverage(costco_facts(), ticker="COST")

    assert all(r.state is LayerCoverage.AVAILABLE for r in cov.layers.values())


def test_visa_partial_coverage_layers() -> None:
    cov = company_coverage(visa_facts(), ticker="V")

    assert cov.layers["capital_efficiency"].state is LayerCoverage.AVAILABLE
    assert cov.layers["owner_economics"].state is LayerCoverage.PARTIAL
    assert cov.layers["economic_value"].state is LayerCoverage.INSUFFICIENT_DATA
    assert cov.layers["compounding"].state is LayerCoverage.INSUFFICIENT_DATA
    assert cov.layers["capital_allocation"].state is LayerCoverage.PARTIAL
    assert cov.layers["economic_summary"].state is LayerCoverage.INSUFFICIENT_DATA
    for layer in ("owner_economics", "economic_value", "economic_summary"):
        assert cov.layers[layer].blocking_input == "diluted_shares"


def test_visa_input_states_are_distinct() -> None:
    # absent != unsupported != available, all preserved on one company.
    cov = company_coverage(visa_facts(), ticker="V")

    assert cov.inputs["diluted_shares"] is MetricCoverage.UNSUPPORTED
    assert cov.inputs["short_term_investments"] is MetricCoverage.STRUCTURALLY_ABSENT
    assert cov.inputs["revenue"] is MetricCoverage.AVAILABLE
    assert cov.inputs["operating_cash_flow"] is MetricCoverage.AVAILABLE


def test_coverage_report_is_deterministic_with_reasons() -> None:
    covs = [
        company_coverage(facts, ticker=ticker)
        for ticker, facts in (
            ("ADBE", adbe_facts()),
            ("V", visa_facts()),
            ("COST", costco_facts()),
        )
    ]

    first = format_coverage_report(covs)
    second = format_coverage_report(covs)

    assert first == second
    assert "diluted shares" in first
    for ticker in ("ADBE", "V", "COST"):
        assert ticker in first


def test_company_output_full_shows_summary_partial_shows_evidence() -> None:
    adbe_out = company_output(
        company_coverage(adbe_facts(), ticker="ADBE"), adbe_facts(), ticker="ADBE"
    )
    assert "Economic Value Lens" in adbe_out
    assert "Overall" in adbe_out

    visa_out = company_output(
        company_coverage(visa_facts(), ticker="V"), visa_facts(), ticker="V"
    )
    assert "partial" in visa_out.lower()
    assert "diluted" in visa_out.lower()
    assert "fabricated" in visa_out.lower()

"""Tests for the SEC Company Facts -> canonical history adapter (Slice 5A)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens._annual import (
    AmbiguousValueError,
    ConceptNotFoundError,
    MalformedFactsError,
)
from owner_lens.balance_sheet import (
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.canonical import CANONICAL_METRICS, MetricKind, MetricStatus
from owner_lens.operating_income import normalize_annual_operating_income
from owner_lens.reported import (
    normalize_capital_expenditures,
    normalize_diluted_shares,
    normalize_dividends_paid,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_operating_cash_flow,
    normalize_pretax_income,
    normalize_repurchases,
    normalize_stock_based_compensation,
)
from owner_lens.revenue import normalize_annual_revenue
from owner_lens.sec_adapter import SEC_PROVIDER, canonical_history_from_sec

_ORACLE = {
    "revenue": normalize_annual_revenue,
    "operating_income": normalize_annual_operating_income,
    "net_income": normalize_net_income,
    "operating_cash_flow": normalize_operating_cash_flow,
    "capital_expenditures": normalize_capital_expenditures,
    "diluted_shares": normalize_diluted_shares,
    "income_tax_expense": normalize_income_tax_expense,
    "pretax_income": normalize_pretax_income,
    "repurchases": normalize_repurchases,
    "stock_based_compensation": normalize_stock_based_compensation,
    "dividends_paid": normalize_dividends_paid,
    "cash": normalize_cash,
    "short_term_investments": normalize_short_term_investments,
    "current_debt": normalize_current_debt,
    "long_term_debt": normalize_long_term_debt,
    "total_assets": normalize_total_assets,
    "total_equity": normalize_total_equity,
}

GOLDEN = [("ADBE", adbe_facts), ("V", visa_facts), ("COST", costco_facts)]


@pytest.mark.parametrize(("ticker", "build"), GOLDEN)
def test_canonical_facts_equal_sec_normalizer_observations(ticker: str, build: Any) -> None:
    facts = build()
    history = canonical_history_from_sec(facts, ticker=ticker)
    for spec in CANONICAL_METRICS:
        series = history.series_for(spec.name)
        if series.status is not MetricStatus.AVAILABLE:
            continue
        window = 6 if spec.kind is MetricKind.INSTANT else 5
        oracle = _ORACLE[spec.name](facts, ticker=ticker, max_years=window)
        assert len(series.observations) == len(oracle.observations)
        for fact, obs in zip(series.observations, oracle.observations, strict=True):
            assert fact.metric == spec.name
            assert fact.provider == SEC_PROVIDER
            assert fact.provider_field == obs.concept
            assert (fact.value, fact.unit, fact.fiscal_year, fact.fiscal_period) == (
                obs.value,
                obs.unit,
                obs.fiscal_year,
                obs.fiscal_period,
            )
            assert fact.period_end == obs.period_end
            assert (fact.form, fact.filed, fact.accession) == (obs.form, obs.filed, obs.accession)
            if spec.kind is MetricKind.DURATION:
                assert fact.period_start == obs.period_start
            else:
                assert fact.period_start is None


def test_revenue_provenance_survives_mapping() -> None:
    facts = adbe_facts()
    history = canonical_history_from_sec(facts, ticker="ADBE")
    latest = history.series_for("revenue").observations[0]
    sec_series = normalize_annual_revenue(facts, ticker="ADBE")
    assert latest.fiscal_year == 2025
    assert latest.provider == "sec"
    assert latest.provider_field == sec_series.concept == "Revenues"
    assert latest.accession == sec_series.observations[0].accession
    assert latest.form == "10-K"


def test_statuses_follow_sec_coverage_semantics() -> None:
    adbe = canonical_history_from_sec(adbe_facts(), ticker="ADBE")
    visa = canonical_history_from_sec(visa_facts(), ticker="V")

    shares = visa.series_for("diluted_shares")
    assert shares.status is MetricStatus.UNSUPPORTED
    assert isinstance(shares.error, ConceptNotFoundError)
    assert shares.reason == str(shares.error)
    assert adbe.series_for("dividends_paid").status is MetricStatus.STRUCTURALLY_ABSENT
    assert visa.series_for("short_term_investments").status is MetricStatus.STRUCTURALLY_ABSENT
    assert visa.series_for("current_debt").observations[0].provider_field == "LongTermDebtCurrent"
    assert visa.series_for("long_term_debt").observations[0].provider_field == (
        "LongTermDebtNoncurrent"
    )


def test_window_matches_existing_capital_efficiency_baseline() -> None:
    history = canonical_history_from_sec(adbe_facts(), ticker="adbe ", max_years=2)
    assert history.ticker == "ADBE"
    assert history.max_years == 2
    assert len(history.series_for("revenue").observations) == 2
    assert len(history.series_for("cash").observations) == 3


def _ambiguous_repurchases() -> dict[str, Any]:
    facts = adbe_facts()
    entries = facts["facts"]["us-gaap"]["PaymentsForRepurchaseOfCommonStock"]["units"]["USD"]
    conflict = dict(max(entries, key=lambda e: e["end"]))
    conflict["val"] += 1
    conflict["filed"] = "2026-03-01"
    entries.append(conflict)
    return facts


def test_ambiguity_is_stored_and_reraised_lazily() -> None:
    facts = _ambiguous_repurchases()
    history = canonical_history_from_sec(facts, ticker="ADBE")
    series = history.series_for("repurchases")
    assert series.status is MetricStatus.INVALID
    with pytest.raises(AmbiguousValueError) as raised:
        normalize_repurchases(facts, ticker="ADBE")
    with pytest.raises(AmbiguousValueError) as info:
        history.require("repurchases")
    assert str(info.value) == str(raised.value)
    assert history.series_for("revenue").status is MetricStatus.AVAILABLE


def test_malformed_payload_marks_every_metric_invalid() -> None:
    history = canonical_history_from_sec({"facts": {}}, ticker="ADBE")
    assert set(history.statuses().values()) == {MetricStatus.INVALID}
    with pytest.raises(MalformedFactsError):
        history.require("revenue")


def test_empty_ticker_fails_eagerly() -> None:
    with pytest.raises(ValueError):
        canonical_history_from_sec(adbe_facts(), ticker="  ")


def test_mapping_does_not_mutate_payload() -> None:
    facts = visa_facts()
    before = copy.deepcopy(facts)
    canonical_history_from_sec(facts, ticker="V")
    assert facts == before

"""Slice 6B: recency-aware SEC concept selection. Offline and deterministic.

A concept is eligible only if its newest qualifying observation covers the
company's latest fiscal year (the newest full-year FY duration period end in any
10-K-family filing, within ``RECENCY_TOLERANCE_DAYS``). Stale concepts are
skipped in preference order; if none is current the metric is unsupported.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens._annual import (
    RECENCY_TOLERANCE_DAYS,
    ConceptNotFoundError,
    is_current,
    latest_annual_period_end,
    select_annual_series,
    select_instant_series,
)
from owner_lens.canonical import MetricStatus
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.sec_adapter import canonical_history_from_sec

_M = 1_000_000


def _duration(concept: str, years: range | tuple[int, ...], value: int = 100 * _M,
              *, end_md: str = "11-30", start_md: str = "12-01") -> list[dict[str, Any]]:
    return [
        {"start": f"{y - 1}-{start_md}", "end": f"{y}-{end_md}", "val": value + y, "fy": y,
         "fp": "FY", "form": "10-K", "filed": f"{y + 1}-01-15", "accn": f"{concept}-{y}"}
        for y in years
    ]


def _instant(concept: str, years: range | tuple[int, ...], value: int = 100 * _M,
             *, end_md: str = "11-30") -> list[dict[str, Any]]:
    return [
        {"end": f"{y}-{end_md}", "val": value + y, "fy": y, "fp": "FY", "form": "10-K",
         "filed": f"{y + 1}-01-15", "accn": f"{concept}-{y}"}
        for y in years
    ]


def _with(facts: dict[str, Any], concept: str, entries: list[dict[str, Any]],
          unit: str = "USD") -> dict[str, Any]:
    facts["facts"]["us-gaap"][concept] = {"units": {unit: entries}}
    return facts


def _without(facts: dict[str, Any], *concepts: str) -> dict[str, Any]:
    for concept in concepts:
        del facts["facts"]["us-gaap"][concept]
    return facts


def _us_gaap(facts: dict[str, Any]) -> dict[str, Any]:
    return facts["facts"]["us-gaap"]


def _select(us_gaap: dict[str, Any], prefs: tuple[str, ...], *, instant: bool = False) -> str:
    select = select_instant_series if instant else select_annual_series
    concept, _ = select(us_gaap, prefs, max_years=5, concept_error=ConceptNotFoundError,
                        ambiguity_error=ValueError)
    return concept


# --- Company reference fiscal-year end ---------------------------------------------


def test_reference_is_latest_full_year_10k_period_end() -> None:
    assert latest_annual_period_end(_us_gaap(adbe_facts())) == date(2025, 11, 30)


def test_reference_ignores_quarterly_and_partial_periods() -> None:
    facts = adbe_facts()
    quarterly = {"start": "2025-12-01", "end": "2026-02-28", "val": 1, "fp": "Q1",
                 "form": "10-Q", "filed": "2026-03-15", "accn": "q"}
    short_fy = {"start": "2026-06-01", "end": "2026-11-30", "val": 1, "fp": "FY",
                "form": "10-K", "filed": "2027-01-15", "accn": "s"}
    eight_k = {**_duration("X", (2026,))[0], "form": "8-K"}
    _with(facts, "Noise", [quarterly, short_fy, eight_k])
    assert latest_annual_period_end(_us_gaap(facts)) == date(2025, 11, 30)


def test_reference_does_not_depend_on_the_calendar_year() -> None:
    # A payload ending in 2015 is judged against its own latest fiscal year.
    us_gaap = {"A": {"units": {"USD": _duration("A", range(2011, 2016))}},
               "B": {"units": {"USD": _duration("B", range(2008, 2013))}}}
    assert latest_annual_period_end(us_gaap) == date(2015, 11, 30)
    assert _select(us_gaap, ("B", "A")) == "A"


def test_tolerance_absorbs_52_53_week_drift_only() -> None:
    reference = date(2026, 1, 31)
    def obs(end: date) -> list[Any]:
        return [type("O", (), {"period_end": end})()]
    assert is_current(obs(date(2026, 1, 25)), reference)  # 6-day calendar drift
    assert is_current(obs(date(2025, 12, 31)), reference)  # exactly the tolerance
    assert RECENCY_TOLERANCE_DAYS == 31
    assert not is_current(obs(date(2025, 1, 26)), reference)  # prior fiscal year


# --- Selection rules ----------------------------------------------------------------


def test_current_preferred_concept_is_still_selected() -> None:
    us_gaap = _us_gaap(_with(adbe_facts(), "SalesRevenueNet", _duration("S", range(2021, 2026))))
    assert _select(us_gaap, ("Revenues", "SalesRevenueNet")) == "Revenues"


def test_stale_preferred_concept_falls_back_to_the_next_current_concept() -> None:
    facts = _with(adbe_facts(), "RevenueFromContractWithCustomerExcludingAssessedTax",
                  _duration("R", range(2018, 2023)))
    history = canonical_history_from_sec(facts, ticker="ADBE")
    revenue = history.series_for("revenue")
    assert revenue.status is MetricStatus.AVAILABLE
    assert {f.provider_field for f in revenue.observations} == {"Revenues"}
    assert [f.fiscal_year for f in revenue.observations] == [2025, 2024, 2023]


def test_multiple_current_concepts_preserve_preference_order() -> None:
    us_gaap = _us_gaap(adbe_facts())
    us_gaap["Stale"] = {"units": {"USD": _duration("Z", range(2010, 2015))}}
    us_gaap["Second"] = {"units": {"USD": _duration("S", range(2023, 2026))}}
    assert _select(us_gaap, ("Stale", "Revenues", "Second")) == "Revenues"
    assert _select(us_gaap, ("Stale", "Second", "Revenues")) == "Second"


def test_all_stale_concepts_are_unsupported_not_available() -> None:
    facts = _with(_without(adbe_facts(), "Revenues"), "SalesRevenueNet",
                  _duration("S", range(2008, 2013)))
    with pytest.raises(ConceptNotFoundError, match=r"Stale .*SalesRevenueNet \(last period end 2012-11-30\)"):
        _select(_us_gaap(facts), ("Revenues", "SalesRevenueNet"))
    history = canonical_history_from_sec(facts, ticker="ADBE")
    assert history.series_for("revenue").status is MetricStatus.UNSUPPORTED
    assert "company latest fiscal-year end 2025-11-30" in (history.series_for("revenue").reason or "")


def test_older_year_gaps_are_not_penalized() -> None:
    # A concept that legitimately starts recently is current; only the newest year matters.
    us_gaap = _us_gaap(adbe_facts())
    us_gaap["Young"] = {"units": {"USD": _duration("Y", (2025,))}}
    assert _select(us_gaap, ("Young", "Revenues")) == "Young"


def test_no_10k_reference_applies_no_recency_filter() -> None:
    # Without any 10-K full-year duration fact there is no reference to judge against.
    us_gaap = {"Assets": {"units": {"USD": _instant("A", range(2010, 2013))}}}
    assert latest_annual_period_end(us_gaap) is None
    assert _select(us_gaap, ("Assets",), instant=True) == "Assets"


# --- Instant metrics ------------------------------------------------------------------


def test_instant_stale_preferred_concept_falls_back() -> None:
    us_gaap = _us_gaap(_with(adbe_facts(), "OldCash", _instant("O", range(2014, 2020))))
    prefs = ("OldCash", "CashAndCashEquivalentsAtCarryingValue")
    assert _select(us_gaap, prefs, instant=True) == "CashAndCashEquivalentsAtCarryingValue"


def test_instant_all_stale_is_unsupported() -> None:
    facts = _with(adbe_facts(), "CashAndCashEquivalentsAtCarryingValue", _instant("C", range(2015, 2020)))
    history = canonical_history_from_sec(facts, ticker="ADBE")
    assert history.series_for("cash").status is MetricStatus.UNSUPPORTED


# --- Tolerant-of-absence metrics -----------------------------------------------------


def test_never_reported_dividends_stay_structurally_absent() -> None:
    history = canonical_history_from_sec(adbe_facts(), ticker="ADBE")
    assert history.series_for("dividends_paid").status is MetricStatus.STRUCTURALLY_ABSENT


def test_stale_only_dividends_are_unsupported_not_absent() -> None:
    facts = _with(adbe_facts(), "PaymentsOfDividendsCommonStock", _duration("D", range(2010, 2014)))
    history = canonical_history_from_sec(facts, ticker="ADBE")
    assert history.series_for("dividends_paid").status is MetricStatus.UNSUPPORTED


def test_stale_only_short_term_investments_are_unsupported_not_absent() -> None:
    # PFE pattern: ShortTermInvestments last reported FY2019 while the company still holds them.
    facts = _with(adbe_facts(), "ShortTermInvestments", _instant("STI", range(2016, 2020)))
    history = canonical_history_from_sec(facts, ticker="ADBE")
    assert history.series_for("short_term_investments").status is MetricStatus.UNSUPPORTED
    visa = canonical_history_from_sec(visa_facts(), ticker="V")
    assert visa.series_for("short_term_investments").status is MetricStatus.STRUCTURALLY_ABSENT


# --- Per-company overrides remain authoritative ---------------------------------------


def test_current_override_wins_over_a_current_default_concept() -> None:
    facts = _with(visa_facts(), "StockholdersEquity",
                  _instant("SE", range(2021, 2026), end_md="09-30"))
    history = canonical_history_from_sec(facts, ticker="V")
    assert {f.provider_field for f in history.series_for("total_equity").observations} == {
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    }


def test_stale_override_is_unsupported_and_never_falls_back_to_the_default() -> None:
    facts = visa_facts()
    _with(facts, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
          _instant("NCI", range(2015, 2020), end_md="09-30"))
    _with(facts, "StockholdersEquity", _instant("SE", range(2021, 2026), end_md="09-30"))
    history = canonical_history_from_sec(facts, ticker="V")
    assert history.series_for("total_equity").status is MetricStatus.UNSUPPORTED


def test_msft_debt_override_pair_is_unchanged_when_current() -> None:
    facts = _without(adbe_facts(), "DebtCurrent")
    _with(facts, "LongTermDebtCurrent", _instant("C", range(2022, 2026), 3_000 * _M))
    _with(facts, "LongTermDebtNoncurrent", _instant("N", range(2022, 2026), 40_000 * _M))
    history = canonical_history_from_sec(facts, ticker="MSFT")
    assert {f.provider_field for f in history.series_for("current_debt").observations} == {
        "LongTermDebtCurrent"
    }
    assert {f.provider_field for f in history.series_for("long_term_debt").observations} == {
        "LongTermDebtNoncurrent"
    }


# --- 6A stale patterns --------------------------------------------------------------


def test_nvda_pattern_revenue_contract_concept_stops_at_fy2022() -> None:
    # NVDA: RevenueFromContractWithCustomerExcludingAssessedTax last FY2022; Revenues current.
    facts = _with(adbe_facts(), "RevenueFromContractWithCustomerExcludingAssessedTax",
                  _duration("R", range(2019, 2023)))
    revenue = canonical_history_from_sec(facts, ticker="NVDA").series_for("revenue")
    assert revenue.observations[0].provider_field == "Revenues"
    assert revenue.observations[0].fiscal_year == 2025


def test_amzn_pattern_capex_ppe_concept_stops_at_fy2016() -> None:
    # AMZN: PaymentsToAcquirePropertyPlantAndEquipment last FY2016; productive assets current.
    facts = _with(adbe_facts(), "PaymentsToAcquirePropertyPlantAndEquipment",
                  _duration("P", range(2012, 2017)))
    _with(facts, "PaymentsToAcquireProductiveAssets", _duration("PA", range(2021, 2026)))
    capex = canonical_history_from_sec(facts, ticker="AMZN").series_for("capital_expenditures")
    assert {f.provider_field for f in capex.observations} == {"PaymentsToAcquireProductiveAssets"}
    assert max(f.fiscal_year for f in capex.observations) == 2025


def test_cat_pattern_net_income_concept_stops_at_fy2010() -> None:
    # CAT: NetIncomeLoss last FY2010 and no current alternative in the preference list.
    facts = _with(adbe_facts(), "NetIncomeLoss", _duration("N", range(2006, 2011)))
    history = canonical_history_from_sec(facts, ticker="CAT")
    assert history.series_for("net_income").status is MetricStatus.UNSUPPORTED
    with pytest.raises(ConceptNotFoundError, match="NetIncomeLoss"):
        owner_economics_from_history(history)


# --- Golden companies ------------------------------------------------------------------


@pytest.mark.parametrize(("ticker", "build"), [("ADBE", adbe_facts), ("V", visa_facts),
                                               ("COST", costco_facts)])
def test_golden_fixtures_have_no_stale_selection(ticker: str, build: Any) -> None:
    history = canonical_history_from_sec(build(), ticker=ticker)
    reference = latest_annual_period_end(_us_gaap(build()))
    assert reference is not None
    for series in history.series:
        if series.status is MetricStatus.AVAILABLE:
            assert max(f.period_end for f in series.observations) == reference

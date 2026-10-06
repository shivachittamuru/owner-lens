"""Controlled tests for fiscal-year-end instant balance-sheet normalization (Slice 1E)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens.balance_sheet import (
    AmbiguousValueError,
    ConceptNotFoundError,
    MalformedFactsError,
    normalize_cash,
    normalize_current_debt,
    normalize_long_term_debt,
    normalize_short_term_investments,
    normalize_total_assets,
    normalize_total_equity,
)
from owner_lens.reported import normalize_net_income


def _instant(
    year: int,
    val: int,
    *,
    filed: str,
    accn: str,
    form: str = "10-K",
    fy: int | None = None,
    fp: str = "FY",
) -> dict[str, Any]:
    # Instant facts have no start date.
    return {
        "end": f"{year}-11-30",
        "val": val,
        "fy": fy if fy is not None else year,
        "fp": fp,
        "form": form,
        "filed": filed,
        "accn": accn,
    }


def _duration(year: int, val: int, *, filed: str, accn: str) -> dict[str, Any]:
    return {
        "start": f"{year - 1}-12-01",
        "end": f"{year}-11-30",
        "val": val,
        "fy": year,
        "fp": "FY",
        "form": "10-K",
        "filed": filed,
        "accn": accn,
    }


def _facts(concept: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cik": 796343,
        "entityName": "ADOBE INC.",
        "facts": {"us-gaap": {concept: {"units": {"USD": entries}}}},
    }


def test_instant_selected_by_period_end() -> None:
    facts = _facts("Assets", [_instant(2025, 29496000000, filed="2026-01-15", accn="a-2025")])

    obs = normalize_total_assets(facts).observations[0]

    assert obs.fiscal_year == 2025
    assert obs.period_end == date(2025, 11, 30)
    assert obs.period_start == obs.period_end  # instant facts collapse start to end


def test_duration_fact_is_not_selected_as_instant() -> None:
    # A concept holding only a duration fact yields no instant observation.
    facts = _facts("Assets", [_duration(2025, 29496000000, filed="2026-01-15", accn="d-2025")])

    with pytest.raises(ConceptNotFoundError):
        normalize_total_assets(facts)


def test_instant_only_concept_is_not_selected_by_duration_path() -> None:
    # The duration normalizer must ignore instant facts (no start date).
    facts = _facts("NetIncomeLoss", [_instant(2025, 7130000000, filed="2026-01-15", accn="i-2025")])

    with pytest.raises(ConceptNotFoundError):
        normalize_net_income(facts)


def test_total_assets_happy_path_newest_first() -> None:
    facts = _facts(
        "Assets",
        [
            _instant(2024, 30230000000, filed="2025-01-13", accn="a-2024"),
            _instant(2025, 29496000000, filed="2026-01-15", accn="a-2025"),
        ],
    )

    series = normalize_total_assets(facts)

    assert [o.fiscal_year for o in series.observations] == [2025, 2024]
    assert series.observations[0].value == 29496000000


def test_total_equity_with_baseline_year() -> None:
    facts = _facts(
        "StockholdersEquity",
        [
            _instant(2023, 16518000000, filed="2024-01-17", accn="e-2023"),
            _instant(2024, 14105000000, filed="2025-01-13", accn="e-2024"),
            _instant(2025, 11623000000, filed="2026-01-15", accn="e-2025"),
        ],
    )

    series = normalize_total_equity(facts, max_years=6)

    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023]


def test_interim_excluded_and_comparatives_collapse() -> None:
    facts = _facts(
        "CashAndCashEquivalentsAtCarryingValue",
        [
            _instant(2024, 7613000000, filed="2025-01-13", accn="c-2024", fy=2024),
            # Comparative repeat of FY2024 in the FY2025 10-K, same value.
            _instant(2024, 7613000000, filed="2026-01-15", accn="c-2025c", fy=2025),
            # Interim quarter-end instant, must be excluded.
            {
                "end": "2025-02-28",
                "val": 6000000000,
                "fy": 2025,
                "fp": "Q1",
                "form": "10-Q",
                "filed": "2025-03-19",
                "accn": "q1",
            },
        ],
    )

    series = normalize_cash(facts)

    assert [o.fiscal_year for o in series.observations] == [2024]
    obs = series.observations[0]
    assert obs.filed == date(2025, 1, 13)
    assert obs.accession == "c-2024"


def test_provenance_is_fully_populated() -> None:
    facts = _facts(
        "StockholdersEquity", [_instant(2025, 11623000000, filed="2026-01-15", accn="e-2025")]
    )

    obs = normalize_total_equity(facts).observations[0]

    assert obs.concept == "StockholdersEquity"
    assert obs.unit == "USD"
    assert obs.fiscal_year == 2025
    assert obs.fiscal_period == "FY"
    assert obs.period_end == date(2025, 11, 30)
    assert obs.form == "10-K"
    assert obs.filed == date(2026, 1, 15)
    assert obs.accession == "e-2025"


def test_conflicting_values_fail_with_year() -> None:
    facts = _facts(
        "Assets",
        [
            _instant(2025, 29496000000, filed="2026-01-15", accn="a"),
            _instant(2025, 29000000000, filed="2026-02-01", accn="b"),
        ],
    )

    with pytest.raises(AmbiguousValueError, match="2025"):
        normalize_total_assets(facts)


def test_missing_concept_fails() -> None:
    facts = _facts("SomethingElse", [_instant(2025, 1, filed="2026-01-15", accn="x")])

    with pytest.raises(ConceptNotFoundError):
        normalize_total_assets(facts)


def test_non_adobe_ticker_is_accepted_as_label() -> None:
    facts = _facts("Assets", [_instant(2025, 1, filed="2026-01-15", accn="x")])

    series = normalize_total_assets(facts, ticker="MSFT")

    assert series.ticker == "MSFT"
    assert series.observations[0].value == 1


def test_malformed_payload_fails() -> None:
    with pytest.raises(MalformedFactsError):
        normalize_total_assets({"cik": 796343, "entityName": "ADOBE INC.", "facts": {}})


def test_multi_company_cash_assets_equity_normalize() -> None:
    for facts, ticker, cash, assets, equity in (
        (adbe_facts(), "ADBE", 5431000000, 29496000000, 11623000000),
        (visa_facts(), "V", 17164000000, 99627000000, 37909000000),
        (costco_facts(), "COST", 14161000000, 77099000000, 29164000000),
    ):
        assert normalize_cash(facts, ticker=ticker).observations[0].value == cash
        assert normalize_total_assets(facts, ticker=ticker).observations[0].value == assets
        assert normalize_total_equity(facts, ticker=ticker).observations[0].value == equity


def test_visa_equity_uses_including_noncontrolling_interest_override() -> None:
    series = normalize_total_equity(visa_facts(), ticker="V")

    assert series.concept == (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    )
    assert series.metric == "total_equity"
    assert series.ticker == "V"


def test_visa_and_costco_debt_use_current_noncurrent_split_without_double_count() -> None:
    for facts, ticker, current, noncurrent in (
        (visa_facts(), "V", 5569000000, 19602000000),
        (costco_facts(), "COST", 75000000, 5713000000),
    ):
        cur = normalize_current_debt(facts, ticker=ticker)
        lt = normalize_long_term_debt(facts, ticker=ticker)
        assert cur.concept == "LongTermDebtCurrent"
        assert lt.concept == "LongTermDebtNoncurrent"
        assert cur.observations[0].value == current
        assert lt.observations[0].value == noncurrent
        # LongTermDebtNoncurrent excludes the current portion, so the sum is total
        # debt with no double count.
        assert cur.observations[0].value + lt.observations[0].value == current + noncurrent


def test_adobe_debt_keeps_default_concepts() -> None:
    facts = adbe_facts()

    assert normalize_current_debt(facts, ticker="ADBE").concept == "DebtCurrent"
    assert normalize_long_term_debt(facts, ticker="ADBE").concept == "LongTermDebt"
    assert normalize_long_term_debt(facts, ticker="ADBE").observations[0].value == 6210000000


def test_visa_short_term_investments_absent_by_policy() -> None:
    # Visa reports no ShortTermInvestments concept; its investment securities are
    # deliberately not absorbed as corporate cash -> tolerant empty series.
    series = normalize_short_term_investments(visa_facts(), ticker="V")

    assert series.observations == ()
    assert series.concept == ""


def test_costco_short_term_investments_present() -> None:
    series = normalize_short_term_investments(costco_facts(), ticker="COST")

    assert series.concept == "ShortTermInvestments"
    assert series.observations[0].value == 1123000000


# MSFT FY2023-FY2025 debt as filed (millions): LongTermDebt is the TOTAL including
# the current portion, so pairing it with LongTermDebtCurrent would double count.
_MSFT_DEBT = {
    "LongTermDebtCurrent": {2023: 5247, 2024: 2249, 2025: 2999},
    "LongTermDebtNoncurrent": {2023: 41990, 2024: 42688, 2025: 40152},
    "LongTermDebt": {2023: 47237, 2024: 44937, 2025: 43151},
}


def _msft_like_facts() -> dict[str, Any]:
    """ADBE fixture with Microsoft's debt tagging: no DebtCurrent, total LongTermDebt."""
    facts = adbe_facts()
    us_gaap = facts["facts"]["us-gaap"]
    del us_gaap["DebtCurrent"]
    for concept, values in _MSFT_DEBT.items():
        us_gaap[concept] = {
            "units": {
                "USD": [
                    _instant(year, val * 1_000_000, filed=f"{year + 1}-07-30", accn=f"{concept}-{year}")
                    for year, val in values.items()
                ]
            }
        }
    return facts


def test_msft_debt_uses_current_noncurrent_split_without_double_count() -> None:
    from owner_lens.capital_efficiency import capital_efficiency_from_facts

    facts = _msft_like_facts()
    cur = normalize_current_debt(facts, ticker="MSFT")
    lt = normalize_long_term_debt(facts, ticker="MSFT")
    assert cur.concept == "LongTermDebtCurrent"
    assert lt.concept == "LongTermDebtNoncurrent"

    rows = {row.fiscal_year: row for row in capital_efficiency_from_facts(facts, ticker="MSFT")}
    for year in (2025, 2024, 2023):
        current = _MSFT_DEBT["LongTermDebtCurrent"][year] * 1_000_000
        noncurrent = _MSFT_DEBT["LongTermDebtNoncurrent"][year] * 1_000_000
        double_counted = current + _MSFT_DEBT["LongTermDebt"][year] * 1_000_000
        assert rows[year].total_debt == current + noncurrent
        assert rows[year].total_debt == _MSFT_DEBT["LongTermDebt"][year] * 1_000_000
        assert rows[year].total_debt != double_counted
    assert rows[2025].roic is not None


def test_msft_override_does_not_affect_other_filers_with_the_same_tagging() -> None:
    # The override is keyed by ticker: another filer with identical tagging keeps
    # the default concepts (and fails loudly without DebtCurrent), unchanged.
    facts = _msft_like_facts()
    assert normalize_long_term_debt(facts, ticker="CRM").concept == "LongTermDebt"
    with pytest.raises(ConceptNotFoundError):
        normalize_current_debt(facts, ticker="CRM")

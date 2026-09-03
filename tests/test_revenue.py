"""Controlled tests for Adobe annual revenue normalization."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from owner_lens.revenue import (
    AmbiguousRevenueError,
    MalformedFactsError,
    RevenueConceptNotFoundError,
    normalize_annual_revenue,
)


def _fact(
    *,
    start: str,
    end: str,
    val: int,
    fy: int,
    fp: str = "FY",
    form: str = "10-K",
    filed: str,
    accn: str,
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "val": val,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": filed,
        "accn": accn,
    }


def _annual_fact(year: int, val: int, *, filed: str, accn: str, form: str = "10-K", fy: int | None = None) -> dict[str, Any]:
    # Adobe-style fiscal year: begins early December, ends late November.
    return _fact(
        start=f"{year - 1}-12-01",
        end=f"{year}-11-30",
        val=val,
        fy=fy if fy is not None else year,
        form=form,
        filed=filed,
        accn=accn,
    )


def _facts(concepts: dict[str, list[dict[str, Any]]], *, unit: str = "USD") -> dict[str, Any]:
    return {
        "cik": 796343,
        "entityName": "ADOBE INC.",
        "facts": {
            "us-gaap": {
                concept: {"units": {unit: entries}}
                for concept, entries in concepts.items()
            }
        },
    }


def test_happy_path_returns_one_observation_per_year_newest_first() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2021, 15785000000, filed="2022-01-14", accn="a-2021"),
                _annual_fact(2022, 17606000000, filed="2023-01-13", accn="a-2022"),
                _annual_fact(2023, 19409000000, filed="2024-01-17", accn="a-2023"),
                _annual_fact(2024, 21505000000, filed="2025-01-13", accn="a-2024"),
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025"),
            ]
        }
    )

    series = normalize_annual_revenue(facts)

    assert series.ticker == "ADBE"
    assert series.concept == "Revenues"
    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023, 2022, 2021]
    assert [o.value for o in series.observations] == [
        23769000000,
        21505000000,
        19409000000,
        17606000000,
        15785000000,
    ]
    newest = series.observations[0]
    assert newest.concept == "Revenues"
    assert newest.unit == "USD"
    assert newest.fiscal_period == "FY"
    assert newest.period_start == date(2024, 12, 1)
    assert newest.period_end == date(2025, 11, 30)
    assert newest.form == "10-K"
    assert newest.filed == date(2026, 1, 15)
    assert newest.accession == "a-2025"


def test_only_latest_five_years_are_returned() -> None:
    entries = [
        _annual_fact(year, year * 1000, filed=f"{year + 1}-01-15", accn=f"a-{year}")
        for year in range(2018, 2026)
    ]
    facts = _facts({"Revenues": entries})

    series = normalize_annual_revenue(facts)

    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023, 2022, 2021]


def test_fewer_than_five_years_returns_all_available() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2023, 19409000000, filed="2024-01-17", accn="a-2023"),
                _annual_fact(2024, 21505000000, filed="2025-01-13", accn="a-2024"),
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025"),
            ]
        }
    )

    series = normalize_annual_revenue(facts)

    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023]


def test_quarterly_and_ytd_observations_are_excluded() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025"),
                # Q1 quarterly (~91 days)
                _fact(
                    start="2024-11-30",
                    end="2025-02-28",
                    val=5710000000,
                    fy=2025,
                    fp="Q1",
                    form="10-Q",
                    filed="2025-03-19",
                    accn="q1-2025",
                ),
                # YTD partial (~273 days) but tagged FY should still be excluded by duration
                _fact(
                    start="2024-11-30",
                    end="2025-08-29",
                    val=17000000000,
                    fy=2025,
                    fp="FY",
                    form="10-Q",
                    filed="2025-09-18",
                    accn="ytd-2025",
                ),
            ]
        }
    )

    series = normalize_annual_revenue(facts)

    assert [o.fiscal_year for o in series.observations] == [2025]
    assert series.observations[0].value == 23769000000


def test_identical_comparative_repeats_collapse_to_earliest_filing() -> None:
    facts = _facts(
        {
            "Revenues": [
                # FY2023 reported originally, then repeated as comparatives.
                _annual_fact(2023, 19409000000, filed="2024-01-17", accn="a-2023", fy=2023),
                _annual_fact(2023, 19409000000, filed="2025-01-13", accn="a-2024", fy=2024),
                _annual_fact(2023, 19409000000, filed="2026-01-15", accn="a-2025", fy=2025),
            ]
        }
    )

    series = normalize_annual_revenue(facts)

    assert len(series.observations) == 1
    obs = series.observations[0]
    assert obs.fiscal_year == 2023
    assert obs.value == 19409000000
    assert obs.filed == date(2024, 1, 17)
    assert obs.accession == "a-2023"


def test_amended_filing_repeat_collapses_to_one_year() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2024, 21505000000, filed="2025-01-13", accn="a-2024", form="10-K"),
                _annual_fact(2024, 21505000000, filed="2025-03-01", accn="a-2024-amend", form="10-K/A"),
            ]
        }
    )

    series = normalize_annual_revenue(facts)

    assert len(series.observations) == 1
    obs = series.observations[0]
    assert obs.fiscal_year == 2024
    assert obs.form == "10-K"
    assert obs.accession == "a-2024"


def test_conflicting_values_for_a_year_fail_explicitly() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2024, 21505000000, filed="2025-01-13", accn="a-2024"),
                _annual_fact(2024, 21000000000, filed="2025-03-01", accn="a-2024-restated"),
            ]
        }
    )

    with pytest.raises(AmbiguousRevenueError, match="2024"):
        normalize_annual_revenue(facts)


def test_missing_revenue_concept_fails_explicitly() -> None:
    facts = _facts(
        {
            "CostOfRevenue": [
                _annual_fact(2025, 9000000000, filed="2026-01-15", accn="cor-2025"),
            ]
        }
    )

    with pytest.raises(RevenueConceptNotFoundError):
        normalize_annual_revenue(facts)


def test_concept_with_only_quarterly_is_skipped_for_next_preference() -> None:
    facts = _facts(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                _fact(
                    start="2024-11-30",
                    end="2025-02-28",
                    val=5710000000,
                    fy=2025,
                    fp="Q1",
                    form="10-Q",
                    filed="2025-03-19",
                    accn="q1-2025",
                ),
            ],
            "Revenues": [
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025"),
            ],
        }
    )

    series = normalize_annual_revenue(facts)

    assert series.concept == "Revenues"
    assert series.observations[0].value == 23769000000


def test_preferred_contract_revenue_concept_wins_when_qualified() -> None:
    facts = _facts(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="rc-2025"),
            ],
            "Revenues": [
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="rev-2025"),
            ],
        }
    )

    series = normalize_annual_revenue(facts)

    assert series.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert series.observations[0].accession == "rc-2025"


def test_non_usd_units_are_ignored() -> None:
    facts = _facts(
        {
            "Revenues": [
                _annual_fact(2025, 23769000000, filed="2026-01-15", accn="usd-2025"),
            ]
        }
    )
    # Add a CAD unit with a different value for the same concept.
    facts["facts"]["us-gaap"]["Revenues"]["units"]["CAD"] = [
        _annual_fact(2025, 31000000000, filed="2026-01-15", accn="cad-2025"),
    ]

    series = normalize_annual_revenue(facts)

    assert series.observations[0].unit == "USD"
    assert series.observations[0].value == 23769000000


def test_malformed_payload_without_us_gaap_fails() -> None:
    with pytest.raises(MalformedFactsError):
        normalize_annual_revenue({"cik": 796343, "entityName": "ADOBE INC.", "facts": {}})


def test_non_adobe_ticker_is_accepted_as_label() -> None:
    facts = _facts(
        {"Revenues": [_annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025")]}
    )

    series = normalize_annual_revenue(facts, ticker="MSFT")

    assert series.ticker == "MSFT"
    assert series.observations[0].value == 23769000000


def test_ticker_is_case_and_whitespace_insensitive() -> None:
    facts = _facts(
        {"Revenues": [_annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025")]}
    )

    series = normalize_annual_revenue(facts, ticker="  adbe ")

    assert series.ticker == "ADBE"


def test_annual_fact_missing_required_field_is_malformed() -> None:
    bad = _annual_fact(2025, 23769000000, filed="2026-01-15", accn="a-2025")
    del bad["accn"]
    facts = _facts({"Revenues": [bad]})

    with pytest.raises(MalformedFactsError, match="accn"):
        normalize_annual_revenue(facts)


def test_visa_and_costco_revenue_use_contract_concept() -> None:
    from _fixtures import costco_facts, visa_facts

    v = normalize_annual_revenue(visa_facts(), ticker="V")
    assert v.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert v.observations[0].value == 40000000000

    cost = normalize_annual_revenue(costco_facts(), ticker="COST")
    assert cost.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert cost.observations[0].value == 275235000000

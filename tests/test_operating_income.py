"""Controlled tests for Adobe annual operating income normalization."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from owner_lens.operating_income import (
    AmbiguousOperatingIncomeError,
    MalformedFactsError,
    OperatingIncomeConceptNotFoundError,
    normalize_annual_operating_income,
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


def _annual_fact(
    year: int,
    val: int,
    *,
    filed: str,
    accn: str,
    form: str = "10-K",
    fy: int | None = None,
) -> dict[str, Any]:
    return _fact(
        start=f"{year - 1}-12-01",
        end=f"{year}-11-30",
        val=val,
        fy=fy if fy is not None else year,
        form=form,
        filed=filed,
        accn=accn,
    )


def _facts(entries: list[dict[str, Any]], *, concept: str = "OperatingIncomeLoss") -> dict[str, Any]:
    return {
        "cik": 796343,
        "entityName": "ADOBE INC.",
        "facts": {"us-gaap": {concept: {"units": {"USD": entries}}}},
    }


def test_happy_path_returns_one_observation_per_year_newest_first() -> None:
    facts = _facts(
        [
            _annual_fact(2021, 5802000000, filed="2022-01-14", accn="a-2021"),
            _annual_fact(2022, 6098000000, filed="2023-01-13", accn="a-2022"),
            _annual_fact(2023, 6650000000, filed="2024-01-17", accn="a-2023"),
            _annual_fact(2024, 6741000000, filed="2025-01-13", accn="a-2024"),
            _annual_fact(2025, 8706000000, filed="2026-01-15", accn="a-2025"),
        ]
    )

    series = normalize_annual_operating_income(facts)

    assert series.ticker == "ADBE"
    assert series.concept == "OperatingIncomeLoss"
    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023, 2022, 2021]
    assert [o.value for o in series.observations] == [
        8706000000,
        6741000000,
        6650000000,
        6098000000,
        5802000000,
    ]
    newest = series.observations[0]
    assert newest.concept == "OperatingIncomeLoss"
    assert newest.unit == "USD"
    assert newest.fiscal_period == "FY"
    assert newest.period_end == date(2025, 11, 30)
    assert newest.accession == "a-2025"


def test_only_latest_five_years_are_returned() -> None:
    entries = [
        _annual_fact(year, year * 1000, filed=f"{year + 1}-01-15", accn=f"a-{year}")
        for year in range(2018, 2026)
    ]
    series = normalize_annual_operating_income(_facts(entries))

    assert [o.fiscal_year for o in series.observations] == [2025, 2024, 2023, 2022, 2021]


def test_fewer_than_five_years_returns_all_available() -> None:
    facts = _facts(
        [
            _annual_fact(2024, 6741000000, filed="2025-01-13", accn="a-2024"),
            _annual_fact(2025, 8706000000, filed="2026-01-15", accn="a-2025"),
        ]
    )

    series = normalize_annual_operating_income(facts)

    assert [o.fiscal_year for o in series.observations] == [2025, 2024]


def test_quarterly_and_ytd_observations_are_excluded() -> None:
    facts = _facts(
        [
            _annual_fact(2025, 8706000000, filed="2026-01-15", accn="a-2025"),
            _fact(
                start="2024-11-30",
                end="2025-02-28",
                val=2000000000,
                fy=2025,
                fp="Q1",
                form="10-Q",
                filed="2025-03-19",
                accn="q1-2025",
            ),
            _fact(
                start="2024-11-30",
                end="2025-08-29",
                val=6000000000,
                fy=2025,
                fp="FY",
                form="10-Q",
                filed="2025-09-18",
                accn="ytd-2025",
            ),
        ]
    )

    series = normalize_annual_operating_income(facts)

    assert [o.fiscal_year for o in series.observations] == [2025]
    assert series.observations[0].value == 8706000000


def test_identical_comparative_repeats_collapse_to_earliest_filing() -> None:
    facts = _facts(
        [
            _annual_fact(2023, 6650000000, filed="2024-01-17", accn="a-2023", fy=2023),
            _annual_fact(2023, 6650000000, filed="2025-01-13", accn="a-2024", fy=2024),
            _annual_fact(2023, 6650000000, filed="2026-01-15", accn="a-2025", fy=2025),
        ]
    )

    series = normalize_annual_operating_income(facts)

    assert len(series.observations) == 1
    obs = series.observations[0]
    assert obs.fiscal_year == 2023
    assert obs.value == 6650000000
    assert obs.filed == date(2024, 1, 17)
    assert obs.accession == "a-2023"


def test_negative_operating_income_is_preserved() -> None:
    facts = _facts(
        [_annual_fact(2025, -1200000000, filed="2026-01-15", accn="a-2025")]
    )

    series = normalize_annual_operating_income(facts)

    assert series.observations[0].value == -1200000000


def test_conflicting_values_for_a_year_fail_explicitly() -> None:
    facts = _facts(
        [
            _annual_fact(2024, 6741000000, filed="2025-01-13", accn="a-2024"),
            _annual_fact(2024, 6700000000, filed="2025-03-01", accn="a-2024-restated"),
        ]
    )

    with pytest.raises(AmbiguousOperatingIncomeError, match="2024"):
        normalize_annual_operating_income(facts)


def test_missing_operating_income_concept_fails_explicitly() -> None:
    facts = _facts(
        [_annual_fact(2025, 9000000000, filed="2026-01-15", accn="rev-2025")],
        concept="Revenues",
    )

    with pytest.raises(OperatingIncomeConceptNotFoundError):
        normalize_annual_operating_income(facts)


def test_non_adobe_ticker_is_accepted_as_label() -> None:
    facts = _facts([_annual_fact(2025, 8706000000, filed="2026-01-15", accn="a-2025")])

    series = normalize_annual_operating_income(facts, ticker="MSFT")

    assert series.ticker == "MSFT"
    assert series.observations[0].value == 8706000000


def test_malformed_payload_without_us_gaap_fails() -> None:
    with pytest.raises(MalformedFactsError):
        normalize_annual_operating_income({"cik": 796343, "entityName": "ADOBE INC.", "facts": {}})


def test_visa_and_costco_operating_income_use_shared_concept() -> None:
    from _fixtures import costco_facts, visa_facts

    v = normalize_annual_operating_income(visa_facts(), ticker="V")
    assert v.concept == "OperatingIncomeLoss"
    assert v.observations[0].value == 23994000000

    cost = normalize_annual_operating_income(costco_facts(), ticker="COST")
    assert cost.concept == "OperatingIncomeLoss"
    assert cost.observations[0].value == 10383000000

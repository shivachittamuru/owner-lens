"""Controlled tests for fiscal-year-end instant balance-sheet normalization (Slice 1E)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from owner_lens.balance_sheet import (
    AmbiguousValueError,
    ConceptNotFoundError,
    MalformedFactsError,
    UnsupportedTickerError,
    normalize_cash,
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


def test_unsupported_ticker_rejected() -> None:
    facts = _facts("Assets", [_instant(2025, 1, filed="2026-01-15", accn="x")])

    with pytest.raises(UnsupportedTickerError):
        normalize_total_assets(facts, ticker="MSFT")


def test_malformed_payload_fails() -> None:
    with pytest.raises(MalformedFactsError):
        normalize_total_assets({"cik": 796343, "entityName": "ADOBE INC.", "facts": {}})

"""Tests for duration reported-metric specs, including the tax-rate inputs."""

from __future__ import annotations

from typing import Any

import pytest

from owner_lens.reported import (
    ConceptNotFoundError,
    normalize_diluted_shares,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_pretax_income,
)


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


def _facts(concept: str, entries: list[dict[str, Any]], *, unit: str = "USD") -> dict[str, Any]:
    return {
        "cik": 796343,
        "entityName": "ADOBE INC.",
        "facts": {"us-gaap": {concept: {"units": {unit: entries}}}},
    }


def test_income_tax_expense_selection() -> None:
    facts = _facts(
        "IncomeTaxExpenseBenefit",
        [_duration(2025, 1000000000, filed="2026-01-15", accn="tax-2025")],
    )

    series = normalize_income_tax_expense(facts)

    assert series.concept == "IncomeTaxExpenseBenefit"
    assert series.observations[0].value == 1000000000


def test_pretax_income_primary_concept() -> None:
    facts = _facts(
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        [_duration(2025, 8000000000, filed="2026-01-15", accn="pt-2025")],
    )

    series = normalize_pretax_income(facts)

    assert series.observations[0].value == 8000000000


def test_pretax_income_falls_back_to_secondary_concept() -> None:
    facts = _facts(
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        [_duration(2020, 3200000000, filed="2021-01-15", accn="pt2-2020")],
    )

    series = normalize_pretax_income(facts)

    assert series.concept == (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
    )


def test_net_income_happy_path() -> None:
    facts = _facts("NetIncomeLoss", [_duration(2025, 7130000000, filed="2026-01-15", accn="ni")])

    assert normalize_net_income(facts).observations[0].value == 7130000000


def test_diluted_shares_missing_concept_fails() -> None:
    facts = _facts("NetIncomeLoss", [_duration(2025, 1, filed="2026-01-15", accn="x")])

    with pytest.raises(ConceptNotFoundError):
        normalize_diluted_shares(facts)

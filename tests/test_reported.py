"""Tests for duration reported-metric specs, including the tax-rate inputs."""

from __future__ import annotations

from typing import Any

import pytest

from owner_lens.reported import (
    ConceptNotFoundError,
    normalize_diluted_shares,
    normalize_dividends_paid,
    normalize_income_tax_expense,
    normalize_net_income,
    normalize_pretax_income,
    normalize_repurchases,
    normalize_stock_based_compensation,
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


def test_repurchases_selection_and_provenance() -> None:
    facts = _facts(
        "PaymentsForRepurchaseOfCommonStock",
        [
            _duration(2025, 11281000000, filed="2026-01-15", accn="repo-2025"),
            _duration(2024, 9500000000, filed="2025-01-15", accn="repo-2024"),
        ],
    )

    series = normalize_repurchases(facts)

    assert series.concept == "PaymentsForRepurchaseOfCommonStock"
    assert [o.value for o in series.observations] == [11281000000, 9500000000]
    assert series.observations[0].accession == "repo-2025"


def test_repurchases_collapses_comparative_repeat_to_earliest_filed() -> None:
    facts = _facts(
        "PaymentsForRepurchaseOfCommonStock",
        [
            _duration(2024, 9500000000, filed="2025-01-15", accn="repo-2024-orig"),
            _duration(2024, 9500000000, filed="2026-01-15", accn="repo-2024-comp"),
        ],
    )

    series = normalize_repurchases(facts)

    assert len(series.observations) == 1
    assert series.observations[0].accession == "repo-2024-orig"


def test_stock_based_compensation_prefers_cash_flow_concept() -> None:
    facts = {
        "cik": 796343,
        "entityName": "ADOBE INC.",
        "facts": {
            "us-gaap": {
                "ShareBasedCompensation": {
                    "units": {"USD": [_duration(2025, 1942000000, filed="2026-01-15", accn="sbc")]}
                },
                "AllocatedShareBasedCompensationExpense": {
                    "units": {"USD": [_duration(2025, 1942000000, filed="2026-01-15", accn="sbc2")]}
                },
            }
        },
    }

    series = normalize_stock_based_compensation(facts)

    assert series.concept == "ShareBasedCompensation"
    assert series.observations[0].value == 1942000000


def test_stock_based_compensation_falls_back_to_allocated_concept() -> None:
    facts = _facts(
        "AllocatedShareBasedCompensationExpense",
        [_duration(2021, 1090000000, filed="2022-01-15", accn="sbc-alloc")],
    )

    series = normalize_stock_based_compensation(facts)

    assert series.concept == "AllocatedShareBasedCompensationExpense"


def test_dividends_absent_concept_returns_empty_series() -> None:
    facts = _facts(
        "PaymentsForRepurchaseOfCommonStock",
        [_duration(2025, 11281000000, filed="2026-01-15", accn="repo")],
    )

    series = normalize_dividends_paid(facts)

    assert series.observations == ()
    assert series.concept == ""


def test_dividends_present_zero_is_preserved_distinctly() -> None:
    facts = _facts(
        "PaymentsOfDividendsCommonStock",
        [_duration(2025, 0, filed="2026-01-15", accn="div-2025")],
    )

    series = normalize_dividends_paid(facts)

    assert len(series.observations) == 1
    assert series.observations[0].value == 0
    assert series.concept == "PaymentsOfDividendsCommonStock"


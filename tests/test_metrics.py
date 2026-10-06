"""Tests for the canonical metric registry and per-company concept resolution."""

from __future__ import annotations

from owner_lens.metrics import (
    CAPITAL_EXPENDITURES,
    CASH,
    CURRENT_DEBT,
    DILUTED_SHARES,
    DIVIDENDS_PAID,
    INCOME_TAX_EXPENSE,
    LONG_TERM_DEBT,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    OPERATING_INCOME,
    PRETAX_INCOME,
    REPURCHASES,
    REVENUE,
    SHORT_TERM_INVESTMENTS,
    STOCK_BASED_COMPENSATION,
    TOTAL_ASSETS,
    TOTAL_EQUITY,
    CanonicalMetricDefinition,
    resolve_concepts,
)

ALL_DEFINITIONS: tuple[CanonicalMetricDefinition, ...] = (
    REVENUE,
    OPERATING_INCOME,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    CAPITAL_EXPENDITURES,
    DILUTED_SHARES,
    INCOME_TAX_EXPENSE,
    PRETAX_INCOME,
    REPURCHASES,
    STOCK_BASED_COMPENSATION,
    DIVIDENDS_PAID,
    CASH,
    SHORT_TERM_INVESTMENTS,
    CURRENT_DEBT,
    LONG_TERM_DEBT,
    TOTAL_ASSETS,
    TOTAL_EQUITY,
)


def test_default_resolution_when_no_override() -> None:
    assert resolve_concepts(REVENUE, "COST") == REVENUE.default_concepts
    assert resolve_concepts(CASH, "V") == CASH.default_concepts


def test_current_debt_needs_no_per_company_override() -> None:
    # Slice 6D: V, COST, and MSFT resolve through the shared component policy.
    assert resolve_concepts(CURRENT_DEBT, "V") == ("DebtCurrent",)
    assert resolve_concepts(CURRENT_DEBT, "COST") == ("DebtCurrent",)
    assert resolve_concepts(CURRENT_DEBT, "ADBE") == ("DebtCurrent",)
    assert CURRENT_DEBT.overrides == {}
    assert CURRENT_DEBT.composition is not None
    assert CURRENT_DEBT.composition.components[0] == "LongTermDebtCurrent"


def test_long_term_debt_override_for_v_and_cost() -> None:
    assert resolve_concepts(LONG_TERM_DEBT, "V") == ("LongTermDebtNoncurrent",)
    assert resolve_concepts(LONG_TERM_DEBT, "COST") == ("LongTermDebtNoncurrent",)
    assert resolve_concepts(LONG_TERM_DEBT, "ADBE") == ("LongTermDebt",)


def test_total_equity_override_only_for_visa() -> None:
    assert resolve_concepts(TOTAL_EQUITY, "V") == (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    )
    assert resolve_concepts(TOTAL_EQUITY, "ADBE") == ("StockholdersEquity",)
    assert resolve_concepts(TOTAL_EQUITY, "COST") == ("StockholdersEquity",)


def test_resolution_canonicalizes_ticker_case_and_whitespace() -> None:
    assert resolve_concepts(LONG_TERM_DEBT, "  v ") == ("LongTermDebtNoncurrent",)
    assert resolve_concepts(LONG_TERM_DEBT, "cost") == ("LongTermDebtNoncurrent",)


def test_resolution_is_deterministic() -> None:
    assert resolve_concepts(LONG_TERM_DEBT, "V") == resolve_concepts(LONG_TERM_DEBT, "V")


def test_adobe_resolves_default_concepts_for_every_metric() -> None:
    # Adobe must never take an override path, preserving its original selection.
    for definition in ALL_DEFINITIONS:
        assert resolve_concepts(definition, "ADBE") == definition.default_concepts


def test_every_override_is_scoped_and_excludes_adobe() -> None:
    for definition in ALL_DEFINITIONS:
        for ticker, concepts in definition.overrides.items():
            assert ticker == ticker.strip().upper()
            assert ticker != "ADBE"
            assert isinstance(concepts, tuple)
            assert concepts, f"{definition.name} override for {ticker} is empty"


def test_only_debt_and_equity_carry_overrides() -> None:
    with_overrides = {d.name for d in ALL_DEFINITIONS if d.overrides}
    assert with_overrides == {"long_term_debt", "total_equity"}


def test_only_current_debt_declares_a_composition() -> None:
    assert {d.name for d in ALL_DEFINITIONS if d.composition} == {"current_debt"}

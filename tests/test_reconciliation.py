"""Tests for SEC-vs-FMP canonical reconciliation (Slice 5C). Offline and deterministic.

The SEC ADBE fixture and the mocked FMP fixture carry identical reported values,
so each test perturbs one side to exercise exactly one rule.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _fixtures import adbe_facts
from _fmp_fixtures import fmp_payloads, fmp_statements, with_field

from owner_lens.canonical import CanonicalFinancialHistory, MetricStatus
from owner_lens.fmp_adapter import canonical_history_from_fmp
from owner_lens.known_discrepancies import KNOWN_DISCREPANCIES
from owner_lens.reconciliation import (
    CORE_METRICS,
    ROUNDING_TOLERANCE,
    DiscrepancyCategory,
    Eligibility,
    FactReconciliation,
    KnownDiscrepancy,
    ReconciliationReport,
    ReconciliationStatus,
    format_reconciliation_report,
    reconcile_histories,
)
from owner_lens.sec_adapter import canonical_history_from_sec

S = ReconciliationStatus
C = DiscrepancyCategory
_M = 1_000_000


def _sec(facts: dict[str, Any] | None = None) -> CanonicalFinancialHistory:
    return canonical_history_from_sec(facts or adbe_facts(), ticker="ADBE")


def _fmp(payloads: dict[str, list[dict[str, Any]]] | None = None) -> CanonicalFinancialHistory:
    return canonical_history_from_fmp(fmp_statements(payloads=payloads))


def _reconcile(
    payloads: dict[str, list[dict[str, Any]]] | None = None,
    *,
    sec_facts: dict[str, Any] | None = None,
    explanations: tuple[KnownDiscrepancy, ...] = (),
) -> ReconciliationReport:
    return reconcile_histories(_sec(sec_facts), _fmp(payloads), explanations=explanations)


def _fact(report: ReconciliationReport, metric: str, year: int | None) -> FactReconciliation:
    return next(r for r in report.facts if r.metric == metric and r.fiscal_year == year)


def _derived(report: ReconciliationReport, output: str, year: int | None):
    return next(r for r in report.derived if r.output == output and r.fiscal_year == year)


def _explain(metric: str, year: int | None, *, trusted: bool, category: C = C.PROVIDER_NORMALIZATION):
    return KnownDiscrepancy(
        ticker="ADBE",
        metric=metric,
        fiscal_year=year,
        category=category,
        explanation="documented test explanation",
        evidence="test evidence",
        fmp_trusted=trusted,
    )


# --- Identical sources ----------------------------------------------------------


def test_identical_reported_values_reconcile_completely() -> None:
    report = _reconcile()
    statuses = {row.status for row in report.facts}
    assert statuses == {S.MATCH}
    assert _fact(report, "dividends_paid", None).reason == "structurally absent in both providers"
    assert {row.status for row in report.derived} == {S.MATCH}
    summary = report.summary()
    assert summary.total_facts_compared == 16 * 3
    assert summary.count(S.MATCH) == len(report.facts)
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.ELIGIBLE
    assert verdict.blocking == verdict.explained_material == ()


def test_mismatched_tickers_fail_loudly() -> None:
    other = canonical_history_from_fmp(fmp_statements("MSFT", payloads=fmp_payloads("MSFT")))
    with pytest.raises(ValueError, match="different companies"):
        reconcile_histories(_sec(), other)


# --- Rounding tolerance only ----------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "status", "category"),
    [
        (ROUNDING_TOLERANCE, S.WITHIN_TOLERANCE, C.ROUNDING),
        (-ROUNDING_TOLERANCE, S.WITHIN_TOLERANCE, C.ROUNDING),
        (ROUNDING_TOLERANCE + 1, S.REVIEW, C.SOURCE_DISCREPANCY),
        (49 * _M, S.REVIEW, C.SOURCE_DISCREPANCY),
    ],
)
def test_usd_tolerance_is_rounding_only(delta: int, status: S, category: C) -> None:
    report = _reconcile(with_field("income-statement", "revenue", {2025: 23769 * _M + delta}))
    row = _fact(report, "revenue", 2025)
    assert (row.status, row.category, row.difference) == (status, category, delta)
    assert row.material is (status is S.REVIEW)


def test_share_rounding_propagates_to_per_share_outputs_as_rounding() -> None:
    report = _reconcile(
        with_field("income-statement", "weightedAverageShsOutDil", {2024: 449_700_000 + 300_000})
    )
    assert _fact(report, "diluted_shares", 2024).status is S.WITHIN_TOLERANCE
    fps = _derived(report, "fcf_per_share", 2024)
    assert fps.status is S.WITHIN_TOLERANCE
    assert fps.category is C.ROUNDING
    assert fps.traced_to == (("diluted_shares", 2024),)
    assert report.verdict().eligibility is Eligibility.ELIGIBLE


def test_large_share_difference_is_review() -> None:
    report = _reconcile(
        with_field("income-statement", "weightedAverageShsOutDil", {2024: 449_700_000 + 600_000})
    )
    assert _fact(report, "diluted_shares", 2024).status is S.REVIEW


# --- Material differences and documented explanations --------------------------

_CAPEX_GAP = with_field("cash-flow-statement", "investmentsInPropertyPlantAndEquipment", {2024: -232 * _M})


def test_unexplained_material_difference_blocks_eligibility_and_traces_to_fcf() -> None:
    report = _reconcile(_CAPEX_GAP)
    capex = _fact(report, "capital_expenditures", 2024)
    assert (capex.status, capex.difference) == (S.REVIEW, 49 * _M)
    fcf = _derived(report, "free_cash_flow", 2024)
    assert fcf.status is S.REVIEW
    assert fcf.difference == -49 * _M
    assert ("capital_expenditures", 2024) in fcf.traced_to
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.NOT_ELIGIBLE
    assert any("capital_expenditures FY2024: unexplained REVIEW" in b for b in verdict.blocking)


def test_explanation_turns_review_into_explained_without_hiding_it() -> None:
    report = _reconcile(_CAPEX_GAP, explanations=(_explain("capital_expenditures", 2024, trusted=True),))
    capex = _fact(report, "capital_expenditures", 2024)
    assert capex.status is S.EXPLAINED
    assert capex.category is C.PROVIDER_NORMALIZATION
    assert capex.difference == 49 * _M
    assert capex.explanation is not None
    assert _derived(report, "free_cash_flow", 2024).status is S.EXPLAINED
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.ELIGIBLE_WITH_EXPLAINED_DIFFERENCES
    assert verdict.explained_material == ("capital_expenditures FY2024: PROVIDER_NORMALIZATION",)


def test_explained_but_untrusted_core_fact_is_not_eligible() -> None:
    assert "capital_expenditures" in CORE_METRICS
    report = _reconcile(_CAPEX_GAP, explanations=(_explain("capital_expenditures", 2024, trusted=False),))
    assert _fact(report, "capital_expenditures", 2024).status is S.EXPLAINED
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.NOT_ELIGIBLE
    assert verdict.blocking == (
        "capital_expenditures FY2024: core fact not trustworthy from FMP (PROVIDER_NORMALIZATION)",
    )


def test_explained_untrusted_non_core_fact_does_not_block() -> None:
    report = _reconcile(
        with_field("cash-flow-statement", "stockBasedCompensation", {2024: 1881 * _M}),
        explanations=(_explain("stock_based_compensation", 2024, trusted=False),),
    )
    assert report.verdict().eligibility is Eligibility.ELIGIBLE_WITH_EXPLAINED_DIFFERENCES


def test_stale_explanation_is_reported_and_blocks() -> None:
    stale = _explain("revenue", 2025, trusted=True)
    report = _reconcile(explanations=(stale,))
    assert report.unused_explanations == (stale,)
    assert _fact(report, "revenue", 2025).explanation is None
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.NOT_ELIGIBLE
    assert any("stale explanation revenue FY2025" in b for b in verdict.blocking)


def test_explanations_for_other_tickers_are_ignored() -> None:
    other = KnownDiscrepancy("MSFT", "revenue", 2025, C.ROUNDING, "x", "y", fmp_trusted=True)
    assert _reconcile(explanations=(other,)).unused_explanations == ()


# --- One-sided, semantic, invalid, and timing rows ------------------------------


def test_window_timing_is_one_sided_and_immaterial() -> None:
    payloads = fmp_payloads()
    for endpoint in payloads:
        payloads[endpoint] = [r for r in payloads[endpoint] if r["fiscalYear"] != "2023"]
    report = _reconcile(payloads)
    row = _fact(report, "revenue", 2023)
    assert (row.status, row.category, row.material) == (S.SEC_ONLY, C.PERIOD_TIMING, False)
    assert "outside FMP's available years FY2024-FY2025" in row.reason
    roic = _derived(report, "roic", 2024)
    assert roic.status is S.SEC_ONLY
    assert roic.category is C.PERIOD_TIMING
    assert report.verdict().eligibility is Eligibility.ELIGIBLE


def test_gap_inside_window_is_material_source_discrepancy() -> None:
    report = _reconcile(with_field("cash-flow-statement", "stockBasedCompensation", {2024: None}))
    row = _fact(report, "stock_based_compensation", 2024)
    assert (row.status, row.category, row.material) == (S.SEC_ONLY, C.SOURCE_DISCREPANCY, True)


def test_unsupported_on_one_side_is_explicit_never_substituted() -> None:
    sec_facts = adbe_facts()
    del sec_facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]
    report = _reconcile(sec_facts=sec_facts)
    row = _fact(report, "diluted_shares", 2025)
    assert (row.status, row.category, row.material) == (S.FMP_ONLY, C.UNSUPPORTED, True)
    assert row.sec_status is MetricStatus.UNSUPPORTED
    assert row.sec_fact is None and row.fmp_fact is not None
    fps = _derived(report, "fcf_per_share", 2025)
    assert (fps.sec_value, fps.status, fps.category) == (None, S.FMP_ONLY, C.UNSUPPORTED)


def test_absent_versus_available_is_semantic_difference() -> None:
    report = _reconcile(
        with_field("cash-flow-statement", "commonDividendsPaid", {2025: -500 * _M})
    )
    row = _fact(report, "dividends_paid", 2025)
    assert (row.status, row.category) == (S.SEMANTIC_DIFFERENCE, C.POLICY_DIFFERENCE)
    assert row.sec_status is MetricStatus.STRUCTURALLY_ABSENT


def test_invalid_series_is_uncomparable_and_blocks() -> None:
    report = _reconcile(
        with_field("cash-flow-statement", "commonStockRepurchased", {2025: 5 * _M})
    )
    row = _fact(report, "repurchases", None)
    assert (row.status, row.category) == (S.UNCOMPARABLE, C.INVALID)
    assert "FMP:" in row.reason and "positive" in row.reason
    overall = _derived(report, "overall_classification", None)
    assert overall.status is S.UNCOMPARABLE
    assert "FMP cannot compute" in overall.reason
    verdict = report.verdict()
    assert verdict.eligibility is Eligibility.NOT_ELIGIBLE
    assert verdict.unassessed


def _shift_period_end(days: int) -> dict[str, list[dict[str, Any]]]:
    from datetime import date, timedelta

    payloads = copy.deepcopy(fmp_payloads())
    for row in payloads["income-statement"]:
        if row["fiscalYear"] == "2025":
            row["date"] = (date(2025, 11, 30) + timedelta(days=days)).isoformat()
    return payloads


def test_period_end_gap_beyond_window_is_uncomparable() -> None:
    row = _fact(_reconcile(_shift_period_end(15)), "revenue", 2025)
    assert (row.status, row.category, row.material) == (S.UNCOMPARABLE, C.PERIOD_TIMING, True)


def test_small_period_end_gap_with_equal_value_still_matches() -> None:
    row = _fact(_reconcile(_shift_period_end(-1)), "revenue", 2025)
    assert row.status is S.MATCH
    assert "period ends differ by 1 days" in row.reason


# --- Provenance and reporting ---------------------------------------------------


def test_material_rows_carry_inspectable_provenance() -> None:
    report = _reconcile(_CAPEX_GAP)
    row = _fact(report, "capital_expenditures", 2024)
    assert row.sec_fact is not None and row.fmp_fact is not None
    assert row.sec_fact.provider == "sec"
    assert row.sec_fact.provider_field == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert row.sec_fact.accession == "PaymentsToAcquirePropertyPlantAndEquipment-2024"
    assert row.fmp_fact.provider == "fmp"
    assert row.fmp_fact.provider_field == "investmentsInPropertyPlantAndEquipment"
    text = format_reconciliation_report(report)
    assert "PaymentsToAcquirePropertyPlantAndEquipment-2024" in text
    assert "investmentsInPropertyPlantAndEquipment" in text
    assert "REVIEW" in text and "Blocking:" in text
    assert "revenue" not in text.split("Derived")[0].split("Reason", 1)[1]


def test_summary_counts_by_status_and_category() -> None:
    report = _reconcile(_CAPEX_GAP)
    summary = report.summary()
    assert summary.count(S.REVIEW) == 1
    assert summary.by_category[C.SOURCE_DISCREPANCY] == 1
    assert summary.derived_by_status[S.REVIEW] >= 1


def test_known_discrepancies_are_well_formed() -> None:
    keys = [(k.ticker, k.metric, k.fiscal_year) for k in KNOWN_DISCREPANCIES]
    assert len(keys) == len(set(keys))
    for known in KNOWN_DISCREPANCIES:
        assert known.explanation and known.evidence
        assert known.category not in (C.NONE, C.ROUNDING)
        assert known.ticker in {"ADBE", "V", "COST", "MSFT"}

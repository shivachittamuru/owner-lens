"""Slice 6D: current-debt normalization and composition. Offline, deterministic.

Current debt resolves from a total concept, else from the registry's additive
components, else from proof of absence in the company's own totals. Lease
liabilities are never summed, and a concept that bundles leases with borrowings
refuses composition rather than understating or widening the metric.
"""

from __future__ import annotations

from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens._annual import ConceptNotFoundError
from owner_lens.canonical import MetricStatus
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.metrics import CURRENT_DEBT
from owner_lens.persistence.adapters import _fact_record
from owner_lens.sec_adapter import canonical_history_from_sec

_M = 1_000_000
_YEARS = (2021, 2022, 2023, 2024, 2025)


def _instant(year: int, value: int, *, accn: str | None = None) -> dict[str, Any]:
    return {"end": f"{year}-11-30", "val": value, "fy": year, "fp": "FY", "form": "10-K",
            "filed": f"{year + 1}-01-15", "accn": accn or f"a-{year}"}


def _facts(**concepts: dict[int, int] | None) -> dict[str, Any]:
    """ADBE fixture with DebtCurrent removed and the given concepts installed."""
    facts = adbe_facts()
    del facts["facts"]["us-gaap"]["DebtCurrent"]
    for concept, values in concepts.items():
        if values is None:
            facts["facts"]["us-gaap"].pop(concept, None)
            continue
        facts["facts"]["us-gaap"][concept] = {
            "units": {"USD": [_instant(y, v) for y, v in values.items()]}
        }
    return facts


def _series(facts: dict[str, Any], ticker: str = "ADBE") -> Any:
    return canonical_history_from_sec(facts, ticker=ticker).series_for("current_debt")


def _by_year(facts: dict[str, Any], ticker: str = "ADBE") -> dict[int, Any]:
    return {f.fiscal_year: f for f in _series(facts, ticker).observations}


# --- 1. Single concept -----------------------------------------------------------


def test_total_concept_resolves_normally() -> None:
    series = _series(adbe_facts())
    assert series.status is MetricStatus.AVAILABLE
    assert {f.provider_field for f in series.observations} == {"DebtCurrent"}
    assert all(not f.components for f in series.observations)


def test_single_component_needs_no_override() -> None:
    # V, COST, CRM, INTU, and CAT all reach current debt this way.
    years = _by_year(_facts(LongTermDebtCurrent=dict.fromkeys(_YEARS, 10 * _M)))
    assert years[2025].provider_field == "LongTermDebtCurrent"
    assert years[2025].value == 10 * _M and not years[2025].components
    assert CURRENT_DEBT.overrides == {}


def test_a_component_reported_only_as_short_term_borrowings_resolves() -> None:
    years = _by_year(_facts(ShortTermBorrowings=dict.fromkeys(_YEARS, 5_514 * _M)))
    assert years[2025].provider_field == "ShortTermBorrowings"


# --- 2 & 3. Composition ------------------------------------------------------------


def test_two_components_are_added_with_per_component_provenance() -> None:
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_748 * _M),
        ShortTermBorrowings=dict.fromkeys(_YEARS, 455 * _M),
    )
    fact = _by_year(facts)[2025]
    assert fact.value == 3_203 * _M
    assert fact.provider_field == "LongTermDebtCurrent + ShortTermBorrowings"
    assert [(c.provider_field, c.value) for c in fact.components] == [
        ("LongTermDebtCurrent", 2_748 * _M), ("ShortTermBorrowings", 455 * _M)
    ]
    for component in fact.components:
        assert component.form == "10-K" and component.filed is not None
        assert component.accession == "a-2025"


def test_msft_fy2024_commercial_paper_is_included_and_other_years_are_unchanged() -> None:
    facts = _facts(
        LongTermDebtCurrent={2023: 5_247 * _M, 2024: 2_249 * _M, 2025: 2_999 * _M},
        CommercialPaper={2023: 0, 2024: 6_693 * _M, 2025: 0},
        LongTermDebtNoncurrent={2023: 41_990 * _M, 2024: 42_688 * _M, 2025: 40_152 * _M},
    )
    years = _by_year(facts, "MSFT")
    assert years[2024].value == 8_942 * _M
    assert [(c.provider_field, c.value) for c in years[2024].components] == [
        ("LongTermDebtCurrent", 2_249 * _M), ("CommercialPaper", 6_693 * _M)
    ]
    # A zero component contributes nothing, so those years stay single-source.
    for year, value in ((2025, 2_999 * _M), (2023, 5_247 * _M)):
        assert (years[year].value, years[year].provider_field) == (value, "LongTermDebtCurrent")
        assert not years[year].components


def test_composed_debt_flows_into_capital_efficiency() -> None:
    facts = _facts(
        LongTermDebtCurrent={2023: 5_247 * _M, 2024: 2_249 * _M, 2025: 2_999 * _M},
        CommercialPaper={2023: 0, 2024: 6_693 * _M, 2025: 0},
        LongTermDebtNoncurrent={2023: 41_990 * _M, 2024: 42_688 * _M, 2025: 40_152 * _M},
    )
    history = canonical_history_from_sec(facts, ticker="MSFT")
    rows = {row.fiscal_year: row for row in capital_efficiency_from_history(history)}
    assert rows[2024].total_debt == (2_249 + 6_693 + 42_688) * _M
    assert rows[2024].roic is not None


def test_all_zero_components_stay_a_reported_zero() -> None:
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 0),
        CommercialPaper=dict.fromkeys(_YEARS, 0),
    )
    fact = _by_year(facts)[2025]
    assert (fact.value, fact.provider_field, fact.components) == (0, "LongTermDebtCurrent", ())
    assert _series(facts).status is MetricStatus.AVAILABLE


# --- 4. No double counting ----------------------------------------------------------


def test_a_reported_total_wins_and_is_never_summed_with_its_components() -> None:
    # ADBE FY2024 reports DebtCurrent 1,499M and LongTermDebtCurrent 1,500M for the
    # same balance; the total must win rather than the two being added.
    facts = adbe_facts()
    facts["facts"]["us-gaap"]["LongTermDebtCurrent"] = {
        "units": {"USD": [_instant(2024, 1_500 * _M)]}
    }
    facts["facts"]["us-gaap"]["CommercialPaper"] = {
        "units": {"USD": [_instant(2024, 900 * _M)]}
    }
    years = _by_year(facts)
    assert years[2024].value == 1_499 * _M
    assert years[2024].provider_field == "DebtCurrent"


def test_components_that_restate_rather_than_add_are_not_summed() -> None:
    # CRM reports ConvertibleDebtCurrent equal to its whole LongTermDebtCurrent.
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 4_000 * _M),
        ConvertibleDebtCurrent=dict.fromkeys(_YEARS, 4_000 * _M),
        NotesPayableCurrent=dict.fromkeys(_YEARS, 4_000 * _M),
        LinesOfCreditCurrent=dict.fromkeys(_YEARS, 4_000 * _M),
    )
    fact = _by_year(facts, "CRM")[2025]
    assert fact.value == 4_000 * _M and not fact.components


# --- 5. Structural absence ------------------------------------------------------------


def test_absence_is_proven_when_all_debt_is_noncurrent() -> None:
    # META: LongTermDebt equals LongTermDebtNoncurrent, so the current portion is zero.
    facts = _facts(
        LongTermDebt=dict.fromkeys(_YEARS, 58_744 * _M),
        LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 58_744 * _M),
    )
    series = _series(facts)
    assert series.status is MetricStatus.STRUCTURALLY_ABSENT
    assert series.observations == ()
    assert "structurally absent" in (series.reason or "")


def test_absence_is_proven_when_the_company_reports_no_debt_at_all() -> None:
    # CMG reports LongTermDebt 0.
    series = _series(_facts(LongTermDebt=dict.fromkeys(_YEARS, 0)))
    assert series.status is MetricStatus.STRUCTURALLY_ABSENT


def test_structurally_absent_current_debt_still_yields_capital_efficiency() -> None:
    facts = _facts(
        LongTermDebt=dict.fromkeys(_YEARS, 58_744 * _M),
        LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 58_744 * _M),
    )
    history = canonical_history_from_sec(facts, ticker="META")
    rows = {row.fiscal_year: row for row in capital_efficiency_from_history(history)}
    assert rows[2025].total_debt == 58_744 * _M  # absent current debt contributes nothing
    assert rows[2025].current_debt is None


def test_absence_is_never_inferred_from_a_missing_tag() -> None:
    # NOW and LULU: no current-debt concept and no debt totals to prove absence.
    series = _series(_facts())
    assert series.status is MetricStatus.UNSUPPORTED
    assert "No supported US-GAAP concept" in (series.reason or "")


def test_a_total_that_exceeds_its_noncurrent_part_does_not_prove_absence() -> None:
    series = _series(_facts(
        LongTermDebt=dict.fromkeys(_YEARS, 10_000 * _M),
        LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 9_000 * _M),
    ))
    assert series.status is MetricStatus.UNSUPPORTED


# --- 6 & 7. Uncertain evidence and lease liabilities -------------------------------------


@pytest.mark.parametrize(
    "lease_concept",
    ["OperatingLeaseLiabilityCurrent", "FinanceLeaseLiabilityCurrent",
     "CapitalLeaseObligationsCurrent"],
)
def test_lease_liabilities_are_never_added_to_debt(lease_concept: str) -> None:
    facts = _facts(LongTermDebtCurrent=dict.fromkeys(_YEARS, 75 * _M))
    facts["facts"]["us-gaap"][lease_concept] = {
        "units": {"USD": [_instant(y, 286 * _M) for y in _YEARS]}
    }
    fact = _by_year(facts)[2025]
    assert fact.value == 75 * _M  # the 5C Costco/FMP lease difference stays excluded
    assert not fact.components


def test_lease_only_company_has_no_current_debt_rather_than_lease_debt() -> None:
    facts = _facts()
    facts["facts"]["us-gaap"]["OperatingLeaseLiabilityCurrent"] = {
        "units": {"USD": [_instant(y, 300 * _M) for y in _YEARS]}
    }
    assert _series(facts).status is MetricStatus.UNSUPPORTED


def test_a_concept_bundling_debt_with_leases_refuses_composition() -> None:
    # HD, KO, and LOW: the current portion of debt is hidden inside the bundle, so
    # composing only commercial paper would understate it.
    facts = _facts(
        CommercialPaper=dict.fromkeys(_YEARS, 4_464 * _M),
        LongTermDebtAndCapitalLeaseObligationsCurrent=dict.fromkeys(_YEARS, 4_967 * _M),
    )
    series = _series(facts)
    assert series.status is MetricStatus.UNSUPPORTED
    assert "LongTermDebtAndCapitalLeaseObligationsCurrent" in (series.reason or "")
    assert "bundles economics this metric excludes" in (series.reason or "")


def test_a_zero_bundle_does_not_refuse_composition() -> None:
    facts = _facts(
        CommercialPaper=dict.fromkeys(_YEARS, 4_464 * _M),
        LongTermDebtAndCapitalLeaseObligationsCurrent=dict.fromkeys(_YEARS, 0),
    )
    assert _by_year(facts)[2025].value == 4_464 * _M


# --- 8. Recency and conflict resolution still apply to components -------------------------


def test_a_component_set_that_stops_before_the_latest_year_is_stale() -> None:
    facts = _facts(LongTermDebtCurrent={2018: 10 * _M, 2019: 10 * _M, 2020: 10 * _M})
    series = _series(facts)
    assert series.status is MetricStatus.UNSUPPORTED
    assert "Stale (no value for the latest fiscal year)" in (series.reason or "")


def test_a_stale_component_still_contributes_to_the_years_it_covers() -> None:
    # NKE: ShortTermBorrowings stopped in FY2024 but the composite stays current.
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_000 * _M),
        ShortTermBorrowings={2023: 6 * _M, 2024: 6 * _M},
    )
    years = _by_year(facts)
    assert years[2025].value == 2_000 * _M and not years[2025].components
    assert years[2024].value == 2_006 * _M


def test_a_precision_restatement_inside_a_component_is_resolved_before_summing() -> None:
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_249_141_000),
        CommercialPaper=dict.fromkeys(_YEARS, 6_693 * _M),
    )
    facts["facts"]["us-gaap"]["LongTermDebtCurrent"]["units"]["USD"].append(
        {**_instant(2025, 2_249_000_000, accn="restated"), "filed": "2027-01-15"}
    )
    fact = _by_year(facts)[2025]
    assert fact.value == 2_249_141_000 + 6_693 * _M


def test_a_genuine_conflict_inside_a_component_still_fails_loudly() -> None:
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_249 * _M),
        CommercialPaper=dict.fromkeys(_YEARS, 6_693 * _M),
    )
    facts["facts"]["us-gaap"]["CommercialPaper"]["units"]["USD"].append(
        {**_instant(2025, 5_000 * _M, accn="revised"), "filed": "2027-01-15"}
    )
    series = _series(facts)
    assert series.status is MetricStatus.INVALID
    assert "conflicting CommercialPaper values" in (series.reason or "")


# --- 9. Persistence provenance ----------------------------------------------------------


def test_a_persisted_composed_fact_names_every_component_and_value() -> None:
    facts = _facts(
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_249 * _M),
        CommercialPaper=dict.fromkeys(_YEARS, 6_693 * _M),
    )
    record = _fact_record("1", "current_debt", _by_year(facts)[2025], "instant")
    assert record.concept == "LongTermDebtCurrent 2249000000 + CommercialPaper 6693000000"
    assert record.value == 8_942 * _M
    assert record.accession == "a-2025"


def test_a_single_source_fact_keeps_its_plain_concept() -> None:
    facts = _facts(LongTermDebtCurrent=dict.fromkeys(_YEARS, 75 * _M))
    record = _fact_record("1", "current_debt", _by_year(facts)[2025], "instant")
    assert record.concept == "LongTermDebtCurrent"


# --- 10. Golden companies -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticker", "build", "concept"),
    [("ADBE", adbe_facts, "DebtCurrent"), ("V", visa_facts, "LongTermDebtCurrent"),
     ("COST", costco_facts, "LongTermDebtCurrent")],
)
def test_golden_companies_resolve_from_a_single_concept_unchanged(
    ticker: str, build: Any, concept: str
) -> None:
    series = canonical_history_from_sec(build(), ticker=ticker).series_for("current_debt")
    assert series.status is MetricStatus.AVAILABLE
    assert {f.provider_field for f in series.observations} == {concept}
    assert all(not f.components for f in series.observations)


def test_unknown_metrics_keep_single_concept_selection() -> None:
    # A metric with no composition policy still fails on its own concept list.
    facts = adbe_facts()
    del facts["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]
    with pytest.raises(ConceptNotFoundError, match="Tried: CashAndCashEquivalentsAtCarryingValue."):
        canonical_history_from_sec(facts, ticker="ADBE").require("cash")

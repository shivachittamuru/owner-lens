"""Slice 6E: canonical alternative-concept policy. Offline and deterministic.

Each recurring SEC alternative the 6A-6D survey surfaced was evaluated and
recorded in ``ALTERNATIVE_CONCEPT_POLICY``. Only a ``SAFE_EQUIVALENT`` verdict is
adopted; every other verdict must stay un-adopted, which these tests enforce so
coverage pressure cannot quietly widen a metric's meaning later.
"""

from __future__ import annotations

from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

import owner_lens.metrics as metrics_module
from owner_lens.canonical import MetricStatus
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.metrics import (
    ALTERNATIVE_CONCEPT_POLICY,
    LONG_TERM_DEBT,
    AlternativeConcept,
    CanonicalMetricDefinition,
    ConceptDecision,
    adopted_alternatives,
    resolve_concepts,
)
from owner_lens.sec_adapter import canonical_history_from_sec

ALL_DEFINITIONS: tuple[CanonicalMetricDefinition, ...] = tuple(
    value for value in vars(metrics_module).values()
    if isinstance(value, CanonicalMetricDefinition)
)

_M = 1_000_000
_YEARS = (2021, 2022, 2023, 2024, 2025)


def _instant(year: int, value: int, *, filed: str | None = None,
             accn: str | None = None) -> dict[str, Any]:
    return {"end": f"{year}-11-30", "val": value, "fy": year, "fp": "FY", "form": "10-K",
            "filed": filed or f"{year + 1}-01-15", "accn": accn or f"a-{year}"}


def _facts(**concepts: dict[int, int] | None) -> dict[str, Any]:
    facts = adbe_facts()
    for concept, values in concepts.items():
        if values is None:
            facts["facts"]["us-gaap"].pop(concept, None)
            continue
        facts["facts"]["us-gaap"][concept] = {
            "units": {"USD": [_instant(y, v) for y, v in values.items()]}
        }
    return facts


def _series(facts: dict[str, Any], metric: str, ticker: str = "ADBE") -> Any:
    return canonical_history_from_sec(facts, ticker=ticker).series_for(metric)


def _fields(facts: dict[str, Any], metric: str, ticker: str = "ADBE") -> set[str]:
    return {f.provider_field for f in _series(facts, metric, ticker).observations}


# --- The policy register --------------------------------------------------------


def test_every_evaluated_concept_has_a_verdict_and_evidence() -> None:
    assert ALTERNATIVE_CONCEPT_POLICY
    for entry in ALTERNATIVE_CONCEPT_POLICY:
        assert isinstance(entry, AlternativeConcept)
        assert entry.metric in {d.name for d in ALL_DEFINITIONS}
        assert len(entry.rationale) > 80 and len(entry.evidence) > 40
        assert entry.adopted is (entry.decision is ConceptDecision.SAFE_EQUIVALENT)


def test_only_safe_equivalents_appear_in_any_concept_preference() -> None:
    selectable = {
        concept
        for definition in ALL_DEFINITIONS
        for concept in (*definition.default_concepts,
                        *(c for o in definition.overrides.values() for c in o))
    }
    for entry in ALTERNATIVE_CONCEPT_POLICY:
        if entry.adopted:
            assert entry.concept in selectable, f"{entry.concept} adopted but unused"
        elif entry.decision is not ConceptDecision.CONTEXT_DEPENDENT:
            assert entry.concept not in selectable, f"{entry.concept} must not be selectable"


def test_the_only_adopted_concept_is_noncurrent_long_term_debt() -> None:
    adopted = [e.concept for e in ALTERNATIVE_CONCEPT_POLICY if e.adopted]
    assert adopted == ["LongTermDebtNoncurrent"]
    assert adopted_alternatives("long_term_debt") == ("LongTermDebtNoncurrent",)
    assert adopted_alternatives("cash") == ()


# --- Adopted: LongTermDebtNoncurrent ---------------------------------------------


def test_noncurrent_debt_is_preferred_and_needs_no_override() -> None:
    assert LONG_TERM_DEBT.default_concepts == ("LongTermDebtNoncurrent", "LongTermDebt")
    assert LONG_TERM_DEBT.overrides == {}
    for ticker in ("ADBE", "V", "COST", "MSFT", "NVDA"):
        assert resolve_concepts(LONG_TERM_DEBT, ticker)[0] == "LongTermDebtNoncurrent"


def test_total_long_term_debt_is_no_longer_double_counted_with_current_debt() -> None:
    # NVDA pattern: LongTermDebt 8,468 = LongTermDebtNoncurrent 7,469 + current 999.
    facts = _facts(
        DebtCurrent=dict.fromkeys(_YEARS, 999 * _M),
        LongTermDebt=dict.fromkeys(_YEARS, 8_468 * _M),
        LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 7_469 * _M),
    )
    history = canonical_history_from_sec(facts, ticker="NVDA")
    assert {f.provider_field for f in history.series_for("long_term_debt").observations} == {
        "LongTermDebtNoncurrent"
    }
    rows = {row.fiscal_year: row for row in capital_efficiency_from_history(history)}
    assert rows[2025].total_debt == 8_468 * _M  # the filed total, not 9,467M
    assert rows[2025].total_debt != (999 + 8_468) * _M


def test_filers_without_a_noncurrent_concept_keep_long_term_debt() -> None:
    # ADBE, HD, and LOW report only LongTermDebt, as their noncurrent line.
    facts = _facts(LongTermDebtNoncurrent=None)
    assert _fields(facts, "long_term_debt") == {"LongTermDebt"}


def test_a_stale_noncurrent_concept_falls_back_to_the_current_total() -> None:
    # 6B recency still governs the order: a stale preferred concept is skipped.
    facts = _facts(
        LongTermDebtNoncurrent={2016: 5_000 * _M, 2017: 5_000 * _M, 2018: 5_000 * _M},
        LongTermDebt=dict.fromkeys(_YEARS, 8_468 * _M),
    )
    assert _fields(facts, "long_term_debt") == {"LongTermDebt"}


def test_a_conflicting_noncurrent_restatement_still_follows_the_6c_rules() -> None:
    facts = _facts(LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 7_469_141_000))
    entries = facts["facts"]["us-gaap"]["LongTermDebtNoncurrent"]["units"]["USD"]
    entries.append(_instant(2025, 7_469_000_000, filed="2027-01-15", accn="reround"))
    assert _series(facts, "long_term_debt").status is MetricStatus.AVAILABLE
    entries.append(_instant(2025, 7_000_000_000, filed="2028-01-15", accn="revised"))
    assert _series(facts, "long_term_debt").status is MetricStatus.INVALID


def test_current_debt_composition_from_6d_is_unchanged() -> None:
    facts = _facts(
        DebtCurrent=None,
        LongTermDebtCurrent=dict.fromkeys(_YEARS, 2_249 * _M),
        CommercialPaper=dict.fromkeys(_YEARS, 6_693 * _M),
        LongTermDebtNoncurrent=dict.fromkeys(_YEARS, 42_688 * _M),
    )
    series = _series(facts, "current_debt", "MSFT")
    assert series.observations[0].value == 8_942 * _M
    assert len(series.observations[0].components) == 2


# --- Rejected: ProfitLoss ----------------------------------------------------------


def test_profit_loss_is_never_used_as_net_income() -> None:
    # UNH pattern: ProfitLoss is 6.2% higher because it includes minority interests.
    facts = adbe_facts()
    facts["facts"]["us-gaap"]["ProfitLoss"] = {
        "units": {"USD": [{"start": f"{y - 1}-12-01", "end": f"{y}-11-30",
                           "val": 12_807 * _M, "fy": y, "fp": "FY", "form": "10-K",
                           "filed": f"{y + 1}-01-15", "accn": f"p-{y}"} for y in _YEARS]}
    }
    assert _fields(facts, "net_income") == {"NetIncomeLoss"}
    del facts["facts"]["us-gaap"]["NetIncomeLoss"]
    assert _series(facts, "net_income").status is MetricStatus.UNSUPPORTED


def test_income_available_to_common_is_never_used_as_net_income() -> None:
    facts = adbe_facts()
    del facts["facts"]["us-gaap"]["NetIncomeLoss"]
    facts["facts"]["us-gaap"]["NetIncomeLossAvailableToCommonStockholdersBasic"] = {
        "units": {"USD": [{"start": f"{y - 1}-12-01", "end": f"{y}-11-30",
                           "val": 8_884 * _M, "fy": y, "fp": "FY", "form": "10-K",
                           "filed": f"{y + 1}-01-15", "accn": f"c-{y}"} for y in _YEARS]}
    }
    assert _series(facts, "net_income").status is MetricStatus.UNSUPPORTED


# --- Context-dependent: equity including noncontrolling interests -------------------


def test_equity_including_nci_is_not_adopted_for_filers_without_an_override() -> None:
    # UNH and CAT report only this concept; adopting it would mix consolidated
    # equity with parent net income, so they stay explicitly unsupported.
    facts = _facts(
        StockholdersEquity=None,
        StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=dict.fromkeys(
            _YEARS, 100_090 * _M
        ),
    )
    assert _series(facts, "total_equity", "UNH").status is MetricStatus.UNSUPPORTED


def test_the_documented_visa_override_still_applies() -> None:
    fields = _fields(visa_facts(), "total_equity", "V")
    assert fields == {"StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"}


def test_plain_equity_still_wins_for_filers_reporting_both() -> None:
    # KO pattern: both concepts present, 6.1% apart.
    facts = _facts(
        StockholdersEquity=dict.fromkeys(_YEARS, 32_169 * _M),
        StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=dict.fromkeys(
            _YEARS, 34_275 * _M
        ),
    )
    assert _fields(facts, "total_equity", "KO") == {"StockholdersEquity"}
    assert _series(facts, "total_equity", "KO").observations[0].value == 32_169 * _M


# --- Rejected: restricted-cash-inclusive cash -----------------------------------------


def test_restricted_cash_inclusive_concept_is_never_used_as_cash() -> None:
    # INTU pattern: the broader concept is 96% larger because of customer funds.
    facts = _facts(
        CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents=dict.fromkeys(
            _YEARS, 9_216 * _M
        ),
    )
    assert _fields(facts, "cash") == {"CashAndCashEquivalentsAtCarryingValue"}
    del facts["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]
    assert _series(facts, "cash").status is MetricStatus.UNSUPPORTED


def test_restricted_cash_cannot_leak_into_net_cash_or_invested_capital() -> None:
    facts = _facts(
        CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents=dict.fromkeys(
            _YEARS, 9_216 * _M
        ),
    )
    rows = {r.fiscal_year: r for r in
            capital_efficiency_from_history(canonical_history_from_sec(facts, ticker="INTU"))}
    cash = _series(facts, "cash").observations[0].value
    sti = _series(facts, "short_term_investments").observations[0].value
    assert rows[2025].cash_plus_sti == cash + sti
    assert rows[2025].cash_plus_sti < 9_216 * _M


# --- Golden companies --------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticker", "build", "concept"),
    [("ADBE", adbe_facts, "LongTermDebt"), ("V", visa_facts, "LongTermDebtNoncurrent"),
     ("COST", costco_facts, "LongTermDebtNoncurrent")],
)
def test_golden_long_term_debt_is_unchanged(ticker: str, build: Any, concept: str) -> None:
    assert _fields(build(), "long_term_debt", ticker) == {concept}


@pytest.mark.parametrize(("ticker", "build"), [("ADBE", adbe_facts), ("V", visa_facts),
                                               ("COST", costco_facts)])
def test_golden_companies_use_no_rejected_concept(ticker: str, build: Any) -> None:
    # Visa's equity concept is context-dependent, adopted only through its
    # documented override; no outright-rejected concept may appear anywhere.
    rejected = {
        entry.concept for entry in ALTERNATIVE_CONCEPT_POLICY
        if entry.decision is ConceptDecision.SEMANTICALLY_DIFFERENT
        or entry.decision is ConceptDecision.REJECT
    }
    history = canonical_history_from_sec(build(), ticker=ticker)
    used = {f.provider_field for s in history.series for f in s.observations}
    assert not used & rejected

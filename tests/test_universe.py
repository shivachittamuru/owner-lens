"""Tests for the Slice 6A universe coverage survey. Offline and deterministic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _fixtures import FakeSecClient, adbe_facts, costco_facts, visa_facts

from owner_lens import company_coverage, universe
from owner_lens.canonical import MetricStatus
from owner_lens.ingestion import ingest_company
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.sec import CompanyResolutionError
from owner_lens.universe import (
    UNIVERSE_6A,
    DiagnosisCategory,
    LayerState,
    Overall,
    RestatementKind,
    UniverseReport,
    format_company_view,
    format_metric_view,
    format_pattern_view,
    survey_company,
    survey_from_snapshot,
    survey_with_ingestion,
)

D = DiagnosisCategory
_M = 1_000_000


def _instant(year: int, value: int, *, form: str = "10-K", fp: str = "FY", filed: str | None = None) -> dict[str, Any]:
    return {
        "end": f"{year}-11-30",
        "val": value,
        "fy": year,
        "fp": fp,
        "form": form,
        "filed": filed or f"{year + 1}-01-15",
        "accn": f"x-{year}-{value}",
    }


def _set(facts: dict[str, Any], concept: str, entries: list[dict[str, Any]], unit: str = "USD") -> dict[str, Any]:
    facts["facts"]["us-gaap"][concept] = {"units": {unit: entries}}
    return facts


def _without(concept: str) -> dict[str, Any]:
    facts = adbe_facts()
    del facts["facts"]["us-gaap"][concept]
    return facts


def _layer_states(survey: universe.CompanySurvey) -> dict[str, str]:
    return {layer: probe.state.value for layer, probe in survey.layers.items()}


# --- Golden companies match existing coverage ------------------------------------


@pytest.mark.parametrize(
    ("ticker", "build", "overall"),
    [("ADBE", adbe_facts, Overall.FULL), ("V", visa_facts, Overall.PARTIAL), ("COST", costco_facts, Overall.FULL)],
)
def test_golden_companies_match_existing_coverage(ticker: str, build: Any, overall: Overall) -> None:
    survey = survey_company(build(), ticker=ticker)
    coverage = company_coverage(build(), ticker=ticker)
    assert survey.overall is overall
    assert _layer_states(survey) == {k: v.state.value for k, v in coverage.layers.items()}
    assert survey.industry == next(m.industry for m in UNIVERSE_6A if m.ticker == ticker)


def test_visa_partial_is_attributed_to_unsupported_diluted_shares() -> None:
    survey = survey_company(visa_facts(), ticker="V")
    shares = survey.metrics["diluted_shares"]
    assert (shares.status, shares.diagnosis) == (MetricStatus.UNSUPPORTED, D.MISSING_CONCEPT)
    assert survey.metrics["short_term_investments"].diagnosis is D.POLICY_ABSENT
    assert survey.layers["owner_economics"].state is LayerState.PARTIAL
    assert survey.primary_blocker == "diluted_shares"
    assert survey.unusable_inputs() == ()  # unsupported diluted shares degrade, never block


def test_adobe_has_no_findings() -> None:
    survey = survey_company(adbe_facts(), ticker="ADBE")
    assert {f.diagnosis for f in survey.metrics.values()} <= {D.NONE, D.POLICY_ABSENT}
    assert survey.primary_blocker is None


# --- Diagnosis rules ---------------------------------------------------------------


def test_single_component_resolves_without_an_override() -> None:
    # Slice 6D: LongTermDebtCurrent is a registry component, so no override is needed.
    facts = _set(_without("DebtCurrent"), "LongTermDebtCurrent", [_instant(y, 10 * _M) for y in (2023, 2024, 2025)])
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["current_debt"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.AVAILABLE, D.NONE)
    assert finding.concept_used == "LongTermDebtCurrent"
    assert survey.layers["capital_efficiency"].state is LayerState.AVAILABLE
    assert survey.overall is Overall.FULL


def test_two_nonzero_components_are_composed() -> None:
    facts = _set(_without("DebtCurrent"), "LongTermDebtCurrent", [_instant(y, 10 * _M) for y in (2023, 2024, 2025)])
    _set(facts, "CommercialPaper", [_instant(y, 5 * _M) for y in (2023, 2024, 2025)])
    finding = survey_company(facts, ticker="ADBE").metrics["current_debt"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.AVAILABLE, D.NONE)
    assert finding.concept_used == "LongTermDebtCurrent + CommercialPaper"


def test_lease_bundled_concept_blocks_composition() -> None:
    facts = _set(_without("DebtCurrent"), "CommercialPaper", [_instant(y, 5 * _M) for y in (2023, 2024, 2025)])
    _set(facts, "LongTermDebtAndCapitalLeaseObligationsCurrent",
         [_instant(y, 9 * _M) for y in (2023, 2024, 2025)])
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["current_debt"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.UNSUPPORTED, D.COMPOSITION_BLOCKED)
    assert "LongTermDebtAndCapitalLeaseObligationsCurrent" in (finding.reason or "")


def test_concept_with_only_quarterly_filings_is_a_period_issue() -> None:
    facts = _set(_without("DebtCurrent"), "DebtCurrent", [_instant(2025, 5 * _M, form="10-Q", fp="Q2")])
    finding = survey_company(facts, ticker="ADBE").metrics["current_debt"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.UNSUPPORTED, D.PERIOD_ISSUE)


def test_missing_concept_without_candidates() -> None:
    finding = survey_company(_without("DebtCurrent"), ticker="ADBE").metrics["current_debt"]
    assert (finding.diagnosis, finding.candidates) == (D.MISSING_CONCEPT, ())


def test_stale_only_concept_is_unsupported_not_silently_available() -> None:
    # Slice 6B: a concept whose newest value precedes the company's latest fiscal
    # year can no longer masquerade as AVAILABLE (6A recorded this as silent staleness).
    facts = _set(adbe_facts(), "ShortTermInvestments", [_instant(y, 7 * _M) for y in (2010, 2011, 2012)])
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["short_term_investments"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.UNSUPPORTED, D.STALE_CONCEPT)
    assert "ShortTermInvestments last reported 2012" in (finding.reason or "")
    assert survey.silently_stale() == ()
    assert survey.layers["capital_efficiency"].state is LayerState.UNAVAILABLE
    assert survey.overall is Overall.PARTIAL


def test_ambiguity_inside_a_stale_concept_no_longer_blocks_as_invalid() -> None:
    # The stale concept is skipped before its years are resolved, so its old
    # restatement conflict is irrelevant; the metric is unsupported, not invalid.
    entries = [_instant(y, 7 * _M) for y in (2010, 2011, 2012)]
    entries.append(_instant(2012, 7 * _M + 40_000, filed="2014-01-15"))
    survey = survey_company(_set(adbe_facts(), "ShortTermInvestments", entries), ticker="ADBE")
    finding = survey.metrics["short_term_investments"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.UNSUPPORTED, D.STALE_CONCEPT)
    assert survey.layers["capital_efficiency"].state is LayerState.UNAVAILABLE


def test_precision_restatement_in_baseline_year_is_resolved() -> None:
    # Slice 6C: a value re-rounded to thousands is the same economic value.
    facts = adbe_facts()
    assets = facts["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    oldest = min(assets, key=lambda e: e["end"])
    assets.append({**oldest, "val": oldest["val"] + 57_000, "filed": "2030-01-15", "accn": "restated"})
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["total_assets"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.AVAILABLE, D.NONE)
    assert finding.resolved_conflicts == (f"FY{oldest['end'][:4]} PRECISION",)
    assert survey.overall is Overall.FULL


def test_genuine_revision_in_baseline_year_still_blocks_capital_layers() -> None:
    facts = adbe_facts()
    assets = facts["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    oldest = min(assets, key=lambda e: e["end"])
    assets.append({**oldest, "val": oldest["val"] + 57_000_000, "filed": "2030-01-15", "accn": "restated"})
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["total_assets"]
    assert (finding.status, finding.diagnosis) == (MetricStatus.INVALID, D.AMBIGUOUS_DUPLICATE)
    assert finding.restatement is RestatementKind.VALUE_CHANGE
    assert survey.layers["owner_economics"].state is LayerState.AVAILABLE
    assert survey.layers["capital_efficiency"].state is LayerState.BLOCKED
    assert survey.layers["capital_efficiency"].blocking_metric == "total_assets"
    assert survey.overall is Overall.PARTIAL


def test_stock_split_restatement_of_diluted_shares_is_resolved() -> None:
    facts = adbe_facts()
    shares = facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"]
    latest = max(shares, key=lambda e: e["end"])
    shares.append({**latest, "val": latest["val"] * 10, "filed": "2030-01-15", "accn": "split"})
    survey = survey_company(facts, ticker="ADBE")
    finding = survey.metrics["diluted_shares"]
    assert finding.status is MetricStatus.AVAILABLE
    assert finding.resolved_conflicts == ("FY2025 STOCK_SPLIT", "FY2024 STOCK_SPLIT x10", "FY2023 STOCK_SPLIT x10")
    assert survey.layers["owner_economics"].state is LayerState.AVAILABLE
    assert survey.overall is Overall.FULL
    report = UniverseReport((survey,))
    assert report.resolved_conflicts()[0] == ("ADBE", "diluted_shares", "FY2025 STOCK_SPLIT")
    assert "Conflicts resolved by the normalizer (precision / stock split): 3" in format_pattern_view(report)
    assert json.loads(report.to_json())["resolved_conflicts"][1] == ["ADBE", "diluted_shares", "FY2024 STOCK_SPLIT x10"]


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("values: [515000000, 10296000000].", RestatementKind.STOCK_SPLIT),
        ("values: [230000000, 230141000].", RestatementKind.PRECISION),
        ("values: [2677000000, 2690000000].", RestatementKind.VALUE_CHANGE),  # CRM: <1% but genuine
        ("values: [73636000000, 81288000000].", RestatementKind.VALUE_CHANGE),
        ("no values here", None),
    ],
)
def test_restatement_kind(reason: str, kind: RestatementKind | None) -> None:
    assert universe._restatement_kind(reason) is kind


def test_unexpected_layer_exception_is_captured_as_likely_bug(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(history: Any) -> Any:
        raise RuntimeError("synthetic defect")

    monkeypatch.setattr(universe, "capital_efficiency_from_history", boom)
    survey = survey_company(adbe_facts(), ticker="ADBE")
    probe = survey.layers["capital_efficiency"]
    assert probe.state is LayerState.ERROR
    assert "RuntimeError: synthetic defect" in (probe.reason or "")
    assert survey.primary_category is D.LIKELY_BUG
    assert UniverseReport((survey,)).diagnosis_counts()["LIKELY_BUG"] == 1


# --- Ingestion reuse and offline replay ---------------------------------------------


def _stores(tmp_path: Path) -> tuple[SqliteStore, FilesystemRawSnapshotStore]:
    raw = FilesystemRawSnapshotStore(tmp_path / "raw")
    store = SqliteStore(tmp_path / "universe.db", raw_store=raw)
    store.initialize()
    return store, raw


def test_survey_reuses_ingestion_and_reloads_the_stored_snapshot(tmp_path: Path) -> None:
    store, raw = _stores(tmp_path)
    survey = survey_with_ingestion("adbe", sec_client=FakeSecClient(), store=store, raw_store=raw)
    assert (survey.ticker, survey.cik, survey.overall) == ("ADBE", "0000796343", Overall.FULL)
    assert survey.company_name == "ADOBE INC."
    assert survey.content_hash is not None and raw.exists(survey.content_hash)

    direct_store, _ = _stores(tmp_path / "direct")
    direct = ingest_company("ADBE", sec_client=FakeSecClient(), store=direct_store)
    assert survey.ingestion_status == direct.status.value
    assert direct.source_snapshot is not None
    assert survey.content_hash == direct.source_snapshot.content_hash
    store.close()
    direct_store.close()


def test_retrieval_failure_is_a_failed_row_not_a_crash(tmp_path: Path) -> None:
    store, raw = _stores(tmp_path)
    client = FakeSecClient(resolve_error=CompanyResolutionError("no such ticker"))
    survey = survey_with_ingestion("ZZZZ", sec_client=client, store=store, raw_store=raw)
    assert survey.overall is Overall.FAILED
    assert survey.layers == {} and survey.metrics == {}
    assert "no such ticker" in (survey.failure or "")
    store.close()


def test_offline_replay_reproduces_the_live_survey(tmp_path: Path) -> None:
    store, raw = _stores(tmp_path)
    live = UniverseReport(
        tuple(
            survey_with_ingestion(t, sec_client=FakeSecClient(), store=store, raw_store=raw)
            for t in ("ADBE", "V", "COST")
        )
    )
    entries = json.loads(live.to_json())["companies"]
    replay = UniverseReport(tuple(survey_from_snapshot(e, raw) for e in entries))
    assert replay.to_json() == live.to_json()
    store.close()


# --- Aggregation ----------------------------------------------------------------------


def _alternative(ticker: str) -> universe.CompanySurvey:
    # A company whose cash concept was retagged to an alternative OwnerLens does
    # not adopt: unsupported, with the alternative recorded as a candidate.
    facts = _set(_without("CashAndCashEquivalentsAtCarryingValue"),
                 "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                 [_instant(y, 10 * _M) for y in (2023, 2024, 2025)])
    return survey_company(facts, ticker=ticker)


def _report() -> UniverseReport:
    return UniverseReport(
        (
            survey_company(adbe_facts(), ticker="ADBE"),
            survey_company(visa_facts(), ticker="V"),
            _alternative("AAA"),
            _alternative("BBB"),
            _alternative("CCC"),
            universe.failed_survey("DDD", "retrieval failed"),
        )
    )


def test_distribution_and_metric_view() -> None:
    report = _report()
    assert report.distribution() == {"FULL": 1, "PARTIAL": 4, "FAILED": 1}
    debt = next(m for m in report.metric_view() if m.metric == "cash")
    assert debt.counts["AVAILABLE"] == 2 and debt.counts["UNSUPPORTED"] == 3
    assert debt.affected["UNSUPPORTED"] == ("AAA", "BBB", "CCC")
    assert debt.blocking_companies == ("AAA", "BBB", "CCC")
    assert debt.dominant_diagnosis == "ALTERNATIVE_CONCEPT"
    assert report.top_blockers()[0] == ("cash", 3)


def test_recurring_versus_quirk_threshold() -> None:
    recurring = _report().recurring_candidates()
    assert recurring == (("cash", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", ("AAA", "BBB", "CCC"), True),)
    two = UniverseReport((_alternative("AAA"), _alternative("BBB"))).recurring_candidates()
    assert two[0][3] is False


def test_unblocked_by_what_if() -> None:
    report = _report()
    resolves_debt = lambda _t, f: f.metric == "cash"
    assert report.unblocked_by(resolves_debt) == ("AAA", "BBB", "CCC")
    assert report.unblocked_by(lambda _t, f: False) == ()


def test_json_export_is_deterministic_and_views_render() -> None:
    assert _report().to_json() == _report().to_json()
    data = json.loads(_report().to_json())
    assert set(data) >= {"distribution", "metric_view", "companies", "recurring_candidates", "silently_stale"}
    for text in (format_company_view(_report()), format_metric_view(_report()), format_pattern_view(_report())):
        assert "AAA" in text or "cash" in text

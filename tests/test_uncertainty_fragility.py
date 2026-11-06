"""Independent review states and threshold boundaries, using offline evidence."""

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from _screening_fixtures import capital_row, evidence, fact, owner_series
from test_candidate_review import source as source  # noqa: PLC0414

from owner_lens.persistence import compute_content_hash
from owner_lens.screening import ScreeningReason, screen_company
from owner_lens.uncertainty_fragility import (
    assess_uncertainty_fragility,
    load_uncertainty_fragility,
)
from owner_lens.workbench.data import (
    WorkbenchSource,
    company_detail,
    load_persisted_companies,
)


def history(fps=(10, 11, 12, 13, 14), margins=(0.2, 0.2, 0.2, 0.2, 0.2), net_cash=100):
    rows = owner_series(
        [100] * 5,
        fcf_per_share=list(fps),
        diluted_shares=[10] * 5,
        fcf_margin=list(margins),
    )
    rows = tuple(
        replace(
            row,
            revenue=fact("revenue", 500, row.fiscal_year),
            operating_cash_flow=fact("operating_cash_flow", 110, row.fiscal_year),
            capital_expenditures=fact("capital_expenditures", 10, row.fiscal_year),
        )
        for row in rows
    )
    return evidence(
        owner_economics=rows,
        capital_efficiency=(capital_row(2025, roic=0.2, net_cash=net_cash),),
    )


def review(e, sector="Technology"):
    result = screen_company(e)
    return assess_uncertainty_fragility(e, result, sector=sector)


@pytest.mark.parametrize("last, fires", [(19.5, False), (19.5001, True)])
def test_normalization_threshold(last, fires):
    r = review(history(fps=(10, 11, 12, 13, last)))
    assert (
        "FCF_SHARE_NORMALIZATION_SENSITIVITY" in {x.code for x in r.business}
    ) == fires
    assert r.financial_state == "NO_FLAG_FROM_CURRENT_CHECKS"


def test_historical_uncertainty_is_not_financial_distress():
    e = history(fps=(10, 15, 10, 12, 14), margins=(0.2, 0.2, 0.2, 0.2, 0.1))
    result = screen_company(e)
    r = assess_uncertainty_fragility(e, result, sector="Technology")
    assert {"FCF_SHARE_DIRECTION_REVERSAL", "FCF_MARGIN_CHANGE"} <= {
        x.code for x in r.business
    }
    assert r.financial_state == "NO_FLAG_FROM_CURRENT_CHECKS"
    assert not r.financial and r.existing_gate is None
    assert screen_company(e) == result
    assert "safety" not in r.financial_state.lower()


@pytest.mark.parametrize(
    "margin,fires", [(0.170001, False), (0.17, True), (0.169999, True)]
)
def test_margin_decline_boundary(margin, fires):
    r = review(history(margins=(0.2, 0.2, 0.2, 0.2, margin)))
    assert ("FCF_MARGIN_CHANGE" in {x.code for x in r.business}) == fires


def test_cash_burn_and_gate_are_preserved():
    e = history()
    e = replace(
        e,
        owner_economics=tuple(
            replace(row, free_cash_flow=-100, fcf_per_share=-10) if i >= 3 else row
            for i, row in enumerate(e.owner_economics)
        ),
    )
    r = review(e)
    assert r.existing_gate == ScreeningReason.PERSISTENT_CASH_BURN.value
    assert r.financial_state == "ACTIVATED_EXISTING_GATE"
    assert "NONPOSITIVE_LATEST_FCF" in {x.code for x in r.financial}
    assert not any(x.code == "FCF_SHARE_NORMALIZATION_SENSITIVITY" for x in r.business)


@pytest.mark.parametrize(
    "net_cash,state",
    [
        (None, "INSUFFICIENT_EVIDENCE"),
        (-201, "OBSERVED_FINANCIAL_WARNING"),
        (-601, "ACTIVATED_EXISTING_GATE"),
    ],
)
def test_existing_leverage_threshold_and_absent_debt(net_cash, state):
    r = review(history(net_cash=net_cash))
    assert r.financial_state == state


def test_missing_and_negative_fcf_do_not_create_false_confidence():
    e = history()
    e = replace(
        e,
        owner_economics=tuple(
            replace(row, free_cash_flow=None, fcf_per_share=None)
            for row in e.owner_economics
        ),
    )
    r = review(e)
    assert r.financial_state == "INSUFFICIENT_EVIDENCE"
    assert "FCF_INSUFFICIENT_EVIDENCE" in {x.code for x in r.limitations}
    assert not r.business
    r = review(evidence())
    assert r.financial_state == "INSUFFICIENT_EVIDENCE"
    assert r.existing_gate is not None


def test_incompatible_sector_gaps_and_misaligned_periods():
    r = review(history(fps=(1, 2, 3, 4, 100)), "Real Estate")
    assert not r.business and r.financial_state == "INSUFFICIENT_EVIDENCE"
    e = history()
    e = replace(e, owner_economics=e.owner_economics[:2] + e.owner_economics[3:])
    r = review(e)
    assert not r.business
    assert r.financial_state == "INSUFFICIENT_EVIDENCE"
    e = history()
    row = e.owner_economics[-1]
    e = replace(
        e,
        owner_economics=e.owner_economics[:-1]
        + (replace(row, diluted_shares=fact("diluted_shares", 10, 2024)),),
    )
    assert not review(e).business


def test_revenue_deceleration_and_financing_capex_context():
    e = history(net_cash=-100)
    revenues = [100, 120, 150, 200, 210]
    e = replace(
        e,
        owner_economics=tuple(
            replace(
                row,
                revenue=fact("revenue", revenues[i], row.fiscal_year),
                capital_expenditures=fact("capital_expenditures", 50, row.fiscal_year),
            )
            for i, row in enumerate(e.owner_economics)
        ),
    )
    r = review(e)
    assert "REVENUE_GROWTH_DECELERATION" in {x.code for x in r.business}
    assert "CAPITAL_INTENSITY_WITH_NET_DEBT" in {x.code for x in r.financial}
    assert r == review(replace(e, owner_economics=tuple(reversed(e.owner_economics))))


def test_definition_limitations_are_not_distress(source: WorkbenchSource, monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline"))
    company = load_persisted_companies(source, "fmp")[0]
    result = company_detail(source, company).screening
    before = source.store._conn.total_changes
    r = load_uncertainty_fragility(source, company, result)
    assert r == load_uncertainty_fragility(source, company, result)
    assert source.store._conn.total_changes == before
    assert r.sources and r.annual
    snapshot = source.store.get_latest_fmp_evidence_snapshot(
        1, "annual_balance_sheet_statement"
    )
    rows = json.loads(source.raw_store.get(snapshot.content_hash))
    for row in rows:
        row["totalDebt"] = 10 * (row["shortTermDebt"] + row["longTermDebt"]) + 1000000
    body = json.dumps(rows).encode()
    content_hash = compute_content_hash(body)
    source.raw_store.put(content_hash, body)
    source.store._conn.execute(
        "UPDATE fmp_evidence_snapshots SET content_hash=? WHERE snapshot_id=?",
        (content_hash, snapshot.snapshot_id),
    )
    changed = load_uncertainty_fragility(source, company, result)
    assert changed.financial_state == r.financial_state
    assert "DEBT_DEFINITION_DIFFERENCE" in {x.code for x in changed.limitations}
    assert changed.financial == r.financial


def test_screener_review_renders_offline_and_navigates(
    source: WorkbenchSource, monkeypatch
):
    from streamlit.testing.v1 import AppTest

    from owner_lens.workbench.cache import clear_caches

    clear_caches()
    monkeypatch.setenv("OWNER_LENS_DB_PATH", source.db_path)
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", source.raw_data_path)
    monkeypatch.setenv("OWNER_LENS_WORKBENCH_PROVIDER", "fmp")
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline UI"))
    app_path = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120)
    app.session_state["page"] = "Screener"
    app.run()
    assert not app.exception
    app.checkbox(key="show_uncertainty_fragility").check().run()
    assert not app.exception and not app.error
    assert any("Uncertainty & Fragility" in x.value for x in app.subheader)
    assert app.selectbox(key="uf_ticker").value == "ADBE"
    app.run()
    assert not app.exception
    app.button(key="uf_open_company").click().run()
    assert not app.exception
    assert app.session_state["page"] == "Company"
    clear_caches()


@pytest.mark.parametrize("problem", ["missing_debt", "missing_period", "currency"])
def test_source_uncertainty_stays_separate(source: WorkbenchSource, problem):
    company = load_persisted_companies(source, "fmp")[0]
    result = company_detail(source, company).screening
    baseline = load_uncertainty_fragility(source, company, result)
    snapshot = source.store.get_latest_fmp_evidence_snapshot(
        1, "annual_balance_sheet_statement"
    )
    rows = json.loads(source.raw_store.get(snapshot.content_hash))
    if problem == "missing_debt":
        for row in rows:
            row.pop("totalDebt", None)
        expected = "DEBT_DEFINITION_NOT_VERIFIED"
    elif problem == "missing_period":
        rows = rows[1:]
        expected = "DEFINITIONS_NOT_VERIFIED"
    else:
        for row in rows:
            row["reportedCurrency"] = "EUR"
        expected = "DEFINITION_CURRENCY_NOT_VERIFIED"
    body = json.dumps(rows).encode()
    content_hash = compute_content_hash(body)
    source.raw_store.put(content_hash, body)
    source.store._conn.execute(
        "UPDATE fmp_evidence_snapshots SET content_hash=? WHERE snapshot_id=?",
        (content_hash, snapshot.snapshot_id),
    )
    reviewed = load_uncertainty_fragility(source, company, result)
    assert expected in {item.code for item in reviewed.limitations}
    assert reviewed.financial_state == baseline.financial_state
    assert reviewed.financial == baseline.financial


def test_cached_review_order_is_original_rank_order(
    source: WorkbenchSource, monkeypatch
):
    from owner_lens.workbench import cache

    company = load_persisted_companies(source, "fmp")[0]
    original = company_detail(source, company).screening
    companies = tuple(replace(company, ticker=ticker) for ticker in ("ZZZ", "AAA"))
    results = tuple(replace(original, ticker=company.ticker) for company in companies)
    monkeypatch.setattr(cache, "open_run_source", lambda: nullcontext(source))
    monkeypatch.setattr(cache, "load_persisted_companies", lambda *args: companies)
    monkeypatch.setattr(
        cache,
        "cached_uncertainty_fragility",
        lambda company, result, *args, **kwargs: result,
    )
    ordered = cache.uncertainty_fragility_reviews(companies, results, source.db_path)
    assert ordered == tuple(sorted(results, key=lambda item: item.rank_key))

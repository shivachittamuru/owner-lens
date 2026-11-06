"""Discovery eligibility and presentation remain independent of price verdicts."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from _screening_fixtures import fact, owner_series
from streamlit.testing.v1 import AppTest
from test_candidate_review import source as source  # noqa: PLC0414

from owner_lens.screening import (
    DimensionBand,
    ScreeningBucket,
    ScreeningReason,
    SetupType,
)
from owner_lens.uncertainty_fragility import load_uncertainty_fragility
from owner_lens.workbench.data import (
    WorkbenchSource,
    company_detail,
    load_persisted_companies,
)
from owner_lens.workbench.discovery import (
    discovery_lanes,
    discovery_price_card,
    price_summary,
)


def sample_lanes(source):
    company = load_persisted_companies(source, "fmp")[0]
    result = company_detail(source, company).screening
    strong = replace(
        result,
        gate=None,
        bucket=ScreeningBucket.HIGH_PRIORITY,
        setup_type=SetupType.COMPOUNDER,
        dimensions={
            d: replace(score, band=DimensionBand.STRONG)
            for d, score in result.dimensions.items()
        },
    )
    companies = tuple(
        replace(company, ticker=t)
        for t in ("FIRST", "SECOND", "IMPROVING", "GATED", "LIMITED")
    )
    results = (
        replace(strong, ticker="FIRST"),
        replace(strong, ticker="SECOND"),
        replace(result, ticker="IMPROVING", gate=None, bucket=ScreeningBucket.WATCH),
        replace(result, ticker="GATED", gate=ScreeningReason.PERSISTENT_CASH_BURN),
        replace(result, ticker="LIMITED", gate=None, bucket=ScreeningBucket.WATCH),
    )
    rows = tuple(
        replace(row, revenue=fact("revenue", 100 + i, row.fiscal_year))
        for i, row in enumerate(
            owner_series(
                [10, 11, 12, 13, 14],
                fcf_per_share=[1, 2, 3, 4, 5],
                diluted_shares=[10] * 5,
            )
        )
    )
    return companies, results, {"IMPROVING": rows, "GATED": rows}


def test_existing_eligibility_not_missingness_or_price(source: WorkbenchSource):
    companies, results, owners = sample_lanes(source)
    lanes = discovery_lanes(companies, results, owners)
    assert [i.company.ticker for i in lanes.compounders] == ["FIRST", "SECOND"]
    assert [i.company.ticker for i in lanes.improving] == ["IMPROVING"]
    assert [i.company.ticker for i in lanes.fragility] == ["GATED"]
    assert "LIMITED" not in {
        i.company.ticker for i in (*lanes.compounders, *lanes.improving)
    }
    assert lanes == discovery_lanes(
        tuple(reversed(companies)), tuple(reversed(results)), owners
    )
    assert all(
        i.screening is next(r for r in results if r.ticker == i.company.ticker)
        for i in lanes.compounders
    )


def test_persisted_prices_conditional_and_no_writes(
    source: WorkbenchSource, monkeypatch
):
    from owner_lens.candidate_review import CandidateSelection

    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline"))
    company = load_persisted_companies(source, "fmp")[0]
    result = company_detail(source, company).screening
    selected = CandidateSelection("COMPOUNDERS", company, result, "fixture")
    before = source.store._conn.total_changes
    card = discovery_price_card(source, selected)
    assert card["quote"]["market_date"] == "2026-10-30"
    assert card["valuation_status"] == "NOT_VERIFIED"
    assert "conditional" in price_summary(card) and "unverified" in price_summary(card)
    assert not any(
        word in price_summary(card).lower()
        for word in ("cheap", "expensive", "attractive")
    )
    assert source.store._conn.total_changes == before
    source.store._conn.execute(
        "DELETE FROM fmp_evidence_snapshots WHERE dataset='candidate_profile'"
    )
    card = discovery_price_card(source, selected)
    assert "unresolved" in price_summary(card)
    assert card["latest_price_to_fcf"] is None


def test_discovery_overview_lists_multiple_companies_and_inspects(
    source: WorkbenchSource, monkeypatch
):
    from owner_lens.workbench import cache

    cache.clear_caches()
    company = load_persisted_companies(source, "fmp")[0]
    result = company_detail(source, company).screening
    review = load_uncertainty_fragility(source, company, result)
    companies, results, owners = sample_lanes(source)
    lanes = discovery_lanes(companies, results, owners)
    reviews = tuple(
        replace(review, ticker=r.ticker, existing_gate=r.gate.value if r.gate else None)
        for r in results
    )
    monkeypatch.setattr(cache, "discovery_overview", lambda *a: (lanes, {}))
    monkeypatch.setattr(cache, "uncertainty_fragility_reviews", lambda *a: reviews)
    monkeypatch.setattr(cache, "cached_screening", lambda *a, **k: results)
    monkeypatch.setattr(
        httpx.Client, "send", lambda *a, **k: pytest.fail("offline rendering")
    )
    monkeypatch.setenv("OWNER_LENS_DB_PATH", source.db_path)
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", source.raw_data_path)
    monkeypatch.setenv("OWNER_LENS_WORKBENCH_PROVIDER", "fmp")
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"),
        default_timeout=120,
    )
    app.session_state["page"] = "Screener"
    app.run()
    assert not app.exception and not app.error
    assert any("Discovery research queue" in h.value for h in app.subheader)
    tables = [d.value for d in app.dataframe if "Why surfaced" in d.value.columns]
    assert len(tables) == 3 and len(tables[0]) == 2
    assert "GATED" in tables[2]["Company"].iloc[0]
    app.selectbox(key="discovery_ticker").set_value("IMPROVING").run()
    app.button(key="discovery_inspect").click().run()
    assert not app.exception
    assert app.selectbox(key="uf_ticker").value == "IMPROVING"
    monkeypatch.undo()
    cache.clear_caches()

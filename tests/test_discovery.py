"""Discovery eligibility and presentation remain independent of price verdicts."""

from copy import deepcopy
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
    attention_date,
    attention_order,
    discovery_lanes,
    discovery_price_card,
    price_summary,
    valuation_attention,
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
    assert "USD (inferred)" in price_summary(card)
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


def attention_fixture(source):
    companies, results, owners = sample_lanes(source)
    selections = discovery_lanes(companies, results, owners).compounders
    company = load_persisted_companies(source, "fmp")[0]
    original = company_detail(source, company).screening
    base = load_uncertainty_fragility(source, company, original)
    reviews = {
        item.company.ticker: replace(
            base,
            ticker=item.company.ticker,
            financial_state="NO_FLAG_FROM_CURRENT_CHECKS",
        )
        for item in selections
    }
    card = {
        "quote": {
            "market_date": "2026-10-30",
            "close": 100,
            "currency_basis": "INFERRED_CURRENT_PROFILE",
            "adjustment_basis": "UNVERIFIED",
        },
        "latest_price_to_fcf": 10.0,
        "median_price_to_fcf": 20.0,
        "latest_fcf_per_share": 10.0,
        "three_year_median_fcf_per_share": 5.0,
        "warnings": [],
        "valuation_status": "NOT_VERIFIED",
        "financial_references": [
            {"fiscal_year": year, "canonical_fcf_per_share": value}
            for year, value in ((2023, 4), (2024, 5), (2025, 10))
        ],
    }
    return selections, reviews, card


def test_attention_changes_order_within_sector_not_original_quality(source):
    selections, reviews, card = attention_fixture(source)
    cards = {"FIRST": deepcopy(card), "SECOND": deepcopy(card)}
    cards["SECOND"]["median_price_to_fcf"] = 12.0
    ordered = attention_order(selections, cards, reviews, attention_date(cards))
    assert [item.company.ticker for item in ordered] == ["SECOND", "FIRST"]
    a = valuation_attention(selections[0], card, reviews["FIRST"], "2026-10-30")
    assert a.ordering_eligible and a.latest_yield == 0.1 and a.median_yield == 0.05
    assert a.denominator_ratio == 2
    assert card["quote"]["adjustment_basis"] == "UNVERIFIED"
    assert "undervaluation" in a.reason and "Conditional" in a.reason
    assert selections[0].screening.bucket is ScreeningBucket.HIGH_PRIORITY
    cards["SECOND"]["median_price_to_fcf"] = 20.0
    assert attention_order(selections, cards, reviews, "2026-10-30") == selections


@pytest.mark.parametrize(
    "problem",
    [
        "negative",
        "missing",
        "nan",
        "history",
        "gap",
        "negative_year",
        "missing_fcf",
        "negative_latest_fcf",
        "currency",
        "stale",
        "sector",
        "sector_unknown",
        "gate",
        "resilience",
        "conflict",
    ],
)
def test_unsupported_attention_unranked(source, problem):
    selections, reviews, card = attention_fixture(source)
    item = selections[0]
    review = reviews["FIRST"]
    if problem in ("negative", "missing", "nan"):
        card["median_price_to_fcf"] = {
            "negative": -1,
            "missing": None,
            "nan": float("nan"),
        }[problem]
    elif problem == "history":
        card["financial_references"] = card["financial_references"][:2]
    elif problem == "gap":
        card["financial_references"][0]["fiscal_year"] = 2021
    elif problem == "negative_year":
        card["financial_references"][0]["canonical_fcf_per_share"] = -1
    elif problem == "missing_fcf":
        card["latest_fcf_per_share"] = None
    elif problem == "negative_latest_fcf":
        card["latest_fcf_per_share"] = -1
    elif problem == "currency":
        card["quote"]["currency_basis"] = "NOT_VERIFIED"
    elif problem == "stale":
        card["quote"]["market_date"] = "2026-09-30"
    elif problem in ("sector", "sector_unknown"):
        item = replace(
            item,
            company=replace(
                item.company, sector="Real Estate" if problem == "sector" else None
            ),
        )
    elif problem == "gate":
        item = replace(
            item,
            screening=replace(
                item.screening, gate=ScreeningReason.PERSISTENT_CASH_BURN
            ),
        )
    elif problem == "resilience":
        review = replace(review, financial_state="INSUFFICIENT_EVIDENCE")
    else:
        card["latest_price_to_fcf"] = None
    a = valuation_attention(item, card, review, "2026-10-30")
    assert not a.ordering_eligible and a.reason.startswith("Unranked:")
    if problem in (
        "history",
        "gap",
        "negative_year",
        "sector",
        "sector_unknown",
        "gate",
    ):
        assert a.median_multiple is None and a.median_yield is None
    if problem in (
        "missing_fcf",
        "negative_latest_fcf",
        "sector",
        "sector_unknown",
        "gate",
    ):
        assert a.latest_multiple is None and a.latest_yield is None


def test_attention_groups_sectors_and_excludes_older_quote(source):
    selections, reviews, card = attention_fixture(source)
    first, second = selections
    first = replace(first, company=replace(first.company, sector="Technology"))
    second = replace(second, company=replace(second.company, sector="Healthcare"))
    cards = {"FIRST": deepcopy(card), "SECOND": deepcopy(card)}
    cards["SECOND"]["median_price_to_fcf"] = 100
    assert attention_order((first, second), cards, reviews, attention_date(cards)) == (
        second,
        first,
    )
    cards["SECOND"]["quote"]["market_date"] = "2026-09-30"
    assert attention_date(cards) == "2026-10-30"
    assert attention_order((first, second), cards, reviews, attention_date(cards)) == (
        first,
        second,
    )


def test_invalid_canonical_evidence_is_explicitly_unranked(source, monkeypatch):
    from owner_lens.canonical import CanonicalDataError
    from owner_lens.workbench import discovery

    company = load_persisted_companies(source, "fmp")[0]
    original = company_detail(source, company).screening
    selections, _, _ = attention_fixture(source)
    item = replace(selections[0], company=company)

    def invalid(*args, **kwargs):
        raise CanonicalDataError("Ambiguous persisted cash-flow sign.")

    monkeypatch.setattr(discovery, "candidate_worksheet", invalid)
    card = discovery_price_card(source, item)
    assert "Ambiguous persisted cash-flow sign" in card["error"]
    review = load_uncertainty_fragility(source, company, original)
    assessment = valuation_attention(item, card, review, None)
    assert not assessment.ordering_eligible and "unresolved" in assessment.reason


def test_all_lane_candidates_receive_evidence_before_ordering(source, monkeypatch):
    from contextlib import nullcontext

    from owner_lens.workbench import cache

    companies, results, owners = sample_lanes(source)
    base = discovery_lanes(companies, results, owners)
    compounders = tuple(
        replace(
            base.compounders[0],
            company=replace(base.compounders[0].company, ticker=f"C{i}"),
        )
        for i in range(10)
    )
    expected = replace(base, compounders=compounders)
    monkeypatch.setattr(cache, "discovery_lanes", lambda *a: expected)
    monkeypatch.setattr(
        cache, "cached_improving_economics_owner_economics", lambda *a: ()
    )
    monkeypatch.setattr(cache, "open_run_source", lambda: nullcontext(source))
    monkeypatch.setattr(cache, "load_persisted_companies", lambda *a: companies)
    monkeypatch.setattr(
        cache,
        "cached_discovery_price",
        lambda item, *a, **k: {"error": item.company.ticker},
    )
    _, cards = cache.discovery_overview(companies, results, source.db_path)
    assert "C9" in cards and len(cards) == 11


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
    _, attention_reviews, card = attention_fixture(source)
    cards = {"FIRST": deepcopy(card), "SECOND": deepcopy(card)}
    cards["SECOND"]["median_price_to_fcf"] = 12.0
    reviews = tuple(
        attention_reviews.get(r.ticker)
        or replace(
            review, ticker=r.ticker, existing_gate=r.gate.value if r.gate else None
        )
        for r in results
    )
    monkeypatch.setattr(cache, "discovery_overview", lambda *a: (lanes, cards))
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
    assert tables[0]["Company"].iloc[0].startswith("SECOND")
    assert "12.0x / 8.33%" in tables[0]["Conditional median P/FCF / yield"].iloc[0]
    assert "2.00x latest/median" in tables[0]["Denominator sensitivity"].iloc[0]
    assert "GATED" in tables[2]["Company"].iloc[0]
    app.selectbox(key="discovery_ticker").set_value("IMPROVING").run()
    app.button(key="discovery_inspect").click().run()
    assert not app.exception
    assert app.selectbox(key="uf_ticker").value == "IMPROVING"
    monkeypatch.undo()
    cache.clear_caches()

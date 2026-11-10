"""Discovery eligibility and presentation remain independent of price verdicts."""

import hashlib
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
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
    tables = [
        d.value for d in app.dataframe
        if "Ticker" in d.value.columns and "Company" not in d.value.columns
        and ("Median P/FCF" in d.value.columns or "Gate/warning summary" in d.value.columns)
    ]
    assert len(tables) == 3 and len(tables[0]) == 2
    assert tables[0]["Ticker"].iloc[0] == "SECOND"
    assert tables[0]["Median P/FCF"].iloc[0] == 12.0
    assert tables[0]["Median FCF yield"].iloc[0] == pytest.approx(1 / 12)
    assert tables[0]["FCF/share latest/median"].iloc[0] == 2.0
    assert tables[2]["Ticker"].iloc[0] == "GATED"
    assert "Persistent cash burn" in tables[2]["Gate/warning summary"].iloc[0]
    app.selectbox(key="discovery_ticker").set_value("IMPROVING").run()
    app.button(key="discovery_inspect").click().run()
    assert not app.exception
    assert app.selectbox(key="uf_ticker").value == "IMPROVING"
    monkeypatch.undo()
    cache.clear_caches()


def test_discovery_numeric_frames_sort_and_preserve_nulls():
    from owner_lens.workbench.views.screener import (
        _DISCOVERY_NUMBERS,
        _OPPORTUNITY_COLUMNS,
        _discovery_columns,
        _discovery_frame,
    )

    rows = [
        {
            **dict.fromkeys(_OPPORTUNITY_COLUMNS, "Evidence retained"),
            **dict.fromkeys(_DISCOVERY_NUMBERS, value),
            "Ticker": ticker,
            "Median FCF yield": yield_value,
        }
        for ticker, value, yield_value in (
            ("HUNDRED", 100.0, 0.02), ("NINE", 9.0, 0.10),
            ("TWENTY", 20.0, 0.05), ("UNSUPPORTED", None, None),
        )
    ]
    original = deepcopy(rows)
    table = _discovery_frame(rows, details=True)
    for column in _DISCOVERY_NUMBERS:
        assert pd.api.types.is_numeric_dtype(table[column])
        assert pd.isna(table[column].iloc[-1])
        assert pa.Table.from_pandas(table)[column].null_count == 1
    assert list(table.sort_values("Median P/FCF")["Ticker"]) == [
        "NINE", "TWENTY", "HUNDRED", "UNSUPPORTED",
    ]
    assert list(table.sort_values("Median P/FCF", ascending=False)["Ticker"]) == [
        "HUNDRED", "TWENTY", "NINE", "UNSUPPORTED",
    ]
    assert list(table.sort_values("Median FCF yield", ascending=False)["Ticker"]) == [
        "NINE", "TWENTY", "HUNDRED", "UNSUPPORTED",
    ]
    assert list(table.sort_values("Median FCF yield")["Ticker"]) == [
        "HUNDRED", "TWENTY", "NINE", "UNSUPPORTED",
    ]
    assert list(table["Ticker"]) == [row["Ticker"] for row in rows]
    assert rows == original
    for column, config in _discovery_columns().items():
        if column in _DISCOVERY_NUMBERS:
            assert config["type_config"]["type"] == "number"
            assert config["type_config"]["format"] == _DISCOVERY_NUMBERS[column][0]
            if _DISCOVERY_NUMBERS[column][0] == "percent":
                assert config["type_config"]["step"] == 0.0001
    assert _discovery_columns()["Median FCF yield"]["type_config"]["format"] == "percent"
    # Streamlit's percent format consumes decimal ratios, not percent points.
    assert table["Median FCF yield"].iloc[1] == 0.1
    null_rows = [
        {**rows[-1], **dict.fromkeys(_DISCOVERY_NUMBERS)}
    ]
    nulls = _discovery_frame(null_rows, details=True)
    assert all(pd.api.types.is_numeric_dtype(nulls[c]) for c in _DISCOVERY_NUMBERS)
    assert all(pa.Table.from_pandas(nulls)[c].null_count == 1 for c in _DISCOVERY_NUMBERS)


def _render_discovery_app(lanes, cards, reviews, results):
    from owner_lens.workbench.views.screener import render_discovery

    render_discovery(lanes, cards, reviews, results)


def test_compact_shortlist_remainder_details_and_all_gates(source, monkeypatch):
    from owner_lens.workbench.discovery import DiscoveryLanes
    from owner_lens.workbench.views.screener import _research_label

    selections, reviews, card = attention_fixture(source)
    items = tuple(
        replace(
            selections[0],
            company=replace(selections[0].company, ticker=f"C{i:02}"),
            screening=replace(selections[0].screening, ticker=f"C{i:02}"),
        )
        for i in range(12)
    )
    gate_codes = (
        ScreeningReason.PERSISTENT_CASH_BURN,
        ScreeningReason.LEVERAGE_UNSUPPORTED_BY_CASH_FLOW,
        ScreeningReason.NET_DEBT_WITHOUT_CASH_FLOW,
        ScreeningReason.RETURNS_BELOW_PLAUSIBLE_COST_OF_CAPITAL,
        ScreeningReason.PERSISTENT_MATERIAL_DILUTION,
    )
    gates = tuple(
        replace(item, screening=replace(
            item.screening, gate=gate_codes[index % len(gate_codes)],
        ))
        for index, item in enumerate(items)
    )
    lane_reviews = tuple(
        replace(
            reviews["FIRST"], ticker=item.company.ticker,
            existing_gate=ScreeningReason.PERSISTENT_CASH_BURN.value,
        )
        for item in items
    )
    cards = {
        item.company.ticker: {**deepcopy(card), "median_price_to_fcf": 100 - i}
        for i, item in enumerate(items)
    }
    lanes = DiscoveryLanes(items, (), gates)
    expected = attention_order(items, cards, {r.ticker: r for r in lane_reviews}, attention_date(cards))
    before = source.store._conn.total_changes
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline"))
    app = AppTest.from_function(
        _render_discovery_app,
        args=(lanes, cards, lane_reviews, tuple(item.screening for item in items)),
    ).run()
    assert not app.exception
    compact = [
        d.value for d in app.dataframe
        if "Median P/FCF" in d.value.columns and "Company" not in d.value.columns
    ]
    assert [len(t) for t in compact] == [8, 12]
    expected_tickers = [item.company.ticker for item in expected]
    assert compact[0]["Ticker"].tolist() == expected_tickers[:8]
    assert compact[1]["Ticker"].tolist() == expected_tickers
    fragile = [
        d.value for d in app.dataframe
        if list(d.value.columns) == [
            "Ticker", "Economic priority", "Gate/warning summary", "Coverage",
        ]
    ]
    assert [len(t) for t in fragile] == [8, 12]
    assert fragile[1]["Ticker"].tolist() == [i.company.ticker for i in gates]
    for index, item in enumerate(gates):
        assert item.screening.gate is not None
        assert _research_label(item.screening.gate.value) in fragile[1]["Gate/warning summary"].iloc[index]
    details = [d.value for d in app.dataframe if "Why surfaced" in d.value.columns]
    assert [len(t) for t in details] == [12, 12]
    assert all("Price/valuation evidence" in t and "Economics trend" in t for t in details)
    assert set(app.selectbox(key="discovery_ticker").options) == set(expected_tickers)
    assert any("Sorting changes presentation only." in c.value for c in app.caption)
    assert source.store._conn.total_changes == before
    assert lanes.compounders == items and lanes.fragility == gates
    app.selectbox(key="discovery_ticker").set_value("C09").run()
    app.button(key="discovery_open").click().run()
    assert not app.exception
    assert app.session_state["selected_ticker"] == "C09"
    assert app.session_state["requested_page"] == "Company"


def test_real_persisted_discovery_presentation_read_only(monkeypatch):
    """Opt-in local evidence check; never seed, refresh or initialize its store."""
    from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
    from owner_lens.screening import screen_company_from_history
    from owner_lens.workbench.data import load_canonical_history

    db_name = os.environ.get("OWNER_LENS_DISCOVERY_TEST_DB")
    raw_name = os.environ.get("OWNER_LENS_DISCOVERY_TEST_RAW")
    if not db_name or not raw_name:
        pytest.skip("Set OWNER_LENS_DISCOVERY_TEST_DB and OWNER_LENS_DISCOVERY_TEST_RAW for saved-evidence controls.")
    db, raw = Path(db_name), Path(raw_name)
    assert db.is_file() and raw.is_dir()
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    raw_store = FilesystemRawSnapshotStore(raw)
    store = SqliteStore(db, raw_store=raw_store, read_only=True)
    source = WorkbenchSource(store, raw_store, str(db), str(raw))
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("offline"))
    monkeypatch.setattr(httpx.AsyncClient, "send", lambda *a, **k: pytest.fail("offline"))
    try:
        targets = {"DECK", "CMG", "NVDA", "ADSK", "ORCL", "INTC"}
        companies = tuple(c for c in load_persisted_companies(source, "fmp") if c.ticker in targets)
        assert {c.ticker for c in companies} == targets
        histories = {c.ticker: load_canonical_history(source, c) for c in companies}
        results = tuple(screen_company_from_history(histories[c.ticker]) for c in companies)
        from owner_lens.screening import assemble_screening_evidence

        owners = {
            ticker: assemble_screening_evidence(history).owner_economics
            for ticker, history in histories.items()
        }
        lanes = discovery_lanes(companies, results, owners)
        assert {i.company.ticker for i in lanes.compounders} == {"DECK", "CMG", "NVDA"}
        assert {i.company.ticker for i in lanes.improving} == {"ADSK"}
        assert {i.company.ticker for i in lanes.fragility} == {"ORCL", "INTC"}
        reviews = tuple(
            load_uncertainty_fragility(source, c, next(r for r in results if r.ticker == c.ticker))
            for c in companies
        )
        cards = {
            i.company.ticker: discovery_price_card(source, i)
            for i in (*lanes.compounders, *lanes.improving)
        }
        assert all("error" not in card for card in cards.values()), cards
        app = AppTest.from_function(
            _render_discovery_app, args=(lanes, cards, reviews, results),
        ).run()
        assert not app.exception
        tables = [
            d.value for d in app.dataframe
            if "Median P/FCF" in d.value.columns and "Company" not in d.value.columns
        ]
        ordered = attention_order(
            lanes.compounders, cards, {r.ticker: r for r in reviews}, attention_date(cards),
        )
        assert tables[0]["Ticker"].tolist() == [i.company.ticker for i in ordered]
        assert tables[0]["Median P/FCF"].notna().all()
        assert tables[1]["Ticker"].tolist() == ["ADSK"]
        assert pd.isna(tables[1]["Median P/FCF"].iloc[0])
        assert pd.isna(tables[1]["Median FCF yield"].iloc[0])
        assert "Unranked" in tables[1]["Valuation/evidence status"].iloc[0]
        details = [d.value for d in app.dataframe if "Why surfaced" in d.value.columns]
        for table in details:
            for column in ("Latest P/FCF", "Median P/FCF", "Latest FCF yield", "Median FCF yield"):
                assert pd.api.types.is_numeric_dtype(table[column])
        gates = next(d.value for d in app.dataframe if len(d.value.columns) == 4 and "Gate/warning summary" in d.value.columns)
        assert set(gates["Ticker"]) == {"ORCL", "INTC"}
        assert gates["Gate/warning summary"].str.contains("Persistent cash burn").all()
        assert store._conn.total_changes == 0
    finally:
        store.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before

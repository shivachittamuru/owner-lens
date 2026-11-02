"""Offline downside budgets, immutable sources and explicit investor policies."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_decisions import comparison_input, four_companies, input_data
from test_opportunity_comparison import persist, snapshot
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.cli import main
from owner_lens.decisions import create_decision
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.position_sizing import (
    PortfolioSnapshot,
    SizingError,
    SizingPolicy,
    canonical_json,
    create_portfolio,
    format_sizing,
    size_position,
)

NOW = datetime(2026, 6, 3, 12, tzinfo=UTC)
APP = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
ROOT = Path(__file__).parents[1]


def policy(**changes: Any) -> dict[str, Any]:
    return {
        "category": "JUDGMENT",
        "max_single_position_weight": 0.1,
        "max_initial_position_weight": 0.08,
        "max_portfolio_bear_loss_contribution": 0.03,
        "max_sector_weight": 0.4,
        "min_cash_reserve": 0.1,
        "starter_position_weight": 0.06,
        "max_thesis_weight": 0.3,
        "severe_bear_loss_threshold": 0.8,
        **changes,
    }


def portfolio_input(**changes: Any) -> dict[str, Any]:
    return {
        "as_of_date": "2026-06-03",
        "basis": "WEIGHT",
        "holdings": [
            {
                "ticker": "ADBE",
                "asset_type": "EQUITY",
                "weight": 0.02,
                "sector": "Technology",
                "industry": "Software",
                "exposure_tags": ["AI_CAPEX"],
            },
            {
                "ticker": "MSFT",
                "asset_type": "EQUITY",
                "weight": 0.18,
                "sector": "Technology",
                "industry": "Software",
                "exposure_tags": ["AI_CAPEX"],
            },
            {
                "ticker": "KO",
                "asset_type": "EQUITY",
                "weight": 0.4,
                "sector": "Consumer",
                "industry": "Beverages",
                "exposure_tags": [],
            },
        ],
        "cash": 0.4,
        **changes,
    }


def preview(
    store: SqliteStore,
    *,
    data: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    price: float = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    selection = persist(store, "ADBE", snapshot(price=price))
    portfolio = create_portfolio(
        store, portfolio_input() if data is None else data, now=NOW
    )
    return size_position(
        store,
        selection,
        portfolio.snapshot_id,
        policy() if limits is None else limits,
        now=NOW,
        **kwargs,
    )


def test_current_weight_downside_and_synthetic_example(store: SqliteStore) -> None:
    report = preview(store)
    assert report["current_weight"] == 0.02
    assert report["cash_weight"] == 0.4
    assert report["modeled_bear_loss"] == pytest.approx(0.5)
    assert report["current_bear_loss_contribution"] == pytest.approx(0.01)
    assert report["target_range"] == pytest.approx([0, 0.06])
    assert report["incremental_room"] == pytest.approx([0, 0.04])
    assert report["binding_constraints"] == ["bear_loss_budget", "evidence_quality"]
    assert report["incremental_capital"] is None
    assert report["opportunity"]["summary"]["current_price"] == 20
    assert report["opportunity"]["summary"]["expected_5y_cagr"] == pytest.approx(
        0.398007, abs=1e-5
    )
    assert "trade" not in report
    assert "trim" in report["disclaimer"]
    assert "Expected CAGR" in format_sizing(report)


@pytest.mark.parametrize(
    "basis,amount_key,amounts,cash",
    [
        ("WEIGHT", "weight", (0.01, 0.09, 0.2), 0.2),
        ("MARKET_VALUE", "market_value", (2000, 18000, 40000), 40000),
    ],
)
def test_normalization_and_roundtrip(
    store: SqliteStore,
    basis: str,
    amount_key: str,
    amounts: tuple[float, ...],
    cash: float,
) -> None:
    data = portfolio_input(basis=basis, cash=cash)
    if basis == "MARKET_VALUE":
        data["currency"] = "USD"
    for holding, amount in zip(data["holdings"], amounts, strict=True):
        holding.pop("weight")
        holding[amount_key] = amount
    result = preview(store, data=data)
    portfolio = PortfolioSnapshot.from_json(canonical_json(result["portfolio"]))
    assert portfolio.holdings[0].weight == pytest.approx(0.02)
    assert portfolio.cash_weight == pytest.approx(0.4)
    assert PortfolioSnapshot.from_json(portfolio.to_json()) == portfolio
    assert portfolio.category == "JUDGMENT"
    if basis == "MARKET_VALUE":
        assert result["incremental_capital"]["range"] == pytest.approx([0, 4000])
        assert result["incremental_capital"]["currency"] == "USD"
    else:
        assert result["incremental_capital"] is None


@pytest.mark.parametrize("missing", list(policy()))
def test_policy_has_no_hidden_defaults(missing: str) -> None:
    data = policy()
    data.pop(missing)
    with pytest.raises(ValueError, match="missing"):
        SizingPolicy.parse(data)


@pytest.mark.parametrize(
    "change",
    [
        {"max_single_position_weight": -0.1},
        {"max_sector_weight": 1.01},
        {"max_thesis_weight": float("nan")},
        {"min_cash_reserve": float("inf")},
        {"starter_position_weight": True},
        {"max_initial_position_weight": 0.11},
        {"starter_position_weight": 0.09},
        {"category": "FACT"},
        {"severe_bear_loss_threshold": 0},
        {"kelly_fraction": 0.5},
    ],
)
def test_invalid_or_unrelated_policy_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SizingPolicy.parse(policy(**change))


@pytest.mark.parametrize(
    "limits,binding,ceiling",
    [
        (
            policy(
                max_single_position_weight=0.025,
                max_initial_position_weight=0.02,
                starter_position_weight=0.02,
                max_portfolio_bear_loss_contribution=1,
            ),
            "evidence_quality",
            0.02,
        ),
        (
            policy(
                max_single_position_weight=0.025,
                max_initial_position_weight=0.025,
                starter_position_weight=0.025,
                max_portfolio_bear_loss_contribution=1,
            ),
            "single_position",
            0.025,
        ),
        (policy(max_portfolio_bear_loss_contribution=0.015), "bear_loss_budget", 0.03),
        (policy(max_sector_weight=0.21), "sector", 0.03),
        (policy(max_thesis_weight=0.205), "thesis", 0.025),
        (policy(min_cash_reserve=0.39), "cash_deployment", 0.03),
    ],
)
def test_independent_ceilings(
    store: SqliteStore, limits: dict[str, Any], binding: str, ceiling: float
) -> None:
    report = preview(store, limits=limits)
    assert report["target_range"][1] == pytest.approx(ceiling)
    assert binding in report["binding_constraints"]


def test_initial_position_limit_only_for_unheld_company(store: SqliteStore) -> None:
    data = portfolio_input()
    data["holdings"].pop(0)
    data["cash"] += 0.02
    limits = policy(max_initial_position_weight=0.02, starter_position_weight=0.02)
    report = preview(
        store,
        data=data,
        limits=limits,
        context_data={
            "sector": "Technology",
            "industry": "Software",
            "exposure_tags": ["AI_CAPEX"],
        },
    )
    assert report["current_weight"] == 0
    assert report["ceilings"]["initial_position"] == 0.02
    assert "initial_position" in report["binding_constraints"]


def test_cash_reserve_zero_room_and_above_policy_are_not_trim(
    store: SqliteStore,
) -> None:
    report = preview(store, limits=policy(max_portfolio_bear_loss_contribution=0.005))
    assert "ABOVE_POLICY_RANGE" in report["warnings"]
    assert report["incremental_room"] == [0, 0]
    assert "recommended_action" not in report
    assert report["current_weight"] == 0.02
    assert report["target_range"][1] == pytest.approx(0.01)


def test_below_reserve_does_not_infer_funding_from_other_positions(
    store: SqliteStore,
) -> None:
    report = preview(store, limits=policy(min_cash_reserve=0.5))
    assert report["target_range"] == [0, 0.02]
    assert report["incremental_room"] == [0, 0]
    assert "CASH_BELOW_RESERVE" in report["warnings"]


@pytest.mark.parametrize("field", ["cash", "sector", "exposure_tags"])
def test_missing_context_blocks_new_deployment(store: SqliteStore, field: str) -> None:
    data = portfolio_input()
    if field == "cash":
        data.pop("cash")
    else:
        data["holdings"][1].pop(field)
    report = preview(store, data=data)
    assert report["incremental_room"] == [0, 0]
    assert report["target_range"][1] <= report["current_weight"]
    assert "INCOMPLETE_PORTFOLIO_CONTEXT" in report["warnings"]
    assert report["missing_dimensions"]
    if field == "cash":
        assert report["cash_weight"] is None
        assert report["current_weight"] == pytest.approx(0.02 / 0.6)


def test_explicit_zero_cash_distinct_from_unknown(store: SqliteStore) -> None:
    data = portfolio_input(cash=0)
    report = preview(store, data=data)
    assert report["cash_weight"] == 0
    assert not any(
        "Cash was not supplied" in item for item in report["missing_dimensions"]
    )


def test_multiple_tags_are_independent_not_disjoint_weights(store: SqliteStore) -> None:
    data = portfolio_input()
    for holding in data["holdings"][:2]:
        holding["exposure_tags"] = ["AI_CAPEX", "ENTERPRISE_SOFTWARE"]
    report = preview(store, data=data, proposed_increment=0.2)
    assert report["thesis_weights"] == {
        "AI_CAPEX": pytest.approx(0.2),
        "ENTERPRISE_SOFTWARE": pytest.approx(0.2),
    }
    assert report["ceilings"]["thesis"] == pytest.approx(0.12)
    assert {
        "THESIS_CONCENTRATION_WARNING",
        "SINGLE_NAME_CONCENTRATION_WARNING",
        "PROPOSED_INCREMENT_EXCEEDS_ROOM",
    } <= set(report["warnings"])
    assert report["proposed_bear_loss_contribution"] == pytest.approx(0.22 * 0.5)


def test_proposal_does_not_change_range_and_sector_warning(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    before = size_position(store, selected, portfolio.snapshot_id, policy(), now=NOW)
    after = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(),
        now=NOW,
        proposed_increment=0.3,
    )
    assert after["target_range"] == before["target_range"]
    assert "SECTOR_CONCENTRATION_WARNING" in after["warnings"]
    assert after["proposed_target_weight"] == pytest.approx(0.32)


def test_quality_cap_includes_missing_evidence_variant_sensitivity_and_questions(
    store: SqliteStore,
) -> None:
    original = snapshot()
    selected = persist(
        store,
        "ADBE",
        replace(
            original,
            manual=replace(
                original.manual,
                supporting_evidence=(),
                disconfirming_evidence=(),
                variant_rationales=(),
            ),
        ),
    )
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    report = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(starter_position_weight=0.01),
        now=NOW,
    )
    assert report["ceilings"]["evidence_quality"] == 0.01
    assert "INCOMPLETE_EVIDENCE" in report["quality_cap_reasons"]
    assert "NO_DOCUMENTED_VARIANT_VIEW" in report["quality_cap_reasons"]
    assert "UNRESOLVED_CHALLENGER_QUESTIONS" in report["quality_cap_reasons"]
    assert report["status"] == "STARTER"
    assert "ABOVE_POLICY_RANGE" in report["warnings"]


def test_missing_feature7_not_recomputed_and_severe_loss_cap(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = snapshot()
    evidence = json.loads(original.evidence_json)
    evidence.pop("feature7_context")
    selected = persist(
        store, "ADBE", replace(original, evidence_json=json.dumps(evidence))
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Feature 7 must not be recomputed")

    monkeypatch.setattr("owner_lens.screening.screen_company_from_history", forbidden)
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    report = size_position(
        store,
        selected,
        portfolio.snapshot_id,
        policy(severe_bear_loss_threshold=0.5),
        now=NOW,
    )
    assert {"MISSING_FEATURE7_8_CONTEXT", "SEVERE_BEAR_LOSS"} <= set(
        report["quality_cap_reasons"]
    )
    assert report["opportunity"]["business"]["missing_reason"]


def test_positive_bear_has_no_infinite_or_division_by_zero_ceiling(
    store: SqliteStore,
) -> None:
    report = preview(store, price=5)
    assert report["modeled_bear_loss"] == 0
    assert report["ceilings"]["bear_loss_budget"] is None
    assert "NON_LOSS_BEAR_IS_NOT_A_RISK_GUARANTEE" in report["warnings"]
    assert "NaN" not in canonical_json(report) and "Infinity" not in canonical_json(
        report
    )
    assert report["target_range"][1] <= policy()["max_single_position_weight"]


def test_below_hurdle_gates_new_exposure_without_automatic_action(
    store: SqliteStore,
) -> None:
    report = preview(store, price=200)
    assert report["target_range"] == [0, 0]
    assert report["status"] == "NO_POSITION"
    assert "economics_gate" in report["binding_constraints"]
    assert "ABOVE_POLICY_RANGE" in report["warnings"]


def test_exact_version_identity_and_immutable_saved_read(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    source_before = store.list_underwriting("ADBE")
    report = size_position(store, first, portfolio.snapshot_id, policy(), now=NOW)
    payload = canonical_json(report)
    saved = store.save_sizing_analysis(payload, created_at=NOW.isoformat())
    second = persist(store, "ADBE", snapshot(price=40))
    revised = portfolio_input()
    revised["cash"] = 0.6
    other_portfolio = create_portfolio(store, revised, now=NOW + timedelta(days=1))
    assert other_portfolio.snapshot_id != portfolio.snapshot_id
    assert (
        size_position(store, first, portfolio.snapshot_id, policy(), now=NOW) == report
    )
    assert (
        size_position(store, second, portfolio.snapshot_id, policy(), now=NOW)[
            "opportunity"
        ]["summary"]["current_price"]
        == 40
    )
    assert store.list_underwriting("ADBE")[0] == source_before[0]

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Saved analysis must be read without recomputation")

    monkeypatch.setattr("owner_lens.position_sizing.size_position", forbidden)
    assert store.get_sizing_analysis(saved.analysis_id).report_json == payload
    assert json.loads(payload)["portfolio"]["snapshot_id"] == portfolio.snapshot_id
    assert canonical_json(json.loads(payload)) == payload


def test_exact_decision_and_comparison_never_infer_holdings(store: SqliteStore) -> None:
    selections = four_companies(store)
    decision = create_decision(
        store, selections[0], comparison_input(store, selections), now=NOW
    )
    decisions_before, shadows_before = (
        store.list_decisions(),
        store.list_shadow_entries(),
    )
    data = portfolio_input()
    data["holdings"].pop(0)
    data["cash"] += 0.02
    portfolio = create_portfolio(store, data, now=NOW)
    report = size_position(
        store,
        selections[0],
        portfolio.snapshot_id,
        policy(),
        now=NOW,
        decision_id=decision.decision_id,
        context_data={
            "sector": "Technology",
            "industry": "Software",
            "exposure_tags": ["AI_CAPEX"],
        },
    )
    assert report["current_weight"] == 0
    assert report["decision_context"]["judgment"]["action"] == "WATCH"
    assert report["decision_context"]["comparison"]
    assert report["decision_context"]["shadows"]
    saved = store.save_sizing_analysis(
        canonical_json(report), created_at=NOW.isoformat()
    )
    assert saved.decision_id == decision.decision_id
    assert (
        store.list_decisions() == decisions_before
        and store.list_shadow_entries() == shadows_before
    )
    newer = persist(store, "ADBE", snapshot(price=25))
    with pytest.raises(SizingError, match="exact"):
        size_position(
            store,
            newer,
            portfolio.snapshot_id,
            policy(),
            decision_id=decision.decision_id,
            now=NOW,
        )
    with pytest.raises(SizingError, match="not found"):
        size_position(
            store,
            selections[0],
            portfolio.snapshot_id,
            policy(),
            decision_id="missing",
            now=NOW,
        )


def test_no_latest_or_missing_snapshot_substitution(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    with pytest.raises(SizingError, match="not found"):
        size_position(
            store,
            UnderwritingSelection("ADBE", 2),
            portfolio.snapshot_id,
            policy(),
            now=NOW,
        )
    with pytest.raises(StorageReadError, match="not found"):
        size_position(store, selected, "missing", policy(), now=NOW)
    assert not store.list_sizing_analyses()


def test_no_lookahead_and_no_future_portfolio_asof(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    with pytest.raises(SizingError, match="not available"):
        size_position(
            store,
            selected,
            portfolio.snapshot_id,
            policy(),
            now=NOW - timedelta(days=1),
        )
    with pytest.raises(SizingError, match="future"):
        create_portfolio(store, portfolio_input(as_of_date="2026-06-04"), now=NOW)
    decision = create_decision(
        store, selected, input_data(), now=NOW + timedelta(days=1)
    )
    with pytest.raises(SizingError, match="not available"):
        size_position(
            store,
            selected,
            portfolio.snapshot_id,
            policy(),
            now=NOW,
            decision_id=decision.decision_id,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "negative",
        "bool",
        "nan",
        "empty",
        "duplicate",
        "wrong_id",
        "unsupported",
        "bad_tags",
        "duplicate_tags",
        "unknown_field",
        "mixed_basis",
    ],
)
def test_invalid_portfolios_leave_no_partial_state(
    store: SqliteStore, mutation: str
) -> None:
    persist(store, "ADBE", snapshot())
    data = portfolio_input()
    holding = data["holdings"][0]
    if mutation == "negative":
        holding["weight"] = -0.1
    elif mutation == "bool":
        holding["weight"] = True
    elif mutation == "nan":
        data["cash"] = float("nan")
    elif mutation == "empty":
        data.update(holdings=[], cash=0)
    elif mutation == "duplicate":
        data["holdings"].append(deepcopy(holding))
    elif mutation == "wrong_id":
        holding["security_id"] = 99999
    elif mutation == "unsupported":
        holding["asset_type"] = "OPTION"
    elif mutation == "bad_tags":
        holding["exposure_tags"] = ["AI capex"]
    elif mutation == "duplicate_tags":
        holding["exposure_tags"] = ["AI_CAPEX", "AI_CAPEX"]
    elif mutation == "unknown_field":
        data["broker_account"] = "unsupported"
    else:
        holding["market_value"] = 100
    with pytest.raises(ValueError):
        create_portfolio(store, data, now=NOW)
    assert not store.list_portfolio_snapshots()


def test_conflicting_context_and_non_equity_holding_rejected(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    with pytest.raises(SizingError, match="agree"):
        size_position(
            store,
            selected,
            portfolio.snapshot_id,
            policy(),
            now=NOW,
            context_data={"sector": "Finance", "industry": None, "exposure_tags": []},
        )
    data = portfolio_input()
    data["holdings"][0]["asset_type"] = "ETF"
    other = create_portfolio(store, data, now=NOW)
    with pytest.raises(SizingError, match="EQUITY"):
        size_position(store, selected, other.snapshot_id, policy(), now=NOW)


@pytest.mark.parametrize("value", [-0.1, 1.1, True, float("inf")])
def test_invalid_proposal_rejected(store: SqliteStore, value: Any) -> None:
    with pytest.raises(SizingError):
        preview(store, proposed_increment=value)


def test_storage_append_only_and_invalid_report_atomic(store: SqliteStore) -> None:
    report = preview(store)
    saved = store.save_sizing_analysis(
        canonical_json(report), created_at=NOW.isoformat()
    )
    for table, field, key in (
        ("portfolio_snapshots", "snapshot_id", report["portfolio"]["snapshot_id"]),
        ("sizing_analyses", "analysis_id", saved.analysis_id),
    ):
        for operation in (
            f"UPDATE {table} SET created_at='changed' WHERE {field}=?",
            f"DELETE FROM {table} WHERE {field}=?",
            f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} WHERE {field}=?",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store._conn.execute(operation, (key,))
            store._conn.rollback()
    with pytest.raises(StorageWriteError):
        store.save_portfolio_snapshot(canonical_json(report["portfolio"]))
    for field in ("current_weight", "target_range", "model_version", "underwriting"):
        changed = deepcopy(report)
        changed[field] = 999 if field == "current_weight" else "tampered"
        with pytest.raises(StorageWriteError):
            store.save_sizing_analysis(
                canonical_json(changed), created_at=NOW.isoformat()
            )
    assert len(store.list_sizing_analyses()) == 1
    assert store.get_sizing_analysis(saved.analysis_id).report_json == canonical_json(
        report
    )


def test_v7_additive_migration_keeps_decision_state(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_decision(store, selected, input_data(), now=NOW)
    before = store.list_decisions()
    store._conn.executescript(
        "DROP TABLE sizing_analyses; DROP TABLE portfolio_snapshots; "
        "UPDATE schema_meta SET value='7' WHERE key='schema_version';"
    )
    store.initialize()
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "10"
    )
    assert store.list_decisions() == before
    assert not store.list_portfolio_snapshots() and not store.list_sizing_analyses()


def test_integrity_errors_are_explicit(store: SqliteStore) -> None:
    report = preview(store)
    saved = store.save_sizing_analysis(
        canonical_json(report), created_at=NOW.isoformat()
    )
    store._conn.executescript(
        "DROP TRIGGER sizing_no_update; UPDATE sizing_analyses SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        store.get_sizing_analysis(saved.analysis_id)
    store._conn.executescript(
        "DROP TRIGGER portfolio_no_update; UPDATE portfolio_snapshots SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        store.get_portfolio_snapshot(report["portfolio"]["snapshot_id"])


def test_cli_offline_create_preview_save_show_and_errors(
    store: SqliteStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    persist(store, "ADBE", snapshot())
    data = portfolio_input(as_of_date="2020-01-01")
    portfolio_file, policy_file = tmp_path / "portfolio.json", tmp_path / "policy.json"
    portfolio_file.write_text(canonical_json(data), encoding="utf-8")
    policy_file.write_text(canonical_json(policy()), encoding="utf-8")
    assert (
        main(
            ["portfolio", "snapshot", "create", "--file", str(portfolio_file), "--json"]
        )
        == 0
    )
    portfolio = PortfolioSnapshot.from_json(capsys.readouterr().out)
    assert main(["portfolio", "snapshot", "show", portfolio.snapshot_id, "--json"]) == 0
    assert capsys.readouterr().out.strip() == portfolio.to_json()
    args = [
        "position-size",
        "ADBE",
        "--version",
        "1",
        "--portfolio",
        portfolio.snapshot_id,
        "--policy",
        str(policy_file),
        "--json",
    ]
    assert main(args) == 0
    preview_json = capsys.readouterr().out.strip()
    assert main(args) == 0 and capsys.readouterr().out.strip() == preview_json
    assert not store.list_sizing_analyses()
    assert main([*args, "--save"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert canonical_json(saved["report"]) == preview_json
    assert main(["sizing", "show", saved["analysis_id"], "--json"]) == 0
    assert capsys.readouterr().out.strip() == preview_json
    assert main(["sizing", "history", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["analysis_id"] == saved["analysis_id"]
    assert main(["portfolio", "snapshot", "list", "--json"]) == 0
    assert (
        json.loads(capsys.readouterr().out)[0]["snapshot_id"] == portfolio.snapshot_id
    )
    assert main(["sizing", "show", "missing", "--json"]) == 1
    assert "not found" in capsys.readouterr().err
    policy_file.write_text(
        '{"category":"JUDGMENT","category":"FACT"}', encoding="utf-8"
    )
    assert main(args) == 1
    assert "Error:" in capsys.readouterr().err


def test_workbench_explicit_creation_review_save_and_history(
    store: SqliteStore,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Portfolio Context / Position Sizing"
    app.run()
    assert not app.exception and not app.error
    assert not store.list_portfolio_snapshots()
    app.text_area(key="sizing_portfolio_input").set_value(
        canonical_json(portfolio_input(as_of_date="2020-01-01"))
    )
    next(
        button for button in app.button if button.label == "Save new portfolio snapshot"
    ).click().run()
    assert not app.exception and not app.error
    portfolio = store.list_portfolio_snapshots()[0]
    app.selectbox(key="sizing_portfolio_id").set_value(portfolio.snapshot_id).run()
    app.selectbox(key="sizing_underwriting").set_value("ADBE:1").run()
    app.text_area(key="sizing_policy_input").set_value(canonical_json(policy()))
    next(
        button for button in app.button if button.label == "Review position-size range"
    ).click().run()
    assert not app.exception and not app.error and app.dataframe
    assert not store.list_sizing_analyses()
    next(
        widget
        for widget in app.checkbox
        if widget.label == "Save this sizing analysis immutably"
    ).set_value(True)
    next(
        button for button in app.button if button.label == "Review position-size range"
    ).click().run()
    assert not app.exception and not app.error and app.success
    assert len(store.list_sizing_analyses()) == 1
    app.run()
    assert len(store.list_sizing_analyses()) == 1
    assert not store.list_decisions() and not store.list_shadow_entries()


def test_documented_examples_execute_offline(store: SqliteStore) -> None:
    portfolio_data = json.loads(
        (ROOT / "docs" / "examples" / "portfolio_context.sample.json").read_text()
    )
    limits = json.loads(
        (ROOT / "docs" / "examples" / "sizing_policy.sample.json").read_text()
    )
    report = preview(store, data=portfolio_data, limits=limits)
    assert report["target_range"] == pytest.approx([0, 0.06])
    assert report["incremental_capital"]["range"] == pytest.approx([0, 4000])
    assert report["incremental_capital"]["currency"] == "USD"


@pytest.mark.parametrize(
    "basis,currency",
    [
        ("MARKET_VALUE", None),
        ("MARKET_VALUE", "usd"),
        ("WEIGHT", "USD"),
    ],
)
def test_currency_is_not_silently_assumed_or_converted(
    store: SqliteStore,
    basis: str,
    currency: str | None,
) -> None:
    data = portfolio_input(basis=basis, currency=currency)
    if basis == "MARKET_VALUE":
        for item in data["holdings"]:
            item["market_value"] = item.pop("weight") * 100000
    with pytest.raises(SizingError, match="currency"):
        create_portfolio(store, data, now=NOW)


def test_cash_only_context_and_explicit_empty_tags(store: SqliteStore) -> None:
    report = preview(
        store,
        data=portfolio_input(holdings=[], cash=1),
        context_data={
            "sector": "Technology",
            "industry": "Software",
            "exposure_tags": [],
        },
    )
    assert report["current_weight"] == 0
    assert report["cash_weight"] == 1
    assert report["ceilings"]["thesis"] == 1
    assert report["ceilings"]["sector"] == 0.4
    assert report["largest_positions"] == []
    assert not report["missing_dimensions"]


def test_unknown_unheld_opportunity_exposure_is_not_neutral(store: SqliteStore) -> None:
    report = preview(store, data=portfolio_input(holdings=[], cash=1))
    assert report["target_range"] == [0, 0]
    assert report["opportunity_context"]["sector"] is None
    assert report["opportunity_context"]["exposure_tags"] is None
    assert {"sector", "thesis"} <= set(report["binding_constraints"])
    assert "INCOMPLETE_PORTFOLIO_CONTEXT" in report["warnings"]


def test_high_sensitivity_uses_exact_9a_band(store: SqliteStore) -> None:
    report = preview(store)
    high = report["opportunity"]["quality"]["sensitivity_band"] == "HIGH"
    assert ("HIGH_LOCAL_SENSITIVITY" in report["quality_cap_reasons"]) is high
    assert report["opportunity"]["quality"]["most_sensitive_driver"]


def test_original_underwriting_evidence_cutoff_enforced(store: SqliteStore) -> None:
    original = snapshot()
    evidence = json.loads(original.evidence_json)
    evidence["lookahead"] = {"fetched_at": "2027-01-01T12:00:00+00:00"}
    selected = persist(
        store, "ADBE", replace(original, evidence_json=json.dumps(evidence))
    )
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    with pytest.raises(SizingError, match="cutoff|after"):
        size_position(store, selected, portfolio.snapshot_id, policy(), now=NOW)


def test_snapshot_identity_and_normalized_weights_cannot_be_forged(
    store: SqliteStore,
) -> None:
    persist(store, "ADBE", snapshot())
    portfolio = create_portfolio(store, portfolio_input(), now=NOW)
    for field, value in (("weight", 0.9), ("security_id", 99999)):
        changed = json.loads(portfolio.to_json())
        changed["snapshot_id"] = "new-snapshot"
        changed["holdings"][0][field] = value
        with pytest.raises(StorageWriteError):
            store.save_portfolio_snapshot(canonical_json(changed))
    changed = json.loads(portfolio.to_json())
    changed["holdings"][0]["extra"] = "not accepted"
    with pytest.raises(SizingError, match="unknown"):
        PortfolioSnapshot.from_json(canonical_json(changed))
    assert len(store.list_portfolio_snapshots()) == 1


def test_report_duplicate_json_keys_rejected_before_save(store: SqliteStore) -> None:
    report = preview(store)
    payload = canonical_json(report)
    payload = '{"model_version":"forged",' + payload[1:]
    with pytest.raises(StorageWriteError, match="Duplicate|duplicate"):
        store.save_sizing_analysis(payload, created_at=NOW.isoformat())
    assert not store.list_sizing_analyses()

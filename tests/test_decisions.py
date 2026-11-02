"""Fixture-only decision history, frozen alternatives and atomic shadow starts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_opportunity_comparison import persist, snapshot
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.cli import main
from owner_lens.decisions import (
    AlternativeDisposition,
    DecisionAction,
    DecisionError,
    DecisionSnapshot,
    ShadowEntry,
    ShadowRole,
    create_decision,
    load_decision_json,
    read_decision,
)
from owner_lens.opportunity_comparison import (
    UnderwritingSelection,
    compare_underwritings,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import StorageReadError, StorageWriteError
from owner_lens.persistence.records import SCHEMA_VERSION
from owner_lens.underwriting import (
    Reference,
    SemanticType,
    Statement,
    create_underwriting,
    parse_manual_input,
)
from owner_lens.valuation import run_valuation
from owner_lens.workbench.data import WorkbenchSource

NOW = datetime(2026, 6, 3, 12, tzinfo=UTC)
APP = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"


def input_data() -> dict[str, Any]:
    return {
        "category": "JUDGMENT",
        "action": "WATCH",
        "confidence": "MEDIUM",
        "rationale": "Expected return is attractive, but evidence verification and the AI thesis need validation.",
        "primary_reason": "Unverified thesis evidence",
        "biggest_risk": "AI disruption erodes workflow economics.",
        "what_would_change_decision": "Verified AI monetization evidence or a more favorable entry price.",
    }


def four_companies(store: SqliteStore) -> tuple[UnderwritingSelection, ...]:
    return tuple(
        persist(store, ticker, snapshot(price=price))
        for ticker, price in (
            ("ADBE", 20),
            ("GOOGL", 25),
            ("MSFT", 30),
            ("NFLX", 35),
        )
    )


def comparison_input(
    store: SqliteStore, selections: tuple[UnderwritingSelection, ...]
) -> dict[str, Any]:
    labels = [f"{item.ticker}:{item.version}" for item in selections[1:]]
    return {
        **input_data(),
        "alternatives": [
            {
                "underwriting": label,
                "disposition": disposition,
                "reason": f"Exact reason for {label}.",
            }
            for label, disposition in zip(
                labels, ["PREFERRED", "DEFERRED", "PASSED_OVER"], strict=True
            )
        ],
        "comparison": json.loads(compare_underwritings(store, selections).to_json()),
        "shadow": {
            "include_benchmark": True,
            "alternatives": [
                {"underwriting": labels[0], "role": "BEST_ALTERNATIVE"},
                {"underwriting": labels[2], "role": "PASS_CANDIDATE"},
            ],
        },
    }


def test_exact_identity_immutable_history_and_changed_mind(store: SqliteStore) -> None:
    original = persist(store, "ADBE", snapshot())
    before = store.list_underwriting("ADBE")
    first = create_decision(store, original, input_data(), now=NOW)
    persist(store, "ADBE", snapshot(price=10))
    changed = {
        **input_data(),
        "action": "BUY",
        "rationale": "New judgment, not a rewrite.",
    }
    second = create_decision(
        store, original, changed, now=datetime(2026, 7, 1, tzinfo=UTC)
    )
    records = store.list_decisions("ADBE")
    assert [read_decision(item).judgment.action for item in records] == [
        DecisionAction.WATCH,
        DecisionAction.BUY,
    ]
    assert first.decision_id != second.decision_id
    assert first.chosen.underwriting == before[0] == store.list_underwriting("ADBE")[0]
    assert (
        first.chosen.summary["current_price"]
        == second.chosen.summary["current_price"]
        == 20
    )
    assert first.chosen.underwriting.version == 1
    assert first.chosen.underwriting.underwriting_id == before[0].underwriting_id
    with pytest.raises(FrozenInstanceError):
        first.judgment.action = DecisionAction.EXIT  # type: ignore[misc]
    with pytest.raises(DecisionError, match="not found"):
        create_decision(store, UnderwritingSelection("ADBE", 99), input_data(), now=NOW)


def test_exact_alternatives_comparison_shadow_and_roundtrip(store: SqliteStore) -> None:
    selections = four_companies(store)
    data = comparison_input(store, selections)
    before = {item.ticker: store.list_underwriting(item.ticker) for item in selections}
    decision = create_decision(store, selections[0], data, now=NOW)
    expected = decision.to_json()
    assert DecisionSnapshot.from_json(expected).to_json() == expected
    assert read_decision(store.list_decisions("ADBE")[0]).to_json() == expected
    assert json.loads(decision.comparison_json) == data["comparison"]
    assert [item.opportunity.label for item in decision.alternatives] == [
        "GOOGL:1",
        "MSFT:1",
        "NFLX:1",
    ]
    assert decision.alternatives[0].disposition == AlternativeDisposition.PREFERRED
    assert [item.role for item in decision.shadows] == [
        ShadowRole.ACTUAL_CHOICE,
        ShadowRole.BEST_ALTERNATIVE,
        ShadowRole.PASS_CANDIDATE,
        ShadowRole.BENCHMARK,
    ]
    for entry in decision.shadows:
        assert entry.decision_at == decision.decision_at
        assert entry.as_of_date == decision.as_of_date
        assert entry.state == "DECISION_STATE"
        assert entry.outcome_state == "NOT_OBSERVED"
        assert entry.notional_usd == 100
        assert entry.basis == "INDEPENDENT_HYPOTHETICAL_100_USD"
        assert entry.action == DecisionAction.WATCH  # not an actual trade assertion
        assert (
            ShadowEntry.from_data(json.loads(entry.to_json())).to_json()
            == entry.to_json()
        )
    benchmark = decision.shadows[-1]
    assert benchmark.ticker == "^GSPC"
    assert (
        benchmark.security_id
        is benchmark.underwriting_id
        is benchmark.frozen_price
        is None
    )
    assert benchmark.missing_reason
    assert decision.shadows[1].frozen_price == 25
    assert decision.shadows[2].ticker == "NFLX"
    rows = store.list_shadow_entries(decision.decision_id)
    assert [row.snapshot_json for row in rows] == [
        entry.to_json() for entry in decision.shadows
    ]
    for ticker, records in before.items():
        assert store.list_underwriting(ticker) == records
    persist(store, "GOOGL", snapshot(price=5))
    persist(store, "ADBE", snapshot(price=8))
    assert read_decision(store.list_decisions("ADBE")[0]).to_json() == expected
    assert store.list_shadow_entries(decision.decision_id) == rows


def test_optional_state_is_explicit_and_saved_hurdle_semantics(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(store, selected, input_data(), now=NOW)
    data = json.loads(decision.to_json())
    assert data["alternatives"] == [] and data["alternatives_status"] == "NONE_RECORDED"
    assert data["comparison"] is None and data["comparison_status"] == "NOT_PROVIDED"
    assert not data["shadow_requested"] and data["shadows"] == []
    assert decision.judgment.category == "JUDGMENT"
    summary = decision.chosen.summary
    assert summary["investor_policy"]["required_return"] == 0.12
    assert summary["investor_policy"]["category"] == "JUDGMENT"
    assert summary["category"] == "CALCULATION"
    assert summary["scenarios"][0]["probability"]["category"] == "JUDGMENT"
    assert summary["variant"]["drivers"][0]["assumption_category"] == "ASSUMPTION"
    raw_snapshot = json.loads(decision.chosen.underwriting.snapshot_json)
    assert raw_snapshot["evidence"]["eod_price"]["category"] == "FACT"
    assert summary["variant"]["drivers"][0]["consensus"]["category"] == "EXPECTATION"
    assert summary["variant"]["drivers"][0]["sensitivity"]["category"] == "CALCULATION"


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE decision_records SET ticker='OTHER'",
        "DELETE FROM decision_records",
        "INSERT OR REPLACE INTO decision_records SELECT * FROM decision_records",
        "UPDATE shadow_entries SET role='BENCHMARK'",
        "DELETE FROM shadow_entries",
        "INSERT OR REPLACE INTO shadow_entries SELECT * FROM shadow_entries",
    ],
)
def test_database_immutability_triggers(store: SqliteStore, operation: str) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(
        store,
        selected,
        {
            **input_data(),
            "shadow": {"alternatives": [], "include_benchmark": True},
        },
        now=NOW,
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(operation)
    store._conn.rollback()
    assert read_decision(store.list_decisions("ADBE")[0]) == decision
    assert len(store.list_shadow_entries()) == 2
    with pytest.raises(StorageWriteError, match="immutable"):
        store.save_decision(decision.to_json())


def test_replace_conflict_cannot_bypass_shadow_immutability(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    decision = create_decision(
        store,
        selected,
        {
            **input_data(),
            "shadow": {"alternatives": [], "include_benchmark": True},
        },
        now=NOW,
    )
    entry = store.list_shadow_entries()[0]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(
            "INSERT OR REPLACE INTO shadow_entries VALUES(?, ?, ?, ?, ?, ?)",
            (
                "new-id",
                entry.decision_id,
                entry.underwriting_id,
                entry.role,
                entry.snapshot_json,
                entry.content_hash,
            ),
        )
    store._conn.rollback()
    assert len(store.list_shadow_entries(decision.decision_id)) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["shadow"]["alternatives"].append(d["shadow"]["alternatives"][0]),
        lambda d: d["shadow"]["alternatives"].append(
            {"underwriting": "MSFT:1", "role": "BEST_ALTERNATIVE"}
        ),
        lambda d: d["shadow"]["alternatives"].append(
            {"underwriting": "ADBE:1", "role": "PASS_CANDIDATE"}
        ),
        lambda d: d["shadow"]["alternatives"][0].update(role="ACTUAL_CHOICE"),
        lambda d: d["shadow"]["alternatives"][0].update(role="BENCHMARK"),
        lambda d: d["shadow"]["alternatives"][0].update(role="PASS_CANDIDATE"),
        lambda d: d["shadow"]["alternatives"][1].update(role="BEST_ALTERNATIVE"),
        lambda d: d["shadow"].update(include_benchmark="yes"),
        lambda d: d["alternatives"].append(d["alternatives"][0]),
        lambda d: d["alternatives"][0].update(underwriting="GOOGL:99"),
        lambda d: d["alternatives"][0].update(underwriting="GOOGL"),
        lambda d: d["alternatives"][0].update(reason=""),
        lambda d: d.update(alternatives=None),
    ],
)
def test_invalid_alternatives_and_shadow_roles_reject_atomically(
    store: SqliteStore, mutation: Any
) -> None:
    selections = four_companies(store)
    data = comparison_input(store, selections)
    mutation(data)
    with pytest.raises(DecisionError):
        create_decision(store, selections[0], data, now=NOW)
    assert store.list_decisions() == () and store.list_shadow_entries() == ()


def test_shadow_write_failure_rolls_back_whole_decision(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    store._conn.executescript(
        "CREATE TRIGGER reject_shadow BEFORE INSERT ON shadow_entries BEGIN "
        "SELECT RAISE(ABORT, 'fixture failure'); END;"
    )
    with pytest.raises(StorageWriteError, match="fixture failure"):
        create_decision(
            store,
            selected,
            {
                **input_data(),
                "shadow": {"alternatives": [], "include_benchmark": True},
            },
            now=NOW,
        )
    assert store.list_decisions() == ()
    assert store.list_shadow_entries() == ()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(decision_at="2026-06-02T11:00:00+00:00"),
        lambda d: d.update(decision_at="2026-06-04T00:00:00+00:00"),
        lambda d: d.update(as_of_date="2026-06-01"),
        lambda d: d.update(as_of_date="2026-06-04"),
        lambda d: d.update(decision_at="2026-06-03T00:00:00"),
    ],
)
def test_no_lookahead_decision_clock(store: SqliteStore, mutation: Any) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = input_data()
    mutation(data)
    with pytest.raises(DecisionError):
        create_decision(store, selected, data, now=NOW)
    assert not store.list_decisions()


def test_alternative_and_underlying_evidence_cutoffs(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    later = store.save_underwriting(
        security_id=store.list_underwriting("ADBE")[0].security_id,
        ticker="ADBE",
        created_at="2026-06-04T00:00:00+00:00",
        as_of_date="2026-06-02",
        snapshot_json=snapshot().to_json(),
    )
    run_valuation(store, later)
    with pytest.raises(DecisionError, match="cutoff"):
        create_decision(
            store,
            selected,
            {
                **input_data(),
                "alternatives": [
                    {
                        "underwriting": "ADBE:2",
                        "disposition": "DEFERRED",
                        "reason": "Not yet available",
                    }
                ],
            },
            now=NOW,
        )
    original = snapshot()
    future = replace(
        original,
        manual=replace(
            original.manual,
            supporting_evidence=(
                Statement(
                    SemanticType.JUDGMENT,
                    "Future",
                    (Reference(observed_at="2026-06-03"),),
                ),
            ),
        ),
    )
    broken = persist(store, "NFLX", future)
    with pytest.raises(DecisionError, match="cutoff"):
        create_decision(store, broken, input_data(), now=NOW)


def test_no_latest_reconstruction_or_current_observations(
    store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    selections = four_companies(store)
    data = comparison_input(store, selections)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Must not use current evidence or latest saved advisory runs.")

    monkeypatch.setattr(store, "get_underwriting_evidence", forbidden)
    monkeypatch.setattr(store, "list_challenger_runs", forbidden)
    decision = create_decision(store, selections[0], data, now=NOW)

    def no_recompute(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Read must not recompute the frozen decision.")

    monkeypatch.setattr("owner_lens.decisions.load_opportunity", no_recompute)
    monkeypatch.setattr("owner_lens.decisions.compare_underwritings", no_recompute)
    assert (
        read_decision(store.list_decisions("ADBE")[0]).to_json() == decision.to_json()
    )
    assert len(store.list_shadow_entries()) == 4


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(category="FACT"),
        lambda d: d.update(action="AUTOBUY"),
        lambda d: d.update(confidence=0.8),
        lambda d: d.update(rationale=" "),
        lambda d: d.update(primary_reason=""),
        lambda d: d.update(biggest_risk=None),
        lambda d: d.update(what_would_change_decision=""),
        lambda d: d.update(required_return=0.2),
        lambda d: d.update(weight=0.1),
    ],
)
def test_strict_judgment_boundary(store: SqliteStore, mutation: Any) -> None:
    selected = persist(store, "ADBE", snapshot())
    data = input_data()
    mutation(data)
    with pytest.raises(DecisionError):
        create_decision(store, selected, data, now=NOW)


def test_v2_decision_retains_source_bytes_and_policy_across_revisions(
    source: WorkbenchSource,
) -> None:
    sample = (
        Path(__file__).parents[1]
        / "docs"
        / "examples"
        / "adbe_consolidated_underwriting.sample.json"
    )
    manual = parse_manual_input(json.loads(sample.read_text()))
    assert isinstance(source.store, SqliteStore)
    first = create_underwriting(
        source,
        "ADBE",
        manual,
        now=datetime(2026, 6, 2, 12, tzinfo=UTC),
    )
    run_valuation(source.store, first)
    decision = create_decision(
        source.store,
        UnderwritingSelection("ADBE", first.version),
        input_data(),
        now=NOW,
    )
    assert json.loads(decision.chosen.underwriting.snapshot_json)["schema_version"] == 2
    expected = decision.to_json()
    assert manual.investor_policy is not None
    revised = replace(
        manual, investor_policy=replace(manual.investor_policy, required_return=0.25)
    )
    second = create_underwriting(
        source,
        "ADBE",
        revised,
        now=datetime(2026, 6, 3, 10, tzinfo=UTC),
    )
    run_valuation(source.store, second)
    new_decision = create_decision(
        source.store,
        UnderwritingSelection("ADBE", second.version),
        input_data(),
        now=NOW,
    )
    assert new_decision.chosen.summary["investor_policy"]["required_return"] == 0.25
    assert (
        decision.chosen.summary["investor_policy"]["required_return"]
        == manual.investor_policy.required_return
    )
    assert source.store.list_decisions("ADBE")[0].snapshot_json == expected


def test_documented_four_company_example_is_executable_offline(
    store: SqliteStore,
) -> None:
    selected = None
    for ticker, versions in (("ADBE", 7), ("GOOGL", 2), ("MSFT", 2), ("NFLX", 1)):
        for _ in range(versions):
            selection = persist(store, ticker, snapshot())
            if ticker == "ADBE":
                selected = selection
    assert selected is not None
    path = Path(__file__).parents[1] / "docs" / "examples" / "adbe_decision.sample.json"
    decision = create_decision(
        store, selected, load_decision_json(path.read_text()), now=NOW
    )
    assert decision.chosen.label == "ADBE:7"
    assert [item.opportunity.label for item in decision.alternatives] == [
        "GOOGL:2",
        "MSFT:2",
        "NFLX:1",
    ]
    assert [(entry.ticker, entry.role.value) for entry in decision.shadows] == [
        ("ADBE", "ACTUAL_CHOICE"),
        ("GOOGL", "BEST_ALTERNATIVE"),
        ("NFLX", "PASS_CANDIDATE"),
        ("^GSPC", "BENCHMARK"),
    ]


def test_shadow_integrity_failure_and_missing_bundle_rows_are_explicit(
    store: SqliteStore,
) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_decision(
        store,
        selected,
        {
            **input_data(),
            "shadow": {"alternatives": [], "include_benchmark": True},
        },
        now=NOW,
    )
    store._conn.executescript(
        "DROP TRIGGER shadow_no_update; UPDATE shadow_entries SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        store.list_shadow_entries()
    store._conn.executescript(
        "DROP TRIGGER shadow_no_delete; DELETE FROM shadow_entries;"
    )
    with pytest.raises(StorageReadError, match="bundle"):
        store.list_shadow_entries()


def test_malformed_and_duplicate_json_rejected() -> None:
    with pytest.raises(DecisionError, match="Duplicate"):
        load_decision_json('{"action":"WATCH","action":"BUY"}')
    with pytest.raises(DecisionError, match="Non-finite"):
        load_decision_json('{"confidence":NaN}')
    with pytest.raises(DecisionError):
        DecisionSnapshot.from_json("{}")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["chosen"]["opportunity"]["summary"].update(current_price=999),
        lambda d: d["chosen"]["underwriting"].update(version=99),
        lambda d: d["shadows"][0].update(frozen_price=999),
        lambda d: d["shadows"][0].update(decision_at="2027-01-01T00:00:00+00:00"),
        lambda d: d["shadows"][0].update(basis="PORTFOLIO_WEIGHT"),
        lambda d: d["shadows"][0].update(state="CURRENT_OBSERVATION"),
        lambda d: d["comparison"]["pairs"][0].update(conclusion="AUTOBUY"),
        lambda d: d.update(alternatives_status="NONE_RECORDED"),
    ],
)
def test_storage_rejects_forged_decision_bundle(
    store: SqliteStore, mutation: Any
) -> None:
    selections = four_companies(store)
    original = create_decision(
        store, selections[0], comparison_input(store, selections), now=NOW
    )
    data = json.loads(original.to_json())
    data["decision_id"] = "forged-decision"
    for entry in data["shadows"]:
        entry["decision_id"] = "forged-decision"
        entry["shadow_id"] += "-forged"
    mutation(data)
    with pytest.raises(StorageWriteError):
        store.save_decision(json.dumps(data))
    assert len(store.list_decisions()) == 1


def test_comparison_snapshot_must_match_exact_alternatives(store: SqliteStore) -> None:
    selections = four_companies(store)
    data = comparison_input(store, selections)
    data["comparison"]["opportunities"][0]["summary"]["current_price"] = 1
    with pytest.raises(DecisionError, match="comparison"):
        create_decision(store, selections[0], data, now=NOW)
    data = comparison_input(store, selections)
    data["alternatives"].pop()
    with pytest.raises(DecisionError):
        create_decision(store, selections[0], data, now=NOW)


def test_integrity_failure_explicit(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    create_decision(store, selected, input_data(), now=NOW)
    store._conn.executescript(
        "DROP TRIGGER decision_no_update; UPDATE decision_records SET content_hash='bad';"
    )
    with pytest.raises(StorageReadError, match="integrity"):
        store.list_decisions()


def test_v6_additive_migration_keeps_underwriting(store: SqliteStore) -> None:
    selected = persist(store, "ADBE", snapshot())
    before = store.list_underwriting("ADBE")
    store._conn.executescript(
        "DROP TABLE shadow_entries; DROP TABLE decision_records; "
        "UPDATE schema_meta SET value='6' WHERE key='schema_version';"
    )
    store.initialize()
    assert (
        int(
            store._conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
        )
        == SCHEMA_VERSION
        == 11
    )
    assert store.list_underwriting("ADBE") == before
    decision = create_decision(store, selected, input_data(), now=NOW)
    store.initialize()
    assert read_decision(store.list_decisions("ADBE")[0]) == decision


def test_cli_roundtrip_history_shadow_and_exact_show(
    store: SqliteStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selections = four_companies(store)
    data = comparison_input(store, selections)
    data["decision_at"] = NOW.isoformat()
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert (
        main(
            [
                "decision",
                "create",
                "ADBE",
                "--version",
                "1",
                "--file",
                str(path),
                "--json",
            ]
        )
        == 0
    )
    payload = capsys.readouterr().out.strip()
    decision = DecisionSnapshot.from_json(payload)
    args = ["decision", "show", "ADBE", "--decision-id", decision.decision_id, "--json"]
    assert main(args) == 0
    assert capsys.readouterr().out.strip() == payload
    assert main(args) == 0
    assert capsys.readouterr().out.strip() == payload
    assert main(["decision", "history", "ADBE", "--json"]) == 0
    assert capsys.readouterr().out.strip() == "[" + payload + "]"
    assert main(["shadow", "show", "--json"]) == 0
    shadows = capsys.readouterr().out.strip()
    assert json.loads(shadows) == [
        json.loads(entry.to_json()) for entry in decision.shadows
    ]
    assert main(["shadow", "show", "--json"]) == 0
    assert capsys.readouterr().out.strip() == shadows
    assert main(["decision", "show", "ADBE", "--decision-id", "missing", "--json"]) == 1
    assert "not found" in capsys.readouterr().err
    assert main(["shadow", "show", "--decision-id", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert (
        main(["decision", "create", "ADBE", "--version", "99", "--file", str(path)])
        == 1
    )
    assert "not found" in capsys.readouterr().err
    assert main(["decision", "show", "ADBE"]) == 0
    assert "Decision [JUDGMENT]: WATCH" in capsys.readouterr().out
    assert main(["shadow", "show"]) == 0
    assert "MISSING (benchmark placeholder)" in capsys.readouterr().out
    assert len(store.list_decisions()) == 1


def test_workbench_decision_create_history_and_shadow(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    persist(store, "ADBE", snapshot())
    persist(store, "ADBE", snapshot(price=10))
    persist(store, "GOOGL", snapshot(price=25))
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Decisions"
    app.run()
    assert not app.exception and not app.error
    picker = app.selectbox(key="decision_selected_underwriting")
    assert picker.value is None
    assert set(picker.options) == {"ADBE:1", "ADBE:2", "GOOGL:1"}
    picker.set_value("ADBE:1").run()
    assert not app.exception
    # Invalid submit must show an error and create nothing.
    next(
        button for button in app.button if button.label == "Save new immutable decision"
    ).click().run()
    assert app.error and not store.list_decisions()

    def set_field(group: Any, label: str, value: Any) -> None:
        next(widget for widget in group if widget.label == label).set_value(value)

    set_field(app.selectbox, "Action [JUDGMENT]", "WATCH")
    set_field(app.selectbox, "Confidence [JUDGMENT]", "MEDIUM")
    set_field(app.text_area, "Rationale [JUDGMENT]", "Exact UI rationale")
    set_field(app.text_input, "Primary reason [JUDGMENT]", "Needs work")
    set_field(app.text_area, "Biggest risk [JUDGMENT]", "Thesis uncertainty")
    set_field(
        app.text_area, "What would change the decision [JUDGMENT]", "Verified evidence"
    )
    set_field(app.checkbox, "Create independent hypothetical $100 shadow entries", True)
    next(
        button for button in app.button if button.label == "Save new immutable decision"
    ).click().run()
    assert not app.exception and not app.error
    assert app.success
    decision = read_decision(store.list_decisions("ADBE")[0])
    assert decision.chosen.underwriting.version == 1
    assert decision.chosen.summary["current_price"] == 20
    assert decision.judgment.rationale == "Exact UI rationale"
    app.run()
    assert len(store.list_decisions()) == 1  # rerun is not a second explicit save
    app.radio(key="page").set_value("Shadow Portfolio").run()
    assert not app.exception and not app.error and app.dataframe
    table = app.dataframe[0].value
    assert set(table["Role"]) == {"ACTUAL_CHOICE", "BENCHMARK"}
    assert not app.text_input and not app.number_input


def test_workbench_comparison_handoff_freezes_context(store: SqliteStore) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    selections = four_companies(store)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["page"] = "Opportunity Comparison"
    app.session_state["opportunity_versions"] = ["ADBE:1", "GOOGL:1"]
    app.run()
    next(
        button
        for button in app.button
        if button.label == "Record a decision from this comparison"
    ).click().run()
    assert not app.exception and not app.error
    assert app.radio(key="page").value == "Decisions"
    assert (
        len(json.loads(app.session_state["decision_comparison_json"])["opportunities"])
        == 2
    )
    app.selectbox(key="decision_selected_underwriting").set_value("ADBE:1").run()
    labels = [widget.label for widget in app.text_area]
    assert "GOOGL:1: why preferred, deferred or passed over" in labels
    assert "MSFT:1: why preferred, deferred or passed over" not in labels
    assert selections[0].version == 1
    next(
        widget for widget in app.selectbox if widget.label == "Action [JUDGMENT]"
    ).set_value("WATCH")
    next(
        widget for widget in app.selectbox if widget.label == "Confidence [JUDGMENT]"
    ).set_value("MEDIUM")
    next(
        widget for widget in app.text_area if widget.label == "Rationale [JUDGMENT]"
    ).set_value("Conditional thesis needs verification")
    next(
        widget
        for widget in app.text_input
        if widget.label == "Primary reason [JUDGMENT]"
    ).set_value("Evidence")
    next(
        widget for widget in app.text_area if widget.label == "Biggest risk [JUDGMENT]"
    ).set_value("AI economics")
    next(
        widget
        for widget in app.text_area
        if widget.label == "What would change the decision [JUDGMENT]"
    ).set_value("Verify evidence")
    next(
        widget for widget in app.selectbox if widget.label == "GOOGL:1: disposition"
    ).set_value("DEFERRED")
    next(
        widget
        for widget in app.text_area
        if widget.label == "GOOGL:1: why preferred, deferred or passed over"
    ).set_value("Exact alternative reason")
    next(
        button for button in app.button if button.label == "Save new immutable decision"
    ).click().run()
    assert not app.exception and not app.error
    assert app.success
    decision = read_decision(store.list_decisions("ADBE")[0])
    assert decision.comparison_json == app.session_state["decision_comparison_json"]
    assert decision.alternatives[0].reason == "Exact alternative reason"

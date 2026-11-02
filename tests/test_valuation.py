"""Deterministic scenario math, strict inputs, and immutable version isolation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from owner_lens.cli import main
from owner_lens.persistence import SqliteStore, UnderwritingRecord, compute_content_hash
from owner_lens.persistence.records import (
    UniverseConstituentRecord,
    UniverseSnapshotRecord,
)
from owner_lens.underwriting import (
    FinancialState,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    parse_manual_input,
    parse_scenarios,
)
from owner_lens.valuation import (
    MODEL_VERSION,
    ValuationError,
    run_valuation,
    value_underwriting,
)
from owner_lens.workbench.data import open_source

_SAMPLE = (
    Path(__file__).parents[1] / "docs" / "examples" / "adbe_underwriting.sample.json"
)


def scenario_inputs() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "category": "ASSUMPTION",
            "narrative": f"Fixture {name}",
            "revenue_cagr": growth,
            "fcf_margin_year5": margin,
            "share_count_cagr": shares,
            "terminal_fcf_multiple": multiple,
            "horizon_years": 5,
        }
        for name, growth, margin, shares, multiple in (
            ("BEAR", 0.0, 0.1, 0.0, 10.0),
            ("BASE", 0.1, 0.2, -0.02, 20.0),
            ("BULL", 0.2, 0.3, -0.04, 30.0),
        )
    ]


def snapshot_input() -> UnderwritingSnapshot:
    manual = json.loads(_SAMPLE.read_text())
    manual["forward_assumptions"] = []
    manual["scenarios"] = scenario_inputs()
    return UnderwritingSnapshot(
        parse_manual_input(manual),
        (
            FinancialState("revenue", 1000, "USD", 2025),
            FinancialState("diluted_shares", 100, "shares", 2025),
        ),
        (),
        json.dumps(
            {
                "eod_price": {
                    "category": "FACT",
                    "value": {
                        "close": 20.0,
                        "market_date": "2026-06-01",
                        "snapshot_id": 7,
                        "content_hash": "price-fixture",
                        "fetched_at": "2026-06-01T12:00:00+00:00",
                        "currency": "USD",
                        "evidence_kind": "FACT",
                    },
                }
            }
        ),
        2025,
    )


def record_from(
    snapshot: UnderwritingSnapshot, *, version: int = 1
) -> UnderwritingRecord:
    payload = snapshot.to_json()
    return UnderwritingRecord(
        f"fixture-{version}",
        1,
        "ADBE",
        version,
        "2026-06-02T12:00:00+00:00",
        "2026-06-02",
        payload,
        compute_content_hash(payload.encode()),
    )


@pytest.fixture
def record() -> UnderwritingRecord:
    return record_from(snapshot_input())


def test_exact_terminal_multiple_math_and_intermediates(
    record: UnderwritingRecord,
) -> None:
    result = value_underwriting(record)
    bear, base, bull = result.scenarios
    assert bear.assumptions.name == "BEAR"
    assert bear.year5_revenue == 1000
    assert bear.year5_fcf == 100
    assert bear.year5_diluted_shares == 100
    assert bear.year5_fcf_per_share == 1
    assert bear.year5_equity_value == 1000
    assert bear.year5_value_per_share == 10
    assert bear.implied_5y_cagr == pytest.approx(0.5**0.2 - 1)
    assert base.year5_revenue == pytest.approx(1000 * 1.1**5)
    assert base.year5_diluted_shares == pytest.approx(100 * 0.98**5)
    assert base.year5_fcf == pytest.approx(1000 * 1.1**5 * 0.2)
    assert base.year5_equity_value == pytest.approx(base.year5_fcf * 20)
    assert base.year5_value_per_share == pytest.approx(base.year5_fcf_per_share * 20)
    assert base.implied_5y_cagr == pytest.approx(
        (base.year5_value_per_share / 20) ** 0.2 - 1
    )
    assert bull.year5_revenue == pytest.approx(1000 * 1.2**5)
    assert (
        bear.year5_value_per_share
        < base.year5_value_per_share
        < bull.year5_value_per_share
    )
    assert all(
        item.category is SemanticType.CALCULATION
        and item.assumptions.category is SemanticType.ASSUMPTION
        for item in result.scenarios
    )
    assert result.input_category is SemanticType.FACT
    assert result.underwriting_content_hash == record.content_hash
    assert result.price_snapshot_id == 7 and result.market_date == "2026-06-01"
    assert value_underwriting(record).to_json() == result.to_json()


def test_scenarios_do_not_inherit_generic_or_other_scenario_assumptions(
    record: UnderwritingRecord,
) -> None:
    snapshot = snapshot_input()
    scenarios = list(snapshot.manual.scenarios)
    scenarios[0] = replace(scenarios[0], terminal_fcf_multiple=15)
    changed = record_from(
        replace(snapshot, manual=replace(snapshot.manual, scenarios=tuple(scenarios)))
    )
    old, new = value_underwriting(record), value_underwriting(changed)
    assert (
        new.scenarios[0].year5_equity_value == old.scenarios[0].year5_equity_value * 1.5
    )
    assert new.scenarios[1:] == old.scenarios[1:]


@pytest.mark.parametrize("growth", (0.0, -0.2, 0.15))
def test_share_count_compounds_without_rounding(growth: float) -> None:
    snapshot = snapshot_input()
    scenarios = tuple(
        replace(item, share_count_cagr=growth) for item in snapshot.manual.scenarios
    )
    result = value_underwriting(
        record_from(
            replace(snapshot, manual=replace(snapshot.manual, scenarios=scenarios))
        )
    )
    assert result.scenarios[1].year5_diluted_shares == pytest.approx(
        100 * (1 + growth) ** 5
    )


def test_zero_fcf_is_zero_value_and_minus_one_cagr() -> None:
    snapshot = snapshot_input()
    scenarios = tuple(
        replace(item, fcf_margin_year5=0) for item in snapshot.manual.scenarios
    )
    result = value_underwriting(
        record_from(
            replace(snapshot, manual=replace(snapshot.manual, scenarios=scenarios))
        )
    )
    assert all(
        item.year5_fcf == item.year5_value_per_share == 0 and item.implied_5y_cagr == -1
        for item in result.scenarios
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("revenue_cagr", -1),
        ("revenue_cagr", "-0.1"),
        ("revenue_cagr", True),
        ("revenue_cagr", float("nan")),
        ("share_count_cagr", -1.01),
        ("fcf_margin_year5", -0.01),
        ("fcf_margin_year5", 1.01),
        ("terminal_fcf_multiple", 0),
        ("terminal_fcf_multiple", -20),
        ("terminal_fcf_multiple", float("inf")),
        ("terminal_fcf_multiple", None),
        ("horizon_years", 4),
        ("horizon_years", 5.0),
        ("horizon_years", True),
        ("name", "base"),
        ("name", "UPSIDE"),
        ("narrative", ""),
        ("category", "CALCULATION"),
    ),
)
def test_invalid_scenario_contract(field: str, value: Any) -> None:
    data = scenario_inputs()
    data[1][field] = value
    with pytest.raises(UnderwritingError):
        parse_scenarios(data)


def test_missing_duplicate_and_unknown_scenarios() -> None:
    data = scenario_inputs()
    for invalid in (data[:2], [data[0], data[0], data[2]]):
        with pytest.raises(UnderwritingError, match="exactly|Duplicate"):
            parse_scenarios(invalid)
    data[1].pop("terminal_fcf_multiple")
    with pytest.raises(UnderwritingError, match="missing"):
        parse_scenarios(data)
    data = scenario_inputs()
    data[0]["probability"] = 0.2
    with pytest.raises(UnderwritingError, match="unknown"):
        parse_scenarios(data)


def test_legacy_underwriting_does_not_get_invented_scenarios() -> None:
    snapshot = snapshot_input()
    legacy_manual = parse_manual_input(json.loads(_SAMPLE.read_text()))
    legacy = replace(snapshot, manual=legacy_manual)
    payload = legacy.to_json()
    assert "scenarios" not in json.loads(payload)["manual"]
    assert UnderwritingSnapshot.from_json(payload).to_json() == payload
    with pytest.raises(ValuationError, match="BEAR"):
        value_underwriting(record_from(legacy))


@pytest.mark.parametrize(
    "metric,value",
    (
        ("diluted_shares", 0),
        ("diluted_shares", -1),
        ("diluted_shares", None),
        ("diluted_shares", True),
        ("revenue", 0),
        ("revenue", -1),
        ("revenue", float("inf")),
    ),
)
def test_invalid_starting_facts(metric: str, value: Any) -> None:
    snapshot = snapshot_input()
    facts = tuple(
        replace(item, value=value) if item.name == metric else item
        for item in snapshot.starting_financial_state
    )
    if isinstance(value, float):
        with pytest.raises(ValueError):
            record_from(replace(snapshot, starting_financial_state=facts))
    else:
        with pytest.raises(ValuationError, match="Starting"):
            value_underwriting(
                record_from(replace(snapshot, starting_financial_state=facts))
            )


@pytest.mark.parametrize("value", (None, 0, -20, True, "20"))
def test_missing_or_invalid_price(value: Any) -> None:
    snapshot = snapshot_input()
    evidence = json.loads(snapshot.evidence_json)
    if value is None:
        evidence["eod_price"]["value"] = None
    else:
        evidence["eod_price"]["value"]["close"] = value
    with pytest.raises(ValuationError, match="price"):
        value_underwriting(
            record_from(replace(snapshot, evidence_json=json.dumps(evidence)))
        )


def test_mismatched_years_categories_and_currency_fail() -> None:
    snapshot = snapshot_input()
    for fact in (
        replace(snapshot.starting_financial_state[0], fiscal_year=2024),
        replace(snapshot.starting_financial_state[0], category=SemanticType.ASSUMPTION),
    ):
        with pytest.raises(ValuationError):
            value_underwriting(
                record_from(
                    replace(
                        snapshot,
                        starting_financial_state=(
                            fact,
                            snapshot.starting_financial_state[1],
                        ),
                    )
                )
            )
    evidence = json.loads(snapshot.evidence_json)
    evidence["eod_price"]["value"]["currency"] = "EUR"
    with pytest.raises(ValuationError, match="currency"):
        value_underwriting(
            record_from(replace(snapshot, evidence_json=json.dumps(evidence)))
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("revenue_cagr", 1e100),
        ("share_count_cagr", 1e100),
        ("share_count_cagr", -0.9999999999999999),
    ),
)
def test_nonfinite_or_underflowed_calculations_fail(field: str, value: float) -> None:
    snapshot = snapshot_input()
    scenarios = tuple(
        replace(item, **{field: value}) for item in snapshot.manual.scenarios
    )
    modified = record_from(
        replace(snapshot, manual=replace(snapshot.manual, scenarios=scenarios))
    )
    if field == "share_count_cagr" and value < 0:
        # Very small but representable positive shares are valid; results stay finite.
        assert value_underwriting(modified).scenarios[0].year5_diluted_shares > 0
    else:
        with pytest.raises(ValuationError, match="numeric range"):
            value_underwriting(modified)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("OWNER_LENS_DB_PATH", str(tmp_path / "valuation.sqlite"))
    monkeypatch.setenv("OWNER_LENS_RAW_DATA_PATH", str(tmp_path / "raw"))
    monkeypatch.setattr(
        httpx.Client,
        "send",
        lambda *args, **kw: pytest.fail("Valuation must stay offline"),
    )
    with open_source() as source:
        store = source.store
        payload = b'[{"symbol":"ADBE"}]'
        store.save_universe_snapshot(
            UniverseSnapshotRecord(
                "fmp", "2026-06-01", "fixture://universe", compute_content_hash(payload)
            ),
            (UniverseConstituentRecord("ADBE", "Adobe", None),),
            raw_payload=payload,
            state_symbols=(),
            datasets=(),
            created_at="2026-06-01",
        )
        yield store


def _persist(store: SqliteStore, snapshot: UnderwritingSnapshot) -> UnderwritingRecord:
    return store.save_underwriting(
        security_id=1,
        ticker="ADBE",
        created_at="2026-06-02T12:00:00+00:00",
        as_of_date="2026-06-02",
        snapshot_json=snapshot.to_json(),
    )


def test_cli_persistence_repeat_and_version_isolation(
    store: SqliteStore, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = snapshot_input()
    first = _persist(store, snapshot)
    assert main(["valuation", "show", "ADBE", "--version", "1"]) == 1
    assert "Run 'valuation run' first" in capsys.readouterr().err
    assert main(["valuation", "run", "ADBE", "--version", "1"]) == 0
    original = capsys.readouterr().out
    assert json.loads(original)["underwriting_id"] == first.underwriting_id
    assert main(["valuation", "run", "ADBE", "--version", "1"]) == 0
    assert capsys.readouterr().out == original
    changed_scenarios = tuple(
        replace(item, revenue_cagr=item.revenue_cagr + 0.05)
        for item in snapshot.manual.scenarios
    )
    revised = _persist(
        store,
        replace(snapshot, manual=replace(snapshot.manual, scenarios=changed_scenarios)),
    )
    assert revised.version == 2
    assert main(["valuation", "run", "ADBE", "--version", "2"]) == 0
    revised_output = capsys.readouterr().out
    assert revised_output != original
    assert main(["valuation", "show", "ADBE", "--version", "1"]) == 0
    assert capsys.readouterr().out == original
    assert (
        store._conn.execute("SELECT COUNT(*) FROM valuation_results").fetchone()[0] == 2
    )
    assert main(["valuation", "run", "ADBE", "--version", "99"]) == 1
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "operation",
    (
        "UPDATE valuation_results SET result_json='{}'",
        "DELETE FROM valuation_results",
        "INSERT OR REPLACE INTO valuation_results SELECT * FROM valuation_results",
    ),
)
def test_results_are_immutable(store: SqliteStore, operation: str) -> None:
    record = _persist(store, snapshot_input())
    output = run_valuation(store, record)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(operation)
    store._conn.rollback()
    assert store.get_valuation(record.underwriting_id, MODEL_VERSION) == output


def test_v4_migration_keeps_old_underwriting_exact(store: SqliteStore) -> None:
    old = _persist(
        store,
        replace(
            snapshot_input(), manual=parse_manual_input(json.loads(_SAMPLE.read_text()))
        ),
    )
    store._conn.execute("DROP TABLE valuation_results")
    store._conn.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
    store._conn.commit()
    store.initialize()
    assert (
        store._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "13"
    )
    assert store.list_underwriting("ADBE") == (old,)
    with pytest.raises(ValuationError, match="BEAR"):
        run_valuation(store, old)
    assert store.get_valuation(old.underwriting_id, MODEL_VERSION) is None


def test_outputs_do_not_read_new_evidence_or_recompute_on_show(
    store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = _persist(store, snapshot_input())
    output = run_valuation(store, record)
    monkeypatch.setattr(
        store,
        "get_underwriting_evidence",
        lambda *args, **kw: pytest.fail("No evidence read"),
    )
    from owner_lens import valuation

    monkeypatch.setattr(
        valuation, "value_underwriting", lambda *args: pytest.fail("No recomputation")
    )
    assert run_valuation(store, record) == output
    assert main(["valuation", "show", "ADBE", "--version", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(output)


def test_adbe_end_to_end_from_persisted_fmp_facts(
    store: SqliteStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from test_underwriting import _annual_history, _save_snapshot

    from owner_lens.persistence.records import FmpEodPriceRecord

    _annual_history(store)
    price_id = _save_snapshot(store, "eod_price", b'[{"price":100}]', period="eod")
    store.save_fmp_eod_price(
        FmpEodPriceRecord(price_id, 1, "2026-06-01", 100, "price", "USD")
    )
    sample = _SAMPLE.with_name("adbe_scenario_underwriting.sample.json")
    input_file = tmp_path / "ADBE-scenarios.json"
    input_file.write_bytes(sample.read_bytes())
    assert main(["underwriting", "create", "ADBE", "--file", str(input_file)]) == 0
    assert "v1" in capsys.readouterr().out
    record = store.list_underwriting("ADBE")[0]
    assert main(["valuation", "run", "ADBE", "--version", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["starting_revenue"] == 23769_000_000
    assert result["starting_diluted_shares"] == 427_000_000
    assert result["current_price"] == 100
    base = result["scenarios"][1]
    assert base["year5_revenue"] == pytest.approx(23769_000_000 * 1.05**5)
    assert base["year5_fcf"] == pytest.approx(base["year5_revenue"] * 0.35)
    assert base["year5_diluted_shares"] == pytest.approx(427_000_000 * 0.99**5)
    assert base["year5_value_per_share"] == pytest.approx(
        base["year5_fcf"] * 20 / base["year5_diluted_shares"]
    )
    assert record.snapshot_json == store.list_underwriting("ADBE")[0].snapshot_json


@pytest.mark.parametrize(
    "field,value",
    (
        ("market_date", "not a date"),
        ("market_date", "2026-06-03"),
        ("fetched_at", "2026-06-04T12:00:00+00:00"),
        ("snapshot_id", None),
        ("content_hash", ""),
        ("evidence_kind", "EXPECTATION"),
    ),
)
def test_price_provenance_and_cutoff_validation(field: str, value: Any) -> None:
    snapshot = snapshot_input()
    evidence = json.loads(snapshot.evidence_json)
    evidence["eod_price"]["value"][field] = value
    with pytest.raises(ValuationError):
        value_underwriting(
            record_from(replace(snapshot, evidence_json=json.dumps(evidence)))
        )


def test_saved_valuation_conflict_fails_without_replacing_result(
    store: SqliteStore,
) -> None:
    record = _persist(store, snapshot_input())
    output = run_valuation(store, record)
    from owner_lens.persistence import StorageWriteError

    with pytest.raises(StorageWriteError, match="differs"):
        store.save_valuation(record.underwriting_id, MODEL_VERSION, "{}")
    assert store.get_valuation(record.underwriting_id, MODEL_VERSION) == output

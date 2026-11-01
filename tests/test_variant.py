"""Fixture-only variant semantics, point-in-time isolation and sensitivity checks."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from test_underwriting import _save_snapshot
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import _persist, record_from, snapshot_input
from test_valuation import store as store  # noqa: PLC0414

from owner_lens.cli import main
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.records import FmpEstimateRecord
from owner_lens.underwriting import (
    BaseRate,
    DriverRationale,
    HistoricalObservation,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    create_underwriting,
    parse_manual_input,
)
from owner_lens.variant import VariantError, compare_variant, format_variant
from owner_lens.workbench.data import WorkbenchSource


def variant_snapshot(growth: float = 0.08) -> UnderwritingSnapshot:
    snapshot = snapshot_input()
    evidence = json.loads(snapshot.evidence_json)
    evidence["cutoff"] = "2026-06-02T12:00:00+00:00"
    evidence["canonical_history"] = {
        "facts": [
            {"metric": "revenue", "fiscal_year": 2025, "period_end": "2025-11-30"}
        ]
    }
    evidence["market_expectations"] = {
        "category": "EXPECTATION",
        "snapshots": [
            {
                "source": {
                    "dataset": "annual_analyst_estimates",
                    "period_type": "annual",
                    "snapshot_id": 8,
                    "fetched_at": "2026-06-01T12:00:00+00:00",
                    "content_hash": "fixture-estimates",
                    "evidence_kind": "EXPECTATION",
                },
                "rows": [
                    {
                        "snapshot_id": 8,
                        "target_date": "2028-11-30",
                        "revenue_average": 1000 * (1 + growth) ** 3,
                        "revenue_low": 1000 * (1 + growth - 0.01) ** 3,
                        "revenue_high": 1000 * (1 + growth + 0.01) ** 3,
                        "revenue_analyst_count": 10,
                        "eps_average": 3.0,
                        "evidence_kind": "EXPECTATION",
                    }
                ],
            }
        ],
    }
    rates = tuple(
        BaseRate(
            name,
            (HistoricalObservation(2024, low), HistoricalObservation(2025, high)),
            low,
            high,
            high,
            "Fixture observed ratio",
        )
        for name, low, high in (
            ("revenue_growth", 0.05, 0.07),
            ("fcf_margin", 0.15, 0.18),
            ("share_count_change", -0.03, -0.01),
        )
    )
    return replace(
        snapshot,
        evidence_json=json.dumps(evidence),
        historical_base_rates=rates,
        manual=replace(
            snapshot.manual,
            variant_rationales=(
                DriverRationale("revenue_cagr", "Fixture-only disagreement rationale"),
            ),
        ),
    )


def changed_evidence(
    snapshot: UnderwritingSnapshot, modify: Any
) -> UnderwritingSnapshot:
    evidence = json.loads(snapshot.evidence_json)
    modify(evidence)
    return replace(snapshot, evidence_json=json.dumps(evidence))


def test_semantics_ranges_delta_and_horizon() -> None:
    report = compare_variant(record_from(variant_snapshot()))
    revenue = report.drivers[0]
    assert (
        revenue.history is not None
        and revenue.history.category is SemanticType.CALCULATION
    )
    assert revenue.history.minimum == 0.05
    assert revenue.consensus.category is SemanticType.EXPECTATION
    assert revenue.consensus.basis_category is SemanticType.CALCULATION
    assert revenue.consensus.horizon_years == 3  # Not five-year consensus!
    assert revenue.consensus.value == pytest.approx(0.08)
    assert revenue.consensus.low == pytest.approx(0.07)
    assert revenue.consensus.high == pytest.approx(0.09)
    assert revenue.consensus.analyst_count == 10
    assert revenue.consensus.content_hash == "fixture-estimates"
    assert revenue.assumption_category is SemanticType.ASSUMPTION
    assert revenue.assumption == 0.1
    assert revenue.absolute_delta == pytest.approx(0.02)
    assert revenue.percentage_delta == pytest.approx(0.25)
    assert revenue.direction == "ABOVE" and revenue.material
    assert (
        revenue.rationale is not None
        and revenue.rationale.category is SemanticType.JUDGMENT
    )
    assert revenue.difference_category is SemanticType.CALCULATION
    assert report.conclusion == "IDENTIFIABLE_VARIANT_VIEW"


@pytest.mark.parametrize(
    "growth,direction,material,conclusion",
    [
        (0.1, "ALIGNED", False, "NO_IDENTIFIABLE_VARIANT_VIEW"),
        (0.105, "BELOW", False, "NO_IDENTIFIABLE_VARIANT_VIEW"),
        (0.11, "BELOW", True, "IDENTIFIABLE_VARIANT_VIEW"),
        (0.0, "ABOVE", True, "IDENTIFIABLE_VARIANT_VIEW"),
        (-0.1, "ABOVE", True, "IDENTIFIABLE_VARIANT_VIEW"),
    ],
)
def test_direction_materiality_and_zero_consensus(
    growth: float, direction: str, material: bool, conclusion: str
) -> None:
    report = compare_variant(record_from(variant_snapshot(growth)))
    driver = report.drivers[0]
    assert driver.direction == direction and driver.material == material
    assert report.conclusion == conclusion
    if growth == 0:
        assert driver.percentage_delta is None
    elif growth == -0.1:
        assert driver.percentage_delta == pytest.approx(2.0)


def test_no_rationale_is_invented_for_material_difference() -> None:
    snapshot = variant_snapshot()
    snapshot = replace(snapshot, manual=replace(snapshot.manual, variant_rationales=()))
    report = compare_variant(record_from(snapshot))
    assert report.drivers[0].material
    assert report.conclusion == "NO_IDENTIFIABLE_VARIANT_VIEW"
    assert "no explicit driver" in format_variant(report)


def test_no_consensus_is_invented_from_eps_history_price_or_assumptions() -> None:
    report = compare_variant(record_from(variant_snapshot()))
    for driver in report.drivers[1:]:
        assert driver.consensus.value is None
        assert driver.absolute_delta is None and driver.percentage_delta is None
        assert not driver.material and driver.direction == "UNAVAILABLE"
        assert driver.consensus.reason
    assert report.drivers[3].history is None
    empty = compare_variant(record_from(snapshot_input()))
    assert empty.conclusion == "NO_IDENTIFIABLE_VARIANT_VIEW"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda e: e["market_expectations"]["snapshots"][0].update(rows=[]), "aligned"),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                revenue_average=None
            ),
            "average",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                target_date="2028-12-31"
            ),
            "aligned",
        ),
        (lambda e: e.pop("canonical_history"), "fiscal period"),
    ],
)
def test_missing_or_incomparable_consensus_is_explicit(
    mutation: Any, reason: str
) -> None:
    report = compare_variant(
        record_from(changed_evidence(variant_snapshot(), mutation))
    )
    assert report.drivers[0].consensus.value is None
    assert reason in str(report.drivers[0].consensus.reason)
    assert report.conclusion == "NO_IDENTIFIABLE_VARIANT_VIEW"


def test_52_week_fiscal_date_drift_is_supported_without_calendar_substitution() -> None:
    snapshot = changed_evidence(
        variant_snapshot(),
        lambda e: e["canonical_history"]["facts"][0].update(period_end="2025-11-28"),
    )
    assert (
        compare_variant(record_from(snapshot)).drivers[0].consensus.horizon_years == 3
    )


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda e: e["market_expectations"].update(category="FACT"), "EXPECTATION"),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["source"].update(
                fetched_at="2026-06-03T00:00:00+00:00"
            ),
            "cutoff",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["source"].update(
                period_type="quarterly"
            ),
            "annual",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["source"].update(
                evidence_kind="FACT"
            ),
            "EXPECTATION",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                evidence_kind="FACT"
            ),
            "category",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                snapshot_id=99
            ),
            "snapshot",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                revenue_average=-1
            ),
            "positive",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                revenue_average=float("inf")
            ),
            "range|finite",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                revenue_low=999999
            ),
            "range",
        ),
        (
            lambda e: e["market_expectations"]["snapshots"][0]["rows"][0].update(
                revenue_analyst_count=-1
            ),
            "count",
        ),
    ],
)
def test_invalid_consensus_fails_explicitly(mutation: Any, match: str) -> None:
    snapshot = changed_evidence(variant_snapshot(), mutation)
    # JSON encoding rejects infinity before the domain call, so keep the source JSON in the record.
    if "Infinity" in snapshot.evidence_json:
        from owner_lens.persistence import UnderwritingRecord, compute_content_hash

        payload = json.loads(record_from(variant_snapshot()).snapshot_json)
        payload["evidence"] = json.loads(snapshot.evidence_json)
        raw = json.dumps(payload)
        record = UnderwritingRecord(
            "invalid",
            1,
            "ADBE",
            1,
            "2026-06-02T12:00:00+00:00",
            "2026-06-02",
            raw,
            compute_content_hash(raw.encode()),
        )
    else:
        record = record_from(snapshot)
    with pytest.raises(VariantError, match=match):
        compare_variant(record)


def test_latest_snapshot_selected_even_when_empty_and_no_duplicate_targets() -> None:
    snapshot = variant_snapshot()
    evidence = json.loads(snapshot.evidence_json)
    latest = json.loads(json.dumps(evidence["market_expectations"]["snapshots"][0]))
    latest["source"].update(snapshot_id=9, fetched_at="2026-06-02T11:00:00+00:00")
    latest["rows"] = []
    evidence["market_expectations"]["snapshots"].append(latest)
    report = compare_variant(
        record_from(replace(snapshot, evidence_json=json.dumps(evidence)))
    )
    assert report.drivers[0].consensus.snapshot_id == 9
    assert report.drivers[0].consensus.value is None
    evidence["market_expectations"]["snapshots"] = [
        evidence["market_expectations"]["snapshots"][0]
    ]
    rows = evidence["market_expectations"]["snapshots"][0]["rows"]
    rows.append(rows[0].copy())
    with pytest.raises(VariantError, match="Duplicate"):
        compare_variant(
            record_from(replace(snapshot, evidence_json=json.dumps(evidence)))
        )


def test_sensitivity_uses_exact_8c_math_and_never_changes_beliefs() -> None:
    record = record_from(variant_snapshot())
    original = record.snapshot_json
    report = compare_variant(record)
    assert compare_variant(record).to_json() == report.to_json()
    assert record.snapshot_json == original
    base_value = 1000 * 1.1**5 * 0.2 * 20 / (100 * 0.98**5)
    expected_factors = [(1.11 / 1.1) ** 5, 0.21 / 0.2, (0.98 / 0.99) ** 5, 21 / 20]
    for driver, factor in zip(report.drivers, expected_factors, strict=True):
        sensitivity = driver.sensitivity
        assert sensitivity.category is SemanticType.CALCULATION
        assert sensitivity.base_value_per_share == pytest.approx(base_value)
        assert sensitivity.perturbed_value_per_share == pytest.approx(
            base_value * factor
        )
        assert sensitivity.value_percentage_delta == pytest.approx(factor - 1)
        assert sensitivity.cagr_delta == pytest.approx(
            (base_value * factor / 20) ** 0.2 - (base_value / 20) ** 0.2
        )
    assert [item.sensitivity.band for item in report.drivers] == [
        "MEDIUM",
        "MEDIUM",
        "MEDIUM",
        "MEDIUM",
    ]
    assert report.drivers[2].sensitivity.cagr_delta < 0


@pytest.mark.parametrize("margin", [0.0, 0.995, 1.0])
def test_margin_boundary_perturbation_and_zero_base(margin: float) -> None:
    snapshot = variant_snapshot()
    scenarios = tuple(
        replace(item, fcf_margin_year5=margin) if item.name.value == "BASE" else item
        for item in snapshot.manual.scenarios
    )
    snapshot = replace(snapshot, manual=replace(snapshot.manual, scenarios=scenarios))
    result = compare_variant(record_from(snapshot)).drivers[1].sensitivity
    assert result.perturbation == (-0.01 if margin > 0.99 else 0.01)
    if margin == 0:
        assert result.base_implied_cagr == -1
        assert result.value_percentage_delta is None
        assert result.band == "HIGH"
    else:
        assert result.band == "LOW"


@pytest.mark.parametrize(
    "field,value",
    [("category", "ASSUMPTION"), ("driver", "eps"), ("text", ""), ("extra", "bad")],
)
def test_strict_manual_rationale_contract(field: str, value: Any) -> None:
    data = json.loads(variant_snapshot().to_json())["manual"]
    data["variant_rationales"][0][field] = value
    with pytest.raises(UnderwritingError):
        parse_manual_input(data)


def test_rationale_references_round_trip_and_duplicates() -> None:
    data = json.loads(variant_snapshot().to_json())["manual"]
    data["variant_rationales"][0]["references"] = [
        {"title": "My research", "uri": "https://example.com/research"}
    ]
    parsed = parse_manual_input(data)
    assert parsed.variant_rationales[0].references[0].title == "My research"
    snapshot = replace(variant_snapshot(), manual=parsed)
    assert (
        UnderwritingSnapshot.from_json(snapshot.to_json()).to_json()
        == snapshot.to_json()
    )
    data["variant_rationales"].append(data["variant_rationales"][0])
    with pytest.raises(UnderwritingError, match="Duplicate"):
        parse_manual_input(data)


def test_cli_offline_and_persisted_v1_v2_isolation(
    store: SqliteStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _persist(store, variant_snapshot())
    before = compare_variant(first).to_json()
    revised = variant_snapshot(0.12)
    scenarios = tuple(
        replace(item, revenue_cagr=0.15) if item.name.value == "BASE" else item
        for item in revised.manual.scenarios
    )
    second = _persist(
        store, replace(revised, manual=replace(revised.manual, scenarios=scenarios))
    )
    monkeypatch.setattr(
        SqliteStore,
        "get_underwriting_evidence",
        lambda *a, **kw: pytest.fail("No current evidence read"),
    )
    assert main(["variant", "show", "ADBE", "--version", "1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(before)
    assert main(["variant", "show", "ADBE", "--version", "2"]) == 0
    assert "underwriting v2" in capsys.readouterr().out
    assert compare_variant(second).to_json() != before
    assert store.list_underwriting("ADBE")[0].snapshot_json == first.snapshot_json
    assert main(["variant", "show", "ADBE", "--version", "99"]) == 1
    assert "not found" in capsys.readouterr().err


def test_real_capture_selects_asof_estimates_and_new_data_never_changes_old_report(
    source: WorkbenchSource,
) -> None:
    assert isinstance(source.store, SqliteStore)
    manual = variant_snapshot().manual
    first = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    old_report = compare_variant(first).to_json()
    snapshot_id = _save_snapshot(
        source.store,
        "annual_analyst_estimates",
        b'[{"new":true}]',
        observed="2026-06-03T12:00:00+00:00",
        period="annual",
    )
    source.store.save_fmp_estimates(
        (
            FmpEstimateRecord(
                snapshot_id, "2028-11-30", 27000e6, 30000e6, 33000e6, 12, 10, 12, 14, 12
            ),
        )
    )
    backdated = create_underwriting(
        source,
        "ADBE",
        replace(manual, as_of_date="2026-06-02"),
        now=datetime(2026, 6, 4, 12, tzinfo=UTC),
    )
    assert compare_variant(backdated).drivers[0].consensus.snapshot_id != snapshot_id
    second = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 4, 12, tzinfo=UTC)
    )
    assert compare_variant(second).drivers[0].consensus.snapshot_id == snapshot_id
    reloaded = source.store.list_underwriting("ADBE")[0]
    assert compare_variant(reloaded).to_json() == old_report
    assert compare_variant(second).drivers[0].consensus.value == pytest.approx(
        (30000 / 23769) ** (1 / 3) - 1
    )

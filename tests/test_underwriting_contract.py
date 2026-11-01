"""Consolidated authoring, legacy reproducibility and offline domain projection."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_underwriting import source as source  # noqa: PLC0414
from test_valuation import _persist, record_from
from test_valuation import store as store  # noqa: PLC0414
from test_variant import variant_snapshot

from owner_lens.challenger import run_challenger
from owner_lens.persistence import SqliteStore
from owner_lens.underwriting import (
    Reference,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    create_underwriting,
    parse_manual_input,
)
from owner_lens.underwriting_contract import project_underwriting, validate_belief_links
from owner_lens.valuation import run_valuation, value_underwriting
from owner_lens.workbench.data import WorkbenchSource


def authoring() -> dict[str, Any]:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "docs"
            / "examples"
            / "adbe_consolidated_underwriting.sample.json"
        ).read_text()
    )


def test_reduced_authoring_auto_facts_expectations_and_semantics(
    source: WorkbenchSource,
) -> None:
    data = authoring()
    assert (
        not {
            "facts",
            "expectations",
            "calculations",
            "forward_assumptions",
            "as_of_date",
        }
        & data.keys()
    )
    manual = parse_manual_input(data)
    record = create_underwriting(
        source, "ADBE", manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
    assert snapshot.schema_version == snapshot.manual.contract_version == 2
    assert snapshot.to_json() == record.snapshot_json
    assert snapshot.starting_financial_state[0].category is SemanticType.FACT
    assert (
        json.loads(snapshot.evidence_json)["market_expectations"]["category"]
        == "EXPECTATION"
    )
    assert json.loads(snapshot.evidence_json)["market_expectations"]["snapshots"]
    assert snapshot.manual.scenarios[0].category is SemanticType.ASSUMPTION
    assert snapshot.manual.probability_distribution.category is SemanticType.JUDGMENT
    assert snapshot.manual.thesis.monitoring_breakers[0].observable
    assert snapshot.manual.thesis.monitoring_breakers[0].monitoring_cadence
    assert (
        snapshot.manual.thesis.breakers[0]
        == snapshot.manual.thesis.monitoring_breakers[0].statement
    )
    assert value_underwriting(record).category is SemanticType.CALCULATION


@pytest.mark.parametrize(
    "key,value",
    [
        ("facts", {}),
        ("expectations", {}),
        ("calculations", {}),
        ("as_of_date", "2026-06-01"),
        ("authoring_version", True),
        ("authoring_version", 3),
    ],
)
def test_automatic_or_calculated_fields_cannot_be_authored(
    key: str, value: Any
) -> None:
    data = authoring()
    data[key] = value
    with pytest.raises(UnderwritingError):
        parse_manual_input(data)


def test_v2_requires_complete_probabilities_and_rationale_and_strict_conditions() -> (
    None
):
    for mutation in [
        lambda d: d["judgments"]["probability_distribution"].update(rationale=None),
        lambda d: d["judgments"].update(investor_policy=None),
        lambda d: d["judgments"]["thesis"]["breakers"][0].update(category="FACT"),
        lambda d: d["judgments"]["thesis"]["breakers"][0].update(
            monitoring_date="not-date"
        ),
        lambda d: d["judgments"]["thesis"]["breakers"].append(
            d["judgments"]["thesis"]["breakers"][0]
        ),
        lambda d: d["assumptions"]["scenarios"][0].update(year5_value_per_share=100),
    ]:
        data = authoring()
        mutation(data)
        with pytest.raises(UnderwritingError):
            parse_manual_input(data)


def test_evidence_links_dates_provenance_and_revision(source: WorkbenchSource) -> None:
    data = authoring()
    data["judgments"]["supporting_evidence"] = [
        {
            "category": "JUDGMENT",
            "text": "Illustrative interpretation, not verified fact.",
            "evidence_id": "retention-note",
            "evidence_date": "2026-06-01",
            "references": [
                {
                    "title": "Research note",
                    "uri": "https://example.com",
                    "observed_at": "2026-06-01",
                }
            ],
            "belief_references": [
                "/manual/business_drivers/0",
                "/manual/scenarios/1/revenue_cagr",
                "/manual/thesis/monitoring_dependencies/0",
                "/manual/thesis/monitoring_breakers/0",
            ],
        }
    ]
    first = create_underwriting(
        source,
        "ADBE",
        parse_manual_input(data),
        now=datetime(2026, 6, 2, 12, tzinfo=UTC),
    )
    snap = UnderwritingSnapshot.from_json(first.snapshot_json)
    assert snap.manual.supporting_evidence[0].evidence_id == "retention-note"
    assert snap.manual.supporting_evidence[0].references[0].observed_at == "2026-06-01"
    data["judgments"]["supporting_evidence"][0]["text"] = "Revised interpretation"
    second = create_underwriting(
        source,
        "ADBE",
        parse_manual_input(data),
        now=datetime(2026, 6, 2, 13, tzinfo=UTC),
    )
    assert second.version == first.version + 1
    assert (
        source.store.list_underwriting("ADBE")[0].snapshot_json == first.snapshot_json
    )
    for pointer in (
        "/manual/scenarios/99",
        "/calculation/expected_cagr",
        "/manual/scenarios/1/key_dependency/99",
    ):
        broken = replace(
            snap,
            manual=replace(
                snap.manual,
                supporting_evidence=(
                    replace(
                        snap.manual.supporting_evidence[0], belief_references=(pointer,)
                    ),
                ),
            ),
        )
        with pytest.raises(UnderwritingError):
            validate_belief_links(broken, "2026-06-02")
    future = replace(
        snap,
        manual=replace(
            snap.manual,
            supporting_evidence=(
                replace(snap.manual.supporting_evidence[0], evidence_date="2026-06-03"),
            ),
        ),
    )
    with pytest.raises(UnderwritingError, match="as-of"):
        validate_belief_links(future, "2026-06-02")
    future_reference = replace(
        snap,
        manual=replace(
            snap.manual,
            supporting_evidence=(
                replace(
                    snap.manual.supporting_evidence[0],
                    references=(
                        Reference(
                            "Future note", observed_at="2026-06-03T00:00:00+00:00"
                        ),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(UnderwritingError, match="cutoff"):
        validate_belief_links(future_reference, "2026-06-02")


def test_legacy_schema1_exact_round_trip_and_valuation_unchanged() -> None:
    snap = variant_snapshot()
    record = record_from(snap)
    payload = record.snapshot_json
    assert "contract_version" not in payload and "monitoring_breakers" not in payload
    assert "belief_references" not in payload
    assert UnderwritingSnapshot.from_json(payload).to_json() == payload
    assert (
        value_underwriting(record).to_json()
        == value_underwriting(
            record_from(UnderwritingSnapshot.from_json(payload))
        ).to_json()
    )


def test_v2_compatibility_mirrors_cannot_diverge() -> None:
    snapshot = replace(
        variant_snapshot(), manual=parse_manual_input(authoring()), schema_version=2
    )
    payload = json.loads(snapshot.to_json())
    payload["manual"]["thesis"]["breakers"][0] = "Contradictory text"
    with pytest.raises(UnderwritingError, match="match structured"):
        UnderwritingSnapshot.from_json(json.dumps(payload))
    payload = json.loads(snapshot.to_json())
    payload["schema_version"] = 1
    with pytest.raises(UnderwritingError, match="versions"):
        UnderwritingSnapshot.from_json(json.dumps(payload))


def test_offline_projection_status_versions_summary_and_challenger(
    store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert project_underwriting(store, "ADBE").status == "NOT_CREATED"
    manual = parse_manual_input(authoring())
    snapshot = replace(variant_snapshot(), manual=manual, schema_version=2)
    first = _persist(store, snapshot)
    assert project_underwriting(store, "ADBE").status == "CAPTURED"
    assert (
        store.get_valuation(first.underwriting_id, "equity-fcf-multiple-5y-v1") is None
    )
    valuation = run_valuation(store, first)
    advisory = run_challenger(store, first)
    monkeypatch.setattr(
        SqliteStore,
        "get_underwriting_evidence",
        lambda *a, **kw: pytest.fail("No evidence read"),
    )
    projection = project_underwriting(store, "ADBE", version=1)
    assert projection.status == "SUMMARY_READY"
    assert projection.valuation_json == valuation
    assert projection.summary.expected_5y_cagr
    assert projection.variant.drivers
    assert projection.snapshot.manual.thesis.monitoring_breakers
    assert projection.challenger_runs == (advisory,)
    assert projection.missing_evidence
    assert projection.snapshot.manual.business_drivers
    old = _persist(store, variant_snapshot())
    assert project_underwriting(store, "ADBE").record.version == old.version
    assert project_underwriting(store, "ADBE", version=1) == projection
    assert store.list_underwriting("ADBE")[0] == first
    with pytest.raises(UnderwritingError, match="not found"):
        project_underwriting(store, "ADBE", version=99)


def test_projection_partial_legacy_remains_visible(store: SqliteStore) -> None:
    first = _persist(store, variant_snapshot())
    run_valuation(store, first)
    projection = project_underwriting(store, "ADBE", version=first.version)
    assert projection.status == "VALUED"
    assert projection.summary is None and projection.variant is not None
    missing = {item.section for item in projection.missing_evidence}
    assert {
        "probability_distribution",
        "investor_policy",
        "dependencies",
        "breakers",
        "supporting_evidence",
        "disconfirming_evidence",
        "challenger",
    } <= missing
    assert projection.snapshot.schema_version == 1
    assert project_underwriting(store, "ADBE", version=first.version) == projection

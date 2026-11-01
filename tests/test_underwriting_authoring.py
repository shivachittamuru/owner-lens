"""Fixture-only human drafts, immutable save and live Streamlit authoring feedback."""

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from test_underwriting import source as source  # noqa: PLC0414
from test_underwriting_contract import authoring

from owner_lens.config import OwnerLensSettings
from owner_lens.persistence.errors import StorageWriteError
from owner_lens.underwriting import (
    UnderwritingError,
    UnderwritingSnapshot,
    capture_underwriting_inputs,
    create_underwriting,
    parse_manual_input,
    save_underwriting_inputs,
)
from owner_lens.underwriting_authoring import (
    authoring_context,
    authoring_from_manual,
    draft_hints,
    empty_authoring,
    probability_feedback,
    review_authoring,
)
from owner_lens.workbench.data import WorkbenchSource

NOW = datetime(2026, 6, 2, 12, tzinfo=UTC)


def test_blank_draft_has_no_belief_policy_or_probability_defaults() -> None:
    blank = empty_authoring()
    assert [item["name"] for item in blank["assumptions"]["scenarios"]] == ["BEAR", "BASE", "BULL"]
    assert all(item["revenue_cagr"] is None and item["terminal_fcf_multiple"] is None
               and item["narrative"] == "" for item in blank["assumptions"]["scenarios"])
    assert blank["judgments"]["investor_policy"]["required_return"] is None
    assert probability_feedback(blank)[0] is None
    with pytest.raises(UnderwritingError):
        parse_manual_input(blank)


def test_context_capture_review_and_cli_share_exact_snapshot(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    data = authoring()
    original = copy.deepcopy(data)
    contexts = authoring_context(inputs)
    reviewed = review_authoring(data, inputs)
    assert data == original
    assert source.store.list_underwriting("ADBE") == ()
    assert all(item.category == "FACT" for item in inputs.starting_financial_state)
    assert json.loads(inputs.evidence_json)["market_expectations"]["category"] == "EXPECTATION"
    assert contexts[-1].presets() == {}
    assert contexts[1].presets()["Historical latest"] == next(
        item.value for item in inputs.starting_financial_state if item.name == "fcf_margin")
    first = save_underwriting_inputs(source, inputs, reviewed.manual, expected_latest_version=0, now=NOW)
    second = create_underwriting(source, "ADBE", parse_manual_input(data), now=NOW)
    assert first.snapshot_json == second.snapshot_json
    assert first.version == 1 and second.version == 2


@pytest.mark.parametrize("mutation", [
    lambda d: d["assumptions"]["scenarios"].pop(),
    lambda d: d["assumptions"]["scenarios"].append(d["assumptions"]["scenarios"][0]),
    lambda d: d["assumptions"]["scenarios"][0].update(revenue_cagr=None),
    lambda d: d["assumptions"]["scenarios"][0].update(key_dependency=None),
    lambda d: d["judgments"]["probability_distribution"]["scenarios"][0].update(probability=0.1),
    lambda d: d["judgments"]["probability_distribution"]["scenarios"][0].update(probability=None),
    lambda d: d["judgments"]["investor_policy"].update(required_return=None),
    lambda d: d["judgments"]["thesis"]["breakers"][0].update(statement=""),
])
def test_invalid_draft_review_never_persists(source: WorkbenchSource, mutation: Any) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    data = authoring()
    mutation(data)
    with pytest.raises(UnderwritingError):
        review_authoring(data, inputs)
    assert source.store.list_underwriting("ADBE") == ()


def test_v7_clone_draft_v8_and_stale_review_guard(source: WorkbenchSource) -> None:
    for _ in range(7):
        seventh = create_underwriting(source, "ADBE", parse_manual_input(authoring()), now=NOW)
    snapshot = UnderwritingSnapshot.from_json(seventh.snapshot_json)
    draft = authoring_from_manual(snapshot.manual)
    assert parse_manual_input(draft) == snapshot.manual
    draft["assumptions"]["scenarios"][1]["revenue_cagr"] = 0.08
    assert UnderwritingSnapshot.from_json(seventh.snapshot_json).manual.scenarios[1].revenue_cagr != 0.08
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    review = review_authoring(draft, inputs)
    eighth = save_underwriting_inputs(source, inputs, review.manual, expected_latest_version=7, now=NOW)
    assert eighth.version == 8
    assert source.store.list_underwriting("ADBE")[6] == seventh
    with pytest.raises(StorageWriteError, match="changed since review"):
        save_underwriting_inputs(source, inputs, review.manual, expected_latest_version=7, now=NOW)
    assert len(source.store.list_underwriting("ADBE")) == 8
    assert not source.store._conn.in_transaction


def test_structured_evidence_conditions_and_no_lookahead_roundtrip(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    data = authoring()
    data["judgments"]["supporting_evidence"] = [{
        "category": "JUDGMENT", "text": "Dated interpretation, not automatically verified fact.",
        "evidence_id": "support-1", "evidence_date": "2026-06-01",
        "references": [{"title": "Filed report", "uri": "fixture://report", "observed_at": "2026-06-01"}],
        "belief_references": ["/manual/scenarios/1/revenue_cagr", "/manual/business_drivers/0"],
    }]
    data["judgments"]["thesis"]["dependencies"][0].update(
        observable="Retention", threshold="At least 90%", monitoring_cadence="Quarterly",
        monitoring_date="2026-09-01", sources=[{"title": "Future quarterly disclosures"}])
    reviewed = review_authoring(data, inputs)
    record = save_underwriting_inputs(source, inputs, reviewed.manual, now=NOW)
    result = UnderwritingSnapshot.from_json(record.snapshot_json)
    assert authoring_from_manual(result.manual) == authoring_from_manual(reviewed.manual)
    assert result.manual.supporting_evidence[0].belief_references[0] == "/manual/scenarios/1/revenue_cagr"
    data["judgments"]["supporting_evidence"][0]["evidence_date"] = "2026-06-03"
    with pytest.raises(UnderwritingError, match="as-of"):
        review_authoring(data, inputs)
    assert len(source.store.list_underwriting("ADBE")) == 1


def test_presets_hints_and_exact_probabilities(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    contexts = authoring_context(inputs)
    data = authoring()
    value = contexts[1].presets()["Historical latest"]
    data["assumptions"]["scenarios"][1]["fcf_margin_year5"] = value
    reviewed = review_authoring(data, inputs)
    assert reviewed.manual.scenarios[1].fcf_margin_year5 == value
    assert reviewed.manual.scenarios[1].category == "ASSUMPTION"
    total, message = probability_feedback(data)
    assert total == 1 and message is None
    hints = draft_hints(data, contexts)
    assert any("No disconfirming" in hint for hint in hints)
    data["assumptions"]["scenarios"][1]["fcf_margin_year5"] = 0.99
    assert any("outside the observed" in hint for hint in draft_hints(data, contexts))
    probabilities = data["judgments"]["probability_distribution"]["scenarios"]
    probabilities[0]["probability"] = 0.15
    assert "90.0%" in probability_feedback(data)[1]
    assert probabilities[0]["probability"] == 0.15


def _app(source: WorkbenchSource) -> AppTest:
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from owner_lens.workbench.data import open_source,company_detail,load_persisted_companies\n"
        "from owner_lens.underwriting_contract import project_underwriting\n"
        "from owner_lens.workbench.views.company import render\n"
        "def source_factory():\n"
        " return open_source(st.session_state['settings'])\n"
        "with source_factory() as source:\n"
        " detail=company_detail(source,load_persisted_companies(source,'fmp')[0])\n"
        " projection=project_underwriting(source.store,'ADBE')\n"
        "render(detail,projection,authoring_source=source_factory)\n",
        default_timeout=45,
    )
    app.session_state["settings"] = OwnerLensSettings(None, source.db_path, source.raw_data_path)
    app.run()
    assert not app.exception
    return app


def _button(app: AppTest, label: str) -> Any:
    return next(item for item in app.button if item.label == label)


def _seed_draft(app: AppTest, data: dict[str, Any]) -> None:
    draft = app.session_state["authoring.ADBE"]
    draft["seed"] = copy.deepcopy(data)
    draft["id"] += 1
    draft.pop("review", None)
    app.run()
    assert not app.exception, [item.value for item in app.exception]


def test_company_form_blank_errors_live_probabilities_and_explicit_preset(source: WorkbenchSource) -> None:
    app = _app(source)
    _button(app, "Create New Underwriting").click().run()
    assert not app.exception
    assert all(item.value is None for item in app.number_input)
    assert not any(item.label == "Create Immutable Underwriting Version" for item in app.button)
    assert any("v1" in item.value and "not be changed" in item.value for item in app.warning)
    _button(app, "Review Draft").click().run()
    assert not app.exception
    assert app.error
    assert source.store.list_underwriting("ADBE") == ()
    _seed_draft(app, authoring())
    probability = next(item for item in app.number_input if item.label == "BEAR probability (%)")
    probability.set_value(15.0).run()
    assert any("90.0%" in item.value for item in app.warning)
    preset = next(item for item in app.selectbox if ".scenario.BASE.fcf_margin_year5.preset" in item.key)
    preset.select("Historical latest").run()
    _button_base = next(item for item in app.button if item.key.endswith(".scenario.BASE.fcf_margin_year5.apply"))
    _button_base.click().run()
    assert not app.exception
    inputs = app.session_state["authoring.ADBE"]["inputs"]
    latest = authoring_context(inputs)[1].latest
    margin = next(item for item in app.number_input if item.key.endswith(".scenario.BASE.fcf_margin_year5"))
    assert margin.value == latest * 100
    assert source.store.list_underwriting("ADBE") == ()


def test_company_form_review_save_no_automatic_artifacts_and_clone(source: WorkbenchSource, monkeypatch: pytest.MonkeyPatch) -> None:
    from owner_lens import challenger, valuation

    monkeypatch.setattr(valuation, "run_valuation", lambda *a, **kw: pytest.fail("No automatic valuation"))
    monkeypatch.setattr(challenger, "run_challenger", lambda *a, **kw: pytest.fail("No automatic challenger"))
    original = create_underwriting(source, "ADBE", parse_manual_input(authoring()), now=NOW)
    app = _app(source)
    _button(app, "Create New Underwriting").click().run()
    _button(app, "Start from latest underwriting").click().run()
    assert source.store.list_underwriting("ADBE") == (original,)
    assert not app.exception
    _button(app, "Review Draft").click().run()
    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    assert any("Review new underwriting v2" in item.value for item in app.subheader)
    assert source.store.list_underwriting("ADBE") == (original,)
    _button(app, "Create Immutable Underwriting Version").click().run()
    assert not app.exception
    assert any("v2" in item.value and "CAPTURED" in item.value for item in app.success)
    records = source.store.list_underwriting("ADBE")
    assert len(records) == 2 and records[0] == original
    assert source.store.get_valuation(records[-1].underwriting_id, valuation.MODEL_VERSION) is None
    assert source.store.list_challenger_runs(records[-1].underwriting_id) == ()
    assert UnderwritingSnapshot.from_json(records[-1].snapshot_json).manual == UnderwritingSnapshot.from_json(original.snapshot_json).manual


def test_context_presets_absence_readonly_and_ui_has_no_financial_math(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    evidence = json.loads(inputs.evidence_json)
    evidence["market_expectations"]["snapshots"] = []
    contexts = authoring_context(replace(inputs, evidence_json=json.dumps(evidence)))
    assert "Consensus" not in contexts[0].presets()
    assert "Conservative" not in contexts[0].presets()
    for filename in ("company.py", "underwriting_authoring.py"):
        text = (Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "views" / filename).read_text()
        assert "** (1 /" not in text and "value_underwriting(" not in text
        assert "run_challenger(" not in text and "run_valuation(" not in text


def test_historical_3_5y_and_consensus_presets_reuse_domain_math(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    evidence = json.loads(inputs.evidence_json)
    evidence["canonical_history"]["facts"] = [
        {**item, "value": 100 * 1.1 ** (item["fiscal_year"] - 2021)}
        if item["metric"] == "revenue" else item
        for item in evidence["canonical_history"]["facts"]
    ]
    revenue = next(item for item in evidence["canonical_history"]["facts"] if item["metric"] == "revenue")
    evidence["canonical_history"]["facts"].extend(
        {**revenue, "fiscal_year": year, "value": 100 * 1.1 ** (year - 2021), "period_end": f"{year}-11-30"}
        for year in (2021, 2022)
    )
    contexts = authoring_context(replace(inputs, evidence_json=json.dumps(evidence)))
    revenue_context = contexts[0]
    assert revenue_context.historical_cagr == pytest.approx(0.1)
    assert revenue_context.presets()["Historical 3-5Y"] == pytest.approx(0.1)
    assert revenue_context.consensus.horizon_years == 2
    assert "Consensus" in revenue_context.presets()
    assert revenue_context.consensus.fetched_at == "2026-06-01T12:00:00+00:00"


def test_review_freezes_inputs_even_when_new_evidence_arrives(source: WorkbenchSource) -> None:
    from test_underwriting import _annual_history

    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    snapshot = review_authoring(authoring(), inputs)
    _annual_history(source.store, observed="2026-06-03T12:00:00+00:00", revenue_delta=100)
    record = save_underwriting_inputs(source, inputs, snapshot.manual,
                                     now=datetime(2026, 6, 4, 12, tzinfo=UTC))
    assert record.snapshot_json == snapshot.to_json()
    assert record.created_at == "2026-06-04T12:00:00+00:00"
    assert json.loads(record.snapshot_json)["evidence"]["cutoff"] == NOW.isoformat()


def test_future_condition_source_is_evidence_not_monitoring_intention(source: WorkbenchSource) -> None:
    inputs = capture_underwriting_inputs(source, "ADBE", now=NOW)
    data = authoring()
    data["judgments"]["thesis"]["dependencies"][0].update(
        monitoring_date="2026-09-01",
        sources=[{"title": "Premature reference", "observed_at": "2026-06-03"}])
    with pytest.raises(UnderwritingError, match="cutoff"):
        review_authoring(data, inputs)
    assert source.store.list_underwriting("ADBE") == ()


def test_repeatable_evidence_thesis_widgets_roundtrip_and_invalidate_review(source: WorkbenchSource) -> None:
    from datetime import date

    app = _app(source)
    _button(app, "Create New Underwriting").click().run()
    _seed_draft(app, authoring())
    prefix = f"authoring.ADBE.draft.{app.session_state['authoring.ADBE']['id']}"
    next(item for item in app.button if item.key == prefix + ".supporting_evidence.count.add").click().run()
    next(item for item in app.text_area if item.key == prefix + ".supporting_evidence.0.text").set_value("Retention observation supports the demand belief.")
    next(item for item in app.selectbox if item.key == prefix + ".supporting_evidence.0.category").select("JUDGMENT")
    next(item for item in app.date_input if item.key == prefix + ".supporting_evidence.0.date").set_value(date(2026, 6, 1))
    next(item for item in app.multiselect if item.key == prefix + ".supporting_evidence.0.links").select("/manual/business_drivers/0")
    next(item for item in app.button if item.key == prefix + ".supporting_evidence.0.refs.count.add").click().run()
    next(item for item in app.text_input if item.key == prefix + ".supporting_evidence.0.refs.0.title").set_value("Dated research note")
    next(item for item in app.text_input if item.key == prefix + ".dependencies.0.observable").set_value("Retention")
    next(item for item in app.text_input if item.key == prefix + ".dependencies.0.threshold").set_value("At least 90%")
    _button(app, "Review Draft").click().run()
    assert not app.exception and not app.error
    next(item for item in app.number_input if item.key == prefix + ".scenario.BASE.revenue_cagr").set_value(8.0).run()
    assert not any(item.label == "Create Immutable Underwriting Version" for item in app.button)
    assert any("Review again" in item.value for item in app.info)
    assert source.store.list_underwriting("ADBE") == ()
    _button(app, "Review Draft").click().run()
    _button(app, "Create Immutable Underwriting Version").click().run()
    assert not app.exception
    snapshot = UnderwritingSnapshot.from_json(source.store.list_underwriting("ADBE")[0].snapshot_json)
    item = snapshot.manual.supporting_evidence[0]
    assert item.text == "Retention observation supports the demand belief."
    assert item.category == "JUDGMENT"
    assert item.references[0].title == "Dated research note"
    assert item.evidence_date == "2026-06-01"
    assert item.belief_references == ("/manual/business_drivers/0",)
    assert snapshot.manual.thesis.monitoring_dependencies[0].observable == "Retention"
    assert snapshot.manual.thesis.monitoring_dependencies[0].threshold == "At least 90%"

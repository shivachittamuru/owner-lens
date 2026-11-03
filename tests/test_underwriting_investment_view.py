"""Compact underwriting read-model and completed-version selection."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_underwriting import source as source  # noqa: PLC0414
from test_underwriting_contract import authoring

pytest.importorskip("streamlit", reason="the workbench needs the streamlit group")

from streamlit.testing.v1 import AppTest

from owner_lens import underwriting_completion as completion
from owner_lens.underwriting_completion import complete_underwriting
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.underwriting_investment_view import (
    build_investment_view,
    select_investment_projection,
)
from owner_lens.valuation import ValuationError
from owner_lens.workbench.data import WorkbenchSource

NOW = datetime(2026, 6, 2, 12, tzinfo=UTC)


def _raw() -> str:
    return json.dumps(authoring())


def test_investment_view_projects_saved_inputs_and_outputs_without_writes(
    source: WorkbenchSource,
) -> None:
    completed = complete_underwriting(source, "ADBE", _raw(), now=NOW)
    before_records = source.store.list_underwriting("ADBE")
    before_runs = source.store.list_challenger_runs(completed.record.underwriting_id)

    projection = project_underwriting(source.store, "ADBE")
    view = build_investment_view(projection)

    assert view.version == completed.record.version
    assert view.frozen_priority is not None
    assert view.frozen_setup is not None
    assert completed.summary is not None
    assert view.expected_cagr == pytest.approx(completed.summary.expected_5y_cagr)
    assert [scenario.name for scenario in view.scenarios] == ["BEAR", "BASE", "BULL"]
    assert all(scenario.value_per_share is not None for scenario in view.scenarios)
    assert view.dependencies
    assert view.breakers
    assert view.most_sensitive_driver is not None
    assert view.challenger is not None
    assert view.challenger.unresolved_questions
    assert source.store.list_underwriting("ADBE") == before_records
    assert source.store.list_challenger_runs(completed.record.underwriting_id) == before_runs


def test_completed_version_remains_visible_while_newer_version_is_retryable(
    source: WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = complete_underwriting(source, "ADBE", _raw(), now=NOW)
    original_run_valuation = completion.run_valuation
    monkeypatch.setattr(
        completion,
        "run_valuation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValuationError("fixture valuation failure")
        ),
    )
    second = complete_underwriting(source, "ADBE", _raw(), now=NOW)
    assert second.record.version == first.record.version + 1
    assert not second.complete

    displayed, retry = select_investment_projection(source.store, "ADBE")

    assert displayed.record == first.record
    assert retry is not None and retry.record == second.record
    assert [record.version for record in source.store.list_underwriting("ADBE")] == [1, 2]

    monkeypatch.setattr(completion, "run_valuation", original_run_valuation)


def test_missing_frozen_screening_context_stays_explicitly_unavailable(
    source: WorkbenchSource,
) -> None:
    complete_underwriting(source, "ADBE", _raw(), now=NOW)
    projection = project_underwriting(source.store, "ADBE")
    assert projection.snapshot is not None
    evidence: dict[str, Any] = json.loads(projection.snapshot.evidence_json)
    evidence.pop("feature7_context", None)
    older_snapshot = replace(
        projection.snapshot,
        evidence_json=json.dumps(evidence, sort_keys=True),
    )

    view = build_investment_view(replace(projection, snapshot=older_snapshot))

    assert view.frozen_priority is None
    assert view.frozen_setup is None
    assert view.frozen_coverage is None


def test_completed_investment_view_renders_decision_metrics(
    source: WorkbenchSource, tmp_path: Path
) -> None:
    complete_underwriting(source, "ADBE", _raw(), now=NOW)
    app_script = tmp_path / "investment_view_app.py"
    app_script.write_text(
        "from owner_lens.persistence import SqliteStore\n"
        "from owner_lens.underwriting_contract import project_underwriting\n"
        "from owner_lens.workbench.views.company import _underwriting\n"
        f"store = SqliteStore({source.db_path!r})\n"
        "projection = project_underwriting(store, 'ADBE')\n"
        "_underwriting(projection)\n"
        "store.close()\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(app_script), default_timeout=30)
    app.run()

    assert not app.exception
    labels = {metric.label for metric in app.metric}
    assert {
        "Frozen price",
        "Expected return",
        "Required return",
        "Assessment",
        "Expected value/share",
    }.issubset(labels)
    assert any(item.value == "Scenario setup and outcomes" for item in app.subheader)

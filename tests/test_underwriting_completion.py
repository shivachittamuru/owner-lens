"""JSON-first underwriting validation, completion and retry behavior."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from test_underwriting import source as source  # noqa: PLC0414
from test_underwriting_contract import authoring

from owner_lens import underwriting_completion as completion
from owner_lens.persistence.errors import StorageWriteError
from owner_lens.underwriting import UnderwritingError
from owner_lens.underwriting_completion import (
    complete_underwriting,
    complete_underwriting_analysis,
    preview_underwriting,
)
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.valuation import ValuationError
from owner_lens.workbench.data import WorkbenchSource
from owner_lens.workbench.views.underwriting_json import _changes, _scenario_rows

NOW = datetime(2026, 6, 2, 12, tzinfo=UTC)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data)


def test_authoring_preview_validates_without_persisting(source: WorkbenchSource) -> None:
    preview = preview_underwriting(source, "ADBE", _json(authoring()), now=NOW)
    assert preview.ticker == "ADBE"
    assert preview.expected_latest_version == 0
    assert preview.proposed_version == 1
    assert [row["Scenario"] for row in _scenario_rows(preview.snapshot)] == [
        "Bear",
        "Base",
        "Bull",
    ]
    assert source.store.list_underwriting("ADBE") == ()


@pytest.mark.parametrize(
    ("raw_json", "message"),
    [
        ("{", "Invalid JSON syntax"),
        ('{"authoring_version": 2}', "missing fields"),
    ],
)
def test_authoring_syntax_and_schema_errors_do_not_persist(
    source: WorkbenchSource, raw_json: str, message: str
) -> None:
    with pytest.raises(UnderwritingError, match=message):
        preview_underwriting(source, "ADBE", raw_json, now=NOW)
    assert source.store.list_underwriting("ADBE") == ()


def test_authoring_semantic_error_and_company_mismatch_do_not_persist(
    source: WorkbenchSource,
) -> None:
    payload = authoring()
    payload["assumptions"]["scenarios"][0]["key_dependency"] = ""
    with pytest.raises(UnderwritingError, match="key_dependency"):
        preview_underwriting(source, "ADBE", _json(payload), now=NOW)

    mismatch = authoring()
    mismatch["ticker"] = "ORCL"
    with pytest.raises(UnderwritingError, match="does not match current company ADBE"):
        preview_underwriting(source, "ADBE", _json(mismatch), now=NOW)
    assert source.store.list_underwriting("ADBE") == ()


def test_changed_json_cannot_commit_a_stale_preview(source: WorkbenchSource) -> None:
    raw_json = _json(authoring())
    preview = preview_underwriting(source, "ADBE", raw_json, now=NOW)
    with pytest.raises(UnderwritingError, match="JSON changed after validation"):
        complete_underwriting(
            source,
            "ADBE",
            raw_json + " ",
            preview=preview,
            now=NOW,
        )
    assert source.store.list_underwriting("ADBE") == ()


def test_cli_exposes_complete_and_exact_version_retry() -> None:
    from owner_lens.cli import _build_parser

    parser = _build_parser()
    complete_args = parser.parse_args(
        ["underwriting", "complete", "ADBE", "--file", "underwriting.json"]
    )
    retry_args = parser.parse_args(
        ["underwriting", "analyze", "ADBE", "--version", "8"]
    )
    assert complete_args.underwriting_action == "complete"
    assert str(complete_args.file) == "underwriting.json"
    assert retry_args.underwriting_action == "analyze"
    assert retry_args.version == 8


def test_atomic_versioning_and_stale_preview_protection(
    source: WorkbenchSource,
) -> None:
    payload = _json(authoring())
    first_preview = preview_underwriting(source, "ADBE", payload, now=NOW)
    first = complete_underwriting(
        source, "ADBE", payload, preview=first_preview, now=NOW
    )
    assert first.record.version == 1

    next_preview = preview_underwriting(source, "ADBE", payload, now=NOW)
    assert next_preview.expected_latest_version == 1
    assert next_preview.proposed_version == 2
    second = complete_underwriting(
        source, "ADBE", payload, preview=next_preview, now=NOW
    )
    assert second.record.version == 2

    stale = preview_underwriting(source, "ADBE", payload, now=NOW)
    concurrent = preview_underwriting(source, "ADBE", payload, now=NOW)
    commit = complete_underwriting(
        source, "ADBE", payload, preview=concurrent, now=NOW
    )
    assert commit.record.version == 3
    with pytest.raises(StorageWriteError, match="history changed since review"):
        complete_underwriting(source, "ADBE", payload, preview=stale, now=NOW)
    assert [record.version for record in source.store.list_underwriting("ADBE")] == [
        1,
        2,
        3,
    ]


def test_completion_runs_existing_analysis_and_reuses_saved_approvals(
    source: WorkbenchSource,
) -> None:
    result = complete_underwriting(
        source, "ADBE", _json(authoring()), now=NOW
    )
    assert result.complete
    assert result.summary is not None
    assert result.summary.investor_policy.required_return == pytest.approx(0.12)
    assert result.summary.policy_source == "saved_underwriting"
    assert result.variant is not None
    assert result.variant.drivers
    assert result.challenger_run is not None

    before_runs = source.store.list_challenger_runs(result.record.underwriting_id)
    retry = complete_underwriting_analysis(source.store, result.record, now=NOW)
    after_runs = source.store.list_challenger_runs(result.record.underwriting_id)
    assert retry.complete
    assert retry.record == result.record
    assert len(after_runs) == len(before_runs) == 1
    assert retry.challenger_run == before_runs[0]
    projection = project_underwriting(source.store, "ADBE")
    assert projection.summary is not None
    assert projection.variant is not None
    assert projection.valuation_json is not None
    assert len(projection.challenger_runs) == 1


def test_partial_failure_keeps_record_and_retry_does_not_duplicate(
    source: WorkbenchSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_run_valuation = completion.run_valuation
    monkeypatch.setattr(
        completion,
        "run_valuation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValuationError("fixture valuation failure")
        ),
    )
    partial = complete_underwriting(
        source, "ADBE", _json(authoring()), now=NOW
    )
    assert partial.record.version == 1
    assert not partial.complete
    assert not partial.stages[0].succeeded
    assert "fixture valuation failure" in partial.stages[0].detail
    assert len(source.store.list_underwriting("ADBE")) == 1
    assert source.store.get_valuation(partial.record.underwriting_id, "8c-scenario-valuation-v1") is None

    monkeypatch.setattr(completion, "run_valuation", original_run_valuation)
    retried = complete_underwriting_analysis(
        source.store, partial.record, now=NOW
    )
    assert retried.complete
    assert retried.record == partial.record
    assert len(source.store.list_underwriting("ADBE")) == 1
    assert len(source.store.list_challenger_runs(partial.record.underwriting_id)) == 1


def test_preview_diff_is_economic_and_readable(source: WorkbenchSource) -> None:
    initial = complete_underwriting(
        source, "ADBE", _json(authoring()), now=NOW
    )
    revised = copy.deepcopy(authoring())
    revised["assumptions"]["scenarios"][1]["revenue_cagr"] = 0.08
    revised["judgments"]["investor_policy"]["required_return"] = 0.13
    preview = preview_underwriting(source, "ADBE", _json(revised), now=NOW)
    rows = _scenario_rows(preview.snapshot)
    changes = _changes(preview)

    assert initial.record.version == preview.expected_latest_version == 1
    assert preview.proposed_version == 2
    assert next(row for row in rows if row["Scenario"] == "Base")["Revenue CAGR"] == "8.0%"
    assert "Base revenue CAGR: 5.0% -> 8.0%" in changes
    assert "Required return: 12.0% -> 13.0%" in changes

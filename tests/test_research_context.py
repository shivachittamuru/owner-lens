"""Read-only Company underwriting rendering and safe deterministic research exports."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from test_underwriting import source as source  # noqa: PLC0414
from test_underwriting_loop import loop_snapshot

from owner_lens.challenger import run_challenger
from owner_lens.research_context import (
    build_research_context,
    estimate_window,
    scenario_rows,
)
from owner_lens.underwriting import (
    Reference,
    SemanticType,
    Statement,
    create_underwriting,
)
from owner_lens.underwriting_contract import project_underwriting
from owner_lens.valuation import run_valuation
from owner_lens.workbench.data import (
    WorkbenchSource,
    company_detail,
    load_persisted_companies,
)


def inputs(source: WorkbenchSource, *, challenger: bool = True) -> tuple[Any, Any]:
    record = create_underwriting(
        source, "ADBE", loop_snapshot().manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    run_valuation(source.store, record)
    if challenger:
        run_challenger(source.store, record)
    detail = company_detail(source, load_persisted_companies(source, "fmp")[0])
    return detail, project_underwriting(source.store, "ADBE")


def render_page(detail: Any, projection: Any) -> AppTest:
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from owner_lens.workbench.views.company import render\n"
        "render(st.session_state['detail'], st.session_state['projection'])",
        default_timeout=30,
    )
    app.session_state["detail"] = detail
    app.session_state["projection"] = projection
    app.run()
    assert not app.exception, [item.value for item in app.exception]
    return app


def test_complete_company_projection_values_without_ui_recomputation(
    source: WorkbenchSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail, projection = inputs(source)
    from owner_lens import challenger, underwriting_summary, valuation, variant

    for module, name in (
        (valuation, "value_underwriting"),
        (variant, "compare_variant"),
        (underwriting_summary, "summarize_underwriting"),
        (challenger, "run_challenger"),
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda *a, **kw: pytest.fail("No investing computation in UI/export"),
        )
    before = source.store.list_underwriting("ADBE")
    app = render_page(detail, projection)
    assert (
        next(item.value for item in app.metric if item.label == "Assessment")
        == projection.summary.classification
    )
    assert any("underwriting v1" in item.value for item in app.caption)
    assert any(item.label == "Frozen price" for item in app.metric)
    table = next(
        item.value for item in app.dataframe if "Scenario" in item.value.columns
    )
    assert list(table["Scenario"]) == ["BEAR", "BASE", "BULL"]
    assert (
        scenario_rows(projection)[1]["Value/share [CALCULATION]"]
        == projection.summary.scenarios[1].value_per_share
    )
    assert any("Evidence unavailable" in item.value for item in app.caption)
    assert source.store.list_underwriting("ADBE") == before
    next(
        item for item in app.button if item.label == "Copy Research Context"
    ).click().run()
    assert not app.exception
    assert any("OwnerLens Research Context" in item.value for item in app.code)


def test_company_empty_underwriting_and_no_saved_challenger(
    source: WorkbenchSource,
) -> None:
    detail = company_detail(source, load_persisted_companies(source, "fmp")[0])
    projection = project_underwriting(source.store, "ADBE")
    app = render_page(detail, projection)
    assert any("No immutable underwriting record" in item.value for item in app.info)
    detail, projection = inputs(source, challenger=False)
    app = render_page(detail, projection)
    assert any("No saved challenger run" in item.value for item in app.caption)
    assert any("None recorded." in item.value for item in app.caption)


def test_deterministic_markdown_json_explicit_semantics_and_sanitization(
    source: WorkbenchSource,
) -> None:
    detail, projection = inputs(source)
    context = build_research_context(detail, projection)
    assert context == build_research_context(detail, projection)
    assert len(context.markdown) < 16000
    for section in (
        "screening",
        "economics",
        "market_expectations",
        "underwriting",
        "ASSUMPTION",
        "JUDGMENT",
        "CALCULATION",
    ):
        assert section in context.markdown
    assert "No investor evidence recorded" in context.markdown
    assert "raw_object_ref" not in context.json_export
    assert "request_parameters" not in context.json_export
    assert "ownerlens.db" not in context.markdown
    assert projection.record.underwriting_id not in context.markdown
    poisoned = replace(
        projection.snapshot,
        manual=replace(
            projection.snapshot.manual,
            business_drivers=(
                Statement(
                    SemanticType.JUDGMENT,
                    r"api_key=SECRET123 password=HIDDEN C:\Users\private\ownerlens.db https://example.com?apikey=KEY",
                    (Reference(uri="https://example.com?token=ABC"),),
                ),
            ),
        ),
    )
    safe = build_research_context(detail, replace(projection, snapshot=poisoned))
    for secret in (
        "SECRET123",
        "HIDDEN",
        "KEY",
        "ABC",
        "C:\\Users",
        "ownerlens.db",
        "request_parameters",
    ):
        assert secret not in safe.markdown and secret not in safe.json_export
    assert "[REDACTED]" in safe.markdown


def test_export_without_underwriting_or_saved_values(source: WorkbenchSource) -> None:
    detail = company_detail(source, load_persisted_companies(source, "fmp")[0])
    empty = build_research_context(detail, project_underwriting(source.store, "ADBE"))
    assert "No immutable underwriting record" in empty.markdown
    assert "EXPECTATION" in empty.markdown
    record = create_underwriting(
        source, "ADBE", loop_snapshot().manual, now=datetime(2026, 6, 2, 12, tzinfo=UTC)
    )
    projection = project_underwriting(source.store, "ADBE", version=record.version)
    assert scenario_rows(projection)[0]["Value/share [CALCULATION]"] is None
    context = build_research_context(detail, projection)
    assert "expected_CAGR: N/A" in context.markdown
    assert "No saved challenger run" in context.markdown
    assert "No saved valuation" in context.markdown
    app = render_page(detail, projection)
    assert any(
        "Analysis incomplete" in item.value for item in app.caption
    )
    assert any(item.label == "View Full JSON" for item in app.get("expander"))
    assert (
        source.store.get_valuation(record.underwriting_id, "equity-fcf-multiple-5y-v1")
        is None
    )


def test_application_company_route_loads_current_projection(
    source: WorkbenchSource,
) -> None:
    _detail, projection = inputs(source)
    app_path = Path(__file__).parents[1] / "src" / "owner_lens" / "workbench" / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120)
    app.session_state["provider"] = "fmp"
    app.session_state["page"] = "Company"
    app.session_state["selected_ticker"] = "ADBE"
    app.run()
    assert not app.exception and not app.error
    assert (
        next(item.value for item in app.metric if item.label == "Assessment")
        == projection.summary.classification
    )
    assert any("underwriting v1" in item.value for item in app.caption)


@pytest.mark.parametrize("period,limit", [("annual", 5), ("quarterly", 4)])
def test_nearest_forward_window_sorted_relative_to_asof(
    period: str, limit: int
) -> None:
    dates = (
        [
            "2024-11-30",
            "2025-11-30",
            "2026-11-30",
            "2027-11-30",
            "2028-11-30",
            "2029-11-30",
            "2030-11-30",
            "2031-11-30",
        ]
        if period == "annual"
        else [
            "2026-03-31",
            "2026-06-30",
            "2026-09-30",
            "2026-12-31",
            "2027-03-31",
            "2027-06-30",
            "2027-09-30",
            "2027-12-31",
        ]
    )
    rows = [
        {"target_date": target, "revenue_average": index}
        for index, target in enumerate(dates)
    ]
    result = estimate_window(list(reversed(rows)), period=period, as_of="2026-06-30")
    expected = [row for row in rows if row["target_date"] > "2026-06-30"][:limit]
    assert result["rows"] == expected
    assert result["available_rows"] == rows
    assert len(result["rows"]) == limit


def test_sparse_and_missing_estimates_remain_explicit() -> None:
    result = estimate_window(
        [{"target_date": "2028-11-28"}], period="annual", as_of="2026-11-01"
    )
    assert result["rows"] == [{"target_date": "2028-11-28"}]
    assert any("No nearer periods captured" in note for note in result["missing"])
    assert any("Only 1" in note for note in result["missing"])
    assert (
        estimate_window(
            [{"target_date": "2025-01-01"}], period="quarterly", as_of="2026-01-01"
        )["rows"]
        == []
    )


def test_unwritten_company_estimates_use_snapshot_date_and_separate_periods(
    source: WorkbenchSource,
) -> None:
    import json

    detail = company_detail(source, load_persisted_companies(source, "fmp")[0])
    rows = tuple(
        {
            "dataset": dataset,
            "target_date": target,
            "fetched_at": "2026-06-30T10:00:00+00:00",
            "snapshot_id": index,
            "content_hash": "fixture",
            "revenue_average": 10,
        }
        for index, (dataset, target) in enumerate(
            [
                ("annual_analyst_estimates", "2030-11-30"),
                ("annual_analyst_estimates", "2027-11-30"),
                ("annual_analyst_estimates", "2026-11-30"),
                ("quarterly_analyst_estimates", "2027-03-31"),
                ("quarterly_analyst_estimates", "2026-09-30"),
            ]
        )
    )
    context = build_research_context(replace(detail, market_expectations=rows), None)
    windows = json.loads(context.json_export)["market_expectations [EXPECTATION]"]
    annual = next(item for item in windows if item["period"] == "annual")
    quarterly = next(item for item in windows if item["period"] == "quarterly")
    assert annual["as_of"] == "2026-06-30"
    assert annual["retrieved_at"] == "2026-06-30T10:00:00+00:00"
    assert [row["target_date"] for row in annual["rows"]] == [
        "2026-11-30",
        "2027-11-30",
        "2030-11-30",
    ]
    assert [row["target_date"] for row in quarterly["rows"]] == [
        "2026-09-30",
        "2027-03-31",
    ]


def test_export_windows_use_frozen_asof_and_keep_complete_sanitized_json(
    source: WorkbenchSource,
) -> None:
    import json

    detail, projection = inputs(source)
    evidence = json.loads(projection.snapshot.evidence_json)
    annual = next(
        item
        for item in evidence["market_expectations"]["snapshots"]
        if item["source"]["period_type"] == "annual"
    )
    original = annual["rows"][0]
    annual["rows"] = [
        {**original, "target_date": f"{year}-11-30"}
        for year in reversed(range(2025, 2033))
    ]
    modified = replace(
        projection,
        snapshot=replace(projection.snapshot, evidence_json=json.dumps(evidence)),
    )
    context = build_research_context(detail, modified)
    exported = json.loads(context.json_export)
    window = next(
        item
        for item in exported["market_expectations [EXPECTATION]"]
        if item["period"] == "annual"
    )
    assert [row["target_date"] for row in window["rows"]] == [
        f"{year}-11-30" for year in range(2026, 2031)
    ]
    assert len(window["available_rows"]) == 8
    assert window["snapshot_id"] == annual["source"]["snapshot_id"]
    assert window["retrieved_at"] == annual["source"]["fetched_at"]
    assert "2032-11-30" not in context.markdown
    assert "frozen_starting_state" not in context.markdown
    assert "historical_ranges" not in context.markdown
    assert len(context.markdown) < len(context.json_export)

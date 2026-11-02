"""JSON-first underwriting approval and completion controls."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import streamlit as st

from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.underwriting import UnderwritingError, UnderwritingSnapshot
from owner_lens.underwriting_completion import (
    UnderwritingCompletion,
    UnderwritingPreview,
    complete_underwriting,
    complete_underwriting_analysis,
    preview_underwriting,
)
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.workbench.data import WorkbenchSource

SourceFactory = Callable[[], AbstractContextManager[WorkbenchSource]]


def _ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _multiple(value: float) -> str:
    return f"{value:.1f}x"


def _scenario_rows(snapshot: UnderwritingSnapshot) -> list[dict[str, str]]:
    probabilities = {
        item.name: item.probability
        for item in (snapshot.manual.probability_distribution.scenarios
                     if snapshot.manual.probability_distribution else ())
    }
    return [
        {
            "Scenario": scenario.name.value.title(),
            "Revenue CAGR": _ratio(scenario.revenue_cagr),
            "Year-5 FCF margin": _ratio(scenario.fcf_margin_year5),
            "Share CAGR": _ratio(scenario.share_count_cagr),
            "Terminal FCF multiple": _multiple(scenario.terminal_fcf_multiple),
            "Probability": _ratio(probabilities.get(scenario.name)),
        }
        for scenario in snapshot.manual.scenarios
    ]


def _condition_map(conditions: tuple[Any, ...], legacy: tuple[str, ...]) -> dict[str, str]:
    if conditions:
        return {
            condition.condition_id: condition.statement
            for condition in conditions
        }
    return {f"legacy-{index}": statement for index, statement in enumerate(legacy)}


def _changes(preview: UnderwritingPreview) -> list[str]:
    previous = preview.latest_record
    if previous is None:
        return []
    old = UnderwritingSnapshot.from_json(previous.snapshot_json).manual
    new = preview.snapshot.manual
    old_scenarios = {item.name: item for item in old.scenarios}
    new_scenarios = {item.name: item for item in new.scenarios}
    old_probabilities = {
        item.name: item.probability
        for item in (old.probability_distribution.scenarios
                     if old.probability_distribution else ())
    }
    new_probabilities = {
        item.name: item.probability
        for item in (new.probability_distribution.scenarios
                     if new.probability_distribution else ())
    }
    changes: list[str] = []
    for name in ("BEAR", "BASE", "BULL"):
        scenario_name = next(item for item in new_scenarios if item.value == name)
        prior = old_scenarios.get(scenario_name)
        current = new_scenarios[scenario_name]
        if prior is None:
            changes.append(f"{name.title()} scenario added.")
            continue
        fields = (
            ("revenue_cagr", "revenue CAGR", _ratio),
            ("fcf_margin_year5", "FCF margin", _ratio),
            ("share_count_cagr", "share CAGR", _ratio),
            ("terminal_fcf_multiple", "terminal FCF", _multiple),
        )
        for field, label, formatter in fields:
            before, after = getattr(prior, field), getattr(current, field)
            if before != after:
                changes.append(f"{name.title()} {label}: {formatter(before)} -> {formatter(after)}")
        before_probability = old_probabilities.get(scenario_name)
        after_probability = new_probabilities.get(scenario_name)
        if before_probability != after_probability:
            changes.append(
                f"{name.title()} probability: {_ratio(before_probability)} -> {_ratio(after_probability)}"
            )

    old_return = old.investor_policy.required_return if old.investor_policy else None
    new_return = new.investor_policy.required_return if new.investor_policy else None
    if old_return != new_return:
        changes.append(f"Required return: {_ratio(old_return)} -> {_ratio(new_return)}")
    elif new_return is not None:
        changes.append(f"Required return: {_ratio(old_return)} -> {_ratio(new_return)} (unchanged)")

    for label, old_conditions, new_conditions in (
        ("Dependency", old.thesis.monitoring_dependencies, new.thesis.monitoring_dependencies),
        ("Breaker", old.thesis.monitoring_breakers, new.thesis.monitoring_breakers),
    ):
        legacy_field = "dependencies" if label == "Dependency" else "breakers"
        before = _condition_map(
            old_conditions, getattr(old.thesis, legacy_field)
        )
        after = _condition_map(
            new_conditions, getattr(new.thesis, legacy_field)
        )
        for condition_id in sorted(before.keys() - after.keys()):
            changes.append(f"{label} removed: {before[condition_id]}")
        for condition_id in sorted(after.keys() - before.keys()):
            changes.append(f"{label} added: {after[condition_id]}")
        for condition_id in sorted(before.keys() & after.keys()):
            if before[condition_id] != after[condition_id]:
                changes.append(
                    f"{label} changed: {before[condition_id]} -> {after[condition_id]}"
                )

    if old.thesis.biggest_uncertainty != new.thesis.biggest_uncertainty:
        changes.append(
            "Biggest uncertainty: "
            f"{old.thesis.biggest_uncertainty} -> {new.thesis.biggest_uncertainty}"
        )
    if old.thesis.most_important_variable != new.thesis.most_important_variable:
        changes.append(
            "Most important variable: "
            f"{old.thesis.most_important_variable} -> {new.thesis.most_important_variable}"
        )
    old_rationales = {item.driver: item.text for item in old.variant_rationales}
    new_rationales = {item.driver: item.text for item in new.variant_rationales}
    for driver in sorted(old_rationales.keys() | new_rationales.keys()):
        before, after = old_rationales.get(driver), new_rationales.get(driver)
        if before != after:
            changes.append(f"Variant rationale ({driver}): {before or 'None'} -> {after or 'None'}")
    return changes


def _show_preview(preview: UnderwritingPreview, raw_json: str) -> None:
    manual = preview.snapshot.manual
    required_return = (
        manual.investor_policy.required_return if manual.investor_policy else None
    )
    st.subheader("Validation and preview")
    st.write(
        f"**{preview.ticker}** | Current version: "
        f"v{preview.expected_latest_version or 'Initial'} | "
        f"Proposed version: v{preview.proposed_version} | "
        f"Required return: {_ratio(required_return)}"
    )
    st.dataframe(_scenario_rows(preview.snapshot), hide_index=True, width="stretch")
    judgments = manual
    st.markdown("**Key business drivers**")
    for driver in judgments.business_drivers:
        st.write(driver.text)
    st.markdown("**Judgment**")
    st.write("Biggest uncertainty: " + judgments.thesis.biggest_uncertainty)
    st.write("Most important variable: " + judgments.thesis.most_important_variable)
    for rationale in judgments.variant_rationales:
        st.write(f"Variant view ({rationale.driver}): {rationale.text}")
    st.write(
        "Probability rationale: "
        + (judgments.probability_distribution.rationale or "N/A")
        if judgments.probability_distribution
        else "Probability rationale: N/A"
    )
    st.markdown("**Dependencies**")
    for condition in judgments.thesis.monitoring_dependencies:
        st.write(condition.statement)
    st.markdown("**Breakers**")
    for condition in judgments.thesis.monitoring_breakers:
        st.write(condition.statement)
    st.markdown("**Supporting evidence**")
    for statement in judgments.supporting_evidence:
        st.write(statement.text)
        if statement.references:
            st.caption(
                "Sources: "
                + ", ".join(
                    reference.title or reference.uri or "Unlabeled source"
                    for reference in statement.references
                )
            )
    st.markdown("**Disconfirming evidence**")
    for statement in judgments.disconfirming_evidence:
        st.write(statement.text)
        if statement.references:
            st.caption(
                "Sources: "
                + ", ".join(
                    reference.title or reference.uri or "Unlabeled source"
                    for reference in statement.references
                )
            )
    st.markdown("**Next evidence to seek**")
    for item in judgments.thesis.next_evidence_to_collect:
        st.write(item)
    changes = _changes(preview)
    st.subheader("Changes versus latest underwriting")
    if preview.latest_record is None:
        st.caption("Initial underwriting")
    elif changes:
        for change in changes:
            st.write(change)
    else:
        st.caption("No tracked judgment changes.")
    with st.expander("Full authoring JSON"):
        st.code(raw_json, language="json")


def _show_stages(stages: tuple[Any, ...]) -> None:
    st.markdown("**Analysis status**")
    for stage in stages:
        if stage.succeeded:
            st.success(f"{stage.name}: {stage.detail}")
        else:
            st.error(f"{stage.name}: {stage.detail}")


def _needs_analysis(projection: UnderwritingProjection) -> bool:
    return bool(
        projection.record is not None
        and (
            projection.valuation_json is None
            or projection.summary is None
            or projection.variant is None
            or not projection.challenger_runs
        )
    )


def render(
    ticker: str,
    projection: UnderwritingProjection,
    source_factory: SourceFactory,
) -> None:
    """Render the primary JSON authoring path and retry controls."""
    state_key = f"underwriting_json.{ticker}"
    raw_key = state_key + ".raw"
    state = st.session_state.setdefault(state_key, {})
    notice = state.pop("commit_notice", None)
    if notice:
        st.success(notice)

    if st.button("New Underwriting", key=state_key + ".new"):
        state.clear()
        state["editing"] = True
        st.session_state[raw_key] = ""

    if st.button("View History", key=state_key + ".history"):
        state["show_history"] = True
    if state.get("show_history"):
        with st.expander("Underwriting history", expanded=True):
            with source_factory() as source:
                if not isinstance(source.store, SqliteStore):
                    raise UnderwritingError("Underwriting requires the SQLite evidence store.")
                records = source.store.list_underwriting(ticker)
            if records:
                st.dataframe(
                    [
                        {
                            "Version": record.version,
                            "As of": record.as_of_date,
                            "Created": record.created_at,
                        }
                        for record in records
                    ],
                    hide_index=True,
                )
            else:
                st.caption("No underwriting history.")

    if _needs_analysis(projection):
        record = projection.record
        assert record is not None
        if st.button("Retry analysis", key=state_key + ".retry"):
            with source_factory() as source:
                if not isinstance(source.store, SqliteStore):
                    raise UnderwritingError("Underwriting requires the SQLite evidence store.")
                analysis_result = complete_underwriting_analysis(source.store, record)
            state["analysis_version"] = record.version
            state["stages"] = analysis_result.stages
            st.rerun()

    if (
        state.get("stages")
        and projection.record is not None
        and state.get("analysis_version") == projection.record.version
    ):
        _show_stages(state["stages"])

    if not state.get("editing"):
        return

    st.subheader("Paste OwnerLens Underwriting JSON")
    with st.expander("Advanced import from JSON file"):
        upload = st.file_uploader(
            "Choose an Authoring v2 JSON file",
            type=["json"],
            key=state_key + ".upload",
        )
        if st.button(
            "Load file into editor",
            key=state_key + ".load",
            disabled=upload is None,
        ) and upload is not None:
            try:
                content = upload.getvalue().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                st.error(f"Unable to decode the selected JSON file: {exc}")
                return
            st.session_state[raw_key] = content
            state.pop("preview", None)
            st.rerun()
    raw_json = st.text_area(
        "Paste OwnerLens Underwriting JSON",
        key=raw_key,
        height=360,
        placeholder="Paste Authoring v2 JSON here.",
    )
    preview: UnderwritingPreview | None = state.get("preview")
    if preview is not None and state.get("preview_json") != raw_json:
        state.pop("preview", None)
        state.pop("preview_json", None)
        preview = None
        st.info("JSON changed. Validate again before committing.")
    if st.button("Validate + Preview", key=state_key + ".validate"):
        try:
            with source_factory() as source:
                preview = preview_underwriting(source, ticker, raw_json)
            state["preview"] = preview
            state["preview_json"] = raw_json
            state.pop("stages", None)
        except (UnderwritingError, PersistenceError, OSError) as exc:
            state.pop("preview", None)
            state.pop("preview_json", None)
            st.error(str(exc))
            return
        preview = state["preview"]
    if preview is None:
        return

    _show_preview(preview, raw_json)
    if st.button("Commit & Analyze", key=state_key + ".commit", type="primary"):
        try:
            with source_factory() as source:
                if not isinstance(source.store, SqliteStore):
                    raise UnderwritingError("Underwriting requires the SQLite evidence store.")
                completion_result: UnderwritingCompletion = complete_underwriting(
                    source,
                    ticker,
                    raw_json,
                    preview=preview,
                )
        except (UnderwritingError, PersistenceError, OSError) as exc:
            state.pop("preview", None)
            state.pop("preview_json", None)
            st.error(str(exc))
            return
        state["editing"] = False
        state["analysis_version"] = completion_result.record.version
        state["stages"] = completion_result.stages
        state["commit_notice"] = (
            f"Underwriting v{completion_result.record.version} committed successfully."
        )
        state.pop("preview", None)
        state.pop("preview_json", None)
        st.rerun()

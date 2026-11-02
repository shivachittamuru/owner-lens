"""Draft widgets only; canonical validation, context and saving live in the domain."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import streamlit as st

from owner_lens.persistence import compute_content_hash
from owner_lens.persistence.errors import PersistenceError
from owner_lens.research_context import estimate_window
from owner_lens.underwriting import (
    PREDICATE_OPERATORS,
    SemanticType,
    UnderwritingError,
    UnderwritingInputs,
    capture_underwriting_inputs,
    load_manual_json,
    save_underwriting_inputs,
)
from owner_lens.underwriting_authoring import (
    DriverContext,
    authoring_context,
    authoring_from_manual,
    draft_hints,
    empty_authoring,
    probability_feedback,
    review_authoring,
)
from owner_lens.underwriting_contract import UnderwritingProjection
from owner_lens.variant import VariantError
from owner_lens.workbench.data import WorkbenchSource, format_ratio

SourceFactory = Callable[[], WorkbenchSource]
LABELS = {
    "revenue_cagr": "Revenue CAGR",
    "fcf_margin_year5": "Year-5 FCF margin",
    "share_count_cagr": "Share-count CAGR",
    "terminal_fcf_multiple": "Terminal equity FCF multiple",
}


def _text(label: str, key: str, value: str | None = None, *, area: bool = False) -> str:
    widget = st.text_area if area else st.text_input
    return str(widget(label, value=value or "", key=key)).strip()


def _required_feedback(value: Any, label: str) -> None:
    if value is None or value == "":
        st.caption(f"{label} is required.")


def _optional_date(label: str, key: str, value: str | None) -> str | None:
    result = st.date_input(label, value=date.fromisoformat(value) if value else None, key=key)
    return result.isoformat() if result is not None else None


def _count(label: str, key: str, seed: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    count = int(st.session_state.setdefault(key, max(seed, minimum)))
    add, remove = st.columns(2)
    if add.button(f"Add {label}", key=key + ".add", disabled=maximum is not None and count >= maximum):
        count += 1
    if remove.button(f"Remove last {label}", key=key + ".remove", disabled=count <= minimum):
        count -= 1
    st.session_state[key] = count
    return count


def _references(seed: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    count = _count("source", key + ".count", len(seed))
    refs = []
    for index in range(count):
        item = seed[index] if index < len(seed) else {}
        prefix = f"{key}.{index}"
        with st.expander(f"Source {index + 1} [Optional]", expanded=False):
            ref = {
                "title": _text("Source/title", prefix + ".title", item.get("title")) or None,
                "uri": _text("Reference URI", prefix + ".uri", item.get("uri")) or None,
                "observed_at": _text("Source observation date/time (optional ISO)", prefix + ".observed", item.get("observed_at")) or None,
                "note": _text("Reference note", prefix + ".note", item.get("note")) or None,
            }
            if any(ref.values()):
                refs.append(ref)
            else:
                st.caption("Empty source; no reference will be asserted.")
    return refs


def _conditions(seed: list[dict[str, Any]], field: str, key: str) -> list[dict[str, Any]]:
    label = "dependency" if field == "dependencies" else "breaker"
    count = _count(label, key + ".count", len(seed), minimum=1)
    result = []
    for index in range(count):
        item = seed[index] if index < len(seed) else {}
        prefix = f"{key}.{index}"
        with st.expander(f"{label.title()} {index + 1}", expanded=index == 0):
            condition: dict[str, Any] = {
                "category": "JUDGMENT",
                "statement": _text("Statement", prefix + ".statement", item.get("statement"), area=True),
                "observable": _text("Metric / observable", prefix + ".observable", item.get("observable")) or None,
            }
            structured = st.checkbox("Use structured predicate", value=item.get("operator") is not None,
                                     key=prefix + ".structured")
            if structured:
                operators = list(PREDICATE_OPERATORS)
                condition.update({
                    "operator": st.selectbox("Predicate operator", operators,
                                             index=operators.index(item["operator"]) if item.get("operator") in operators else None,
                                             key=prefix + ".operator"),
                    "threshold": st.number_input("Numeric predicate threshold", value=float(item["threshold"]) if item.get("operator") and item.get("threshold") is not None else None,
                                                 key=prefix + ".numeric_threshold"),
                    "unit": _text("Exact predicate unit", prefix + ".unit", item.get("unit")) or None,
                    "cadence": _text("Exact predicate cadence", prefix + ".predicate_cadence", item.get("cadence")) or None,
                    "source_family": _text("Exact predicate source family", prefix + ".source_family", item.get("source_family")) or None,
                })
            else:
                condition["threshold"] = _text("Threshold / condition", prefix + ".threshold",
                                               item.get("threshold") if not item.get("operator") else None) or None
            _required_feedback(condition["statement"], f"{label.title()} statement (v2 contract)")
            with st.expander("Sources / monitoring metadata [Optional]"):
                condition.update({
                    "condition_id": _text("Condition ID", prefix + ".id", item.get("condition_id", f"{field}-{index + 1}")),
                    "sources": _references(item.get("sources", []), prefix + ".sources"),
                    "monitoring_cadence": _text("Monitoring cadence", prefix + ".cadence", item.get("monitoring_cadence")) or None,
                    "monitoring_date": _optional_date("Monitoring date (optional)", prefix + ".date", item.get("monitoring_date")),
                })
            result.append(condition)
    return result


def _evidence(seed: list[dict[str, Any]], field: str, key: str, links: dict[str, str]) -> list[dict[str, Any]]:
    count = _count("evidence item", key + ".count", len(seed))
    if not count:
        st.info("No evidence recorded. Missing evidence is not assumed.")
    result = []
    for index in range(count):
        item = seed[index] if index < len(seed) else {}
        prefix = f"{key}.{index}"
        with st.expander(f"Evidence {index + 1}", expanded=not item):
            kinds = [kind.value for kind in SemanticType]
            category = st.selectbox(
                "Semantic category (investor asserted, not automatically verified)",
                kinds, index=kinds.index(item["category"]) if item.get("category") in kinds else None,
                key=prefix + ".category",
            )
            options = list(dict.fromkeys([*links, *item.get("belief_references", [])]))
            evidence = {
                "category": category,
                "text": _text("Claim / observation", prefix + ".text", item.get("text"), area=True),
                "belief_references": st.multiselect(
                    "Supports / challenges belief (optional)", options,
                    default=item.get("belief_references", []), format_func=lambda pointer: links.get(pointer, pointer),
                    key=prefix + ".links",
                ),
            }
            with st.expander("Sources / evidence metadata [Optional]"):
                evidence.update({
                    "evidence_id": _text("Evidence ID", prefix + ".id", item.get("evidence_id", f"{field}-{index + 1}")) or None,
                    "evidence_date": _optional_date("Evidence date / as-of (optional)", prefix + ".date", item.get("evidence_date")),
                    "references": _references(item.get("references", []), prefix + ".refs"),
                })
            result.append(evidence)
    return result


def _assumption(context: DriverContext, scenario: dict[str, Any], key: str) -> float | None:
    driver = context.driver
    is_multiple = driver == "terminal_fcf_multiple"
    label = LABELS[driver] + (" (x)" if is_multiple else " (%)")
    scale = 1 if is_multiple else 100
    input_key = key + "." + driver
    entry, information = st.columns([3, 2])
    with information, st.expander("History / consensus reference"):
        if is_multiple:
            st.caption("Investor ASSUMPTION only. No terminal-multiple consensus or preset is available.")
        else:
            st.caption(f"Latest annual [FACT/CALCULATION]: {format_ratio(context.latest)}")
            st.caption(f"Observed annual range [CALCULATION]: {format_ratio(context.minimum)} to {format_ratio(context.maximum)}")
            if context.historical_cagr is not None:
                st.caption(f"FY{context.start_year}-FY{context.end_year} CAGR [CALCULATION]: {format_ratio(context.historical_cagr)}")
            if context.consensus:
                consensus = context.consensus
                st.caption(f"Captured consensus CAGR [EXPECTATION basis]: {format_ratio(consensus.value)}"
                           f"; {consensus.horizon_years or 'N/A'}Y target {consensus.target_date or 'N/A'}")
                if consensus.reason:
                    st.caption(consensus.reason)
    with entry:
        choices = context.presets()
        if choices:
            selected = st.selectbox(
                "Optional explicit preset", list(choices), index=None,
                key=input_key + ".preset", placeholder="No preset selected",
            )
            if st.button("Apply preset as ASSUMPTION", key=input_key + ".apply", disabled=selected is None):
                st.session_state[input_key] = choices[str(selected)] * scale
        value = scenario.get(driver)
        number = st.number_input(
            label, value=float(value) * scale if value is not None else None,
            step=0.5 if is_multiple else 0.1, format="%.4f", key=input_key,
            placeholder="Investor approval required",
        )
        _required_feedback(number, LABELS[driver])
    return number / scale if number is not None else None


def _fields(seed: dict[str, Any], contexts: tuple[DriverContext, ...], key: str) -> dict[str, Any]:
    payload = empty_authoring()
    st.subheader("1. Scenarios [Required · ASSUMPTION]")
    for index, original in enumerate(seed["assumptions"]["scenarios"]):
        name = original["name"]
        prefix = f"{key}.scenario.{name}"
        with st.expander(name + " [Required]", expanded=True):
            scenario = {
                "name": name, "category": "ASSUMPTION", "horizon_years": 5,
                "narrative": _text("Scenario narrative", prefix + ".narrative", original.get("narrative"), area=True),
                "key_dependency": _text("Scenario key dependency", prefix + ".dependency", original.get("key_dependency"), area=True) or None,
            }
            _required_feedback(scenario["narrative"], f"{name.title()} narrative")
            _required_feedback(scenario["key_dependency"], f"{name.title()} key dependency")
            for context in contexts:
                scenario[context.driver] = _assumption(context, original, prefix)
            payload["assumptions"]["scenarios"][index] = scenario
    judgment = payload["judgments"]
    original_judgment = seed["judgments"]
    st.subheader("2. Probabilities & hurdle [Required · JUDGMENT]")
    for index, probability in enumerate(original_judgment["probability_distribution"]["scenarios"]):
        value = probability["probability"]
        entered = st.number_input(
            probability["name"] + " probability (%)", min_value=0.0, max_value=100.0,
            value=float(value) * 100 if value is not None else None, step=1.0,
            key=f"{key}.probability.{probability['name']}",
        )
        judgment["probability_distribution"]["scenarios"][index]["probability"] = entered / 100 if entered is not None else None
    total, error = probability_feedback(payload)
    st.caption("Total: " + (f"{total:.2%}" if total is not None else "N/A (missing probabilities)"))
    if error:
        st.warning(error)
    judgment["probability_distribution"]["rationale"] = _text(
        "Probability rationale", key + ".probability.rationale", original_judgment["probability_distribution"].get("rationale"), area=True
    ) or None
    _required_feedback(judgment["probability_distribution"]["rationale"], "Probability rationale")
    original_policy = original_judgment["investor_policy"]
    hurdle = st.number_input(
        "Required-return hurdle (%)", value=float(original_policy["required_return"]) * 100 if original_policy["required_return"] is not None else None,
        step=0.5, key=key + ".hurdle",
    )
    _required_feedback(hurdle, "Required-return hurdle")
    with st.expander("Investor policy rationale [Optional]"):
        judgment["investor_policy"] = {
            "category": "JUDGMENT", "required_return": hurdle / 100 if hurdle is not None else None,
            "rationale": _text("Required-return policy rationale (optional)", key + ".policy.rationale", original_policy.get("rationale")) or None,
        }
    thesis = original_judgment["thesis"]
    with st.expander("3. Business judgment [Recommended; v2 required fields inside]"):
        st.info("The unchanged v2 contract requires 3-5 drivers, biggest uncertainty, most important variable and next evidence. "
                "Start from latest to reuse your existing judgments; no placeholders are invented.")
        count = _count("business driver", key + ".drivers.count", len(original_judgment["business_drivers"]), minimum=3, maximum=5)
        judgment["business_drivers"] = [
            {**(original_judgment["business_drivers"][i] if i < len(original_judgment["business_drivers"]) else {}),
             "category": "JUDGMENT", "text": _text(f"Business/value driver {i + 1} [Required by v2]", f"{key}.drivers.{i}",
              original_judgment["business_drivers"][i]["text"] if i < len(original_judgment["business_drivers"]) else "", area=True)}
            for i in range(count)
        ]
        for field, label in (("biggest_uncertainty", "Biggest uncertainty"), ("most_important_variable", "Most important variable")):
            judgment["thesis"][field] = _text(label + " [Required by v2]", key + "." + field, thesis[field], area=True)
            _required_feedback(judgment["thesis"][field], label + " (v2 contract)")
        for index, driver in enumerate(judgment["business_drivers"]):
            _required_feedback(driver["text"], f"Business driver {index + 1} (v2 contract)")
        count = _count("next evidence", key + ".next.count", len(thesis["next_evidence_to_collect"]), minimum=1)
        judgment["thesis"]["next_evidence_to_collect"] = [
            _text(f"Next evidence to collect {i + 1} [Required by v2]", f"{key}.next.{i}",
                  thesis["next_evidence_to_collect"][i] if i < len(thesis["next_evidence_to_collect"]) else "", area=True)
            for i in range(count)
        ]
        for index, text in enumerate(judgment["thesis"]["next_evidence_to_collect"]):
            _required_feedback(text, f"Next evidence {index + 1} (v2 contract)")
    with st.expander("Variant rationales [Recommended · JUDGMENT]"):
        for driver, label in LABELS.items():
            previous: dict[str, Any] = next((item for item in original_judgment["variant_rationales"] if item["driver"] == driver), {})
            text = _text(label + " rationale", f"{key}.variant.{driver}", previous.get("text"), area=True)
            if text:
                judgment["variant_rationales"].append({**previous, "driver": driver, "category": "JUDGMENT", "text": text})
    evidence_section = st.container()
    thesis_section = st.container()
    with thesis_section, st.expander("5. Thesis monitoring [Recommended; v2 required statements inside]"):
        st.caption("Required by the existing v2 contract: at least one dependency and breaker statement. "
                   "Observables/thresholds are recommended; sources/cadence/dates are optional.")
        for field, label in (("dependencies", "What must be true"), ("breakers", "What would break the thesis")):
            st.subheader(label + " [JUDGMENT]")
            judgment["thesis"][field] = _conditions(thesis[field], field, f"{key}.{field}")
    links = {f"/manual/business_drivers/{i}": f"Business driver {i + 1}" for i in range(len(judgment["business_drivers"]))}
    links.update({f"/manual/scenarios/{i}/{driver}": f"{scenario['name']} {LABELS[driver]}"
                  for i, scenario in enumerate(payload["assumptions"]["scenarios"]) for driver in LABELS})
    for field in ("dependencies", "breakers"):
        links.update({f"/manual/thesis/monitoring_{field}/{i}": f"{field.title()}: {item['statement']}"
                      for i, item in enumerate(judgment["thesis"][field])})
    with evidence_section, st.expander("4. Evidence [Recommended]"):
        for field, label in (("supporting_evidence", "Supporting evidence"), ("disconfirming_evidence", "Disconfirming evidence")):
            with st.expander(label):
                judgment[field] = _evidence(original_judgment[field], field, f"{key}.{field}", links)
            if not judgment[field]:
                st.caption(f"No {label.lower()} recorded - recommended, not required.")
    return payload


def _context(inputs: UnderwritingInputs) -> None:
    with st.expander("OwnerLens Context - Facts, History & Consensus", expanded=False):
        st.caption(f"FMP-only input capture {inputs.captured_at}; underwriting as-of {inputs.as_of_date}. "
                   "Sources are persisted, not retrieved. Nothing here is copied into assumptions unless you apply a preset.")
        st.dataframe([{"FACT": item.name, "FY": item.fiscal_year, "Value": item.value,
                       "Missing": item.missing_reason} for item in inputs.starting_financial_state], hide_index=True)
        evidence = json.loads(inputs.evidence_json)
        price = evidence["eod_price"]
        if price["value"]:
            st.caption(f"Saved price FACT: {price['value']['close']} | {price['value']['market_date']}")
        else:
            st.warning(price["missing_reason"])
        snapshots = evidence["market_expectations"]["snapshots"]
        if not snapshots:
            st.info("No persisted consensus captured.")
        for item in snapshots:
            source = item["source"]
            window = estimate_window(item["rows"], period=source["period_type"], as_of=inputs.as_of_date)
            st.caption(f"EXPECTATION: {source['period_type']} | retrieved {source['fetched_at']} | {source['source_endpoint']}")
            if window["rows"]:
                st.dataframe([{field: row.get(field) for field in ("target_date", "revenue_average", "eps_average", "revenue_analyst_count")}
                              for row in window["rows"]], hide_index=True)
            for note in window["missing"]:
                st.info(note)


def _preview(payload: dict[str, Any], version: int) -> None:
    st.subheader(f"Review new underwriting v{version}")
    st.dataframe(payload["assumptions"]["scenarios"], hide_index=True)
    judgment = payload["judgments"]
    st.write("Probabilities [JUDGMENT]", judgment["probability_distribution"])
    st.write("Required return [JUDGMENT]", judgment["investor_policy"])
    st.write("Business drivers", [item["text"] for item in judgment["business_drivers"]])
    st.write("Variant rationale", [f"{item['driver']}: {item['text']}" for item in judgment["variant_rationales"]] or "N/A")
    st.write("Uncertainty", judgment["thesis"]["biggest_uncertainty"])
    st.write("Most important variable", judgment["thesis"]["most_important_variable"])
    st.write("Next evidence to collect", judgment["thesis"]["next_evidence_to_collect"])
    st.write(f"Evidence: {len(judgment['supporting_evidence'])} supporting / {len(judgment['disconfirming_evidence'])} disconfirming")
    for field in ("dependencies", "breakers"):
        st.write(field.title(), judgment["thesis"][field])
    with st.expander("Detailed beliefs and evidence review"):
        st.json(payload["judgments"])


def render(ticker: str, projection: UnderwritingProjection, source_factory: SourceFactory) -> None:
    state_key = "authoring." + ticker
    version = projection.record.version if projection.record else 0
    success = st.session_state.pop(state_key + ".success", None)
    if success:
        st.success(f"Created immutable underwriting v{success}. Status CAPTURED. Existing versions were not changed.")
    notice = st.session_state.pop(state_key + ".notice", None)
    if notice:
        st.success(notice)
    if st.button("Create New Underwriting", key=state_key + ".open"):
        st.session_state[state_key] = {"seed": empty_authoring(), "id": 1 + int(st.session_state.get(state_key + ".generation", 0))}
        st.session_state[state_key + ".generation"] = st.session_state[state_key]["id"]
        st.success(f"Draft created for {ticker} v{version + 1}. Nothing has been saved.")
    draft = st.session_state.get(state_key)
    if not draft:
        return
    st.warning(f"This will create underwriting v{version + 1}. Existing versions will not be changed.")
    st.caption("Draft only. No autosave. You supply ASSUMPTION and JUDGMENT; OwnerLens freezes FACT and EXPECTATION.")
    controls = st.columns(3)
    if controls[0].button("Discard draft", key=state_key + ".discard"):
        del st.session_state[state_key]
        st.session_state[state_key + ".notice"] = "Draft discarded. Returned to read-only underwriting."
        st.rerun()
    if projection.snapshot and controls[1].button("Start from latest underwriting", key=state_key + ".clone"):
        draft["seed"] = authoring_from_manual(projection.snapshot.manual)
        draft["id"] += 1
        draft.pop("review", None)
        st.session_state[state_key + ".generation"] = draft["id"]
        st.session_state[state_key + ".notice"] = f"Draft initialized from {ticker} v{version}. Saving will create v{version + 1}."
        st.rerun()
    prefix = state_key + f".draft.{draft['id']}"
    as_of = st.date_input("Underwriting as-of date", value=datetime.now(UTC).date(), key=prefix + ".asof")
    refresh = controls[2].button("Refresh draft evidence context", key=prefix + ".refresh")
    try:
        if "inputs" not in draft or refresh:
            with source_factory() as source:
                draft["inputs"] = capture_underwriting_inputs(source, ticker, as_of_date=as_of.isoformat())
            draft.pop("review", None)
            if refresh:
                st.success("Evidence context refreshed from persisted data. Nothing has been saved.")
        inputs: UnderwritingInputs = draft["inputs"]
        if inputs.as_of_date != as_of.isoformat():
            st.warning("As-of changed. Refresh draft evidence context before review.")
            return
        contexts = authoring_context(inputs)
        payload = _fields(draft["seed"], contexts, prefix)
        _context(inputs)
        with st.expander("Deterministic hints [Recommended; not investment judgment]", expanded=False):
            for hint in draft_hints(payload, contexts):
                st.info(hint + (" Recommended, not required." if hint.startswith("No ") else ""))
        fingerprint = compute_content_hash(json.dumps(payload, sort_keys=True).encode())
        if draft.get("review") and (draft["review"]["hash"] != fingerprint or draft["review"]["version"] != version):
            draft.pop("review")
            st.info("Draft or history changed. Review again before saving.")
        if st.button("Review Draft", key=prefix + ".review"):
            snapshot = review_authoring(payload, inputs)
            draft["review"] = {"snapshot": snapshot, "hash": fingerprint, "version": version}
        review = draft.get("review")
        if review:
            _preview(payload, version + 1)
            st.download_button("Export authoring JSON", json.dumps(payload, indent=2), file_name=ticker + "-authoring.json", mime="application/json")
            if st.button("Create Immutable Underwriting Version", key=prefix + ".save", type="primary"):
                with source_factory() as source:
                    record = save_underwriting_inputs(source, inputs, review["snapshot"].manual, expected_latest_version=review["version"])
                del st.session_state[state_key]
                st.session_state[state_key + ".success"] = record.version
                st.rerun()
        with st.expander("Optional JSON draft import"):
            upload = st.file_uploader("Import authoring JSON into a draft only", type=["json"], key=prefix + ".import")
            if st.button("Load JSON into draft", key=prefix + ".load", disabled=upload is None) and upload:
                draft["seed"] = authoring_from_manual(load_manual_json(upload.getvalue().decode("utf-8")))
                draft["id"] += 1
                draft.pop("review", None)
                st.session_state[state_key + ".generation"] = draft["id"]
                st.session_state[state_key + ".notice"] = "JSON loaded into draft. No immutable version was created."
                st.rerun()
    except (UnderwritingError, VariantError, PersistenceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        st.error(f"Underwriting draft could not be reviewed/saved: {exc}")

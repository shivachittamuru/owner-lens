"""Manual immutable outcome entry and descriptive scenario realization."""

from __future__ import annotations

import json

import streamlit as st

from owner_lens.decisions import load_decision_json
from owner_lens.opportunity_comparison import UnderwritingSelection
from owner_lens.outcomes import (
    DISCLAIMER,
    compare_outcomes,
    create_observation,
    format_observation,
)
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json
from owner_lens.workbench.views._common import frame


def render(store: SqliteStore) -> None:
    st.title("Outcomes")
    st.caption(DISCLAIMER)
    selections = {
        f"{record.ticker}:{record.version}": UnderwritingSelection(
            record.ticker, record.version
        )
        for security in store.list_securities()
        for record in store.list_underwriting(security.symbol)
    }
    selected = st.selectbox(
        "Exact underwriting version",
        list(selections),
        index=None,
        key="outcomes_version",
    )
    if not selected:
        st.info(
            "Select an exact completed underwriting version. No observations are fetched or manufactured."
        )
        return
    try:
        comparison = compare_outcomes(store, selections[selected])
    except (ValueError, PersistenceError) as exc:
        st.error(f"Outcome comparison could not be loaded: {exc}")
        return
    forecast = comparison["forecast"]
    st.write(
        f"Underwriting as-of: {forecast['as_of_date']} | frozen starting price: "
        f"{forecast['valuation']['current_price']} {forecast['valuation']['price_currency'] or '(currency missing)'} "
        f"on {forecast['valuation']['market_date']}"
    )
    st.caption(
        "FORECAST vs OUTCOME, not ASSESSMENT. Interim observations are not terminal forecast failures."
    )
    with st.expander("Frozen scenario definitions and thesis variables"):
        st.json(
            {
                "scenarios": forecast["valuation"]["scenarios"],
                "conditions": forecast["conditions"],
            }
        )
    st.caption(
        "Paste manually prepared observation JSON or upload a UTF-8 JSON file. "
        "FACT values require sources and manual verification. Recording does not create a change event."
    )
    with st.form("outcomes_create"):
        text = st.text_area("Outcome observation JSON", key="outcomes_input")
        uploaded = st.file_uploader(
            "Import observation JSON", type=["json"], key="outcomes_upload"
        )
        submitted = st.form_submit_button("Record immutable outcome observation")
    if submitted:
        try:
            if uploaded is not None and text.strip():
                raise ValueError("Use either pasted JSON or a file, not both.")
            payload = (
                uploaded.getvalue().decode("utf-8-sig")
                if uploaded is not None
                else text
            )
            observation = create_observation(
                store, selections[selected], load_decision_json(payload)
            )
            st.success(
                f"Recorded {observation['observation_id']}. No thesis, probability, decision or sizing changed."
            )
            comparison = compare_outcomes(store, selections[selected])
        except (ValueError, PersistenceError, UnicodeError, OverflowError) as exc:
            st.error(f"Outcome was not recorded: {exc}")
    st.subheader("Observed scenario resemblance")
    rows = []
    for report in comparison["observations"]:
        observation = report["observation"]
        market = report["market_outcome"]
        rows.append(
            {
                "Observation": observation["observation_date"],
                "Horizon": observation["horizon"],
                "Variable": "MARKET_OUTCOME",
                "Observed": canonical_json(market["observed"]),
                "Status": market["comparison"]["status"],
                "Nearest scenarios": ", ".join(
                    market["comparison"]["nearest_scenarios"]
                ),
                "Condition result": None,
                "Price return": market["total_price_return"],
                "Annualized price return": market["annualized_price_return"],
            }
        )
        for item in report["fundamental_outcomes"]:
            rows.append(
                {
                    "Observation": observation["observation_date"],
                    "Horizon": observation["horizon"],
                    "Variable": item["observed"]["forecast"]["id"],
                    "Observed": f"{item['observed']['value']} {item['observed']['unit']}",
                    "Status": item["status"],
                    "Nearest scenarios": ", ".join(item["nearest_scenarios"]),
                    "Condition result": item.get("condition_status"),
                    "Price return": None,
                    "Annualized price return": None,
                }
            )
    if rows:
        st.dataframe(frame(rows), width="stretch", hide_index=True)
    else:
        st.info("No outcomes recorded for this exact version.")
    st.write("Missing observations (not assumed neutral)")
    st.json(comparison["missing_observations"])
    for report in comparison["observations"]:
        with st.expander(
            f"{report['observation']['observation_date']} | {report['observation_id']}"
        ):
            st.text(format_observation(report))
            st.json(json.loads(canonical_json(report)))
    st.download_button(
        "Download forecast vs outcomes JSON",
        canonical_json(comparison),
        file_name=f"outcomes-{selected.replace(':', '-v')}.json",
        mime="application/json",
    )

"""Sample-guarded, descriptive forecast calibration without decision assessment."""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from owner_lens.calibration import DISCLAIMER, build_report, read_report
from owner_lens.persistence import SqliteStore
from owner_lens.persistence.errors import PersistenceError
from owner_lens.position_sizing import canonical_json
from owner_lens.workbench.views._common import frame


def render(store: SqliteStore) -> None:
    st.title("Calibration")
    st.caption(DISCLAIMER)
    as_of = st.date_input(
        "Calibration as-of (UTC)",
        value=datetime.now(UTC).date(),
        key="calibration_as_of",
    )
    companies = [item.symbol for item in store.list_securities()]
    company = st.selectbox(
        "Company cohort (optional)", companies, index=None, key="calibration_company"
    )
    try:
        report = build_report(store, as_of=as_of.isoformat(), company=company)
        st.write("Status: " + report["status"])
        st.write(
            f"Eligible forecasts: {report['eligible_sample_count']} | eligible metric pairs: "
            f"{report['eligible_pair_count']} | excluded pairs: {report['excluded_sample_count']}"
        )
        st.caption(f"Horizon: {report['horizon_type']} | dates: {report['date_range']}")
        if report["status"] != "CALIBRATION_AVAILABLE":
            st.warning(
                "Low sample size: "
                + report["status"]
                + ". No strong conclusions are supported."
            )
        probability = report["probability_calibration"]
        if probability["status"] != "CALIBRATION_AVAILABLE":
            st.warning(
                "Probability calibration: "
                + probability["status"]
                + ". Its sample guard is independent of the overall count."
            )
        st.subheader("Scenario-probability calibration")
        st.write(
            f"{probability['status']} | unambiguous: {probability['eligible_sample_count']} | "
            f"ambiguous: {probability['ambiguous_count']}"
        )
        st.caption(
            "Terminal market regions only. Between-anchor outcomes are excluded from Brier/frequency denominators."
        )
        if probability["scenario_frequency"]:
            st.dataframe(
                frame(probability["scenario_frequency"]),
                width="stretch",
                hide_index=True,
            )
        st.write(
            f"Mean Brier (unnormalized three-class sum): {probability['mean_brier']}"
        )
        if probability["buckets"]:
            st.dataframe(
                frame(probability["buckets"]), width="stretch", hide_index=True
            )
        st.subheader("Continuous Base forecast errors")
        summaries = [
            {key: value for key, value in item.items() if key != "raw_errors"}
            for item in report["continuous_forecast_errors"]
        ]
        if summaries:
            st.dataframe(frame(summaries), width="stretch", hide_index=True)
        else:
            st.info(
                "No eligible continuous measurements. Missing outcomes are not assumed neutral."
            )
        st.subheader("Simple cohorts")
        st.dataframe(
            frame(
                [
                    {
                        key: item[key]
                        for key in (
                            "dimension",
                            "value",
                            "eligible_sample_count",
                            "status",
                            "suppressed",
                        )
                    }
                    for item in report["cohorts"]
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        with st.expander(
            "Exact pair links, exclusions, raw errors/scores and cohort details"
        ):
            st.json(report)
        if st.button("Save immutable calibration report", key="calibration_save"):
            store.save_calibration_report(canonical_json(report))
            st.success("Saved calibration report " + report["report_id"])
        st.download_button(
            "Download calibration JSON",
            canonical_json(report),
            file_name=f"calibration-{report['report_id']}.json",
            mime="application/json",
        )
        saved = st.text_input("Saved report ID", key="calibration_report_id")
        if saved:
            st.json(read_report(store, saved))
    except (ValueError, PersistenceError, OverflowError) as exc:
        st.error(f"Calibration could not be loaded or saved: {exc}")

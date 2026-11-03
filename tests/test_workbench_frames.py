"""Presentation frames retain numeric nulls without losing coverage semantics."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pyarrow as pa
import pytest

from owner_lens.workbench.views._common import frame


def test_numeric_evidence_and_other_nullable_columns_serialize_to_arrow() -> None:
    rows = [
        {
            "cashAndCashEquivalents": 123.5,
            "revenue": 1000,
            "Latest FY": 2025,
            "Price return": 0.12,
            "Status": "AVAILABLE",
        },
        {
            "cashAndCashEquivalents": None,
            "revenue": None,
            "Latest FY": None,
            "Price return": None,
            "Status": "UNSUPPORTED",
        },
        {"Status": "INVALID"},
        {"Status": "STRUCTURALLY_ABSENT"},
    ]
    original = deepcopy(rows)
    table = frame(rows)
    arrow = pa.Table.from_pandas(table)

    for column in ("cashAndCashEquivalents", "revenue", "Latest FY", "Price return"):
        assert pd.api.types.is_numeric_dtype(table[column])
        assert arrow[column].null_count == 3
        assert arrow[column][0].as_py() == rows[0][column]
        assert "N/A" not in table[column].dropna().tolist()
    assert arrow["Status"].to_pylist() == [row["Status"] for row in rows]
    assert rows == original


def test_text_missing_values_and_index_remain_display_labels() -> None:
    table = frame([
        {"Metric": "Cash", "Reason": None},
        {"Metric": "Debt", "Reason": "Unsupported by provider"},
    ], index="Metric")
    assert list(table.index) == ["Cash", "Debt"]
    assert table.loc["Cash", "Reason"] == "N/A"
    assert table.loc["Debt", "Reason"] == "Unsupported by provider"
    pa.Table.from_pandas(table)


def test_malformed_numeric_fact_is_not_silently_discarded() -> None:
    rows = [{"cashAndCashEquivalents": 123.5}, {"cashAndCashEquivalents": "broken"}]
    table = frame(rows)
    assert table.loc[1, "cashAndCashEquivalents"] == "broken"
    with pytest.raises(pa.ArrowInvalid, match="broken"):
        pa.Table.from_pandas(table)


def test_empty_frame_remains_empty() -> None:
    table = frame([], index="Metric")
    assert table.empty
    pa.Table.from_pandas(table)


def test_all_missing_column_stays_null_and_boolean_flag_stays_typed() -> None:
    table = frame([
        {"cashAndCashEquivalents": None, "Verified": True},
        {"cashAndCashEquivalents": None, "Verified": None},
    ])
    arrow = pa.Table.from_pandas(table)
    assert arrow["cashAndCashEquivalents"].null_count == 2
    assert arrow["Verified"].to_pylist() == [True, None]
    assert pa.types.is_boolean(arrow["Verified"].type)


def test_numeric_na_display_styling_does_not_change_arrow_data() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
import streamlit as st
from owner_lens.workbench.views._common import frame
table = frame([
    {"cashAndCashEquivalents": 123.5},
    {"cashAndCashEquivalents": None},
])
st.dataframe(table.style.format(na_rep="N/A"))
""").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert pd.api.types.is_numeric_dtype(table["cashAndCashEquivalents"])
    assert pd.isna(table.loc[1, "cashAndCashEquivalents"])
    assert pa.Table.from_pandas(table)["cashAndCashEquivalents"].null_count == 1
    assert "N/A" in table.style.format(na_rep="N/A").to_html()

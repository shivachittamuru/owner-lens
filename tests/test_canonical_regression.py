"""Characterization test freezing SEC-derived OwnerLens outputs (Slice 5A).

The baseline in ``tests/data/canonical_baseline.json`` was captured from the
pre-canonical code path. Every downstream refactor must reproduce it exactly:
entry-point results (or exception type and message), persistence records, and
formatted views. Regenerate only deliberately with::

    uv run python tests/test_canonical_regression.py --update-baseline
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Callable
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens.capital_allocation import (
    capital_allocation_from_facts,
    format_capital_allocation_view,
)
from owner_lens.capital_efficiency import capital_efficiency_from_facts
from owner_lens.compounding import (
    compounding_views_from_facts,
    format_compounding_view,
)
from owner_lens.coverage import (
    company_coverage,
    company_output,
    format_coverage_report,
)
from owner_lens.economic_summary import (
    economic_value_summary_from_facts,
    format_economic_value_summary,
)
from owner_lens.economic_value import (
    economic_value_from_facts,
    format_economic_value_view,
)
from owner_lens.owner_economics import owner_economics_from_facts
from owner_lens.persistence.adapters import (
    analysis_result_records,
    coverage_result_records,
    derived_metric_records,
    reported_fact_records,
)

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "canonical_baseline.json"
_CIK = "0000000000"
_COMPUTED_AT = "2026-01-01T00:00:00+00:00"


def _adbe_without_current_debt() -> dict[str, Any]:
    facts = adbe_facts()
    del facts["facts"]["us-gaap"]["DebtCurrent"]
    return facts


def _adbe_ambiguous_repurchases() -> dict[str, Any]:
    facts = adbe_facts()
    entries = facts["facts"]["us-gaap"]["PaymentsForRepurchaseOfCommonStock"]["units"]["USD"]
    latest = dict(max(entries, key=lambda e: e["end"]))
    latest["val"] = latest["val"] + 1_000_000
    latest["filed"] = "2026-03-01"
    latest["accn"] = "conflicting-restatement"
    entries.append(latest)
    return facts


SCENARIOS: dict[str, tuple[Callable[[], dict[str, Any]], str]] = {
    "ADBE": (adbe_facts, "ADBE"),
    "V": (visa_facts, "V"),
    "COST": (costco_facts, "COST"),
    "ADBE_NO_CURRENT_DEBT": (_adbe_without_current_debt, "ADBE"),
    "ADBE_AMBIGUOUS_REPURCHASES": (_adbe_ambiguous_repurchases, "ADBE"),
}


def _is_reported_fact(obj: Any) -> bool:
    if hasattr(obj, "canonical_metric"):
        return False  # persistence records are serialized verbatim
    return all(hasattr(obj, name) for name in ("value", "fiscal_year", "accession", "filed"))


def _serialize(obj: Any) -> Any:
    """Convert outputs to JSON primitives, projecting reported facts provider-neutrally."""
    if _is_reported_fact(obj):
        source_field = getattr(obj, "provider_field", None) or getattr(obj, "concept", None)
        return {
            "value": obj.value,
            "unit": obj.unit,
            "fiscal_year": obj.fiscal_year,
            "period_end": obj.period_end.isoformat(),
            "form": obj.form,
            "filed": obj.filed.isoformat(),
            "accession": obj.accession,
            "source_field": source_field,
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _serialize(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return obj


def _run(fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - the exception itself is the recorded outcome
        return None, {"error": [type(exc).__name__, str(exc)]}
    return result, {"ok": _serialize(result)}


def capture(raw_facts: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Record every entry-point outcome, persistence record, and formatted view."""
    out: dict[str, Any] = {}
    owner, out["owner_economics"] = _run(
        lambda: owner_economics_from_facts(raw_facts, ticker=ticker)
    )
    capital, out["capital_efficiency"] = _run(
        lambda: capital_efficiency_from_facts(raw_facts, ticker=ticker)
    )
    snapshots, out["economic_value"] = _run(
        lambda: economic_value_from_facts(raw_facts, ticker=ticker)
    )
    views, out["compounding"] = _run(
        lambda: compounding_views_from_facts(raw_facts, ticker=ticker)
    )
    allocation, out["capital_allocation"] = _run(
        lambda: capital_allocation_from_facts(raw_facts, ticker=ticker)
    )
    summary, out["economic_summary"] = _run(
        lambda: economic_value_summary_from_facts(raw_facts, ticker=ticker)
    )
    coverage, out["coverage"] = _run(lambda: company_coverage(raw_facts, ticker=ticker))

    owner_rows = owner or ()
    capital_rows = capital or ()
    records: dict[str, Any] = {
        "reported_facts": reported_fact_records(_CIK, owner_rows, capital_rows),
        "derived_metrics": derived_metric_records(
            _CIK, owner_rows, capital_rows, computed_at=_COMPUTED_AT
        ),
        "analyses": analysis_result_records(
            _CIK,
            annual_snapshots=snapshots or (),
            compounding_views=views or (),
            capital_allocation_rows=allocation or (),
            summary=summary,
            computed_at=_COMPUTED_AT,
        ),
    }
    if coverage is not None:
        records["coverage"] = coverage_result_records(_CIK, coverage)
    out["records"] = _serialize(records)

    views_text: dict[str, str] = {}
    if snapshots is not None:
        views_text["economic_value"] = format_economic_value_view(snapshots)
    if views is not None:
        views_text["compounding"] = "\n\n".join(format_compounding_view(v) for v in views)
    if allocation is not None:
        views_text["capital_allocation"] = format_capital_allocation_view(allocation)
    if summary is not None:
        views_text["economic_summary"] = format_economic_value_summary(summary)
    if coverage is not None:
        views_text["coverage_report"] = format_coverage_report([coverage])
        _, output = _run(lambda: company_output(coverage, raw_facts, ticker=ticker))
        views_text["company_output"] = output.get("ok") or json.dumps(output)
    out["views"] = views_text
    return out


def capture_all() -> dict[str, Any]:
    return {name: capture(build(), ticker) for name, (build, ticker) in SCENARIOS.items()}


def test_outputs_match_pre_canonical_baseline() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(capture_all()))
    assert set(current) == set(baseline)
    for name in SCENARIOS:
        assert current[name] == baseline[name], f"scenario {name} diverged from baseline"


if __name__ == "__main__" and "--update-baseline" in sys.argv:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(capture_all(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {BASELINE_PATH}")

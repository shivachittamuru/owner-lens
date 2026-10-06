"""Architecture test: downstream OwnerLens logic must not depend on SEC (Slice 5A).

The seven analytical modules may import only the canonical model, the shared
trajectory helper, each other, and exactly one SEC-side symbol
(``canonical_history_from_sec``) used solely by the legacy ``*_from_facts``
compatibility wrappers. No SEC XBRL concept name may appear in their source.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import owner_lens.metrics as sec_metrics
from owner_lens import (
    capital_allocation,
    capital_efficiency,
    compounding,
    coverage,
    economic_summary,
    economic_value,
    owner_economics,
)
from owner_lens.canonical import CanonicalFinancialHistory

SRC = Path(__file__).resolve().parents[1] / "src" / "owner_lens"
DOWNSTREAM = (
    "owner_economics",
    "capital_efficiency",
    "economic_value",
    "compounding",
    "capital_allocation",
    "economic_summary",
    "coverage",
)
ALLOWED_INTERNAL = {"owner_lens.canonical", "owner_lens._trajectory"} | {
    f"owner_lens.{name}" for name in DOWNSTREAM
}
ADAPTER_MODULE = "owner_lens.sec_adapter"
ADAPTER_SYMBOL = "canonical_history_from_sec"
WRAPPERS = {"company_coverage", "company_output"}
MODULES = {
    "owner_economics": owner_economics,
    "capital_efficiency": capital_efficiency,
    "economic_value": economic_value,
    "compounding": compounding,
    "capital_allocation": capital_allocation,
    "economic_summary": economic_summary,
    "coverage": coverage,
}


def _tree(name: str) -> ast.Module:
    return ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))


def _sec_concepts() -> set[str]:
    concepts: set[str] = set()
    for value in vars(sec_metrics).values():
        if isinstance(value, sec_metrics.CanonicalMetricDefinition):
            concepts.update(value.default_concepts)
            for override in value.overrides.values():
                concepts.update(override)
    return concepts


@pytest.mark.parametrize("name", DOWNSTREAM)
def test_downstream_imports_only_canonical_side(name: str) -> None:
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("owner_lens"), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            "owner_lens"
        ):
            if node.module == ADAPTER_MODULE:
                assert [a.name for a in node.names] == [ADAPTER_SYMBOL]
            else:
                assert node.module in ALLOWED_INTERNAL, f"{name} imports {node.module}"


@pytest.mark.parametrize("name", DOWNSTREAM)
def test_sec_adapter_used_only_by_compatibility_wrappers(name: str) -> None:
    for func in ast.walk(_tree(name)):
        if not isinstance(func, ast.FunctionDef):
            continue
        uses_adapter = any(
            isinstance(n, ast.Name) and n.id == ADAPTER_SYMBOL for n in ast.walk(func)
        )
        if uses_adapter:
            assert func.name.endswith("_from_facts") or func.name in WRAPPERS, func.name


@pytest.mark.parametrize("name", DOWNSTREAM)
def test_no_sec_concept_names_downstream(name: str) -> None:
    concepts = _sec_concepts()
    assert "Revenues" in concepts and "LongTermDebtCurrent" in concepts
    literals = {
        node.value
        for node in ast.walk(_tree(name))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not literals & concepts


@pytest.mark.parametrize("name", DOWNSTREAM)
def test_history_entry_points_accept_only_canonical_history(name: str) -> None:
    module = MODULES[name]
    entry_points = [
        fn
        for attr, fn in vars(module).items()
        if attr.endswith("_from_history") and inspect.isfunction(fn)
        and fn.__module__ == module.__name__
    ]
    assert entry_points, f"{name} exposes no *_from_history entry point"
    for fn in entry_points:
        params = list(inspect.signature(fn, eval_str=True).parameters.values())
        history_params = [p for p in params if p.annotation is CanonicalFinancialHistory]
        assert len(history_params) == 1, fn.__name__
        assert all(
            p.name in {"history", "coverage", "thresholds", "period_years"} for p in params
        ), fn.__name__


def test_reconciliation_is_provider_neutral() -> None:
    """Reconciliation compares canonical histories; it must not import provider code."""
    tree = ast.parse((SRC / "reconciliation.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            "owner_lens"
        ):
            assert node.module in ALLOWED_INTERNAL, f"reconciliation imports {node.module}"
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("owner_lens") for a in node.names)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not literals & _sec_concepts()

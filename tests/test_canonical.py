"""Tests for the provider-neutral canonical financial model (Slice 5A)."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from owner_lens.canonical import (
    CANONICAL_METRICS,
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalSeries,
    MetricInvalidError,
    MetricKind,
    MetricStatus,
    MetricUnsupportedError,
    metric_spec,
)


def _fact(metric: str = "revenue", year: int = 2025, value: int = 100, **overrides: object) -> CanonicalFact:
    spec = metric_spec(metric)
    fields: dict[str, object] = {
        "metric": metric,
        "value": value,
        "unit": spec.unit,
        "fiscal_year": year,
        "fiscal_period": "FY",
        "period_end": date(year, 12, 31),
        "period_start": date(year, 1, 1) if spec.kind is MetricKind.DURATION else None,
        "provider": "test",
        "provider_field": f"test.{metric}",
        "form": "10-K",
        "filed": date(year + 1, 2, 1),
        "accession": f"{metric}-{year}",
    }
    fields.update(overrides)
    return CanonicalFact(**fields)  # type: ignore[arg-type]


def _all_facts(year: int = 2025) -> list[CanonicalFact]:
    return [_fact(spec.name, year) for spec in CANONICAL_METRICS]


def test_vocabulary_is_the_seventeen_owner_lens_metrics() -> None:
    names = [spec.name for spec in CANONICAL_METRICS]
    assert len(names) == 17
    assert names[0] == "revenue" and names[-1] == "total_equity"
    assert metric_spec("diluted_shares").unit == "shares"
    assert metric_spec("cash").kind is MetricKind.INSTANT
    with pytest.raises(KeyError):
        metric_spec("Revenues")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"unit": "EUR"}, "requires unit"),
        ({"period_start": None}, "requires a period start"),
        ({"period_start": date(2026, 1, 1)}, "must precede"),
        ({"provider": ""}, "requires a provider"),
        ({"provider_field": ""}, "requires a provider field"),
    ],
)
def test_fact_validation_fails_loudly(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _fact(**overrides)


def test_fact_rejects_unknown_metric() -> None:
    valid = _fact()
    with pytest.raises(ValueError, match="Unknown canonical metric"):
        dataclasses.replace(valid, metric="ebitda")


def test_instant_fact_has_no_period_start() -> None:
    assert _fact("cash").period_start is None
    with pytest.raises(ValueError, match="must not have a period start"):
        _fact("cash", period_start=date(2025, 1, 1))


def test_fact_is_immutable() -> None:
    fact = _fact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.value = 1  # type: ignore[misc]


def test_series_status_invariants() -> None:
    with pytest.raises(ValueError, match="requires facts"):
        CanonicalSeries("revenue", "USD", MetricStatus.AVAILABLE)
    with pytest.raises(ValueError, match="must have no facts"):
        CanonicalSeries("revenue", "USD", MetricStatus.UNSUPPORTED, (_fact(),), reason="x")
    with pytest.raises(ValueError, match="requires a reason"):
        CanonicalSeries("revenue", "USD", MetricStatus.UNSUPPORTED)
    with pytest.raises(ValueError, match="requires an error"):
        CanonicalSeries("revenue", "USD", MetricStatus.INVALID, reason="bad")
    with pytest.raises(ValueError, match="has an error"):
        CanonicalSeries(
            "dividends_paid",
            "USD",
            MetricStatus.STRUCTURALLY_ABSENT,
            error=MetricUnsupportedError("x"),
        )


def test_series_ordering_and_uniqueness() -> None:
    with pytest.raises(ValueError, match="newest first"):
        CanonicalSeries(
            "revenue", "USD", MetricStatus.AVAILABLE, (_fact(year=2024), _fact(year=2025))
        )
    with pytest.raises(ValueError, match="duplicate"):
        CanonicalSeries("revenue", "USD", MetricStatus.AVAILABLE, (_fact(), _fact()))
    with pytest.raises(ValueError, match="another metric"):
        CanonicalSeries("revenue", "USD", MetricStatus.AVAILABLE, (_fact("net_income"),))


def test_build_groups_and_sorts_facts() -> None:
    facts = _all_facts(2024) + _all_facts(2025)
    history = CanonicalFinancialHistory.build(ticker="TEST", max_years=5, facts=facts)
    revenue = history.series_for("revenue")
    assert [f.fiscal_year for f in revenue.observations] == [2025, 2024]
    assert set(history.statuses().values()) == {MetricStatus.AVAILABLE}
    assert history.providers() == frozenset({"test"})


def test_build_rejects_undeclared_gap() -> None:
    facts = [f for f in _all_facts() if f.metric != "dividends_paid"]
    with pytest.raises(ValueError, match="dividends_paid has no facts"):
        CanonicalFinancialHistory.build(ticker="TEST", max_years=5, facts=facts)


def test_history_requires_complete_ordered_vocabulary() -> None:
    history = CanonicalFinancialHistory.build(ticker="TEST", max_years=5, facts=_all_facts())
    with pytest.raises(ValueError, match="exactly one series"):
        CanonicalFinancialHistory("TEST", 5, history.series[:-1])
    with pytest.raises(ValueError, match="uppercase ticker"):
        CanonicalFinancialHistory("test", 5, history.series)
    with pytest.raises(ValueError, match="max_years"):
        CanonicalFinancialHistory("TEST", 0, history.series)


def _history_with(metric: str, series: CanonicalSeries) -> CanonicalFinancialHistory:
    base = CanonicalFinancialHistory.build(
        ticker="TEST", max_years=5, facts=[f for f in _all_facts() if f.metric != metric],
        unsupported={metric: "placeholder"},
    )
    replaced = tuple(series if s.metric == metric else s for s in base.series)
    return CanonicalFinancialHistory("TEST", 5, replaced)


def test_require_semantics_for_each_status() -> None:
    history = CanonicalFinancialHistory.build(
        ticker="TEST",
        max_years=5,
        facts=[f for f in _all_facts() if f.metric not in ("dividends_paid", "diluted_shares")],
        structurally_absent=("dividends_paid",),
        unsupported={"diluted_shares": "no diluted share field"},
    )
    assert history.require("revenue").status is MetricStatus.AVAILABLE
    assert history.require("dividends_paid").observations == ()
    with pytest.raises(MetricUnsupportedError, match="no diluted share field"):
        history.require("diluted_shares")
    tolerated = history.require("diluted_shares", allow_unsupported=True)
    assert tolerated.status is MetricStatus.UNSUPPORTED and tolerated.observations == ()


def test_require_reraises_the_stored_provider_error() -> None:
    stored = MetricInvalidError("FY2025 has conflicting values")
    series = CanonicalSeries(
        "repurchases", "USD", MetricStatus.INVALID, reason=str(stored), error=stored
    )
    history = _history_with("repurchases", series)
    for _ in range(2):
        with pytest.raises(MetricInvalidError) as info:
            history.require("repurchases", allow_unsupported=True)
        assert info.value is stored
        assert str(info.value) == "FY2025 has conflicting values"


def test_require_reraises_stored_unsupported_error() -> None:
    stored = MetricUnsupportedError("No supported concept")
    series = CanonicalSeries(
        "current_debt", "USD", MetricStatus.UNSUPPORTED, reason=str(stored), error=stored
    )
    history = _history_with("current_debt", series)
    with pytest.raises(MetricUnsupportedError) as info:
        history.require("current_debt")
    assert info.value is stored

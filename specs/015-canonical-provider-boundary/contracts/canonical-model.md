---
title: "Contract: Canonical Model"
description: Public API of owner_lens.canonical, the provider-neutral boundary for OwnerLens Slice 5A
ms.date: 2026-10-05
ms.topic: reference
---

## Module

`owner_lens.canonical`. This module has no imports from SEC modules, persistence, or downstream
analytical modules.

## Public names

```python
__all__ = [
    "CANONICAL_METRICS",
    "CanonicalDataError",
    "CanonicalFact",
    "CanonicalFinancialHistory",
    "CanonicalMetricSpec",
    "CanonicalSeries",
    "MetricInvalidError",
    "MetricKind",
    "MetricStatus",
    "MetricUnsupportedError",
    "metric_spec",
]
```

`metric_spec(name: str) -> CanonicalMetricSpec` raises `KeyError` for a name outside the
vocabulary.

## Signatures

```python
@dataclass(frozen=True)
class CanonicalFact:
    metric: str
    value: int
    unit: str
    fiscal_year: int
    fiscal_period: str
    period_end: date
    period_start: date | None
    provider: str
    provider_field: str
    form: str
    filed: date
    accession: str

@dataclass(frozen=True)
class CanonicalSeries:
    metric: str
    unit: str
    status: MetricStatus
    observations: tuple[CanonicalFact, ...] = ()
    reason: str | None = None
    error: CanonicalDataError | None = None

@dataclass(frozen=True)
class CanonicalFinancialHistory:
    ticker: str
    max_years: int
    series: tuple[CanonicalSeries, ...]

    def series_for(self, metric: str) -> CanonicalSeries: ...
    def require(self, metric: str, *, allow_unsupported: bool = False) -> CanonicalSeries: ...
    def statuses(self) -> dict[str, MetricStatus]: ...
    def providers(self) -> frozenset[str]: ...

    @classmethod
    def build(
        cls,
        *,
        ticker: str,
        max_years: int,
        facts: Iterable[CanonicalFact],
        structurally_absent: Iterable[str] = (),
        unsupported: Mapping[str, str] | None = None,
    ) -> CanonicalFinancialHistory: ...
```

## Behavioral guarantees

1. **Immutable**: All instances are frozen. Every collection is a tuple.
2. **Complete**: A history holds exactly one series per vocabulary metric. A metric is never
   silently missing.
3. **Fail loudly**: `require` raises for `INVALID`. It raises for `UNSUPPORTED` unless
   `allow_unsupported=True`. When the series holds a stored provider error, that exact error object
   is raised, with its type and message unchanged.
4. **No fabrication**: An absent or unsupported metric has no facts. The model never substitutes a
   zero.
5. **Provider-neutral**: No field, method, or constant refers to SEC, XBRL, or a taxonomy. The
   provider identity appears only as data: `CanonicalFact.provider` and `provider_field`.
6. **Deterministic**: Building from the same facts produces an equal history. Series and
   observation ordering is canonical: vocabulary order, then descending fiscal year.

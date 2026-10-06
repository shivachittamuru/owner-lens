"""Provider-neutral canonical financial history for OwnerLens.

This module is the boundary between data providers and OwnerLens economics.
Provider adapters (SEC today) translate their payloads into a
``CanonicalFinancialHistory``; every downstream deterministic calculation reads
only these types. Nothing here knows about SEC, XBRL, or any taxonomy: provider
identity survives only as provenance data on each ``CanonicalFact``.

Each metric carries an explicit ``MetricStatus``. Provider failures are stored on
the metric's series rather than raised during mapping, and are re-raised only
when a calculation requires that metric. This keeps failure lazy and
per-layer: an ambiguous repurchases fact blocks capital allocation without
blocking owner economics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final

__all__ = [
    "CANONICAL_METRICS",
    "CanonicalDataError",
    "CanonicalFact",
    "CanonicalFinancialHistory",
    "CanonicalMetricSpec",
    "CanonicalSeries",
    "ConflictResolution",
    "ConflictResolutionKind",
    "MetricInvalidError",
    "MetricKind",
    "MetricStatus",
    "MetricUnsupportedError",
    "SupersededValue",
    "metric_spec",
]

USD: Final = "USD"
SHARES: Final = "shares"


class MetricKind(Enum):
    """Whether a metric is a fiscal-period duration or a fiscal-year-end instant."""

    DURATION = "duration"
    INSTANT = "instant"


class MetricStatus(Enum):
    """Availability of one canonical metric in a financial history."""

    AVAILABLE = "AVAILABLE"
    STRUCTURALLY_ABSENT = "STRUCTURALLY_ABSENT"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


class CanonicalDataError(Exception):
    """Base class for provider-neutral financial-data failures."""


class MetricUnsupportedError(CanonicalDataError):
    """Raised when a required metric has no trusted provider field."""


class MetricInvalidError(CanonicalDataError):
    """Raised when provider data for a metric is malformed or ambiguous."""


@dataclass(frozen=True)
class CanonicalMetricSpec:
    """One entry of the fixed OwnerLens canonical metric vocabulary."""

    name: str
    kind: MetricKind
    unit: str


CANONICAL_METRICS: Final[tuple[CanonicalMetricSpec, ...]] = (
    CanonicalMetricSpec("revenue", MetricKind.DURATION, USD),
    CanonicalMetricSpec("operating_income", MetricKind.DURATION, USD),
    CanonicalMetricSpec("net_income", MetricKind.DURATION, USD),
    CanonicalMetricSpec("operating_cash_flow", MetricKind.DURATION, USD),
    CanonicalMetricSpec("capital_expenditures", MetricKind.DURATION, USD),
    CanonicalMetricSpec("diluted_shares", MetricKind.DURATION, SHARES),
    CanonicalMetricSpec("income_tax_expense", MetricKind.DURATION, USD),
    CanonicalMetricSpec("pretax_income", MetricKind.DURATION, USD),
    CanonicalMetricSpec("repurchases", MetricKind.DURATION, USD),
    CanonicalMetricSpec("stock_based_compensation", MetricKind.DURATION, USD),
    CanonicalMetricSpec("dividends_paid", MetricKind.DURATION, USD),
    CanonicalMetricSpec("cash", MetricKind.INSTANT, USD),
    CanonicalMetricSpec("short_term_investments", MetricKind.INSTANT, USD),
    CanonicalMetricSpec("current_debt", MetricKind.INSTANT, USD),
    CanonicalMetricSpec("long_term_debt", MetricKind.INSTANT, USD),
    CanonicalMetricSpec("total_assets", MetricKind.INSTANT, USD),
    CanonicalMetricSpec("total_equity", MetricKind.INSTANT, USD),
)

_SPECS: Final = {spec.name: spec for spec in CANONICAL_METRICS}
_ORDER: Final = tuple(spec.name for spec in CANONICAL_METRICS)


def metric_spec(name: str) -> CanonicalMetricSpec:
    """Return the vocabulary spec for a canonical metric name."""
    try:
        return _SPECS[name]
    except KeyError:
        raise KeyError(f"Unknown canonical metric: {name!r}.") from None


class ConflictResolutionKind(Enum):
    """How a same-year conflict between reported values was resolved."""

    PRECISION = "PRECISION"
    STOCK_SPLIT = "STOCK_SPLIT"


@dataclass(frozen=True)
class SupersededValue:
    """A conflicting reported value that a resolution set aside (kept for audit)."""

    value: int
    form: str | None
    filed: date | None
    accession: str | None
    split_factor: int = 1


@dataclass(frozen=True)
class ConflictResolution:
    """Why a canonical value was chosen among conflicting reports for one year.

    ``reported_value`` is the value exactly as filed in the fact's own source
    filing. ``split_factor`` is the cumulative stock-split factor applied to it,
    so the canonical value equals ``reported_value * split_factor``; a factor of
    1 means the canonical value was reported verbatim. ``superseded`` lists every
    other distinct reported value for the year, so nothing is discarded silently.
    """

    kind: ConflictResolutionKind
    reported_value: int
    split_factor: int
    superseded: tuple[SupersededValue, ...]

    def __post_init__(self) -> None:
        if self.split_factor < 1:
            raise ValueError("A split factor must be a positive integer.")


@dataclass(frozen=True)
class CanonicalFact:
    """One reported annual value for one canonical metric, with source provenance.

    Sign convention: cash outflows (``capital_expenditures``, ``repurchases``,
    ``dividends_paid``) are positive magnitudes; adapters normalize providers that
    report them as negative numbers.

    Provenance fields a provider does not supply stay ``None`` rather than being
    fabricated: ``period_start`` (duration facts only), ``form``, ``filed``, and
    ``accession``. SEC supplies all of them.

    ``resolution`` is set only when the provider reported conflicting values for
    the year and a deterministic rule (re-rounding or stock-split restatement)
    chose this one; it records the as-filed value, any split factor applied, and
    the superseded values.
    """

    metric: str
    value: int
    unit: str
    fiscal_year: int
    fiscal_period: str
    period_end: date
    period_start: date | None
    provider: str
    provider_field: str
    form: str | None
    filed: date | None
    accession: str | None
    resolution: ConflictResolution | None = None

    def __post_init__(self) -> None:
        if self.metric not in _SPECS:
            raise ValueError(f"Unknown canonical metric: {self.metric!r}.")
        spec = _SPECS[self.metric]
        if self.unit != spec.unit:
            raise ValueError(
                f"{self.metric} requires unit {spec.unit!r}, got {self.unit!r}."
            )
        if spec.kind is MetricKind.DURATION:
            if self.period_start is not None and self.period_start >= self.period_end:
                raise ValueError(
                    f"{self.metric} period start must precede period end."
                )
        elif self.period_start is not None:
            raise ValueError(f"Instant metric {self.metric} must not have a period start.")
        if not self.provider:
            raise ValueError("A canonical fact requires a provider.")
        if not self.provider_field:
            raise ValueError("A canonical fact requires a provider field.")


@dataclass(frozen=True)
class CanonicalSeries:
    """All canonical facts for one metric, newest fiscal year first, plus its status."""

    metric: str
    unit: str
    status: MetricStatus
    observations: tuple[CanonicalFact, ...] = ()
    reason: str | None = None
    error: CanonicalDataError | None = None

    def __post_init__(self) -> None:
        spec = metric_spec(self.metric)
        if self.unit != spec.unit:
            raise ValueError(f"{self.metric} requires unit {spec.unit!r}.")
        years = [fact.fiscal_year for fact in self.observations]
        if any(fact.metric != self.metric for fact in self.observations):
            raise ValueError(f"Series {self.metric} contains a fact for another metric.")
        if len(set(years)) != len(years):
            raise ValueError(f"Series {self.metric} has duplicate fiscal years.")
        if years != sorted(years, reverse=True):
            raise ValueError(f"Series {self.metric} must be ordered newest first.")

        if self.status is MetricStatus.AVAILABLE:
            if not self.observations:
                raise ValueError(f"AVAILABLE series {self.metric} requires facts.")
        elif self.observations:
            raise ValueError(f"{self.status.value} series {self.metric} must have no facts.")
        if (
            self.status in (MetricStatus.AVAILABLE, MetricStatus.STRUCTURALLY_ABSENT)
            and self.error is not None
        ):
            raise ValueError(f"{self.status.value} series {self.metric} has an error.")
        if self.status in (MetricStatus.UNSUPPORTED, MetricStatus.INVALID) and not self.reason:
            raise ValueError(f"{self.status.value} series {self.metric} requires a reason.")
        if self.status is MetricStatus.INVALID and self.error is None:
            raise ValueError(f"INVALID series {self.metric} requires an error.")


@dataclass(frozen=True)
class CanonicalFinancialHistory:
    """The complete canonical reported history for one company.

    ``max_years`` is the requested annual window; instant metrics may hold one
    extra baseline fiscal-year-end for average-balance denominators.
    """

    ticker: str
    max_years: int
    series: tuple[CanonicalSeries, ...]

    def __post_init__(self) -> None:
        if not self.ticker or self.ticker != self.ticker.strip().upper():
            raise ValueError("A canonical history requires a canonical uppercase ticker.")
        if self.max_years < 1:
            raise ValueError("max_years must be at least 1.")
        names = tuple(series.metric for series in self.series)
        if names != _ORDER:
            raise ValueError(
                "A canonical history must hold exactly one series per canonical "
                "metric, in vocabulary order."
            )

    def series_for(self, metric: str) -> CanonicalSeries:
        """Return the series for a metric regardless of its status."""
        metric_spec(metric)
        return self.series[_ORDER.index(metric)]

    def require(self, metric: str, *, allow_unsupported: bool = False) -> CanonicalSeries:
        """Return a usable series or raise the metric's typed failure.

        AVAILABLE and STRUCTURALLY_ABSENT series are returned. An UNSUPPORTED
        series is returned (empty) only when ``allow_unsupported`` is set. The
        provider's stored error object is re-raised unchanged so callers see the
        same type and message the provider produced.
        """
        series = self.series_for(metric)
        if series.status is MetricStatus.INVALID or (
            series.status is MetricStatus.UNSUPPORTED and not allow_unsupported
        ):
            if series.error is not None:
                raise series.error.with_traceback(None)
            raise MetricUnsupportedError(series.reason)
        return series

    def statuses(self) -> dict[str, MetricStatus]:
        """Return each metric's status in vocabulary order."""
        return {series.metric: series.status for series in self.series}

    def providers(self) -> frozenset[str]:
        """Return the providers that contributed facts to this history."""
        return frozenset(
            fact.provider for series in self.series for fact in series.observations
        )

    @classmethod
    def build(
        cls,
        *,
        ticker: str,
        max_years: int,
        facts: Iterable[CanonicalFact],
        structurally_absent: Iterable[str] = (),
        unsupported: Mapping[str, str] | None = None,
    ) -> CanonicalFinancialHistory:
        """Assemble a history from facts plus explicit absent/unsupported declarations.

        Every metric without facts must be declared structurally absent or
        unsupported; an undeclared gap raises ``ValueError`` rather than being
        silently treated as either.
        """
        by_metric: dict[str, list[CanonicalFact]] = {}
        for fact in facts:
            by_metric.setdefault(fact.metric, []).append(fact)
        absent = set(structurally_absent)
        unsupported_reasons = dict(unsupported or {})
        for name in absent | set(unsupported_reasons):
            metric_spec(name)

        series: list[CanonicalSeries] = []
        for spec in CANONICAL_METRICS:
            observations = tuple(
                sorted(by_metric.get(spec.name, ()), key=lambda f: f.fiscal_year, reverse=True)
            )
            declared = (spec.name in absent) + (spec.name in unsupported_reasons)
            if observations and declared:
                raise ValueError(f"{spec.name} has facts but is also declared missing.")
            if declared > 1:
                raise ValueError(f"{spec.name} is declared both absent and unsupported.")
            if observations:
                series.append(
                    CanonicalSeries(spec.name, spec.unit, MetricStatus.AVAILABLE, observations)
                )
            elif spec.name in absent:
                series.append(
                    CanonicalSeries(spec.name, spec.unit, MetricStatus.STRUCTURALLY_ABSENT)
                )
            elif spec.name in unsupported_reasons:
                series.append(
                    CanonicalSeries(
                        spec.name,
                        spec.unit,
                        MetricStatus.UNSUPPORTED,
                        reason=unsupported_reasons[spec.name],
                    )
                )
            else:
                raise ValueError(
                    f"{spec.name} has no facts and is not declared structurally "
                    "absent or unsupported."
                )
        return cls(ticker=ticker, max_years=max_years, series=tuple(series))

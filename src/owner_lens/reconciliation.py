"""Deterministic dual-source reconciliation of canonical financial histories (Slice 5C).

Compares an SEC-backed and an FMP-backed ``CanonicalFinancialHistory`` for the same
company by ``(ticker, metric, fiscal_year)``, classifies every difference, compares
the OwnerLens outputs computed from each history, and derives an evidence-based
verdict on whether the candidate provider (FMP) could serve as primary.

This module never sees raw provider payloads and imports no provider module: it
reads canonical facts and their provenance only. It compares *reported* canonical
facts; OwnerLens-derived outputs (FCF, FCF/share, margins, ROIC, classifications)
are recomputed from each history by the existing deterministic layers. FMP's own
precomputed values are never used.

Tolerance is rounding tolerance only: a difference of at most half a million
(USD or shares) reflects filings reported in millions. Any larger difference is
``REVIEW`` until a documented ``KnownDiscrepancy`` explains it, and an explained
difference remains visible as ``EXPLAINED``; it is never absorbed by a band.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final

from owner_lens.canonical import (
    CANONICAL_METRICS,
    CanonicalDataError,
    CanonicalFact,
    CanonicalFinancialHistory,
    CanonicalSeries,
    MetricStatus,
)
from owner_lens.capital_efficiency import capital_efficiency_from_history
from owner_lens.economic_summary import economic_value_summary_from_history
from owner_lens.economic_value import economic_value_from_history
from owner_lens.owner_economics import owner_economics_from_history

__all__ = [
    "CORE_METRICS",
    "ROUNDING_TOLERANCE",
    "DerivedReconciliation",
    "DiscrepancyCategory",
    "Eligibility",
    "EligibilityVerdict",
    "FactReconciliation",
    "KnownDiscrepancy",
    "ReconciliationReport",
    "ReconciliationStatus",
    "ReconciliationSummary",
    "format_reconciliation_report",
    "reconcile_histories",
]

ROUNDING_TOLERANCE: Final = 500_000
MAX_PERIOD_END_GAP_DAYS: Final = 7
CORE_METRICS: Final = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "pretax_income",
        "income_tax_expense",
        "operating_cash_flow",
        "capital_expenditures",
        "cash",
        "total_assets",
        "total_equity",
        "current_debt",
        "long_term_debt",
    }
)


class ReconciliationStatus(Enum):
    """Outcome of comparing one fact or derived output across the two providers."""

    MATCH = "MATCH"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    REVIEW = "REVIEW"
    EXPLAINED = "EXPLAINED"
    SEC_ONLY = "SEC_ONLY"
    FMP_ONLY = "FMP_ONLY"
    SEMANTIC_DIFFERENCE = "SEMANTIC_DIFFERENCE"
    UNCOMPARABLE = "UNCOMPARABLE"


class DiscrepancyCategory(Enum):
    """Why two providers disagree."""

    NONE = "NONE"
    ROUNDING = "ROUNDING"
    PERIOD_TIMING = "PERIOD_TIMING"
    PROVIDER_NORMALIZATION = "PROVIDER_NORMALIZATION"
    SEC_CONCEPT_SELECTION = "SEC_CONCEPT_SELECTION"
    SOURCE_DISCREPANCY = "SOURCE_DISCREPANCY"
    POLICY_DIFFERENCE = "POLICY_DIFFERENCE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


class Eligibility(Enum):
    """Whether the candidate provider could serve as primary for a company.

    * ``ELIGIBLE``: no material differences at all (only matches, rounding, and
      window timing).
    * ``ELIGIBLE_WITH_EXPLAINED_DIFFERENCES``: material differences exist, and
      every one is understood, documented, and does not make a core fact
      untrustworthy.
    * ``NOT_ELIGIBLE``: at least one material unresolved discrepancy, or a core
      fact from the candidate provider cannot be trusted.
    """

    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_EXPLAINED_DIFFERENCES = "ELIGIBLE_WITH_EXPLAINED_DIFFERENCES"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


@dataclass(frozen=True)
class KnownDiscrepancy:
    """A documented, evidence-backed explanation for a provider difference.

    ``fiscal_year=None`` applies to every fiscal year of the metric.
    ``fmp_trusted`` records whether the FMP value is acceptable as an OwnerLens
    fact despite the difference (for example, FMP matches the filed canonical
    meaning while SEC concept selection does not). ``fmp_trusted=False`` on a
    core metric keeps the company ``NOT_ELIGIBLE`` even though it is explained.
    """

    ticker: str
    metric: str
    fiscal_year: int | None
    category: DiscrepancyCategory
    explanation: str
    evidence: str
    fmp_trusted: bool

    def matches(self, ticker: str, metric: str, fiscal_year: int | None) -> bool:
        return (
            self.ticker == ticker
            and self.metric == metric
            and (self.fiscal_year is None or self.fiscal_year == fiscal_year)
        )


@dataclass(frozen=True)
class FactReconciliation:
    """One canonical metric and fiscal year compared across providers, with provenance.

    ``fiscal_year`` is ``None`` for metric-level rows (a metric with no facts on
    at least one side, such as structurally absent or unsupported on both).
    """

    ticker: str
    metric: str
    fiscal_year: int | None
    sec_fact: CanonicalFact | None
    fmp_fact: CanonicalFact | None
    sec_status: MetricStatus
    fmp_status: MetricStatus
    status: ReconciliationStatus
    category: DiscrepancyCategory
    reason: str
    material: bool
    explanation: KnownDiscrepancy | None = None

    @property
    def difference(self) -> int | None:
        if self.sec_fact is None or self.fmp_fact is None:
            return None
        return self.fmp_fact.value - self.sec_fact.value

    @property
    def relative_difference(self) -> float | None:
        """Informational only; never used for classification."""
        diff = self.difference
        if diff is None or self.sec_fact is None or self.sec_fact.value == 0:
            return None
        return diff / abs(self.sec_fact.value)

    @property
    def accounted_for(self) -> bool:
        """True when the row is immaterial or carries a documented explanation."""
        return not self.material or self.explanation is not None

    @property
    def is_core(self) -> bool:
        return self.metric in CORE_METRICS


@dataclass(frozen=True)
class DerivedReconciliation:
    """One OwnerLens-derived output compared across providers.

    ``traced_to`` lists the non-matching fact rows (metric, fiscal year) among the
    output's inputs, so a derived difference always points at its fact-level cause.
    """

    ticker: str
    output: str
    fiscal_year: int | None
    sec_value: Any
    fmp_value: Any
    status: ReconciliationStatus
    category: DiscrepancyCategory
    reason: str
    traced_to: tuple[tuple[str, int | None], ...] = ()

    @property
    def difference(self) -> float | None:
        a, b = self.sec_value, self.fmp_value
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return b - a
        return None


@dataclass(frozen=True)
class ReconciliationSummary:
    """Counts across a company's fact-level reconciliation."""

    ticker: str
    total_facts_compared: int
    by_status: dict[ReconciliationStatus, int]
    by_category: dict[DiscrepancyCategory, int]
    derived_by_status: dict[ReconciliationStatus, int]

    def count(self, status: ReconciliationStatus) -> int:
        return self.by_status.get(status, 0)


@dataclass(frozen=True)
class EligibilityVerdict:
    """Company-level primary-provider verdict with the rows that drive it."""

    ticker: str
    eligibility: Eligibility
    blocking: tuple[str, ...]
    explained_material: tuple[str, ...]
    unassessed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationReport:
    """The full fact-level and derived-output reconciliation for one company."""

    ticker: str
    facts: tuple[FactReconciliation, ...]
    derived: tuple[DerivedReconciliation, ...]
    unused_explanations: tuple[KnownDiscrepancy, ...] = field(default=())

    def summary(self) -> ReconciliationSummary:
        compared = sum(1 for r in self.facts if r.sec_fact is not None and r.fmp_fact is not None)
        return ReconciliationSummary(
            ticker=self.ticker,
            total_facts_compared=compared,
            by_status=dict(Counter(r.status for r in self.facts)),
            by_category=dict(Counter(r.category for r in self.facts)),
            derived_by_status=dict(Counter(r.status for r in self.derived)),
        )

    def verdict(self) -> EligibilityVerdict:
        blocking: list[str] = []
        explained: list[str] = []
        for row in self.facts:
            label = _fact_label(row)
            if not row.material:
                continue
            if row.explanation is None:
                blocking.append(f"{label}: unexplained {row.status.value} ({row.category.value})")
            elif row.is_core and not row.explanation.fmp_trusted:
                blocking.append(f"{label}: core fact not trustworthy from FMP ({row.category.value})")
            elif row.is_core and row.category is DiscrepancyCategory.INVALID:
                blocking.append(f"{label}: core fact is INVALID")
            else:
                explained.append(f"{label}: {row.category.value}")
        unassessed = tuple(
            f"{d.output}: {d.reason}"
            for d in self.derived
            if d.status is ReconciliationStatus.UNCOMPARABLE
        )
        for derived in self.derived:
            if derived.status is ReconciliationStatus.REVIEW:
                year = f" FY{derived.fiscal_year}" if derived.fiscal_year else ""
                blocking.append(f"derived {derived.output}{year}: unexplained difference")
        for unused in self.unused_explanations:
            year = f" FY{unused.fiscal_year}" if unused.fiscal_year else ""
            blocking.append(f"stale explanation {unused.metric}{year}: no longer matches a difference")
        if blocking:
            eligibility = Eligibility.NOT_ELIGIBLE
        elif explained:
            eligibility = Eligibility.ELIGIBLE_WITH_EXPLAINED_DIFFERENCES
        else:
            eligibility = Eligibility.ELIGIBLE
        return EligibilityVerdict(
            self.ticker, eligibility, tuple(blocking), tuple(explained), unassessed
        )


def _fact_label(row: FactReconciliation) -> str:
    year = f" FY{row.fiscal_year}" if row.fiscal_year is not None else ""
    return f"{row.metric}{year}"


# --- Fact-level comparison ---------------------------------------------------

_Row = FactReconciliation


def _row(
    ticker: str,
    metric: str,
    year: int | None,
    sec: CanonicalSeries,
    fmp: CanonicalSeries,
    status: ReconciliationStatus,
    category: DiscrepancyCategory,
    reason: str,
    *,
    material: bool,
    sec_fact: CanonicalFact | None = None,
    fmp_fact: CanonicalFact | None = None,
) -> _Row:
    return FactReconciliation(
        ticker=ticker,
        metric=metric,
        fiscal_year=year,
        sec_fact=sec_fact,
        fmp_fact=fmp_fact,
        sec_status=sec.status,
        fmp_status=fmp.status,
        status=status,
        category=category,
        reason=reason,
        material=material,
    )


def _compare_values(
    ticker: str, metric: str, year: int, sec: CanonicalSeries, fmp: CanonicalSeries,
    a: CanonicalFact, b: CanonicalFact,
) -> _Row:
    gap = abs((a.period_end - b.period_end).days)
    if gap > MAX_PERIOD_END_GAP_DAYS:
        return _row(
            ticker, metric, year, sec, fmp, ReconciliationStatus.UNCOMPARABLE,
            DiscrepancyCategory.PERIOD_TIMING,
            f"period ends differ by {gap} days ({a.period_end} vs {b.period_end})",
            material=True, sec_fact=a, fmp_fact=b,
        )
    date_note = f"; period ends differ by {gap} days" if gap else ""
    diff = b.value - a.value
    if diff == 0:
        status, category, material = ReconciliationStatus.MATCH, DiscrepancyCategory.NONE, False
        reason = "values equal" + date_note
    elif abs(diff) <= ROUNDING_TOLERANCE:
        status, category, material = (
            ReconciliationStatus.WITHIN_TOLERANCE, DiscrepancyCategory.ROUNDING, False
        )
        reason = f"difference {diff:+,} is within rounding tolerance" + date_note
    else:
        status, category, material = (
            ReconciliationStatus.REVIEW, DiscrepancyCategory.SOURCE_DISCREPANCY, True
        )
        reason = f"difference {diff:+,} exceeds rounding tolerance" + date_note
    return _row(
        ticker, metric, year, sec, fmp, status, category, reason,
        material=material, sec_fact=a, fmp_fact=b,
    )


def _one_sided(
    ticker: str, metric: str, year: int, sec: CanonicalSeries, fmp: CanonicalSeries,
    a: CanonicalFact | None, b: CanonicalFact | None,
) -> _Row:
    missing = fmp if a is not None else sec
    status = ReconciliationStatus.SEC_ONLY if a is not None else ReconciliationStatus.FMP_ONLY
    missing_name = "FMP" if a is not None else "SEC"
    if missing.status is MetricStatus.UNSUPPORTED:
        return _row(
            ticker, metric, year, sec, fmp, status, DiscrepancyCategory.UNSUPPORTED,
            f"{missing_name} has no supported value: {missing.reason}",
            material=True, sec_fact=a, fmp_fact=b,
        )
    if missing.status is MetricStatus.STRUCTURALLY_ABSENT:
        return _row(
            ticker, metric, year, sec, fmp, ReconciliationStatus.SEMANTIC_DIFFERENCE,
            DiscrepancyCategory.POLICY_DIFFERENCE,
            f"{missing_name} treats {metric} as structurally absent"
            + (f": {missing.reason}" if missing.reason else ""),
            material=True, sec_fact=a, fmp_fact=b,
        )
    years = [f.fiscal_year for f in missing.observations]
    if years and not min(years) <= year <= max(years):
        return _row(
            ticker, metric, year, sec, fmp, status, DiscrepancyCategory.PERIOD_TIMING,
            f"FY{year} is outside {missing_name}'s available years "
            f"FY{min(years)}-FY{max(years)}",
            material=False, sec_fact=a, fmp_fact=b,
        )
    return _row(
        ticker, metric, year, sec, fmp, status, DiscrepancyCategory.SOURCE_DISCREPANCY,
        f"{missing_name} has no FY{year} value inside its available years",
        material=True, sec_fact=a, fmp_fact=b,
    )


def _metric_level(
    ticker: str, metric: str, sec: CanonicalSeries, fmp: CanonicalSeries
) -> _Row | None:
    s, f = sec.status, fmp.status
    absent, unsupported = MetricStatus.STRUCTURALLY_ABSENT, MetricStatus.UNSUPPORTED
    if MetricStatus.INVALID in (s, f):
        reasons = "; ".join(
            f"{name}: {series.reason}"
            for name, series in (("SEC", sec), ("FMP", fmp))
            if series.status is MetricStatus.INVALID
        )
        return _row(
            ticker, metric, None, sec, fmp, ReconciliationStatus.UNCOMPARABLE,
            DiscrepancyCategory.INVALID, f"invalid provider data ({reasons})", material=True,
        )
    if s is absent and f is absent:
        return _row(
            ticker, metric, None, sec, fmp, ReconciliationStatus.MATCH,
            DiscrepancyCategory.NONE, "structurally absent in both providers", material=False,
        )
    if s is unsupported and f is unsupported:
        return _row(
            ticker, metric, None, sec, fmp, ReconciliationStatus.UNCOMPARABLE,
            DiscrepancyCategory.UNSUPPORTED, "unsupported by both providers", material=False,
        )
    if {s, f} == {absent, unsupported}:
        return _row(
            ticker, metric, None, sec, fmp, ReconciliationStatus.SEMANTIC_DIFFERENCE,
            DiscrepancyCategory.POLICY_DIFFERENCE,
            f"SEC {s.value} vs FMP {f.value}", material=True,
        )
    return None


def _compare_metric(
    ticker: str, metric: str, sec: CanonicalSeries, fmp: CanonicalSeries
) -> list[_Row]:
    metric_row = _metric_level(ticker, metric, sec, fmp)
    if metric_row is not None:
        return [metric_row]
    sec_by = {fact.fiscal_year: fact for fact in sec.observations}
    fmp_by = {fact.fiscal_year: fact for fact in fmp.observations}
    rows: list[_Row] = []
    for year in sorted(set(sec_by) | set(fmp_by), reverse=True):
        a, b = sec_by.get(year), fmp_by.get(year)
        if a is not None and b is not None:
            rows.append(_compare_values(ticker, metric, year, sec, fmp, a, b))
        else:
            rows.append(_one_sided(ticker, metric, year, sec, fmp, a, b))
    return rows


def _compatible(known: KnownDiscrepancy, row: _Row) -> bool:
    if known.category is DiscrepancyCategory.UNSUPPORTED:
        return row.category is DiscrepancyCategory.UNSUPPORTED
    if known.category is DiscrepancyCategory.POLICY_DIFFERENCE:
        return row.status is ReconciliationStatus.SEMANTIC_DIFFERENCE
    return True


def _apply_explanations(
    rows: list[_Row], explanations: Sequence[KnownDiscrepancy]
) -> tuple[list[_Row], tuple[KnownDiscrepancy, ...]]:
    used: set[int] = set()
    applied: list[_Row] = []
    for row in rows:
        if row.status is ReconciliationStatus.MATCH:
            applied.append(row)
            continue
        # Year-wildcard explanations apply to material rows only, so they never
        # relabel routine window-timing rows; a year-specific entry may annotate any row.
        # An explanation must also fit the row's kind: an UNSUPPORTED or POLICY
        # explanation never absorbs a value difference, so an explanation whose
        # premise no longer holds goes stale instead of masking a new discrepancy.
        match = next(
            (
                (index, known)
                for index, known in enumerate(explanations)
                if known.matches(row.ticker, row.metric, row.fiscal_year)
                and (row.material or known.fiscal_year is not None)
                and _compatible(known, row)
            ),
            None,
        )
        if match is None or row.status is ReconciliationStatus.WITHIN_TOLERANCE:
            applied.append(row)
            continue
        index, known = match
        used.add(index)
        status = (
            ReconciliationStatus.EXPLAINED
            if row.status is ReconciliationStatus.REVIEW
            else row.status
        )
        category = (
            row.category
            if row.category is DiscrepancyCategory.INVALID
            else known.category
        )
        applied.append(
            replace(
                row,
                status=status,
                category=category,
                reason=f"{row.reason}; explained: {known.explanation}",
                explanation=known,
            )
        )
    unused = tuple(known for index, known in enumerate(explanations) if index not in used)
    return applied, unused


# --- Derived-output comparison ------------------------------------------------

_OWNER_OUTPUTS: Final = {
    "free_cash_flow": ("operating_cash_flow", "capital_expenditures"),
    "fcf_per_share": ("operating_cash_flow", "capital_expenditures", "diluted_shares"),
    "operating_margin": ("operating_income", "revenue"),
    "fcf_margin": ("operating_cash_flow", "capital_expenditures", "revenue"),
}
_BALANCE: Final = (
    "cash", "short_term_investments", "current_debt", "long_term_debt", "total_equity"
)
_CAPITAL_OUTPUTS: Final = {
    "net_cash": ("cash", "short_term_investments", "current_debt", "long_term_debt"),
    "invested_capital": _BALANCE,
    "roic": ("operating_income", "income_tax_expense", "pretax_income", *_BALANCE),
}
# How many prior fiscal years an output reads: ROIC averages the prior balance; the
# annual classification reads the ROIC change, which itself needs two prior balances.
_LOOKBACK_YEARS: Final = {"roic": 1, "annual_classification": 2}
_ANNUAL_CLASSIFICATION_INPUTS: Final = tuple(
    spec.name
    for spec in CANONICAL_METRICS
    if spec.name not in {"repurchases", "stock_based_compensation", "dividends_paid"}
)
_ALL_METRICS: Final = tuple(spec.name for spec in CANONICAL_METRICS)


def _safe(fn: Callable[[CanonicalFinancialHistory], Any], history: CanonicalFinancialHistory):
    try:
        return fn(history), None
    except CanonicalDataError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _traced(
    facts: Sequence[_Row], metrics: Iterable[str], years: set[int] | None
) -> list[_Row]:
    wanted = set(metrics)
    return [
        row
        for row in facts
        if row.metric in wanted
        and row.status is not ReconciliationStatus.MATCH
        and (years is None or row.fiscal_year is None or row.fiscal_year in years)
    ]


def _classify_derived(
    ticker: str,
    output: str,
    year: int | None,
    sec_value: Any,
    fmp_value: Any,
    causes: list[_Row],
) -> DerivedReconciliation:
    keys = tuple((row.metric, row.fiscal_year) for row in causes)
    if sec_value == fmp_value:
        return DerivedReconciliation(
            ticker, output, year, sec_value, fmp_value,
            ReconciliationStatus.MATCH, DiscrepancyCategory.NONE, "equal", keys,
        )
    if sec_value is None or fmp_value is None:
        status = (
            ReconciliationStatus.FMP_ONLY if sec_value is None else ReconciliationStatus.SEC_ONLY
        )
        category = next(
            (r.category for r in causes if r.category is not DiscrepancyCategory.ROUNDING),
            DiscrepancyCategory.SOURCE_DISCREPANCY,
        )
        reason = (
            f"only one provider can compute {output}; caused by "
            + (", ".join(_fact_label(r) for r in causes) or "no fact-level difference")
        )
        return DerivedReconciliation(
            ticker, output, year, sec_value, fmp_value, status, category, reason, keys
        )
    if not causes:
        return DerivedReconciliation(
            ticker, output, year, sec_value, fmp_value,
            ReconciliationStatus.REVIEW, DiscrepancyCategory.SOURCE_DISCREPANCY,
            "outputs differ with no fact-level cause among inputs", keys,
        )
    if all(r.category is DiscrepancyCategory.ROUNDING for r in causes):
        return DerivedReconciliation(
            ticker, output, year, sec_value, fmp_value,
            ReconciliationStatus.WITHIN_TOLERANCE, DiscrepancyCategory.ROUNDING,
            "difference propagates only input rounding", keys,
        )
    material = [r for r in causes if r.category is not DiscrepancyCategory.ROUNDING]
    unexplained = [r for r in material if not r.accounted_for]
    labels = ", ".join(f"{_fact_label(r)} ({r.category.value})" for r in material)
    if unexplained:
        return DerivedReconciliation(
            ticker, output, year, sec_value, fmp_value,
            ReconciliationStatus.REVIEW, unexplained[0].category,
            f"traced to unexplained fact differences: {labels}", keys,
        )
    return DerivedReconciliation(
        ticker, output, year, sec_value, fmp_value,
        ReconciliationStatus.EXPLAINED, material[0].category,
        f"traced to accounted fact differences: {labels}", keys,
    )


def _uncomparable(
    ticker: str, output: str, sec_error: str | None, fmp_error: str | None
) -> DerivedReconciliation:
    parts = [f"{n} cannot compute: {e}" for n, e in (("SEC", sec_error), ("FMP", fmp_error)) if e]
    return DerivedReconciliation(
        ticker, output, None, None, None, ReconciliationStatus.UNCOMPARABLE,
        DiscrepancyCategory.UNSUPPORTED, "; ".join(parts),
    )


def _derived_rows(
    ticker: str,
    sec: CanonicalFinancialHistory,
    fmp: CanonicalFinancialHistory,
    facts: Sequence[_Row],
) -> list[DerivedReconciliation]:
    rows: list[DerivedReconciliation] = []

    def per_year(
        layer: Callable[[CanonicalFinancialHistory], Any],
        layer_name: str,
        outputs: dict[str, tuple[str, ...]],
        value: Callable[[Any, str], Any],
    ) -> None:
        sec_rows, sec_err = _safe(layer, sec)
        fmp_rows, fmp_err = _safe(layer, fmp)
        if sec_err or fmp_err:
            rows.append(_uncomparable(ticker, layer_name, sec_err, fmp_err))
            return
        sec_by = {r.fiscal_year: r for r in sec_rows}
        fmp_by = {r.fiscal_year: r for r in fmp_rows}
        for year in sorted(set(sec_by) | set(fmp_by), reverse=True):
            for output, inputs in outputs.items():
                years = {year - back for back in range(_LOOKBACK_YEARS.get(output, 0) + 1)}
                sec_value = value(sec_by.get(year), output)
                fmp_value = value(fmp_by.get(year), output)
                causes = _traced(facts, inputs, years)
                rows.append(_classify_derived(ticker, output, year, sec_value, fmp_value, causes))

    def attr(row: Any, name: str) -> Any:
        return getattr(row, name) if row is not None else None

    per_year(owner_economics_from_history, "owner_economics", dict(_OWNER_OUTPUTS), attr)
    per_year(capital_efficiency_from_history, "capital_efficiency", dict(_CAPITAL_OUTPUTS), attr)
    per_year(
        economic_value_from_history,
        "economic_value",
        {"annual_classification": _ANNUAL_CLASSIFICATION_INPUTS},
        lambda row, _name: row.classification.value if row is not None else None,
    )

    sec_summary, sec_err = _safe(economic_value_summary_from_history, sec)
    fmp_summary, fmp_err = _safe(economic_value_summary_from_history, fmp)
    if sec_err or fmp_err:
        rows.append(_uncomparable(ticker, "overall_classification", sec_err, fmp_err))
    else:
        rows.append(
            _classify_derived(
                ticker,
                "overall_classification",
                None,
                sec_summary.overall_economic_value_classification.value,
                fmp_summary.overall_economic_value_classification.value,
                _traced(facts, _ALL_METRICS, None),
            )
        )
    return rows


def reconcile_histories(
    sec: CanonicalFinancialHistory,
    fmp: CanonicalFinancialHistory,
    *,
    explanations: Sequence[KnownDiscrepancy] = (),
) -> ReconciliationReport:
    """Compare two canonical histories fact by fact, then their OwnerLens outputs.

    Only ``explanations`` for this ticker are considered; an explanation that no
    longer matches any difference is reported as unused so it cannot silently
    mask a future change.
    """
    if sec.ticker != fmp.ticker:
        raise ValueError(
            f"Cannot reconcile different companies: {sec.ticker} vs {fmp.ticker}."
        )
    ticker = sec.ticker
    raw_rows: list[_Row] = []
    for spec in CANONICAL_METRICS:
        raw_rows.extend(
            _compare_metric(ticker, spec.name, sec.series_for(spec.name), fmp.series_for(spec.name))
        )
    relevant = [known for known in explanations if known.ticker == ticker]
    facts, unused = _apply_explanations(raw_rows, relevant)
    derived = _derived_rows(ticker, sec, fmp, facts)
    return ReconciliationReport(ticker, tuple(facts), tuple(derived), unused)


# --- Formatting ---------------------------------------------------------------


def _fmt_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (bool, str)):
        return str(value)
    if isinstance(value, int):
        return f"{value / 1e6:,.1f}M"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _fmt_provenance(fact: CanonicalFact | None) -> str:
    if fact is None:
        return "-"
    parts = [fact.provider, fact.provider_field, f"end {fact.period_end}"]
    if fact.form:
        parts.append(fact.form)
    if fact.filed:
        parts.append(f"filed {fact.filed}")
    if fact.accession:
        parts.append(fact.accession)
    return " ".join(parts)


def format_reconciliation_report(
    report: ReconciliationReport, *, show_all: bool = False
) -> str:
    """Render the reconciliation as compact text, with provenance for every difference."""
    summary = report.summary()
    verdict = report.verdict()
    lines = [
        f"{report.ticker} — SEC vs FMP reconciliation",
        f"facts compared: {summary.total_facts_compared}  "
        + "  ".join(f"{s.value}={summary.count(s)}" for s in ReconciliationStatus),
        f"verdict: {verdict.eligibility.value}",
        "",
        (
            f"{'Metric':<25} {'FY':>4} {'SEC':>12} {'FMP':>12} {'Diff':>11}  "
            f"{'Status':<19} {'Category':<22} Reason"
        ),
    ]
    for row in report.facts:
        if not show_all and row.status is ReconciliationStatus.MATCH:
            continue
        year = str(row.fiscal_year) if row.fiscal_year is not None else "-"
        lines.append(
            f"{row.metric:<25} {year:>4} {_fmt_value(row.sec_fact and row.sec_fact.value):>12} "
            f"{_fmt_value(row.fmp_fact and row.fmp_fact.value):>12} "
            f"{_fmt_value(row.difference):>11}  {row.status.value:<19} "
            f"{row.category.value:<22} {row.reason}"
        )
        if row.material:
            lines.append(f"{'':>31}SEC: {_fmt_provenance(row.sec_fact)}")
            lines.append(f"{'':>31}FMP: {_fmt_provenance(row.fmp_fact)}")
            if row.explanation is not None:
                lines.append(f"{'':>31}evidence: {row.explanation.evidence}")
    lines.append("")
    lines.append("Derived OwnerLens outputs")
    for derived in report.derived:
        if not show_all and derived.status is ReconciliationStatus.MATCH:
            continue
        year = str(derived.fiscal_year) if derived.fiscal_year is not None else "-"
        lines.append(
            f"{derived.output:<25} {year:>4} {_fmt_value(derived.sec_value):>12} "
            f"{_fmt_value(derived.fmp_value):>12} {_fmt_value(derived.difference):>11}  "
            f"{derived.status.value:<19} {derived.category.value:<22} {derived.reason}"
        )
    if report.unused_explanations:
        lines.append("")
        lines.append("Unused (stale) explanations:")
        for known in report.unused_explanations:
            lines.append(f"  {known.metric} FY{known.fiscal_year}: {known.explanation}")
    if verdict.blocking:
        lines.append("")
        lines.append("Blocking:")
        lines.extend(f"  {item}" for item in verdict.blocking)
    return "\n".join(lines)

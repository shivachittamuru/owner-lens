"""Reproducible, unscored comparisons of exact immutable Feature 8 versions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from itertools import combinations
from typing import Any

from owner_lens.challenger import (
    RULE_MODEL_VERSION,
    RuleBasedChallenger,
    build_context,
)
from owner_lens.persistence import SqliteStore
from owner_lens.screening import DimensionBand, ScreeningDimension
from owner_lens.underwriting import (
    UnderwritingSnapshot,
    _retrieved_at,
)
from owner_lens.underwriting_contract import validate_belief_links
from owner_lens.underwriting_summary import (
    UnderwritingSummary,
    saved_valuation,
    summarize_underwriting,
)

COMPARISON_VERSION = "opportunity-comparison-v1"
DISCLAIMER = (
    "Conditional on frozen prices and investor beliefs; not a recommendation, "
    "buy/sell decision or position size. No aggregate ranking score."
)
_EPSILON = 1e-12


class ComparisonError(ValueError):
    """Selection is invalid or an underwriting is not comparison-ready."""


@dataclass(frozen=True)
class UnderwritingSelection:
    ticker: str
    version: int

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]*", self.ticker)
            or type(self.version) is not int
            or self.version < 1
        ):
            raise ComparisonError(
                "Use an explicit TICKER:VERSION with a positive version."
            )

    @classmethod
    def parse(cls, value: str) -> UnderwritingSelection:
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9.-]*):([1-9][0-9]*)", value)
        if match is None:
            raise ComparisonError(f"Invalid selection {value!r}; use TICKER:VERSION.")
        return cls(match[1].upper(), int(match[2]))


@dataclass(frozen=True)
class BusinessContext:
    priority: str | None
    setup_type: str | None
    coverage: str | None
    dimensions: tuple[tuple[str, str | None], ...]
    missing_reason: str | None

    def band(self, dimension: str) -> int | None:
        value = dict(self.dimensions).get(dimension)
        return DimensionBand(value).ordinal if value is not None else None


@dataclass(frozen=True)
class UnderwritingQuality:
    supporting_evidence: tuple[str, ...]
    disconfirming_evidence: tuple[str, ...]
    variant_status: str
    documented_variant: bool | None
    most_sensitive_driver: str
    sensitivity_cagr_delta: float
    sensitivity_band: str
    challenger_status: str
    challenger_model_version: str
    major_unresolved_questions: tuple[str, ...]
    biggest_uncertainty: str
    missing_dimensions: tuple[str, ...]


@dataclass(frozen=True)
class Opportunity:
    summary: UnderwritingSummary
    quality: UnderwritingQuality
    business: BusinessContext
    flags: tuple[str, ...] = ()
    research_attention: tuple[str, ...] = ()
    capital_attractiveness: str = ""
    key_tradeoff: str = ""
    unresolved_issue: str = ""

    @property
    def label(self) -> str:
        return f"{self.summary.ticker}:{self.summary.underwriting_version}"

    @property
    def bear_cagr(self) -> float:
        return self.summary.scenarios[0].implied_cagr


@dataclass(frozen=True)
class PairwiseComparison:
    left: str
    right: str
    left_flags: tuple[str, ...]
    right_flags: tuple[str, ...]
    left_advantages: tuple[str, ...]
    right_advantages: tuple[str, ...]
    missing_dimensions: tuple[str, ...]
    conclusion: str
    dominated: str | None
    key_tradeoff: str
    capital_attractiveness: str
    research_attention: str


@dataclass(frozen=True)
class OpportunityComparison:
    opportunities: tuple[Opportunity, ...]
    pairs: tuple[PairwiseComparison, ...]
    model_version: str = COMPARISON_VERSION
    disclaimer: str = DISCLAIMER

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


def _business(snapshot: UnderwritingSnapshot) -> BusinessContext:
    context = json.loads(snapshot.evidence_json).get("feature7_context")
    if context is None:
        return BusinessContext(
            None,
            None,
            None,
            tuple((item.value, None) for item in ScreeningDimension),
            "Feature 7 context was not frozen in this underwriting; not recomputed.",
        )
    dimensions = context["dimensions"]
    # Validate labels, but do not evaluate Feature 7 rules or import its score.
    for band in dimensions.values():
        if band is not None:
            DimensionBand(band)
    return BusinessContext(
        context["priority"],
        context["setup_type"],
        context["coverage"],
        tuple((item.value, dimensions.get(item.value)) for item in ScreeningDimension),
        None,
    )


def _validate_cutoff(
    snapshot: UnderwritingSnapshot, created_at: str, as_of: str
) -> None:
    evidence = json.loads(snapshot.evidence_json)
    cutoff = min(
        _retrieved_at(created_at),
        _retrieved_at(as_of + "T23:59:59.999999+00:00"),
        _retrieved_at(evidence.get("cutoff", created_at)),
    )

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                # Future estimate targets and thesis monitoring dates are intentional.
                if (
                    key
                    in {
                        "observed_at",
                        "fetched_at",
                        "evidence_date",
                        "period_end",
                        "market_date",
                    }
                    and child
                    and (not isinstance(child, str) or _retrieved_at(child) > cutoff)
                ):
                    raise ComparisonError(f"{key} exceeds frozen underwriting cutoff.")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(json.loads(snapshot.to_json()))
    validate_belief_links(snapshot, as_of)


def load_opportunity(
    store: SqliteStore, selection: UnderwritingSelection
) -> Opportunity:
    """No latest fallback, current evidence queries, writes, or saved-run selection."""
    record = next(
        (
            item
            for item in store.list_underwriting(selection.ticker)
            if item.version == selection.version
        ),
        None,
    )
    if record is None:
        raise ComparisonError(
            f"Underwriting {selection.ticker}:{selection.version} not found."
        )
    try:
        snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
        _validate_cutoff(snapshot, record.created_at, record.as_of_date)
        valuation = saved_valuation(store, record)
        summary = summarize_underwriting(record, valuation)
        if summary.classification == "INSUFFICIENT":
            raise ComparisonError(
                "Scenario labels are unordered; complete the underwriting first."
            )
        drivers = summary.variant.drivers
        sensitive = max(drivers, key=lambda item: abs(item.sensitivity.cagr_delta))
        material = tuple(item for item in drivers if item.material)
        documented = (
            any(item.rationale is not None for item in material)
            if material
            else False
            if all(item.consensus.value is not None for item in drivers)
            else None
        )
        missing = [
            f"{item.driver}: {item.consensus.reason}"
            for item in drivers
            if item.consensus.value is None
        ]
        for field in ("supporting_evidence", "disconfirming_evidence"):
            if not getattr(snapshot.manual, field):
                missing.append(f"{field}: no investor evidence recorded")
        business = _business(snapshot)
        for name, value in business.dimensions:
            if value is None or value == "NOT_EVALUABLE":
                missing.append(
                    f"{name}: frozen Feature 7 context unavailable/not evaluable"
                )
        # Reuse the bounded Feature 8 rules, never a mutable latest advisory run.
        challenge = RuleBasedChallenger().challenge(build_context(record, valuation))
        questions = tuple(
            dict.fromkeys(
                [item.text for item in challenge.questions_to_resolve]
                + [item.text for item in challenge.fragile_assumptions]
                + [item.text for item in challenge.missing_evidence]
                + list(snapshot.manual.thesis.next_evidence_to_collect)
            )
        )
        quality = UnderwritingQuality(
            tuple(item.text for item in snapshot.manual.supporting_evidence),
            tuple(item.text for item in snapshot.manual.disconfirming_evidence),
            summary.variant.conclusion,
            documented,
            sensitive.driver,
            sensitive.sensitivity.cagr_delta,
            sensitive.sensitivity.band,
            "OFFLINE_RULE_REVIEW_REQUIRED",
            RULE_MODEL_VERSION,
            questions,
            snapshot.manual.thesis.biggest_uncertainty,
            tuple(missing),
        )
        return Opportunity(summary, quality, business)
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ComparisonError):
            raise
        raise ComparisonError(f"{selection.ticker}:{selection.version}: {exc}") from exc


def _dimensions(opportunity: Opportunity) -> dict[str, float | bool | int | None]:
    return {
        "expected CAGR": opportunity.summary.expected_5y_cagr,
        "hurdle spread": opportunity.summary.return_spread,
        "Bear CAGR": opportunity.bear_cagr,
        "terminal loss protection": -opportunity.summary.loss_probability,
        "supporting evidence present": bool(opportunity.quality.supporting_evidence),
        "disconfirming evidence present": bool(
            opportunity.quality.disconfirming_evidence
        ),
        "business quality": opportunity.business.band("BUSINESS_QUALITY"),
        "local sensitivity protection": -abs(
            opportunity.quality.sensitivity_cagr_delta
        ),
        "documented variant": opportunity.quality.documented_variant,
    }


def compare_pair(left: Opportunity, right: Opportunity) -> PairwiseComparison:
    """Pareto core plus conservative conflict vetoes; absence is never neutral."""
    lhs, rhs = _dimensions(left), _dimensions(right)
    better_left: list[str] = []
    better_right: list[str] = []
    missing: list[str] = []
    for name in lhs:
        a, b = lhs[name], rhs[name]
        if a is None or b is None:
            missing.append(name)
        elif a > b + _EPSILON:
            better_left.append(name)
        elif b > a + _EPSILON:
            better_right.append(name)
    # Other known Feature 7 conflicts veto dominance without inventing missing bands.
    for dimension in ScreeningDimension:
        if dimension is ScreeningDimension.BUSINESS_QUALITY:
            continue
        a, b = left.business.band(dimension.value), right.business.band(dimension.value)
        if a is not None and b is not None:
            if a > b:
                better_left.append(dimension.value)
            elif b > a:
                better_right.append(dimension.value)

    def flags(advantages: list[str], other: list[str]) -> list[str]:
        result = []
        for dimension, flag in (
            ("expected CAGR", "HIGHER_EXPECTED_RETURN"),
            ("Bear CAGR", "BETTER_DOWNSIDE_PROTECTION"),
            ("documented variant", "STRONGER_VARIANT_VIEW"),
            ("business quality", "HIGHER_BUSINESS_QUALITY"),
        ):
            if dimension in advantages:
                result.append(flag)
        if "local sensitivity protection" in other:
            result.append("MORE_FRAGILE")
        if any(
            name in other
            for name in (
                "supporting evidence present",
                "disconfirming evidence present",
            )
        ):
            result.append("WEAKER_EVIDENCE")
        return result

    lf, rf = flags(better_left, better_right), flags(better_right, better_left)
    core = {
        "expected CAGR",
        "Bear CAGR",
        "supporting evidence present",
        "disconfirming evidence present",
        "business quality",
    }
    evidence_complete = all(
        opportunity.quality.supporting_evidence
        and opportunity.quality.disconfirming_evidence
        for opportunity in (left, right)
    )
    known_core = not core.intersection(missing) and evidence_complete
    dominated = None
    # A strict improvement must be in the core, not only in a guard dimension.
    if known_core and core.intersection(better_left) and not better_right:
        dominated = right.label
        rf.append("DOMINATED")
    elif known_core and core.intersection(better_right) and not better_left:
        dominated = left.label
        lf.append("DOMINATED")
    if better_left and better_right:
        conclusion = "TRADEOFF"
        lf.append("TRADEOFF")
        rf.append("TRADEOFF")
    elif dominated:
        conclusion = "DOMINATED"
    elif missing or not evidence_complete:
        conclusion = "INCOMPLETE"
    else:
        conclusion = "NO_CORE_DOMINANCE"
    tradeoff = (
        f"{left.label} advantages: {', '.join(better_left) or 'none established'}; "
        f"{right.label} advantages: {', '.join(better_right) or 'none established'}."
    )
    if missing:
        tradeoff += " Unknown: " + ", ".join(missing) + "."
    if not evidence_complete:
        tradeoff += " Missing investor evidence blocks dominance."
    return_leader = (
        left.label
        if "expected CAGR" in better_left
        else right.label
        if "expected CAGR" in better_right
        else None
    )
    capital = (
        f"{return_leader} has higher conditional expected CAGR. "
        if return_leader
        else "Neither has a higher conditional expected CAGR. "
    ) + (
        f"{dominated} is dominated on the documented core, with no known guard conflict."
        if dominated
        else "No overall capital preference established; inspect tradeoffs and unknowns."
    )
    attention = "; ".join(
        f"{item.label}: " + " / ".join(research_attention(item))
        for item in (left, right)
    )
    return PairwiseComparison(
        left.label,
        right.label,
        tuple(lf),
        tuple(rf),
        tuple(better_left),
        tuple(better_right),
        tuple(missing),
        conclusion,
        dominated,
        tradeoff,
        capital,
        attention,
    )


def research_attention(opportunity: Opportunity) -> tuple[str, ...]:
    quality = opportunity.quality
    reasons = []
    if not quality.supporting_evidence:
        reasons.append("Collect supporting evidence; presence is not verification.")
    if not quality.disconfirming_evidence:
        reasons.append("Collect disconfirming evidence; absence is not reassurance.")
    if opportunity.summary.return_spread > 0 and (
        not quality.supporting_evidence or not quality.disconfirming_evidence
    ):
        reasons.append(
            "Positive hurdle spread depends on incomplete evidence; validate before relying on it."
        )
    if quality.documented_variant:
        reasons.append(
            "Validate the documented variant view against its frozen rationales."
        )
    elif quality.documented_variant is None:
        reasons.append("Variant strength unknown: comparable consensus is incomplete.")
    else:
        reasons.append(
            "Document a rationale for the variant, or validate the aligned thesis."
        )
    if quality.sensitivity_band == "HIGH":
        reasons.append(
            f"Validate high local sensitivity to {quality.most_sensitive_driver}."
        )
    if quality.missing_dimensions:
        reasons.append(
            "Resolve explicit missing dimensions; do not treat them as neutral."
        )
    if quality.major_unresolved_questions:
        reasons.append(
            "Resolve offline challenger questions; they are advisory, not verified findings."
        )
    return tuple(reasons)


def compare_underwritings(
    store: SqliteStore, selections: tuple[UnderwritingSelection, ...]
) -> OpportunityComparison:
    if not 2 <= len(selections) <= 5:
        raise ComparisonError("Select 2 to 5 completed underwriting versions.")
    ordered = sorted(selections, key=lambda item: (item.ticker, item.version))
    opportunities = tuple(load_opportunity(store, item) for item in ordered)
    identities = [item.summary.underwriting_id for item in opportunities]
    if len(set(identities)) != len(identities):
        raise ComparisonError("Duplicate underwriting identity selected.")
    pairs = tuple(compare_pair(a, b) for a, b in combinations(opportunities, 2))
    enriched = []
    for item in opportunities:
        related = [pair for pair in pairs if item.label in (pair.left, pair.right)]
        flags = sorted(
            {
                flag
                for pair in related
                for flag in (
                    pair.left_flags if pair.left == item.label else pair.right_flags
                )
            }
        )
        enriched.append(
            replace(
                item,
                flags=tuple(flags),
                research_attention=research_attention(item),
                capital_attractiveness=" ".join(
                    pair.capital_attractiveness for pair in related
                ),
                key_tradeoff=" ".join(pair.key_tradeoff for pair in related),
                unresolved_issue=item.quality.biggest_uncertainty,
            )
        )
    return OpportunityComparison(tuple(enriched), pairs)


def comparison_rows(report: OpportunityComparison) -> list[dict[str, str]]:
    """Shared presentation, in the requested reading order, with explicit missingness."""
    columns: dict[str, dict[str, str]] = {}
    for item in report.opportunities:
        summary, quality = item.summary, item.quality
        bear, base, bull = summary.scenarios
        values = {
            "Frozen price / market date": f"${summary.current_price:.2f} / {summary.market_date}",
            "Expected 5Y CAGR": f"{summary.expected_5y_cagr:.2%}",
            "Required return": f"{summary.investor_policy.required_return:.2%}",
            "Spread over hurdle": f"{summary.return_spread:+.2%}",
            "Feature 8 classification": summary.classification,
            "Bear value/share": f"${bear.value_per_share:.2f}",
            "Bear CAGR / terminal return": f"{bear.implied_cagr:.2%} / {bear.terminal_return:+.2%}",
            "Base CAGR": f"{base.implied_cagr:.2%}",
            "Bull CAGR / terminal return": f"{bull.implied_cagr:.2%} / {bull.terminal_return:+.2%}",
            "Bear / Base / Bull probabilities": " / ".join(
                f"{outcome.probability.probability:.2%}"
                for outcome in summary.scenarios
            ),
            "Probability of terminal loss": f"{summary.loss_probability:.2%}",
            "Supporting evidence": "PRESENT (unverified)"
            if quality.supporting_evidence
            else "MISSING",
            "Disconfirming evidence": "PRESENT (unverified)"
            if quality.disconfirming_evidence
            else "MISSING",
            "Variant view": quality.variant_status,
            "Variant documentation": "UNKNOWN"
            if quality.documented_variant is None
            else str(quality.documented_variant),
            "Most sensitive driver": quality.most_sensitive_driver,
            "Local CAGR perturbation / band": f"{quality.sensitivity_cagr_delta:+.2%} / {quality.sensitivity_band}",
            "Priority": item.business.priority or "MISSING (not frozen)",
            "Setup type": item.business.setup_type or "MISSING (not frozen)",
            "Coverage": item.business.coverage or "MISSING (not frozen)",
            **{
                name.replace("_", " ").title(): value or "MISSING (not frozen)"
                for name, value in item.business.dimensions
            },
            "Challenger status": quality.challenger_status,
            "Unresolved challenger questions": " | ".join(
                quality.major_unresolved_questions
            )
            or "None recorded",
            "Biggest uncertainty": quality.biggest_uncertainty,
            "Missing dimensions": " | ".join(quality.missing_dimensions)
            or "None recorded",
            "Flags": ", ".join(item.flags) or "None established",
            "Immutable identity": f"{summary.underwriting_id} / {summary.underwriting_content_hash}",
            "Underwriting as of": summary.as_of_date,
        }
        columns[item.label] = values
    first = next(iter(columns.values()))
    return [
        {
            "Metric": metric,
            **{label: values[metric] for label, values in columns.items()},
        }
        for metric in first
    ]


def format_comparison(report: OpportunityComparison) -> str:
    rows = comparison_rows(report)
    compact = {
        "Expected 5Y CAGR",
        "Required return",
        "Spread over hurdle",
        "Bear CAGR / terminal return",
        "Probability of terminal loss",
        "Supporting evidence",
        "Disconfirming evidence",
        "Flags",
    }
    labels = [item.label for item in report.opportunities]
    lines = ["Opportunity Comparison", "Metric | " + " | ".join(labels)]
    lines.extend(
        row["Metric"] + " | " + " | ".join(row[label] for label in labels)
        for row in rows
        if row["Metric"] in compact
    )
    for item in report.opportunities:
        lines += [
            f"\n{item.label}",
            "Research attention: " + " ".join(item.research_attention),
            "Unresolved issue: " + item.unresolved_issue,
        ]
    for pair in report.pairs:
        lines += [
            f"\n{pair.left} vs {pair.right}: {pair.conclusion}",
            pair.key_tradeoff,
            "Capital attractiveness: " + pair.capital_attractiveness,
        ]
    lines.append(
        "\nDetails (frozen inputs; evidence presence is not evidence verification):"
    )
    lines.extend(
        row["Metric"] + " | " + " | ".join(row[label] for label in labels)
        for row in rows
        if row["Metric"] not in compact
    )
    lines.append(report.disclaimer)
    return "\n".join(lines)

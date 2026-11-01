"""Bounded offline falsification prompts, not an investment decision engine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from owner_lens.persistence import SqliteStore, UnderwritingRecord
from owner_lens.persistence.records import ChallengerRunRecord
from owner_lens.underwriting import SemanticType
from owner_lens.underwriting_summary import saved_valuation
from owner_lens.variant import compare_variant

CHALLENGER_VERSION = "underwriting-falsification-v1"
RULE_MODEL_VERSION = "offline-rules-v1"


class ChallengerError(ValueError):
    """Invalid read-only context or advisory output."""


@dataclass(frozen=True)
class ChallengerContext:
    json_payload: str


@dataclass(frozen=True)
class Citation:
    path: str
    source_category: SemanticType
    value_json: str


@dataclass(frozen=True)
class Challenge:
    text: str
    references: tuple[Citation, ...]
    evidence_available: bool = True
    category: SemanticType = SemanticType.JUDGMENT


@dataclass(frozen=True)
class ChallengerOutput:
    overall_assessment: Challenge
    strongest_argument_against: Challenge
    fragile_assumptions: tuple[Challenge, ...]
    probability_challenges: tuple[Challenge, ...]
    contradictory_evidence: tuple[Challenge, ...]
    missing_evidence: tuple[Challenge, ...]
    alternative_explanations: tuple[Challenge, ...]
    thesis_breaker_quality: Challenge
    variant_view_challenge: Challenge
    questions_to_resolve: tuple[Challenge, ...]
    category: SemanticType = SemanticType.JUDGMENT

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


class ChallengerBackend(Protocol):
    """Advisory boundary: receives a frozen value, never a store or retrieval tools."""

    @property
    def model_version(self) -> str: ...

    def challenge(self, context: ChallengerContext) -> ChallengerOutput: ...


def _resolve(data: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ChallengerError("Citation must be an absolute JSON pointer.")
    value = data
    try:
        for raw in pointer[1:].split("/"):
            part = raw.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ChallengerError(
            f"Citation path is not in frozen context: {pointer}"
        ) from exc
    return value


def _citation(context: dict[str, Any], path: str, category: SemanticType) -> Citation:
    return Citation(
        path,
        category,
        json.dumps(_resolve(context, path), sort_keys=True, allow_nan=False),
    )


class RuleBasedChallenger:
    """Transparent rules and questions; no language-model claims or inferred business facts."""

    model_version = RULE_MODEL_VERSION

    def challenge(self, context: ChallengerContext) -> ChallengerOutput:
        data = json.loads(context.json_payload)
        snapshot = data["snapshot"]
        manual = snapshot["manual"]
        variant = data["variant"]

        def finding(
            text: str, *sources: tuple[str, SemanticType], available: bool = True
        ) -> Challenge:
            return Challenge(
                text,
                tuple(_citation(data, path, category) for path, category in sources),
                available,
            )

        j, a, c = (
            SemanticType.JUDGMENT,
            SemanticType.ASSUMPTION,
            SemanticType.CALCULATION,
        )
        fragile: list[Challenge] = []
        missing: list[Challenge] = []
        probability: list[Challenge] = []
        drivers = variant["drivers"]
        most = max(
            enumerate(drivers),
            key=lambda pair: abs(pair[1]["sensitivity"]["cagr_delta"]),
        )
        strongest = finding(
            f"Local BASE fragility is greatest for {most[1]['driver']} under the documented 8D perturbations. "
            "This is not proof of its total contribution or business plausibility. What evidence supports it?",
            (f"/variant/drivers/{most[0]}/sensitivity", c),
        )
        optimistic = 0
        for i, driver in enumerate(drivers):
            history = driver["history"]
            assumptions = (f"/variant/drivers/{i}/assumption", a)
            if (
                history is None
                or history["minimum"] is None
                or history["maximum"] is None
            ):
                missing.append(
                    finding(
                        f"Historical range unavailable for {driver['driver']}; plausibility cannot be checked against history.",
                        (f"/variant/drivers/{i}/history", c),
                        available=False,
                    )
                )
            else:
                value, low, high = (
                    driver["assumption"],
                    history["minimum"],
                    history["maximum"],
                )
                if value < low or value > high:
                    fragile.append(
                        finding(
                            f"BASE {driver['driver']} lies outside its captured historical range. "
                            "A range exceedance is not proof it is wrong; what observable change justifies it?",
                            assumptions,
                            (
                                f"/variant/drivers/{i}/history",
                                SemanticType(history["category"]),
                            ),
                        )
                    )
                if (
                    value < low
                    if driver["driver"] == "share_count_cagr"
                    else value > high
                ):
                    optimistic += 1
            if driver["consensus"]["value"] is None:
                missing.append(
                    finding(
                        f"Comparable consensus unavailable for {driver['driver']}; do not treat its assumption as market-backed.",
                        (f"/variant/drivers/{i}/consensus", SemanticType.EXPECTATION),
                        available=False,
                    )
                )
        if optimistic >= 2:
            fragile.append(
                finding(
                    "Multiple valuation-favorable BASE assumptions exceed captured historical experience. "
                    "Test whether their joint realization is coherent, not merely each assumption separately.",
                    ("/variant/drivers", c),
                )
            )
        history_by_driver = {driver["driver"]: driver["history"] for driver in drivers}
        for i, scenario in enumerate(manual["scenarios"]):
            if scenario["name"] == "BASE":
                continue
            favorable: list[str] = []
            for driver, history in history_by_driver.items():
                if (
                    history is None
                    or history["minimum"] is None
                    or history["maximum"] is None
                ):
                    continue
                value = scenario[driver]
                outside = value < history["minimum"] or value > history["maximum"]
                if outside:
                    fragile.append(
                        finding(
                            f"{scenario['name']} {driver} lies outside captured historical experience. "
                            "Does its narrative justify this departure, and what would falsify it?",
                            (f"/snapshot/manual/scenarios/{i}", a),
                            ("/snapshot/historical_base_rates", c),
                        )
                    )
                is_favorable = (
                    value < history["minimum"]
                    if driver == "share_count_cagr"
                    else value > history["maximum"]
                )
                if is_favorable:
                    favorable.append(driver)
            if len(favorable) >= 2:
                fragile.append(
                    finding(
                        f"{scenario['name']} stacks multiple valuation-favorable departures from history. "
                        "Review the joint outcome and its probability, not independent justifications.",
                        (f"/snapshot/manual/scenarios/{i}", a),
                        ("/snapshot/manual/probability_distribution", j)
                        if manual.get("probability_distribution") is not None
                        else ("/snapshot/manual", j),
                    )
                )
        distribution = manual.get("probability_distribution")
        if distribution is None:
            missing.append(
                finding(
                    "Manually approved probabilities are unavailable; no probability or expected return is inferred.",
                    ("/snapshot/manual", j),
                    available=False,
                )
            )
        else:
            probability.append(
                finding(
                    "Numerical coherence does not establish narrative coherence. For each scenario, "
                    "which recorded evidence justifies its manually approved probability?",
                    ("/snapshot/manual/probability_distribution", j),
                    ("/snapshot/manual/scenarios", a),
                )
            )
            if not distribution.get("rationale"):
                probability.append(
                    finding(
                        "Distribution rationale is unavailable. Explain why these probabilities, especially downside, deserve confidence.",
                        ("/snapshot/manual/probability_distribution", j),
                        available=False,
                    )
                )
            bear = next(
                item for item in distribution["scenarios"] if item["name"] == "BEAR"
            )
            if bear["probability"] < 0.1:
                probability.append(
                    finding(
                        "BEAR probability is below the explicit 10% review threshold. "
                        "This rule does not estimate the correct probability; what disconfirming evidence supports so little downside weight?",
                        ("/snapshot/manual/probability_distribution", j),
                        ("/snapshot/manual/disconfirming_evidence", j),
                    )
                )
            if any(item["probability"] == 0 for item in distribution["scenarios"]):
                probability.append(
                    finding(
                        "A scenario has zero weight. What evidence justifies ruling it out rather than leaving residual uncertainty?",
                        ("/snapshot/manual/probability_distribution", j),
                    )
                )
        supporting = manual["supporting_evidence"]
        if not supporting:
            missing.append(
                finding(
                    "Supporting evidence is unavailable in this record; starting financial facts alone do not validate future assumptions.",
                    ("/snapshot/manual/supporting_evidence", j),
                    available=False,
                )
            )
        for i, item in enumerate(supporting[:20]):
            if (
                item["category"] not in ("FACT", "EXPECTATION")
                or not item["references"]
            ):
                missing.append(
                    finding(
                        "This supporting item is interpretation/assumption or lacks references. "
                        "Do not count it as independently verified support for a major driver.",
                        (
                            f"/snapshot/manual/supporting_evidence/{i}",
                            SemanticType(item["category"]),
                        ),
                    )
                )
        contradictory = tuple(
            finding(
                "Recorded disconfirming item: "
                + item["text"]
                + " What assumption or probability would change if this is confirmed? Its truth is not independently verified.",
                (
                    f"/snapshot/manual/disconfirming_evidence/{i}",
                    SemanticType(item["category"]),
                ),
            )
            for i, item in enumerate(manual["disconfirming_evidence"][:20])
        )
        for field in ("supporting_evidence", "disconfirming_evidence"):
            if len(manual[field]) > 20:
                missing.append(
                    finding(
                        f"Bounded review examined only the first 20 {field} items; review the remaining items manually.",
                        (f"/snapshot/manual/{field}", j),
                        available=False,
                    )
                )
        if not contradictory:
            contradictory = (
                finding(
                    "Disconfirming evidence is unavailable; absence in the record is not evidence that none exists.",
                    ("/snapshot/manual/disconfirming_evidence", j),
                    available=False,
                ),
            )
        breakers = finding(
            "NOT_ASSESSED_AUTOMATICALLY: textual breakers are recorded, but these rules cannot verify "
            "observability or specificity. Give each dependency/breaker a metric, threshold, source and monitoring date.",
            ("/snapshot/manual/thesis", j),
        )
        variant_challenge = finding(
            "No explicit identifiable variant view is captured. Is this a price/quality thesis rather than differentiated insight?"
            if variant["conclusion"] == "NO_IDENTIFIABLE_VARIANT_VIEW"
            else "A numerical disagreement and rationale are recorded; neither proves consensus is wrong. "
            "What evidence discriminates your view from consensus?",
            ("/variant/conclusion", c),
            ("/snapshot/manual/variant_rationales", j)
            if "variant_rationales" in manual
            else ("/snapshot/manual", j),
        )
        alternatives = (
            finding(
                "Alternative business explanations are not established by the captured structured fields. "
                "Formulate a competing causal explanation for the thesis, then identify evidence that distinguishes them; "
                "no company-specific alternative is invented here.",
                ("/snapshot/manual/thesis/biggest_uncertainty", j),
                ("/snapshot/manual/thesis/dependencies", j),
                available=False,
            ),
        )
        questions = (
            strongest,
            finding(
                "Which new observation would falsify the thesis rather than merely lower the target value?",
                ("/snapshot/manual/thesis/breakers", j),
                ("/snapshot/manual/thesis/next_evidence_to_collect", j),
            ),
            variant_challenge,
        )
        return ChallengerOutput(
            finding(
                "ADVISORY_REVIEW_REQUIRED: bounded offline rule checks, not a verified factual assessment "
                "or investment decision. Evidence/narrative quality requires human review.",
                ("/record", SemanticType.FACT),
            ),
            strongest,
            tuple(fragile),
            tuple(probability),
            contradictory,
            tuple(missing),
            alternatives,
            breakers,
            variant_challenge,
            questions,
        )


def build_context(record: UnderwritingRecord, valuation_json: str) -> ChallengerContext:
    # compare_variant validates the frozen evidence cutoff and the complete 8C contract.
    variant = compare_variant(record)
    data = {
        "record": {
            "underwriting_id": record.underwriting_id,
            "version": record.version,
            "content_hash": record.content_hash,
            "created_at": record.created_at,
            "as_of_date": record.as_of_date,
        },
        "snapshot": json.loads(record.snapshot_json),
        "valuation": json.loads(valuation_json),
        "variant": json.loads(variant.to_json()),
    }
    return ChallengerContext(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


def validate_output(output: ChallengerOutput, context: ChallengerContext) -> None:
    data = json.loads(context.json_payload)
    if not isinstance(output, ChallengerOutput):
        raise ChallengerError(
            "Backend must return the structured ChallengerOutput contract."
        )
    if output.category is not SemanticType.JUDGMENT:
        raise ChallengerError("Challenger output must be JUDGMENT.")
    for name, value in asdict(output).items():
        if name == "category":
            continue
        findings = value if isinstance(value, tuple) else (value,)
        for finding in findings:
            if (
                finding["category"] != SemanticType.JUDGMENT
                or not isinstance(finding["text"], str)
                or not finding["text"].strip()
                or not isinstance(finding["evidence_available"], bool)
            ):
                raise ChallengerError("Every challenge must be non-empty JUDGMENT.")
            if not finding["references"]:
                raise ChallengerError(
                    "Every challenge must cite frozen context fields."
                )
            for reference in finding["references"]:
                resolved = _resolve(data, reference["path"])
                if json.loads(reference["value_json"]) != resolved:
                    raise ChallengerError(
                        "Citation value does not match immutable context."
                    )
                if (
                    isinstance(resolved, dict)
                    and "category" in resolved
                    and resolved["category"] != reference["source_category"]
                ):
                    raise ChallengerError(
                        "Citation source category does not match captured evidence."
                    )
                parts = reference["path"].split("/")
                if parts[1:3] == ["variant", "drivers"] and len(parts) >= 5:
                    field = parts[4]
                    expected = {
                        "assumption": "ASSUMPTION",
                        "consensus": "EXPECTATION",
                        "sensitivity": "CALCULATION",
                        "rationale": "JUDGMENT",
                    }.get(field)
                    if (
                        expected is not None
                        and reference["source_category"] != expected
                    ):
                        raise ChallengerError(
                            "Citation source category does not match driver semantics."
                        )
    output.to_json()


def run_challenger(
    store: SqliteStore,
    record: UnderwritingRecord,
    *,
    backend: ChallengerBackend | None = None,
    now: datetime | None = None,
) -> ChallengerRunRecord:
    selected = backend if backend is not None else RuleBasedChallenger()
    if not selected.model_version.strip():
        raise ChallengerError(
            "Challenger backend must identify its model/rules version."
        )
    context = build_context(record, saved_valuation(store, record))
    output = selected.challenge(context)
    validate_output(output, context)
    created = now if now is not None else datetime.now(UTC)
    if created.tzinfo is None:
        raise ChallengerError("Challenger creation time must include timezone.")
    if created < datetime.fromisoformat(record.created_at):
        raise ChallengerError("Challenger run cannot predate underwriting creation.")
    return store.save_challenger_run(
        record,
        challenger_version=CHALLENGER_VERSION,
        model_version=selected.model_version,
        created_at=created.astimezone(UTC).isoformat(),
        context_json=context.json_payload,
        output_json=output.to_json(),
    )

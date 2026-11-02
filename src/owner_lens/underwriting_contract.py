"""Versioned investor authoring boundary and offline workbench-ready projection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from owner_lens.persistence import SqliteStore, UnderwritingRecord
from owner_lens.persistence.records import ChallengerRunRecord
from owner_lens.underwriting import (
    ManualUnderwriting,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    _conditions,
    _object,
    _retrieved_at,
    parse_manual_input,
)
from owner_lens.underwriting_summary import (
    UnderwritingSummary,
    saved_valuation,
    summarize_underwriting,
)
from owner_lens.valuation import MODEL_VERSION
from owner_lens.variant import VariantReport, compare_variant

AUTHORING_VERSION = 2


def parse_authoring_input(data: Any) -> ManualUnderwriting:
    """Only investor beliefs; identity, facts, estimates and calculations are not inputs."""
    root = _object(
        data,
        "authoring",
        {"authoring_version", "assumptions", "judgments"},
        {"authoring_version", "assumptions", "judgments"},
    )
    if (
        type(root["authoring_version"]) is not int
        or root["authoring_version"] != AUTHORING_VERSION
    ):
        raise UnderwritingError("authoring_version must be 2.")
    assumptions = _object(
        root["assumptions"],
        "assumptions",
        {"category", "scenarios"},
        {"category", "scenarios"},
    )
    if assumptions["category"] != SemanticType.ASSUMPTION:
        raise UnderwritingError("Assumptions section must be ASSUMPTION.")
    judgment_fields = {
        "category",
        "business_drivers",
        "supporting_evidence",
        "disconfirming_evidence",
        "variant_rationales",
        "probability_distribution",
        "investor_policy",
        "thesis",
    }
    judgment = _object(
        root["judgments"],
        "judgments",
        judgment_fields,
        judgment_fields - {"variant_rationales"},
    )
    if judgment["category"] != SemanticType.JUDGMENT:
        raise UnderwritingError("Judgments section must be JUDGMENT.")
    thesis = _object(
        judgment["thesis"],
        "thesis",
        {
            "category",
            "dependencies",
            "breakers",
            "biggest_uncertainty",
            "most_important_variable",
            "next_evidence_to_collect",
        },
        {
            "category",
            "dependencies",
            "breakers",
            "biggest_uncertainty",
            "most_important_variable",
            "next_evidence_to_collect",
        },
    )
    dependencies = _conditions(thesis["dependencies"])
    breakers = _conditions(thesis["breakers"])
    legacy = {key: value for key, value in judgment.items() if key != "category"}
    legacy.update(
        {
            "contract_version": 2,
            "forward_assumptions": [],
            "scenarios": assumptions["scenarios"],
            "thesis": {
                **thesis,
                "dependencies": [item.statement for item in dependencies],
                "breakers": [item.statement for item in breakers],
                "monitoring_dependencies": [asdict(item) for item in dependencies],
                "monitoring_breakers": [asdict(item) for item in breakers],
            },
        }
    )
    manual = parse_manual_input(legacy)
    if manual.probability_distribution is None or manual.investor_policy is None:
        raise UnderwritingError(
            "Version 2 requires approved probabilities and investor policy."
        )
    if not manual.probability_distribution.rationale:
        raise UnderwritingError(
            "Version 2 requires an explicit probability distribution rationale."
        )
    return manual


def validate_belief_links(snapshot: UnderwritingSnapshot, as_of_date: str) -> None:
    """Resolve JSON pointers into this snapshot, not mutable external evidence."""
    data = json.loads(snapshot.to_json())
    seen: set[str] = set()
    conditions = (
        *snapshot.manual.thesis.monitoring_dependencies,
        *snapshot.manual.thesis.monitoring_breakers,
    )
    identifiers = [item.condition_id for item in conditions]
    if len(set(identifiers)) != len(identifiers):
        raise UnderwritingError(
            "Thesis condition ids must be unique across dependencies and breakers."
        )
    if snapshot.schema_version == 2:
        cutoff = _retrieved_at(data["evidence"].get(
            "cutoff", as_of_date + "T23:59:59.999999+00:00"
        ))
        references = [
            reference
            for item in (*snapshot.manual.business_drivers,
                         *snapshot.manual.supporting_evidence,
                         *snapshot.manual.disconfirming_evidence)
            for reference in item.references
        ]
        references.extend(reference for rationale in snapshot.manual.variant_rationales for reference in rationale.references)
        references.extend(reference for condition in conditions for reference in condition.sources)
        for reference in references:
            if reference.observed_at and _retrieved_at(reference.observed_at) > cutoff:
                raise UnderwritingError("Evidence reference observation exceeds frozen cutoff.")
    for item in (
        *snapshot.manual.supporting_evidence,
        *snapshot.manual.disconfirming_evidence,
    ):
        if item.evidence_id:
            if item.evidence_id in seen:
                raise UnderwritingError(
                    "Duplicate evidence id across supporting/disconfirming evidence."
                )
            seen.add(item.evidence_id)
        if item.evidence_date and date.fromisoformat(
            item.evidence_date
        ) > date.fromisoformat(as_of_date):
            raise UnderwritingError("Evidence date exceeds underwriting as-of date.")
        for pointer in item.belief_references:
            prefixes = (
                "/manual/business_drivers/",
                "/manual/scenarios/",
                "/manual/thesis/monitoring_dependencies/",
                "/manual/thesis/monitoring_breakers/",
                "/manual/thesis/dependencies/",
                "/manual/thesis/breakers/",
            )
            if not pointer.startswith(prefixes):
                raise UnderwritingError(
                    "Evidence belief reference must point to a driver, assumption, dependency or breaker."
                )
            try:
                value: Any = data
                for token in pointer[1:].split("/"):
                    key = token.replace("~1", "/").replace("~0", "~")
                    value = value[int(key)] if isinstance(value, list) else value[key]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise UnderwritingError(
                    f"Unresolved evidence belief reference: {pointer}"
                ) from exc
            if value is None:
                raise UnderwritingError(
                    f"Evidence belief reference points to missing belief: {pointer}"
                )


@dataclass(frozen=True)
class MissingUnderwritingItem:
    section: str
    reason: str


@dataclass(frozen=True)
class UnderwritingProjection:
    """Domain values for 8F2; pages need not perform financial calculations."""

    record: UnderwritingRecord | None
    status: str
    snapshot: UnderwritingSnapshot | None
    valuation_json: str | None
    summary: UnderwritingSummary | None
    variant: VariantReport | None
    challenger_runs: tuple[ChallengerRunRecord, ...]
    missing_evidence: tuple[MissingUnderwritingItem, ...]
    projection_version: str = "underwriting-read-v1"


def project_underwriting(
    store: SqliteStore,
    ticker: str,
    *,
    version: int | None = None,
) -> UnderwritingProjection:
    """Read one exact/latest record; never fetch evidence, persist or invent inputs."""
    records = store.list_underwriting(ticker.strip().upper())
    if not records:
        if version is not None:
            raise UnderwritingError(
                f"Underwriting {ticker} version {version} not found."
            )
        return UnderwritingProjection(
            None,
            "NOT_CREATED",
            None,
            None,
            None,
            None,
            (),
            (MissingUnderwritingItem("underwriting", "No immutable record created."),),
        )
    selected = next(
        (
            item
            for item in reversed(records)
            if version is None or item.version == version
        ),
        None,
    )
    if selected is None:
        raise UnderwritingError(f"Underwriting {ticker} version {version} not found.")
    snapshot = UnderwritingSnapshot.from_json(selected.snapshot_json)
    validate_belief_links(snapshot, selected.as_of_date)
    missing: list[MissingUnderwritingItem] = []
    evidence = json.loads(snapshot.evidence_json)
    for item in snapshot.starting_financial_state:
        if item.value is None:
            missing.append(
                MissingUnderwritingItem(
                    item.name, item.missing_reason or "Starting fact unavailable."
                )
            )
    for field in ("supporting_evidence", "disconfirming_evidence"):
        if not getattr(snapshot.manual, field):
            missing.append(
                MissingUnderwritingItem(field, "No investor evidence recorded.")
            )
    for field in ("eod_price", "market_expectations"):
        if evidence.get(field, {}).get("missing_reason"):
            missing.append(
                MissingUnderwritingItem(field, evidence[field]["missing_reason"])
            )
    for estimate in evidence.get("market_expectations", {}).get("snapshots", []):
        if estimate.get("missing_reason"):
            missing.append(
                MissingUnderwritingItem(
                    estimate["source"]["dataset"],
                    estimate["missing_reason"],
                )
            )
    for kind, conditions in (
        ("dependencies", snapshot.manual.thesis.monitoring_dependencies),
        ("breakers", snapshot.manual.thesis.monitoring_breakers),
    ):
        if not conditions:
            missing.append(
                MissingUnderwritingItem(
                    kind,
                    "Legacy text only; structured monitoring metadata unavailable.",
                )
            )
        for condition in conditions:
            absent = [
                name
                for name in ("observable", "threshold", "sources")
                if getattr(condition, name) in (None, (), "")
            ]
            if condition.operator is not None and condition.source_family and "sources" in absent:
                absent.remove("sources")
            if not condition.cadence and not condition.monitoring_cadence and not condition.monitoring_date:
                absent.append("monitoring cadence/date")
            if absent:
                missing.append(
                    MissingUnderwritingItem(
                        condition.condition_id, "Missing " + ", ".join(absent)
                    )
                )
    valuation_json = store.get_valuation(selected.underwriting_id, MODEL_VERSION)
    summary = None
    variant = None
    if valuation_json is None:
        missing.append(
            MissingUnderwritingItem(
                "valuation", "No saved valuation for this exact underwriting version."
            )
        )
    else:
        valuation_json = saved_valuation(store, selected)
        variant = compare_variant(selected)
        for driver in variant.drivers:
            if driver.consensus.value is None:
                missing.append(
                    MissingUnderwritingItem(
                        driver.driver,
                        driver.consensus.reason or "Consensus unavailable.",
                    )
                )
        if (
            snapshot.manual.probability_distribution is not None
            and snapshot.manual.investor_policy is not None
        ):
            summary = summarize_underwriting(selected, valuation_json)
    for field in ("probability_distribution", "investor_policy"):
        if getattr(snapshot.manual, field) is None:
            missing.append(
                MissingUnderwritingItem(
                    field, "Not approved in this underwriting version."
                )
            )
    runs = store.list_challenger_runs(selected.underwriting_id)
    if not runs:
        missing.append(
            MissingUnderwritingItem(
                "challenger", "No saved advisory run for this version."
            )
        )
    else:
        output = json.loads(runs[-1].output_json)
        for section, findings in output.items():
            if isinstance(findings, list):
                for finding in findings:
                    if not finding["evidence_available"]:
                        missing.append(
                            MissingUnderwritingItem(section, finding["text"])
                        )
    status = (
        "SUMMARY_READY"
        if summary is not None
        else "VALUED"
        if valuation_json
        else "CAPTURED"
    )
    return UnderwritingProjection(
        selected,
        status,
        snapshot,
        valuation_json,
        summary,
        variant,
        runs,
        tuple(missing),
    )

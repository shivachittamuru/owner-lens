"""JSON-first underwriting validation, immutable approval and analysis workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from owner_lens.challenger import (
    CHALLENGER_VERSION,
    ChallengerError,
    RuleBasedChallenger,
    build_context,
    run_challenger,
)
from owner_lens.persistence import (
    SqliteStore,
    UnderwritingRecord,
    compute_content_hash,
)
from owner_lens.persistence.errors import PersistenceError
from owner_lens.persistence.records import ChallengerRunRecord
from owner_lens.underwriting import (
    UnderwritingError,
    UnderwritingInputs,
    UnderwritingSnapshot,
    capture_underwriting_inputs,
    save_underwriting_inputs,
)
from owner_lens.underwriting_authoring import review_authoring
from owner_lens.underwriting_contract import parse_authoring_input
from owner_lens.underwriting_summary import (
    SummaryError,
    UnderwritingSummary,
    summarize_underwriting,
)
from owner_lens.valuation import ValuationError, run_valuation
from owner_lens.variant import VariantError, VariantReport, compare_variant
from owner_lens.workbench.data import WorkbenchSource


@dataclass(frozen=True)
class UnderwritingPreview:
    ticker: str
    expected_latest_version: int
    latest_record: UnderwritingRecord | None
    authoring_hash: str
    inputs: UnderwritingInputs
    snapshot: UnderwritingSnapshot

    @property
    def proposed_version(self) -> int:
        return self.expected_latest_version + 1


@dataclass(frozen=True)
class AnalysisStage:
    name: str
    succeeded: bool
    detail: str


@dataclass(frozen=True)
class UnderwritingCompletion:
    record: UnderwritingRecord
    stages: tuple[AnalysisStage, ...]
    valuation_json: str | None
    summary: UnderwritingSummary | None
    variant: VariantReport | None
    challenger_run: ChallengerRunRecord | None

    @property
    def complete(self) -> bool:
        return all(stage.succeeded for stage in self.stages)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UnderwritingError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _parse_authoring_json(raw_json: str, ticker: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_json, object_pairs_hook=_unique_keys)
    except json.JSONDecodeError as exc:
        raise UnderwritingError(
            f"Invalid JSON syntax at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc
    if isinstance(payload, dict):
        identity = payload.get("ticker")
        security = payload.get("security")
        if isinstance(security, str):
            identity = security
        elif isinstance(security, dict):
            identity = security.get("ticker", security.get("symbol", identity))
        if isinstance(identity, str) and identity.strip().upper() != ticker:
            raise UnderwritingError(
                f"Ticker/security does not match current company {ticker}."
            )
    parse_authoring_input(payload)
    return payload


def preview_underwriting(
    source: WorkbenchSource,
    ticker: str,
    raw_json: str,
    *,
    now: datetime | None = None,
) -> UnderwritingPreview:
    """Validate existing Authoring v2 JSON and freeze the preview inputs without saving."""
    if not isinstance(source.store, SqliteStore):
        raise UnderwritingError("Underwriting requires the SQLite evidence store.")
    symbol = ticker.strip().upper()
    payload = _parse_authoring_json(raw_json, symbol)
    records = source.store.list_underwriting(symbol)
    latest = records[-1] if records else None
    latest_version = latest.version if latest is not None else 0
    manual = parse_authoring_input(payload)
    inputs = capture_underwriting_inputs(
        source, symbol, as_of_date=manual.as_of_date, now=now
    )
    reviewed = review_authoring(payload, inputs)
    return UnderwritingPreview(
        symbol,
        latest_version,
        latest,
        compute_content_hash(raw_json.encode()),
        inputs,
        reviewed,
    )


def complete_underwriting_analysis(
    store: SqliteStore,
    record: UnderwritingRecord,
    *,
    now: datetime | None = None,
) -> UnderwritingCompletion:
    """Run or safely retry deterministic analysis for one exact immutable version."""
    stages: list[AnalysisStage] = []
    valuation_json: str | None = None
    summary: UnderwritingSummary | None = None
    variant: VariantReport | None = None
    challenger_run: ChallengerRunRecord | None = None

    try:
        valuation_json = run_valuation(store, record)
        stages.append(AnalysisStage("Valuation", True, "Saved for this underwriting version."))
    except (ValuationError, PersistenceError) as exc:
        stages.append(AnalysisStage("Valuation", False, str(exc)))

    try:
        variant = compare_variant(record)
        stages.append(AnalysisStage("Variant and sensitivity", True, "Derived from approved assumptions."))
    except (VariantError, PersistenceError) as exc:
        stages.append(AnalysisStage("Variant and sensitivity", False, str(exc)))

    if valuation_json is None:
        stages.append(
            AnalysisStage("Expected return", False, "Blocked because valuation did not complete.")
        )
        stages.append(
            AnalysisStage("Challenger", False, "Blocked because valuation did not complete.")
        )
    else:
        try:
            summary = summarize_underwriting(record, valuation_json)
            stages.append(
                AnalysisStage("Expected return", True, "Uses the required return approved in this underwriting.")
            )
        except (SummaryError, ValuationError, VariantError, PersistenceError) as exc:
            stages.append(AnalysisStage("Expected return", False, str(exc)))

        try:
            context = build_context(record, valuation_json)
            input_hash = compute_content_hash(context.json_payload.encode())
            expected_model = RuleBasedChallenger().model_version
            existing = next(
                (
                    run
                    for run in reversed(store.list_challenger_runs(record.underwriting_id))
                    if run.challenger_version == CHALLENGER_VERSION
                    and run.model_version == expected_model
                    and run.input_content_hash == input_hash
                ),
                None,
            )
            challenger_run = existing or run_challenger(store, record, now=now)
            stages.append(
                AnalysisStage(
                    "Challenger",
                    True,
                    "Reused the matching saved run." if existing else "Saved for this underwriting version.",
                )
            )
        except (ChallengerError, SummaryError, PersistenceError) as exc:
            stages.append(AnalysisStage("Challenger", False, str(exc)))

    return UnderwritingCompletion(
        record, tuple(stages), valuation_json, summary, variant, challenger_run
    )


def complete_underwriting(
    source: WorkbenchSource,
    ticker: str,
    raw_json: str,
    *,
    preview: UnderwritingPreview | None = None,
    now: datetime | None = None,
) -> UnderwritingCompletion:
    """Validate, append one approved version, then run its deterministic analysis."""
    if not isinstance(source.store, SqliteStore):
        raise UnderwritingError("Underwriting requires the SQLite evidence store.")
    reviewed = preview or preview_underwriting(source, ticker, raw_json, now=now)
    if reviewed.ticker != ticker.strip().upper():
        raise UnderwritingError("Validated preview belongs to a different company.")
    if reviewed.authoring_hash != compute_content_hash(raw_json.encode()):
        raise UnderwritingError("JSON changed after validation. Validate the preview again.")
    security = next(
        (item for item in source.store.list_securities() if item.symbol == reviewed.ticker),
        None,
    )
    if security is None or security.security_id != reviewed.inputs.security_id:
        raise UnderwritingError(
            "Ticker/security does not match the current company evidence."
        )
    record = save_underwriting_inputs(
        source,
        reviewed.inputs,
        reviewed.snapshot.manual,
        expected_latest_version=reviewed.expected_latest_version,
        now=now,
    )
    return complete_underwriting_analysis(source.store, record, now=now)

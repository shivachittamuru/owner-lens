"""Single deterministic five-year terminal equity-FCF-multiple valuation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from owner_lens.persistence import SqliteStore, UnderwritingRecord, compute_content_hash
from owner_lens.underwriting import (
    ScenarioAssumption,
    SemanticType,
    UnderwritingError,
    UnderwritingSnapshot,
    parse_scenarios,
)

MODEL_VERSION = "equity-fcf-multiple-5y-v1"


class ValuationError(ValueError):
    """Missing or invalid immutable valuation inputs or non-finite results."""


@dataclass(frozen=True)
class ScenarioValuation:
    assumptions: ScenarioAssumption
    year5_revenue: float
    year5_fcf: float
    year5_diluted_shares: float
    year5_fcf_per_share: float
    year5_equity_value: float
    year5_value_per_share: float
    implied_5y_cagr: float
    category: SemanticType = SemanticType.CALCULATION


@dataclass(frozen=True)
class ValuationResult:
    underwriting_id: str
    underwriting_version: int
    underwriting_content_hash: str
    ticker: str
    security_id: int
    as_of_date: str
    latest_fiscal_year: int
    starting_revenue: float
    starting_diluted_shares: float
    current_price: float
    market_date: str
    price_snapshot_id: int
    price_content_hash: str
    price_fetched_at: str
    price_currency: str | None
    scenarios: tuple[ScenarioValuation, ...]
    model_version: str = MODEL_VERSION
    horizon_years: int = 5
    input_category: SemanticType = SemanticType.FACT
    category: SemanticType = SemanticType.CALCULATION

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValuationError(f"{name} requires a finite number, not missing/text/bool.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValuationError(f"{name} is outside numeric range.") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValuationError(
            f"{name} must be finite{' and positive' if positive else ''}."
        )
    return number


def value_underwriting(record: UnderwritingRecord) -> ValuationResult:
    """Pure computation: no market/evidence reads and no assumption defaults."""
    if compute_content_hash(record.snapshot_json.encode()) != record.content_hash:
        raise ValuationError("Underwriting content hash failed integrity verification.")
    try:
        snapshot = UnderwritingSnapshot.from_json(record.snapshot_json)
        scenarios = parse_scenarios(
            [asdict(item) for item in snapshot.manual.scenarios]
        )
    except (UnderwritingError, ValueError, KeyError, TypeError) as exc:
        raise ValuationError(f"Invalid underwriting/scenario contract: {exc}") from exc
    if (
        snapshot.manual.as_of_date is not None
        and snapshot.manual.as_of_date != record.as_of_date
    ):
        raise ValuationError(
            "Underwriting as-of date is inconsistent with its snapshot."
        )
    facts = {item.name: item for item in snapshot.starting_financial_state}
    if len(facts) != len(snapshot.starting_financial_state):
        raise ValuationError("Duplicate starting financial facts.")
    for name, unit in (("revenue", "USD"), ("diluted_shares", "shares")):
        fact = facts.get(name)
        if fact is None or fact.category is not SemanticType.FACT or fact.unit != unit:
            raise ValuationError(f"Starting {name} must be a persisted FACT in {unit}.")
        if fact.fiscal_year != snapshot.latest_fiscal_year:
            raise ValuationError(
                "Starting financial facts must use the same latest fiscal year."
            )
    revenue = _number(facts["revenue"].value, "Starting revenue", positive=True)
    shares = _number(
        facts["diluted_shares"].value, "Starting diluted shares", positive=True
    )
    try:
        market = json.loads(snapshot.evidence_json)["eod_price"]
        price_evidence = market["value"]
        if market["category"] != SemanticType.FACT or price_evidence is None:
            raise ValuationError("Missing persisted current EOD price FACT.")
        if price_evidence["evidence_kind"] != SemanticType.FACT:
            raise ValuationError("EOD price source must be FACT.")
        if price_evidence.get("currency") not in (None, "USD"):
            raise ValuationError(
                "Price currency must match USD financial facts; no FX conversion."
            )
        price = _number(price_evidence["close"], "Current EOD price", positive=True)
        market_date = price_evidence["market_date"]
        if (
            not isinstance(market_date, str)
            or date.fromisoformat(market_date).isoformat() != market_date
        ):
            raise ValuationError("Market date must be YYYY-MM-DD.")
        if date.fromisoformat(market_date) > date.fromisoformat(record.as_of_date):
            raise ValuationError("Market date is after underwriting as-of date.")
        price_id = price_evidence["snapshot_id"]
        price_hash = price_evidence["content_hash"]
        fetched_at = price_evidence["fetched_at"]
        fetched = datetime.fromisoformat(fetched_at)
        fetched = (
            fetched.replace(tzinfo=UTC)
            if fetched.tzinfo is None
            else fetched.astimezone(UTC)
        )
        if fetched.date() > date.fromisoformat(
            record.as_of_date
        ) or fetched > datetime.fromisoformat(record.created_at):
            raise ValuationError("Price was retrieved after the underwriting cutoff.")
        if isinstance(price_id, bool) or not isinstance(price_id, int) or price_id <= 0:
            raise ValuationError("Price requires a positive persisted snapshot ID.")
        if not isinstance(price_hash, str) or not price_hash.strip():
            raise ValuationError("Price requires a persisted content hash.")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValuationError(
            f"Missing/malformed persisted EOD price provenance: {exc}"
        ) from exc
    except ValueError as exc:
        if isinstance(exc, ValuationError):
            raise
        raise ValuationError(
            f"Invalid price/underwriting date metadata: {exc}"
        ) from exc
    results: list[ScenarioValuation] = []
    for scenario in scenarios:
        try:
            revenue5 = _number(
                revenue * (1 + scenario.revenue_cagr) ** 5,
                f"{scenario.name} year-5 revenue",
                positive=True,
            )
            shares5 = _number(
                shares * (1 + scenario.share_count_cagr) ** 5,
                f"{scenario.name} year-5 shares",
                positive=True,
            )
            fcf5 = _number(
                revenue5 * scenario.fcf_margin_year5, f"{scenario.name} year-5 FCF"
            )
            fcf_per_share5 = _number(
                fcf5 / shares5, f"{scenario.name} year-5 FCF/share"
            )
            equity5 = _number(
                fcf5 * scenario.terminal_fcf_multiple, f"{scenario.name} equity value"
            )
            value5 = _number(equity5 / shares5, f"{scenario.name} value/share")
            cagr = _number(
                (value5 / price) ** (1 / 5) - 1, f"{scenario.name} implied CAGR"
            )
        except (OverflowError, ZeroDivisionError) as exc:
            raise ValuationError(
                f"{scenario.name} assumptions overflow/underflow numeric range."
            ) from exc
        results.append(
            ScenarioValuation(
                scenario, revenue5, fcf5, shares5, fcf_per_share5, equity5, value5, cagr
            )
        )
    return ValuationResult(
        record.underwriting_id,
        record.version,
        record.content_hash,
        record.ticker,
        record.security_id,
        record.as_of_date,
        snapshot.latest_fiscal_year,
        revenue,
        shares,
        price,
        market_date,
        price_id,
        price_hash,
        fetched_at,
        price_evidence.get("currency"),
        tuple(results),
    )


def run_valuation(store: SqliteStore, record: UnderwritingRecord) -> str:
    """Persist once per immutable underwriting/model version, then reuse exactly."""
    existing = store.get_valuation(record.underwriting_id, MODEL_VERSION)
    if existing is not None:
        return existing
    result_json = value_underwriting(record).to_json()
    return store.save_valuation(record.underwriting_id, MODEL_VERSION, result_json)

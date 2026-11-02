"""Explicit, cash-funded downside budgets, not optimization or trade instructions."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from owner_lens.decisions import load_decision_json, read_decision
from owner_lens.opportunity_comparison import UnderwritingSelection, load_opportunity
from owner_lens.persistence import SqliteStore, compute_content_hash
from owner_lens.underwriting import _object, _retrieved_at

PORTFOLIO_VERSION = "manual-portfolio-v1"
SIZING_VERSION = "downside-budget-sizing-v1"
DISCLAIMER = (
    "Conditional sizing guidance, not an execution instruction. The zero lower bound "
    "does not require a position; ABOVE_POLICY_RANGE does not instruct a trim. "
    "Shadow choices, including WATCH/PASS, are counterfactual, never executed holdings."
)
EPSILON = 1e-12


class SizingError(ValueError):
    """Missing explicit inputs, inconsistent identities or unsupported portfolio state."""


class AssetType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    BOND = "BOND"
    OTHER = "OTHER"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value: Any, label: str, *, ratio: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SizingError(f"{label} must be a finite nonnegative number.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise SizingError(f"{label} exceeds numeric range.") from exc
    if not math.isfinite(result) or result < 0 or (ratio and result > 1):
        raise SizingError(
            f"{label} must be finite and in {'[0,1]' if ratio else '[0,infinity)'}."
        )
    return result


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SizingError(f"{label} must be non-empty text or null.")
    return value


def _tags(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(tag, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", tag)
        for tag in value
    ):
        raise SizingError(
            "exposure_tags must be explicit uppercase tags, [] for none, or null for unknown."
        )
    if len(set(value)) != len(value):
        raise SizingError("Duplicate exposure tags.")
    return tuple(sorted(value))


@dataclass(frozen=True)
class ExposureContext:
    sector: str | None
    industry: str | None
    exposure_tags: tuple[str, ...] | None

    @classmethod
    def parse(cls, data: Any) -> ExposureContext:
        obj = _object(
            data,
            "exposure context",
            {"sector", "industry", "exposure_tags"},
            {"sector", "industry", "exposure_tags"},
        )
        return cls(
            _optional_text(obj["sector"], "sector"),
            _optional_text(obj["industry"], "industry"),
            _tags(obj["exposure_tags"]),
        )


@dataclass(frozen=True)
class Holding:
    ticker: str
    security_id: int | None
    asset_type: AssetType
    input_amount: float
    weight: float
    context: ExposureContext
    notes: str | None


@dataclass(frozen=True)
class PortfolioSnapshot:
    snapshot_id: str
    created_at: str
    as_of_date: str
    basis: str
    holdings: tuple[Holding, ...]
    cash_input: float | None
    cash_weight: float | None
    normalization_total: float
    notes: str | None
    currency: str | None = None
    model_version: str = PORTFOLIO_VERSION
    category: str = "JUDGMENT"

    def to_json(self) -> str:
        return canonical_json(asdict(self))

    @classmethod
    def from_json(cls, payload: str) -> PortfolioSnapshot:
        try:
            data = load_decision_json(payload)
            fields = set(cls.__dataclass_fields__)
            obj = _object(data, "portfolio snapshot", fields, fields)
            holdings = []
            if not isinstance(obj["holdings"], list):
                raise SizingError("Snapshot holdings must be a list.")
            for raw in obj["holdings"]:
                holding_fields = set(Holding.__dataclass_fields__)
                item = _object(raw, "snapshot holding", holding_fields, holding_fields)
                holdings.append(
                    Holding(
                        item["ticker"],
                        item["security_id"],
                        AssetType(item["asset_type"]),
                        item["input_amount"],
                        item["weight"],
                        ExposureContext.parse(item["context"]),
                        item["notes"],
                    )
                )
            result = cls(**{**obj, "holdings": tuple(holdings)})
            result.validate()
            return result
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            if isinstance(exc, SizingError):
                raise
            raise SizingError(f"Invalid portfolio snapshot: {exc}") from exc

    def validate(self) -> None:
        if self.model_version != PORTFOLIO_VERSION or self.category != "JUDGMENT":
            raise SizingError("Unsupported portfolio model/category.")
        if self.basis not in ("MARKET_VALUE", "WEIGHT"):
            raise SizingError("basis must be MARKET_VALUE or WEIGHT.")
        if self.basis == "MARKET_VALUE":
            if not isinstance(self.currency, str) or not re.fullmatch(
                r"[A-Z]{3}", self.currency
            ):
                raise SizingError(
                    "MARKET_VALUE requires an explicit three-letter currency; no currency conversion is performed."
                )
        elif self.currency is not None:
            raise SizingError(
                "WEIGHT has no monetary currency or inferred portfolio size."
            )
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise SizingError("Missing portfolio snapshot ID.")
        created = datetime.fromisoformat(self.created_at)
        if created.tzinfo is None:
            raise SizingError("Portfolio creation time requires timezone.")
        as_of = date.fromisoformat(self.as_of_date)
        if (
            as_of.isoformat() != self.as_of_date
            or as_of > created.astimezone(UTC).date()
        ):
            raise SizingError(
                "Portfolio as-of date must be YYYY-MM-DD, not in the future."
            )
        _optional_text(self.notes, "notes")
        tickers: set[str] = set()
        identities: set[int] = set()
        amounts = []
        for holding in self.holdings:
            UnderwritingSelection(holding.ticker, 1)
            if holding.ticker in tickers:
                raise SizingError(
                    "Duplicate holding ticker; consolidate lots explicitly."
                )
            tickers.add(holding.ticker)
            if holding.security_id is not None:
                if (
                    type(holding.security_id) is not int
                    or holding.security_id < 1
                    or holding.security_id in identities
                ):
                    raise SizingError("Invalid/duplicate holding security identity.")
                identities.add(holding.security_id)
            amounts.append(
                _number(
                    holding.input_amount, "holding amount", ratio=self.basis == "WEIGHT"
                )
            )
            _number(holding.weight, "holding weight", ratio=True)
            _optional_text(holding.notes, "holding notes")
        cash = (
            _number(self.cash_input, "cash", ratio=self.basis == "WEIGHT")
            if self.cash_input is not None
            else None
        )
        _number(self.normalization_total, "normalization_total")
        if self.cash_weight is not None:
            _number(self.cash_weight, "cash_weight", ratio=True)
        total = math.fsum([*amounts, *([cash] if cash is not None else [])])
        if not math.isfinite(total) or total <= 0 or total != self.normalization_total:
            raise SizingError(
                "Portfolio denominator must be positive, finite and match input amounts."
            )
        for holding in self.holdings:
            if holding.weight != holding.input_amount / total:
                raise SizingError(
                    "Portfolio weights differ from deterministic normalization."
                )
        if self.cash_weight != (cash / total if cash is not None else None):
            raise SizingError(
                "Cash weight differs from normalization; missing cash must remain null."
            )


def _resolve_security(store: SqliteStore, ticker: str) -> int | None:
    history = store.list_underwriting(ticker)
    if history:
        return history[0].security_id
    return next(
        (item.security_id for item in store.list_securities() if item.symbol == ticker),
        None,
    )


def validate_portfolio_sources(
    store: SqliteStore, portfolio: PortfolioSnapshot
) -> None:
    for holding in portfolio.holdings:
        if holding.security_id != _resolve_security(store, holding.ticker):
            raise SizingError(
                f"{holding.ticker}: security identity does not match persisted identity."
            )


def create_portfolio(
    store: SqliteStore, data: Any, *, now: datetime | None = None
) -> PortfolioSnapshot:
    try:
        obj = _object(
            data,
            "portfolio input",
            {"as_of_date", "basis", "holdings", "cash", "notes", "currency"},
            {"as_of_date", "basis", "holdings"},
        )
        basis = obj["basis"]
        if basis not in ("MARKET_VALUE", "WEIGHT") or not isinstance(
            obj["holdings"], list
        ):
            raise SizingError(
                "Use MARKET_VALUE or WEIGHT and an explicit holdings list."
            )
        created = now or datetime.now(UTC)
        if created.tzinfo is None:
            raise SizingError("Portfolio creation time requires timezone.")
        holdings = []
        for raw in obj["holdings"]:
            amount_field = "market_value" if basis == "MARKET_VALUE" else "weight"
            item = _object(
                raw,
                "holding",
                {
                    "ticker",
                    "security_id",
                    "asset_type",
                    amount_field,
                    "sector",
                    "industry",
                    "exposure_tags",
                    "notes",
                },
                {"ticker", "asset_type", amount_field},
            )
            ticker = item["ticker"]
            UnderwritingSelection(ticker, 1)
            resolved = _resolve_security(store, ticker)
            identity = item.get("security_id", resolved)
            if identity != resolved or (
                identity is not None and type(identity) is not int
            ):
                raise SizingError(
                    f"{ticker}: supplied security_id does not match persisted identity."
                )
            holdings.append(
                Holding(
                    ticker,
                    identity,
                    AssetType(item["asset_type"]),
                    _number(item[amount_field], amount_field, ratio=basis == "WEIGHT"),
                    0,
                    ExposureContext.parse(
                        {
                            key: item.get(key)
                            for key in ("sector", "industry", "exposure_tags")
                        }
                    ),
                    _optional_text(item.get("notes"), "holding notes"),
                )
            )
        cash = (
            _number(obj["cash"], "cash", ratio=basis == "WEIGHT")
            if obj.get("cash") is not None
            else None
        )
        total = math.fsum(
            [
                *(item.input_amount for item in holdings),
                *([cash] if cash is not None else []),
            ]
        )
        if not math.isfinite(total) or total <= 0:
            raise SizingError(
                "Portfolio input amounts must have a positive finite sum."
            )
        portfolio = PortfolioSnapshot(
            str(uuid4()),
            created.astimezone(UTC).isoformat(),
            obj["as_of_date"],
            basis,
            tuple(
                replace(item, weight=item.input_amount / total)
                for item in sorted(holdings, key=lambda item: item.ticker)
            ),
            cash,
            cash / total if cash is not None else None,
            total,
            _optional_text(obj.get("notes"), "notes"),
            obj.get("currency"),
        )
        portfolio.validate()
        store.save_portfolio_snapshot(portfolio.to_json())
        return portfolio
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        if isinstance(exc, SizingError):
            raise
        raise SizingError(f"Cannot create portfolio snapshot: {exc}") from exc


@dataclass(frozen=True)
class SizingPolicy:
    max_single_position_weight: float
    max_initial_position_weight: float
    max_portfolio_bear_loss_contribution: float
    max_sector_weight: float
    min_cash_reserve: float
    starter_position_weight: float
    max_thesis_weight: float
    severe_bear_loss_threshold: float
    category: str

    @classmethod
    def parse(cls, data: Any) -> SizingPolicy:
        fields = set(cls.__dataclass_fields__)
        obj = _object(data, "explicit sizing policy", fields, fields)
        if obj["category"] != "JUDGMENT":
            raise SizingError("Every sizing policy must be explicit JUDGMENT.")
        numbers = {
            key: _number(obj[key], key, ratio=True) for key in fields - {"category"}
        }
        if (
            not numbers["starter_position_weight"]
            <= numbers["max_initial_position_weight"]
            <= numbers["max_single_position_weight"]
        ):
            raise SizingError(
                "Require starter <= max_initial <= max_single_position_weight."
            )
        if numbers["severe_bear_loss_threshold"] == 0:
            raise SizingError("severe_bear_loss_threshold must be positive.")
        return cls(**numbers, category="JUDGMENT")


def _identity_match(holding: Holding, security_id: int, ticker: str) -> bool:
    return (
        holding.security_id == security_id
        if holding.security_id is not None
        else holding.ticker == ticker
    )


def size_position(
    store: SqliteStore,
    selection: UnderwritingSelection,
    portfolio_id: str,
    policy_data: Any,
    *,
    context_data: Any = None,
    proposed_increment: float | None = None,
    decision_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure preview over selected immutable state; output has no generated timestamp."""
    try:
        policy = SizingPolicy.parse(policy_data)
        opportunity = load_opportunity(store, selection)
        record = next(
            item
            for item in store.list_underwriting(selection.ticker)
            if item.underwriting_id == opportunity.summary.underwriting_id
        )
        portfolio_json = store.get_portfolio_snapshot(portfolio_id)
        portfolio = PortfolioSnapshot.from_json(portfolio_json)
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None:
            raise SizingError("Analysis time requires timezone.")
        if any(
            _retrieved_at(value) > clock
            for value in (portfolio.created_at, record.created_at)
        ):
            raise SizingError(
                "Portfolio/underwriting was not available at analysis time."
            )
        decision_json = None
        if decision_id is not None:
            decision_record = next(
                (
                    item
                    for item in store.list_decisions()
                    if item.decision_id == decision_id
                ),
                None,
            )
            if decision_record is None:
                raise SizingError(f"Decision {decision_id} not found.")
            decision = read_decision(decision_record)
            if decision.chosen.underwriting.underwriting_id != record.underwriting_id:
                raise SizingError(
                    "Decision must link to the exact selected underwriting UUID/version."
                )
            if _retrieved_at(decision.recorded_at) > clock:
                raise SizingError("Decision was not available at analysis time.")
            decision_json = json.loads(decision.to_json())
        matches = [
            item
            for item in portfolio.holdings
            if _identity_match(item, record.security_id, record.ticker)
        ]
        if len(matches) > 1:
            raise SizingError("Ambiguous duplicate company holdings.")
        holding = matches[0] if matches else None
        if holding and holding.asset_type != AssetType.EQUITY:
            raise SizingError(
                "Selected company position sizing supports EQUITY holdings only."
            )
        context = (
            ExposureContext.parse(context_data)
            if context_data is not None
            else (holding.context if holding else ExposureContext(None, None, None))
        )
        if holding and context_data is not None and context != holding.context:
            raise SizingError(
                "Opportunity exposure context must agree with the frozen holding; create a revised portfolio snapshot."
            )
        current = holding.weight if holding else 0.0
        proposed = (
            _number(proposed_increment, "proposed_increment", ratio=True)
            if proposed_increment is not None
            else None
        )
        summary, quality = opportunity.summary, opportunity.quality
        bear = summary.scenarios[0]
        loss = max(0.0, -bear.terminal_return)
        warnings: list[str] = []
        missing: list[str] = []
        quality_reasons: list[str] = []
        if not quality.supporting_evidence or not quality.disconfirming_evidence:
            quality_reasons.append("INCOMPLETE_EVIDENCE")
        if quality.documented_variant is not True:
            quality_reasons.append("NO_DOCUMENTED_VARIANT_VIEW")
        if quality.major_unresolved_questions:
            # 9A has no high-impact/resolution taxonomy. Never infer questions resolved.
            quality_reasons.append("UNRESOLVED_CHALLENGER_QUESTIONS")
        if quality.sensitivity_band == "HIGH":
            quality_reasons.append("HIGH_LOCAL_SENSITIVITY")
        if quality.missing_dimensions or any(
            value in (None, "NOT_EVALUABLE")
            for _, value in opportunity.business.dimensions
        ):
            quality_reasons.append("MISSING_FEATURE7_8_CONTEXT")
        if loss >= policy.severe_bear_loss_threshold:
            quality_reasons.append("SEVERE_BEAR_LOSS")
        if loss == 0:
            warnings.append("NON_LOSS_BEAR_IS_NOT_A_RISK_GUARANTEE")
        ceilings: dict[str, float | None] = {
            "single_position": policy.max_single_position_weight,
            "initial_position": policy.max_initial_position_weight
            if current == 0
            else None,
            "bear_loss_budget": min(
                1.0, policy.max_portfolio_bear_loss_contribution / loss
            )
            if loss > 0
            else None,
            "evidence_quality": policy.starter_position_weight
            if quality_reasons
            else None,
        }
        cash = portfolio.cash_weight
        if cash is None:
            missing.append(
                "Cash was not supplied; normalization covers reported holdings only, not verified total wealth."
            )
            ceilings["cash_deployment"] = current
        else:
            ceilings["cash_deployment"] = min(
                1.0, current + max(0.0, cash - policy.min_cash_reserve)
            )
            if cash < policy.min_cash_reserve - EPSILON:
                warnings.append("CASH_BELOW_RESERVE")
        sector_weights: dict[str, float] = {}
        industry_weights: dict[str, float] = {}
        tag_weights: dict[str, float] = {}
        for item in portfolio.holdings:
            for label, totals in (
                (item.context.sector, sector_weights),
                (item.context.industry, industry_weights),
            ):
                if label is not None:
                    totals[label] = math.fsum((totals.get(label, 0), item.weight))
            for tag in item.context.exposure_tags or ():
                tag_weights[tag] = math.fsum((tag_weights.get(tag, 0), item.weight))
        unknown_sector = any(
            item.weight > 0 and item.context.sector is None
            for item in portfolio.holdings
        )
        if context.sector is None or unknown_sector:
            missing.append(
                "Sector coverage incomplete; no additional sector capacity assumed."
            )
            ceilings["sector"] = current
        else:
            existing_sector = sector_weights.get(context.sector, 0)
            ceilings["sector"] = max(
                0.0, policy.max_sector_weight - max(0.0, existing_sector - current)
            )
        unknown_tags = context.exposure_tags is None or any(
            item.weight > 0 and item.context.exposure_tags is None
            for item in portfolio.holdings
        )
        if unknown_tags:
            missing.append(
                "Exposure tags unknown; no additional thesis capacity assumed."
            )
            ceilings["thesis"] = current
        else:
            ceilings["thesis"] = min(
                (
                    max(
                        0.0,
                        policy.max_thesis_weight
                        - max(0.0, tag_weights.get(tag, 0) - current),
                    )
                    for tag in context.exposure_tags or ()
                ),
                default=1.0,
            )
        if context.industry is None or any(
            item.context.industry is None and item.weight > 0
            for item in portfolio.holdings
        ):
            missing.append(
                "Industry coverage incomplete; known industry totals are partial, not inferred."
            )
        if summary.return_spread <= EPSILON or summary.classification not in (
            "INTERESTING",
            "ATTRACTIVE",
        ):
            ceilings["economics_gate"] = 0.0
            warnings.append("ECONOMICS_DO_NOT_SUPPORT_ADDITIONAL_EXPOSURE")
        cap = min(value for value in ceilings.values() if value is not None)
        binding = sorted(
            name
            for name, value in ceilings.items()
            if value is not None and abs(value - cap) <= EPSILON
        )
        room = max(0.0, cap - current)
        target_proposed = current + proposed if proposed is not None else None
        if current > cap + EPSILON:
            warnings.append("ABOVE_POLICY_RANGE")
        if any(
            item.weight > policy.max_single_position_weight + EPSILON
            for item in portfolio.holdings
        ) or (
            target_proposed is not None
            and target_proposed > policy.max_single_position_weight + EPSILON
        ):
            warnings.append("SINGLE_NAME_CONCENTRATION_WARNING")
        if any(
            value > policy.max_sector_weight + EPSILON
            for value in sector_weights.values()
        ) or (
            proposed is not None
            and context.sector is not None
            and sector_weights.get(context.sector, 0) + proposed
            > policy.max_sector_weight + EPSILON
        ):
            warnings.append("SECTOR_CONCENTRATION_WARNING")
        if any(
            value > policy.max_thesis_weight + EPSILON for value in tag_weights.values()
        ) or (
            proposed is not None
            and any(
                tag_weights.get(tag, 0) + proposed > policy.max_thesis_weight + EPSILON
                for tag in context.exposure_tags or ()
            )
        ):
            warnings.append("THESIS_CONCENTRATION_WARNING")
        if proposed is not None and proposed > room + EPSILON:
            warnings.append("PROPOSED_INCREMENT_EXCEEDS_ROOM")
        if missing:
            warnings.append("INCOMPLETE_PORTFOLIO_CONTEXT")
        status = (
            "NO_POSITION"
            if cap <= EPSILON
            else "STARTER"
            if cap <= policy.starter_position_weight + EPSILON
            else "NORMAL"
        )
        total_value = (
            portfolio.normalization_total
            if portfolio.basis == "MARKET_VALUE" and cash is not None
            else None
        )
        return {
            "model_version": SIZING_VERSION,
            "category": "CALCULATION",
            "state": "SIZING_ANALYSIS",
            "ticker": record.ticker,
            "security_id": record.security_id,
            "underwriting": asdict(record),
            "opportunity": asdict(opportunity),
            "portfolio": json.loads(portfolio.to_json()),
            "portfolio_content_hash": compute_content_hash(portfolio_json.encode()),
            "policy": asdict(policy),
            "opportunity_context": asdict(context),
            "decision_context": decision_json,
            "current_weight": current,
            "cash_weight": cash,
            "bear_terminal_return": bear.terminal_return,
            "modeled_bear_loss": loss,
            "current_bear_loss_contribution": current * loss,
            "largest_positions": [
                asdict(item)
                for item in sorted(
                    portfolio.holdings, key=lambda item: (-item.weight, item.ticker)
                )[:5]
            ],
            "sector_weights": dict(sorted(sector_weights.items())),
            "industry_weights": dict(sorted(industry_weights.items())),
            "thesis_weights": dict(sorted(tag_weights.items())),
            "ceilings": ceilings,
            "quality_cap_reasons": quality_reasons,
            "target_range": [0.0, cap],
            "incremental_room": [0.0, room],
            "incremental_capital": {
                "currency": portfolio.currency,
                "range": [0.0, room * total_value],
            }
            if total_value is not None
            else None,
            "proposed_increment": proposed,
            "proposed_target_weight": target_proposed,
            "proposed_bear_loss_contribution": target_proposed * loss
            if target_proposed is not None
            else None,
            "binding_constraints": binding,
            "status": status,
            "warnings": sorted(set(warnings)),
            "missing_dimensions": missing,
            "disclaimer": DISCLAIMER,
        }
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        if isinstance(exc, SizingError):
            raise
        raise SizingError(f"Cannot size exact opportunity: {exc}") from exc


def validate_sizing_sources(
    store: SqliteStore, report: dict[str, Any], created_at: str
) -> None:
    record = report["underwriting"]
    expected = size_position(
        store,
        UnderwritingSelection(record["ticker"], record["version"]),
        report["portfolio"]["snapshot_id"],
        report["policy"],
        context_data=report["opportunity_context"],
        proposed_increment=report["proposed_increment"],
        decision_id=report["decision_context"]["decision_id"]
        if report["decision_context"] is not None
        else None,
        now=datetime.fromisoformat(created_at),
    )
    if canonical_json(expected) != canonical_json(report):
        raise SizingError(
            "Sizing result differs from the exact selected sources and model rules."
        )


def sizing_rows(report: dict[str, Any]) -> list[dict[str, str]]:
    summary = report["opportunity"]["summary"]
    values = {
        "Ticker": report["ticker"],
        "Underwriting version / UUID": f"{summary['underwriting_version']} / {summary['underwriting_id']}",
        "Frozen underwriting price / date": f"{summary['current_price']:g} / {summary['market_date']}",
        "Portfolio snapshot / as-of": f"{report['portfolio']['snapshot_id']} / {report['portfolio']['as_of_date']}",
        "Normalization basis / denominator": f"{report['portfolio']['basis']} / {report['portfolio']['normalization_total']:g}",
        "Sizing model": report["model_version"],
        "Current weight": f"{report['current_weight']:.2%}",
        "Cash weight": f"{report['cash_weight']:.2%}"
        if report["cash_weight"] is not None
        else "MISSING",
        "Expected CAGR": f"{summary['expected_5y_cagr']:.2%}",
        "Hurdle spread": f"{summary['return_spread']:+.2%}",
        "Feature 8 classification": summary["classification"],
        "Bear terminal return": f"{report['bear_terminal_return']:+.2%}",
        "Modeled Bear loss": f"{report['modeled_bear_loss']:.2%}",
        "Bear contribution at current weight": f"{report['current_bear_loss_contribution']:.2%}",
        **{
            f"Ceiling: {key}": f"{value:.2%}" if value is not None else "NOT APPLICABLE"
            for key, value in report["ceilings"].items()
        },
        "Quality cap reasons": ", ".join(report["quality_cap_reasons"])
        or "None established",
        "Reasonable target range": f"0.00%-{report['target_range'][1]:.2%}",
        "Incremental room": f"+0.00% to +{report['incremental_room'][1]:.2%}",
        "Incremental capital": f"{report['incremental_capital']['currency']} 0.00-{report['incremental_capital']['range'][1]:.2f}"
        if report["incremental_capital"] is not None
        else "MISSING (no complete market-value denominator)",
        "Proposed increment": f"{report['proposed_increment']:+.2%}"
        if report["proposed_increment"] is not None
        else "NOT PROVIDED",
        "Status": report["status"],
        "Binding constraints": ", ".join(report["binding_constraints"]),
        "Warnings": ", ".join(report["warnings"]) or "None established",
        "Missing dimensions": " | ".join(report["missing_dimensions"])
        or "None recorded",
    }
    return [{"Metric": key, "Value": value} for key, value in values.items()]


def format_sizing(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            *(f"{row['Metric']}: {row['Value']}" for row in sizing_rows(report)),
            report["disclaimer"],
        ]
    )

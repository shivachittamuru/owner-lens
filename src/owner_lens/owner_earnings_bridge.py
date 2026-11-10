"""Read-only integrity checks over the v1 research sidecar, not normalization policy."""

from __future__ import annotations

import json
import sysconfig
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Context, Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

PER_SHARE_TOLERANCE = Decimal("1e-12")
SCHEMA_NAME = "owner_earnings_bridge_v1.schema.json"
_DERIVED = {"free_cash_flow", "fcf_per_share", "total_debt", "net_cash", "roic"}
_NUMERIC = {"AVAILABLE", "CONDITIONAL"}
_UNITS = {"diluted_shares": "shares", "fcf_per_share": "USD/share", "roic": "ratio"}


class BridgeError(ValueError):
    """Malformed or contradictory research data, never an unresolved hypothesis."""


@dataclass(frozen=True)
class BridgeCase:
    case_id: str
    outcome: str
    total: dict[str, str] | None
    per_share: dict[str, str] | None
    assumptions: tuple[dict[str, str], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class BridgeValidation:
    ticker: str
    cases: tuple[BridgeCase, ...]
    limitations: tuple[str, ...]
    price_evidence: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2, allow_nan=False)


def _reject_constant(value: str) -> None:
    raise BridgeError(f"JSON: nonfinite constant {value} is not permitted.")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError(f"JSON: duplicate key {key!r}.")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"Cannot load {path.name}: {exc}") from exc


def load_bridge_schema() -> dict[str, Any]:
    """Use the canonical checkout artifact, or its wheel-installed documentation."""
    checkout = Path(__file__).resolve().parents[2] / "docs" / "examples" / SCHEMA_NAME
    installed = Path(sysconfig.get_path("data")) / "examples" / SCHEMA_NAME
    schema = _read_json(checkout if checkout.is_file() else installed)
    Draft202012Validator.check_schema(schema)
    return schema


def load_bridge(path: Path) -> BridgeValidation:
    return validate_bridge(_read_json(path))


def _bounds(quantity: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    if quantity["status"] not in _NUMERIC:
        return None
    if quantity["amount"] is not None:
        value = Decimal(quantity["amount"])
        return value, value
    return Decimal(quantity["lower"]), Decimal(quantity["upper"])


def _scalar(quantity: dict[str, Any]) -> Decimal | None:
    return Decimal(quantity["amount"]) if quantity["amount"] is not None else None


def _wire(bounds: tuple[Decimal, Decimal] | None, unit: str) -> dict[str, str] | None:
    if bounds is None:
        return None
    low, high = bounds
    if low == high:
        return {"amount": format(low, "f"), "unit": unit}
    return {"lower": format(low, "f"), "upper": format(high, "f"), "unit": unit}


class _Validator:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.errors: list[str] = []
        self.sources = self._index(data["source_evidence"]["sources"], "source_id")
        self.periods = self._index(data["source_evidence"]["periods"], "period_id")
        self.observations = self._index(
            data["reported_owner_economics"], "observation_id"
        )
        self.adjustments = self._index(
            data["normalization_adjustments"], "adjustment_id"
        )
        self.claims = self._index(data["research_card"]["claims"], "claim_id")
        self.cases = self._index(data["conditional_owner_earnings"], "case_id")
        all_ids: list[str] = []
        for namespace in (
            self.sources,
            self.periods,
            self.observations,
            self.adjustments,
            self.claims,
            self.cases,
        ):
            for identifier in namespace:
                if identifier in all_ids:
                    self.error(identifier, "ID is ambiguous across namespaces.")
                all_ids.append(identifier)

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def _index(
        self, rows: list[dict[str, Any]], field: str
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row[field]
            if key in index:
                self.error(key, f"duplicate {field}.")
            index[key] = row
        return index

    def refs(
        self, location: str, identifiers: list[str], namespace: dict[str, Any]
    ) -> None:
        for identifier in identifiers:
            if identifier not in namespace:
                self.error(location, f"unresolved reference {identifier!r}.")

    def quantity(self, location: str, quantity: dict[str, Any], unit: str) -> None:
        if quantity["unit"] != unit:
            self.error(location, f"unit must be {unit}.")
        bounds = _bounds(quantity)
        if bounds is not None and bounds[0] > bounds[1]:
            self.error(location, "lower bound exceeds upper bound.")

    def check_links(self) -> None:
        for identifier, row in self.observations.items():
            self.refs(identifier, [row["period_id"]], self.periods)
            self.refs(identifier, row["input_ids"], self.observations)
            self.refs(identifier, row["source_ids"], self.sources)
        for identifier, row in self.adjustments.items():
            self.refs(identifier, [row["period_id"]], self.periods)
            self.refs(identifier, row["input_ids"], self.observations)
            self.refs(identifier, row["source_ids"], self.sources)
            self.refs(identifier, row["depends_on"] + row["excludes"], self.adjustments)
        for identifier, row in self.claims.items():
            self.refs(identifier, row["source_ids"], self.sources)
            self.refs(
                identifier,
                row["supports"] + row["disconfirms"],
                self.claims | self.adjustments,
            )
            if identifier in row["supports"] + row["disconfirms"]:
                self.error(identifier, "claim cannot support/disconfirm itself.")
            if set(row["supports"]) & set(row["disconfirms"]):
                self.error(
                    identifier, "same target is both supported and disconfirmed."
                )
        for identifier, row in self.cases.items():
            self.refs(identifier, [row["period_id"]], self.periods)
            self.refs(identifier, [row["baseline_observation_id"]], self.observations)
            if row["share_observation_id"] is not None:
                self.refs(identifier, [row["share_observation_id"]], self.observations)
            self.refs(identifier, row["adjustment_ids"], self.adjustments)
            self.refs(identifier, row["unsupported_components"], self.adjustments)
        source = self.data["source_evidence"]
        research = self.data["research_card"]
        self.refs("price", source["price"]["source_ids"], self.sources)
        for row in (
            *source["limitations"],
            *research["business_uncertainty"],
            *research["financial_fragility"]["observations"],
            *research["evidence_limitations"],
        ):
            self.refs(row["code"], row["source_ids"], self.sources)
        self.cycles(self.adjustments, "depends_on", "adjustment dependency")
        self.cycles(self.observations, "input_ids", "observation dependency")

    def cycles(self, namespace: dict[str, Any], field: str, label: str) -> None:
        # Iterative traversal avoids recursion limits for invalid deep input graphs.
        completed: set[str] = set()
        for root in sorted(namespace):
            active: set[str] = set()
            stack = [(root, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    active.discard(node)
                    completed.add(node)
                elif node in active:
                    self.error(node, f"{label} cycle.")
                elif node not in completed and node in namespace:
                    active.add(node)
                    stack.append((node, True))
                    stack.extend(
                        (child, False) for child in reversed(namespace[node][field])
                    )

    def chronology(self) -> None:
        cutoff = datetime.fromisoformat(self.data["knowledge_cutoff"])
        generated = datetime.fromisoformat(self.data["generated_at"])
        if cutoff > generated:
            self.error("knowledge_cutoff", "exceeds generated_at.")
        fiscal_years: set[int] = set()
        for identifier, period in self.periods.items():
            if period["fiscal_year"] in fiscal_years:
                self.error(identifier, "ambiguous duplicate fiscal year.")
            fiscal_years.add(period["fiscal_year"])
            end = date.fromisoformat(period["period_end"])
            start = period["period_start"]
            if end > cutoff.date() or (
                start is not None and date.fromisoformat(start) > end
            ):
                self.error(identifier, "invalid historical fiscal-period chronology.")
        for identifier, source in self.sources.items():
            retrieved = source["retrieved_at"]
            filing = source["provider_reported_filing_date"]
            if retrieved is not None:
                timestamp = datetime.fromisoformat(retrieved)
                if timestamp > cutoff:
                    self.error(identifier, "retrieval exceeds knowledge cutoff.")
                if filing is not None and date.fromisoformat(filing) > timestamp.date():
                    self.error(identifier, "filing date exceeds retrieval date.")
            accepted = source["provider_reported_acceptance"]
            if accepted is not None:
                try:
                    accepted_date = datetime.fromisoformat(accepted).date()
                except ValueError:
                    self.error(identifier, "malformed provider acceptance timestamp.")
                else:
                    if accepted_date > cutoff.astimezone(UTC).date():
                        self.error(
                            identifier, "acceptance date exceeds knowledge cutoff."
                        )
                    if (
                        retrieved is not None
                        and accepted_date > datetime.fromisoformat(retrieved).date()
                    ):
                        self.error(
                            identifier, "acceptance date exceeds retrieval date."
                        )
        for identifier, row in self.claims.items():
            if (
                row["observation_date"]
                and date.fromisoformat(row["observation_date"]) > cutoff.date()
            ):
                self.error(identifier, "claim observation exceeds knowledge cutoff.")
        for identifier, row in self.observations.items():
            end = self.periods[row["period_id"]]["period_end"]
            for source_id in row["source_ids"]:
                source = self.sources[source_id]
                if source["retrieved_at"] and end > source["retrieved_at"][:10]:
                    self.error(identifier, "fiscal end exceeds source retrieval.")
                if (
                    source["provider_reported_filing_date"]
                    and end > source["provider_reported_filing_date"]
                ):
                    self.error(identifier, "fiscal end exceeds source filing.")
        quote = self.data["source_evidence"]["price"]
        market_date = quote["market_date"]
        if market_date and date.fromisoformat(market_date) > cutoff.date():
            self.error("price", "market date exceeds knowledge cutoff.")
        for source_id in quote["source_ids"]:
            retrieved = self.sources[source_id]["retrieved_at"]
            if retrieved and market_date and market_date > retrieved[:10]:
                self.error("price", "market date exceeds retrieval date.")
        currency = quote["currency_basis"]
        expected_unit = (
            "UNKNOWN_CURRENCY/share" if currency == "NOT_VERIFIED" else "USD/share"
        )
        self.quantity("price", quote["close"], expected_unit)
        if currency != "NOT_VERIFIED" and quote["currency"] not in ("USD", None):
            self.error("price", "non-USD currency cannot establish USD compatibility.")
        if currency == "VERIFIED_BAR" and quote["currency"] != "USD":
            self.error("price", "VERIFIED_BAR requires explicit USD currency.")
        price_bounds = _bounds(quote["close"])
        if price_bounds is not None and (
            market_date is None or not quote["source_ids"] or price_bounds[0] <= 0
        ):
            self.error(
                "price", "numeric close requires a positive price, date and source."
            )

    def supported(self, row: dict[str, Any]) -> bool:
        return (
            row["quantity"]["status"] == "AVAILABLE"
            and _scalar(row["quantity"]) is not None
            and bool(row["source_ids"])
            and all(
                self.sources[i]["status"] == "AVAILABLE"
                and self.sources[i]["retrieved_at"] is not None
                for i in row["source_ids"]
            )
        )

    def metric_inputs(
        self, row: dict[str, Any], metrics: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        inputs = [self.observations[i] for i in row["input_ids"]]
        if sorted(i["metric"] for i in inputs) != sorted(metrics):
            self.error(
                row["observation_id"],
                f"input_ids must identify exactly {', '.join(metrics)}.",
            )
            return []
        if any(i["period_id"] != row["period_id"] for i in inputs):
            self.error(
                row["observation_id"], "arithmetic input fiscal period mismatch."
            )
        return inputs

    def reconcile(
        self,
        location: str,
        declared: dict[str, Any],
        expected: tuple[Decimal, Decimal] | None,
        *,
        conditional: bool = False,
        tolerance: Decimal = Decimal(0),
    ) -> None:
        actual = _bounds(declared)
        if expected is None:
            if actual is not None:
                self.error(
                    location, "numeric result has unsupported indispensable inputs."
                )
        elif actual is None:
            self.error(location, "supported calculation requires a numeric result.")
        elif any(abs(a - e) > tolerance for a, e in zip(actual, expected, strict=True)):
            self.error(
                location, "declared amount/bounds disagree with recomputed result."
            )
        elif conditional and declared["status"] != "CONDITIONAL":
            self.error(location, "investor assumptions require CONDITIONAL status.")

    def observations_check(self) -> dict[str, Decimal | None]:
        seen: set[tuple[str, str]] = set()
        for identifier, row in self.observations.items():
            key = row["period_id"], row["metric"]
            if key in seen:
                self.error(identifier, "duplicate metric in the same fiscal period.")
            seen.add(key)
            self.quantity(identifier, row["quantity"], _UNITS.get(row["metric"], "USD"))
            expected_category = "CALCULATION" if row["metric"] in _DERIVED else "FACT"
            if row["category"] != expected_category:
                self.error(identifier, f"{row['metric']} must be {expected_category}.")
            if (
                row["quantity"]["amount"] is None
                and _bounds(row["quantity"]) is not None
            ):
                self.error(
                    identifier, "reported historical observations must be scalar."
                )
            value = _scalar(row["quantity"])
            if (
                row["metric"] == "capital_expenditures"
                and value is not None
                and value < 0
            ):
                self.error(
                    identifier, "canonical PP&E CapEx must be a nonnegative magnitude."
                )
            fact = row["canonical_metadata"]["fact"]
            if fact is not None:
                period = self.periods[row["period_id"]]
                for field, expected in (
                    ("metric", row["metric"]),
                    ("unit", row["quantity"]["unit"]),
                    ("fiscal_year", period["fiscal_year"]),
                    ("period_end", period["period_end"]),
                    ("provider_field", row["provider_field"]),
                ):
                    if fact.get(field) != expected:
                        self.error(
                            identifier,
                            f"canonical_metadata {field} disagrees with observation.",
                        )
                if value is not None and (
                    isinstance(fact.get("value"), bool)
                    or str(fact.get("value")) != str(value)
                ):
                    self.error(
                        identifier,
                        "canonical_metadata value disagrees with observation.",
                    )
        totals: dict[str, Decimal | None] = {}
        for identifier, row in self.observations.items():
            if row["metric"] != "free_cash_flow":
                continue
            inputs = self.metric_inputs(
                row, ("operating_cash_flow", "capital_expenditures")
            )
            values = {i["metric"]: _scalar(i["quantity"]) for i in inputs}
            total = None
            if (
                inputs
                and all(self.supported(i) for i in inputs)
                and self.supported(row)
            ):
                ocf, capex = (
                    values["operating_cash_flow"],
                    values["capital_expenditures"],
                )
                if ocf is not None and capex is not None:
                    total = ocf - capex
            self.reconcile(
                identifier,
                row["quantity"],
                (total, total) if total is not None else None,
            )
            totals[identifier] = total
        for identifier, row in self.observations.items():
            if row["metric"] != "fcf_per_share":
                continue
            inputs = self.metric_inputs(row, ("free_cash_flow", "diluted_shares"))
            by_metric = {i["metric"]: i for i in inputs}
            fps = None
            if inputs:
                fcf = totals.get(by_metric["free_cash_flow"]["observation_id"])
                shares = by_metric["diluted_shares"]
                denominator = _scalar(shares["quantity"])
                if (
                    fcf is not None
                    and self.supported(shares)
                    and denominator is not None
                    and denominator > 0
                ):
                    fps = fcf / denominator
            self.reconcile(
                identifier,
                row["quantity"],
                (fps, fps) if fps is not None else None,
                tolerance=PER_SHARE_TOLERANCE,
            )
        return totals

    def adjustment_checks(self) -> None:
        for identifier, row in self.adjustments.items():
            self.quantity(identifier, row["signed_effect"], "USD")
            if (
                row["category"] != "CALCULATION"
                and row["approval"] == "NOT_REQUIRED_DETERMINISTIC"
            ):
                self.error(
                    identifier,
                    "assumptions/judgments cannot claim deterministic approval.",
                )
            if (
                row["category"] == "JUDGMENT"
                and _bounds(row["signed_effect"]) is not None
            ):
                self.error(
                    identifier,
                    "numeric policy must be ASSUMPTION or CALCULATION, not JUDGMENT.",
                )
            if (
                row["category"] == "ASSUMPTION"
                and _bounds(row["signed_effect"]) is not None
                and row["signed_effect"]["status"] != "CONDITIONAL"
            ):
                self.error(
                    identifier,
                    "numeric investor assumption must remain CONDITIONAL.",
                )
            if identifier in row["excludes"]:
                self.error(identifier, "adjustment cannot exclude itself.")
            for input_id in row["input_ids"]:
                if self.observations[input_id]["period_id"] != row["period_id"]:
                    self.error(identifier, "adjustment input fiscal period mismatch.")

    def effect_supported(self, row: dict[str, Any]) -> bool:
        if _bounds(row["signed_effect"]) is None:
            return False
        if not all(self.supported(self.observations[i]) for i in row["input_ids"]):
            return False
        if row["category"] == "ASSUMPTION":
            return True
        return (
            row["category"] == "CALCULATION"
            and bool(row["input_ids"])
            and bool(row["source_ids"])
            and all(self.supported(self.observations[i]) for i in row["input_ids"])
            and all(
                self.sources[i]["status"] == "AVAILABLE"
                and self.sources[i]["retrieved_at"]
                for i in row["source_ids"]
            )
        )

    def calculate_case(
        self, identifier: str, row: dict[str, Any], totals: dict[str, Decimal | None]
    ) -> BridgeCase:
        baseline = self.observations[row["baseline_observation_id"]]
        if (
            baseline["metric"] != "free_cash_flow"
            or baseline["period_id"] != row["period_id"]
        ):
            self.error(
                identifier,
                "baseline must reference canonical FCF in the case fiscal period.",
            )
        selected = row["adjustment_ids"]
        if row["kind"] == "REPORTED_BASELINE" and selected:
            self.error(identifier, "REPORTED_BASELINE cannot select adjustments.")
        groups: set[str] = set()
        for adjustment_id in selected:
            adjustment = self.adjustments[adjustment_id]
            if adjustment["period_id"] != row["period_id"]:
                self.error(
                    identifier, f"{adjustment_id}: adjustment fiscal period mismatch."
                )
            if not set(adjustment["depends_on"]) <= set(selected):
                self.error(
                    identifier, f"{adjustment_id}: required dependency not selected."
                )
            if set(adjustment["excludes"]) & set(selected):
                self.error(
                    identifier, f"{adjustment_id}: excluded adjustment selected."
                )
            group = adjustment["overlap_group"]
            if group is not None and group in groups:
                self.error(
                    identifier, f"overlap_group {group!r} selected more than once."
                )
            if group is not None:
                groups.add(group)
        self.quantity(identifier + "/owner_earnings", row["owner_earnings"], "USD")
        self.quantity(
            identifier + "/owner_earnings_per_share",
            row["owner_earnings_per_share"],
            "USD/share",
        )
        limitations = list(row["unresolved_risks"])
        base = totals.get(row["baseline_observation_id"])
        bounds = (base, base) if base is not None else None
        missing = [
            i for i in selected if not self.effect_supported(self.adjustments[i])
        ]
        if base is None:
            limitations.append(
                "Canonical FCF baseline lacks supported OCF/CapEx evidence."
            )
        for adjustment_id in missing:
            limitations.append(
                f"{adjustment_id}: {self.adjustments[adjustment_id]['signed_effect']['reason']}"
            )
        if not set(missing) <= set(row["unsupported_components"]):
            self.error(
                identifier,
                "unsupported_components must disclose every unsupported selected adjustment.",
            )
        if missing:
            bounds = None
        if bounds is not None:
            low, high = bounds
            for adjustment_id in selected:
                effect = _bounds(self.adjustments[adjustment_id]["signed_effect"])
                if effect is not None:
                    low += effect[0]
                    high += effect[1]
            bounds = low, high
        assumptions = tuple(
            {
                "adjustment_id": i,
                "category": self.adjustments[i]["category"],
                "approval": self.adjustments[i]["approval"],
            }
            for i in selected
        )
        has_assumption = any(a["category"] == "ASSUMPTION" for a in assumptions)
        if row["kind"] == "REPORTED_BASELINE":
            for name in ("owner_earnings", "owner_earnings_per_share"):
                if (
                    _bounds(row[name]) is not None
                    and row[name]["status"] != "AVAILABLE"
                ):
                    self.error(
                        identifier,
                        "reported baseline numeric outputs must be AVAILABLE.",
                    )
        self.reconcile(
            identifier + "/owner_earnings",
            row["owner_earnings"],
            bounds,
            conditional=has_assumption,
        )
        denominator = None
        shares_id = row["share_observation_id"]
        if shares_id is not None:
            shares = self.observations[shares_id]
            if (
                shares["metric"] != "diluted_shares"
                or shares["period_id"] != row["period_id"]
            ):
                self.error(
                    identifier, "denominator must be aligned annual diluted shares."
                )
            if self.supported(shares):
                denominator = _scalar(shares["quantity"])
        fps = None
        if denominator is None or denominator <= 0:
            limitations.append(
                "Per-share result unavailable: positive aligned diluted shares required."
            )
        elif bounds is not None:
            fps = bounds[0] / denominator, bounds[1] / denominator
        self.reconcile(
            identifier + "/owner_earnings_per_share",
            row["owner_earnings_per_share"],
            fps,
            conditional=has_assumption,
            tolerance=PER_SHARE_TOLERANCE,
        )
        outcome = (
            "UNRESOLVED"
            if bounds is None or fps is None
            else "VALID_REPORTED_BASELINE"
            if row["kind"] == "REPORTED_BASELINE"
            else "VALID_CONDITIONAL"
        )
        for assumption in assumptions:
            if assumption["approval"] == "UNREVIEWED":
                limitations.append(
                    f"{assumption['adjustment_id']}: UNREVIEWED; not investor-approved."
                )
        return BridgeCase(
            identifier,
            outcome,
            _wire(bounds, "USD"),
            _wire(fps, "USD/share"),
            assumptions,
            tuple(limitations),
        )

    def raise_errors(self) -> None:
        if self.errors:
            raise BridgeError("\n".join(sorted(set(self.errors))))

    def run(self) -> BridgeValidation:
        self.check_links()
        self.raise_errors()
        self.chronology()
        totals = self.observations_check()
        self.adjustment_checks()
        cases = tuple(
            self.calculate_case(i, row, totals) for i, row in self.cases.items()
        )
        self.raise_errors()
        research = self.data["research_card"]
        gate = research["existing_screening"]["gate"]
        state = research["financial_fragility"]["state"]
        if state == "ACTIVATED_EXISTING_GATE" and gate is None:
            self.error(
                "financial_fragility", "activated-gate state requires an existing gate."
            )
        if (
            gate
            and gate not in ("COVERAGE_FAILED", "TOO_FEW_EVALUABLE_DIMENSIONS")
            and state != "ACTIVATED_EXISTING_GATE"
        ):
            self.error(
                "financial_fragility",
                "existing financial gate cannot be hidden by another evidence state.",
            )
        self.raise_errors()
        limitations = [
            "Research only; no forecast, sustainable earnings estimate or valuation verdict.",
            "Source IDs/hashes are provenance claims; raw payloads are not verified by this validator.",
            "Adjustment effects are declared inputs; narrative calculation/assumption text is not executed.",
            *[
                f"{i['code']}: {i['explanation']}"
                for i in self.data["source_evidence"]["limitations"]
            ],
            *[
                f"{i['code']}: {i['explanation']}"
                for i in research["evidence_limitations"]
            ],
        ]
        if gate:
            limitations.append(
                f"Existing gate retained: {gate}; financial evidence state: {state}."
            )
        limitations.extend(
            f"{i['code']}: {i['explanation']}"
            for i in research["financial_fragility"]["observations"]
        )
        limitations.extend(
            f"{i['code']}: {i['explanation']}" for i in research["business_uncertainty"]
        )
        limitations.append(
            f"Financial evidence state: {state}; no gate is not proof of safety."
        )
        return BridgeValidation(
            self.data["identity"]["ticker"],
            cases,
            tuple(limitations),
            self.data["source_evidence"]["price"],
        )


def validate_bridge(document: Any) -> BridgeValidation:
    """Validate shape, references and arithmetic without I/O beyond the local schema."""
    try:
        json.dumps(document, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise BridgeError(
            "Document must contain finite, serializable JSON values."
        ) from exc
    validator = Draft202012Validator(
        load_bridge_schema(), format_checker=FormatChecker()
    )
    errors = sorted(
        "/" + "/".join(str(p) for p in error.absolute_path) + ": " + error.message
        for error in validator.iter_errors(document)
    )
    if errors:
        raise BridgeError("\n".join(errors))
    try:
        return _validate_arithmetic(document)
    except DecimalException as exc:
        raise BridgeError(
            f"Decimal arithmetic exceeds supported numeric range: {type(exc).__name__}."
        ) from exc


def _validate_arithmetic(document: dict[str, Any]) -> BridgeValidation:
    with localcontext(Context(prec=50)) as context:
        # Precision scales with explicit operands, not the caller's Decimal context.
        quantities = [o["quantity"] for o in document["reported_owner_economics"]]
        quantities += [
            a["signed_effect"] for a in document["normalization_adjustments"]
        ]
        quantities += [
            c[k]
            for c in document["conditional_owner_earnings"]
            for k in ("owner_earnings", "owner_earnings_per_share")
        ]
        width = max(
            (
                len(q[k])
                for q in quantities
                for k in ("amount", "lower", "upper")
                if q[k] is not None
            ),
            default=1,
        )
        context.prec = max(50, width * 2 + len(str(len(quantities))) + 20)
        return _Validator(document).run()

"""Contract arithmetic controls, not proposed company normalization assumptions."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import httpx
import pytest

from owner_lens import cli
from owner_lens.owner_earnings_bridge import BridgeError, load_bridge, validate_bridge

EXAMPLES = Path(__file__).parents[1] / "docs" / "examples"
SAMPLE = EXAMPLES / "deck_owner_earnings_bridge_v1.sample.json"


def quantity(amount=None, *, status=None, unit="USD", lower=None, upper=None):
    return {
        "status": status
        or (
            "AVAILABLE"
            if amount is not None or lower is not None
            else "INSUFFICIENT_EVIDENCE"
        ),
        "amount": str(amount) if amount is not None else None,
        "lower": str(lower) if lower is not None else None,
        "upper": str(upper) if upper is not None else None,
        "unit": unit,
        "reason": "Synthetic arithmetic control, not a company fact.",
    }


@pytest.fixture
def bridge():
    document = json.loads(SAMPLE.read_text())
    document["identity"].update(
        ticker="SYNTHETIC",
        company_name="Synthetic control",
        security_id=None,
        issuer_cik=None,
        history_id=None,
        history_input_hash=None,
    )
    document["source_evidence"]["sources"] = [
        {
            "source_id": "source",
            "provider": "investor",
            "title": "Synthetic fixture",
            "public_uri": None,
            "dataset": "synthetic",
            "snapshot_id": None,
            "content_hash": None,
            "endpoint": None,
            "retrieved_at": "2026-10-31T00:00:00+00:00",
            "provider_reported_filing_date": None,
            "provider_reported_acceptance": None,
            "accession": None,
            "status": "AVAILABLE",
        }
    ]
    document["source_evidence"]["price"].update(
        market_date=None, source_ids=[], close=quantity(unit="UNKNOWN_CURRENCY/share")
    )
    document["source_evidence"]["limitations"] = []
    document["reported_owner_economics"] = [
        {
            "observation_id": metric,
            "period_id": "FY2026",
            "metric": metric,
            "category": "CALCULATION"
            if metric in ("free_cash_flow", "fcf_per_share")
            else "FACT",
            "quantity": quantity(value, unit=unit),
            "provider_field": None,
            "source_ids": ["source"],
            "input_ids": inputs,
            "calculation": "Synthetic control" if inputs else None,
            "canonical_metadata": {"fact": None},
        }
        for metric, value, unit, inputs in (
            ("revenue", "100", "USD", []),
            ("operating_cash_flow", "15", "USD", []),
            ("capital_expenditures", "5", "USD", []),
            (
                "free_cash_flow",
                "10",
                "USD",
                ["operating_cash_flow", "capital_expenditures"],
            ),
            ("diluted_shares", "10", "shares", []),
            ("fcf_per_share", "1", "USD/share", ["free_cash_flow", "diluted_shares"]),
        )
    ]
    document["normalization_adjustments"] = []
    case = document["conditional_owner_earnings"][0]
    case.update(
        case_id="baseline",
        baseline_observation_id="free_cash_flow",
        share_observation_id="diluted_shares",
        unsupported_components=[],
        unresolved_risks=[],
        owner_earnings=quantity("10"),
        owner_earnings_per_share=quantity("1", unit="USD/share"),
    )
    document["conditional_owner_earnings"] = [case]
    research = document["research_card"]
    research.update(
        claims=[],
        business_uncertainty=[],
        evidence_limitations=[],
        next_evidence=[],
        financial_fragility={
            "state": "NO_FLAG_FROM_CURRENT_CHECKS",
            "observations": [],
        },
    )
    research["existing_screening"].update(gate=None)
    document["underwriting_handoff"]["existing_underwriting"] = None
    return document


def observation(bridge, metric):
    return next(
        row for row in bridge["reported_owner_economics"] if row["metric"] == metric
    )


def add_adjustment(
    bridge,
    effect="2",
    *,
    category="ASSUMPTION",
    approval="UNREVIEWED",
    identifier="adjustment",
):
    adjustment = {
        "adjustment_id": identifier,
        "adjustment_type": "WORKING_CAPITAL",
        "period_id": "FY2026",
        "category": category,
        "signed_effect": quantity(
            effect, status="CONDITIONAL" if category == "ASSUMPTION" else "AVAILABLE"
        ),
        "input_ids": ["operating_cash_flow"],
        "source_ids": ["source"],
        "calculation_or_assumption": "Explicit synthetic effect; no economic inference.",
        "economic_rationale": "Synthetic fixture only.",
        "uncertainty": "Not a company fact.",
        "approval": approval,
        "depends_on": [],
        "overlap_group": None,
        "excludes": [],
    }
    bridge["normalization_adjustments"].append(adjustment)
    return adjustment


def add_case(bridge, adjustments, total="12", fps="1.2", *, status="CONDITIONAL"):
    case = deepcopy(bridge["conditional_owner_earnings"][0])
    case.update(
        case_id="conditional",
        kind="HISTORICAL_CONDITIONAL",
        adjustment_ids=adjustments,
        owner_earnings=quantity(total, status=status if total is not None else None),
        owner_earnings_per_share=quantity(
            fps, status=status if fps is not None else None, unit="USD/share"
        ),
    )
    bridge["conditional_owner_earnings"].append(case)
    return case


def test_committed_deck_baseline_and_unresolved_normalization():
    before = SAMPLE.read_bytes()
    result = load_bridge(SAMPLE)
    assert [case.outcome for case in result.cases] == [
        "VALID_REPORTED_BASELINE",
        "UNRESOLVED",
    ]
    assert result.cases[0].total == {"amount": "1097332000", "unit": "USD"}
    assert abs(
        Decimal(result.cases[0].per_share["amount"]) - Decimal("7.526024484757039")
    ) < Decimal("1e-12")
    assert result.cases[1].total is None and result.cases[1].per_share is None
    assert all(a["approval"] == "UNREVIEWED" for a in result.cases[1].assumptions)
    assert result.price_evidence["currency_basis"] == "NOT_VERIFIED"
    assert result.price_evidence["share_basis"] == "UNVERIFIED"
    assert SAMPLE.read_bytes() == before


@pytest.mark.parametrize(
    "effect,total,fps",
    [("2", "12", "1.2"), ("-4", "6", "0.6"), ("-10", "0", "0"), ("-20", "-10", "-1")],
)
@pytest.mark.parametrize("approval", ["UNREVIEWED", "INVESTOR_APPROVED"])
def test_signed_assumptions_preserve_approval(bridge, effect, total, fps, approval):
    add_adjustment(bridge, effect, approval=approval)
    add_case(bridge, ["adjustment"], total, fps)
    result = validate_bridge(bridge).cases[1]
    assert result.outcome == "VALID_CONDITIONAL"
    assert Decimal(result.total["amount"]) == Decimal(total)
    assert result.assumptions[0]["approval"] == approval
    assert any("UNREVIEWED" in note for note in result.limitations) == (
        approval == "UNREVIEWED"
    )


def test_scalar_and_interval_effects(bridge):
    first = add_adjustment(bridge, "-2")
    second = add_adjustment(bridge, identifier="range")
    second["signed_effect"] = quantity(status="CONDITIONAL", lower="-4", upper="1")
    case = add_case(bridge, [first["adjustment_id"], second["adjustment_id"]])
    case["owner_earnings"] = quantity(status="CONDITIONAL", lower="4", upper="9")
    case["owner_earnings_per_share"] = quantity(
        status="CONDITIONAL",
        lower="0.4",
        upper="0.9",
        unit="USD/share",
    )
    result = validate_bridge(bridge).cases[1]
    assert result.total == {"lower": "4", "upper": "9", "unit": "USD"}
    assert result.per_share == {"lower": "0.4", "upper": "0.9", "unit": "USD/share"}


def test_deterministic_declared_adjustment_and_dependency_once(bridge):
    first = add_adjustment(
        bridge, "2", category="CALCULATION", approval="NOT_REQUIRED_DETERMINISTIC"
    )
    second = add_adjustment(bridge, "3", identifier="second")
    second["depends_on"] = [first["adjustment_id"]]
    add_case(bridge, ["adjustment", "second"], "15", "1.5")
    assert validate_bridge(bridge).cases[1].total["amount"] == "15"


@pytest.mark.parametrize("shares", [None, "0", "-1"])
def test_missing_nonpositive_shares_preserve_total(bridge, shares):
    observation(bridge, "diluted_shares")["quantity"] = quantity(shares, unit="shares")
    observation(bridge, "fcf_per_share")["quantity"] = quantity(unit="USD/share")
    bridge["conditional_owner_earnings"][0]["owner_earnings_per_share"] = quantity(
        unit="USD/share"
    )
    case = validate_bridge(bridge).cases[0]
    assert (
        case.outcome == "UNRESOLVED"
        and case.total["amount"] == "10"
        and case.per_share is None
    )


def test_no_share_reference_preserves_total(bridge):
    bridge["conditional_owner_earnings"][0].update(
        share_observation_id=None, owner_earnings_per_share=quantity(unit="USD/share")
    )
    result = validate_bridge(bridge).cases[0]
    assert result.outcome == "UNRESOLVED" and result.total is not None


def test_missing_numerator_does_not_become_zero(bridge):
    for metric in ("operating_cash_flow", "free_cash_flow", "fcf_per_share"):
        observation(bridge, metric)["quantity"] = quantity(
            unit="USD/share" if metric == "fcf_per_share" else "USD"
        )
    bridge["conditional_owner_earnings"][0].update(
        owner_earnings=quantity(), owner_earnings_per_share=quantity(unit="USD/share")
    )
    assert validate_bridge(bridge).cases[0].total is None


def test_unresolved_selected_effect_does_not_block_baseline(bridge):
    adjustment = add_adjustment(bridge)
    adjustment["signed_effect"] = quantity()
    case = add_case(bridge, ["adjustment"], None, None)
    case["unsupported_components"] = ["adjustment"]
    results = validate_bridge(bridge).cases
    assert [r.outcome for r in results] == ["VALID_REPORTED_BASELINE", "UNRESOLVED"]


@pytest.mark.parametrize(
    "problem",
    [
        "source",
        "input",
        "period",
        "adjustment",
        "shares",
        "baseline",
        "unsupported",
        "duplicate_source",
        "ambiguous_namespace",
        "duplicate_case",
        "case_metric",
        "unit",
        "period_alignment",
        "cycle",
        "observation_cycle",
        "dependency",
        "excludes",
        "overlap",
        "result",
        "reported_fcf",
        "reported_fps",
        "baseline_adjustment",
        "negative_capex",
        "assumption_status",
        "approval",
        "missing_source",
        "conditional_available",
        "bounds",
        "cutoff",
        "retrieval",
        "filing",
        "acceptance",
        "period_end",
        "claim",
        "canonical_metadata",
    ],
)
def test_semantic_errors_are_not_unresolved(bridge, problem):
    adjustment = add_adjustment(bridge)
    case = add_case(bridge, ["adjustment"])
    if problem == "source":
        adjustment["source_ids"] = ["missing"]
    elif problem == "input":
        adjustment["input_ids"] = ["missing"]
    elif problem == "period":
        adjustment["period_id"] = "missing"
    elif problem == "adjustment":
        case["adjustment_ids"] = ["missing"]
    elif problem == "shares":
        case["share_observation_id"] = "missing"
    elif problem == "baseline":
        case["baseline_observation_id"] = "missing"
    elif problem == "unsupported":
        case["unsupported_components"] = ["missing"]
    elif problem == "duplicate_source":
        bridge["source_evidence"]["sources"] *= 2
    elif problem == "ambiguous_namespace":
        bridge["source_evidence"]["sources"][0]["source_id"] = "revenue"
    elif problem == "duplicate_case":
        bridge["conditional_owner_earnings"].append(deepcopy(case))
    elif problem == "case_metric":
        case["baseline_observation_id"] = "revenue"
    elif problem == "unit":
        adjustment["signed_effect"]["unit"] = "shares"
    elif problem == "period_alignment":
        bridge["source_evidence"]["periods"].append(
            {
                **bridge["source_evidence"]["periods"][0],
                "period_id": "prior",
                "fiscal_year": 2025,
                "period_end": "2025-03-31",
            }
        )
        observation(bridge, "diluted_shares")["period_id"] = "prior"
    elif problem == "cycle":
        adjustment["depends_on"] = ["adjustment"]
    elif problem == "observation_cycle":
        observation(bridge, "operating_cash_flow")["input_ids"] = ["free_cash_flow"]
    elif problem == "dependency":
        add_adjustment(bridge, identifier="other")
        adjustment["depends_on"] = ["other"]
    elif problem == "excludes":
        adjustment["excludes"] = ["adjustment"]
    elif problem == "overlap":
        add_adjustment(bridge, identifier="other")["overlap_group"] = "shared"
        adjustment["overlap_group"] = "shared"
        case["adjustment_ids"].append("other")
    elif problem == "result":
        case["owner_earnings"]["amount"] = "99"
    elif problem == "reported_fcf":
        observation(bridge, "free_cash_flow")["quantity"]["amount"] = "11"
    elif problem == "reported_fps":
        observation(bridge, "fcf_per_share")["quantity"]["amount"] = "2"
    elif problem == "baseline_adjustment":
        bridge["conditional_owner_earnings"][0]["adjustment_ids"] = ["adjustment"]
    elif problem == "negative_capex":
        observation(bridge, "capital_expenditures")["quantity"]["amount"] = "-5"
    elif problem == "assumption_status":
        adjustment["signed_effect"]["status"] = "AVAILABLE"
    elif problem == "approval":
        adjustment["approval"] = "NOT_REQUIRED_DETERMINISTIC"
    elif problem == "missing_source":
        observation(bridge, "operating_cash_flow")["source_ids"] = []
    elif problem == "conditional_available":
        case["owner_earnings"]["status"] = "AVAILABLE"
    elif problem == "bounds":
        adjustment["signed_effect"] = quantity(
            status="CONDITIONAL", lower="9", upper="1"
        )
    elif problem == "cutoff":
        bridge["knowledge_cutoff"] = "2027-01-01T00:00:00+00:00"
    elif problem == "retrieval":
        bridge["source_evidence"]["sources"][0]["retrieved_at"] = (
            "2027-01-01T00:00:00+00:00"
        )
    elif problem == "filing":
        bridge["source_evidence"]["sources"][0]["provider_reported_filing_date"] = (
            "2027-01-01"
        )
    elif problem == "acceptance":
        bridge["source_evidence"]["sources"][0]["provider_reported_acceptance"] = (
            "bad timestamp"
        )
    elif problem == "period_end":
        bridge["source_evidence"]["periods"][0]["period_end"] = "2027-01-01"
    elif problem == "claim":
        bridge["research_card"]["claims"] = [
            {
                "claim_id": "claim",
                "topic": "BUSINESS_MODEL",
                "category": "JUDGMENT",
                "text": "Synthetic",
                "source_ids": [],
                "supports": ["missing"],
                "disconfirms": [],
                "unresolved": True,
                "observation_date": None,
            }
        ]
    else:
        observation(bridge, "revenue")["canonical_metadata"]["fact"] = {
            "metric": "wrong"
        }
    with pytest.raises(BridgeError):
        validate_bridge(bridge)


@pytest.mark.parametrize(
    "problem",
    [
        "extra",
        "float",
        "nan",
        "bool",
        "missing_key",
        "state",
        "future_kind",
        "date",
        "range_and_scalar",
    ],
)
def test_structural_errors(bridge, problem):
    q = observation(bridge, "revenue")["quantity"]
    if problem == "extra":
        bridge["intrinsic_value"] = 1
    elif problem == "float":
        q["amount"] = 1.0
    elif problem == "nan":
        q["amount"] = "NaN"
    elif problem == "bool":
        bridge["identity"]["security_id"] = True
    elif problem == "missing_key":
        del q["reason"]
    elif problem == "state":
        q["status"] = "UNSUPPORTED"
    elif problem == "future_kind":
        bridge["conditional_owner_earnings"][0]["kind"] = "PROJECTED_CONDITIONAL"
    elif problem == "date":
        bridge["source_evidence"]["periods"][0]["period_end"] = "2026-02-30"
    else:
        q.update(lower="1", upper="2")
    with pytest.raises(BridgeError):
        validate_bridge(bridge)


def test_repeatable_order_and_decimal_context_independence(bridge):
    first = validate_bridge(bridge).to_json()
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert validate_bridge(bridge).to_json() == first
    broken = deepcopy(bridge)
    observation(broken, "free_cash_flow")["input_ids"] = ["missing"]
    messages = []
    for _ in range(2):
        with pytest.raises(BridgeError) as error:
            validate_bridge(broken)
        messages.append(str(error.value))
    assert messages[0] == messages[1]


@pytest.mark.parametrize("ocf,expected", [("5", "0"), ("3", "-2")])
def test_zero_and_negative_reported_baselines(bridge, ocf, expected):
    observation(bridge, "operating_cash_flow")["quantity"] = quantity(ocf)
    observation(bridge, "free_cash_flow")["quantity"] = quantity(expected)
    fps = str(Decimal(expected) / 10)
    observation(bridge, "fcf_per_share")["quantity"] = quantity(fps, unit="USD/share")
    bridge["conditional_owner_earnings"][0].update(
        owner_earnings=quantity(expected),
        owner_earnings_per_share=quantity(fps, unit="USD/share"),
    )
    result = validate_bridge(bridge).cases[0]
    assert result.outcome == "VALID_REPORTED_BASELINE"
    assert Decimal(result.total["amount"]) == Decimal(expected)


def test_per_share_tolerance_not_used_for_cash(bridge):
    observation(bridge, "fcf_per_share")["quantity"]["amount"] = "1.0000000000001"
    validate_bridge(bridge)
    observation(bridge, "free_cash_flow")["quantity"]["amount"] = "10.0000000000001"
    with pytest.raises(BridgeError, match="declared amount"):
        validate_bridge(bridge)


def test_two_node_cycle_and_mutual_exclusions(bridge):
    first = add_adjustment(bridge)
    second = add_adjustment(bridge, identifier="second")
    first["depends_on"] = ["second"]
    second["depends_on"] = ["adjustment"]
    with pytest.raises(BridgeError, match="cycle"):
        validate_bridge(bridge)
    first["depends_on"] = []
    second["depends_on"] = []
    first["excludes"] = ["second"]
    add_case(bridge, ["adjustment", "second"], "14", "1.4")
    with pytest.raises(BridgeError, match="excluded adjustment"):
        validate_bridge(bridge)


def test_unsupported_effect_not_disclosed_is_error(bridge):
    add_adjustment(bridge)["signed_effect"] = quantity()
    add_case(bridge, ["adjustment"], None, None)
    with pytest.raises(BridgeError, match="unsupported_components"):
        validate_bridge(bridge)


def test_gate_state_cannot_hide_financial_gate(bridge):
    bridge["research_card"]["existing_screening"]["gate"] = "PERSISTENT_CASH_BURN"
    with pytest.raises(BridgeError, match="cannot be hidden"):
        validate_bridge(bridge)


def test_no_nonfinite_values_even_inside_open_metadata(bridge):
    observation(bridge, "revenue")["canonical_metadata"]["fact"] = {
        "untyped": float("inf")
    }
    with pytest.raises(BridgeError, match="finite"):
        validate_bridge(bridge)


def test_cli_offline_no_store_or_settings_and_no_input_writes(
    bridge, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(bridge))
    before = path.read_bytes()
    monkeypatch.setattr(cli, "load_settings", lambda: pytest.fail("No settings"))
    monkeypatch.setattr(
        cli, "build_local_store", lambda *a, **k: pytest.fail("No database")
    )
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("No network"))
    assert cli.main(["owner-earnings-bridge", "--file", str(path)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["cases"][0]["outcome"] == "VALID_REPORTED_BASELINE"
    assert output.err == "" and path.read_bytes() == before
    observation(bridge, "free_cash_flow")["quantity"]["amount"] = "99"
    path.write_text(json.dumps(bridge))
    assert cli.main(["owner-earnings-bridge", "--file", str(path)]) == 2
    assert "Invalid Owner Earnings Bridge" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    [
        '{"purpose":"RESEARCH_ONLY","purpose":"RESEARCH_ONLY"}',
        '{"value":NaN}',
        '{"value":Infinity}',
        "{",
    ],
)
def test_file_loading_errors(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(BridgeError):
        load_bridge(path)


def test_missing_file(tmp_path):
    with pytest.raises(BridgeError, match="Cannot load"):
        load_bridge(tmp_path / "absent.json")


@pytest.mark.parametrize("ticker", ["ORCL", "JPM"])
def test_synthetic_cross_business_controls(bridge, ticker):
    bridge["identity"].update(
        ticker=ticker, company_name=f"{ticker} SYNTHETIC STRUCTURAL CONTROL"
    )
    bridge["research_card"]["existing_screening"]["gate"] = "PERSISTENT_CASH_BURN"
    bridge["research_card"]["financial_fragility"]["state"] = "ACTIVATED_EXISTING_GATE"
    if ticker == "ORCL":
        observation(bridge, "operating_cash_flow")["quantity"] = quantity("3")
        observation(bridge, "free_cash_flow")["quantity"] = quantity("-2")
        observation(bridge, "fcf_per_share")["quantity"] = quantity(
            "-0.2", unit="USD/share"
        )
        bridge["conditional_owner_earnings"][0].update(
            owner_earnings=quantity("-2"),
            owner_earnings_per_share=quantity("-0.2", unit="USD/share"),
        )
        adjustment = add_adjustment(bridge)
        adjustment.update(
            adjustment_type="MAINTENANCE_GROWTH_REINVESTMENT",
            category="JUDGMENT",
            signed_effect=quantity(),
        )
        case = add_case(bridge, ["adjustment"], None, None)
        case["unsupported_components"] = ["adjustment"]
    else:
        bridge["research_card"]["evidence_limitations"] = [
            {
                "code": "SECTOR_COMPARABILITY_NOT_VERIFIED",
                "explanation": "Synthetic financial-sector control: generic industrial FCF is inappropriate.",
                "source_ids": [],
            }
        ]
    result = validate_bridge(bridge)
    assert "PERSISTENT_CASH_BURN" in result.to_json()
    assert "price_to_fcf" not in result.to_json()
    if ticker == "ORCL":
        assert result.cases[0].total["amount"] == "-2"
        assert result.cases[1].outcome == "UNRESOLVED" and result.cases[1].total is None
    else:
        assert "SECTOR_COMPARABILITY_NOT_VERIFIED" in result.to_json()

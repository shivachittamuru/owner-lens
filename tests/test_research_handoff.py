"""Manual handoff integrity and offline/immutable boundaries."""

from __future__ import annotations

import json
import socket
import sqlite3
from copy import deepcopy
from datetime import date
from pathlib import Path

import httpx
import pytest

from owner_lens import cli
from owner_lens.owner_earnings_bridge import BridgeError
from owner_lens.research_handoff import (
    TOPICS,
    bridge_fingerprint,
    export_research_package,
    load_document,
    load_response_schema,
    review_research_response,
)

EXAMPLES = Path(__file__).parents[1] / "docs" / "examples"
BRIDGE = EXAMPLES / "deck_owner_earnings_bridge_v1.sample.json"
RESPONSE = EXAMPLES / "deck_research_response_v1.sample.json"
AS_OF = date(2026, 11, 10)


@pytest.fixture
def bridge():
    return load_document(BRIDGE)


@pytest.fixture
def response():
    return load_document(RESPONSE)


def review(bridge, response):
    return review_research_response(bridge, response, as_of=AS_OF)


def context_for(bridge):
    screening = bridge["research_card"]["existing_screening"]
    return {
        "identity [FACT]": {
            "ticker": "DECK",
            "provider": "fmp",
            "evidence_as_of": "2026-10-31T08:29:57+00:00",
        },
        "screening [CALCULATION]": {
            **{
                k: screening[k] for k in ("priority", "setup", "coverage", "dimensions")
            },
            "holds_back": [screening["gate"]] if screening["gate"] else [],
        },
        "economics [FACT/CALCULATION]": {
            "fiscal_year": 2026,
            "revenue": 5472296000,
            "FCF": 1097332000,
            "FCF_per_share": 7.526024484757039,
        },
        "market_expectations [EXPECTATION]": "No captured estimates.",
        "underwriting": "No extra frozen input supplied.",
    }


def test_export_deterministic_bound_complete_and_no_input_mutation(bridge):
    before = deepcopy(bridge)
    package = export_research_package(bridge)
    assert package == export_research_package(bridge)
    assert bridge == before
    for text in (
        bridge_fingerprint(bridge),
        "1097332000",
        "7.526024484757039",
        "working-capital",
        "maintenance-growth",
        "sbc-dilution",
        "FACT",
        "CALCULATION",
        "EXPECTATION",
        "ASSUMPTION",
        "JUDGMENT",
        "UNREVIEWED",
        "NOT_VERIFIED",
        "UNVERIFIED",
        "disconfirming",
        "No gate does not mean safe",
        "Response schema",
    ):
        assert text in package
    assert str(BRIDGE.parent) not in package
    assert "No Copy Research Context supplied." in package


def test_optional_context_export_is_sanitized(bridge):
    context = context_for(bridge)
    context["underwriting"] = {
        "note": (
            "api_key=SECRETQUERY Authorization: Bearer SECRETBEARER "
            r"C:\Users\Private\private.env \\server\private\file /opt/private/file "
            "/mnt/private/file ./private.env "
            "https://user:pass@example.com/data?apikey=SECRETURL "
            "ghp_SECRETGITHUB"
        ),
        "nested": {"password": "SECRETVALUE", "api_key": "KEYVALUE"},
        r"C:\Users\PRIVATEKEY": "normal",
    }
    package = export_research_package(bridge, context)
    for secret in (
        "SECRETQUERY",
        "SECRETBEARER",
        "SECRETURL",
        "SECRETGITHUB",
        "SECRETVALUE",
        "KEYVALUE",
        "PRIVATEKEY",
        "Private",
        "private.env",
    ):
        assert secret not in package
    assert "[REDACTED]" in package
    assert "No captured estimates." in package


@pytest.mark.parametrize(
    "text",
    [
        r"C:\Users\confidential\file.env",
        r"\\server\confidential\file.env",
        "/opt/confidential/file.env",
        "~/confidential/file.env",
        "./confidential/file.env",
        "Bearer confidential",
        "https://host.example/path?api_key=confidential",
        "api-key: confidential",
        "token=confidential",
        "ghp_confidential",
        "-----BEGIN PRIVATE KEY-----\nconfidential\n-----END PRIVATE KEY-----",
    ],
)
def test_redaction_does_not_depend_on_other_secrets_in_same_string(bridge, text):
    bridge["research_card"]["next_evidence"].append(text)
    assert "confidential" not in export_research_package(bridge)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ticker", "OTHER"),
        ("provider", "sec"),
        ("evidence_as_of", "2099-01-01T00:00:00Z"),
    ],
)
def test_context_identity_and_chronology(bridge, field, value):
    context = context_for(bridge)
    context["identity [FACT]"][field] = value
    with pytest.raises(BridgeError, match="identity|observation"):
        export_research_package(bridge, context)


def test_context_cannot_override_canonical_or_screening(bridge):
    context = context_for(bridge)
    context["economics [FACT/CALCULATION]"]["FCF"] = 1
    with pytest.raises(BridgeError, match="FCF differs"):
        export_research_package(bridge, context)
    context = context_for(bridge)
    context["screening [CALCULATION]"]["priority"] = "LOW_PRIORITY"
    with pytest.raises(BridgeError, match="priority differs"):
        export_research_package(bridge, context)


def test_deck_sample_is_consistent_but_needs_evidence(bridge, response):
    before = deepcopy(response)
    result = review(bridge, response)
    assert result.outcome == "NEEDS_MORE_EVIDENCE" and not result.errors
    assert response == before
    assert any(
        "normalization remains unresolved" in gap for gap in result.evidence_gaps
    )
    assert any("disconfirming" in gap for gap in result.evidence_gaps)
    assert "Revenue growth" in result.handoff_markdown
    assert "Terminal FCF multiple" in result.handoff_markdown
    assert "UNREVIEWED" in result.handoff_markdown
    assert any("currency" in note for note in result.limitations)
    assert "9201c0b0" in result.handoff_markdown


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_version", "research-response/2"),
        ("bridge_version", "owner-earnings-bridge/2"),
        ("bridge_sha256", "0" * 64),
        ("identity", {"store_namespace": "other", "security_id": 50, "ticker": "DECK"}),
        ("research_as_of", "2026-11-09"),
        ("research_as_of", "2026-11-11"),
        ("preserved_gate", "PERSISTENT_CASH_BURN"),
        ("canonical_observation_ids", []),
        ("preserved_limitation_codes", []),
        ("unresolved_adjustment_ids", []),
        ("reported_owner_economics", [{"metric": "free_cash_flow", "amount": "999"}]),
        ("probability_distribution", {"BASE": 1}),
    ],
)
def test_invalid_response_controls(bridge, response, field, value):
    response[field] = value
    result = review(bridge, response)
    assert result.outcome == "INVALID_RESEARCH_RESPONSE"
    assert result.errors and not result.handoff_markdown


@pytest.mark.parametrize(
    "location", ["source_ids", "observation_ids", "supporting_ids", "disconfirming_ids"]
)
def test_unknown_claim_references(bridge, response, location):
    response["claims"][0][location] = ["nonexistent"]
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_unverified_external_claims_never_become_verified(bridge, response):
    response["sources"].append(
        {
            "source_id": "external-note",
            "title": "Unverified example",
            "url": "https://example.com/research",
            "publication_date": "2026-11-09",
            "observed_at": "2026-11-10T00:00:00Z",
            "verification_status": "UNVERIFIED_EXTERNAL",
        }
    )
    response["claims"][1].update(
        category="FACT",
        text="Unverified external assertion.",
        source_ids=["external-note"],
        unresolved=False,
    )
    result = review(bridge, response)
    assert result.outcome == "NEEDS_MORE_EVIDENCE"
    assert any("independent investor verification" in g for g in result.evidence_gaps)
    assert any("not verified by citations" in g for g in result.evidence_gaps)
    response["sources"][-1]["verification_status"] = "VERIFIED"
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_id", "not-a-bridge-source"),
        ("title", "Altered title"),
        ("observed_at", "2027-01-01T00:00:00Z"),
        ("publication_date", "2026-11-11"),
        ("url", "https://example.com/?token=confidential"),
    ],
)
def test_source_reference_mutation(bridge, response, key, value):
    response["sources"][0][key] = value
    result = review(bridge, response)
    assert result.outcome == "INVALID_RESEARCH_RESPONSE"
    assert "confidential" not in result.to_json()


def test_equivalent_source_timestamps_survive_manual_json_roundtrip(bridge, response):
    response["sources"][0]["observed_at"] = "2026-10-31T08:29:57.2157430Z"
    response["sources"][1]["observed_at"] = "2026-10-31T01:29:57.495460-07:00"
    assert review(bridge, response).outcome == "NEEDS_MORE_EVIDENCE"


def test_attempted_canonical_fact_rewrite(bridge, response):
    response["claims"][0]["text"] = "Canonical FCF is USD 999."
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_missing_disconfirmation_does_not_pass(bridge, response):
    response["claims"][0]["material"] = True
    result = review(bridge, response)
    assert any(
        "cash-baseline-citation" in g and "disconfirming" in g
        for g in result.evidence_gaps
    )


@pytest.mark.parametrize("category", ["CALCULATION", "JUDGMENT"])
def test_unsupported_numeric_normalization_not_certified(bridge, response, category):
    response["adjustment_proposals"][0].update(
        category=category, effect={"lower": "1", "upper": "2", "unit": "USD"}
    )
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_hypothetical_adjustment_stays_unreviewed(bridge, response):
    proposal = response["adjustment_proposals"][0]
    proposal.update(
        category="ASSUMPTION", effect={"lower": "-2", "upper": "1", "unit": "USD"}
    )
    assert review(bridge, response).outcome == "NEEDS_MORE_EVIDENCE"
    assert proposal["approval"] == "UNREVIEWED"
    proposal["approval"] = "INVESTOR_APPROVED"
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_supported_effect_must_match_validated_bridge(bridge, response):
    adjustment = bridge["normalization_adjustments"][0]
    adjustment.update(category="CALCULATION", approval="NOT_REQUIRED_DETERMINISTIC")
    adjustment["signed_effect"].update(status="AVAILABLE", amount="2")
    response["bridge_sha256"] = bridge_fingerprint(bridge)
    proposal = response["adjustment_proposals"][0]
    proposal.update(
        category="CALCULATION",
        effect={"lower": "2", "upper": "2", "unit": "USD"},
    )
    assert review(bridge, response).outcome == "NEEDS_MORE_EVIDENCE"
    proposal["effect"]["upper"] = "3"
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


@pytest.mark.parametrize(
    "driver,low,high,unit",
    [
        ("revenue_cagr", "-1", "0", "ratio"),
        ("share_count_cagr", "0.1", "0", "ratio"),
        ("terminal_fcf_multiple", "0", "20", "multiple"),
        ("terminal_fcf_multiple", "10", "20", "ratio"),
        ("fcf_margin_year5", "0.1", "0.2", "USD"),
    ],
)
def test_scenario_range_units_and_bounds(bridge, response, driver, low, high, unit):
    proposal = next(p for p in response["scenario_proposals"] if p["driver"] == driver)
    proposal["range"] = {"lower": low, "upper": high, "unit": unit}
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_missing_margin_dependencies_rejected(bridge, response):
    response["scenario_proposals"][1]["adjustment_dependencies"] = []
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_unsupported_citations_are_actionable_gaps(bridge, response):
    response["claims"][1]["supporting_ids"] = ["sti-26"]
    response["claims"][1]["disconfirming_ids"] = ["durability-question"]
    result = review(bridge, response)
    assert any("unsupported observation sti-26" in gap for gap in result.evidence_gaps)
    assert any(
        "unresolved bridge claim durability-question" in gap
        for gap in result.evidence_gaps
    )


def test_malformed_context_number_is_explicit_error(bridge):
    context = context_for(bridge)
    context["economics [FACT/CALCULATION]"]["FCF"] = "not-a-number"
    with pytest.raises(BridgeError, match="FCF is not numeric"):
        export_research_package(bridge, context)


def test_survival_gate_cannot_disappear(bridge, response):
    bridge["research_card"]["existing_screening"]["gate"] = "PERSISTENT_CASH_BURN"
    bridge["research_card"]["financial_fragility"]["state"] = "ACTIVATED_EXISTING_GATE"
    response["bridge_sha256"] = bridge_fingerprint(bridge)
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"
    response["preserved_gate"] = "PERSISTENT_CASH_BURN"
    result = review(bridge, response)
    assert result.outcome == "NEEDS_MORE_EVIDENCE"
    assert "PERSISTENT_CASH_BURN" in result.handoff_markdown
    assert "PERSISTENT_CASH_BURN" in export_research_package(bridge)


def test_market_expectations_cannot_be_inferred_from_judgment(bridge, response):
    response["market_expectations"].update(
        status="SUPPORTED", source_ids=["price-2026-10-30"], claim_ids=["market-gap"]
    )
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"
    response["claims"][-2]["category"] = "EXPECTATION"
    result = review(bridge, response)
    assert result.outcome == "NEEDS_MORE_EVIDENCE"
    assert any("horizon/unit" in g for g in result.evidence_gaps)


def test_explicit_workflow_state_transitions(bridge, response):
    # Synthetic completeness control, not completed DECK research or new company facts.
    bridge["identity"]["ticker"] = "SYNTHETIC"
    bridge["normalization_adjustments"] = []
    bridge["conditional_owner_earnings"] = bridge["conditional_owner_earnings"][:1]
    bridge["conditional_owner_earnings"][0]["unsupported_components"] = []
    response["identity"]["ticker"] = "SYNTHETIC"
    response["bridge_sha256"] = bridge_fingerprint(bridge)
    response["unresolved_adjustment_ids"] = []
    response["adjustment_proposals"] = []
    response["scenario_proposals"] = []
    response["evidence_gaps"] = []
    response["research_decision"] = "WATCHLIST"
    for index, claim in enumerate(response["claims"]):
        claim.update(
            category="JUDGMENT",
            text=f"Synthetic qualitative hypothesis {index}.",
            source_ids=["cash-fy2026"],
            observation_ids=[],
            supporting_ids=["fcf-26"],
            disconfirming_ids=["revenue-26"],
            unresolved=False,
            material=True,
            observation_date="2026-10-31",
        )
    assert {c["topic"] for c in response["claims"]} == set(TOPICS)
    assert review(bridge, response).outcome == "READY_FOR_INVESTOR_REVIEW"
    response["claims"][0]["disconfirming_ids"] = []
    assert review(bridge, response).outcome == "NEEDS_MORE_EVIDENCE"
    response["claims"][0]["supporting_ids"] = ["no-such-id"]
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_cyclic_claims_rejected(bridge, response):
    response["claims"][0]["supporting_ids"] = ["business-question"]
    response["claims"][1]["supporting_ids"] = ["cash-baseline-citation"]
    assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"


def test_schema_available_from_wheel_data_location(tmp_path, monkeypatch):
    from owner_lens import research_handoff

    target = tmp_path / "examples" / research_handoff.SCHEMA_NAME
    target.parent.mkdir()
    target.write_bytes((EXAMPLES / research_handoff.SCHEMA_NAME).read_bytes())
    monkeypatch.setattr(
        research_handoff,
        "__file__",
        str(tmp_path / "site" / "owner_lens" / "research_handoff.py"),
    )
    monkeypatch.setattr(
        research_handoff.sysconfig, "get_path", lambda name: str(tmp_path)
    )
    assert (
        load_response_schema()["properties"]["response_version"]["const"]
        == "research-response/1"
    )


def test_cli_no_settings_database_network_or_writes(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("No network/database/settings access allowed")

    monkeypatch.setattr(cli, "load_settings", forbidden)
    monkeypatch.setattr(cli, "build_local_store", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    before = {p: p.read_bytes() for p in (BRIDGE, RESPONSE)}
    assert cli.main(["research-export", "--bridge", str(BRIDGE)]) == 0
    assert "Research instructions" in capsys.readouterr().out
    args = [
        "research-review",
        "--bridge",
        str(BRIDGE),
        "--response",
        str(RESPONSE),
        "--as-of",
        "2026-11-10",
    ]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "NEEDS_MORE_EVIDENCE"
    invalid = tmp_path / "invalid.json"
    response = load_document(RESPONSE)
    response["identity"]["ticker"] = "OTHER"
    invalid.write_text(json.dumps(response))
    args[args.index(str(RESPONSE))] = str(invalid)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "INVALID_RESEARCH_RESPONSE"
    invalid.write_text('{"duplicate": 1, "duplicate": 2}')
    assert cli.main(args) == 2
    assert "duplicate" in capsys.readouterr().err
    for p, content in before.items():
        assert p.read_bytes() == content


def test_nonfinite_and_nonobject_response(bridge):
    for response in ([1], {"bad": float("nan")}, None):
        assert review(bridge, response).outcome == "INVALID_RESEARCH_RESPONSE"

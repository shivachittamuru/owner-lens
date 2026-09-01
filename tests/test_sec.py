"""Controlled tests for SEC identity resolution and Company Facts retrieval."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from owner_lens.sec import (
    COMPANY_FACTS_URL_TEMPLATE,
    COMPANY_TICKERS_URL,
    CompanyIdentity,
    CompanyIdentityMismatchError,
    CompanyResolutionError,
    MalformedSecResponseError,
    SecClient,
    SecResponseError,
    SecTransportError,
    UnsupportedTickerError,
)

USER_AGENT = "OwnerLens admin@example.com"
ADBE_CIK = "0000796343"
ADBE_FACTS_URL = COMPANY_FACTS_URL_TEMPLATE.format(cik=ADBE_CIK)

ADBE_MAPPING = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 796343, "ticker": "ADBE", "title": "ADOBE INC."},
}

ADBE_FACTS = {
    "cik": 796343,
    "entityName": "ADOBE INC.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {
                            "start": "2022-12-03",
                            "end": "2023-12-01",
                            "val": 19409000000,
                            "accn": "0000796343-24-000008",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-01-16",
                            "frame": "CY2023",
                        }
                    ]
                },
            }
        }
    },
}


def _handler(
    responses: dict[str, httpx.Response],
    recorder: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)
        url = str(request.url)
        if url not in responses:
            raise AssertionError(f"Unexpected request URL: {url}")
        return responses[url]

    return handler


def _client(
    responses: dict[str, httpx.Response],
    recorder: list[httpx.Request] | None = None,
) -> SecClient:
    transport = httpx.MockTransport(_handler(responses, recorder))
    http_client = httpx.Client(transport=transport)
    return SecClient(USER_AGENT, http_client=http_client)


def _json_response(payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_retrieve_company_facts_returns_identity_and_raw_payload() -> None:
    recorder: list[httpx.Request] = []
    client = _client(
        {
            COMPANY_TICKERS_URL: _json_response(ADBE_MAPPING),
            ADBE_FACTS_URL: _json_response(ADBE_FACTS),
        },
        recorder,
    )

    result = client.retrieve_company_facts("ADBE")

    assert result.identity == CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )
    assert result.raw_facts == ADBE_FACTS
    assert [str(r.url) for r in recorder] == [COMPANY_TICKERS_URL, ADBE_FACTS_URL]
    for request in recorder:
        assert request.headers["User-Agent"] == USER_AGENT


def test_raw_payload_is_returned_unmodified() -> None:
    client = _client(
        {
            COMPANY_TICKERS_URL: _json_response(ADBE_MAPPING),
            ADBE_FACTS_URL: _json_response(ADBE_FACTS),
        }
    )

    result = client.retrieve_company_facts("ADBE")

    # Structural equality against the exact source payload proves no
    # normalization, selection, or coercion occurred.
    assert json.dumps(result.raw_facts, sort_keys=True) == json.dumps(
        ADBE_FACTS, sort_keys=True
    )


def test_ticker_resolution_is_case_and_whitespace_insensitive() -> None:
    client = _client({COMPANY_TICKERS_URL: _json_response(ADBE_MAPPING)})

    identity = client.resolve_company("  adbe ")

    assert identity.ticker == "ADBE"
    assert identity.cik == ADBE_CIK


def test_company_facts_request_uses_ten_digit_cik() -> None:
    recorder: list[httpx.Request] = []
    client = _client(
        {ADBE_FACTS_URL: _json_response(ADBE_FACTS)},
        recorder,
    )

    identity = CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )
    client.get_company_facts(identity)

    assert str(recorder[0].url).endswith(f"CIK{ADBE_CIK}.json")


def test_unsupported_ticker_is_rejected_without_network() -> None:
    recorder: list[httpx.Request] = []
    client = _client({}, recorder)

    with pytest.raises(UnsupportedTickerError):
        client.retrieve_company_facts("MSFT")

    assert recorder == []


def test_missing_mapping_entry_fails_explicitly() -> None:
    mapping = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    client = _client({COMPANY_TICKERS_URL: _json_response(mapping)})

    with pytest.raises(CompanyResolutionError):
        client.resolve_company("ADBE")


def test_ambiguous_mapping_entries_fail_explicitly() -> None:
    mapping = {
        "0": {"cik_str": 796343, "ticker": "ADBE", "title": "ADOBE INC."},
        "1": {"cik_str": 111111, "ticker": "ADBE", "title": "ADOBE DUP"},
    }
    client = _client({COMPANY_TICKERS_URL: _json_response(mapping)})

    with pytest.raises(CompanyResolutionError):
        client.resolve_company("ADBE")


def test_mapping_with_invalid_cik_fails_resolution() -> None:
    mapping = {"0": {"cik_str": "not-a-number", "ticker": "ADBE", "title": "ADOBE"}}
    client = _client({COMPANY_TICKERS_URL: _json_response(mapping)})

    with pytest.raises(CompanyResolutionError):
        client.resolve_company("ADBE")


def test_non_object_mapping_is_malformed() -> None:
    client = _client({COMPANY_TICKERS_URL: _json_response([1, 2, 3])})

    with pytest.raises(MalformedSecResponseError):
        client.resolve_company("ADBE")


def test_transport_failure_is_reported() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SecClient(USER_AGENT, http_client=http_client)

    with pytest.raises(SecTransportError):
        client.resolve_company("ADBE")


def test_unsuccessful_status_is_reported() -> None:
    client = _client({COMPANY_TICKERS_URL: httpx.Response(503)})

    with pytest.raises(SecResponseError):
        client.resolve_company("ADBE")


def test_non_json_response_is_malformed() -> None:
    client = _client(
        {COMPANY_TICKERS_URL: httpx.Response(200, text="not json")}
    )

    with pytest.raises(MalformedSecResponseError):
        client.resolve_company("ADBE")


def test_company_facts_missing_entity_name_is_malformed() -> None:
    payload = {"cik": 796343, "facts": {}}
    client = _client({ADBE_FACTS_URL: _json_response(payload)})
    identity = CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )

    with pytest.raises(MalformedSecResponseError):
        client.get_company_facts(identity)


def test_company_facts_missing_facts_object_is_malformed() -> None:
    payload = {"cik": 796343, "entityName": "ADOBE INC."}
    client = _client({ADBE_FACTS_URL: _json_response(payload)})
    identity = CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )

    with pytest.raises(MalformedSecResponseError):
        client.get_company_facts(identity)


def test_company_facts_cik_mismatch_fails() -> None:
    payload = {"cik": 111111, "entityName": "ADOBE INC.", "facts": {}}
    client = _client({ADBE_FACTS_URL: _json_response(payload)})
    identity = CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )

    with pytest.raises(CompanyIdentityMismatchError):
        client.get_company_facts(identity)


def test_company_facts_with_empty_facts_is_valid() -> None:
    payload = {"cik": 796343, "entityName": "ADOBE INC.", "facts": {}}
    client = _client({ADBE_FACTS_URL: _json_response(payload)})
    identity = CompanyIdentity(
        ticker="ADBE", company_name="ADOBE INC.", cik=ADBE_CIK
    )

    assert client.get_company_facts(identity) == payload


def test_empty_user_agent_is_rejected() -> None:
    with pytest.raises(ValueError):
        SecClient("   ")

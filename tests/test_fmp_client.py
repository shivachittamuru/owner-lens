"""Tests for the FMP annual-statement client (Slice 5B). No network access."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _fmp_fixtures import fmp_payloads

from owner_lens.fmp import (
    FmpAuthenticationError,
    FmpClient,
    FmpConfigurationError,
    FmpPlanRestrictionError,
    FmpRateLimitError,
    FmpResponseError,
    FmpSymbolNotFoundError,
    FmpTransportError,
    MalformedFmpResponseError,
)

KEY = "secret-test-key-123"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> FmpClient:
    return FmpClient(KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok(payloads: dict[str, Any], seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=payloads[endpoint])

    return handler


def test_retrieves_three_annual_statements_with_expected_parameters() -> None:
    seen: list[httpx.Request] = []
    statements = _client(_ok(fmp_payloads(), seen)).retrieve_annual_statements(" adbe ", limit=3)

    assert statements.symbol == "ADBE"
    assert [r["fiscalYear"] for r in statements.income] == ["2025", "2024", "2023"]
    assert len(statements.balance_sheet) == len(statements.cash_flow) == 3
    paths = [r.url.path for r in seen]
    assert paths == [
        "/stable/income-statement",
        "/stable/balance-sheet-statement",
        "/stable/cash-flow-statement",
    ]
    for request in seen:
        assert request.url.params["symbol"] == "ADBE"
        assert request.url.params["period"] == "annual"
        assert request.url.params["limit"] == "3"
        assert request.url.params["apikey"] == KEY
    assert all(KEY not in url and "apikey=<redacted>" in url for url in statements.source_urls)


@pytest.mark.parametrize("key", ["", "   "])
def test_blank_api_key_is_a_configuration_error(key: str) -> None:
    with pytest.raises(FmpConfigurationError, match="OWNER_LENS_FMP_API_KEY"):
        FmpClient(key)


def test_api_key_is_not_in_repr() -> None:
    assert KEY not in repr(FmpClient(KEY))


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"Error Message": f"Invalid API KEY {KEY}"}, FmpAuthenticationError),
        (403, {"Error Message": "Forbidden"}, FmpAuthenticationError),
        (402, "Premium Query Parameter: symbol not available", FmpPlanRestrictionError),
        (429, {"Error Message": "Limit Reach"}, FmpRateLimitError),
        (500, "server error", FmpResponseError),
    ],
)
def test_http_failures_are_typed_and_redacted(status: int, body: Any, error: type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = body if isinstance(body, str) else json.dumps(body)
        return httpx.Response(status, text=content)

    with pytest.raises(error) as info:
        _client(handler).retrieve_annual_statements("ADBE")
    assert KEY not in str(info.value)
    assert info.value.status_code == status


def test_ok_status_with_api_error_message_is_a_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Error Message": "Something failed"})

    with pytest.raises(FmpResponseError, match="Something failed"):
        _client(handler).retrieve_annual_statements("ADBE")


def test_transport_failure_is_typed_and_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}", request=request)

    with pytest.raises(FmpTransportError) as info:
        _client(handler).retrieve_annual_statements("ADBE")
    assert KEY not in str(info.value)
    assert info.value.__cause__ is None


def test_non_json_body_is_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(MalformedFmpResponseError):
        _client(handler).retrieve_annual_statements("ADBE")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: {"rows": rows}, "not a JSON list"),
        (lambda rows: [*rows, "oops"], "not a JSON object"),
        (lambda rows: [{**rows[0], "symbol": "MSFT"}], "identifies 'MSFT'"),
        (lambda rows: [{**rows[0], "period": "Q4"}], "not an annual FY period"),
        (lambda rows: [{**rows[0], "date": "not-a-date"}], "invalid date"),
    ],
)
def test_malformed_statement_shapes(mutate: Callable[[Any], Any], message: str) -> None:
    payloads = fmp_payloads()
    payloads["income-statement"] = mutate(payloads["income-statement"])
    with pytest.raises(MalformedFmpResponseError, match=message):
        _client(_ok(payloads)).retrieve_annual_statements("ADBE")


def test_empty_statement_list_means_symbol_not_found() -> None:
    payloads = fmp_payloads()
    payloads["balance-sheet-statement"] = []
    with pytest.raises(FmpSymbolNotFoundError):
        _client(_ok(payloads)).retrieve_annual_statements("ADBE")


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_limit_is_rejected_before_any_request(limit: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(ValueError, match="limit"):
        _client(handler).retrieve_annual_statements("ADBE", limit=limit)

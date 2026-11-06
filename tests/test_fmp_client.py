"""Tests for the FMP annual-statement client (Slice 5B). No network access."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
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
    FmpResponseCache,
    FmpResponseError,
    FmpSymbolNotFoundError,
    FmpTransportError,
    MalformedFmpResponseError,
)

KEY = "secret-test-key-123"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    cache: FmpResponseCache | None = None,
) -> FmpClient:
    return FmpClient(
        KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=cache,
    )


def _ok(payloads: dict[str, Any], seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        endpoint = request.url.path.removeprefix("/stable/")
        if endpoint not in payloads:
            endpoint = endpoint.rsplit("/", 1)[-1]
        return httpx.Response(200, json=payloads[endpoint])

    return handler


def test_retrieves_three_annual_statements_with_expected_parameters() -> None:
    seen: list[httpx.Request] = []
    statements = _client(_ok(fmp_payloads(), seen)).retrieve_annual_statements(
        " adbe ", limit=3
    )

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
    assert all(
        KEY not in url and "apikey=<redacted>" in url for url in statements.source_urls
    )


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
def test_http_failures_are_typed_and_redacted(
    status: int, body: Any, error: type
) -> None:
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


def test_premium_evidence_endpoints_preserve_raw_payload_and_parameters() -> None:
    seen: list[httpx.Request] = []
    responses: dict[str, Any] = {
        "/stable/income-statement": [
            {
                "symbol": "ADBE",
                "date": "2025-12-31",
                "fiscalYear": "2025",
                "period": "FY",
            }
        ],
        "/stable/analyst-estimates": [
            {"symbol": "ADBE", "date": "2026-12-31", "revenueAvg": 100.0}
        ],
        "/stable/historical-price-eod/light": [
            {"symbol": "ADBE", "date": "2026-01-02", "price": 123.45}
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=responses[request.url.path])

    client = _client(handler)
    annual = client.get_statement_evidence("income", "ADBE", period="annual", limit=15)
    estimate = client.get_analyst_estimates_evidence("ADBE", period="quarter", limit=4)
    eod = client.get_eod_price_evidence("ADBE")

    assert annual.rows[0]["period"] == "FY"
    assert json.loads(annual.raw_payload)[0]["symbol"] == "ADBE"
    assert seen[0].url.params["period"] == "annual"
    assert seen[0].url.params["limit"] == "15"
    assert seen[1].url.params["period"] == "quarter"
    assert seen[1].url.params["limit"] == "4"
    assert seen[1].url.params["page"] == "0"
    assert seen[2].url.path == "/stable/historical-price-eod/light"
    assert eod.rows[0]["price"] == 123.45
    assert estimate.endpoint == "analyst-estimates"


def test_historical_price_profile_and_splits_evidence_preserve_raw_responses() -> None:
    seen: list[httpx.Request] = []
    responses: dict[str, Any] = {
        "historical-price-eod/full": [
            {"symbol": "NVDA", "date": "2024-06-10", "close": 121.79}
        ],
        "profile": [
            {"symbol": "NVDA", "currency": "USD", "exchangeShortName": "NASDAQ"}
        ],
        "splits": [
            {
                "symbol": "NVDA",
                "date": "2024-06-10",
                "numerator": 10,
                "denominator": 1,
            }
        ],
    }
    client = _client(_ok(responses, seen))
    start_date, end_date = date(2024, 6, 1), date(2024, 6, 30)

    history = client.get_historical_price_evidence(
        "nvda", start_date=start_date, end_date=end_date
    )
    profile = client.get_profile_evidence("NVDA")
    splits = client.get_splits_evidence(
        "NVDA", start_date=start_date, end_date=end_date
    )

    assert [request.url.path for request in seen] == [
        "/stable/historical-price-eod/full",
        "/stable/profile",
        "/stable/splits",
    ]
    assert seen[0].url.params["from"] == "2024-06-01"
    assert seen[0].url.params["to"] == "2024-06-30"
    assert history.rows[0]["close"] == 121.79
    assert history.raw_payload.startswith(b"[")
    assert profile.rows[0]["currency"] == "USD"
    assert splits.rows[0]["numerator"] == 10
    assert all(KEY not in payload.source_url for payload in (history, profile, splits))
    assert all(payload.request_parameters for payload in (history, profile, splits))


@pytest.mark.parametrize(
    "row",
    [
        {"symbol": "OTHER", "date": "2024-06-10", "close": 10.0},
        {"symbol": "NVDA", "date": "2024-06-31", "close": 10.0},
        {"symbol": "NVDA", "date": "2024-06-10", "close": float("nan")},
        {"symbol": "NVDA", "date": "2024-06-10", "close": -1.0},
    ],
)
def test_historical_prices_reject_identity_date_and_price_errors(
    row: dict[str, Any],
) -> None:
    client = _client(
        lambda _request: httpx.Response(
            200, content=json.dumps([row], allow_nan=True).encode()
        )
    )
    with pytest.raises(MalformedFmpResponseError):
        client.get_historical_price_evidence(
            "NVDA", start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )


def test_profile_and_split_evidence_reject_identity_and_invalid_split() -> None:
    profile_client = _client(
        lambda _request: httpx.Response(
            200, json=[{"symbol": "OTHER", "currency": "USD"}]
        )
    )
    with pytest.raises(MalformedFmpResponseError, match="not NVDA"):
        profile_client.get_profile_evidence("NVDA")

    split_client = _client(
        lambda _request: httpx.Response(
            200,
            json=[
                {
                    "symbol": "NVDA",
                    "date": "2024-06-10",
                    "numerator": 10,
                    "denominator": 0,
                }
            ],
        )
    )
    with pytest.raises(MalformedFmpResponseError, match="denominator"):
        split_client.get_splits_evidence(
            "NVDA", start_date=date(2024, 6, 1), end_date=date(2024, 6, 30)
        )


def test_historical_price_range_is_bounded_and_not_future() -> None:
    client = _client(lambda _request: httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match="limited to three years"):
        client.get_historical_price_evidence(
            "NVDA", start_date=date(2020, 1, 1), end_date=date(2024, 1, 2)
        )
    with pytest.raises(ValueError, match="future"):
        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        client.get_historical_price_evidence(
            "NVDA",
            start_date=tomorrow,
            end_date=tomorrow,
        )


def test_quarterly_statement_request_uses_fmp_period_label() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "ADBE",
                    "date": "2025-03-31",
                    "fiscalYear": "2025",
                    "period": "Q1",
                }
            ],
        )

    payload = _client(handler).get_statement_evidence(
        "income", "ADBE", period="quarter", limit=8
    )

    assert seen[0].url.params["period"] == "quarter"
    assert payload.request_parameters == (
        ("limit", "8"),
        ("period", "quarter"),
        ("symbol", "ADBE"),
    )


def test_premium_evidence_rejects_duplicate_quarterly_periods() -> None:
    row = {
        "symbol": "ADBE",
        "date": "2025-03-31",
        "fiscalYear": "2025",
        "period": "Q1",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row, row])

    with pytest.raises(MalformedFmpResponseError, match="duplicate quarter period"):
        _client(handler).get_statement_evidence(
            "income", "ADBE", period="quarter", limit=8
        )


def test_premium_estimates_reject_duplicate_target_periods() -> None:
    row = {"symbol": "ADBE", "date": "2026-12-31"}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row, row])

    with pytest.raises(MalformedFmpResponseError, match="duplicate target date"):
        _client(handler).get_analyst_estimates_evidence(
            "ADBE", period="annual", limit=3
        )


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_limit_is_rejected_before_any_request(limit: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(ValueError, match="limit"):
        _client(handler).retrieve_annual_statements("ADBE", limit=limit)


# --- Local raw-response cache -------------------------------------------------


def _counting(payloads: dict[str, Any], calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.path}?limit={request.url.params['limit']}")
        endpoint = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=payloads[endpoint])

    return handler


def test_default_client_caches_under_data_raw_fmp() -> None:
    client = FmpClient(KEY)
    assert client.cache is not None
    assert client.cache.root == Path("data/raw/fmp")


def test_cache_miss_calls_fmp_and_writes_raw_json(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = FmpResponseCache(tmp_path)
    rows = _client(_counting(fmp_payloads(), calls), cache).get_income_statement("adbe")

    assert len(calls) == 1
    path = tmp_path / "income-statement" / "ADBE.annual.limit5.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == list(rows)
    assert KEY not in path.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("*.tmp"))


def test_cache_hit_makes_no_network_call(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = FmpResponseCache(tmp_path)
    first = _client(_counting(fmp_payloads(), calls), cache).retrieve_annual_statements(
        "ADBE"
    )

    def offline(request: httpx.Request) -> httpx.Response:
        raise AssertionError("cache hit must not call FMP")

    second = _client(offline, cache).retrieve_annual_statements("ADBE")
    assert len(calls) == 3
    assert second == first


def test_endpoints_and_parameters_do_not_collide(tmp_path: Path) -> None:
    calls: list[str] = []
    cache = FmpResponseCache(tmp_path)
    client = _client(_counting(fmp_payloads(), calls), cache)
    client.get_income_statement("ADBE", limit=5)
    client.get_income_statement("ADBE", limit=3)
    client.get_cash_flow_statement("ADBE", limit=5)
    client.get_income_statement("ADBE", limit=3)  # cached

    assert calls == [
        "/stable/income-statement?limit=5",
        "/stable/income-statement?limit=3",
        "/stable/cash-flow-statement?limit=5",
    ]
    names = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json"))
    assert names == [
        "cash-flow-statement/ADBE.annual.limit5.json",
        "income-statement/ADBE.annual.limit3.json",
        "income-statement/ADBE.annual.limit5.json",
    ]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (402, "Premium Query Parameter", FmpPlanRestrictionError),
        (429, '{"Error Message": "Limit Reach"}', FmpRateLimitError),
        (500, "server error", FmpResponseError),
        (200, "<html>not json</html>", MalformedFmpResponseError),
        (200, '{"Error Message": "bad"}', FmpResponseError),
        (200, "[]", FmpSymbolNotFoundError),
    ],
)
def test_failed_responses_are_not_cached(
    tmp_path: Path, status: int, body: str, error: type
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    with pytest.raises(error):
        _client(handler, FmpResponseCache(tmp_path)).get_income_statement("ADBE")
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "corrupt",
    [
        "{not json",
        '{"rows": []}',
        '[{"symbol": "MSFT", "period": "FY", "date": "2025-11-30"}]',
    ],
)
def test_invalid_cache_entry_is_refetched_and_overwritten(
    tmp_path: Path, corrupt: str
) -> None:
    cache = FmpResponseCache(tmp_path)
    path = cache.path("income-statement", "ADBE", period="annual", limit=5)
    assert path is not None
    path.parent.mkdir(parents=True)
    path.write_text(corrupt, encoding="utf-8")

    calls: list[str] = []
    rows = _client(_counting(fmp_payloads(), calls), cache).get_income_statement("ADBE")
    assert len(calls) == 1
    assert rows[0]["symbol"] == "ADBE"
    assert json.loads(path.read_text(encoding="utf-8"))[0]["symbol"] == "ADBE"


def test_refresh_bypasses_cache_and_overwrites(tmp_path: Path) -> None:
    cache = FmpResponseCache(tmp_path)
    calls: list[str] = []
    payloads = fmp_payloads()
    client = _client(_counting(payloads, calls), cache)
    client.get_income_statement("ADBE")
    payloads["income-statement"][0]["revenue"] = 1

    refreshed = client.get_income_statement("ADBE", refresh=True)
    assert len(calls) == 2
    assert refreshed[0]["revenue"] == 1
    assert client.get_income_statement("ADBE")[0]["revenue"] == 1
    assert len(calls) == 2


def test_failed_refresh_keeps_previous_cache_entry(tmp_path: Path) -> None:
    cache = FmpResponseCache(tmp_path)
    _client(_ok(fmp_payloads()), cache).get_income_statement("ADBE")
    path = tmp_path / "income-statement" / "ADBE.annual.limit5.json"
    before = path.read_text(encoding="utf-8")

    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Limit Reach")

    with pytest.raises(FmpRateLimitError):
        _client(limited, cache).get_income_statement("ADBE", refresh=True)
    assert path.read_text(encoding="utf-8") == before


def test_path_unsafe_symbol_is_never_cached(tmp_path: Path) -> None:
    cache = FmpResponseCache(tmp_path)
    assert cache.path("income-statement", "../ADBE", period="annual", limit=5) is None
    assert cache.path("income-statement", "BRK.B", period="annual", limit=5) is not None


def test_disabled_cache_always_calls_fmp(tmp_path: Path) -> None:
    calls: list[str] = []
    client = _client(_counting(fmp_payloads(), calls), cache=None)
    client.get_income_statement("ADBE")
    client.get_income_statement("ADBE")
    assert len(calls) == 2

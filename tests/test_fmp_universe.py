"""Fixture-only tests for FMP S&P 500 constituent retrieval and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from _fmp_universe_fixtures import sp500_payload

from owner_lens.fmp import (
    FMP_SP500_ENDPOINT,
    FmpAuthenticationError,
    FmpClient,
    FmpRateLimitError,
    FmpResponseCache,
    MalformedFmpResponseError,
)

KEY = "fixture-fmp-key"


def _client(
    payload: Any,
    *,
    cache: FmpResponseCache | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    seen: list[httpx.Request] | None = None,
) -> FmpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(
            status_code,
            text=payload if isinstance(payload, str) else json.dumps(payload),
            headers=headers,
        )

    return FmpClient(
        KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=cache,
    )


def test_sp500_endpoint_parses_metadata_without_exact_count_assumption(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []
    raw = json.dumps(sp500_payload()).encode()
    result = _client(sp500_payload(), cache=FmpResponseCache(tmp_path), seen=seen)
    constituents = result.get_sp500_constituents()

    assert len(constituents.members) == 4
    assert [member.symbol for member in constituents.members] == [
        "ADBE",
        "GOOG",
        "GOOGL",
        "MSFT",
    ]
    assert constituents.members[0].sector == "Technology"
    assert constituents.members[0].subsector == "Application Software"
    assert constituents.members[0].cik == "0000796343"
    assert constituents.raw_payload == raw
    assert constituents.source_url.endswith(f"/{FMP_SP500_ENDPOINT}")
    assert KEY not in constituents.source_url
    assert len(seen) == 1
    assert seen[0].url.path.endswith(f"/{FMP_SP500_ENDPOINT}")
    assert dict(seen[0].url.params) == {"apikey": KEY}


def test_duplicate_issuer_cik_is_allowed_but_share_classes_are_distinct() -> None:
    members = _client(sp500_payload()).get_sp500_constituents().members

    goog = next(member for member in members if member.symbol == "GOOG")
    googl = next(member for member in members if member.symbol == "GOOGL")
    assert goog.cik == googl.cik
    assert goog.symbol != googl.symbol


@pytest.mark.parametrize(
    "payload",
    [
        [{"symbol": "ADBE", "name": "Adobe"}, {"symbol": "adbe", "name": "Adobe"}],
        [{"symbol": "../ADBE", "name": "Adobe"}],
        [{"symbol": "ADBE", "name": ""}],
        [{"symbol": "ADBE", "name": "Adobe", "cik": "not-a-cik"}],
        [{"symbol": "ADBE", "name": "Adobe", "cik": "12345678901"}],
        [],
        {"symbol": "ADBE", "name": "Adobe"},
    ],
)
def test_invalid_or_duplicate_constituents_are_rejected(payload: Any) -> None:
    with pytest.raises(MalformedFmpResponseError):
        _client(payload).get_sp500_constituents()


def test_missing_cik_and_optional_metadata_are_supported() -> None:
    row = {"symbol": "NEW", "name": "Example Security", "cik": None}
    member = _client([row]).get_sp500_constituents().members[0]

    assert member.symbol == "NEW"
    assert member.cik is None
    assert member.sector is None
    assert member.subsector is None


def test_constituent_refresh_bypasses_cache_and_saves_successful_payload(
    tmp_path: Path,
) -> None:
    cache = FmpResponseCache(tmp_path)
    path = cache.path(FMP_SP500_ENDPOINT, "SP500", period="current", limit=1)
    assert path is not None
    cache.save(path, json.dumps([{"symbol": "OLD", "name": "Cached"}]))
    seen: list[httpx.Request] = []

    result = _client(sp500_payload(), cache=cache, seen=seen).get_sp500_constituents()

    assert len(seen) == 1
    assert result.members[0].symbol == "ADBE"
    assert json.loads(path.read_text(encoding="utf-8"))[0]["symbol"] == "ADBE"


def test_rate_limit_retries_honor_retry_after_and_fail_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="Limit reached", headers={"Retry-After": "2"})

    monkeypatch.setattr("owner_lens.fmp.time.sleep", sleeps.append)
    client = FmpClient(
        KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=None,
    )
    with pytest.raises(FmpRateLimitError):
        client.get_sp500_constituents()

    assert calls == 3
    assert sleeps == [2.0, 2.0]


def test_retries_transient_server_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    responses: list[httpx.Response] = [
        httpx.Response(503, text="temporarily unavailable"),
        httpx.Response(200, json=sp500_payload()),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr("owner_lens.fmp.time.sleep", sleeps.append)
    client = FmpClient(
        KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=None,
    )
    assert len(client.get_sp500_constituents().members) == 4
    assert sleeps == [0.5]


def test_authentication_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="Invalid key")

    monkeypatch.setattr(
        "owner_lens.fmp.time.sleep",
        lambda _seconds: pytest.fail("Authentication failure should not retry"),
    )
    client = FmpClient(
        KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=None,
    )
    with pytest.raises(FmpAuthenticationError):
        client.get_sp500_constituents()
    assert calls == 1

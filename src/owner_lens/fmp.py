"""FMP (Financial Modeling Prep) annual financial-statement retrieval.

A small synchronous client for the three FMP "stable" endpoints OwnerLens needs
for annual fundamentals: income statement, balance sheet, and cash-flow
statement. It performs no financial normalization; validated statement rows are
returned unchanged so the FMP adapter can map them into canonical facts.

The API key is a secret. It is sent only as the ``apikey`` query parameter and
is redacted from every error message and recorded source URL.

Successful raw responses are cached locally (``data/raw/fmp/`` by default) so
development and reconciliation do not repeatedly consume free-tier API calls:

* cache hit: the stored raw JSON is deserialized, validated, and returned;
* cache miss: FMP is called, and only a successful, valid response is saved;
* ``refresh=True`` bypasses the cache read, calls FMP, and overwrites the entry.

Cache entries never expire; annual statements change only on refresh. A cached
entry that is unreadable or fails validation is treated as a miss and refetched
(and overwritten on success). Errors, plan restrictions, rate limits, and
malformed responses are never cached. The cache stores response bodies only, so
it never contains the API key. Callers above this module cannot tell whether
statements came from the cache or the network.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final, Self

import httpx

__all__ = [
    "DEFAULT_FMP_CACHE_DIR",
    "FMP_BASE_URL",
    "FMP_SP500_ENDPOINT",
    "FMP_STATEMENT_ENDPOINTS",
    "FmpAuthenticationError",
    "FmpClient",
    "FmpConfigurationError",
    "FmpConstituent",
    "FmpConstituents",
    "FmpError",
    "FmpPlanRestrictionError",
    "FmpRateLimitError",
    "FmpResponseCache",
    "FmpResponseError",
    "FmpStatements",
    "FmpSymbolNotFoundError",
    "FmpTransportError",
    "MalformedFmpResponseError",
]

FMP_BASE_URL: Final = "https://financialmodelingprep.com/stable"
FMP_STATEMENT_ENDPOINTS: Final = {
    "income": "income-statement",
    "balance_sheet": "balance-sheet-statement",
    "cash_flow": "cash-flow-statement",
}
DEFAULT_FMP_CACHE_DIR: Final = Path("data/raw/fmp")
_ANNUAL_PERIOD: Final = "FY"
_REQUEST_PERIOD: Final = "annual"
_CACHEABLE_SYMBOL: Final = re.compile(r"[A-Z0-9][A-Z0-9.\-]*")
_REQUEST_TIMEOUT_SECONDS: Final = 30.0
_MAX_REQUEST_ATTEMPTS: Final = 3
_MAX_RETRY_DELAY_SECONDS: Final = 30.0
_REDACTED: Final = "<redacted>"
FMP_SP500_ENDPOINT: Final = "sp500-constituent"


class FmpError(Exception):
    """Base class for every FMP configuration or retrieval failure."""


class FmpConfigurationError(FmpError, ValueError):
    """Raised when FMP is requested without a usable API key."""


class FmpTransportError(FmpError):
    """Raised when a network or timeout failure prevents an FMP request."""


class FmpResponseError(FmpError):
    """Raised when FMP returns an unsuccessful status or an API error message."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FmpAuthenticationError(FmpResponseError):
    """Raised when FMP rejects the API key (HTTP 401/403)."""


class FmpPlanRestrictionError(FmpResponseError):
    """Raised when the request exceeds the current FMP subscription (HTTP 402)."""


class FmpRateLimitError(FmpResponseError):
    """Raised when FMP reports the request or daily limit is exhausted (HTTP 429)."""


class MalformedFmpResponseError(FmpError):
    """Raised when an FMP response is not JSON with the expected statement shape."""


class FmpSymbolNotFoundError(FmpError):
    """Raised when FMP returns no annual statements for the requested symbol."""


@dataclass(frozen=True)
class FmpStatements:
    """Validated annual statements for one symbol, with retrieval context.

    ``source_urls`` record each endpoint queried, with the API key redacted.
    """

    symbol: str
    limit: int
    income: tuple[dict[str, Any], ...]
    balance_sheet: tuple[dict[str, Any], ...]
    cash_flow: tuple[dict[str, Any], ...]
    source_urls: tuple[str, ...]

    def rows(self, statement: str) -> tuple[dict[str, Any], ...]:
        """Return the rows for ``income``, ``balance_sheet``, or ``cash_flow``."""
        if statement not in FMP_STATEMENT_ENDPOINTS:
            raise KeyError(f"Unknown FMP statement: {statement!r}.")
        rows: tuple[dict[str, Any], ...] = getattr(self, statement)
        return rows


@dataclass(frozen=True)
class FmpConstituent:
    """Validated point-in-time FMP constituent identity and membership metadata."""

    symbol: str
    name: str
    cik: str | None
    sector: str | None
    subsector: str | None


@dataclass(frozen=True)
class FmpConstituents:
    """Validated constituent payload and its raw retrieval provenance."""

    members: tuple[FmpConstituent, ...]
    source_url: str
    raw_payload: bytes


class _DefaultCache:
    """Sentinel type: use the default on-disk cache."""


_DEFAULT_CACHE: Final = _DefaultCache()


class FmpResponseCache:
    """Local store of successful raw FMP response bodies, one file per request identity.

    Paths are endpoint-aware and include every parameter that changes the
    response: ``<root>/<endpoint>/<SYMBOL>.<period>.limit<N>.json``.
    """

    def __init__(self, root: str | Path = DEFAULT_FMP_CACHE_DIR) -> None:
        self.root = Path(root)

    def path(self, endpoint: str, symbol: str, *, period: str, limit: int) -> Path | None:
        """Return the cache file for a request, or ``None`` if the symbol is not path-safe."""
        if not _CACHEABLE_SYMBOL.fullmatch(symbol):
            return None
        return self.root / endpoint / f"{symbol}.{period}.limit{limit}.json"

    def load(self, path: Path) -> Any | None:
        """Return the cached JSON payload, or ``None`` when missing or unreadable."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, path: Path, body: str) -> None:
        """Atomically write a raw response body."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)


class FmpClient:
    """Synchronous FMP client for annual income, balance-sheet, and cash-flow statements.

    ``cache`` defaults to a ``FmpResponseCache`` rooted at ``data/raw/fmp``;
    pass ``cache=None`` to disable caching entirely.
    """

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
        base_url: str = FMP_BASE_URL,
        cache: FmpResponseCache | _DefaultCache | None = _DEFAULT_CACHE,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise FmpConfigurationError(
                "A non-empty FMP API key is required; set OWNER_LENS_FMP_API_KEY."
            )
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client
        self._owns_client = http_client is None
        self.cache: FmpResponseCache | None = (
            FmpResponseCache() if isinstance(cache, _DefaultCache) else cache
        )

    def __repr__(self) -> str:
        return f"FmpClient(base_url={self._base_url!r})"

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)
        return self._http_client

    def close(self) -> None:
        """Close the owned HTTP client, if this client created one."""
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, _REDACTED)

    def _source_url(self, endpoint: str, symbol: str, limit: int) -> str:
        return (
            f"{self._base_url}/{endpoint}?symbol={symbol}&period=annual"
            f"&limit={limit}&apikey={_REDACTED}"
        )

    def _get_json(self, endpoint: str, symbol: str, limit: int) -> tuple[Any, str]:
        """Call FMP and return the parsed payload with its raw body text."""
        source = self._source_url(endpoint, symbol, limit)
        payload, body, _raw = self._request_json(
            endpoint,
            {
                "symbol": symbol,
                "period": _REQUEST_PERIOD,
                "limit": limit,
                "apikey": self._api_key,
            },
            source=source,
            description=f"{endpoint} for {symbol}",
        )
        return payload, body

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, str | int],
        *,
        source: str,
        description: str,
    ) -> tuple[Any, str, bytes]:
        """Request JSON with bounded retries for transient transport and HTTP failures."""
        url = f"{self._base_url}/{endpoint}"
        response: httpx.Response | None = None
        last_transport_error: httpx.HTTPError | None = None
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                response = self._client().get(url, params=params)
                last_transport_error = None
            except httpx.HTTPError as exc:
                last_transport_error = exc
                if attempt + 1 < _MAX_REQUEST_ATTEMPTS:
                    time.sleep(min(0.5 * (2**attempt), _MAX_RETRY_DELAY_SECONDS))
                    continue
                break
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            if attempt + 1 < _MAX_REQUEST_ATTEMPTS:
                time.sleep(_retry_delay(response, attempt))
        if response is None or last_transport_error is not None:
            detail = self._redact(str(last_transport_error))
            raise FmpTransportError(
                self._redact(f"Failed to reach FMP at {source}: {detail}")
            ) from None
        detail = self._redact(response.text.strip())[:300]
        status = response.status_code
        if status == httpx.codes.PAYMENT_REQUIRED:
            raise FmpPlanRestrictionError(
                f"FMP {description} is not available on the current "
                f"subscription (HTTP 402): {detail}",
                status_code=status,
            )
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise FmpAuthenticationError(
                f"FMP rejected the API key for {description} (HTTP {status}): {detail}",
                status_code=status,
            )
        if status == httpx.codes.TOO_MANY_REQUESTS:
            raise FmpRateLimitError(
                f"FMP rate limit reached for {description} (HTTP 429): {detail}",
                status_code=status,
            )
        if status != httpx.codes.OK:
            raise FmpResponseError(
                f"FMP {description} returned HTTP {status}: {detail}",
                status_code=status,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MalformedFmpResponseError(
                f"FMP {description} did not return valid JSON: {exc}"
            ) from None
        if isinstance(payload, dict) and "Error Message" in payload:
            raise FmpResponseError(
                self._redact(f"FMP {endpoint} error: {payload['Error Message']}"),
                status_code=status,
            )
        return payload, response.text, response.content

    def get_sp500_constituents(self, *, refresh: bool = True) -> FmpConstituents:
        """Retrieve the current S&P 500 constituents from FMP's stable endpoint.

        A normal refresh always requests the latest provider membership. Passing
        ``refresh=False`` opts into the local response cache.
        """
        endpoint = FMP_SP500_ENDPOINT
        path = (
            self.cache.path(endpoint, "SP500", period="current", limit=1)
            if self.cache is not None
            else None
        )
        if path is not None and self.cache is not None and not refresh:
            cached = self.cache.load(path)
            if cached is not None:
                try:
                    members = _validate_constituents(cached)
                    return FmpConstituents(
                        members=members,
                        source_url=f"{self._base_url}/{endpoint}",
                        raw_payload=path.read_bytes(),
                    )
                except (OSError, MalformedFmpResponseError):
                    pass

        source_url = f"{self._base_url}/{endpoint}"
        payload, body, raw_payload = self._request_json(
            endpoint,
            {"apikey": self._api_key},
            source=source_url,
            description="S&P 500 constituents",
        )
        members = _validate_constituents(payload)
        if path is not None and self.cache is not None:
            self.cache.save(path, body)
        return FmpConstituents(
            members=members, source_url=source_url, raw_payload=raw_payload
        )

    def get_annual_statement(
        self, statement: str, symbol: str, *, limit: int = 5, refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        """Retrieve and validate one annual statement, using the local cache first.

        ``refresh=True`` skips the cache read and overwrites the entry on success.
        """
        if statement not in FMP_STATEMENT_ENDPOINTS:
            raise KeyError(f"Unknown FMP statement: {statement!r}.")
        normalized = _normalize_symbol(symbol)
        _validate_limit(limit)
        endpoint = FMP_STATEMENT_ENDPOINTS[statement]
        path = (
            self.cache.path(endpoint, normalized, period=_REQUEST_PERIOD, limit=limit)
            if self.cache is not None
            else None
        )
        if path is not None and self.cache is not None and not refresh:
            cached = self.cache.load(path)
            if cached is not None:
                try:
                    return _validate_rows(cached, endpoint, normalized)
                except (MalformedFmpResponseError, FmpSymbolNotFoundError):
                    pass  # invalid cache entry: refetch and overwrite
        payload, body = self._get_json(endpoint, normalized, limit)
        rows = _validate_rows(payload, endpoint, normalized)
        if path is not None and self.cache is not None:
            self.cache.save(path, body)
        return rows

    def get_income_statement(
        self, symbol: str, *, limit: int = 5, refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        """Retrieve the annual income statement for a symbol."""
        return self.get_annual_statement("income", symbol, limit=limit, refresh=refresh)

    def get_balance_sheet_statement(
        self, symbol: str, *, limit: int = 5, refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        """Retrieve the annual balance-sheet statement for a symbol."""
        return self.get_annual_statement("balance_sheet", symbol, limit=limit, refresh=refresh)

    def get_cash_flow_statement(
        self, symbol: str, *, limit: int = 5, refresh: bool = False
    ) -> tuple[dict[str, Any], ...]:
        """Retrieve the annual cash-flow statement for a symbol."""
        return self.get_annual_statement("cash_flow", symbol, limit=limit, refresh=refresh)

    def retrieve_annual_statements(
        self, symbol: str, *, limit: int = 5, refresh: bool = False
    ) -> FmpStatements:
        """Retrieve all three annual statements for a symbol as one result.

        ``limit`` is the number of most recent fiscal years requested per
        statement; the FMP free tier accepts at most 5. Each statement is served
        from the local cache when present unless ``refresh=True``.
        """
        normalized = _normalize_symbol(symbol)
        _validate_limit(limit)
        rows = {
            name: self.get_annual_statement(name, normalized, limit=limit, refresh=refresh)
            for name in FMP_STATEMENT_ENDPOINTS
        }
        return FmpStatements(
            symbol=normalized,
            limit=limit,
            income=rows["income"],
            balance_sheet=rows["balance_sheet"],
            cash_flow=rows["cash_flow"],
            source_urls=tuple(
                self._source_url(endpoint, normalized, limit)
                for endpoint in FMP_STATEMENT_ENDPOINTS.values()
            ),
        )


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("A non-empty ticker symbol is required for FMP retrieval.")
    return normalized


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"FMP limit must be a positive integer, got {limit!r}.")


def _validate_rows(payload: Any, endpoint: str, symbol: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(payload, list):
        raise MalformedFmpResponseError(f"FMP {endpoint} for {symbol} is not a JSON list.")
    if not payload:
        raise FmpSymbolNotFoundError(f"FMP returned no annual {endpoint} rows for {symbol}.")
    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise MalformedFmpResponseError(f"FMP {endpoint} row is not a JSON object.")
        row_symbol = row.get("symbol")
        if not isinstance(row_symbol, str) or row_symbol.strip().upper() != symbol:
            raise MalformedFmpResponseError(
                f"FMP {endpoint} row identifies {row_symbol!r}, not {symbol}."
            )
        if row.get("period") != _ANNUAL_PERIOD:
            raise MalformedFmpResponseError(
                f"FMP {endpoint} row for {symbol} has period {row.get('period')!r}, "
                "not an annual FY period."
            )
        try:
            date.fromisoformat(str(row.get("date")))
        except ValueError:
            raise MalformedFmpResponseError(
                f"FMP {endpoint} row for {symbol} has an invalid date {row.get('date')!r}."
            ) from None
        rows.append(row)
    return tuple(rows)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_time = parsedate_to_datetime(retry_after)
                if retry_time.tzinfo is None:
                    retry_time = retry_time.replace(tzinfo=UTC)
                delay = (retry_time - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 0.5 * (2**attempt)
    else:
        delay = 0.5 * (2**attempt)
    return min(max(delay, 0.0), _MAX_RETRY_DELAY_SECONDS)


def _validate_constituents(payload: Any) -> tuple[FmpConstituent, ...]:
    if not isinstance(payload, list) or not payload:
        raise MalformedFmpResponseError(
            "FMP S&P 500 constituents must be a non-empty JSON list."
        )
    members: list[FmpConstituent] = []
    seen_symbols: set[str] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise MalformedFmpResponseError(
                f"FMP S&P 500 constituent at index {index} is not a JSON object."
            )
        symbol_value = row.get("symbol")
        if not isinstance(symbol_value, str):
            raise MalformedFmpResponseError(
                f"FMP S&P 500 constituent at index {index} has no valid symbol."
            )
        symbol = symbol_value.strip().upper()
        if not _CACHEABLE_SYMBOL.fullmatch(symbol):
            raise MalformedFmpResponseError(
                f"FMP S&P 500 constituent at index {index} has invalid symbol "
                f"{symbol_value!r}."
            )
        if symbol in seen_symbols:
            raise MalformedFmpResponseError(
                f"FMP S&P 500 response contains duplicate symbol {symbol}."
            )
        seen_symbols.add(symbol)

        name_value = row.get("name")
        if not isinstance(name_value, str) or not name_value.strip():
            raise MalformedFmpResponseError(
                f"FMP S&P 500 constituent {symbol} has no valid name."
            )

        cik_value = row.get("cik")
        cik: str | None = None
        if cik_value is not None:
            if isinstance(cik_value, bool) or not isinstance(cik_value, (int, str)):
                raise MalformedFmpResponseError(
                    f"FMP S&P 500 constituent {symbol} has an invalid CIK."
                )
            cik_digits = str(cik_value).strip()
            if not cik_digits.isdigit() or len(cik_digits) > 10:
                raise MalformedFmpResponseError(
                    f"FMP S&P 500 constituent {symbol} has an invalid CIK."
                )
            cik = cik_digits.zfill(10)

        sector = _optional_text(row.get("sector"), "sector", symbol)
        subsector_value = row.get("subSector", row.get("subsector"))
        subsector = _optional_text(subsector_value, "subsector", symbol)
        members.append(
            FmpConstituent(
                symbol=symbol,
                name=name_value.strip(),
                cik=cik,
                sector=sector,
                subsector=subsector,
            )
        )
    return tuple(members)


def _optional_text(value: Any, field: str, symbol: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedFmpResponseError(
            f"FMP S&P 500 constituent {symbol} has an invalid {field}."
        )
    return value.strip() or None

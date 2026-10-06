"""FMP (Financial Modeling Prep) annual financial-statement retrieval.

A small synchronous client for the three FMP "stable" endpoints OwnerLens needs
for annual fundamentals: income statement, balance sheet, and cash-flow
statement. It performs no financial normalization; validated statement rows are
returned unchanged so the FMP adapter can map them into canonical facts.

The API key is a secret. It is sent only as the ``apikey`` query parameter and
is redacted from every error message and recorded source URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Self

import httpx

__all__ = [
    "FMP_BASE_URL",
    "FMP_STATEMENT_ENDPOINTS",
    "FmpAuthenticationError",
    "FmpClient",
    "FmpConfigurationError",
    "FmpError",
    "FmpPlanRestrictionError",
    "FmpRateLimitError",
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
_ANNUAL_PERIOD: Final = "FY"
_REQUEST_TIMEOUT_SECONDS: Final = 30.0
_REDACTED: Final = "<redacted>"


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


class FmpClient:
    """Synchronous FMP client for annual income, balance-sheet, and cash-flow statements."""

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
        base_url: str = FMP_BASE_URL,
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

    def _get_json(self, endpoint: str, symbol: str, limit: int) -> Any:
        url = f"{self._base_url}/{endpoint}"
        params: dict[str, str | int] = {
            "symbol": symbol,
            "period": "annual",
            "limit": limit,
            "apikey": self._api_key,
        }
        source = self._source_url(endpoint, symbol, limit)
        try:
            response = self._client().get(url, params=params)
        except httpx.HTTPError as exc:
            raise FmpTransportError(
                self._redact(f"Failed to reach FMP at {source}: {exc}")
            ) from None
        detail = self._redact(response.text.strip())[:300]
        status = response.status_code
        if status == httpx.codes.PAYMENT_REQUIRED:
            raise FmpPlanRestrictionError(
                f"FMP {endpoint} for {symbol} is not available on the current "
                f"subscription (HTTP 402): {detail}",
                status_code=status,
            )
        if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise FmpAuthenticationError(
                f"FMP rejected the API key for {endpoint} (HTTP {status}): {detail}",
                status_code=status,
            )
        if status == httpx.codes.TOO_MANY_REQUESTS:
            raise FmpRateLimitError(
                f"FMP rate limit reached for {endpoint} (HTTP 429): {detail}",
                status_code=status,
            )
        if status != httpx.codes.OK:
            raise FmpResponseError(
                f"FMP {endpoint} for {symbol} returned HTTP {status}: {detail}",
                status_code=status,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MalformedFmpResponseError(
                f"FMP {endpoint} for {symbol} did not return valid JSON: {exc}"
            ) from None
        if isinstance(payload, dict) and "Error Message" in payload:
            raise FmpResponseError(
                self._redact(f"FMP {endpoint} error: {payload['Error Message']}"),
                status_code=status,
            )
        return payload

    def get_annual_statement(
        self, statement: str, symbol: str, *, limit: int = 5
    ) -> tuple[dict[str, Any], ...]:
        """Retrieve and validate one annual statement for a symbol."""
        if statement not in FMP_STATEMENT_ENDPOINTS:
            raise KeyError(f"Unknown FMP statement: {statement!r}.")
        normalized = _normalize_symbol(symbol)
        _validate_limit(limit)
        endpoint = FMP_STATEMENT_ENDPOINTS[statement]
        payload = self._get_json(endpoint, normalized, limit)
        return _validate_rows(payload, endpoint, normalized)

    def retrieve_annual_statements(self, symbol: str, *, limit: int = 5) -> FmpStatements:
        """Retrieve all three annual statements for a symbol as one result.

        ``limit`` is the number of most recent fiscal years requested per
        statement; the FMP free tier accepts at most 5.
        """
        normalized = _normalize_symbol(symbol)
        _validate_limit(limit)
        rows = {
            name: self.get_annual_statement(name, normalized, limit=limit)
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

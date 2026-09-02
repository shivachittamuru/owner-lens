"""SEC company identity resolution and raw Company Facts retrieval.

This module resolves any ticker present in the SEC company ticker mapping to
its SEC identity and retrieves the raw Company Facts JSON. It performs no
financial normalization. The parsed Company Facts payload is returned unchanged
so callers inspect source truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Self

import httpx

COMPANY_TICKERS_URL: Final = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL_TEMPLATE: Final = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
_CIK_DIGITS: Final = 10
_REQUEST_TIMEOUT_SECONDS: Final = 30.0


class SecError(Exception):
    """Base class for every SEC retrieval failure in this feature."""


class MalformedTickerError(SecError):
    """Raised when the requested ticker is empty or whitespace only."""


class CompanyResolutionError(SecError):
    """Raised when the SEC mapping cannot yield one usable company identity."""


class SecTransportError(SecError):
    """Raised when a network or timeout failure prevents an SEC request."""


class SecResponseError(SecError):
    """Raised when an SEC source returns an unsuccessful HTTP status."""


class MalformedSecResponseError(SecError):
    """Raised when an SEC response is not valid JSON with the required shape."""


class CompanyIdentityMismatchError(SecError):
    """Raised when Company Facts identify a different company than resolved."""


@dataclass(frozen=True)
class CompanyIdentity:
    """Company identity resolved from the SEC company ticker mapping."""

    ticker: str
    company_name: str
    cik: str


@dataclass(frozen=True)
class CompanyFactsResult:
    """Atomic successful result pairing identity with unchanged raw facts."""

    identity: CompanyIdentity
    raw_facts: dict[str, Any]


def _canonical_cik(value: Any) -> int:
    """Return the positive numeric CIK for a mapping or payload value.

    Booleans are rejected even though Python treats them as integers.
    """
    if isinstance(value, bool):
        raise TypeError("CIK must not be a boolean")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError(f"CIK is not a positive integer: {value!r}")
        number = int(text)
    else:
        raise TypeError(f"CIK has an unsupported type: {type(value).__name__}")
    if number <= 0:
        raise ValueError("CIK must be a positive integer")
    if len(str(number)) > _CIK_DIGITS:
        raise ValueError("CIK exceeds ten digits")
    return number


def _format_cik(number: int) -> str:
    """Return the ten-digit, zero-padded CIK string used by SEC routes."""
    return str(number).zfill(_CIK_DIGITS)


class SecClient:
    """Synchronous SEC client for company identity and raw Company Facts."""

    def __init__(
        self,
        user_agent: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        declared = user_agent.strip()
        if not declared:
            raise ValueError(
                "A non-empty SEC User-Agent identifying the application and "
                "an administrative contact is required."
            )
        self._user_agent = declared
        self._http_client = http_client
        self._owns_client = http_client is None

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

    def _get_json(self, url: str) -> Any:
        headers = {
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            response = self._client().get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise SecTransportError(
                f"Failed to reach SEC source at {url}: {exc}"
            ) from exc
        if response.status_code != httpx.codes.OK:
            raise SecResponseError(
                f"SEC source at {url} returned status {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MalformedSecResponseError(
                f"SEC source at {url} did not return valid JSON: {exc}"
            ) from exc

    def resolve_company(self, ticker: str) -> CompanyIdentity:
        """Resolve a ticker to its SEC identity via the company mapping."""
        normalized = ticker.strip().upper()
        if not normalized:
            raise MalformedTickerError(
                "A non-empty ticker is required to resolve a company identity."
            )
        mapping = self._get_json(COMPANY_TICKERS_URL)
        return _resolve_identity_from_mapping(mapping, normalized)

    def get_company_facts(self, identity: CompanyIdentity) -> dict[str, Any]:
        """Retrieve and validate the raw Company Facts for an identity."""
        url = COMPANY_FACTS_URL_TEMPLATE.format(cik=identity.cik)
        payload = self._get_json(url)
        return _validate_company_facts(payload, identity)

    def retrieve_company_facts(self, ticker: str) -> CompanyFactsResult:
        """Resolve identity, then retrieve raw facts, as one atomic result."""
        identity = self.resolve_company(ticker)
        raw_facts = self.get_company_facts(identity)
        return CompanyFactsResult(identity=identity, raw_facts=raw_facts)


def _resolve_identity_from_mapping(
    mapping: Any,
    normalized_ticker: str,
) -> CompanyIdentity:
    if not isinstance(mapping, dict):
        raise MalformedSecResponseError(
            "SEC company mapping is not a JSON object."
        )
    matches: list[CompanyIdentity] = []
    for entry in mapping.values():
        if not isinstance(entry, dict):
            continue
        entry_ticker = entry.get("ticker")
        if not isinstance(entry_ticker, str):
            continue
        if entry_ticker.strip().upper() != normalized_ticker:
            continue
        matches.append(_identity_from_entry(entry, normalized_ticker))
    if not matches:
        raise CompanyResolutionError(
            f"SEC company mapping has no entry for {normalized_ticker}."
        )
    if len(matches) > 1:
        raise CompanyResolutionError(
            f"SEC company mapping has ambiguous entries for {normalized_ticker}."
        )
    return matches[0]


def _identity_from_entry(
    entry: dict[str, Any],
    normalized_ticker: str,
) -> CompanyIdentity:
    title = entry.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CompanyResolutionError(
            f"SEC mapping entry for {normalized_ticker} has no company name."
        )
    try:
        cik_number = _canonical_cik(entry.get("cik_str"))
    except (TypeError, ValueError) as exc:
        raise CompanyResolutionError(
            f"SEC mapping entry for {normalized_ticker} has an invalid CIK: {exc}"
        ) from exc
    return CompanyIdentity(
        ticker=normalized_ticker,
        company_name=title,
        cik=_format_cik(cik_number),
    )


def _validate_company_facts(
    payload: Any,
    identity: CompanyIdentity,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MalformedSecResponseError(
            "SEC Company Facts payload is not a JSON object."
        )
    entity_name = payload.get("entityName")
    if not isinstance(entity_name, str) or not entity_name.strip():
        raise MalformedSecResponseError(
            "SEC Company Facts payload has no entityName."
        )
    if not isinstance(payload.get("facts"), dict):
        raise MalformedSecResponseError(
            "SEC Company Facts payload has no facts object."
        )
    try:
        payload_cik = _canonical_cik(payload.get("cik"))
    except (TypeError, ValueError) as exc:
        raise MalformedSecResponseError(
            f"SEC Company Facts payload has an invalid CIK: {exc}"
        ) from exc
    if payload_cik != _canonical_cik(identity.cik):
        raise CompanyIdentityMismatchError(
            f"Company Facts CIK {_format_cik(payload_cik)} does not match "
            f"resolved CIK {identity.cik}."
        )
    return payload

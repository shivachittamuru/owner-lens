"""OwnerLens package.

Exposes the SEC identity and raw Company Facts retrieval slice and a minimal
console entry point used to validate it.
"""

from __future__ import annotations

import os
import sys

from owner_lens.revenue import (
    AmbiguousRevenueError,
    AnnualRevenueObservation,
    AnnualRevenueSeries,
    MalformedFactsError,
    RevenueConceptNotFoundError,
    RevenueNormalizationError,
    normalize_annual_revenue,
)
from owner_lens.sec import (
    CompanyFactsResult,
    CompanyIdentity,
    CompanyIdentityMismatchError,
    CompanyResolutionError,
    MalformedSecResponseError,
    SecClient,
    SecError,
    SecResponseError,
    SecTransportError,
    UnsupportedTickerError,
)

__all__ = [
    "AmbiguousRevenueError",
    "AnnualRevenueObservation",
    "AnnualRevenueSeries",
    "CompanyFactsResult",
    "CompanyIdentity",
    "CompanyIdentityMismatchError",
    "CompanyResolutionError",
    "MalformedFactsError",
    "MalformedSecResponseError",
    "RevenueConceptNotFoundError",
    "RevenueNormalizationError",
    "SecClient",
    "SecError",
    "SecResponseError",
    "SecTransportError",
    "UnsupportedTickerError",
    "main",
    "normalize_annual_revenue",
]

_USER_AGENT_ENV_VAR = "OWNER_LENS_SEC_USER_AGENT"


def main() -> None:
    """Validate the slice by retrieving raw Company Facts for one ticker."""
    args = sys.argv[1:]
    if len(args) != 1:
        print("Usage: owner-lens <TICKER>", file=sys.stderr)
        raise SystemExit(2)
    ticker = args[0]

    user_agent = os.environ.get(_USER_AGENT_ENV_VAR, "").strip()
    if not user_agent:
        print(
            f"Set {_USER_AGENT_ENV_VAR} to an SEC User-Agent identifying the "
            "application and an administrative contact, for example "
            "'OwnerLens admin@example.com'.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        with SecClient(user_agent) as client:
            result = client.retrieve_company_facts(ticker)
    except SecError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    identity = result.identity
    raw = result.raw_facts
    print(f"ticker: {identity.ticker}")
    print(f"company: {identity.company_name}")
    print(f"CIK: {identity.cik}")
    print()
    print("top-level keys:")
    print(list(raw.keys()))
    print()

    facts = raw.get("facts", {})
    print("facts namespaces:")
    print(sorted(facts.keys()))
    print()

    us_gaap = facts.get("us-gaap", {})
    print("sample us-gaap concepts:")
    print(sorted(us_gaap.keys())[:10])
    print()
    print("-" * 30)


# $env:OWNER_LENS_SEC_USER_AGENT = "OwnerLens admin@example.com"
# uv run owner-lens ADBE
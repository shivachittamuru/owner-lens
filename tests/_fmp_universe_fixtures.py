"""Fixture-only FMP constituent payloads for Feature 8A1 tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def sp500_payload(*, sector_suffix: str = "") -> list[dict[str, Any]]:
    return deepcopy(
        [
            {
                "symbol": "ADBE",
                "name": "Adobe Inc.",
                "cik": "0000796343",
                "sector": f"Technology{sector_suffix}",
                "subSector": "Application Software",
            },
            {
                "symbol": "GOOG",
                "name": "Alphabet Inc. Class C",
                "cik": "0001652044",
                "sector": "Communication Services",
                "subSector": "Interactive Media",
            },
            {
                "symbol": "GOOGL",
                "name": "Alphabet Inc. Class A",
                "cik": "0001652044",
                "sector": "Communication Services",
                "subSector": "Interactive Media",
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft Corporation",
                "cik": "0000789019",
                "sector": "Technology",
                "subSector": "Systems Software",
            },
        ]
    )

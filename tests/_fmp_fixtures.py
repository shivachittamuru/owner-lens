"""Mocked FMP annual-statement fixtures for Slice 5B tests.

Values mirror the ADBE SEC fixture in ``_fixtures.py`` (fiscal years 2023-2025,
millions scaled to whole dollars) but in FMP's shape: one row per fiscal year
per statement, provider field names, and FMP sign conventions (cash outflows
negative, unreported line items zero).
"""

from __future__ import annotations

import copy
from typing import Any

from owner_lens.fmp import FmpStatements

_MILL = 1_000_000
YEARS = (2025, 2024, 2023)

_INCOME = {
    "revenue": {2023: 19409, 2024: 21505, 2025: 23769},
    "operatingIncome": {2023: 6650, 2024: 6741, 2025: 8706},
    "netIncome": {2023: 5428, 2024: 5560, 2025: 7130},
    "incomeTaxExpense": {2023: 1371, 2024: 1371, 2025: 1604},
    "incomeBeforeTax": {2023: 6799, 2024: 6931, 2025: 8734},
    # Precomputed FMP values OwnerLens must ignore.
    "ebitda": {2023: 1, 2024: 1, 2025: 1},
}
_SHARES = {2023: 459100000, 2024: 449700000, 2025: 427000000}
_CASH_FLOW = {
    "netCashProvidedByOperatingActivities": {2023: 7302, 2024: 8056, 2025: 10031},
    "operatingCashFlow": {2023: 7302, 2024: 8056, 2025: 10031},
    "capitalExpenditure": {2023: -360, 2024: -183, 2025: -179},
    "investmentsInPropertyPlantAndEquipment": {2023: -360, 2024: -183, 2025: -179},
    "commonStockRepurchased": {2023: -4400, 2024: -9500, 2025: -11281},
    "stockBasedCompensation": {2023: 1718, 2024: 1833, 2025: 1942},
    "commonDividendsPaid": {2023: 0, 2024: 0, 2025: 0},
    "freeCashFlow": {2023: 1, 2024: 1, 2025: 1},
}
_BALANCE = {
    "cashAndCashEquivalents": {2023: 7141, 2024: 7613, 2025: 5431},
    "shortTermInvestments": {2023: 701, 2024: 273, 2025: 1164},
    "shortTermDebt": {2023: 0, 2024: 1499, 2025: 0},
    "longTermDebt": {2023: 3634, 2024: 4129, 2025: 6210},
    "totalAssets": {2023: 29779, 2024: 30230, 2025: 29496},
    "totalStockholdersEquity": {2023: 16518, 2024: 14105, 2025: 11623},
}


def _row(symbol: str, year: int, fields: dict[str, dict[int, int]]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": f"{year}-11-30",
        "symbol": symbol,
        "reportedCurrency": "USD",
        "cik": "0000796343",
        "filingDate": f"{year + 1}-01-15",
        "acceptedDate": f"{year + 1}-01-15 17:01:55",
        "fiscalYear": str(year),
        "period": "FY",
    }
    for name, values in fields.items():
        row[name] = values[year] * _MILL
    return row


def fmp_payloads(symbol: str = "ADBE") -> dict[str, list[dict[str, Any]]]:
    """Raw JSON lists keyed by FMP endpoint name, newest year first."""
    income = [_row(symbol, y, _INCOME) for y in YEARS]
    for row in income:
        row["weightedAverageShsOutDil"] = _SHARES[int(row["fiscalYear"])]
    return {
        "income-statement": income,
        "balance-sheet-statement": [_row(symbol, y, _BALANCE) for y in YEARS],
        "cash-flow-statement": [_row(symbol, y, _CASH_FLOW) for y in YEARS],
    }


def fmp_statements(
    symbol: str = "ADBE",
    payloads: dict[str, list[dict[str, Any]]] | None = None,
) -> FmpStatements:
    """Validated-statement object as the client would return it."""
    data = copy.deepcopy(payloads) if payloads is not None else fmp_payloads(symbol)
    return FmpStatements(
        symbol=symbol,
        limit=5,
        income=tuple(data["income-statement"]),
        balance_sheet=tuple(data["balance-sheet-statement"]),
        cash_flow=tuple(data["cash-flow-statement"]),
        source_urls=(),
    )


def with_field(
    endpoint: str, field: str, values: dict[int, Any] | None
) -> dict[str, list[dict[str, Any]]]:
    """Payloads with one field replaced per year, or removed when ``values`` is None."""
    data = fmp_payloads()
    for row in data[endpoint]:
        year = int(row["fiscalYear"])
        if values is None:
            row.pop(field, None)
        elif year in values:
            row[field] = values[year]
    return data

"""Shared controlled multi-company Company Facts fixtures for Slice 3B tests.

Values mirror the live SEC concepts recorded in
specs/011-generalize-metric-normalization/research.md for fiscal years
2023-2025. Dollar amounts are expressed in millions and scaled to whole dollars;
diluted share counts are absolute. Each company uses a period calendar that lands
inside the 52/53-week full-year window so the shared selectors accept it.

Deliberate gaps encode the canonical coverage policy:

* Visa reports no ``ShortTermInvestments`` concept (absent by policy).
* Visa reports no weighted-average diluted-share concept (unsupported).
* Adobe reports no dividend concept (structurally absent).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

from owner_lens.sec import CompanyFactsResult, CompanyIdentity

_MILL = 1_000_000


def _duration_entries(
    concept: str,
    values: dict[int, int],
    *,
    start_md: str,
    end_md: str,
) -> list[dict[str, Any]]:
    return [
        {
            "start": f"{year - 1}-{start_md}",
            "end": f"{year}-{end_md}",
            "val": val,
            "fy": year,
            "fp": "FY",
            "form": "10-K",
            "filed": f"{year + 1}-01-15",
            "accn": f"{concept}-{year}",
        }
        for year, val in values.items()
    ]


def _instant_entries(
    concept: str,
    values: dict[int, int],
    *,
    end_md: str,
) -> list[dict[str, Any]]:
    return [
        {
            "end": f"{year}-{end_md}",
            "val": val,
            "fy": year,
            "fp": "FY",
            "form": "10-K",
            "filed": f"{year + 1}-01-15",
            "accn": f"{concept}-{year}",
        }
        for year, val in values.items()
    ]


def _build_facts(
    *,
    cik: int,
    name: str,
    start_md: str,
    end_md: str,
    duration: dict[str, tuple[str, dict[int, int]]],
    instant: dict[str, tuple[str, dict[int, int]]],
) -> dict[str, Any]:
    us_gaap: dict[str, Any] = {}
    for concept, (unit, values) in duration.items():
        us_gaap[concept] = {
            "units": {unit: _duration_entries(concept, values, start_md=start_md, end_md=end_md)}
        }
    for concept, (unit, values) in instant.items():
        us_gaap[concept] = {"units": {unit: _instant_entries(concept, values, end_md=end_md)}}
    return {"cik": cik, "entityName": name, "facts": {"us-gaap": us_gaap}}


def _usd(values_millions: dict[int, int]) -> tuple[str, dict[int, int]]:
    return "USD", {year: val * _MILL for year, val in values_millions.items()}


def _shares(values: dict[int, int]) -> tuple[str, dict[int, int]]:
    return "shares", values


def adbe_facts() -> dict[str, Any]:
    """Adobe: default concepts throughout; no dividend program."""
    return _build_facts(
        cik=796343,
        name="ADOBE INC.",
        start_md="12-01",
        end_md="11-30",
        duration={
            "Revenues": _usd({2023: 19409, 2024: 21505, 2025: 23769}),
            "OperatingIncomeLoss": _usd({2023: 6650, 2024: 6741, 2025: 8706}),
            "NetIncomeLoss": _usd({2023: 5428, 2024: 5560, 2025: 7130}),
            "NetCashProvidedByUsedInOperatingActivities": _usd(
                {2023: 7302, 2024: 8056, 2025: 10031}
            ),
            "PaymentsToAcquirePropertyPlantAndEquipment": _usd(
                {2023: 360, 2024: 183, 2025: 179}
            ),
            "WeightedAverageNumberOfDilutedSharesOutstanding": _shares(
                {2023: 459100000, 2024: 449700000, 2025: 427000000}
            ),
            "IncomeTaxExpenseBenefit": _usd({2023: 1371, 2024: 1371, 2025: 1604}),
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": _usd(
                {2023: 6799, 2024: 6931, 2025: 8734}
            ),
            "PaymentsForRepurchaseOfCommonStock": _usd(
                {2023: 4400, 2024: 9500, 2025: 11281}
            ),
            "ShareBasedCompensation": _usd({2023: 1718, 2024: 1833, 2025: 1942}),
        },
        instant={
            "CashAndCashEquivalentsAtCarryingValue": _usd(
                {2023: 7141, 2024: 7613, 2025: 5431}
            ),
            "ShortTermInvestments": _usd({2023: 701, 2024: 273, 2025: 1164}),
            "DebtCurrent": _usd({2023: 0, 2024: 1499, 2025: 0}),
            "LongTermDebt": _usd({2023: 3634, 2024: 4129, 2025: 6210}),
            "Assets": _usd({2023: 29779, 2024: 30230, 2025: 29496}),
            "StockholdersEquity": _usd({2023: 16518, 2024: 14105, 2025: 11623}),
        },
    )


def visa_facts() -> dict[str, Any]:
    """Visa: revenue via the contract concept, CapEx via productive-assets, debt via
    the current/noncurrent split, equity including noncontrolling interest, and no
    short-term-investments or diluted-share concept.
    """
    return _build_facts(
        cik=1403161,
        name="VISA INC.",
        start_md="10-01",
        end_md="09-30",
        duration={
            "RevenueFromContractWithCustomerExcludingAssessedTax": _usd(
                {2023: 32653, 2024: 35926, 2025: 40000}
            ),
            "OperatingIncomeLoss": _usd({2023: 21000, 2024: 23595, 2025: 23994}),
            "NetIncomeLoss": _usd({2023: 17273, 2024: 19743, 2025: 20058}),
            "NetCashProvidedByUsedInOperatingActivities": _usd(
                {2023: 20755, 2024: 19950, 2025: 23059}
            ),
            "PaymentsToAcquireProductiveAssets": _usd(
                {2023: 1059, 2024: 1257, 2025: 1482}
            ),
            "IncomeTaxExpenseBenefit": _usd({2023: 3764, 2024: 4173, 2025: 4136}),
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": _usd(
                {2023: 21037, 2024: 23916, 2025: 24194}
            ),
            "PaymentsForRepurchaseOfCommonStock": _usd(
                {2023: 12101, 2024: 16713, 2025: 18316}
            ),
            "ShareBasedCompensation": _usd({2023: 765, 2024: 850, 2025: 897}),
            "PaymentsOfDividends": _usd({2023: 3751, 2024: 4217, 2025: 4634}),
        },
        instant={
            "CashAndCashEquivalentsAtCarryingValue": _usd(
                {2023: 16286, 2024: 11975, 2025: 17164}
            ),
            "LongTermDebtCurrent": _usd({2023: 0, 2024: 0, 2025: 5569}),
            "LongTermDebtNoncurrent": _usd({2023: 20463, 2024: 20836, 2025: 19602}),
            "Assets": _usd({2023: 90499, 2024: 94511, 2025: 99627}),
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": _usd(
                {2023: 38733, 2024: 39137, 2025: 37909}
            ),
        },
    )


def costco_facts() -> dict[str, Any]:
    """Costco: contract revenue, PPE CapEx, debt via the current/noncurrent split,
    plain equity, and its own diluted-share and dividend concepts.
    """
    return _build_facts(
        cik=909832,
        name="COSTCO WHOLESALE CORP /NEW",
        start_md="09-02",
        end_md="09-01",
        duration={
            "RevenueFromContractWithCustomerExcludingAssessedTax": _usd(
                {2023: 242290, 2024: 254453, 2025: 275235}
            ),
            "OperatingIncomeLoss": _usd({2023: 8114, 2024: 9285, 2025: 10383}),
            "NetIncomeLoss": _usd({2023: 6292, 2024: 7367, 2025: 8099}),
            "NetCashProvidedByUsedInOperatingActivities": _usd(
                {2023: 11068, 2024: 11339, 2025: 13335}
            ),
            "PaymentsToAcquirePropertyPlantAndEquipment": _usd(
                {2023: 4323, 2024: 4710, 2025: 5498}
            ),
            "WeightedAverageNumberOfDilutedSharesOutstanding": _shares(
                {2023: 444452000, 2024: 444759000, 2025: 444803000}
            ),
            "IncomeTaxExpenseBenefit": _usd({2023: 2195, 2024: 2373, 2025: 2719}),
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": _usd(
                {2023: 8487, 2024: 9740, 2025: 10818}
            ),
            "PaymentsForRepurchaseOfCommonStock": _usd({2023: 676, 2024: 700, 2025: 903}),
            "ShareBasedCompensation": _usd({2023: 774, 2024: 818, 2025: 860}),
            "PaymentsOfDividendsCommonStock": _usd({2023: 1251, 2024: 9041, 2025: 2183}),
        },
        instant={
            "CashAndCashEquivalentsAtCarryingValue": _usd(
                {2023: 13700, 2024: 9906, 2025: 14161}
            ),
            "ShortTermInvestments": _usd({2023: 1534, 2024: 1238, 2025: 1123}),
            "LongTermDebtCurrent": _usd({2023: 1081, 2024: 103, 2025: 75}),
            "LongTermDebtNoncurrent": _usd({2023: 5377, 2024: 5794, 2025: 5713}),
            "Assets": _usd({2023: 68994, 2024: 69831, 2025: 77099}),
            "StockholdersEquity": _usd({2023: 25058, 2024: 23622, 2025: 29164}),
        },
    )


# -- Shared offline SEC client stand-in for ingestion/CLI tests ---------------

FIXTURE_CIKS = {"ADBE": "0000796343", "V": "0001403161", "COST": "0000909832"}
FIXTURE_NAMES = {
    "ADBE": "ADOBE INC.",
    "V": "VISA INC.",
    "COST": "COSTCO WHOLESALE CORP /NEW",
}
FIXTURE_FACTS: dict[str, Callable[[], dict[str, Any]]] = {
    "ADBE": adbe_facts,
    "V": visa_facts,
    "COST": costco_facts,
}


class FakeSecClient:
    """An offline ``SecClient`` stand-in that returns fixture payloads."""

    def __init__(
        self,
        *,
        facts: dict[str, Callable[[], dict[str, Any]]] | None = None,
        resolve_error: Exception | None = None,
    ) -> None:
        self._facts = facts if facts is not None else FIXTURE_FACTS
        self._resolve_error = resolve_error

    def resolve_company(self, ticker: str) -> CompanyIdentity:
        if self._resolve_error is not None:
            raise self._resolve_error
        symbol = ticker.strip().upper()
        return CompanyIdentity(
            ticker=symbol, company_name=FIXTURE_NAMES[symbol], cik=FIXTURE_CIKS[symbol]
        )

    def get_company_facts(self, identity: CompanyIdentity) -> dict[str, Any]:
        return self._facts[identity.ticker]()

    def retrieve_company_facts(self, ticker: str) -> CompanyFactsResult:
        identity = self.resolve_company(ticker)
        return CompanyFactsResult(
            identity=identity, raw_facts=self.get_company_facts(identity)
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        pass

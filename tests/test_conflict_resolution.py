"""Slice 6C: restatement- and stock-split-aware conflict resolution. Offline, deterministic.

Mechanical conflicts (precision re-rounding, evidenced forward stock splits on
share counts) resolve with full provenance; genuine or uncertain conflicts keep
failing loudly with the unchanged ambiguity error.
"""

from __future__ import annotations

from typing import Any

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens._annual import AmbiguousValueError, classify_conflict_values
from owner_lens.canonical import ConflictResolutionKind, MetricStatus
from owner_lens.owner_economics import owner_economics_from_history
from owner_lens.persistence.adapters import _fact_record
from owner_lens.reported import normalize_diluted_shares, normalize_net_income
from owner_lens.sec_adapter import canonical_history_from_sec

P = ConflictResolutionKind.PRECISION
S = ConflictResolutionKind.STOCK_SPLIT
_SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"


def _fact(year: int, value: int, filed: str, accn: str) -> dict[str, Any]:
    return {"start": f"{year - 1}-12-01", "end": f"{year}-11-30", "val": value, "fy": year,
            "fp": "FY", "form": "10-K", "filed": filed, "accn": accn}


def _with(concept: str, entries: list[dict[str, Any]], unit: str = "USD") -> dict[str, Any]:
    facts = adbe_facts()
    facts["facts"]["us-gaap"][concept] = {"units": {unit: entries}}
    return facts


def _shares(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _with(_SHARES, entries, unit="shares")


def _by_year(series: Any) -> dict[int, Any]:
    return {o.fiscal_year: o for o in series.observations}


# --- Precision re-rounding ----------------------------------------------------------


def test_precision_rerounding_resolves_to_the_precise_original_filing() -> None:
    # NOW FY2021 net income: 230,141,000 (thousands) later restated as 230,000,000 (millions).
    facts = _with("NetIncomeLoss", [
        _fact(2023, 5_428_000_000, "2024-01-15", "a23"),
        _fact(2024, 5_560_000_000, "2025-01-15", "a24"),
        _fact(2025, 7_130_000_000, "2026-01-15", "a25"),
        _fact(2021, 230_141_000, "2022-02-03", "orig"),
        _fact(2021, 230_000_000, "2023-01-31", "re1"),
        _fact(2021, 230_000_000, "2024-01-25", "re2"),
        _fact(2022, 300_000_000, "2023-01-31", "re1"),
    ])
    fy2021 = _by_year(normalize_net_income(facts, ticker="ADBE"))[2021]
    assert (fy2021.value, fy2021.accession, fy2021.filed.isoformat()) == (230_141_000, "orig", "2022-02-03")
    resolution = fy2021.resolution
    assert resolution is not None
    assert (resolution.kind, resolution.split_factor, resolution.reported_value) == (P, 1, 230_141_000)
    assert [(s.value, s.accession) for s in resolution.superseded] == [(230_000_000, "re1"), (230_000_000, "re2")]


def test_later_more_precise_value_also_resolves() -> None:
    facts = _with("NetIncomeLoss", [_fact(2025, 7_130_000_000, "2026-01-15", "m"),
                                    _fact(2025, 7_129_812_000, "2027-01-15", "k")])
    fy2025 = _by_year(normalize_net_income(facts, ticker="ADBE"))[2025]
    assert fy2025.value == 7_129_812_000 and fy2025.accession == "k"
    assert fy2025.resolution is not None and fy2025.resolution.kind is P


def test_untouched_years_carry_no_resolution() -> None:
    history = canonical_history_from_sec(adbe_facts(), ticker="ADBE")
    assert all(f.resolution is None for s in history.series for f in s.observations)


@pytest.mark.parametrize(
    ("values", "why"),
    [
        ((2_690_000_000, 2_677_000_000), "CRM: <1% apart but same precision, a genuine revision"),
        ((27_266_000_000, 27_045_000_000), "META capex: genuine revision"),
        ((1_784_000_000, 1_786_000_000), "PFE cash: genuine revision"),
        ((1_234_567_890, 1_230_000_000), "differs beyond millions re-rounding"),
        ((1_234_567, 1_234_570), "re-rounding to tens is not a SEC reporting scale"),
        ((0, 400_000), "zero versus non-zero"),
    ],
)
def test_genuine_or_unknown_conflicts_still_fail(values: tuple[int, int], why: str) -> None:
    facts = _with("NetIncomeLoss", [_fact(2025, values[0], "2026-01-15", "a"),
                                    _fact(2025, values[1], "2027-01-15", "b")])
    with pytest.raises(AmbiguousValueError, match=r"Fiscal year 2025 has conflicting NetIncomeLoss values"):
        normalize_net_income(facts, ticker="ADBE")
    assert classify_conflict_values(set(values), shares=False) is None, why


def test_genuine_revision_marks_metric_invalid_in_canonical_history() -> None:
    facts = _with("NetIncomeLoss", [_fact(2025, 7_130_000_000, "2026-01-15", "a"),
                                    _fact(2025, 7_200_000_000, "2027-01-15", "b")])
    history = canonical_history_from_sec(facts, ticker="ADBE")
    assert history.series_for("net_income").status is MetricStatus.INVALID


# --- Stock splits ---------------------------------------------------------------------


def _nvda_like() -> dict[str, Any]:
    # 10:1 split between the 2024-02 and 2025-02 10-Ks; FY2022 exists only pre-split.
    return _shares([
        _fact(2022, 2_535_000_000, "2023-01-15", "k22"),
        _fact(2023, 2_507_000_000, "2024-01-15", "k23"),
        _fact(2023, 2_507_000_000, "2025-01-15", "k24"),
        _fact(2024, 2_494_000_000, "2025-01-15", "k24"),
        _fact(2023, 25_070_000_000, "2026-01-15", "k25"),
        _fact(2024, 24_940_000_000, "2026-01-15", "k25"),
        _fact(2025, 24_804_000_000, "2026-01-15", "k25"),
    ])


def test_stock_split_resolves_to_the_restated_post_split_value() -> None:
    years = _by_year(normalize_diluted_shares(_nvda_like(), ticker="NVDA"))
    fy2024 = years[2024]
    assert (fy2024.value, fy2024.accession) == (24_940_000_000, "k25")
    assert fy2024.resolution is not None
    assert (fy2024.resolution.kind, fy2024.resolution.split_factor) == (S, 1)
    assert [(s.value, s.split_factor) for s in fy2024.resolution.superseded] == [(2_494_000_000, 10)]
    assert years[2025].resolution is None


def test_pre_split_only_year_is_adjusted_to_the_post_split_basis_with_provenance() -> None:
    fy2022 = _by_year(normalize_diluted_shares(_nvda_like(), ticker="NVDA"))[2022]
    assert fy2022.value == 25_350_000_000
    assert fy2022.accession == "k22"  # the filing that reported the pre-split value
    assert fy2022.resolution is not None
    assert (fy2022.resolution.kind, fy2022.resolution.reported_value, fy2022.resolution.split_factor) == (
        S, 2_535_000_000, 10
    )


def test_split_combined_with_rerounding_resolves_amzn_pattern() -> None:
    # AMZN FY2021: 515,000,000 (millions, pre 20:1) versus 10,296,000,000 post-split.
    facts = _shares([
        _fact(2021, 515_000_000, "2022-02-04", "k21"),
        _fact(2021, 10_296_000_000, "2023-02-03", "k22"),
        _fact(2022, 10_189_000_000, "2023-02-03", "k22"),
        _fact(2025, 10_827_000_000, "2026-01-15", "k25"),
    ])
    years = _by_year(normalize_diluted_shares(facts, ticker="AMZN"))
    assert years[2021].value == 10_296_000_000
    assert years[2021].resolution is not None and years[2021].resolution.kind is S


@pytest.mark.parametrize(
    ("ratio", "pre", "post"),
    [(50, 27_710_000, 1_385_500_000), (5, 208_423_000, 1_042_113_000)],  # CMG 50:1, NOW 5:1
)
def test_cmg_and_now_split_ratios(ratio: int, pre: int, post: int) -> None:
    facts = _shares([
        _fact(2023, pre, "2024-01-15", "old"),
        _fact(2023, post, "2025-01-15", "new"),
        _fact(2022, pre - 1_000, "2023-01-15", "older"),
        _fact(2025, post, "2026-01-15", "current"),
    ])
    years = _by_year(normalize_diluted_shares(facts, ticker="CMG"))
    assert years[2023].value == post
    assert years[2022].value == (pre - 1_000) * ratio
    assert years[2022].resolution is not None and years[2022].resolution.split_factor == ratio


def test_two_splits_apply_a_cumulative_factor() -> None:
    # NVDA-like history: 4:1 then 10:1; a year reported only before both scales x40.
    facts = _shares([
        _fact(2021, 600_000_000, "2022-01-15", "k21"),
        _fact(2021, 2_400_000_000, "2023-01-15", "k22"),
        _fact(2022, 2_500_000_000, "2023-01-15", "k22"),
        _fact(2022, 25_000_000_000, "2025-01-15", "k24"),
        _fact(2020, 590_000_000, "2021-01-15", "k20"),
        _fact(2024, 24_900_000_000, "2025-01-15", "k24"),
        _fact(2025, 24_800_000_000, "2026-01-15", "k25"),
    ])
    years = _by_year(normalize_diluted_shares(facts, ticker="NVDA", max_years=6))
    assert years[2020].value == 590_000_000 * 40
    assert years[2020].resolution is not None and years[2020].resolution.split_factor == 40
    assert years[2021].value == 24_000_000_000  # restated after 4:1, then scaled x10
    assert years[2022].value == 25_000_000_000


def test_owner_economics_runs_on_the_split_adjusted_basis() -> None:
    history = canonical_history_from_sec(_nvda_like(), ticker="NVDA")
    assert history.series_for("diluted_shares").status is MetricStatus.AVAILABLE
    rows = owner_economics_from_history(history)
    shares = {row.fiscal_year: row.diluted_shares.value for row in rows if row.diluted_shares}
    assert shares[2025] == 24_804_000_000 and shares[2024] == 24_940_000_000 and shares[2023] == 25_070_000_000


@pytest.mark.parametrize(
    ("entries", "why"),
    [
        ([_fact(2025, 1_000_000_000, "2026-01-15", "a"), _fact(2025, 100_000_000, "2027-01-15", "b")],
         "reverse split (later value smaller) is not recognized"),
        ([_fact(2025, 1_000_000_000, "2027-01-15", "a"), _fact(2025, 100_000_000, "2026-01-15", "b"),
          _fact(2025, 1_000_000_000, "2025-06-01", "c")],
         "a post-split value filed before a pre-split value contradicts the timing"),
        ([_fact(2025, 100_000_000, "2026-01-15", "a"), _fact(2025, 150_000_000, "2027-01-15", "b")],
         "3:2 split (non-integer ratio) is not recognized"),
        ([_fact(2025, 100_000_000, "2026-01-15", "a"), _fact(2025, 1_007_000_000, "2027-01-15", "b")],
         "ratio near 10 but not a re-rounding of a 10:1 split"),
    ],
)
def test_unrecognized_share_conflicts_still_fail(entries: list[dict[str, Any]], why: str) -> None:
    with pytest.raises(AmbiguousValueError):
        normalize_diluted_shares(_shares(entries), ticker="ADBE")


def test_observation_filed_between_pre_and_post_reports_has_uncertain_basis() -> None:
    facts = _shares([
        _fact(2024, 100_000_000, "2025-01-15", "pre"),
        _fact(2024, 1_000_000_000, "2026-01-15", "post"),
        _fact(2023, 95_000_000, "2025-06-01", "between"),
        _fact(2025, 990_000_000, "2026-01-15", "post"),
    ])
    with pytest.raises(AmbiguousValueError, match="share basis is uncertain"):
        normalize_diluted_shares(facts, ticker="ADBE")


def test_contradictory_split_evidence_disables_split_resolution() -> None:
    # Two overlapping filing intervals imply different ratios (10:1 and 2:1).
    facts = _shares([
        _fact(2024, 100_000_000, "2025-01-15", "a"),
        _fact(2024, 1_000_000_000, "2026-01-15", "b"),
        _fact(2023, 90_000_000, "2025-01-10", "c"),
        _fact(2023, 180_000_000, "2026-01-10", "d"),
        _fact(2025, 1_100_000_000, "2026-01-15", "b"),
    ])
    with pytest.raises(AmbiguousValueError, match="conflicting"):
        normalize_diluted_shares(facts, ticker="ADBE")


def test_split_logic_never_applies_to_currency_metrics() -> None:
    facts = _with("NetIncomeLoss", [_fact(2025, 713_000_000, "2026-01-15", "a"),
                                    _fact(2025, 7_130_000_000, "2027-01-15", "b")])
    with pytest.raises(AmbiguousValueError):
        normalize_net_income(facts, ticker="ADBE")
    assert classify_conflict_values({713_000_000, 7_130_000_000}, shares=False) is None
    assert classify_conflict_values({713_000_000, 7_130_000_000}, shares=True) is S


# --- Persistence provenance -------------------------------------------------------


def test_persisted_split_adjusted_fact_states_the_adjustment() -> None:
    history = canonical_history_from_sec(_nvda_like(), ticker="NVDA")
    years = _by_year(history.series_for("diluted_shares"))
    adjusted = _fact_record("1", "diluted_shares", years[2022], "duration")
    assert adjusted.concept == f"{_SHARES} [split-adjusted x10 from reported 2535000000]"
    assert adjusted.value == 25_350_000_000 and adjusted.accession == "k22"
    restated = _fact_record("1", "diluted_shares", years[2024], "duration")
    assert restated.concept == _SHARES  # reported verbatim by its accession


# --- Golden companies -----------------------------------------------------------------


@pytest.mark.parametrize(("ticker", "build"), [("ADBE", adbe_facts), ("V", visa_facts),
                                               ("COST", costco_facts)])
def test_golden_fixtures_have_no_conflict_resolution(ticker: str, build: Any) -> None:
    history = canonical_history_from_sec(build(), ticker=ticker)
    assert all(f.resolution is None for s in history.series for f in s.observations)

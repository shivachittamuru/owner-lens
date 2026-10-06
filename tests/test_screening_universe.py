"""Tests for Feature 7 universe screening, ranking, and the CLI (Slice 7C).

The golden-company fixtures (ADBE, V, COST) exercise the end-to-end path from
SEC Company Facts through coverage-aware evidence assembly to a ranked result.
A separate characterization test pins the full 24-company outcome; it runs only
when the local SEC snapshots are present, because ``data/`` is not committed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from _fixtures import adbe_facts, costco_facts, visa_facts

from owner_lens.coverage import LayerCoverage, company_coverage_from_history
from owner_lens.screening import (
    BUCKET_ORDER,
    DIMENSION_ORDER,
    CoverageClass,
    DimensionBand,
    ScreeningBucket,
    ScreeningDimension,
    ScreeningReason,
    assemble_screening_evidence,
    format_screening_detail,
    format_screening_result,
    format_screening_table,
    screen_company_from_facts,
    screen_company_from_history,
    screen_universe,
)
from owner_lens.sec_adapter import canonical_history_from_sec

Band = DimensionBand
Bucket = ScreeningBucket

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COVERAGE_REPORT = _REPO_ROOT / "data" / "universe_6a_report.json"

# The expected outcome for the 24-company universe. These are not rules fitted
# to names: each entry must follow from the documented bands and rules, and a
# change here is a deliberate design change that belongs in the feature doc.
EXPECTED_UNIVERSE: dict[str, tuple[ScreeningBucket, CoverageClass]] = {
    "ADBE": (Bucket.HIGH_PRIORITY, CoverageClass.FULL),
    "CMG": (Bucket.HIGH_PRIORITY, CoverageClass.FULL),
    "NVDA": (Bucket.HIGH_PRIORITY, CoverageClass.FULL),
    "COST": (Bucket.HIGH_PRIORITY, CoverageClass.FULL),
    "INTU": (Bucket.HIGH_PRIORITY, CoverageClass.FULL),
    "MSFT": (Bucket.WORTH_UNDERWRITING, CoverageClass.FULL),
    "NOW": (Bucket.WORTH_UNDERWRITING, CoverageClass.PARTIAL),
    "CRM": (Bucket.WATCH, CoverageClass.FULL),
    "PG": (Bucket.WATCH, CoverageClass.PARTIAL),
    "V": (Bucket.WATCH, CoverageClass.PARTIAL),
    "LOW": (Bucket.WATCH, CoverageClass.PARTIAL),
    "AMZN": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "LULU": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "HD": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "KO": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "UNH": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "ORCL": (Bucket.LOW_PRIORITY, CoverageClass.PARTIAL),
    "CAT": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "CVX": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "DE": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "META": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "NKE": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "PFE": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
    "XOM": (Bucket.INSUFFICIENT_DATA, CoverageClass.FAILED),
}


# --- Golden companies end to end ------------------------------------------------


def test_adobe_screens_end_to_end_from_raw_company_facts() -> None:
    result = screen_company_from_facts(adbe_facts(), ticker="ADBE")

    assert result.ticker == "ADBE"
    assert result.coverage_class is CoverageClass.FULL
    assert result.evaluable_dimensions == len(DIMENSION_ORDER)
    assert result.bucket is not Bucket.INSUFFICIENT_DATA


def test_costco_is_not_penalized_for_a_structurally_low_margin() -> None:
    """Business quality must read cash generation, never the margin level."""
    result = screen_company_from_facts(costco_facts(), ticker="COST")
    owner_rows = assemble_screening_evidence(
        canonical_history_from_sec(costco_facts(), ticker="COST", max_years=5)
    ).owner_economics
    latest_margin = owner_rows[-1].operating_margin

    assert latest_margin is not None and latest_margin < 0.06
    assert result.band(ScreeningDimension.BUSINESS_QUALITY) is Band.STRONG
    assert result.band(ScreeningDimension.CAPITAL_EFFICIENCY) is Band.STRONG


def test_visa_has_no_per_share_dimension_and_is_coverage_capped() -> None:
    """Visa files no diluted-share concept, so per-share value is unseeable."""
    result = screen_company_from_facts(visa_facts(), ticker="V")

    assert result.coverage_class is CoverageClass.PARTIAL
    assert result.band(ScreeningDimension.PER_SHARE_COMPOUNDING) is Band.NOT_EVALUABLE
    assert (
        ScreeningReason.PER_SHARE_METRICS_UNAVAILABLE
        in result.dimensions[ScreeningDimension.PER_SHARE_COMPOUNDING].reasons
    )
    assert result.coverage_ceiling is not None
    assert ScreeningReason.COVERAGE_LIMITED in result.coverage_reasons


def test_screening_coverage_class_agrees_with_the_feature_6_contract() -> None:
    """Screening must not invent a second, divergent coverage opinion."""
    for facts, ticker in ((adbe_facts(), "ADBE"), (costco_facts(), "COST"), (visa_facts(), "V")):
        history = canonical_history_from_sec(facts, ticker=ticker, max_years=5)
        coverage = company_coverage_from_history(history)
        evidence = assemble_screening_evidence(history)

        feature_6_full = all(
            layer.state is LayerCoverage.AVAILABLE for layer in coverage.layers.values()
        )
        assert (evidence.coverage_class is CoverageClass.FULL) is feature_6_full


def test_blocked_layers_are_named_rather_than_silently_dropped() -> None:
    evidence = assemble_screening_evidence(
        canonical_history_from_sec(visa_facts(), ticker="V", max_years=5)
    )

    assert evidence.blocked_layers
    assert all(isinstance(layer, str) for layer in evidence.blocked_layers)


def test_a_structurally_absent_metric_is_not_treated_as_a_blocker() -> None:
    """Adobe pays no dividend; absence by policy must not degrade its coverage."""
    evidence = assemble_screening_evidence(
        canonical_history_from_sec(adbe_facts(), ticker="ADBE", max_years=5)
    )

    assert "dividends_paid" not in evidence.unavailable_metrics
    assert evidence.coverage_class is CoverageClass.FULL


# --- Ranking -------------------------------------------------------------------


def _golden_universe() -> tuple[object, ...]:
    return tuple(
        canonical_history_from_sec(facts, ticker=ticker, max_years=5)
        for facts, ticker in (
            (adbe_facts(), "ADBE"),
            (visa_facts(), "V"),
            (costco_facts(), "COST"),
        )
    )


def test_ranking_orders_by_bucket_then_coverage_then_score_then_ticker() -> None:
    screening = screen_universe(_golden_universe())  # type: ignore[arg-type]
    ranked = screening.ranked

    keys = [result.rank_key for result in ranked]
    assert keys == sorted(keys)
    buckets = [BUCKET_ORDER.index(result.bucket) for result in ranked]
    assert buckets == sorted(buckets)


def test_ranking_is_stable_regardless_of_input_order() -> None:
    histories = list(_golden_universe())
    forward = screen_universe(histories)  # type: ignore[arg-type]
    backward = screen_universe(list(reversed(histories)))  # type: ignore[arg-type]

    assert [r.ticker for r in forward.ranked] == [r.ticker for r in backward.ranked]


def test_the_distribution_covers_every_bucket_including_empty_ones() -> None:
    screening = screen_universe(_golden_universe())  # type: ignore[arg-type]
    distribution = screening.distribution()

    assert tuple(distribution) == BUCKET_ORDER
    assert sum(distribution.values()) == len(screening.results)


def test_worth_underwriting_returns_only_the_two_highest_priority_buckets() -> None:
    screening = screen_universe(_golden_universe())  # type: ignore[arg-type]

    assert all(
        result.bucket in (Bucket.HIGH_PRIORITY, Bucket.WORTH_UNDERWRITING)
        for result in screening.worth_underwriting()
    )


def test_the_table_renders_every_company_and_the_distribution() -> None:
    screening = screen_universe(_golden_universe())  # type: ignore[arg-type]
    rendered = format_screening_table(screening)

    for result in screening.results:
        assert result.ticker in rendered
    assert "Distribution:" in rendered
    assert "not investment advice" in rendered


def test_the_detail_view_renders_one_justification_per_company() -> None:
    screening = screen_universe(_golden_universe())  # type: ignore[arg-type]
    rendered = format_screening_detail(screening)

    assert rendered.count("Opportunity Screening") == len(screening.results)


def test_screening_makes_no_network_call_and_runs_each_layer_once() -> None:
    """Scale check: screening is pure composition over already-derived rows."""
    history = canonical_history_from_sec(adbe_facts(), ticker="ADBE", max_years=5)
    calls: list[str] = []
    original_require = type(history).require

    def counting_require(self, metric: str, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append(metric)
        return original_require(self, metric, **kwargs)  # type: ignore[arg-type]

    type(history).require = counting_require  # type: ignore[method-assign]
    try:
        screen_company_from_history(history)
    finally:
        type(history).require = original_require  # type: ignore[method-assign]

    # Owner economics, capital efficiency, and capital allocation each resolve
    # their inputs once; no metric is resolved more than those three passes.
    assert max(calls.count(metric) for metric in set(calls)) <= 3


# --- Feature boundary ----------------------------------------------------------


def test_screening_never_emits_a_valuation_concept() -> None:
    """Feature 7 stops below valuation: no price, multiple, or expected return."""
    rendered = format_screening_result(
        screen_company_from_facts(adbe_facts(), ticker="ADBE")
    ).lower()

    for forbidden in (
        "price",
        "multiple",
        "intrinsic",
        "valuation",
        "expected return",
        "discount",
        "fair value",
        "scenario",
        "probability",
    ):
        assert forbidden not in rendered

    # Recommendation words are matched whole, so "buybacks" is not a false hit.
    for forbidden_word in ("buy", "sell", "hold", "target", "undervalued"):
        assert not re.search(rf"\b{forbidden_word}\b", rendered)


# --- Full-universe characterization (local snapshots only) ----------------------


def _universe_histories() -> list[object]:
    from owner_lens import load_settings
    from owner_lens.persistence import FilesystemRawSnapshotStore

    settings = load_settings()
    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    entries = json.loads(_COVERAGE_REPORT.read_text(encoding="utf-8"))["companies"]
    histories: list[object] = []
    for entry in entries:
        content_hash = entry.get("content_hash")
        if not content_hash or not raw_store.exists(str(content_hash)):
            continue
        histories.append(
            canonical_history_from_sec(
                json.loads(raw_store.get(str(content_hash))),
                ticker=str(entry["ticker"]),
                max_years=5,
            )
        )
    return histories


@pytest.mark.skipif(
    not _COVERAGE_REPORT.is_file(),
    reason="data/ is not committed; run scripts/survey_universe.py to populate it",
)
def test_the_full_universe_screens_as_documented() -> None:
    screening = screen_universe(_universe_histories())  # type: ignore[arg-type]
    actual = {
        result.ticker: (result.bucket, result.coverage_class)
        for result in screening.results
    }

    assert actual == EXPECTED_UNIVERSE


@pytest.mark.skipif(
    not _COVERAGE_REPORT.is_file(),
    reason="data/ is not committed; run scripts/survey_universe.py to populate it",
)
def test_the_universe_narrows_to_a_small_set_worth_underwriting() -> None:
    screening = screen_universe(_universe_histories())  # type: ignore[arg-type]
    worth = screening.worth_underwriting()

    assert len(worth) < len(screening.results) / 2
    assert {result.ticker for result in worth} == {
        "ADBE",
        "CMG",
        "NVDA",
        "COST",
        "INTU",
        "MSFT",
        "NOW",
    }


@pytest.mark.skipif(
    not _COVERAGE_REPORT.is_file(),
    reason="data/ is not committed; run scripts/survey_universe.py to populate it",
)
def test_nvidia_ties_at_the_top_rather_than_dominating_on_one_metric() -> None:
    """Banding is what stops one extraordinary number from deciding the ranking."""
    by_ticker = {
        result.ticker: result for result in screen_universe(_universe_histories()).results  # type: ignore[arg-type]
    }

    assert by_ticker["NVDA"].screening_score == by_ticker["ADBE"].screening_score
    assert by_ticker["NVDA"].bucket is by_ticker["ADBE"].bucket


@pytest.mark.skipif(
    not _COVERAGE_REPORT.is_file(),
    reason="data/ is not committed; run scripts/survey_universe.py to populate it",
)
def test_a_coverage_limited_company_does_not_outrank_a_fully_covered_one() -> None:
    """ServiceNow's measurable economics match the leaders; its coverage does not."""
    by_ticker = {
        result.ticker: result for result in screen_universe(_universe_histories()).results  # type: ignore[arg-type]
    }
    now, adbe = by_ticker["NOW"], by_ticker["ADBE"]

    assert now.coverage_class is CoverageClass.PARTIAL
    assert now.band(ScreeningDimension.BUSINESS_QUALITY) is Band.STRONG
    assert now.band(ScreeningDimension.PER_SHARE_COMPOUNDING) is Band.STRONG
    assert adbe.rank_key < now.rank_key


@pytest.mark.skipif(
    not _COVERAGE_REPORT.is_file(),
    reason="data/ is not committed; run scripts/survey_universe.py to populate it",
)
def test_weak_fundamentals_are_distinguished_from_incomplete_data() -> None:
    by_ticker = {
        result.ticker: result for result in screen_universe(_universe_histories()).results  # type: ignore[arg-type]
    }

    # Excluded because nothing can be derived at all.
    assert by_ticker["META"].bucket is Bucket.INSUFFICIENT_DATA
    assert by_ticker["META"].gate is ScreeningReason.COVERAGE_FAILED
    # Set aside on measured evidence, with the coverage limit also recorded.
    assert by_ticker["ORCL"].gate is ScreeningReason.PERSISTENT_CASH_BURN
    # Fully covered and set aside purely on fundamentals.
    assert by_ticker["CRM"].limiting_factor.value == "FUNDAMENTALS"

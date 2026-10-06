"""Screen the OwnerLens universe for research priority (Feature 7, Slice 7C).

Runs the deterministic opportunity screen across a universe of companies and
prints a ranked grid plus, optionally, the full per-company justification. It
answers "who deserves deeper underwriting and why", never "is this cheap":
nothing here reads a price, a multiple, or an estimate.

Usage (from the repository root)::

    uv run python scripts/screen_universe.py                 # the 24-company universe
    uv run python scripts/screen_universe.py ADBE MSFT NOW   # a subset
    uv run python scripts/screen_universe.py --detail        # full justifications

Screening is offline: it reads the raw SEC snapshots recorded in the coverage
report written by ``scripts/survey_universe.py``, so no SEC request is made and
no stored database is modified. The JSON report is written to
``data/screening_report.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from owner_lens import load_settings
from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.persistence import FilesystemRawSnapshotStore
from owner_lens.persistence.errors import StorageReadError
from owner_lens.screening import (
    DIMENSION_ORDER,
    ScreeningResult,
    UniverseScreening,
    format_screening_detail,
    format_screening_table,
    screen_universe,
)
from owner_lens.sec_adapter import canonical_history_from_sec
from owner_lens.universe import UNIVERSE_6A

_COVERAGE_REPORT = Path("data/universe_6a_report.json")
_REPORT = Path("data/screening_report.json")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("tickers", nargs="*", help="Tickers (default: the universe).")
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Print the full per-company justification after the grid.",
    )
    parser.add_argument("--max-years", type=int, default=5)
    parser.add_argument("--coverage-report", type=Path, default=_COVERAGE_REPORT)
    parser.add_argument("--report", type=Path, default=_REPORT)
    return parser.parse_args(argv)


def _histories(
    tickers: list[str],
    coverage_report: Path,
    raw_store: FilesystemRawSnapshotStore,
    max_years: int,
) -> tuple[list[CanonicalFinancialHistory], list[str]]:
    """Rebuild canonical histories offline from the recorded raw snapshots."""
    if not coverage_report.is_file():
        raise SystemExit(
            f"No coverage report at {coverage_report}; "
            "run 'uv run python scripts/survey_universe.py' first."
        )
    entries = {
        str(entry["ticker"]): entry
        for entry in json.loads(coverage_report.read_text(encoding="utf-8"))["companies"]
    }
    histories: list[CanonicalFinancialHistory] = []
    skipped: list[str] = []
    for ticker in tickers:
        entry = entries.get(ticker)
        content_hash = entry.get("content_hash") if entry else None
        if not content_hash:
            skipped.append(ticker)
            continue
        try:
            payload = raw_store.get(str(content_hash))
        except StorageReadError:
            skipped.append(ticker)
            continue
        histories.append(
            canonical_history_from_sec(
                json.loads(payload), ticker=ticker, max_years=max_years
            )
        )
    return histories, skipped


def _as_json(screening: UniverseScreening, skipped: list[str]) -> str:
    """Serialize the ranked results so a run is reproducible and diffable."""
    return json.dumps(
        {
            "companies": [_result_json(result) for result in screening.ranked],
            "distribution": {
                bucket.value: count
                for bucket, count in screening.distribution().items()
            },
            "no_stored_snapshot": skipped,
        },
        indent=1,
    )


def _result_json(result: ScreeningResult) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "latest_fiscal_year": result.latest_fiscal_year,
        "coverage_class": result.coverage_class.value,
        "bucket": result.bucket.value,
        "setup_type": result.setup_type.value,
        "limiting_factor": result.limiting_factor.value,
        "screening_score": result.screening_score,
        "evaluable_dimensions": result.evaluable_dimensions,
        "coverage_ceiling": (
            result.coverage_ceiling.value if result.coverage_ceiling else None
        ),
        "gate": result.gate.value if result.gate else None,
        "dimensions": {
            dimension.value: {
                "band": result.dimensions[dimension].band.value,
                "reasons": [r.value for r in result.dimensions[dimension].reasons],
                "evidence": list(result.dimensions[dimension].evidence),
            }
            for dimension in DIMENSION_ORDER
        },
        "supporting_reasons": [r.value for r in result.supporting_reasons],
        "limiting_reasons": [r.value for r in result.limiting_reasons],
        "coverage_reasons": [r.value for r in result.coverage_reasons],
        "unavailable_dimensions": [d.value for d in result.unavailable_dimensions],
        "unavailable_metrics": list(result.unavailable_metrics),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    tickers = [t.strip().upper() for t in args.tickers] or [
        member.ticker for member in UNIVERSE_6A
    ]

    histories, skipped = _histories(
        tickers, args.coverage_report, raw_store, args.max_years
    )
    if not histories:
        raise SystemExit("No stored raw snapshots are available to screen.")

    screening = screen_universe(histories)
    print(format_screening_table(screening))
    if skipped:
        print()
        print(f"No stored snapshot: {', '.join(skipped)}")
    if args.detail:
        print()
        print(format_screening_detail(screening))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_as_json(screening, skipped), encoding="utf-8")
    print(f"\nReport written to {args.report}")

    worth = screening.worth_underwriting()
    print(
        f"{len(worth)} of {len(screening.results)} companies warrant deeper "
        f"underwriting: {', '.join(r.ticker for r in worth)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Survey OwnerLens SEC-first coverage across a universe of companies (Slice 6A).

Runs the existing pipeline (SEC fetch, canonical history, every analytical layer,
coverage) for each ticker, diagnoses blockers, and prints three deterministic
views: per company, per canonical metric, and recurring patterns. Discovery only:
no override or mapping is changed by running it.

Usage (from the repository root)::

    uv run python scripts/survey_universe.py                 # the 24-company 6A universe
    uv run python scripts/survey_universe.py NKE LULU        # a subset
    uv run python scripts/survey_universe.py --from-store    # offline re-run of the last report

Live runs ingest through ``ingest_company`` into a dedicated survey database
(``data/universe_6a.db``) that shares the normal raw-snapshot store, so the working
``data/ownerlens.db`` is never touched. The JSON report is written to
``data/universe_6a_report.json``; ``--from-store`` reproduces it offline from the
stored raw snapshots listed there.

Requires ``OWNER_LENS_SEC_USER_AGENT`` for live runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from owner_lens import load_settings
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore
from owner_lens.sec import SecClient
from owner_lens.universe import (
    UNIVERSE_6A,
    CompanySurvey,
    UniverseReport,
    format_company_view,
    format_metric_view,
    format_pattern_view,
    survey_from_snapshot,
    survey_with_ingestion,
)

_SURVEY_DB = Path("data/universe_6a.db")
_REPORT = Path("data/universe_6a_report.json")
_PAUSE_SECONDS = 0.5  # SEC fair access: sequential requests, well under 10/second


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("tickers", nargs="*", help="Tickers (default: the 6A universe).")
    parser.add_argument(
        "--from-store",
        action="store_true",
        help="Re-survey offline from the snapshots recorded in the last report.",
    )
    parser.add_argument("--max-years", type=int, default=5)
    parser.add_argument("--report", type=Path, default=_REPORT)
    return parser.parse_args(argv)


def _live(tickers: list[str], raw_store: FilesystemRawSnapshotStore, max_years: int) -> list[CompanySurvey]:
    settings = load_settings()
    if not settings.sec_user_agent:
        raise SystemExit("OWNER_LENS_SEC_USER_AGENT is not set; add it to .env.")
    _SURVEY_DB.parent.mkdir(parents=True, exist_ok=True)
    surveys: list[CompanySurvey] = []
    with SqliteStore(_SURVEY_DB, raw_store=raw_store) as store, SecClient(
        settings.sec_user_agent
    ) as sec:
        store.initialize()
        for index, ticker in enumerate(tickers):
            if index:
                time.sleep(_PAUSE_SECONDS)
            survey = survey_with_ingestion(
                ticker, sec_client=sec, store=store, raw_store=raw_store, max_years=max_years
            )
            print(f"  {survey.ticker:<6} {survey.overall.value:<8} {survey.primary_blocker or ''}"[:140])
            surveys.append(survey)
    return surveys


def _from_store(
    tickers: list[str] | None, report: Path, raw_store: FilesystemRawSnapshotStore, max_years: int
) -> list[CompanySurvey]:
    if not report.is_file():
        raise SystemExit(f"No prior report at {report}; run a live survey first.")
    entries = json.loads(report.read_text(encoding="utf-8"))["companies"]
    wanted = {t.upper() for t in tickers} if tickers else None
    return [
        survey_from_snapshot(entry, raw_store, max_years=max_years)
        for entry in entries
        if wanted is None or entry["ticker"] in wanted
    ]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    tickers = [t.strip().upper() for t in args.tickers] or [m.ticker for m in UNIVERSE_6A]

    if args.from_store:
        surveys = _from_store(args.tickers or None, args.report, raw_store, args.max_years)
    else:
        print(f"Surveying {len(tickers)} companies (live SEC, survey DB {_SURVEY_DB})")
        surveys = _live(tickers, raw_store, args.max_years)

    report = UniverseReport(tuple(surveys))
    if not args.from_store:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report.to_json(), encoding="utf-8")
    print()
    print(format_company_view(report))
    print()
    print(format_metric_view(report))
    print()
    print(format_pattern_view(report))
    if not args.from_store:
        print(f"\nReport written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

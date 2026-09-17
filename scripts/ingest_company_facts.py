"""Persist SEC Company Facts for one or more tickers via the ingestion workflow.

This script is a thin convenience wrapper: it builds the local dependencies once
and calls the same :func:`owner_lens.ingestion.ingest_company` used by the
``owner-lens ingest`` CLI, so there is exactly one ingestion implementation. For a
single company prefer ``uv run owner-lens ingest <TICKER>``.

Usage (from the repository root)::

    uv run python scripts/ingest_company_facts.py                 # ADBE V COST
    uv run python scripts/ingest_company_facts.py MSFT AAPL
    uv run python scripts/ingest_company_facts.py ADBE --max-years 7

Requires ``OWNER_LENS_SEC_USER_AGENT`` (set it in ``.env``); SEC requires a
User-Agent identifying the application and an administrative contact.
"""

from __future__ import annotations

import argparse
import sys

from owner_lens import ingest_company, load_settings
from owner_lens.config import build_local_store
from owner_lens.ingestion import IngestionStatus
from owner_lens.sec import SecClient

_DEFAULT_TICKERS = ("ADBE", "V", "COST")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers",
        nargs="*",
        default=list(_DEFAULT_TICKERS),
        help="Ticker symbols to ingest (default: ADBE V COST).",
    )
    parser.add_argument(
        "--max-years",
        type=int,
        default=5,
        help="Number of fiscal years of history to normalize (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    if not settings.sec_user_agent:
        print(
            "OWNER_LENS_SEC_USER_AGENT is not set. Add it to .env (SEC requires a "
            "User-Agent identifying the application and an administrative contact).",
            file=sys.stderr,
        )
        return 2

    store = build_local_store(settings)
    store.initialize()
    tickers = [t.strip().upper() for t in args.tickers if t.strip()]
    print(f"Persisting to {settings.db_path} (raw: {settings.raw_data_path})")

    exit_code = 0
    with SecClient(settings.sec_user_agent) as client:
        for ticker in tickers:
            result = ingest_company(
                ticker, sec_client=client, store=store, max_years=args.max_years
            )
            if result.status is IngestionStatus.FAILED and result.failure is not None:
                print(
                    f"  {ticker}: FAILED ({result.failure.kind.value})", file=sys.stderr
                )
                exit_code = 1
                continue
            label = result.company.cik if result.company else ticker
            print(
                f"  {ticker} (CIK {label}): {result.status.value} — "
                f"{result.persisted_metric_count} derived metrics"
            )

    store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


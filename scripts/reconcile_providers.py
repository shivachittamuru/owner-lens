"""Reconcile SEC-backed and FMP-backed canonical histories (OwnerLens Slice 5C).

For each ticker this script:

1. retrieves SEC Company Facts live (no FMP cost), records the CIK and payload
   content hash, and stores the raw payload under the local raw-snapshot root so
   the report is reproducible offline;
2. loads FMP annual statements from the local raw-response cache only. A cache
   miss is an error unless ``--allow-fmp-fetch`` is given, so re-running never
   spends FMP API calls by accident;
3. builds both canonical histories, reconciles them with the documented
   ``KNOWN_DISCREPANCIES``, and prints the report and a cross-company summary.

Usage (from the repository root)::

    uv run python scripts/reconcile_providers.py               # ADBE V COST MSFT
    uv run python scripts/reconcile_providers.py ADBE --show-all
    uv run python scripts/reconcile_providers.py MSFT --allow-fmp-fetch

Requires ``OWNER_LENS_SEC_USER_AGENT``. ``OWNER_LENS_FMP_API_KEY`` is needed only
with ``--allow-fmp-fetch``. Exit code 0 means every report was produced; it does
not imply FMP is eligible as the primary provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from owner_lens import (
    FmpClient,
    FmpError,
    SecClient,
    SecError,
    canonical_history_from_fmp,
    canonical_history_from_sec,
    compute_content_hash,
    load_settings,
    require_fmp_api_key,
)
from owner_lens.fmp import FMP_STATEMENT_ENDPOINTS
from owner_lens.known_discrepancies import KNOWN_DISCREPANCIES
from owner_lens.persistence import FilesystemRawSnapshotStore
from owner_lens.reconciliation import (
    ReconciliationReport,
    ReconciliationStatus,
    format_reconciliation_report,
    reconcile_histories,
)

_DEFAULT_TICKERS = ("ADBE", "V", "COST", "MSFT")
_FMP_LIMIT = 5


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tickers", nargs="*", default=list(_DEFAULT_TICKERS))
    parser.add_argument("--show-all", action="store_true", help="Also list matching rows.")
    parser.add_argument(
        "--allow-fmp-fetch",
        action="store_true",
        help="Call FMP on a cache miss (spends free-tier API calls).",
    )
    return parser.parse_args(argv)


def _refuse_network(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("FMP network access disabled (cache-only mode)", request=request)


def _fmp_client(allow_fetch: bool) -> FmpClient:
    if allow_fetch:
        return FmpClient(require_fmp_api_key(load_settings()))
    # Cache-only: no key is sent anywhere and any network attempt fails loudly.
    return FmpClient(
        "cache-only", http_client=httpx.Client(transport=httpx.MockTransport(_refuse_network))
    )


def _missing_cache_entries(client: FmpClient, ticker: str) -> list[str]:
    if client.cache is None:
        return list(FMP_STATEMENT_ENDPOINTS.values())
    missing = []
    for endpoint in FMP_STATEMENT_ENDPOINTS.values():
        path = client.cache.path(endpoint, ticker, period="annual", limit=_FMP_LIMIT)
        if path is None or not path.is_file():
            missing.append(endpoint)
    return missing


def reconcile_ticker(
    ticker: str, sec: SecClient, fmp: FmpClient, raw_store: FilesystemRawSnapshotStore,
    *, allow_fetch: bool,
) -> tuple[ReconciliationReport, str]:
    """Return the report and a provenance header for one ticker."""
    result = sec.retrieve_company_facts(ticker)
    payload = json.dumps(result.raw_facts, sort_keys=True).encode()
    content_hash = compute_content_hash(payload)
    raw_path = raw_store.put(content_hash, payload)

    missing = _missing_cache_entries(fmp, ticker)
    if missing and not allow_fetch:
        raise FmpError(
            f"FMP cache miss for {ticker} ({', '.join(missing)}); "
            "re-run with --allow-fmp-fetch to fetch from FMP."
        )
    statements = fmp.retrieve_annual_statements(ticker, limit=_FMP_LIMIT)

    report = reconcile_histories(
        canonical_history_from_sec(result.raw_facts, ticker=ticker),
        canonical_history_from_fmp(statements),
        explanations=KNOWN_DISCREPANCIES,
    )
    header = (
        f"SEC: CIK {result.identity.cik}  content hash {content_hash}  raw {raw_path}\n"
        f"FMP: cache {fmp.cache.root if fmp.cache else '(disabled)'}  "
        f"{'fetched or cached' if allow_fetch else 'cache only'}"
    )
    return report, header


def _summary_table(reports: list[ReconciliationReport]) -> str:
    statuses = list(ReconciliationStatus)
    head = f"{'Ticker':<6} {'Compared':>8} " + " ".join(f"{s.value[:11]:>11}" for s in statuses)
    lines = [head + "  Verdict"]
    for report in reports:
        summary = report.summary()
        counts = " ".join(f"{summary.count(s):>11}" for s in statuses)
        lines.append(
            f"{report.ticker:<6} {summary.total_facts_compared:>8} {counts}  "
            f"{report.verdict().eligibility.value}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    if not settings.sec_user_agent:
        print("OWNER_LENS_SEC_USER_AGENT is not set; add it to .env.", file=sys.stderr)
        return 2
    try:
        fmp = _fmp_client(args.allow_fmp_fetch)
    except FmpError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    reports: list[ReconciliationReport] = []
    failures = 0
    with SecClient(settings.sec_user_agent) as sec, fmp:
        for ticker in (t.strip().upper() for t in args.tickers):
            try:
                report, header = reconcile_ticker(
                    ticker, sec, fmp, raw_store, allow_fetch=args.allow_fmp_fetch
                )
            except (SecError, FmpError) as exc:
                failures += 1
                print(f"{ticker}: {type(exc).__name__}: {exc}\n", file=sys.stderr)
                continue
            reports.append(report)
            print(header)
            print(format_reconciliation_report(report, show_all=args.show_all))
            print("\n" + "=" * 100 + "\n")
    if reports:
        print(_summary_table(reports))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

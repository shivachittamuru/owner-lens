"""Command-line interface for OwnerLens.

The console entry point ``owner-lens`` delegates to :func:`main`, which dispatches
argparse subcommands. ``ingest`` is the primary workflow (retrieve + persist one
company); ``show`` reads the latest persisted summary/coverage from storage with
no network call; ``screen`` runs the Feature 7 opportunity screen over already
persisted companies, also with no network call; ``workbench`` launches the
Feature 7D local research UI over the same persisted data; ``inspect`` preserves
the pre-4B raw-facts view. This module owns argument parsing, settings loading,
dependency composition, result formatting, and exit codes; the ingestion
orchestration itself lives in :mod:`owner_lens.ingestion`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.config import OwnerLensSettings, build_local_store, load_settings
from owner_lens.coverage import LAYER_ORDER
from owner_lens.ingestion import IngestionResult, IngestionStatus, ingest_company
from owner_lens.persistence import FilesystemRawSnapshotStore, OwnerLensStore
from owner_lens.persistence.errors import StorageReadError
from owner_lens.screening import (
    format_screening_detail,
    format_screening_table,
    screen_company_from_history,
    screen_universe,
)
from owner_lens.sec import SecClient, SecError
from owner_lens.sec_adapter import canonical_history_from_sec

__all__ = ["format_result", "main"]

_MISSING_USER_AGENT = (
    "Set OWNER_LENS_SEC_USER_AGENT to an SEC User-Agent identifying the "
    "application and an administrative contact, for example "
    "'OwnerLens admin@example.com'."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="owner-lens")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Retrieve and persist one company.")
    ingest.add_argument("ticker", help="SEC-resolvable ticker symbol.")
    ingest.add_argument(
        "--max-years", type=int, default=5, help="Fiscal years of history (>= 1)."
    )
    ingest.add_argument(
        "--force",
        action="store_true",
        help="Re-run analytics against an already-stored snapshot.",
    )

    show = sub.add_parser("show", help="Show the latest persisted summary/coverage.")
    show.add_argument("ticker", help="SEC-resolvable ticker symbol.")

    screen = sub.add_parser(
        "screen",
        help="Screen persisted companies for research priority (no network call).",
    )
    screen.add_argument(
        "tickers",
        nargs="*",
        help="Tickers to screen (default: every persisted company).",
    )
    screen.add_argument(
        "--detail",
        action="store_true",
        help="Print the full per-company justification instead of the grid.",
    )
    screen.add_argument(
        "--max-years", type=int, default=5, help="Fiscal years of history (>= 1)."
    )

    inspect = sub.add_parser("inspect", help="Print a raw Company Facts overview.")
    inspect.add_argument("ticker", help="SEC-resolvable ticker symbol.")

    workbench = sub.add_parser(
        "workbench", help="Launch the local research workbench in a browser."
    )
    workbench.add_argument(
        "--db",
        help="Persisted store to open (default: OWNER_LENS_DB_PATH).",
    )
    workbench.add_argument(
        "--port", type=int, default=8501, help="Port to serve the workbench on."
    )
    workbench.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window automatically.",
    )

    return parser


def format_result(result: IngestionResult, *, overall: str | None = None) -> str:
    """Render a concise, owner-friendly report for one ingestion outcome."""
    if result.status is IngestionStatus.FAILED and result.failure is not None:
        name = result.company.company_name if result.company else "(unresolved)"
        return (
            f"{name}\n"
            f"FAILED ({result.failure.kind.value}): {result.failure.message}"
        )

    company = result.company
    snapshot = result.source_snapshot
    assert company is not None and snapshot is not None
    short_hash = snapshot.content_hash[:8]
    source_state = "unchanged" if result.status is IngestionStatus.UNCHANGED else "new"

    lines = [
        f"{company.ticker} - {company.company_name}",
        f"CIK: {company.cik}",
        "",
        "Source:",
        "  SEC Company Facts",
        f"  snapshot: {short_hash}... (status: {source_state})",
        f"  processing: {result.processing_status.value}",
        "",
        "Persistence:",
        f"  reported facts:   {result.persisted_fact_count}",
        f"  derived metrics:  {result.persisted_metric_count}",
        f"  analyses:         {result.analysis_count}",
    ]

    if result.coverage is not None:
        lines.append("")
        lines.append("Coverage:")
        for layer in LAYER_ORDER:
            layer_result = result.coverage.layers[layer]
            label = layer.replace("_", " ").title()
            reason = (
                f"  ({layer_result.reason})"
                if layer_result.state.value != "AVAILABLE" and layer_result.reason
                else ""
            )
            lines.append(f"  {label + ':':<22}{layer_result.state.value}{reason}")
    elif result.status is IngestionStatus.UNCHANGED:
        lines.append("")
        lines.append("Coverage: unchanged (source already ingested)")

    if overall:
        lines.append("")
        lines.append("Overall Economic Value:")
        lines.append(f"  {overall}")

    if result.unsupported_items:
        lines.append("")
        lines.append("Unsupported / insufficient:")
        for item in result.unsupported_items:
            detail = f" ({item.reason})" if item.reason else ""
            lines.append(f"  {item.subject}: {item.kind.value}{detail}")

    return "\n".join(lines)


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.sec_user_agent:
        print(_MISSING_USER_AGENT, file=sys.stderr)
        return 2
    if args.max_years < 1:
        print("--max-years must be >= 1", file=sys.stderr)
        return 2

    store = build_local_store(settings)
    store.initialize()
    try:
        with SecClient(settings.sec_user_agent) as client:
            result = ingest_company(
                args.ticker,
                sec_client=client,
                store=store,
                max_years=args.max_years,
                force=args.force,
            )
        overall = None
        if result.company is not None and result.status is not IngestionStatus.FAILED:
            summary = store.get_latest_summary(result.company.cik)
            overall = summary.classification if summary else None
        print(format_result(result, overall=overall))
    finally:
        store.close()

    return 1 if result.status is IngestionStatus.FAILED else 0


def _cmd_show(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = build_local_store(settings)
    store.initialize()
    try:
        ticker = args.ticker.strip().upper()
        company = next(
            (c for c in store.list_companies() if c.ticker == ticker), None
        )
        if company is None:
            print(f"{ticker} has not been ingested.", file=sys.stderr)
            return 1
        summary = store.get_latest_summary(company.cik)
        coverage = store.get_company_coverage(company.cik)
        lines = [f"{company.ticker} - {company.company_name}", f"CIK: {company.cik}", ""]
        lines.append(
            f"Latest summary: {summary.classification}"
            if summary
            else "Latest summary: (none)"
        )
        history = _persisted_history(store, settings, company.cik, ticker, max_years=5)
        if history is not None:
            result = screen_company_from_history(history)
            lines.append(
                f"Screening:      {result.bucket.value}"
                f" ({result.setup_type.value}, coverage {result.coverage_class.value})"
            )
        if coverage:
            lines.append("")
            lines.append("Coverage:")
            for record in coverage:
                reason = f"  ({record.reason})" if record.reason else ""
                lines.append(
                    f"  {record.subject_kind}/{record.subject}: {record.state}{reason}"
                )
        print("\n".join(lines))
    finally:
        store.close()
    return 0


def _persisted_history(
    store: OwnerLensStore,
    settings: OwnerLensSettings,
    cik: str,
    ticker: str,
    *,
    max_years: int,
) -> CanonicalFinancialHistory | None:
    """Rebuild a canonical history from the stored raw snapshot, or None if absent.

    Reads only persisted data: no SEC call is made, so screening a company that
    has never been ingested fails explicitly rather than fetching silently.
    """
    snapshot = store.get_latest_source_snapshot(cik)
    if snapshot is None:
        return None
    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    try:
        payload = raw_store.get(snapshot.content_hash)
    except StorageReadError:
        return None
    return canonical_history_from_sec(
        json.loads(payload), ticker=ticker, max_years=max_years
    )


def _cmd_screen(args: argparse.Namespace) -> int:
    if args.max_years < 1:
        print("--max-years must be >= 1", file=sys.stderr)
        return 2
    settings = load_settings()
    store = build_local_store(settings)
    store.initialize()
    try:
        companies = store.list_companies()
        wanted = {t.strip().upper() for t in args.tickers}
        if wanted:
            selected = [c for c in companies if c.ticker in wanted]
            missing = sorted(wanted - {c.ticker for c in selected})
            if missing:
                print(
                    f"Not ingested: {', '.join(missing)}. Run 'owner-lens ingest' first.",
                    file=sys.stderr,
                )
                return 1
        else:
            selected = list(companies)
        if not selected:
            print("No companies have been ingested.", file=sys.stderr)
            return 1

        histories: list[CanonicalFinancialHistory] = []
        unavailable: list[str] = []
        for company in sorted(selected, key=lambda c: c.ticker):
            history = _persisted_history(
                store, settings, company.cik, company.ticker, max_years=args.max_years
            )
            if history is None:
                unavailable.append(company.ticker)
                continue
            histories.append(history)
        if not histories:
            print("No stored raw snapshots are available to screen.", file=sys.stderr)
            return 1

        screening = screen_universe(histories)
        print(
            format_screening_detail(screening)
            if args.detail
            else format_screening_table(screening)
        )
        if unavailable:
            print()
            print(f"No stored snapshot: {', '.join(unavailable)}")
    finally:
        store.close()
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.sec_user_agent:
        print(_MISSING_USER_AGENT, file=sys.stderr)
        return 2
    try:
        with SecClient(settings.sec_user_agent) as client:
            result = client.retrieve_company_facts(args.ticker)
    except SecError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    identity = result.identity
    raw = result.raw_facts
    facts = raw.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    print(f"ticker: {identity.ticker}")
    print(f"company: {identity.company_name}")
    print(f"CIK: {identity.cik}")
    print()
    print("top-level keys:")
    print(list(raw.keys()))
    print()
    print("facts namespaces:")
    print(sorted(facts.keys()))
    print()
    print("sample us-gaap concepts:")
    print(sorted(us_gaap.keys())[:10])
    return 0


def _cmd_workbench(args: argparse.Namespace) -> int:
    """Launch the Streamlit workbench against the persisted store.

    Streamlit owns its own process lifecycle, so this delegates to its CLI with
    the app module resolved from the installed package rather than from a
    hard-coded path. The store is passed through the environment, which is the
    same configuration contract every other command uses.
    """
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print(
            "The workbench needs Streamlit, which is not installed. Run 'uv sync' "
            "(it is in the 'workbench' dependency group) and try again.",
            file=sys.stderr,
        )
        return 2

    app_path = Path(__file__).resolve().parent / "workbench" / "app.py"
    if not app_path.is_file():
        print(f"Workbench application not found at {app_path}.", file=sys.stderr)
        return 1

    argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(args.port),
        "--server.headless",
        "true" if args.no_browser else "false",
    ]
    previous_argv, sys.argv = sys.argv, argv
    previous_db = os.environ.get("OWNER_LENS_DB_PATH")
    if args.db:
        os.environ["OWNER_LENS_DB_PATH"] = args.db
    try:
        streamlit_cli.main(prog_name="streamlit")
    except SystemExit as exit_signal:
        code = exit_signal.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    finally:
        # Both the argument vector and the environment are process-wide, so an
        # in-process caller must see them exactly as it left them.
        sys.argv = previous_argv
        if args.db:
            if previous_db is None:
                os.environ.pop("OWNER_LENS_DB_PATH", None)
            else:
                os.environ["OWNER_LENS_DB_PATH"] = previous_db
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch a subcommand; return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "screen":
        return _cmd_screen(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "workbench":
        return _cmd_workbench(args)
    parser.error(f"unknown command: {args.command}")
    return 2

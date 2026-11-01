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
from owner_lens.config import (
    OwnerLensSettings,
    build_local_store,
    load_settings,
    require_fmp_api_key,
)
from owner_lens.coverage import LAYER_ORDER
from owner_lens.evidence_ingestion import refresh_sp500_evidence
from owner_lens.fmp import FmpClient, FmpConfigurationError, FmpError
from owner_lens.ingestion import IngestionResult, IngestionStatus, ingest_company
from owner_lens.persistence import (
    FilesystemRawSnapshotStore,
    OwnerLensStore,
    SqliteStore,
)
from owner_lens.persistence.errors import PersistenceError, StorageReadError
from owner_lens.screening import (
    format_screening_detail,
    format_screening_table,
    screen_company_from_history,
    screen_universe,
)
from owner_lens.sec import SecClient, SecError
from owner_lens.sec_adapter import canonical_history_from_sec
from owner_lens.underwriting import (
    UnderwritingError,
    create_underwriting,
    load_manual_json,
)
from owner_lens.universe_ingestion import (
    UniverseRefreshError,
    refresh_sp500_universe,
)
from owner_lens.valuation import MODEL_VERSION, ValuationError, run_valuation

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

    refresh_sp500 = sub.add_parser(
        "refresh-sp500",
        help="Refresh current FMP S&P 500 membership and persisted evidence.",
    )
    refresh_sp500.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help=(
            "Limit evidence acquisition to these current members; the full "
            "membership snapshot is still persisted."
        ),
    )
    refresh_sp500.add_argument(
        "--force",
        action="store_true",
        help="Refetch evidence even when a recent persisted response is available.",
    )

    evidence_status = sub.add_parser(
        "evidence-status",
        help="Summarize persisted S&P 500 evidence coverage without network calls.",
    )
    evidence_status.add_argument(
        "--tickers",
        nargs="*",
        default=[],
        metavar="TICKER",
        help="Limit the summary to these securities.",
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
    screen.add_argument(
        "--provider",
        choices=("sec", "fmp"),
        default="sec",
        help="Explicit persisted evidence source (default: sec).",
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
    workbench.add_argument(
        "--provider",
        choices=("sec", "fmp"),
        default="sec",
        help="Initially selected evidence provider (default: sec).",
    )

    underwriting = sub.add_parser(
        "underwriting", help="Create or inspect immutable manual underwriting snapshots (offline)."
    )
    actions = underwriting.add_subparsers(dest="underwriting_action", required=True)
    create = actions.add_parser("create", help="Append a new version using persisted FMP evidence.")
    create.add_argument("ticker")
    create.add_argument("--file", required=True, type=Path, help="Explicit manual JSON inputs.")
    show_underwriting = actions.add_parser("show", help="Print a saved snapshot without recomputation.")
    show_underwriting.add_argument("ticker")
    show_underwriting.add_argument("--version", type=int, help="Version to show (default: latest).")
    history = actions.add_parser("history", help="List preserved versions.")
    history.add_argument("ticker")

    valuation = sub.add_parser("valuation", help="Offline deterministic five-year scenario valuation.")
    valuation_actions = valuation.add_subparsers(dest="valuation_action", required=True)
    for action in ("run", "show"):
        valuation_command = valuation_actions.add_parser(
            action, help="Compute and persist valuation." if action == "run" else "Read a saved valuation."
        )
        valuation_command.add_argument("ticker")
        valuation_command.add_argument("--version", type=int, required=True,
                                       help="Exact immutable underwriting version.")

    return parser


def _cmd_valuation(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise ValuationError("Valuation requires SQLite persistence.")
            records = source.store.list_underwriting(args.ticker.strip().upper())
            record = next((item for item in records if item.version == args.version), None)
            if record is None:
                raise ValuationError(f"Underwriting {args.ticker} version {args.version} not found.")
            if args.valuation_action == "run":
                result_json = run_valuation(source.store, record)
            else:
                saved_json = source.store.get_valuation(record.underwriting_id, MODEL_VERSION)
                if saved_json is None:
                    raise ValuationError("No saved valuation for this version. Run 'valuation run' first.")
                result_json = saved_json
            print(json.dumps(json.loads(result_json), indent=2))
        return 0
    except (ValuationError, PersistenceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_underwriting(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise UnderwritingError("Underwriting requires SQLite persistence.")
            if args.underwriting_action == "create":
                manual = load_manual_json(args.file.read_text(encoding="utf-8-sig"))
                record = create_underwriting(source, args.ticker, manual)
                print(f"Created {record.ticker} underwriting v{record.version}: "
                      f"{record.underwriting_id} | as of {record.as_of_date}")
                return 0
            records = source.store.list_underwriting(args.ticker.strip().upper())
            if not records:
                raise UnderwritingError(f"No underwriting records for {args.ticker}.")
            if args.underwriting_action == "history":
                print(json.dumps([
                    {"underwriting_id": record.underwriting_id, "version": record.version,
                     "ticker": record.ticker, "security_id": record.security_id,
                     "created_at": record.created_at, "as_of_date": record.as_of_date,
                     "content_hash": record.content_hash}
                    for record in records
                ], indent=2))
            else:
                version = args.version
                selected_record = next((record for record in reversed(records)
                               if version is None or record.version == version), None)
                if selected_record is None:
                    raise UnderwritingError(f"Underwriting version {version} not found.")
                record = selected_record
                print(json.dumps({
                    "underwriting_id": record.underwriting_id, "version": record.version,
                    "ticker": record.ticker, "security_id": record.security_id,
                    "created_at": record.created_at, "as_of_date": record.as_of_date,
                    "content_hash": record.content_hash,
                    "snapshot": json.loads(record.snapshot_json),
                }, indent=2))
        return 0
    except (UnderwritingError, PersistenceError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


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


def _cmd_refresh_sp500(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        api_key = require_fmp_api_key(settings)
    except FmpConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    store = build_local_store(settings)
    try:
        store.initialize()
        with FmpClient(api_key) as client:
            universe = refresh_sp500_universe(
                client=client,
                store=store,
                tickers=tuple(args.tickers) if args.tickers else None,
            )
            evidence = refresh_sp500_evidence(
                client=client,
                store=store,
                tickers=tuple(args.tickers) if args.tickers else None,
                force=args.force,
            )
        snapshot_status = "new" if universe.new_snapshot else "unchanged"
        print(f"S&P 500 refresh completed (run {universe.run_id[:8]}).")
        print(
            f"Membership: {universe.member_count} securities; snapshot "
            f"{universe.snapshot_id} ({snapshot_status}, {universe.content_hash[:12]})."
        )
        print(
            f"Evidence: {evidence.securities} securities; "
            f"{evidence.refreshed} refreshed, {evidence.skipped} reused, "
            f"{evidence.unsupported} unsupported, {evidence.failed} failed; "
            f"{evidence.canonical_histories} annual canonical histories."
        )
        return 1 if evidence.failed else 0
    except (FmpError, PersistenceError, UniverseRefreshError, ValueError) as exc:
        print(f"S&P 500 refresh failed: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


def _cmd_evidence_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = build_local_store(settings)
    try:
        store.initialize()
        snapshot = store.get_latest_universe_snapshot("fmp")
        if snapshot is None or snapshot.snapshot_id is None:
            print("No persisted FMP S&P 500 universe is available.", file=sys.stderr)
            return 1
        members = store.list_universe_members(snapshot.snapshot_id)
        requested = {ticker.strip().upper() for ticker in args.tickers}
        selected = [member for member in members if member.symbol in requested]
        if requested:
            missing = requested - {member.symbol for member in selected}
            if missing:
                print(
                    f"Not in persisted S&P 500 snapshot: {', '.join(sorted(missing))}.",
                    file=sys.stderr,
                )
                return 1
        else:
            selected = list(members)
        security_ids = store.universe_security_ids(snapshot.snapshot_id)
        counts = store.list_evidence_status_counts(
            [security_ids[member.symbol] for member in selected]
        )
        print(
            f"Persisted universe: {len(members)} securities, "
            f"snapshot {snapshot.snapshot_id} observed {snapshot.observed_at}."
        )
        for dataset, states in sorted(counts.items()):
            summary = ", ".join(
                f"{status.lower()}={count}" for status, count in sorted(states.items())
            )
            print(f"{dataset}: {summary}")
        return 0
    except PersistenceError as exc:
        print(f"Cannot read evidence status: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


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
        if args.provider == "fmp":
            from owner_lens.workbench.data import (
                WorkbenchSource,
                load_persisted_companies,
                screen_persisted_universe,
            )

            source = WorkbenchSource(
                store=store,
                raw_store=FilesystemRawSnapshotStore(Path(settings.raw_data_path)),
                db_path=settings.db_path,
                raw_data_path=settings.raw_data_path,
            )
            companies_fmp = load_persisted_companies(source, "fmp")
            wanted_fmp = {ticker.strip().upper() for ticker in args.tickers}
            missing_fmp = wanted_fmp - {company.ticker for company in companies_fmp}
            if missing_fmp:
                print(
                    f"Not in persisted S&P 500: {', '.join(sorted(missing_fmp))}.",
                    file=sys.stderr,
                )
                return 1
            selected_fmp = tuple(
                company
                for company in companies_fmp
                if not wanted_fmp or company.ticker in wanted_fmp
            )
            if not selected_fmp:
                print("No persisted FMP S&P 500 securities.", file=sys.stderr)
                return 1
            results_fmp = screen_persisted_universe(
                source, selected_fmp, max_years=args.max_years
            )
            from owner_lens.screening import UniverseScreening

            screening_fmp = UniverseScreening(results_fmp)
            print(
                "Provider: FMP · persisted annual canonical histories; no network calls."
            )
            print(
                format_screening_detail(screening_fmp)
                if args.detail
                else format_screening_table(screening_fmp)
            )
            return 0
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
    previous_provider = os.environ.get("OWNER_LENS_WORKBENCH_PROVIDER")
    os.environ["OWNER_LENS_WORKBENCH_PROVIDER"] = args.provider
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
        if previous_provider is None:
            os.environ.pop("OWNER_LENS_WORKBENCH_PROVIDER", None)
        else:
            os.environ["OWNER_LENS_WORKBENCH_PROVIDER"] = previous_provider
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
    if args.command == "refresh-sp500":
        return _cmd_refresh_sp500(args)
    if args.command == "evidence-status":
        return _cmd_evidence_status(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "screen":
        return _cmd_screen(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "workbench":
        return _cmd_workbench(args)
    if args.command == "underwriting":
        return _cmd_underwriting(args)
    if args.command == "valuation":
        return _cmd_valuation(args)
    parser.error(f"unknown command: {args.command}")
    return 2

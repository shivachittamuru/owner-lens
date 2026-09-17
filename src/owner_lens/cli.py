"""Command-line interface for OwnerLens.

The console entry point ``owner-lens`` delegates to :func:`main`, which dispatches
argparse subcommands. ``ingest`` is the primary workflow (retrieve + persist one
company); ``show`` reads the latest persisted summary/coverage from storage with
no network call; ``inspect`` preserves the pre-4B raw-facts view. This module owns
argument parsing, settings loading, dependency composition, result formatting, and
exit codes; the ingestion orchestration itself lives in :mod:`owner_lens.ingestion`.
"""

from __future__ import annotations

import argparse
import sys

from owner_lens.config import build_local_store, load_settings
from owner_lens.coverage import LAYER_ORDER
from owner_lens.ingestion import IngestionResult, IngestionStatus, ingest_company
from owner_lens.sec import SecClient, SecError

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

    inspect = sub.add_parser("inspect", help="Print a raw Company Facts overview.")
    inspect.add_argument("ticker", help="SEC-resolvable ticker symbol.")

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


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch a subcommand; return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    parser.error(f"unknown command: {args.command}")
    return 2

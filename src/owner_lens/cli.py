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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from owner_lens.canonical import CanonicalFinancialHistory
from owner_lens.challenger import ChallengerError, run_challenger
from owner_lens.changes import (
    ChangeClassification,
    ChangeError,
    approve_event,
    assess_event,
    change_history,
    create_event,
    current_change_state,
    format_assessment,
    format_current_state,
)
from owner_lens.config import (
    OwnerLensSettings,
    build_local_store,
    load_settings,
    require_fmp_api_key,
)
from owner_lens.coverage import LAYER_ORDER
from owner_lens.decisions import (
    DISCLAIMER as DECISION_DISCLAIMER,
)
from owner_lens.decisions import (
    DecisionError,
    ShadowEntry,
    create_decision,
    format_decision,
    load_decision_json,
    read_decision,
)
from owner_lens.evidence_ingestion import refresh_sp500_evidence
from owner_lens.fmp import FmpClient, FmpConfigurationError, FmpError
from owner_lens.ingestion import IngestionResult, IngestionStatus, ingest_company
from owner_lens.opportunity_comparison import (
    ComparisonError,
    UnderwritingSelection,
    compare_underwritings,
    format_comparison,
)
from owner_lens.persistence import (
    FilesystemRawSnapshotStore,
    OwnerLensStore,
    SqliteStore,
)
from owner_lens.persistence.errors import PersistenceError, StorageReadError
from owner_lens.position_sizing import (
    SizingError,
    canonical_json,
    create_portfolio,
    format_sizing,
    size_position,
)
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
from owner_lens.underwriting_summary import (
    SummaryError,
    format_summary,
    saved_valuation,
    summarize_underwriting,
)
from owner_lens.universe_ingestion import (
    UniverseRefreshError,
    refresh_sp500_universe,
)
from owner_lens.valuation import MODEL_VERSION, ValuationError, run_valuation
from owner_lens.variant import VariantError, compare_variant, format_variant

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

    comparison = sub.add_parser(
        "compare-underwriting",
        help="Compare 2-5 exact completed underwriting versions offline (no ranking score).",
    )
    comparison.add_argument("selections", nargs="+", metavar="TICKER:VERSION")
    comparison.add_argument("--json", action="store_true")

    mistakes = sub.add_parser("mistakes", help="Immutable investor mistake reviews; no skill assessment.")
    mistake_actions = mistakes.add_subparsers(dest="mistakes_action", required=True)
    review = mistake_actions.add_parser("review")
    review_actions = review.add_subparsers(dest="review_action", required=True)
    for action in ("create", "suggest"):
        command = review_actions.add_parser(action)
        command.add_argument("ticker")
        command.add_argument("--version", type=int, required=True)
        command.add_argument("--json", action="store_true")
        if action == "create":
            command.add_argument("--file", type=Path, required=True)
        else:
            command.add_argument("--review-date", help="UTC review date (default: today).")
            command.add_argument("--decision-id")
            command.add_argument("--sizing-analysis-id")
            command.add_argument("--calibration-report-id")
    for action in ("show", "history"):
        command = review_actions.add_parser(action)
        command.add_argument("review_id" if action == "show" else "ticker")
        command.add_argument("--json", action="store_true")
    mistake_summary = mistake_actions.add_parser("summary")
    mistake_summary.add_argument("--json", action="store_true")

    calibration = sub.add_parser("calibration", help="Offline, sample-guarded forecast calibration; no skill assessment.")
    calibration_actions = calibration.add_subparsers(dest="calibration_action", required=True)
    for action in ("run", "company"):
        command = calibration_actions.add_parser(action)
        if action == "company":
            command.add_argument("ticker")
        command.add_argument("--as-of", help="UTC cutoff date YYYY-MM-DD (default: today).")
        command.add_argument("--json", action="store_true")
    calibration_show = calibration_actions.add_parser("show")
    calibration_show.add_argument("report_id")
    calibration_show.add_argument("--json", action="store_true")

    outcome = sub.add_parser("outcome", help="Immutable manual forecast-versus-outcome tracking, offline.")
    outcome_actions = outcome.add_subparsers(dest="outcome_action", required=True)
    for action in ("create", "compare"):
        command = outcome_actions.add_parser(action)
        command.add_argument("ticker")
        command.add_argument("--version", type=int, required=True)
        command.add_argument("--json", action="store_true")
        if action == "create":
            command.add_argument("--file", type=Path, required=True)
    outcome_show = outcome_actions.add_parser("show")
    outcome_show.add_argument("observation_id")
    outcome_show.add_argument("--json", action="store_true")
    outcome_history = outcome_actions.add_parser("history")
    outcome_history.add_argument("ticker")
    outcome_history.add_argument("--json", action="store_true")

    change = sub.add_parser("change", help="Manual What Changed events and explicit classification approval, offline.")
    change_actions = change.add_subparsers(dest="change_action", required=True)
    change_create = change_actions.add_parser("create")
    change_create.add_argument("ticker")
    change_create.add_argument("--version", type=int, required=True)
    change_create.add_argument("--file", type=Path, required=True)
    change_create.add_argument("--json", action="store_true")
    for action in ("show", "assess", "approve"):
        command = change_actions.add_parser(action)
        command.add_argument("event_id")
        command.add_argument("--json", action="store_true")
        if action == "approve":
            command.add_argument("--classification", choices=[item.value for item in ChangeClassification], required=True)
            command.add_argument("--rationale", required=True, help="Explicit investor approval/override rationale.")
    for action in ("history", "summary"):
        command = change_actions.add_parser(action)
        command.add_argument("ticker")
        command.add_argument("--json", action="store_true")

    decision = sub.add_parser("decision", help="Append or read immutable investor decisions offline.")
    decision_actions = decision.add_subparsers(dest="decision_action", required=True)
    decision_create = decision_actions.add_parser("create", help="Append a decision tied to an exact completed version.")
    decision_create.add_argument("ticker")
    decision_create.add_argument("--version", type=int, required=True)
    decision_create.add_argument("--file", type=Path, required=True)
    decision_create.add_argument("--json", action="store_true")
    decision_show = decision_actions.add_parser("show", help="Show the most recent decision or an exact decision ID.")
    decision_show.add_argument("ticker")
    decision_show.add_argument("--decision-id")
    decision_show.add_argument("--json", action="store_true")
    decision_history = decision_actions.add_parser("history", help="Show append-only chronological decision history.")
    decision_history.add_argument("ticker")
    decision_history.add_argument("--json", action="store_true")
    shadow = sub.add_parser("shadow", help="Read frozen independent counterfactual starts; no P&L.")
    shadow_actions = shadow.add_subparsers(dest="shadow_action", required=True)
    shadow_show = shadow_actions.add_parser("show", help="Show shadow entries from saved decisions.")
    shadow_show.add_argument("--decision-id")
    shadow_show.add_argument("--json", action="store_true")

    portfolio = sub.add_parser("portfolio", help="Immutable manually supplied portfolio context.")
    portfolio_actions = portfolio.add_subparsers(dest="portfolio_action", required=True)
    snapshots = portfolio_actions.add_parser("snapshot")
    snapshot_actions = snapshots.add_subparsers(dest="snapshot_action", required=True)
    portfolio_create = snapshot_actions.add_parser("create")
    portfolio_create.add_argument("--file", type=Path, required=True)
    portfolio_create.add_argument("--json", action="store_true")
    portfolio_show = snapshot_actions.add_parser("show")
    portfolio_show.add_argument("snapshot_id")
    portfolio_show.add_argument("--json", action="store_true")
    portfolio_list = snapshot_actions.add_parser("list")
    portfolio_list.add_argument("--json", action="store_true")
    sizing = sub.add_parser("position-size", help="Offline bounded sizing guidance; no trade or decision is created.")
    sizing.add_argument("ticker")
    sizing.add_argument("--version", type=int, required=True)
    sizing.add_argument("--portfolio", required=True, help="Exact immutable portfolio snapshot UUID.")
    sizing.add_argument("--policy", type=Path, required=True, help="Explicit JUDGMENT limits; no defaults.")
    sizing.add_argument("--context", type=Path, help="Manual sector/industry/tags for an unheld opportunity.")
    sizing.add_argument("--increment", type=float, help="Proposed incremental weight as a decimal ratio.")
    sizing.add_argument("--decision-id", help="Optional exact Feature 9B decision context.")
    sizing.add_argument("--save", action="store_true", help="Append an immutable analysis; no decision or trade.")
    sizing.add_argument("--json", action="store_true")
    sizing_history = sub.add_parser("sizing", help="Read saved sizing analyses without recalculation.")
    sizing_actions = sizing_history.add_subparsers(dest="sizing_action", required=True)
    sizing_show = sizing_actions.add_parser("show")
    sizing_show.add_argument("analysis_id")
    sizing_show.add_argument("--json", action="store_true")
    sizing_list = sizing_actions.add_parser("history")
    sizing_list.add_argument("--json", action="store_true")

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
    summary = actions.add_parser("summary", help="Offline probability-weighted terminal return, not a recommendation.")
    summary.add_argument("ticker")
    summary.add_argument("--version", type=int, required=True)
    summary.add_argument("--required-return", type=float, help="Explicit evaluation hurdle; otherwise use saved investor policy.")
    summary.add_argument("--json", action="store_true")

    challenger = sub.add_parser("challenger", help="Bounded offline advisory review of immutable underwriting.")
    challenger_actions = challenger.add_subparsers(dest="challenger_action", required=True)
    for action in ("run", "show"):
        command = challenger_actions.add_parser(action, help="Append an advisory run." if action == "run" else "Read a saved run.")
        command.add_argument("ticker")
        command.add_argument("--version", type=int, required=True)
        if action == "show":
            command.add_argument("--run-id", help="Exact run UUID; default latest for this underwriting version.")

    valuation = sub.add_parser("valuation", help="Offline deterministic five-year scenario valuation.")
    valuation_actions = valuation.add_subparsers(dest="valuation_action", required=True)
    for action in ("run", "show"):
        valuation_command = valuation_actions.add_parser(
            action, help="Compute and persist valuation." if action == "run" else "Read a saved valuation."
        )
        valuation_command.add_argument("ticker")
        valuation_command.add_argument("--version", type=int, required=True,
                                       help="Exact immutable underwriting version.")

    variant = sub.add_parser("variant", help="Offline consensus/BASE assumption comparison.")
    variant_actions = variant.add_subparsers(dest="variant_action", required=True)
    variant_show = variant_actions.add_parser("show", help="Derive variant perception and local valuation sensitivity.")
    variant_show.add_argument("ticker")
    variant_show.add_argument("--version", type=int, required=True)
    variant_show.add_argument("--json", action="store_true", help="Print full typed report and provenance.")

    return parser


def _cmd_mistakes(args: argparse.Namespace) -> int:
    from owner_lens.mistakes import (
        MistakeError,
        create_review,
        read_review,
        review_history,
        review_summary,
        suggest_review,
    )
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise MistakeError("Mistake reviews require SQLite.")
            report: dict[str, Any] | list[dict[str, Any]]
            if args.mistakes_action == "summary":
                report = review_summary(source.store)
            elif args.review_action == "show":
                report = read_review(source.store, args.review_id)
            elif args.review_action == "history":
                report = review_history(source.store, args.ticker.strip().upper())
            else:
                selection = UnderwritingSelection(args.ticker.strip().upper(), args.version)
                if args.review_action == "create":
                    report = create_review(
                        source.store, selection,
                        load_decision_json(args.file.read_text(encoding="utf-8-sig")),
                    )
                else:
                    suggestion = suggest_review(source.store, selection, review_date=args.review_date)
                    links = {
                        **suggestion["links"],
                        "decision_id": args.decision_id,
                        "sizing_analysis_id": args.sizing_analysis_id,
                        "calibration_report_id": args.calibration_report_id,
                    }
                    report = suggest_review(
                        source.store, selection, links=links, review_date=args.review_date,
                    )
            print(canonical_json(report))
        return 0
    except (ValueError, PersistenceError, OSError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_calibration(args: argparse.Namespace) -> int:
    from owner_lens.calibration import (
        CalibrationError,
        format_report,
        read_report,
        run_calibration,
    )
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise CalibrationError("Calibration requires SQLite.")
            if args.calibration_action == "show":
                report = read_report(source.store, args.report_id)
            else:
                report = run_calibration(
                    source.store, as_of=args.as_of,
                    company=args.ticker if args.calibration_action == "company" else None,
                )
            print(canonical_json(report) if args.json else format_report(report))
        return 0
    except (ValueError, PersistenceError, OSError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_outcome(args: argparse.Namespace) -> int:
    from owner_lens.outcomes import (
        OutcomeError,
        compare_outcomes,
        create_observation,
        format_comparison,
        format_observation,
        outcome_history,
        read_observation,
    )
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise OutcomeError("Outcome history requires SQLite.")
            if args.outcome_action == "create":
                report = create_observation(
                    source.store, UnderwritingSelection(args.ticker.strip().upper(), args.version),
                    load_decision_json(args.file.read_text(encoding="utf-8-sig")),
                )
            elif args.outcome_action == "show":
                report = read_observation(source.store, args.observation_id)
            elif args.outcome_action == "history":
                history = outcome_history(source.store, args.ticker.strip().upper())
                print(canonical_json(history) if args.json else
                      "\n\n".join(format_observation(item) for item in history) or "No outcome observations recorded.")
                return 0
            else:
                comparison = compare_outcomes(
                    source.store, UnderwritingSelection(args.ticker.strip().upper(), args.version),
                )
                print(canonical_json(comparison) if args.json else format_comparison(comparison))
                return 0
            print(canonical_json(report) if args.json else format_observation(report))
        return 0
    except (ValueError, PersistenceError, OSError, UnicodeError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_change(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise ChangeError("Change history requires SQLite.")
            if args.change_action == "create":
                event = create_event(
                    source.store, UnderwritingSelection(args.ticker.strip().upper(), args.version),
                    load_decision_json(args.file.read_text(encoding="utf-8-sig")),
                )
                report = assess_event(source.store, event["event_id"])
            elif args.change_action in ("assess", "show"):
                report = assess_event(source.store, args.event_id)
            elif args.change_action == "approve":
                approve_event(source.store, args.event_id, args.classification, args.rationale)
                report = assess_event(source.store, args.event_id)
            elif args.change_action == "history":
                history = change_history(source.store, args.ticker.strip().upper())
                print(canonical_json(history) if args.json else
                      "\n\n".join(format_assessment(item) for item in history) or "No change events recorded.")
                return 0
            else:
                report = current_change_state(source.store, args.ticker.strip().upper())
                print(canonical_json(report) if args.json else format_current_state(report))
                return 0
            print(canonical_json(report) if args.json else format_assessment(report))
        return 0
    except (ValueError, PersistenceError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_sizing(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise SizingError("Portfolio context and sizing require SQLite.")
            if args.command == "portfolio":
                if args.snapshot_action == "create":
                    portfolio = create_portfolio(source.store, load_decision_json(args.file.read_text(encoding="utf-8-sig")))
                    print(portfolio.to_json() if args.json else f"Created portfolio snapshot {portfolio.snapshot_id}; normalization total {portfolio.normalization_total:g}.")
                elif args.snapshot_action == "show":
                    payload = source.store.get_portfolio_snapshot(args.snapshot_id)
                    print(payload if args.json else json.dumps(json.loads(payload), indent=2))
                else:
                    records = source.store.list_portfolio_snapshots()
                    print("[" + ",".join(record.snapshot_json for record in records) + "]" if args.json else
                          "\n".join(f"{record.snapshot_id} | {record.as_of_date}" for record in records) or "No portfolio snapshots recorded.")
            elif args.command == "position-size":
                report = size_position(
                    source.store, UnderwritingSelection(args.ticker.strip().upper(), args.version),
                    args.portfolio, load_decision_json(args.policy.read_text(encoding="utf-8-sig")),
                    context_data=load_decision_json(args.context.read_text(encoding="utf-8-sig")) if args.context else None,
                    proposed_increment=args.increment, decision_id=args.decision_id,
                )
                if args.save:
                    saved = source.store.save_sizing_analysis(canonical_json(report), created_at=datetime.now(UTC).isoformat())
                    print(canonical_json({"analysis_id": saved.analysis_id, "created_at": saved.created_at, "report": report}) if args.json else
                          f"Saved analysis {saved.analysis_id}\n" + format_sizing(report))
                else:
                    print(canonical_json(report) if args.json else format_sizing(report))
            elif args.sizing_action == "show":
                saved = source.store.get_sizing_analysis(args.analysis_id)
                print(saved.report_json if args.json else format_sizing(json.loads(saved.report_json)))
            else:
                analyses = source.store.list_sizing_analyses()
                print(canonical_json([{
                    "analysis_id": item.analysis_id, "created_at": item.created_at,
                    "report": json.loads(item.report_json),
                } for item in analyses]) if args.json else
                    "\n".join(f"{item.analysis_id} | {item.created_at} | {item.underwriting_id} | {item.portfolio_id}" for item in analyses) or "No sizing analyses recorded.")
        return 0
    except (SizingError, DecisionError, ComparisonError, PersistenceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_decision(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise DecisionError("Decision and shadow workflows require SQLite.")
            if args.command == "shadow":
                entries = [
                    ShadowEntry.from_data(json.loads(record.snapshot_json))
                    for record in source.store.list_shadow_entries(args.decision_id)
                ]
                if args.json:
                    print("[" + ",".join(entry.to_json() for entry in entries) + "]")
                else:
                    print("Decision date | Ticker | Role | Frozen price/date | Underwriting | Decision/action")
                    for entry in entries:
                        price = (f"${entry.frozen_price:.2f} / {entry.market_date}"
                                 if entry.frozen_price is not None else "MISSING (benchmark placeholder)")
                        print(f"{entry.decision_at} | {entry.ticker} | {entry.role} | {price} | "
                              f"{entry.underwriting_version or 'N/A'} | {entry.decision_id} / {entry.action}")
                    if not entries:
                        print("No shadow entries recorded.")
                    print(DECISION_DISCLAIMER)
                return 0
            if args.decision_action == "create":
                snapshot = create_decision(
                    source.store, UnderwritingSelection(args.ticker.strip().upper(), args.version),
                    load_decision_json(args.file.read_text(encoding="utf-8-sig")),
                )
                print(snapshot.to_json() if args.json else format_decision(snapshot))
            else:
                records = source.store.list_decisions(args.ticker)
                if args.decision_action == "history":
                    if args.json:
                        print("[" + ",".join(record.snapshot_json for record in records) + "]")
                    else:
                        print("\n\n".join(format_decision(read_decision(record)) for record in records)
                              or f"No decisions recorded for {args.ticker}.")
                else:
                    selected = next((record for record in records if record.decision_id == args.decision_id), None) if args.decision_id else (records[-1] if records else None)
                    if selected is None:
                        raise DecisionError(f"Decision {args.decision_id or 'history'} not found for {args.ticker}.")
                    print(selected.snapshot_json if args.json else format_decision(read_decision(selected)))
        return 0
    except (DecisionError, ComparisonError, PersistenceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_compare_underwriting(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        selections = tuple(UnderwritingSelection.parse(value) for value in args.selections)
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise ComparisonError("Opportunity comparison requires SQLite.")
            report = compare_underwritings(source.store, selections)
            print(report.to_json() if args.json else format_comparison(report))
        return 0
    except (ComparisonError, PersistenceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_variant(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise VariantError("Variant comparison requires SQLite underwriting records.")
            record = next((item for item in source.store.list_underwriting(args.ticker.strip().upper())
                           if item.version == args.version), None)
            if record is None:
                raise VariantError(f"Underwriting {args.ticker} version {args.version} not found.")
            report = compare_variant(record)
            print(json.dumps(json.loads(report.to_json()), indent=2) if args.json else format_variant(report))
        return 0
    except (VariantError, PersistenceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_summary(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise SummaryError("Underwriting summary requires SQLite.")
            record = next((item for item in source.store.list_underwriting(args.ticker.strip().upper())
                           if item.version == args.version), None)
            if record is None:
                raise SummaryError(f"Underwriting {args.ticker} version {args.version} not found.")
            summary = summarize_underwriting(
                record, saved_valuation(source.store, record), required_return=args.required_return,
            )
            print(json.dumps(json.loads(summary.to_json()), indent=2) if args.json else format_summary(summary))
        return 0
    except (SummaryError, PersistenceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_challenger(args: argparse.Namespace) -> int:
    from owner_lens.workbench.data import open_source

    try:
        with open_source() as source:
            if not isinstance(source.store, SqliteStore):
                raise ChallengerError("Challenger requires SQLite.")
            record = next((item for item in source.store.list_underwriting(args.ticker.strip().upper())
                           if item.version == args.version), None)
            if record is None:
                raise ChallengerError(f"Underwriting {args.ticker} version {args.version} not found.")
            if args.challenger_action == "run":
                run = run_challenger(source.store, record)
            else:
                runs = source.store.list_challenger_runs(record.underwriting_id)
                selected_run = next((item for item in reversed(runs) if args.run_id is None or item.run_id == args.run_id), None)
                if selected_run is None:
                    raise ChallengerError("No matching saved challenger run. Run 'challenger run' first.")
                run = selected_run
            print(json.dumps({
                "run_id": run.run_id, "underwriting_id": run.underwriting_id,
                "underwriting_version": run.underwriting_version,
                "underwriting_content_hash": run.underwriting_content_hash,
                "challenger_version": run.challenger_version, "model_version": run.model_version,
                "created_at": run.created_at, "input_content_hash": run.input_content_hash,
                "output_content_hash": run.output_content_hash, "output": json.loads(run.output_json),
            }, indent=2))
        return 0
    except (ChallengerError, SummaryError, VariantError, PersistenceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


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
        if args.underwriting_action == "summary":
            return _cmd_summary(args)
        return _cmd_underwriting(args)
    if args.command == "challenger":
        return _cmd_challenger(args)
    if args.command == "valuation":
        return _cmd_valuation(args)
    if args.command == "variant":
        return _cmd_variant(args)
    if args.command == "compare-underwriting":
        return _cmd_compare_underwriting(args)
    if args.command in ("decision", "shadow"):
        return _cmd_decision(args)
    if args.command in ("portfolio", "position-size", "sizing"):
        return _cmd_sizing(args)
    if args.command == "change":
        return _cmd_change(args)
    if args.command == "outcome":
        return _cmd_outcome(args)
    if args.command == "mistakes":
        return _cmd_mistakes(args)
    if args.command == "calibration":
        return _cmd_calibration(args)
    parser.error(f"unknown command: {args.command}")
    return 2

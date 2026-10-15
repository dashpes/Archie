"""Command-line interface for market-wide data collection.

Usage:
    investment-monitor --type collect-broad [--days-back N]
    investment-monitor --type insights
    investment-monitor --type prune [--insider-days N] [--news-days N] ...
"""

from __future__ import annotations

import argparse
import sys

from investment_monitor import __version__


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="investment-monitor",
        description="Market-wide data collection and confluence detection",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--type",
        "-t",
        choices=["collect-broad", "insights", "prune"],
        default="collect-broad",
        help="collect-broad (market-wide event ingestion, universe-independent), "
        "insights (run the confluence engine over collected data), "
        "prune (delete data older than the --*-days windows). "
        "Default: collect-broad",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level. Default: INFO",
    )

    parser.add_argument("--insider-days", type=int, default=0,
                        help="For --type prune: delete insider rows older than N days (0=keep all).")
    parser.add_argument("--news-days", type=int, default=0,
                        help="For --type prune: delete news rows older than N days (0=keep all).")
    parser.add_argument("--price-days", type=int, default=0,
                        help="For --type prune: delete price rows older than N days (0=keep all).")
    parser.add_argument("--findings-days", type=int, default=0,
                        help="For --type prune: delete findings older than N days (0=keep all).")

    parser.add_argument(
        "--days-back",
        type=int,
        default=1,
        help="For --type collect-broad: recent business days of SEC indexes to "
        "ingest (default 1; dedup makes overlap safe for catch-up).",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress non-error output",
    )

    return parser


def _collect_broad(args: argparse.Namespace, log_level: str) -> int:
    from investment_monitor.broad_collect import run_broad_collection_sync
    from investment_monitor.config import get_settings
    from investment_monitor.logging_config import setup_logging

    # Drop loguru's DEBUG default handler and honour --log-level, otherwise every
    # per-request rate-limit wait lands in the log.
    setup_logging(log_dir=str(get_settings().log_dir), log_level=log_level)

    try:
        results = run_broad_collection_sync(days_back=args.days_back)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not args.quiet:
        for r in results:
            print(str(r))

    # Label fresh ticker-tagged headlines bullish/bearish/neutral with the cheap
    # triage model, so confluence can drop bearish items from long-side
    # corroboration. Fail-open: no Ollama just leaves sentiment NULL.
    try:
        import asyncio as _asyncio

        from investment_monitor.analysis.local_llm import LocalLLM
        from investment_monitor.analysis.model_router import ModelRouter
        from investment_monitor.analysis.news_processor import classify_unscored_sentiment
        from investment_monitor.storage import get_session

        settings = get_settings()
        llm = LocalLLM(
            model=ModelRouter(settings).resolve("triage", base_url=settings.ollama_host),
            base_url=settings.ollama_host,
        )
        with get_session() as session:
            labeled = _asyncio.run(classify_unscored_sentiment(session, llm))
        if labeled and not args.quiet:
            print(f"sentiment: labeled {labeled} headlines")
    except Exception as e:  # noqa: BLE001 - sentiment must not fail collection
        print(f"sentiment labeling warning: {e}", file=sys.stderr)

    # After collecting, detect cross-source confluence and promote the strongest
    # findings to theses so the autonomous advisor trades them.
    try:
        from investment_monitor.robo.confluence_promotion import run_insight_promotion

        outcome = run_insight_promotion()
        if not args.quiet:
            promoted = ", ".join(outcome["promoted"]) or "(none)"
            print(f"insights: {outcome['findings']} findings; "
                  f"promoted {len(outcome['promoted'])} to theses: {promoted}")
    except Exception as e:  # noqa: BLE001 - insight pipeline must not fail collection
        print(f"insight pipeline warning: {e}", file=sys.stderr)
    return 0 if all(r.success for r in results) else 1


def _insights() -> int:
    from investment_monitor.analysis.confluence import run_confluence

    try:
        findings = run_confluence()
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not findings:
        print("No confluence findings.")
    else:
        print(f"{len(findings)} confluence finding(s):\n")
        for f in findings:
            print(f"  [{f['score']:>5.1f}] {f['narrative']}")
    return 0


def _prune(args: argparse.Namespace) -> int:
    from investment_monitor.config import get_settings
    from investment_monitor.storage import (
        RetentionConfig, get_session, init_db, prune_old_data,
    )

    cfg = RetentionConfig(
        insider_days=args.insider_days, news_days=args.news_days,
        price_days=args.price_days, findings_days=args.findings_days,
    )
    try:
        init_db(get_settings().db_path)
        with get_session() as s:
            deleted = prune_old_data(s, cfg)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("Pruned:" if deleted else "Nothing to prune (all windows 0 / no old rows).")
    for table, n in (deleted or {}).items():
        print(f"  {table}: {n} rows deleted")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI. Returns 0 on success, 1 on error."""
    parser = create_parser()
    args = parser.parse_args(argv)
    log_level = "ERROR" if args.quiet else args.log_level

    try:
        if args.type == "collect-broad":
            return _collect_broad(args, log_level)
        if args.type == "insights":
            return _insights()
        return _prune(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())

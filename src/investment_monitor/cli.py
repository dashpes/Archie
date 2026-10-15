"""``investment-data``: the data service CLI.

Usage:
    investment-data collect [--source insider ...] [--days-back N]
    investment-data label
    investment-data insights
    investment-data universe
    investment-data prune
    investment-data serve
    investment-data health data 300
    investment-data research discover | top | simulate | simulation-results
"""

from __future__ import annotations

import asyncio
import sys

import typer

from investment_monitor import __version__
from investment_monitor.config import get_settings
from investment_monitor.logging_config import setup_logging

app = typer.Typer(
    name="investment-data",
    help="Market-wide data collection, confluence detection, and the data service.",
    no_args_is_help=True,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"investment-data {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True),
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="DEBUG, INFO, WARNING, ERROR"),
) -> None:
    setup_logging(log_dir=str(get_settings().log_dir), log_level=log_level.upper())


@app.command()
def collect(
    source: list[str] = typer.Option(
        ["all"], "--source", "-s",
        help="insider, events, prices, news, congress, or all (repeatable).",
    ),
    days_back: int = typer.Option(
        1, "--days-back", help="Recent business days of SEC indexes to ingest; dedup makes overlap safe.",
    ),
) -> None:
    """Run the broad, market-wide collectors (each in its own session)."""
    from investment_monitor.broad_collect import SOURCES, run_broad_collection_sync

    wanted = tuple(SOURCES) if "all" in source else tuple(source)
    unknown = sorted(set(wanted) - set(SOURCES))
    if unknown:
        typer.secho(f"unknown source(s): {', '.join(unknown)}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    results = run_broad_collection_sync(days_back=days_back, sources=wanted)
    for r in results:
        typer.echo(str(r))
    if not all(r.success for r in results):
        raise typer.Exit(code=1)


@app.command()
def label() -> None:
    """Label unlabeled, ticker-tagged headlines bullish/bearish/neutral with the triage model."""
    from investment_monitor.analysis.local_llm import LocalLLM
    from investment_monitor.analysis.model_router import ModelRouter
    from investment_monitor.analysis.news_processor import classify_unscored_sentiment
    from investment_monitor.storage import get_session, init_db

    settings = get_settings()
    init_db(settings.db_path)
    llm = LocalLLM(
        model=ModelRouter(settings).resolve("triage", base_url=settings.ollama_host),
        base_url=settings.ollama_host,
    )
    with get_session() as session:
        labeled = asyncio.run(classify_unscored_sentiment(session, llm))
    typer.echo(f"sentiment: labeled {labeled} headlines")


@app.command()
def insights() -> None:
    """Detect cross-source confluence over the collected data and persist findings."""
    from investment_monitor.analysis.confluence import run_confluence

    findings = run_confluence()
    if not findings:
        typer.echo("No confluence findings.")
        return
    typer.echo(f"{len(findings)} confluence finding(s):\n")
    for f in findings:
        typer.echo(f"  [{f['score']:>5.1f}] {f['narrative']}")


@app.command()
def universe() -> None:
    """Refresh the research universe (S&P 500 and Nasdaq-100 membership)."""
    from investment_monitor.collectors.universe import UniverseCollector
    from investment_monitor.storage import get_session, init_db

    settings = get_settings()
    init_db(settings.db_path)
    with get_session() as session:
        result = asyncio.run(UniverseCollector(session, settings).collect([]))
    typer.echo(str(result))
    if not result.success:
        raise typer.Exit(code=1)


@app.command()
def prune() -> None:
    """Delete rows older than the RETENTION_* windows (0 keeps everything) and VACUUM."""
    from investment_monitor.storage import get_session, init_db
    from investment_monitor.storage.retention import RetentionConfig, prune_old_data

    settings = get_settings()
    init_db(settings.db_path)
    cfg = RetentionConfig(
        insider_days=settings.retention_insider_days,
        news_days=settings.retention_news_days,
        price_days=settings.retention_price_days,
        findings_days=settings.retention_findings_days,
        events_days=settings.retention_events_days,
    )
    if not cfg.any_enabled():
        typer.echo("Retention disabled (all windows 0): nothing to prune.")
        return
    with get_session() as session:
        deleted = prune_old_data(session, cfg)
    for table, n in sorted(deleted.items()):
        typer.echo(f"  {table:<22} {n:>8,} rows pruned")
    typer.echo(f"Prune complete ({sum(deleted.values()):,} rows removed).")


def data_jobs() -> list:
    """The data service schedule (US Eastern)."""
    from investment_monitor.scheduler import MON_TO_SAT, Job, daily_at, every, weekly_at

    py = [sys.executable, "-m", "investment_monitor.cli"]
    return [
        Job("news", py + ["collect", "--source", "news"], every(60), timeout_s=600),
        Job(
            "collect",
            py + ["collect", "--source", "insider", "--source", "events",
                  "--source", "prices", "--source", "congress", "--days-back", "3"],
            daily_at(6, 30, weekdays=MON_TO_SAT), timeout_s=3600,
        ),
        Job("label", py + ["label"], daily_at(7, 0, weekdays=MON_TO_SAT), timeout_s=1800),
        Job("insights", py + ["insights"], daily_at(7, 15, weekdays=MON_TO_SAT), timeout_s=600),
        Job("universe", py + ["universe"], weekly_at(6, 5, 0), timeout_s=1800),
        Job("prune", py + ["prune"], weekly_at(6, 4, 0), timeout_s=1800),
    ]


@app.command()
def serve() -> None:
    """Run the data service: the scheduler loop that runs the jobs above forever."""
    from investment_monitor.scheduler import serve as _serve

    _serve(data_jobs(), role="data")


@app.command()
def health(
    role: str = typer.Argument(..., help="data or bot"),
    max_age_s: int = typer.Argument(300, help="Oldest acceptable heartbeat age in seconds"),
) -> None:
    """Exit 0 when the service heartbeat is fresh; 1 otherwise (Docker healthcheck)."""
    from investment_monitor.scheduler import heartbeat_age_s

    age = heartbeat_age_s(get_settings(), role)
    if age is None or age > max_age_s:
        typer.echo(f"{role}: heartbeat {'missing' if age is None else f'{age:.0f}s old'}")
        raise typer.Exit(code=1)
    typer.echo(f"{role}: ok ({age:.0f}s)")


def _mount_research() -> None:
    from investment_monitor.research_cli import app as research_app

    app.add_typer(research_app, name="research", help="Discovery, scores, and simulations.")


_mount_research()


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()

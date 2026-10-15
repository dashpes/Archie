"""Command-line interface for the investment research system.

This module provides CLI commands for stock research operations including:
- Discovery pipeline execution
- Fundamentals refresh and universe scoring
- Viewing top scores
- Monte Carlo simulation for risk analysis

Usage:
    investment-data research discover
    investment-data research top [--limit N] [--min-score N]
    investment-data research simulate --ticker TICKER [--force] [--horizons 30,90,252]
    investment-data research simulate --tickers AAPL,MSFT,GOOGL
    investment-data research simulate --auto
    investment-data research simulation-results [--ticker TICKER] [--latest N]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer

import yfinance as yf

from investment_monitor.config import get_settings
from investment_monitor.models import ResearchConfig
from investment_monitor.collectors.universe import UniverseCollector
from investment_monitor.research.discovery import refresh_fundamentals, score_universe
from investment_monitor.simulation.analyzer import MonteCarloAnalyzer
from investment_monitor.simulation.models import SimulationConfig
from investment_monitor.storage import (
    get_session,
    get_simulation_results,
    init_db,
    latest_score,
    save_simulation_result,
    top_scores,
)

app = typer.Typer(
    name="investment-research",
    help="Stock research and discovery CLI",
    no_args_is_help=True,
)


def _load_research_config(config_dir: Path) -> ResearchConfig:
    """Load research config from YAML or use defaults."""
    config_path = config_dir / "research.yaml"
    if config_path.exists():
        return ResearchConfig.from_yaml(config_path)
    return ResearchConfig()


@app.command()
def discover() -> None:
    """Refresh the universe, fetch stale fundamentals, and score every member."""
    try:
        settings = get_settings()
        init_db(settings.db_path)
        research_config = _load_research_config(settings.config_dir)
        with get_session() as session:
            universe = asyncio.run(UniverseCollector(session, settings).collect([]))
            typer.echo(f"universe: {universe.records_collected} new members")
            refreshed = asyncio.run(refresh_fundamentals(session, settings, research_config))
            typer.echo(f"fundamentals: refreshed {refreshed.fetched}/{refreshed.requested}")
            scored = score_universe(session, research_config)
        typer.echo(
            f"scores: {scored.scored} scored, {scored.filtered} filtered, "
            f"{scored.no_snapshot} awaiting fundamentals (universe {scored.universe})"
        )
        if scored.top:
            typer.echo("top: " + ", ".join(f"{t} {c:.0f}" for t, c in scored.top[:10]))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def top(
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of candidates to show"),
    min_score: Optional[float] = typer.Option(None, "--min-score", "-s", help="Minimum composite score"),
) -> None:
    """Show the top-scoring tickers (each ticker's newest score)."""
    try:
        settings = get_settings()
        init_db(settings.db_path)
        with get_session() as session:
            rows = top_scores(session, limit=limit, min_composite=min_score)
            if not rows:
                typer.echo("No scored tickers found matching criteria.")
                return
            typer.echo(f"\n--- Top Scores ({len(rows)}) ---")
            typer.echo(f"{'#':<4} {'Ticker':<8} {'Score':>6} {'Val':>5} {'Gro':>5} {'Qua':>5} {'Mom':>5} {'Sen':>5}  as of")
            typer.echo("-" * 62)

            def _f(v):
                return f"{v:5.0f}" if v is not None else "    -"

            for i, r in enumerate(rows, 1):
                typer.echo(
                    f"{i:<4} {r.ticker:<8} {r.composite:6.1f} {_f(r.value)} {_f(r.growth)} "
                    f"{_f(r.quality)} {_f(r.momentum)} {_f(r.sentiment)}  {r.as_of.isoformat()}"
                )
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def simulate(
    ticker: Optional[str] = typer.Option(
        None,
        "--ticker",
        "-t",
        help="Single ticker to simulate",
    ),
    tickers: Optional[str] = typer.Option(
        None,
        "--tickers",
        help="Comma-separated list of tickers",
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        "-a",
        help="Auto-simulate all candidates >= 80 score",
    ),
    horizons: str = typer.Option(
        "30,90,252",
        "--horizons",
        "-h",
        help="Comma-separated time horizons (days)",
    ),
    min_paths: int = typer.Option(
        1000,
        "--min-paths",
        "-p",
        help="Minimum simulation paths",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force simulation regardless of score",
    ),
) -> None:
    """Run Monte Carlo simulation for stock candidates.

    Simulates price paths for one or more tickers using Geometric Brownian
    Motion and historical crisis scenarios. Results are saved to the database.

    Either --ticker, --tickers, or --auto must be specified.
    """
    try:
        settings = get_settings()
        init_db(settings.db_path)

        # Determine which tickers to simulate
        tickers_to_simulate: list[str] = []

        if ticker:
            tickers_to_simulate.append(ticker.upper())
        elif tickers:
            tickers_to_simulate.extend([t.strip().upper() for t in tickers.split(",")])
        elif auto:
            with get_session() as session:
                tickers_to_simulate.extend(r.ticker for r in top_scores(session, limit=50, min_composite=80.0))
                if not tickers_to_simulate:
                    typer.echo("No high-scoring candidates found for auto-simulation.")
                    return
        else:
            typer.echo(
                "Error: Must specify --ticker, --tickers, or --auto",
                err=True,
            )
            raise typer.Exit(code=1)

        # Parse horizons
        horizon_list = [int(h.strip()) for h in horizons.split(",")]

        # Create config
        config = SimulationConfig(
            horizons=horizon_list,
            min_paths=min_paths,
        )

        # Create analyzer
        analyzer = MonteCarloAnalyzer(config=config)

        typer.echo(f"Running simulations for {len(tickers_to_simulate)} ticker(s)...")
        typer.echo(f"Horizons: {horizon_list} days")
        typer.echo(f"Min paths: {min_paths}")
        typer.echo("")

        successful = 0
        failed = 0

        for t in tickers_to_simulate:
            try:
                # Get current price from yfinance
                stock = yf.Ticker(t)
                info = stock.info
                current_price = info.get("currentPrice") or info.get("regularMarketPrice")

                if not current_price:
                    typer.echo(f"  {t}: Error - Could not fetch current price", err=True)
                    failed += 1
                    continue

                # Get composite score if available
                with get_session() as session:
                    row = latest_score(session, t)
                    composite_score = (row.composite if row else 0.0) or 0.0

                # Run simulation
                typer.echo(f"  {t}: Simulating (price=${current_price:.2f})...")
                output = analyzer.analyze(
                    ticker=t,
                    entry_price=current_price,
                    composite_score=composite_score,
                    force=force,
                )

                # Save results
                with get_session() as session:
                    save_simulation_result(session, output)
                    session.commit()

                # Display summary
                if 30 in output.results:
                    var_30 = output.results[30].base_var_95
                    typer.echo(f"    30-day VaR (95%): {var_30:.1%}")

                if 252 in output.results:
                    mean_252 = output.results[252].base_mean
                    typer.echo(f"    252-day expected: ${mean_252:.2f}")

                typer.echo(f"    Primary risk driver: {output.sensitivity.primary_driver}")
                successful += 1

            except ValueError as e:
                typer.echo(f"  {t}: Error - {e}", err=True)
                failed += 1
            except Exception as e:
                typer.echo(f"  {t}: Error - {e}", err=True)
                failed += 1

        typer.echo("")
        typer.echo("--- Simulation Complete ---")
        typer.echo(f"Successful: {successful}")
        typer.echo(f"Failed: {failed}")

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("simulation-results")
def simulation_results(
    ticker: Optional[str] = typer.Option(
        None,
        "--ticker",
        "-t",
        help="Show results for specific ticker",
    ),
    latest: Optional[int] = typer.Option(
        None,
        "--latest",
        "-n",
        help="Show N most recent results",
    ),
) -> None:
    """View Monte Carlo simulation results.

    Displays stored simulation results from the database. Results can be
    filtered by ticker or limited to the most recent N entries.
    """
    try:
        settings = get_settings()
        init_db(settings.db_path)

        # Determine limit
        limit = latest if latest is not None else 10

        with get_session() as session:
            results = get_simulation_results(
                session,
                ticker=ticker.upper() if ticker else None,
                limit=limit,
            )

            if not results:
                if ticker:
                    typer.echo(f"No simulation results found for {ticker.upper()}")
                else:
                    typer.echo("No simulation results found.")
                return

            typer.echo(f"\n--- Simulation Results ({len(results)}) ---")
            typer.echo(
                f"{'Ticker':<8} {'Date':<12} {'Price':<10} {'Score':<8} "
                f"{'30d VaR':<10} {'252d Mean':<12}"
            )
            typer.echo("-" * 70)

            for r in results:
                # Extract VaR and mean from stored JSON
                var_30 = r.results_30d.get("base_var_95", 0) if r.results_30d else 0
                mean_252 = r.results_252d.get("base_mean", 0) if r.results_252d else 0

                var_str = f"{var_30:.1%}" if var_30 else "N/A"
                mean_str = f"${mean_252:.2f}" if mean_252 else "N/A"

                typer.echo(
                    f"{r.ticker:<8} {r.run_date.isoformat():<12} "
                    f"${r.entry_price:<9.2f} {r.composite_score:<8.1f} "
                    f"{var_str:<10} {mean_str:<12}"
                )

            typer.echo("")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


def main() -> int:
    """Main entry point for the CLI."""
    try:
        app()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())

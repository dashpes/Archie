"""Command-line interface for the trading bot.

Usage:
    investment-robo accounts
    investment-robo check-safety [--config DIR] [--raw]
    investment-robo status [--limit N] [--run-id RUN_ID]
    investment-robo pnl
    investment-robo pause / resume
    investment-robo notify-test
    investment-robo backtest [--days N]
    investment-robo prune

`check-safety` connects to Public, confirms the account is cash-only, and exits
non-zero if margin is present. `status` shows recent runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from investment_monitor.config import get_settings
from investment_monitor.robo.broker import BrokerError, PublicBroker
from investment_monitor.robo.config import ConfigError, RoboConfig
from investment_monitor.robo.notify import send_test
from investment_monitor.storage import (
    get_filled_robo_orders,
    get_recent_robo_runs,
    get_robo_orders_for_run,
    get_session,
    init_db,
)

app = typer.Typer(
    name="investment-robo",
    help="Cash-only, long-only trading bot for a Public.com account.",
    no_args_is_help=True,
)


def _load_config(config_dir: Path | None) -> RoboConfig:
    settings = get_settings()
    cfg_dir = config_dir or settings.config_dir
    try:
        return RoboConfig.from_yaml(Path(cfg_dir) / "robo.yaml")
    except ConfigError as exc:
        # A bad robo.yaml must never crash a command with a raw traceback.
        # Surface one clear, actionable message and exit non-zero.
        typer.secho(f"Config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@app.command("accounts")
def accounts(
    config: Path = typer.Option(None, "--config", "-c", help="Config directory"),
) -> None:
    """List all accounts your token can see, so you can pick the cash one."""
    settings = get_settings()
    broker = PublicBroker(
        api_token=settings.public_api_token,
        base_url=settings.public_api_base_url,
        dry_run=True,
    )
    try:
        accts = broker.list_accounts()
    except BrokerError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{'account_id':<24} {'type':<14} cash?")
    for a in accts:
        flag = "CASH ✓" if a["is_cash"] else (a["brokerage_account_type"] or "?")
        color = typer.colors.GREEN if a["is_cash"] else typer.colors.YELLOW
        typer.secho(f"{a['account_id']:<24} {a['account_type']:<14} {flag}", fg=color)
    cash = [a for a in accts if a["is_cash"]]
    if cash:
        typer.echo(
            f"\nSet `account_id: \"{cash[0]['account_id']}\"` in config/robo.yaml "
            "(the CASH account)."
        )
    else:
        typer.secho(
            "\nNo CASH account found — the bot requires one and will refuse to run.",
            fg=typer.colors.RED,
        )


@app.command("check-safety")
def check_safety(
    config: Path = typer.Option(None, "--config", "-c", help="Config directory"),
    raw: bool = typer.Option(False, "--raw", help="Print raw account/portfolio payloads"),
) -> None:
    """Confirm the configured account is cash-only and print balances. Exits non-zero on margin."""
    settings = get_settings()
    cfg = _load_config(config)
    broker = PublicBroker(
        api_token=settings.public_api_token,
        account_id=cfg.account_id,
        base_url=settings.public_api_base_url,
        dry_run=True,
    )
    try:
        account = broker.get_account_state()
    except BrokerError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Account:        {account.account_id} ({account.account_type})")
    typer.echo(f"Cash account:   {account.is_cash_account}")
    typer.echo(f"Margin enabled: {account.has_margin}")
    typer.echo(f"Settled cash:   ${account.settled_cash}")
    typer.echo(f"Positions value:${account.positions_value}")
    typer.echo(f"Total value:    ${account.total_value}")
    if account.positions:
        typer.echo("Positions:")
        for p in account.positions:
            line = f"  {p.symbol:<6} {p.quantity} @ ${p.price} = ${p.market_value}"
            if p.unit_cost is not None:
                gain = p.unrealized_gain
                gain_str = f"${gain:+.2f}" if gain is not None else "n/a"
                line += f"  (cost ${p.unit_cost}/sh, unrealized {gain_str})"
            typer.echo(line)
    total_unrl = account.total_unrealized_gain
    if total_unrl is not None:
        typer.echo(f"Unrealized P&L: ${total_unrl:+.2f}")
    if raw:
        typer.echo("\nRaw payloads (verify field mapping):")
        typer.echo(str(account.raw))

    if not account.is_cash_account or account.has_margin:
        typer.secho(
            "\nUNSAFE: account is not cash-only / has margin. The bot will refuse to run.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    typer.secho("\nSAFE: cash-only account confirmed.", fg=typer.colors.GREEN)


@app.command("status")
def status(
    limit: int = typer.Option(10, "--limit", help="Number of recent runs to show"),
    run_id: str = typer.Option("", "--run-id", help="Show orders for a specific run"),
) -> None:
    """Show recent runs (and orders for a given run)."""
    settings = get_settings()
    init_db(settings.db_path)
    with get_session() as session:
        if run_id:
            orders = get_robo_orders_for_run(session, run_id)
            if not orders:
                typer.echo(f"No orders for run {run_id}")
                return
            for o in orders:
                size = f"${o.notional}" if o.notional is not None else f"{o.quantity} sh"
                state = o.status or ("accepted" if o.gate_accepted else "rejected")
                fill = f" filled {o.fill_quantity}@${o.fill_price}" if o.fill_price is not None else ""
                typer.echo(
                    f"  {o.side:<4} {o.symbol:<6} {size:<10} {state:<16} "
                    f"{o.gate_code or ''} {o.gate_reason or ''}{fill}"
                )
            return

        runs = get_recent_robo_runs(session, limit=limit)
        if not runs:
            typer.echo("No runs recorded yet.")
            return
        typer.echo(
            f"{'started':<17} {'mode':<7} {'status':<10} {'value':>10} {'unreal':>9} "
            f"{'p/a/r/x':<10} run_id"
        )
        for r in runs:
            mode = "dry-run" if r.dry_run else "LIVE"
            started = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "?"
            counts = f"{r.num_proposed}/{r.num_accepted}/{r.num_rejected}/{r.num_placed}"
            value = f"${r.total_value:,.0f}" if r.total_value is not None else "-"
            unreal = f"${r.unrealized_pnl:+,.0f}" if r.unrealized_pnl is not None else "-"
            typer.echo(
                f"{started:<17} {mode:<7} {r.status:<10} {value:>10} {unreal:>9} "
                f"{counts:<10} {r.run_id}"
            )


@app.command("pnl")
def pnl(
    config: Path = typer.Option(None, "--config", "-c", help="Config directory"),
) -> None:
    """Show live positions with unrealized P&L (read straight from the broker)."""
    settings = get_settings()
    cfg = _load_config(config)
    broker = PublicBroker(
        api_token=settings.public_api_token,
        account_id=cfg.account_id,
        base_url=settings.public_api_base_url,
        dry_run=True,
    )
    try:
        account = broker.get_account_state()
    except BrokerError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Account: {account.account_id}    Total value: ${account.total_value}")
    if not account.positions:
        typer.echo("No open positions.")
        return

    header = f"{'symbol':<6} {'qty':>10} {'cost/sh':>10} {'price':>10} {'mkt val':>12} {'unreal $':>12} {'unreal %':>9}"
    typer.echo(header)
    for p in sorted(account.positions, key=lambda x: x.symbol):
        cost = f"${p.unit_cost}" if p.unit_cost is not None else "n/a"
        gain = f"{p.unrealized_gain:+.2f}" if p.unrealized_gain is not None else "n/a"
        ret = p.unrealized_return
        ret_str = f"{ret * 100:+.1f}%" if ret is not None else "n/a"
        typer.echo(
            f"{p.symbol:<6} {str(p.quantity):>10} {cost:>10} {f'${p.price}':>10} "
            f"{f'${p.market_value:.2f}':>12} {gain:>12} {ret_str:>9}"
        )

    total_unrl = account.total_unrealized_gain
    basis = account.total_cost_basis
    typer.echo(f"\nSettled cash:   ${account.settled_cash}")
    typer.echo(f"Positions value:${account.positions_value:.2f}")
    if basis is not None:
        typer.echo(f"Cost basis:     ${basis:.2f}")
    if total_unrl is not None:
        pct = f" ({total_unrl / basis * 100:+.1f}%)" if basis and basis > 0 else ""
        typer.echo(f"Unrealized P&L: ${total_unrl:+.2f}{pct}")
    else:
        typer.echo("Unrealized P&L: n/a (broker reported no cost basis)")

    # Realized P&L, reconstructed from the bot's OWN filled orders (not the shared
    # account's history) so manual/pre-existing positions never count as bot gains.
    realized_total = None
    try:
        from investment_monitor.robo.pnl import realized_pnl, trades_from_fills

        init_db(settings.db_path)
        with get_session() as session:
            rp = realized_pnl(trades_from_fills(get_filled_robo_orders(session)))
        realized_total = rp.total_realized
        realized_syms = {s: sp for s, sp in rp.per_symbol.items() if sp.realized != 0}
        if realized_syms:
            typer.echo("\nRealized P&L (bot trades only):")
            for sym, sp in sorted(realized_syms.items()):
                typer.echo(f"  {sym:<6} ${sp.realized:+.2f}")
        typer.echo(f"Realized P&L:   ${realized_total:+.2f}")
    except Exception as exc:  # noqa: BLE001 - reporting only; never fail the command
        typer.secho(f"Realized P&L:   unavailable ({exc})", fg=typer.colors.YELLOW)

    if realized_total is not None and total_unrl is not None:
        typer.echo(f"Total P&L:      ${realized_total + total_unrl:+.2f}  (realized + unrealized)")


@app.command("notify-test")
def notify_test() -> None:
    """Send a test email to confirm the channel is wired up."""
    settings = get_settings()
    email_on = bool((settings.smtp_host or "").strip() and (settings.email_to or "").strip())
    if not email_on:
        typer.secho(
            "No notification channel configured. Set SMTP_HOST + EMAIL_TO in .env.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    if send_test(settings):
        typer.secho(f"Sent test email to {settings.email_to}.", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "Failed to send email. Check SMTP_HOST/PORT/USERNAME/PASSWORD "
            "(Gmail needs an App Password) and logs.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)


@app.command("pause")
def pause(
    reason: str = typer.Option("", "--reason", "-r", help="Why trading is paused."),
) -> None:
    """Pause trading (the next trade runs record 'paused' and skip the broker).

    Data collection keeps running. Resume with `investment-robo resume`.
    """
    from investment_monitor.robo import control

    state = control.set_paused(get_settings().db_path, True, reason=reason, updated_by="cli")
    suffix = f" ({state.reason})" if state.reason else ""
    typer.secho(f"Trading PAUSED{suffix}. Resume with: investment-robo resume", fg=typer.colors.YELLOW)


@app.command("resume")
def resume() -> None:
    """Resume trading after a pause. (Never arms live mode by itself.)"""
    from investment_monitor.robo import control

    settings = get_settings()
    control.set_paused(settings.db_path, False, updated_by="cli")
    state = control.load_control(settings.db_path)
    typer.secho("Trading resumed.", fg=typer.colors.GREEN)
    if state.force_dry_run or settings.robo_force_dry_run:
        typer.echo("Note: paper mode is still forced (control file / ROBO_FORCE_DRY_RUN).")


@app.command("backtest")
def backtest(
    days: int = typer.Option(180, "--days", help="Replay window ending today"),
    step: int = typer.Option(5, "--step", help="Days between signal re-evaluations"),
    horizon: int = typer.Option(90, "--horizon", help="Max holding period (days)"),
    min_score: float = typer.Option(4.0, "--min-score", help="Promotion score floor to test"),
    profit_target: float = typer.Option(
        None, "--profit-target", help="Take-profit at this % gain from entry (off if omitted)"
    ),
    trailing_stop: float = typer.Option(
        None, "--trailing-stop", help="Exit this % below the post-entry high (off if omitted)"
    ),
    trailing_arm: float = typer.Option(
        10.0, "--trailing-arm", help="Gain % from entry required before the trailing stop arms"
    ),
) -> None:
    """Walk-forward replay of confluence -> entry -> exits over stored history.

    Uses the REAL production scoring and guards as-of each past date (insider +
    volume sources; no look-ahead). Depth is bounded by ingested history — run
    'investment-monitor --type collect-broad --days-back N' first to backfill
    EDGAR, and note retention windows cap what is kept.
    """
    from datetime import date, timedelta

    from investment_monitor.simulation.backtest import run_confluence_backtest

    settings = get_settings()
    init_db(settings.db_path)
    end = date.today()
    start = end - timedelta(days=days)
    with get_session() as session:
        result = run_confluence_backtest(
            session, start=start, end=end, step_days=step,
            horizon_days=horizon, promote_min_score=min_score,
            profit_target_pct=profit_target, trailing_stop_pct=trailing_stop,
            trailing_arm_pct=trailing_arm,
        )
    s = result.summary()

    def _fmt(st: dict) -> str:
        if not st["n"]:
            return "n=0"
        return (
            f"n={st['n']:<3} hit {st['hit_rate'] * 100:>3.0f}%  "
            f"avg {st['avg'] * 100:+6.1f}%  med {st['median'] * 100:+6.1f}%  "
            f"best {st['best'] * 100:+.0f}%  worst {st['worst'] * 100:+.0f}%"
        )

    typer.echo(f"Backtest {s['start']} -> {s['end']} ({s['steps']} steps, "
               f"{s['n_trades']} trades, {s['n_closed']} closed)")
    typer.echo(f"  overall      {_fmt(s['overall'])}")
    for band, st in s["by_score_band"].items():
        typer.echo(f"  score {band:<6} {_fmt(st)}")
    for reason, st in s["by_exit_reason"].items():
        typer.echo(f"  exit {reason:<9} {_fmt(st)}")
    if not s["n_trades"]:
        typer.echo("No trades — likely not enough insider/price history ingested "
                   "for this window.")


@app.command("prune")
def prune() -> None:
    """Prune old market data to keep the SQLite DB bounded.

    Applies the RETENTION_* windows from settings to the broad, market-wide tables
    (insider / news / prices / confluence findings) and VACUUMs to reclaim space. A
    window of 0 keeps everything for that source.
    """
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
        typer.echo("Retention disabled (all windows 0) — nothing to prune.")
        return
    with get_session() as session:
        deleted = prune_old_data(session, cfg)
    for table, n in sorted(deleted.items()):
        typer.echo(f"  {table:<22} {n:>8,} rows pruned")
    typer.echo(f"Prune complete ({sum(deleted.values()):,} rows removed).")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    sys.exit(app())

"""Email notifications for the bot's runs.

A thin, synchronous, fail-open bridge between the (sync) CLI and the email
channel. Two triggers:

  * trades executed — every BUY/SELL actually placed in a run (live; paper only when
    ``NOTIFY_PAPER_TRADES`` is set);
  * run errors      — a run that refused (margin!), failed, or errored, plus broker
    errors raised before a result exists.

Design rules:
  * Never raise. A notification problem must never affect trading — every public
    function swallows its own exceptions.
  * Silent when unconfigured. With ``SMTP_HOST`` or ``EMAIL_TO`` blank there is no channel and the
    functions are no-ops, so the feature is opt-in and the default path is byte-identical.
  * Read placed orders from the DB by ``run_id`` rather than threading state through
    the rebalance core — the trading pipeline needs no changes to support this.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from loguru import logger

from investment_monitor.config import Settings

if TYPE_CHECKING:
    from investment_monitor.robo.models import RebalanceResult

# Statuses that mean "this run did not complete normally" — always worth a ping,
# regardless of mode (a silently dead or refused trader is the worst outcome).
_ERROR_STATUSES = {"failed", "refused", "errored"}


# --- channel + send (fail-open) ---------------------------------------------------

def _channel(settings: Settings):
    """Build the notification channel, or None when unconfigured/unavailable.

    Email (SMTP) is the only transport; it needs no GUI and works from a container.
    """
    # Email (SMTP) — headless, daemon-safe. Active when host + recipient are set.
    if (settings.smtp_host or "").strip() and (settings.email_to or "").strip():
        try:
            from investment_monitor.notifications.email import EmailChannel

            return EmailChannel(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                sender=(settings.email_from or settings.smtp_username),
                recipient=settings.email_to,
                use_tls=settings.email_use_tls,
            )
        except Exception as exc:  # noqa: BLE001 - setup must never break a run
            logger.warning("email channel unavailable (ignored): {e}", e=exc)

    return None


def _send(
    settings: Settings, text: str, subject: str | None = None, html: str | None = None
) -> bool:
    """Send one message via the active channel. True on success, False otherwise.

    ``subject`` sets the email subject explicitly (iMessage ignores it). It must be
    passed for any branded message, since the letterhead is the first body line and
    would otherwise become the subject. ``html`` is an optional rich alternative,
    forwarded only to channels that advertise ``supports_html`` (email); the plain
    text always remains the canonical body.
    """
    channel = _channel(settings)
    if channel is None:
        return False
    try:
        if html and getattr(channel, "supports_html", False):
            return channel.send_text(text, subject=subject, html=html)
        return channel.send_text(text, subject=subject)
    except Exception as exc:  # noqa: BLE001 - fail-open
        logger.warning("notify failed (ignored): {e}", e=exc)
        return False


def notifications_configured(settings: Settings) -> bool:
    """True when any notification channel is configured (email or iMessage)."""
    return _channel(settings) is not None


def _wants_html(settings: Settings) -> bool:
    """True when the active channel can render an HTML alternative (email).

    Gathering the HTML letter's data touches the DB; skip all of it when the
    channel (iMessage, or none) would drop the HTML anyway.
    """
    return bool(getattr(_channel(settings), "supports_html", False))


# --- Archie: the advisor's persona / branding ------------------------------------
# Change ADVISOR_NAME (and the firm line) to rebrand; everything else flows from it.
ADVISOR_NAME = "Archie"
_FIRM_LINE = "Personal Private Equity"
_RULE = "─" * 30


def _british_date(d: date) -> str:
    """British long form, e.g. '23 June 2026'."""
    return f"{d.day} {d.strftime('%B %Y')}"


def _subject(title: str) -> str:
    """Email subject, brand-prefixed so every note is recognisably from Archie."""
    return f"{ADVISOR_NAME} · {title}"


def _compose(title: str, body: str) -> str:
    """Wrap a message body in Archie's letterhead + sign-off."""
    return (
        f"{ADVISOR_NAME.upper()}\n{_FIRM_LINE}\n{_RULE}\n"
        f"{title}\n\n{body}\n\n"
        f"Yours faithfully,\n{ADVISOR_NAME}"
    )


# --- formatting helpers -----------------------------------------------------------

def _mode(dry_run: bool) -> str:
    return "Paper" if dry_run else "Live"


def _money(value) -> str:
    """Format a dollar amount with cents: $1,234.56."""
    return f"${value:,.2f}"


def _signed_money(value) -> str:
    """Format a signed dollar amount: +$0.04 / -$12.50.

    The sign is decided AFTER rounding to cents: a tiny magnitude that rounds to
    0.00 (e.g. Decimal('-0.004')) must render '+$0.00', never a misleading '-$0.00'.
    """
    magnitude = f"{abs(value):,.2f}"
    sign = "-" if value < 0 and float(magnitude.replace(",", "")) != 0 else "+"
    return f"{sign}${magnitude}"


def _order_size(order_row) -> str:
    if order_row.notional is not None:
        return _money(order_row.notional)
    if order_row.quantity is not None:
        return f"{order_row.quantity:g} shares"
    return "n/a"


def _value_line(result: RebalanceResult) -> str:
    try:
        return (
            f"Portfolio value: {_money(result.total_value)}    "
            f"Cash: {_money(result.settled_cash)}"
        )
    except Exception:  # noqa: BLE001 - cosmetic only
        return ""


def _order_row(order_row) -> dict:
    """One executed order as a structured row — the single source for text AND HTML."""
    fill = (
        f"at {_money(order_row.fill_price)}" if order_row.fill_price is not None else ""
    )
    return {
        "side": order_row.side.title(),
        "symbol": order_row.symbol,
        "size": _order_size(order_row),
        "fill": fill,
        "why": (getattr(order_row, "rationale", None) or "").strip(),
    }


def trade_text_lines(rows: list[dict]) -> list[str]:
    """Render structured order rows in the plain-text format (regression-locked)."""
    lines: list[str] = []
    for r in rows:
        fill = f" {r['fill']}" if r.get("fill") else ""
        lines.append(f"  {r['side']} {r['symbol']} — {r['size']}{fill}")
        if r.get("why"):
            lines.append(f"      why: {r['why']}")
    return lines


def _placed_order_rows(run_id: str, settings: Settings) -> list[dict]:
    """Read the orders that actually executed in a run (placed live, or simulated)."""
    from investment_monitor.storage import (
        get_robo_orders_for_run,
        get_session,
        init_db,
    )

    init_db(settings.db_path)
    with get_session() as session:
        return [
            _order_row(order_row)
            for order_row in get_robo_orders_for_run(session, run_id)
            if order_row.placed or order_row.simulated
        ]


# --- HTML letter data gatherers (each fail-open: None means "omit the section") ---

def _rejected_order_rows(run_id: str, settings: Settings) -> list[dict] | None:
    """Orders the gate declined in a run — the confirmation letter's appendix."""
    try:
        from investment_monitor.storage import (
            get_robo_orders_for_run,
            get_session,
            init_db,
        )

        init_db(settings.db_path)
        with get_session() as session:
            return [
                {
                    "symbol": o.symbol,
                    "side": o.side.title(),
                    "reason": (o.gate_reason or o.preflight_reason or "").strip(),
                }
                for o in get_robo_orders_for_run(session, run_id)
                if o.gate_accepted is False or (o.gate_accepted and o.preflight_ok is False)
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("rejected orders unavailable (ignored): {e}", e=exc)
        return None


# --- public triggers (all fail-open) ----------------------------------------------

def notify_run(result: RebalanceResult, settings: Settings) -> None:
    """Notify on a finished run: an error status, or the trades that were placed."""
    try:
        from investment_monitor.robo import email_html

        status = (result.status or "").lower()
        today = _british_date(date.today())
        if status in _ERROR_STATUSES:
            title = f"Trading Run {status.title()} ({_mode(result.dry_run)})"
            detail = result.message or result.summary_line()
            html = None
            try:
                if _wants_html(settings):
                    html = email_html.render_error(
                        date_str=today, title=title, message=detail, mode=_mode(result.dry_run)
                    )
            except Exception as exc:  # noqa: BLE001 - HTML is optional garnish
                logger.debug("error HTML skipped: {e}", e=exc)
            _send(settings, _compose(title, detail), subject=_subject(title), html=html)
            return

        if result.num_placed <= 0:
            return  # nothing executed — stay quiet
        if result.dry_run and not settings.notify_paper_trades:
            return  # paper placements are silent unless explicitly enabled

        title = (
            f"Trade Confirmation — {result.num_placed} order(s) executed "
            f"({_mode(result.dry_run)})"
        )
        rows = _placed_order_rows(result.run_id, settings)
        body_lines = trade_text_lines(rows)
        value = _value_line(result)
        if value:
            body_lines.extend(["", value])
        html = None
        try:
            if _wants_html(settings):
                html = email_html.render_trade_confirmation(
                    date_str=today,
                    mode=_mode(result.dry_run),
                    trade_rows=rows,
                    total_value=result.total_value,
                    settled_cash=result.settled_cash,
                    rejected_rows=_rejected_order_rows(result.run_id, settings),
                )
        except Exception as exc:  # noqa: BLE001 - HTML is optional garnish
            logger.debug("confirmation HTML skipped: {e}", e=exc)
        _send(settings, _compose(title, "\n".join(body_lines)), subject=_subject(title), html=html)
    except Exception as exc:  # noqa: BLE001 - never let a notification break the CLI
        logger.warning("robo notify_run failed (ignored): {e}", e=exc)


def notify_error(settings: Settings, *, message: str, dry_run: bool | None = None) -> None:
    """Notify on a broker/exception error raised before a result exists."""
    try:
        from investment_monitor.robo import email_html

        mode = f" ({_mode(dry_run)})" if dry_run is not None else ""
        title = f"Trading Run Error{mode}"
        html = None
        try:
            if _wants_html(settings):
                html = email_html.render_error(
                    date_str=_british_date(date.today()),
                    title=title,
                    message=message,
                    mode=_mode(dry_run) if dry_run is not None else None,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("error HTML skipped: {e}", e=exc)
        _send(settings, _compose(title, message), subject=_subject(title), html=html)
    except Exception as exc:  # noqa: BLE001 - fail-open
        logger.warning("robo notify_error failed (ignored): {e}", e=exc)


def send_test(settings: Settings) -> bool:
    """Send a test message so the operator can verify notification setup."""
    title = "Notification Test"
    body = (
        "This confirms your advisory notifications are configured correctly.\n"
        "I shall be in touch with trade confirmations and your daily summary."
    )
    html = None
    try:
        if _wants_html(settings):
            from investment_monitor.robo import email_html

            html = email_html.render_note(
                date_str=_british_date(date.today()),
                title=title,
                paragraphs=[
                    "This confirms your advisory notifications are configured correctly.",
                    "I shall be in touch with trade confirmations and your daily summary.",
                ],
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("test HTML skipped: {e}", e=exc)
    return _send(settings, _compose(title, body), subject=_subject(title), html=html)

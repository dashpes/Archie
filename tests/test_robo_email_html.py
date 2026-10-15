"""Tests for Archie's HTML letters (robo/email_html) and the multipart transport."""

from decimal import Decimal
from types import SimpleNamespace

from investment_monitor.robo import email_html


def _position(symbol="AAPL", value="1000", gain="120"):
    mv = Decimal(value)
    return SimpleNamespace(
        symbol=symbol,
        quantity=Decimal("2"),
        price=mv / 2,
        market_value=mv,
        unrealized_gain=Decimal(gain) if gain is not None else None,
    )


def _account(positions=None):
    positions = positions if positions is not None else [
        _position("AAPL", "1000", "120"),
        _position("TSLA", "500", "-300"),
    ]
    invested = sum((p.market_value for p in positions), Decimal("0"))
    return SimpleNamespace(
        total_value=Decimal("2500") + invested,
        settled_cash=Decimal("2500"),
        positions_value=invested,
        positions=positions,
        total_unrealized_gain=Decimal("-180"),
        total_cost_basis=Decimal("1680"),
    )


def _realized():
    aapl = SimpleNamespace(symbol="AAPL", realized=Decimal("54"))
    return SimpleNamespace(total_realized=Decimal("54"), per_symbol={"AAPL": aapl})


TRADES = [
    {"side": "Buy", "symbol": "EML", "size": "$1.94", "fill": "at $12.30",
     "why": "78% conviction — Insider cluster"},
]
THESES = [
    {"symbol": "NVDA", "status": "active", "conviction": 0.8, "delta": 0.05,
     "target_weight": 0.12, "excerpt": "Datacentre demand continues to outrun supply."},
]
FINDINGS = [
    {"ticker": "BORR", "kind": "insider_cluster", "score": 0.91,
     "narrative": "Three insiders bought $937k within a week."},
]
LEARNING = {"n": 12, "win_rate": 0.67, "brier": 0.19}


def _daily(**kw):
    base = dict(
        date_str="1 July 2026",
        mode="Paper",
        account=_account(),
        realized=_realized(),
        trade_rows=TRADES,
        theses=THESES,
        findings=FINDINGS,
        learning=LEARNING,
        prev_total=Decimal("3900"),
    )
    base.update(kw)
    return email_html.render_daily_summary(**base)


# --- daily summary -----------------------------------------------------------------

# --- trade confirmation / error / note ----------------------------------------------

def test_trade_confirmation_lists_orders_and_rejections():
    html = email_html.render_trade_confirmation(
        date_str="1 July 2026",
        mode="Live",
        trade_rows=TRADES,
        total_value=Decimal("4000"),
        settled_cash=Decimal("2500"),
        rejected_rows=[{"symbol": "GME", "side": "Buy", "reason": "concentration cap"}],
    )
    assert "1 Order Executed" in html
    assert "EML" in html
    assert "GME" in html and "concentration cap" in html
    assert "POSITION AFTER DEALING" in html


def test_error_letter_carries_message():
    html = email_html.render_error(
        date_str="1 July 2026", title="Trading Run Error", message="boom & bust",
        mode="Paper",
    )
    assert "regretfully" in html
    assert "boom &amp; bust" in html


def test_note_renders_paragraphs():
    html = email_html.render_note(
        date_str="1 July 2026", title="Notification Test",
        paragraphs=["First line.", "Second line."],
    )
    assert "First line." in html and "Second line." in html


# --- transport: multipart/alternative ------------------------------------------------

def test_email_channel_builds_multipart_with_html():
    from investment_monitor.notifications.email import EmailChannel

    ch = EmailChannel(host="smtp.x.com", recipient="to@x.com", username="u@x.com")
    msg = ch._build("plain body", "Subject", "<html><body>rich</body></html>")
    assert msg.get_content_type() == "multipart/alternative"
    parts = list(msg.iter_parts())
    assert parts[0].get_content_type() == "text/plain"
    assert "plain body" in parts[0].get_content()
    assert parts[1].get_content_type() == "text/html"
    assert "rich" in parts[1].get_content()


def test_email_channel_stays_plain_without_html():
    from investment_monitor.notifications.email import EmailChannel

    ch = EmailChannel(host="smtp.x.com", recipient="to@x.com", username="u@x.com")
    msg = ch._build("plain body", None)
    assert msg.get_content_type() == "text/plain"
    assert "plain body" in msg.get_content()

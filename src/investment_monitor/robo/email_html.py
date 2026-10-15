"""HTML renderers for Archie's advisory correspondence.

Every email the robo advisor sends keeps its plain-text body (the canonical,
regression-locked part) and gains an HTML alternative built here. The design is
the firm's letterhead: ivory paper, deep-green ink, brass hairlines, Georgia
serif — a private letter first, with the hard data as an appendix below.

Email-client constraints honoured throughout: nested tables only (no flexbox or
grid), every style inline, ``bgcolor`` attributes doubled up for dark-mode
clients, no webfonts, no ``<style>`` blocks (Gmail clips them), total size kept
well under Gmail's ~102 KB clipping threshold.

All functions are pure — no I/O, no DB, no network — so they unit-test exactly
like ``notify.format_daily_summary``. Callers gather the data (fail-open) and
pass plain values; any section whose data is ``None`` is simply omitted.
"""

from __future__ import annotations

from html import escape
from typing import Any

# --- palette: Archie's stationery --------------------------------------------------
IVORY = "#F6F1E7"       # the paper
INK = "#1C2A24"         # body text
GREEN = "#1E3A2F"       # headings, the firm's deep green
BRASS = "#A9852F"       # section labels, accents
HAIRLINE = "#D9CFBA"    # rules
MUTED = "#5C665F"       # secondary text, appendix
GAIN = "#2E6B4F"        # understated green for gains
LOSS = "#8C3B2E"        # claret for losses

SERIF = "Georgia, 'Times New Roman', Times, serif"

_BODY_STYLE = f"margin:0;padding:0;background-color:{IVORY};"
_TD_BASE = f"font-family:{SERIF};color:{INK};"


# --- money formatting (mirrors notify's rules, incl. the -$0.00 guard) -------------

def _money(value: Any) -> str:
    return f"${value:,.2f}"


def _signed_money(value: Any) -> str:
    magnitude = f"{abs(value):,.2f}"
    sign = "-" if value < 0 and float(magnitude.replace(",", "")) != 0 else "+"
    return f"{sign}${magnitude}"


def _pnl_color(value: Any) -> str:
    try:
        return LOSS if value < 0 else GAIN
    except TypeError:
        return INK


def _pct(value: Any, digits: int = 1) -> str:
    return f"{float(value) * 100:+.{digits}f}%"


# --- building blocks ----------------------------------------------------------------

def _letterhead(date_str: str) -> str:
    return f"""
<tr><td align="center" style="{_TD_BASE}padding:34px 40px 0 40px;">
  <div style="font-size:24px;letter-spacing:8px;color:{GREEN};">ARCHIE</div>
  <div style="font-size:11px;letter-spacing:4px;color:{BRASS};padding-top:6px;">PERSONAL&nbsp;PRIVATE&nbsp;EQUITY</div>
  <div style="font-size:12px;font-style:italic;color:{MUTED};padding-top:10px;">{escape(date_str)}</div>
</td></tr>
<tr><td style="padding:18px 40px 0 40px;"><div style="border-top:1px solid {HAIRLINE};font-size:0;line-height:0;">&nbsp;</div></td></tr>
"""


def _title(text: str) -> str:
    return (
        f'<tr><td align="center" style="{_TD_BASE}padding:22px 40px 4px 40px;'
        f'font-size:18px;font-style:italic;color:{GREEN};">{escape(text)}</td></tr>'
    )


def _letter(paragraphs: list[str]) -> str:
    """The plain-English letter body — the novice layer, always up top."""
    ps = "".join(
        f'<p style="margin:0 0 12px 0;font-size:15px;line-height:1.65;">{p}</p>'
        for p in paragraphs
        if p
    )
    return f'<tr><td style="{_TD_BASE}padding:16px 40px 6px 40px;">{ps}</td></tr>'


def _section(label: str, inner: str, *, muted: bool = False) -> str:
    """A section: small-caps brass label over a hairline rule, then content."""
    color = MUTED if muted else BRASS
    return f"""
<tr><td style="padding:22px 40px 0 40px;">
  <div style="font-family:{SERIF};font-size:11px;letter-spacing:3px;color:{color};padding-bottom:5px;">{escape(label.upper())}</div>
  <div style="border-top:1px solid {HAIRLINE};font-size:0;line-height:0;">&nbsp;</div>
</td></tr>
<tr><td style="padding:10px 40px 0 40px;">{inner}</td></tr>
"""


def _kv_table(rows: list[tuple[str, str, str | None]]) -> str:
    """Label/value rows: (label, value_html, color or None)."""
    out = ['<table width="100%" cellpadding="0" cellspacing="0" border="0">']
    for label, value, color in rows:
        c = color or INK
        out.append(
            f'<tr><td style="{_TD_BASE}font-size:14px;padding:3px 0;">{escape(label)}</td>'
            f'<td align="right" style="font-family:{SERIF};font-size:14px;padding:3px 0;'
            f'color:{c};">{value}</td></tr>'
        )
    out.append("</table>")
    return "".join(out)


def _data_table(headers: list[str], rows: list[list[str]], *, size: int = 13) -> str:
    """A dense table for the appendix/detail sections. Cell values are pre-built HTML."""
    head = "".join(
        f'<td style="font-family:{SERIF};font-size:10px;letter-spacing:2px;color:{MUTED};'
        f'padding:4px 6px;border-bottom:1px solid {HAIRLINE};">{escape(h.upper())}</td>'
        for h in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="{_TD_BASE}font-size:{size}px;padding:5px 6px;'
            f'border-bottom:1px solid {HAIRLINE};">{cell}</td>'
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"<tr>{head}</tr>{body}</table>"
    )


def _signoff(mode: str | None = None) -> str:
    mode_line = ""
    if mode:
        note = (
            "Paper mode — no real money moved."
            if mode.lower() == "paper"
            else "Live trading."
        )
        mode_line = (
            f'<div style="font-size:11px;color:{MUTED};padding-top:14px;">'
            f"{escape(note)} Automated advisory correspondence.</div>"
        )
    return f"""
<tr><td style="{_TD_BASE}padding:26px 40px 8px 40px;font-size:15px;line-height:1.6;">
  Yours faithfully,<br/><span style="font-style:italic;font-size:17px;color:{GREEN};">Archie</span>
  {mode_line}
</td></tr>
<tr><td style="padding:14px 40px 34px 40px;"><div style="border-top:1px solid {HAIRLINE};font-size:0;line-height:0;">&nbsp;</div></td></tr>
"""


def _document(date_str: str, title: str, inner: str, *, mode: str | None = None) -> str:
    """Assemble the full letter: letterhead, title, content, sign-off."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body style="{_BODY_STYLE}" bgcolor="{IVORY}">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{IVORY}" style="background-color:{IVORY};">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%;">
{_letterhead(date_str)}
{_title(title)}
{inner}
{_signoff(mode)}
</table>
</td></tr>
</table>
</body></html>"""


# --- sections shared between renderers ----------------------------------------------

def _trades_section(trade_rows: list[dict], label: str) -> str:
    rows: list[list[str]] = []
    for r in trade_rows:
        side = escape(str(r.get("side", "")))
        side_html = f'<span style="color:{GAIN if side.lower() == "buy" else LOSS};">{side}</span>'
        detail = escape(str(r.get("size", "")))
        fill = str(r.get("fill") or "")
        if fill:
            detail += f' <span style="color:{MUTED};">{escape(fill)}</span>'
        rows.append([side_html, escape(str(r.get("symbol", ""))), detail])
        why = str(r.get("why") or "").strip()
        if why:
            rows.append(
                [
                    "",
                    "",
                    f'<span style="font-style:italic;color:{MUTED};">{escape(why)}</span>',
                ]
            )
    return _section(label, _data_table(["Side", "Symbol", "Particulars"], rows))


# --- public renderers ----------------------------------------------------------------

def render_trade_confirmation(
    *,
    date_str: str,
    mode: str,
    trade_rows: list[dict],
    total_value: Any | None = None,
    settled_cash: Any | None = None,
    rejected_rows: list[dict] | None = None,
) -> str:
    """The trade-confirmation letter for a run that placed orders."""
    n = len(trade_rows)
    plural = "order" if n == 1 else "orders"
    sentences = [
        f"I have today executed <b>{n} {plural}</b> on your behalf, as set out below."
    ]
    if mode.lower() == "paper":
        sentences.append("This was a paper transaction — no real money moved.")

    body = [_letter(sentences), _trades_section(trade_rows, "Orders Executed")]

    if total_value is not None:
        rows = [("Portfolio value", f"<b>{_money(total_value)}</b>", None)]
        if settled_cash is not None:
            rows.append(("Cash available", _money(settled_cash), None))
        body.append(_section("Position After Dealing", _kv_table(rows)))

    if rejected_rows:
        rows = [
            [
                escape(str(r.get("symbol", ""))),
                escape(str(r.get("side", ""))),
                f'<span style="color:{MUTED};">{escape(str(r.get("reason") or ""))}</span>',
            ]
            for r in rejected_rows
        ]
        body.append(
            _section(
                "Appendix — orders the gate declined",
                _data_table(["Symbol", "Side", "Reason"], rows, size=12),
                muted=True,
            )
        )

    title = f"Trade Confirmation — {n} {plural.title()} Executed"
    return _document(date_str, title, "".join(body), mode=mode)


def render_error(*, date_str: str, title: str, message: str, mode: str | None = None) -> str:
    """A run-error notice, in the same letterhead."""
    inner = _letter(
        [
            "I must regretfully report a problem with today's run.",
        ]
    ) + _section(
        "Particulars",
        f'<div style="{_TD_BASE}font-size:14px;line-height:1.6;color:{LOSS};">{escape(message)}</div>',
    )
    return _document(date_str, title, inner, mode=mode)


def render_note(*, date_str: str, title: str, paragraphs: list[str]) -> str:
    """A short branded note (used by the notification test)."""
    return _document(date_str, title, _letter([escape(p) for p in paragraphs]))

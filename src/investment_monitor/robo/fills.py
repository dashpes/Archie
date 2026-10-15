"""Fill reconciliation for orders the bot placed at the broker.

Read-only and fail-open: a poll error on one order must never abort a run.
"""

from __future__ import annotations

from loguru import logger

from investment_monitor.robo.broker import PublicBroker, fill_from_order_raw
from investment_monitor.storage import get_unfilled_placed_orders


def apply_fill(order_row, info: dict) -> bool:
    """Apply a parsed ``get_order`` fill onto a RoboOrder row. Returns True ONLY if the
    order reached a genuinely terminal STATUS (so it no longer needs polling).

    Terminality is driven by ``info['terminal']`` (the broker order status), NOT by the
    mere presence of an ``average_price``. A PARTIALLY_FILLED order carries an
    ``average_price`` / ``filled_quantity`` for the shares filled so far but is still
    working — we record that partial progress yet keep ``fill_status`` NULL (the "still
    polling" sentinel ``get_unfilled_placed_orders`` keys on) so the remainder is
    reconciled on a later run. Latching it terminal here would strand the unfilled
    shares forever.
    """
    terminal = bool(info.get("terminal"))
    if info.get("average_price") is not None:
        # Record progress whether partial or fully filled (shares filled so far).
        order_row.fill_price = float(info["average_price"])
        order_row.fill_quantity = float(info.get("filled_quantity") or 0)
        if terminal:
            order_row.fill_status = info.get("status") or "FILLED"
            return True
        # Still working (e.g. PARTIALLY_FILLED): leave fill_status NULL, poll again.
        return False
    if terminal:  # rejected / cancelled / expired — done, no fill
        order_row.fill_quantity = 0.0
        order_row.fill_status = info.get("status") or "TERMINAL"
        return True
    return False  # still working — leave fill_status NULL, retry next run


def reconcile_order_fills(session, broker: PublicBroker) -> None:
    """Poll the broker for fills of previously-placed orders not yet reconciled.

    Read-only and fail-open: a poll error on one order must never abort the run.

    Skipped entirely in dry-run: a paper run must be fully read-isolated from the live
    broker. Unfilled rows are real LIVE placements left by an earlier live run; calling
    ``broker.get_order`` on them here would make an authenticated read against the real
    broker from a paper run. We leave them untouched so the next LIVE run reconciles
    them (fill_status stays NULL, so they remain in the unfilled-poll set).
    """
    if getattr(broker, "dry_run", False):
        return
    try:
        pending = get_unfilled_placed_orders(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load unfilled orders: {e}", e=exc)
        return
    for order_row in pending:
        try:
            info = fill_from_order_raw(broker.get_order(order_row.broker_order_id))
            if apply_fill(order_row, info):
                logger.info(
                    "order {oid} reconciled: {st} {q}@{p}", oid=order_row.broker_order_id,
                    st=order_row.fill_status, q=order_row.fill_quantity, p=order_row.fill_price,
                )
        except Exception as exc:  # noqa: BLE001 - one bad poll never breaks the run
            logger.warning("fill poll failed for {oid}: {e}", oid=order_row.broker_order_id, e=exc)

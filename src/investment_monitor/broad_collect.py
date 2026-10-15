"""Broad, universe-independent multi-source collection.

Each source runs in its own session and commits on its own, so a slow or failing
source never holds the write lock for the others. The insight engine mines this
market-wide stream for cross-source confluence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from investment_monitor.collectors.base import CollectorResult
from investment_monitor.collectors.congress import CongressTradesCollector
from investment_monitor.collectors.insider import InsiderCollector
from investment_monitor.collectors.material_events import MaterialEventsCollector
from investment_monitor.collectors.news import NewsCollector
from investment_monitor.collectors.prices import PriceCollector
from investment_monitor.config import Settings, get_settings
from investment_monitor.storage import get_session, init_db

# Price collection is bounded to the insider-active universe (the names confluence
# cares about) and capped so the daily run stays fast.
_PRICE_WINDOW_DAYS = 30
_PRICE_MAX_TICKERS = 500

# Order matters: insider first (it defines the relevant universe), then prices for
# that universe, then market-wide news and congress.
SOURCES = ("insider", "events", "prices", "news", "congress")


async def collect_source(
    name: str, settings: Settings, *, days_back: int = 1, limit: int | None = None
) -> CollectorResult:
    """Run one broad collector in its own session."""
    with get_session() as session:
        if name == "insider":
            return await InsiderCollector(session, settings).collect_all(
                days_back=days_back, limit=limit
            )
        if name == "events":
            return await MaterialEventsCollector(session, settings).collect_all(
                days_back=days_back, limit=limit
            )
        if name == "prices":
            return await PriceCollector(session, settings).collect_all(
                window_days=_PRICE_WINDOW_DAYS, max_tickers=_PRICE_MAX_TICKERS
            )
        if name == "news":
            return await NewsCollector(session, settings).collect_all()
        if name == "congress":
            # PTRs disclose up to 45 days late, so each run sweeps a trailing window
            # of submissions and dedup makes re-sweeps no-ops.
            return await CongressTradesCollector(session, settings).collect_all(
                days_back=max(7, days_back)
            )
    raise ValueError(f"unknown source {name!r}; expected one of {SOURCES}")


async def run_broad_collection(
    settings: Settings | None = None,
    *,
    days_back: int = 1,
    limit: int | None = None,
    sources: tuple[str, ...] | list[str] | None = None,
) -> list[CollectorResult]:
    """Run the requested broad collectors (default: all), returning their results.

    A source that raises is reported as a failed result; the others still run.
    """
    settings = settings or get_settings()
    init_db(settings.db_path)
    results: list[CollectorResult] = []
    for name in sources or SOURCES:
        started = datetime.now()
        try:
            results.append(
                await collect_source(name, settings, days_back=days_back, limit=limit)
            )
        except Exception as exc:  # noqa: BLE001 - one source must not abort the rest
            logger.error("broad-collect: {n} raised: {e}", n=name, e=exc)
            results.append(
                CollectorResult(
                    collector_name=name,
                    success=False,
                    records_collected=0,
                    errors=[str(exc)],
                    started_at=started,
                    finished_at=datetime.now(),
                )
            )
    for r in results:
        logger.info(f"broad-collect: {r}")
    return results


def run_broad_collection_sync(
    settings: Settings | None = None,
    *,
    days_back: int = 1,
    limit: int | None = None,
    sources: tuple[str, ...] | list[str] | None = None,
) -> list[CollectorResult]:
    """Synchronous wrapper around :func:`run_broad_collection` for CLI use."""
    return asyncio.run(
        run_broad_collection(settings, days_back=days_back, limit=limit, sources=sources)
    )

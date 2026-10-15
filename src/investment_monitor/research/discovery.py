"""Universe scoring: refresh fundamentals snapshots, then score every member.

Two jobs, both idempotent per day:

- ``refresh_fundamentals`` fetches yfinance fundamentals for the universe members
  whose snapshot is missing or older than ``fundamentals_max_age_days``, oldest
  first, capped per run so about 600 names turn over in a week.
- ``score_universe`` scores every universe member that has a snapshot, from stored
  data only (no network), and upserts one ``ticker_scores`` row per ticker per day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from loguru import logger
from sqlalchemy.orm import Session

from investment_monitor.analysis.scoring import passes_filters, score_ticker
from investment_monitor.analysis.scoring_bands import SCORER_VERSION
from investment_monitor.collectors.fundamentals import FundamentalsCollector, FundamentalsData
from investment_monitor.config import Settings
from investment_monitor.models import ResearchConfig
from investment_monitor.storage import (
    get_insider_transactions,
    get_prices,
    get_recent_news,
    get_universe_tickers,
    latest_snapshot,
    save_snapshot,
    stale_snapshot_tickers,
    upsert_score,
)

# Enough daily history for 1y momentum + 52-week levels (calendar days).
PRICE_HISTORY_DAYS = 400
INSIDER_DAYS = 90
NEWS_DAYS = 14


@dataclass
class RefreshResult:
    requested: int = 0
    fetched: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    universe: int = 0
    scored: int = 0
    filtered: int = 0
    no_snapshot: int = 0
    top: list[tuple[str, float]] = field(default_factory=list)


async def refresh_fundamentals(
    session: Session,
    settings: Settings,
    config: ResearchConfig,
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> RefreshResult:
    """Fetch and persist fundamentals for the stalest universe members."""
    as_of = as_of or date.today()
    tickers = stale_snapshot_tickers(
        session,
        get_universe_tickers(session),
        as_of=as_of,
        max_age_days=config.fundamentals_max_age_days,
        limit=config.fundamentals_per_run if limit is None else limit,
    )
    result = RefreshResult(requested=len(tickers))
    collector = FundamentalsCollector(session, settings)
    for ticker in tickers:
        try:
            data = await collector.get_fundamentals(ticker)
        except Exception as exc:  # noqa: BLE001 - one bad name must not stop the batch
            result.errors.append(f"{ticker}: {exc}")
            logger.warning("fundamentals fetch failed for {t}: {e}", t=ticker, e=exc)
            continue
        save_snapshot(session, ticker, as_of, data.model_dump(mode="json"))
        result.fetched += 1
    session.commit()
    logger.info("fundamentals: refreshed {n}/{m}", n=result.fetched, m=result.requested)
    return result


def score_universe(
    session: Session, config: ResearchConfig, *, as_of: date | None = None
) -> ScoreResult:
    """Score every universe member with a snapshot. Deterministic given the database."""
    as_of = as_of or date.today()
    tickers = get_universe_tickers(session)
    result = ScoreResult(universe=len(tickers))
    for ticker in tickers:
        snap = latest_snapshot(session, ticker)
        if snap is None:
            result.no_snapshot += 1
            continue
        fundamentals = FundamentalsData(**snap.data)
        if not passes_filters(fundamentals, config.universe):
            result.filtered += 1
            continue
        card = score_ticker(
            fundamentals,
            as_of=as_of,
            prices=get_prices(session, ticker, days=PRICE_HISTORY_DAYS),
            insider_txns=get_insider_transactions(session, ticker, days=INSIDER_DAYS),
            news_items=get_recent_news(session, ticker=ticker, hours=NEWS_DAYS * 24),
            weights=config.scoring_weights,
        )
        upsert_score(session, card, version=SCORER_VERSION)
        result.scored += 1
        if card.composite is not None:
            result.top.append((ticker, card.composite))
    session.commit()
    result.top.sort(key=lambda pair: (-pair[1], pair[0]))
    result.top = result.top[:20]
    logger.info(
        "score: {s} scored, {f} filtered, {n} without snapshot (universe {u})",
        s=result.scored, f=result.filtered, n=result.no_snapshot, u=result.universe,
    )
    return result

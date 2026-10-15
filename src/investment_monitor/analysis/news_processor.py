"""AI-enhanced news processing for relevance scoring and filtering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from investment_monitor.storage import (
    get_unclassified_news,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


    from .local_llm import LocalLLM


async def classify_unscored_sentiment(
    session: Session, llm: LocalLLM, *, batch_size: int = 150
) -> int:
    """Populate ``NewsItem.sentiment`` for ticker-tagged headlines (batch job).

    Standalone (no Portfolio needed — this labels the BROAD market-wide stream, not
    holdings). Each headline gets one bullish/bearish/neutral label from the local
    LLM; 'unknown' (LLM unavailable / unparseable) is left NULL so the item is
    retried next pass. Downstream, confluence drops bearish items from long-side
    news corroboration.
    """
    items = get_unclassified_news(session, limit=batch_size)
    if not items or not llm.is_available():
        return 0
    n = 0
    for item in items:
        try:
            sentiment = await llm.classify_sentiment(item.headline)
            if sentiment and sentiment != "unknown":
                item.sentiment = sentiment
                n += 1
        except Exception as e:  # noqa: BLE001 - one bad headline must not abort the batch
            logger.debug(f"sentiment classify failed for news {item.id}: {e}")
    try:
        session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to commit sentiment labels: {e}")
        session.rollback()
        return 0
    if n:
        logger.info(f"sentiment: labeled {n} headlines")
    return n



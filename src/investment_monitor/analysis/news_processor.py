"""Batch sentiment labeling of the market-wide headline stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from investment_monitor.storage import get_unclassified_news

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .sentiment import SentimentLabeler


def classify_unscored_sentiment(
    session: Session, labeler: SentimentLabeler, *, batch_size: int = 150
) -> int:
    """Populate ``NewsItem.sentiment`` for ticker-tagged headlines (batch job).

    Each headline gets one bullish/bearish/neutral label. A ``None`` from the
    labeler leaves the row NULL so it is retried next pass. ``sentiment_model``
    records which labeler wrote the label. Downstream, confluence drops bearish
    items from long-side news corroboration.
    """
    items = get_unclassified_news(session, limit=batch_size)
    if not items:
        return 0
    labels = labeler.label([item.headline for item in items])
    n = 0
    for item, sentiment in zip(items, labels, strict=True):
        if sentiment is None:
            continue
        item.sentiment = sentiment
        item.sentiment_model = labeler.name
        n += 1
    try:
        session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to commit sentiment labels: {e}")
        session.rollback()
        return 0
    if n:
        logger.info(f"sentiment: labeled {n} headlines via {labeler.name}")
    return n

"""CRUD operations for database models."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import InsiderTransaction, NewsItem, Price


# Price operations
def save_price(session: Session, price: Price) -> int:
    """Save a price record, returning its ID."""
    session.add(price)
    session.flush()
    return price.id


def save_prices(session: Session, prices: list[Price]) -> int:
    """Save multiple price records, returning count saved."""
    session.add_all(prices)
    session.flush()
    return len(prices)


def get_latest_price(session: Session, ticker: str) -> Price | None:
    """Get the most recent price for a ticker."""
    stmt = (
        select(Price)
        .where(Price.ticker == ticker)
        .order_by(Price.date.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def get_prices(
    session: Session, ticker: str, days: int = 30
) -> list[Price]:
    """Get price history for a ticker."""
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(Price)
        .where(Price.ticker == ticker, Price.date >= cutoff)
        .order_by(Price.date.desc())
    )
    return list(session.scalars(stmt))


def price_exists(session: Session, ticker: str, price_date: date) -> bool:
    """Check if a price record exists for ticker/date."""
    stmt = select(Price.id).where(Price.ticker == ticker, Price.date == price_date)
    return session.scalar(stmt) is not None


# Insider transaction operations
def save_insider_transaction(session: Session, txn: InsiderTransaction) -> int:
    """Save an insider transaction, returning its ID."""
    session.add(txn)
    session.flush()
    return txn.id


def get_insider_transactions(
    session: Session, ticker: str, days: int = 30
) -> list[InsiderTransaction]:
    """Get recent insider transactions for a ticker."""
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(InsiderTransaction)
        .where(InsiderTransaction.ticker == ticker, InsiderTransaction.trade_date >= cutoff)
        .order_by(InsiderTransaction.trade_date.desc())
    )
    return list(session.scalars(stmt))


def insider_transaction_exists(session: Session, sec_url: str) -> bool:
    """Check if an insider transaction already exists by SEC URL."""
    stmt = select(InsiderTransaction.id).where(InsiderTransaction.sec_url == sec_url)
    return session.scalar(stmt) is not None


# News operations
def save_news_item(session: Session, item: NewsItem) -> int:
    """Save a news item, returning its ID."""
    session.add(item)
    session.flush()
    return item.id


def news_exists(session: Session, url: str) -> bool:
    """Check if a news item exists by URL."""
    stmt = select(NewsItem.id).where(NewsItem.url == url)
    return session.scalar(stmt) is not None


def get_unclassified_news(session: Session, limit: int = 200) -> list[NewsItem]:
    """Ticker-tagged news items with no sentiment label yet (newest first).

    Ticker-less market wrap-ups are skipped: sentiment only becomes signal when it
    can be attributed to a name (directional confluence corroboration).
    """
    stmt = (
        select(NewsItem)
        .where(NewsItem.sentiment.is_(None), NewsItem.ticker.is_not(None))
        .order_by(NewsItem.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def get_recent_news(
    session: Session, ticker: str | None = None, hours: int = 24
) -> list[NewsItem]:
    """Get recent news items, optionally filtered by ticker."""
    cutoff = datetime.now() - timedelta(hours=hours)
    stmt = select(NewsItem).where(NewsItem.created_at >= cutoff)
    if ticker:
        stmt = stmt.where(NewsItem.ticker == ticker)
    stmt = stmt.order_by(NewsItem.created_at.desc())
    return list(session.scalars(stmt))


# Alert operations
# Earnings operations
# ETF operations

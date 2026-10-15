"""SQLAlchemy ORM models for all data types."""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Price(Base):
    """Daily price and volume data."""

    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=True)
    high: Mapped[float] = mapped_column(Float, nullable=True)
    low: Mapped[float] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    # Split/dividend-adjusted close (yfinance 'Adj Close'). Raw close is what trades.
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),
        Index("ix_price_ticker_date", "ticker", "date"),
    )


class InsiderTransaction(Base):
    """SEC Form 4 insider transactions."""

    __tablename__ = "insider_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_title: Mapped[str] = mapped_column(String(100), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Raw SEC Form 4 transaction code (P=open-market purchase, S=sale, A=award/grant,
    # M=option exercise, F=tax withholding, ...). transaction_type collapses these to
    # P/S for the legacy signal path; raw_code preserves the distinction so the
    # confluence engine can isolate GENUINE buys (P) from grants/exercises.
    raw_code: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    price_per_share: Mapped[float] = mapped_column(Float, nullable=True)
    total_value: Mapped[float] = mapped_column(Float, nullable=True)
    sec_url: Mapped[str] = mapped_column(String(500), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class NewsItem(Base):
    """News articles and headlines."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )



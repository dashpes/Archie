"""Fundamentals snapshots and the ticker score time series."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, DateTime, Float, Index, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func as sqlfunc

from .models import Base

if TYPE_CHECKING:
    from investment_monitor.analysis.scoring import ScoreCard


class FundamentalsSnapshot(Base):
    """A FundamentalsData payload as fetched on ``as_of``; scores are reproducible from it."""

    __tablename__ = "fundamentals_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=sqlfunc.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_fund_snapshot_ticker_asof"),)


class TickerScore(Base):
    """One score per ticker per day per scorer version."""

    __tablename__ = "ticker_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scorer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=sqlfunc.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("ticker", "as_of", "scorer_version", name="uq_ticker_score_day"),
        Index("ix_ticker_score_asof_composite", "as_of", "composite"),
    )


# --- snapshots -----------------------------------------------------------------------

def save_snapshot(session: Session, ticker: str, as_of: date, data: dict) -> FundamentalsSnapshot:
    """Insert or replace the snapshot for (ticker, as_of)."""
    ticker = ticker.upper()
    row = session.scalar(
        select(FundamentalsSnapshot).where(
            FundamentalsSnapshot.ticker == ticker, FundamentalsSnapshot.as_of == as_of
        )
    )
    if row is None:
        row = FundamentalsSnapshot(ticker=ticker, as_of=as_of, data=data)
        session.add(row)
    else:
        row.data = data
        row.fetched_at = datetime.now()
    session.flush()
    return row


def latest_snapshot(session: Session, ticker: str) -> FundamentalsSnapshot | None:
    stmt = (
        select(FundamentalsSnapshot)
        .where(FundamentalsSnapshot.ticker == ticker.upper())
        .order_by(FundamentalsSnapshot.as_of.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def stale_snapshot_tickers(
    session: Session, tickers: list[str], *, as_of: date, max_age_days: int, limit: int | None = None
) -> list[str]:
    """Tickers with no snapshot, or one older than ``max_age_days``; oldest first, then A-Z."""
    wanted = sorted({t.upper() for t in tickers})
    if not wanted:
        return []
    newest = (
        select(FundamentalsSnapshot.ticker, func.max(FundamentalsSnapshot.as_of).label("as_of"))
        .where(FundamentalsSnapshot.ticker.in_(wanted))
        .group_by(FundamentalsSnapshot.ticker)
    )
    have = {t: d for t, d in session.execute(newest)}
    cutoff = as_of - timedelta(days=max_age_days)
    stale = [(have.get(t), t) for t in wanted if have.get(t) is None or have[t] < cutoff]
    stale.sort(key=lambda pair: (pair[0] is not None, pair[0] or date.min, pair[1]))
    out = [t for _, t in stale]
    return out[:limit] if limit is not None else out


# --- scores ----------------------------------------------------------------------------

def upsert_score(session: Session, card: ScoreCard, *, version: int) -> TickerScore:
    row = session.scalar(
        select(TickerScore).where(
            TickerScore.ticker == card.ticker,
            TickerScore.as_of == card.as_of,
            TickerScore.scorer_version == version,
        )
    )
    if row is None:
        row = TickerScore(ticker=card.ticker, as_of=card.as_of, scorer_version=version)
        session.add(row)
    for name in ("value", "growth", "quality", "momentum", "sentiment", "composite"):
        setattr(row, name, getattr(card, name))
    row.breakdown = card.breakdown
    session.flush()
    return row


def latest_score(session: Session, ticker: str) -> TickerScore | None:
    stmt = (
        select(TickerScore)
        .where(TickerScore.ticker == ticker.upper())
        .order_by(TickerScore.as_of.desc(), TickerScore.scorer_version.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def top_scores(
    session: Session,
    *,
    limit: int = 20,
    min_composite: float | None = None,
    max_age_days: int | None = None,
    as_of: date | None = None,
) -> list[TickerScore]:
    """Each ticker's newest score, ranked composite desc then ticker asc (stable ties)."""
    newest = (
        select(TickerScore.ticker, func.max(TickerScore.as_of).label("as_of"))
        .group_by(TickerScore.ticker)
        .subquery()
    )
    stmt = (
        select(TickerScore)
        .join(newest, (TickerScore.ticker == newest.c.ticker) & (TickerScore.as_of == newest.c.as_of))
        .where(TickerScore.composite.is_not(None))
    )
    if min_composite is not None:
        stmt = stmt.where(TickerScore.composite >= min_composite)
    if max_age_days is not None:
        cutoff = (as_of or date.today()) - timedelta(days=max_age_days)
        stmt = stmt.where(TickerScore.as_of >= cutoff)
    stmt = stmt.order_by(TickerScore.composite.desc(), TickerScore.ticker.asc()).limit(limit)
    return list(session.scalars(stmt))

"""Tests for research CRUD operations."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from investment_monitor.storage.models import Base
from investment_monitor.storage.research_models import (
    CongressionalTrade,
    StockCandidate,
)
from investment_monitor.storage.research_operations import (
    get_candidate_by_ticker,
    get_trades_for_ticker,
    save_candidate,
    save_congressional_trade,
)


@pytest.fixture
def db_session():
    """Create a temporary in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestCandidateOperations:
    """Tests for StockCandidate CRUD operations."""

    def test_save_candidate(self, db_session):
        """Test saving a stock candidate."""
        candidate = StockCandidate(
            ticker="AAPL",
            discovery_source="congressional_trades",
            in_universe=True,
        )
        candidate_id = save_candidate(db_session, candidate)
        assert candidate_id is not None
        assert candidate.id == candidate_id

    def test_get_candidate_by_ticker(self, db_session):
        """Test getting candidate by ticker."""
        candidate = StockCandidate(ticker="MSFT", in_universe=True)
        save_candidate(db_session, candidate)
        db_session.commit()

        retrieved = get_candidate_by_ticker(db_session, "MSFT")
        assert retrieved is not None
        assert retrieved.ticker == "MSFT"

    def test_get_candidate_by_ticker_not_found(self, db_session):
        """Test getting non-existent candidate returns None."""
        result = get_candidate_by_ticker(db_session, "NONEXISTENT")
        assert result is None

class TestCongressionalTradeOperations:
    """Tests for CongressionalTrade CRUD operations."""

    def test_save_congressional_trade(self, db_session):
        """Test saving a congressional trade."""
        trade = CongressionalTrade(
            ticker="NVDA",
            politician="Nancy Pelosi",
            party="Democrat",
            chamber="House",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date(2026, 1, 10),
        )
        trade_id = save_congressional_trade(db_session, trade)
        assert trade_id is not None
        assert trade.id == trade_id

    def test_get_trades_for_ticker(self, db_session):
        """Test getting trades for a ticker."""
        # Create trades within date range
        trade1 = CongressionalTrade(
            ticker="AAPL",
            politician="Politician A",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date.today() - timedelta(days=30),
        )
        trade2 = CongressionalTrade(
            ticker="AAPL",
            politician="Politician B",
            trade_type="sell",
            amount_range="$15,001-$50,000",
            trade_date=date.today() - timedelta(days=60),
        )
        save_congressional_trade(db_session, trade1)
        save_congressional_trade(db_session, trade2)
        db_session.commit()

        trades = get_trades_for_ticker(db_session, "AAPL")
        assert len(trades) == 2

    def test_get_trades_for_ticker_date_filter(self, db_session):
        """Test that old trades are filtered out."""
        # Create recent trade
        recent = CongressionalTrade(
            ticker="MSFT",
            politician="Politician C",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date.today() - timedelta(days=30),
        )
        # Create old trade (beyond 90 days)
        old = CongressionalTrade(
            ticker="MSFT",
            politician="Politician D",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date.today() - timedelta(days=100),
        )
        save_congressional_trade(db_session, recent)
        save_congressional_trade(db_session, old)
        db_session.commit()

        trades = get_trades_for_ticker(db_session, "MSFT", days=90)
        assert len(trades) == 1
        assert trades[0].politician == "Politician C"

    def test_get_trades_for_ticker_custom_days(self, db_session):
        """Test custom days parameter."""
        trade = CongressionalTrade(
            ticker="GOOGL",
            politician="Politician E",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date.today() - timedelta(days=45),
        )
        save_congressional_trade(db_session, trade)
        db_session.commit()

        # Should find with 60-day window
        trades_60 = get_trades_for_ticker(db_session, "GOOGL", days=60)
        assert len(trades_60) == 1

        # Should not find with 30-day window
        trades_30 = get_trades_for_ticker(db_session, "GOOGL", days=30)
        assert len(trades_30) == 0

    def test_get_trades_for_ticker_not_found(self, db_session):
        """Test getting trades for ticker with no trades."""
        result = get_trades_for_ticker(db_session, "NONEXISTENT")
        assert result == []

    def test_get_trades_for_ticker_ordering(self, db_session):
        """Test that trades are ordered by date descending."""
        dates = [
            date.today() - timedelta(days=10),
            date.today() - timedelta(days=5),
            date.today() - timedelta(days=20),
        ]
        for i, trade_date in enumerate(dates):
            trade = CongressionalTrade(
                ticker="ORDER",
                politician=f"Politician {i}",
                trade_type="buy",
                amount_range="$1,001-$15,000",
                trade_date=trade_date,
            )
            save_congressional_trade(db_session, trade)
        db_session.commit()

        trades = get_trades_for_ticker(db_session, "ORDER")
        assert len(trades) == 3
        # Should be ordered by date descending (most recent first)
        assert trades[0].trade_date == date.today() - timedelta(days=5)
        assert trades[1].trade_date == date.today() - timedelta(days=10)
        assert trades[2].trade_date == date.today() - timedelta(days=20)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_special_characters_in_ticker(self, db_session):
        """Test handling tickers with special formats."""
        # Some tickers have dots (e.g., BRK.A, BRK.B)
        candidate = StockCandidate(ticker="BRK.A", in_universe=True)
        save_candidate(db_session, candidate)
        db_session.commit()

        retrieved = get_candidate_by_ticker(db_session, "BRK.A")
        assert retrieved is not None
        assert retrieved.ticker == "BRK.A"

    def test_flush_behavior(self, db_session):
        """Test that flush makes IDs available without commit."""
        candidate = StockCandidate(ticker="FLUSH")
        # Before save, ID should be None
        assert candidate.id is None

        candidate_id = save_candidate(db_session, candidate)
        # After save (with flush), ID should be available
        assert candidate.id is not None
        assert candidate.id == candidate_id

        # But not committed yet - can still rollback
        db_session.rollback()
        result = get_candidate_by_ticker(db_session, "FLUSH")
        assert result is None

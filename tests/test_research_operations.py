"""Tests for research CRUD operations."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from investment_monitor.storage.models import Base
from investment_monitor.storage.research_models import (
    CANDIDATE_STATUSES,
    CandidateScore,
    CongressionalTrade,
    StockCandidate,
)
from investment_monitor.storage.research_operations import (
    get_candidate_by_ticker,
    get_candidates_by_status,
    get_latest_score,
    get_score_history,
    get_top_candidates,
    get_trades_for_ticker,
    save_candidate,
    save_congressional_trade,
    save_score,
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
            status="discovered",
            composite_score=85.0,
        )
        candidate_id = save_candidate(db_session, candidate)
        assert candidate_id is not None
        assert candidate.id == candidate_id

    def test_get_candidate_by_ticker(self, db_session):
        """Test getting candidate by ticker."""
        candidate = StockCandidate(ticker="MSFT", status="screening")
        save_candidate(db_session, candidate)
        db_session.commit()

        retrieved = get_candidate_by_ticker(db_session, "MSFT")
        assert retrieved is not None
        assert retrieved.ticker == "MSFT"
        assert retrieved.status == "screening"

    def test_get_candidate_by_ticker_not_found(self, db_session):
        """Test getting non-existent candidate returns None."""
        result = get_candidate_by_ticker(db_session, "NONEXISTENT")
        assert result is None

    def test_get_candidates_by_status(self, db_session):
        """Test getting candidates by status."""
        # Create candidates with different statuses
        for i, status in enumerate(CANDIDATE_STATUSES[:3]):
            for j in range(2):
                candidate = StockCandidate(
                    ticker=f"TEST{i}_{j}",
                    status=status,
                )
                save_candidate(db_session, candidate)
        db_session.commit()

        # Get candidates by status
        discovered = get_candidates_by_status(db_session, "discovered")
        assert len(discovered) == 2

        screening = get_candidates_by_status(db_session, "screening")
        assert len(screening) == 2

    def test_get_candidates_by_status_with_limit(self, db_session):
        """Test limiting candidates by status."""
        for i in range(5):
            candidate = StockCandidate(ticker=f"LIM{i}", status="watchlist")
            save_candidate(db_session, candidate)
        db_session.commit()

        limited = get_candidates_by_status(db_session, "watchlist", limit=3)
        assert len(limited) == 3

    def test_get_candidates_by_status_empty(self, db_session):
        """Test getting candidates with status that has no matches."""
        result = get_candidates_by_status(db_session, "rejected")
        assert result == []

    def test_get_top_candidates(self, db_session):
        """Test getting top scoring candidates."""
        scores = [90.0, 85.0, 80.0, 75.0, 70.0]
        for i, score in enumerate(scores):
            candidate = StockCandidate(
                ticker=f"TOP{i}",
                status="researched",
                composite_score=score,
            )
            save_candidate(db_session, candidate)
        db_session.commit()

        top = get_top_candidates(db_session, limit=3)
        assert len(top) == 3
        assert top[0].composite_score == 90.0
        assert top[1].composite_score == 85.0
        assert top[2].composite_score == 80.0

    def test_get_top_candidates_with_min_score(self, db_session):
        """Test getting candidates above minimum score."""
        scores = [90.0, 75.0, 60.0, 45.0]
        for i, score in enumerate(scores):
            candidate = StockCandidate(
                ticker=f"MIN{i}",
                status="researched",
                composite_score=score,
            )
            save_candidate(db_session, candidate)
        db_session.commit()

        top = get_top_candidates(db_session, min_score=70.0)
        assert len(top) == 2
        assert all(c.composite_score >= 70.0 for c in top)

    def test_get_top_candidates_excludes_null_scores(self, db_session):
        """Test that candidates without scores are excluded."""
        candidate_with_score = StockCandidate(
            ticker="SCORED", composite_score=80.0
        )
        candidate_without_score = StockCandidate(
            ticker="UNSCORED", composite_score=None
        )
        save_candidate(db_session, candidate_with_score)
        save_candidate(db_session, candidate_without_score)
        db_session.commit()

        top = get_top_candidates(db_session)
        assert len(top) == 1
        assert top[0].ticker == "SCORED"


class TestScoreOperations:
    """Tests for CandidateScore CRUD operations."""

    def test_save_score(self, db_session):
        """Test saving a candidate score."""
        score = CandidateScore(
            ticker="AAPL",
            value_score=80.0,
            growth_score=75.0,
            quality_score=85.0,
            momentum_score=70.0,
            sentiment_score=90.0,
            composite_score=80.0,
        )
        score_id = save_score(db_session, score)
        assert score_id is not None
        assert score.id == score_id

    def test_get_latest_score(self, db_session):
        """Test getting latest score for a ticker."""
        score = CandidateScore(ticker="MSFT", composite_score=75.0)
        save_score(db_session, score)
        db_session.commit()

        retrieved = get_latest_score(db_session, "MSFT")
        assert retrieved is not None
        assert retrieved.ticker == "MSFT"
        assert retrieved.composite_score == 75.0

    def test_get_latest_score_not_found(self, db_session):
        """Test getting score for ticker with no scores."""
        result = get_latest_score(db_session, "NONEXISTENT")
        assert result is None

    def test_get_score_history(self, db_session):
        """Test getting score history for a ticker.

        Note: CandidateScore has a unique constraint on ticker, so in practice
        only one score per ticker is stored. This test verifies the operation
        works correctly with the constraint in place.
        """
        score = CandidateScore(
            ticker="HIST",
            composite_score=80.0,
            reasoning="Initial score",
        )
        save_score(db_session, score)
        db_session.commit()

        history = get_score_history(db_session, "HIST")
        assert len(history) == 1
        assert history[0].composite_score == 80.0

    def test_get_score_history_limit(self, db_session):
        """Test limiting score history."""
        # Create score
        score = CandidateScore(ticker="LIMSCORE", composite_score=85.0)
        save_score(db_session, score)
        db_session.commit()

        # Limit should work (returns 1 since unique constraint)
        history = get_score_history(db_session, "LIMSCORE", limit=5)
        assert len(history) == 1


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

    def test_empty_database_operations(self, db_session):
        """Test operations on empty database."""
        assert get_candidate_by_ticker(db_session, "NONE") is None
        assert get_latest_score(db_session, "NONE") is None
        assert get_candidates_by_status(db_session, "discovered") == []
        assert get_top_candidates(db_session) == []
        assert get_score_history(db_session, "NONE") == []
        assert get_trades_for_ticker(db_session, "NONE") == []

    def test_zero_limit(self, db_session):
        """Test operations with zero limit."""
        candidate = StockCandidate(ticker="ZERO", status="discovered")
        save_candidate(db_session, candidate)
        db_session.commit()

        # Zero limit should return empty list
        result = get_candidates_by_status(db_session, "discovered", limit=0)
        assert result == []

    def test_special_characters_in_ticker(self, db_session):
        """Test handling tickers with special formats."""
        # Some tickers have dots (e.g., BRK.A, BRK.B)
        candidate = StockCandidate(ticker="BRK.A", status="discovered")
        save_candidate(db_session, candidate)
        db_session.commit()

        retrieved = get_candidate_by_ticker(db_session, "BRK.A")
        assert retrieved is not None
        assert retrieved.ticker == "BRK.A"

    def test_null_optional_fields(self, db_session):
        """Test that optional fields can be null."""
        # Candidate with minimal required fields
        candidate = StockCandidate(ticker="MINIMAL")
        save_candidate(db_session, candidate)

        # Score with minimal required fields
        score = CandidateScore(ticker="MINIMAL")
        save_score(db_session, score)

        db_session.commit()

        # All should be saved successfully
        assert get_candidate_by_ticker(db_session, "MINIMAL") is not None
        assert get_latest_score(db_session, "MINIMAL") is not None

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

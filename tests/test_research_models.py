"""Tests for research database models."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investment_monitor.storage.models import Base
from investment_monitor.storage.research_models import (
    CANDIDATE_STATUSES,
    CandidateScore,
    CongressionalTrade,
    StockCandidate,
)


@pytest.fixture
def db_session():
    """Create a temporary in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestStockCandidate:
    """Tests for StockCandidate model."""

    def test_create_candidate(self, db_session):
        """Test creating a stock candidate."""
        candidate = StockCandidate(
            ticker="AAPL",
            discovery_source="congressional_trades",
            status="discovered",
            composite_score=75.5,
            notes="Strong buy signals from multiple congress members",
        )
        db_session.add(candidate)
        db_session.commit()

        retrieved = db_session.query(StockCandidate).filter_by(ticker="AAPL").first()
        assert retrieved is not None
        assert retrieved.discovery_source == "congressional_trades"
        assert retrieved.status == "discovered"
        assert retrieved.composite_score == 75.5

    def test_candidate_default_status(self, db_session):
        """Test that default status is 'discovered'."""
        candidate = StockCandidate(ticker="MSFT")
        db_session.add(candidate)
        db_session.commit()

        retrieved = db_session.query(StockCandidate).filter_by(ticker="MSFT").first()
        assert retrieved.status == "discovered"

    def test_candidate_unique_ticker_constraint(self, db_session):
        """Test that ticker must be unique."""
        candidate1 = StockCandidate(ticker="GOOGL")
        db_session.add(candidate1)
        db_session.commit()

        candidate2 = StockCandidate(ticker="GOOGL")
        db_session.add(candidate2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_candidate_valid_statuses(self):
        """Test that valid statuses are defined correctly."""
        expected = (
            "discovered",
            "screening",
            "researched",
            "watchlist",
            "rejected",
            "archived",
        )
        assert CANDIDATE_STATUSES == expected


class TestCandidateScore:
    """Tests for CandidateScore model."""

    def test_create_score(self, db_session):
        """Test creating a candidate score."""
        score = CandidateScore(
            ticker="AAPL",
            value_score=80.0,
            growth_score=75.0,
            quality_score=85.0,
            momentum_score=70.0,
            sentiment_score=90.0,
            composite_score=80.0,
            reasoning="Strong fundamentals with positive momentum",
        )
        db_session.add(score)
        db_session.commit()

        retrieved = db_session.query(CandidateScore).filter_by(ticker="AAPL").first()
        assert retrieved is not None
        assert retrieved.value_score == 80.0
        assert retrieved.growth_score == 75.0
        assert retrieved.quality_score == 85.0
        assert retrieved.momentum_score == 70.0
        assert retrieved.sentiment_score == 90.0
        assert retrieved.composite_score == 80.0

    def test_score_unique_ticker_constraint(self, db_session):
        """Test that ticker must be unique in scores."""
        score1 = CandidateScore(ticker="NVDA", value_score=85.0)
        db_session.add(score1)
        db_session.commit()

        score2 = CandidateScore(ticker="NVDA", value_score=90.0)
        db_session.add(score2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_score_range_values(self, db_session):
        """Test that scores can be in 0-100 range."""
        score = CandidateScore(
            ticker="TSLA",
            value_score=0.0,
            growth_score=100.0,
            quality_score=50.0,
        )
        db_session.add(score)
        db_session.commit()

        retrieved = db_session.query(CandidateScore).filter_by(ticker="TSLA").first()
        assert retrieved.value_score == 0.0
        assert retrieved.growth_score == 100.0
        assert retrieved.quality_score == 50.0


class TestCongressionalTrade:
    """Tests for CongressionalTrade model."""

    def test_create_trade(self, db_session):
        """Test creating a congressional trade."""
        trade = CongressionalTrade(
            ticker="NVDA",
            politician="Nancy Pelosi",
            party="Democrat",
            chamber="House",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date(2026, 1, 10),
            disclosure_date=date(2026, 1, 25),
            description="Purchase of NVDA stock",
            source_url="https://efdsearch.senate.gov/trade/123",
        )
        db_session.add(trade)
        db_session.commit()

        retrieved = db_session.query(CongressionalTrade).filter_by(politician="Nancy Pelosi").first()
        assert retrieved is not None
        assert retrieved.ticker == "NVDA"
        assert retrieved.amount_range == "$1,001-$15,000"
        assert retrieved.trade_type == "buy"

    def test_trade_amount_range_format(self, db_session):
        """Test that amount_range can store disclosure format strings."""
        ranges = [
            "$1,001-$15,000",
            "$15,001-$50,000",
            "$50,001-$100,000",
            "$100,001-$250,000",
            "$250,001-$500,000",
            "$500,001-$1,000,000",
            "Over $1,000,000",
        ]

        for i, amount_range in enumerate(ranges):
            trade = CongressionalTrade(
                ticker=f"TEST{i}",
                politician=f"Politician {i}",
                trade_type="buy",
                amount_range=amount_range,
                trade_date=date(2026, 1, i + 1),
            )
            db_session.add(trade)

        db_session.commit()

        trades = db_session.query(CongressionalTrade).all()
        assert len(trades) == len(ranges)

    def test_trade_unique_constraint(self, db_session):
        """Test that same trade cannot be recorded twice."""
        trade1 = CongressionalTrade(
            ticker="AAPL",
            politician="John Smith",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date(2026, 1, 20),
        )
        db_session.add(trade1)
        db_session.commit()

        trade2 = CongressionalTrade(
            ticker="AAPL",
            politician="John Smith",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date(2026, 1, 20),
        )
        db_session.add(trade2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_trade_same_politician_different_trades(self, db_session):
        """Test that same politician can have multiple different trades."""
        trade1 = CongressionalTrade(
            ticker="AAPL",
            politician="Jane Doe",
            trade_type="buy",
            amount_range="$1,001-$15,000",
            trade_date=date(2026, 1, 10),
        )
        trade2 = CongressionalTrade(
            ticker="MSFT",
            politician="Jane Doe",
            trade_type="sell",
            amount_range="$15,001-$50,000",
            trade_date=date(2026, 1, 15),
        )
        db_session.add(trade1)
        db_session.add(trade2)
        db_session.commit()

        trades = db_session.query(CongressionalTrade).filter_by(politician="Jane Doe").all()
        assert len(trades) == 2



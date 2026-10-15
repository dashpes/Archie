"""Tests for the fundamentals refresh and universe scoring jobs."""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from investment_monitor.collectors.fundamentals import FundamentalsData
from investment_monitor.config import Settings
from investment_monitor.models import ResearchConfig
from investment_monitor.research.discovery import refresh_fundamentals, score_universe
from investment_monitor.storage import (
    Price,
    StockCandidate,
    get_session,
    init_db,
    latest_score,
    latest_snapshot,
    save_snapshot,
)

D0 = date(2026, 10, 10)


def _settings(tmp_path):
    return Settings(_env_file=None, db_path=str(tmp_path / "d.db"))


def _seed_universe(tickers):
    with get_session() as s:
        for t in tickers:
            s.add(StockCandidate(ticker=t, discovery_source="test", in_universe=True))
        s.add(StockCandidate(ticker="GONE", discovery_source="test", in_universe=False))


def _prices(ticker, days=400):
    return [
        Price(ticker=ticker, date=D0 - timedelta(days=i), close=100.0 + i * 0.05, adj_close=100.0 + i * 0.05)
        for i in range(days)
    ]


def test_refresh_fetches_stale_members_oldest_first_and_caps(tmp_path):
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _seed_universe(["AAA", "BBB", "CCC"])
    with get_session() as s:
        save_snapshot(s, "BBB", D0 - timedelta(days=1), {"ticker": "BBB"})   # fresh
        save_snapshot(s, "CCC", D0 - timedelta(days=30), {"ticker": "CCC"})  # stale
    cfg = ResearchConfig(fundamentals_max_age_days=7, fundamentals_per_run=1)
    fetch = AsyncMock(side_effect=lambda t: FundamentalsData(ticker=t, pe_ratio=11.0))
    with patch("investment_monitor.research.discovery.FundamentalsCollector.get_fundamentals", fetch), get_session() as s:
        result = asyncio.run(refresh_fundamentals(s, settings, cfg, as_of=D0))
    assert (result.requested, result.fetched) == (1, 1)
    fetch.assert_awaited_once_with("AAA")     # missing before stale, A-Z
    with get_session() as s:
        assert latest_snapshot(s, "AAA").data["pe_ratio"] == 11.0
        assert latest_snapshot(s, "GONE") is None


def test_refresh_survives_one_failed_fetch(tmp_path):
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _seed_universe(["AAA", "BBB"])
    fetch = AsyncMock(side_effect=[RuntimeError("yf down"), FundamentalsData(ticker="BBB")])
    with patch("investment_monitor.research.discovery.FundamentalsCollector.get_fundamentals", fetch), get_session() as s:
        result = asyncio.run(refresh_fundamentals(s, settings, ResearchConfig(), as_of=D0))
    assert result.fetched == 1 and result.errors and "AAA" in result.errors[0]


def test_score_universe_scores_every_member_and_filters_after_snapshot(tmp_path):
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _seed_universe(["AAA", "SMALL", "NOSNAP"])
    with get_session() as s:
        s.add_all(_prices("AAA"))
        save_snapshot(s, "AAA", D0, FundamentalsData(ticker="AAA", pe_ratio=12.0, roe=0.2, revenue_growth_yoy=0.1, market_cap=5e9).model_dump(mode="json"))
        save_snapshot(s, "SMALL", D0, FundamentalsData(ticker="SMALL", pe_ratio=12.0, market_cap=1e6).model_dump(mode="json"))
    cfg = ResearchConfig()
    with get_session() as s:
        first = score_universe(s, cfg, as_of=D0)
        second = score_universe(s, cfg, as_of=D0)       # same day again: idempotent
    assert (first.universe, first.scored, first.filtered, first.no_snapshot) == (3, 1, 1, 1)
    assert first.top and first.top[0][0] == "AAA"
    assert second.scored == 1
    with get_session() as s:
        row = latest_score(s, "AAA")
        assert row.as_of == D0 and row.composite is not None and row.momentum is not None
        assert latest_score(s, "SMALL") is None

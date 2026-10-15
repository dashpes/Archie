"""Tests for fundamentals snapshots and the ticker score table."""

from datetime import date, timedelta

from investment_monitor.analysis.scoring import ScoreCard
from investment_monitor.storage import (
    TickerScore,
    get_session,
    init_db,
    latest_score,
    latest_snapshot,
    save_snapshot,
    stale_snapshot_tickers,
    top_scores,
    upsert_score,
)

D0 = date(2026, 10, 10)


def _card(ticker, as_of, composite):
    return ScoreCard(ticker, as_of, 50.0, 50.0, 50.0, 50.0, 50.0, composite, {"k": 1})


def test_snapshot_upsert_and_latest(tmp_path):
    init_db(tmp_path / "s.db")
    with get_session() as s:
        save_snapshot(s, "aaa", D0, {"pe_ratio": 10})
        save_snapshot(s, "AAA", D0, {"pe_ratio": 12})          # same day -> replaced
        save_snapshot(s, "AAA", D0 - timedelta(days=9), {"pe_ratio": 9})
    with get_session() as s:
        assert latest_snapshot(s, "AAA").data == {"pe_ratio": 12}


def test_stale_snapshot_tickers_orders_missing_then_oldest_then_az(tmp_path):
    init_db(tmp_path / "s.db")
    with get_session() as s:
        save_snapshot(s, "OLD", D0 - timedelta(days=30), {})
        save_snapshot(s, "FRESH", D0 - timedelta(days=1), {})
        save_snapshot(s, "MID", D0 - timedelta(days=10), {})
        stale = stale_snapshot_tickers(s, ["ZZZ", "MID", "AAA", "OLD", "FRESH"], as_of=D0, max_age_days=7)
    assert stale == ["AAA", "ZZZ", "OLD", "MID"]
    with get_session() as s:
        assert stale_snapshot_tickers(s, ["ZZZ", "AAA", "OLD"], as_of=D0, max_age_days=7, limit=2) == ["AAA", "ZZZ"]


def test_upsert_score_is_idempotent_per_day(tmp_path):
    init_db(tmp_path / "s.db")
    with get_session() as s:
        upsert_score(s, _card("AAA", D0, 60.0), version=1)
        upsert_score(s, _card("AAA", D0, 65.0), version=1)
        upsert_score(s, _card("AAA", D0 - timedelta(days=1), 55.0), version=1)
    with get_session() as s:
        rows = s.query(TickerScore).filter_by(ticker="AAA").count()
        assert rows == 2
        assert latest_score(s, "AAA").composite == 65.0


def test_top_scores_uses_newest_per_ticker_and_breaks_ties_az(tmp_path):
    init_db(tmp_path / "s.db")
    with get_session() as s:
        upsert_score(s, _card("BBB", D0, 80.0), version=1)
        upsert_score(s, _card("AAA", D0, 80.0), version=1)
        upsert_score(s, _card("CCC", D0 - timedelta(days=1), 99.0), version=1)   # stale high
        upsert_score(s, _card("CCC", D0, 70.0), version=1)
        upsert_score(s, _card("NUL", D0, None), version=1)
    with get_session() as s:
        got = [(r.ticker, r.composite) for r in top_scores(s, limit=10)]
        assert got == [("AAA", 80.0), ("BBB", 80.0), ("CCC", 70.0)]
        assert [r.ticker for r in top_scores(s, min_composite=75)] == ["AAA", "BBB"]
        assert [r.ticker for r in top_scores(s, max_age_days=0, as_of=D0)] == ["AAA", "BBB", "CCC"]
        assert top_scores(s, max_age_days=0, as_of=D0 + timedelta(days=1)) == []

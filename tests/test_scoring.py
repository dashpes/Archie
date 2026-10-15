"""Tests for the deterministic numeric scorer."""

from dataclasses import dataclass
from datetime import date, timedelta

from investment_monitor.analysis import scoring_bands as bands
from investment_monitor.analysis.scoring import (
    band_score,
    composite_score,
    factor_score,
    momentum_inputs,
    passes_filters,
    score_ticker,
    sentiment_inputs,
    value_score,
)
from investment_monitor.collectors.fundamentals import FundamentalsData
from investment_monitor.models import ScoringWeights, UniverseConfig

AS_OF = date(2026, 10, 10)


@dataclass
class _P:
    date: date
    close: float
    adj_close: float | None = None


@dataclass
class _Txn:
    raw_code: str
    owner_name: str


@dataclass
class _News:
    sentiment: str | None


def _series(days: int, start: float, end: float, *, adj_scale: float | None = None) -> list[_P]:
    """Newest-first daily closes moving linearly from start (oldest) to end (newest)."""
    out = []
    for i in range(days):
        d = AS_OF - timedelta(days=i)
        px = end - (end - start) * i / max(days - 1, 1)
        out.append(_P(d, px, px * adj_scale if adj_scale else None))
    return out


def _fund(**kw) -> FundamentalsData:
    return FundamentalsData(ticker="AAA", **kw)


# --- bands ------------------------------------------------------------------------

def test_band_score_clips_and_handles_reversed_bands():
    assert band_score(10.0, 40.0, 10.0) == 100.0   # P/E at the "best" edge
    assert band_score(40.0, 40.0, 10.0) == 0.0
    assert band_score(25.0, 40.0, 10.0) == 50.0
    assert band_score(5.0, 40.0, 10.0) == 100.0    # beyond best clips
    assert band_score(0.25, 0.0, 0.25) == 100.0    # ROE upward band
    assert band_score(-1.0, 0.0, 0.25) == 0.0


def test_factor_score_is_mean_of_present_metrics_and_none_when_empty():
    assert factor_score({"roe": 0.25, "profit_margin": None}, bands.QUALITY) == 100.0
    assert factor_score({"roe": None}, bands.QUALITY) is None


def test_value_score_treats_negative_pe_as_zero_and_ignores_negative_peg():
    assert value_score(_fund(pe_ratio=-5.0)) == 0.0
    assert value_score(_fund(peg_ratio=-2.0)) is None
    assert value_score(_fund(pe_ratio=10.0, peg_ratio=1.0)) == 100.0


def test_units_match_yfinance():
    """Fractions for growth/ROE/margins, percent for debt_to_equity."""
    f = _fund(revenue_growth_yoy=0.25, roe=0.25, profit_margin=0.20, debt_to_equity=0.0)
    card = score_ticker(f, as_of=AS_OF, prices=[], insider_txns=[], news_items=[], weights=ScoringWeights())
    assert card.growth == 100.0 and card.quality == 100.0


# --- composite -----------------------------------------------------------------------

def test_composite_needs_three_factors_and_renormalises_weights():
    w = ScoringWeights(value=0.4, growth=0.4, quality=0.1, momentum=0.05, sentiment=0.05)
    assert composite_score({"value": 100.0, "growth": 0.0, "quality": None, "momentum": None, "sentiment": None}, w) is None
    got = composite_score({"value": 100.0, "growth": 0.0, "quality": 50.0, "momentum": None, "sentiment": None}, w)
    assert round(got, 4) == round((0.4 * 100 + 0.4 * 0 + 0.1 * 50) / 0.9, 4)


# --- momentum ------------------------------------------------------------------------

def test_momentum_inputs_from_long_history():
    prices = _series(400, 100.0, 120.0)
    m = momentum_inputs(prices, as_of=AS_OF)
    assert m["price_change_1y"] is not None and m["price_change_1y"] > 0
    assert m["vs_52w_high"] == 0.0  # today is the high


def test_momentum_inputs_degrade_to_none_on_short_history():
    m = momentum_inputs(_series(30, 100.0, 110.0), as_of=AS_OF)
    assert m == {"price_change_3m": None, "price_change_6m": None, "price_change_1y": None, "vs_52w_high": None}


def test_momentum_prefers_adjusted_close():
    raw = _series(400, 100.0, 100.0, adj_scale=0.5)      # flat raw, but adj is half -> still flat
    assert momentum_inputs(raw, as_of=AS_OF)["price_change_1y"] == 0.0


# --- sentiment ------------------------------------------------------------------------

def test_sentiment_inputs_count_distinct_actors_and_need_three_labels():
    txns = [_Txn("P", "a"), _Txn("P", "a"), _Txn("P", "b"), _Txn("S", "c"), _Txn("A", "d")]
    s = sentiment_inputs(txns, [_News("bullish"), _News("bearish")])
    assert s == {"insider_net_buyers": 1.0, "news_ratio": None}
    s = sentiment_inputs([], [_News("bullish"), _News("bullish"), _News("neutral"), _News(None)])
    assert s["insider_net_buyers"] is None and round(s["news_ratio"], 4) == round(2 / 3, 4)


# --- filters and determinism ----------------------------------------------------------

def test_passes_filters_after_snapshot():
    u = UniverseConfig(min_market_cap=1_000, excluded_sectors=["Energy"], excluded_tickers=["bad"])
    assert passes_filters(_fund(market_cap=5_000, sector="Tech"), u)
    assert not passes_filters(_fund(market_cap=500), u)
    assert not passes_filters(_fund(sector="energy"), u)
    assert not passes_filters(FundamentalsData(ticker="BAD"), u)


def test_same_inputs_same_score():
    f = _fund(pe_ratio=15.0, revenue_growth_yoy=0.1, roe=0.15, market_cap=1e9, free_cash_flow=3e7)
    prices = _series(400, 90.0, 100.0)
    kw = dict(as_of=AS_OF, prices=prices, insider_txns=[_Txn("P", "x")], news_items=[], weights=ScoringWeights())
    a, b = score_ticker(f, **kw), score_ticker(f, **kw)
    assert a == b and a.composite is not None
    assert set(a.breakdown) == {"value", "growth", "quality", "momentum", "sentiment"}

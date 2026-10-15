"""Deterministic numeric scoring of one ticker from stored data.

Five factors (value, growth, quality, momentum, sentiment), each the mean of its
available metrics after mapping through an absolute band, then a weighted mean
over the factors present. Nothing here reads the clock or the network: given the
same snapshot, prices, insider rows and news rows, the score is the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from investment_monitor.analysis import scoring_bands as bands
from investment_monitor.collectors.fundamentals import FundamentalsData
from investment_monitor.models import ScoringWeights, UniverseConfig

FACTORS = ("value", "growth", "quality", "momentum", "sentiment")


@dataclass(frozen=True)
class ScoreCard:
    ticker: str
    as_of: date
    value: float | None
    growth: float | None
    quality: float | None
    momentum: float | None
    sentiment: float | None
    composite: float | None
    breakdown: dict = field(default_factory=dict)

    def factor(self, name: str) -> float | None:
        return getattr(self, name)


# --- band math -----------------------------------------------------------------

def band_score(x: float, worst: float, best: float) -> float:
    """Linear map of ``x`` from [worst, best] onto [0, 100], clipped. Works both ways."""
    if best == worst:
        return 100.0 if x == best else 0.0
    t = (x - worst) / (best - worst)
    return max(0.0, min(100.0, t * 100.0))


def factor_score(metrics: dict[str, float | None], table: dict[str, bands.Band]) -> float | None:
    """Mean band score over the metrics present; None when none are present."""
    scores = [
        band_score(v, *table[k]) for k, v in metrics.items() if k in table and v is not None
    ]
    return sum(scores) / len(scores) if scores else None


def composite_score(factors: dict[str, float | None], weights: ScoringWeights) -> float | None:
    """Weight-normalised mean over present factors; None below MIN_FACTORS."""
    present = {k: v for k, v in factors.items() if v is not None}
    if len(present) < bands.MIN_FACTORS:
        return None
    total_w = sum(getattr(weights, k) for k in present)
    if total_w <= 0:
        return None
    return sum(getattr(weights, k) * v for k, v in present.items()) / total_w


# --- inputs ------------------------------------------------------------------------

def value_inputs(f: FundamentalsData) -> dict[str, float | None]:
    pe = f.pe_ratio
    peg = f.peg_ratio if (f.peg_ratio is not None and f.peg_ratio > 0) else None
    return {
        "pe_ratio": pe,
        "pb_ratio": f.pb_ratio,
        "ps_ratio": f.ps_ratio,
        "peg_ratio": peg,
    }


def value_score(f: FundamentalsData) -> float | None:
    metrics = value_inputs(f)
    pe = metrics.pop("pe_ratio")
    scores = [band_score(v, *bands.VALUE[k]) for k, v in metrics.items() if v is not None]
    if pe is not None:
        scores.append(0.0 if pe <= 0 else band_score(pe, *bands.VALUE["pe_ratio"]))
    return sum(scores) / len(scores) if scores else None


def growth_inputs(f: FundamentalsData) -> dict[str, float | None]:
    return {
        "revenue_growth_yoy": f.revenue_growth_yoy,
        "revenue_growth_3y": f.revenue_growth_3y,
        "eps_growth_yoy": f.eps_growth_yoy,
        "eps_growth_3y": f.eps_growth_3y,
    }


def quality_inputs(f: FundamentalsData) -> dict[str, float | None]:
    fcf_yield = None
    if f.free_cash_flow is not None and f.market_cap and f.market_cap > 0:
        fcf_yield = f.free_cash_flow / f.market_cap
    return {
        "roe": f.roe,
        "profit_margin": f.profit_margin,
        "debt_to_equity": f.debt_to_equity,
        "current_ratio": f.current_ratio,
        "fcf_yield": fcf_yield,
    }


def _close_on_or_before(prices: list, target: date) -> float | None:
    for p in prices:  # newest first
        if p.date <= target and p.close:
            return float(p.close)
    return None


def momentum_inputs(prices: list, *, as_of: date) -> dict[str, float | None]:
    """Percent changes and 52-week position from stored daily prices (newest first).

    Uses the adjusted close when present so splits and dividends do not fake a move.
    Every field degrades to None when history is too short.
    """
    out: dict[str, float | None] = {
        "price_change_3m": None, "price_change_6m": None,
        "price_change_1y": None, "vs_52w_high": None,
    }
    priced = [p for p in prices if p.close and p.date <= as_of]
    if not priced:
        return out

    def _px(p) -> float:
        return float(p.adj_close if getattr(p, "adj_close", None) else p.close)

    latest = _px(priced[0])
    oldest = min(p.date for p in priced)
    for key, span in (("price_change_3m", 91), ("price_change_6m", 182), ("price_change_1y", 365)):
        target = as_of - timedelta(days=span)
        if oldest > target:
            continue
        base = next((_px(p) for p in priced if p.date <= target), None)
        if base and base > 0:
            out[key] = (latest / base - 1.0) * 100.0
    if (as_of - oldest).days >= 300:
        year = [_px(p) for p in priced if p.date >= as_of - timedelta(days=365)]
        if year:
            out["vs_52w_high"] = (latest / max(year) - 1.0) * 100.0
    return out


def sentiment_inputs(insider_txns: list, news_items: list) -> dict[str, float | None]:
    """Distinct open-market buyers minus sellers (90d) and the labeled-news ratio (14d)."""
    buyers = {t.owner_name for t in insider_txns if t.raw_code == "P"}
    sellers = {t.owner_name for t in insider_txns if t.raw_code == "S"}
    net: float | None = float(len(buyers) - len(sellers)) if (buyers or sellers) else None
    labeled = [n.sentiment for n in news_items if n.sentiment in ("bullish", "bearish", "neutral")]
    ratio: float | None = None
    if len(labeled) >= 3:
        ratio = (labeled.count("bullish") - labeled.count("bearish")) / len(labeled)
    return {"insider_net_buyers": net, "news_ratio": ratio}


# --- the score -----------------------------------------------------------------------

def passes_filters(f: FundamentalsData, universe: UniverseConfig) -> bool:
    """Universe filters applied after the snapshot is read, so they actually bite."""
    if f.ticker.upper() in {t.upper() for t in universe.excluded_tickers}:
        return False
    if f.market_cap is not None and f.market_cap < universe.min_market_cap:
        return False
    if f.sector and f.sector.lower() in {s.lower() for s in universe.excluded_sectors}:
        return False
    return True


def score_ticker(
    fundamentals: FundamentalsData,
    *,
    as_of: date,
    prices: list,
    insider_txns: list,
    news_items: list,
    weights: ScoringWeights,
) -> ScoreCard:
    momentum = momentum_inputs(prices, as_of=as_of)
    sentiment = sentiment_inputs(insider_txns, news_items)
    growth = growth_inputs(fundamentals)
    quality = quality_inputs(fundamentals)
    factors = {
        "value": value_score(fundamentals),
        "growth": factor_score(growth, bands.GROWTH),
        "quality": factor_score(quality, bands.QUALITY),
        "momentum": factor_score(momentum, bands.MOMENTUM),
        "sentiment": factor_score(sentiment, bands.SENTIMENT),
    }
    return ScoreCard(
        ticker=fundamentals.ticker.upper(),
        as_of=as_of,
        composite=composite_score(factors, weights),
        breakdown={
            "value": value_inputs(fundamentals), "growth": growth, "quality": quality,
            "momentum": momentum, "sentiment": sentiment,
        },
        **factors,
    )

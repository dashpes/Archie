"""Absolute scoring bands: (worst, best) per metric, mapped linearly to 0-100.

Bands are absolute, not percentile ranks, so a name's score depends only on
its own data and can be reproduced from one snapshot. Units follow yfinance:
growth, ROE and margins are fractions; debtToEquity is a percent; price
changes are percents. Recalibrate an edge here only when the observed
distribution bunches (most names between 40 and 60).
"""

from __future__ import annotations

Band = tuple[float, float]  # (worst, best); best may be below worst for "lower is better"

SCORER_VERSION = 1
MIN_FACTORS = 3  # a composite needs at least this many factors present

VALUE: dict[str, Band] = {
    "pe_ratio": (40.0, 10.0),
    "pb_ratio": (8.0, 1.0),
    "ps_ratio": (10.0, 1.0),
    "peg_ratio": (3.0, 1.0),
}

GROWTH: dict[str, Band] = {
    "revenue_growth_yoy": (-0.05, 0.25),
    "revenue_growth_3y": (-0.05, 0.25),
    "eps_growth_yoy": (-0.10, 0.30),
    "eps_growth_3y": (-0.10, 0.30),
}

QUALITY: dict[str, Band] = {
    "roe": (0.0, 0.25),
    "profit_margin": (0.0, 0.20),
    "debt_to_equity": (200.0, 0.0),  # yfinance reports percent
    "current_ratio": (0.8, 2.0),
    "fcf_yield": (0.0, 0.06),  # free_cash_flow / market_cap
}

MOMENTUM: dict[str, Band] = {  # percents
    "price_change_3m": (-10.0, 20.0),
    "price_change_6m": (-20.0, 30.0),
    "price_change_1y": (-25.0, 40.0),
    "vs_52w_high": (-30.0, 0.0),
}

SENTIMENT: dict[str, Band] = {
    "insider_net_buyers": (-3.0, 3.0),  # distinct open-market buyers minus sellers, 90d
    "news_ratio": (-1.0, 1.0),  # (bullish - bearish) / labeled headlines, 14d, n >= 3
}

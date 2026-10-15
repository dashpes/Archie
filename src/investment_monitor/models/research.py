"""Research configuration models."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ScoringWeights(BaseModel):
    """Weights for composite score calculation.

    Each weight represents the importance of that factor in the overall
    investment decision. All weights must be between 0 and 1, and the
    total must sum to 1.0 (with small floating point tolerance).
    """

    value: float = Field(default=0.2, ge=0, le=1)
    growth: float = Field(default=0.2, ge=0, le=1)
    quality: float = Field(default=0.2, ge=0, le=1)
    momentum: float = Field(default=0.2, ge=0, le=1)
    sentiment: float = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def check_weights_sum(self) -> "ScoringWeights":
        """Validate that all weights sum to 1.0."""
        total = self.value + self.growth + self.quality + self.momentum + self.sentiment
        if not (0.99 <= total <= 1.01):  # Allow small floating point tolerance
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


class UniverseConfig(BaseModel):
    """Configuration for the stock universe to screen.

    Controls which stocks are included in the research universe
    for discovery and screening.
    """

    include_sp500: bool = True
    include_nasdaq100: bool = True
    min_market_cap: int = Field(default=1_000_000_000, ge=0)  # $1B minimum
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)


class ResearchThresholds(BaseModel):
    """Score thresholds used by the research CLI's ``top`` listing."""

    min_composite_score: float = Field(default=60.0, ge=0, le=100)


class ResearchConfig(BaseModel):
    """Main research configuration containing all research-related settings.

    This configuration controls:
    - Scoring weights for investment analysis
    - Universe of stocks to screen
    - Thresholds for automated decisions
    """

    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    thresholds: ResearchThresholds = Field(default_factory=ResearchThresholds)
    # A snapshot older than this is refreshed; at most this many fetches per run.
    fundamentals_max_age_days: int = Field(default=7, ge=1, le=90)
    fundamentals_per_run: int = Field(default=150, ge=1, le=2000)

    @classmethod
    def from_yaml(cls, path: Path) -> "ResearchConfig":
        """Load research config from YAML file.

        The YAML can contain partial configuration - any missing fields
        will use their default values.
        """
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

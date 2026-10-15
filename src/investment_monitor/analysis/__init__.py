"""Analysis module: local LLM helpers and research scoring."""

from .local_llm import LocalLLM
from .news_processor import classify_unscored_sentiment
from .prompts import SENTIMENT_PROMPT
from .research_prompts import (
    GROWTH_SCORE_PROMPT,
    MOMENTUM_SCORE_PROMPT,
    PROMPT_PLACEHOLDERS,
    QUALITY_SCORE_PROMPT,
    RESEARCH_PROMPTS,
    SENTIMENT_SCORE_PROMPT,
    VALUE_SCORE_PROMPT,
)
from .research_scorer import ResearchScorer, ScoreResult
from .sentiment import SentimentLabeler, build_labeler

__all__ = [
    "LocalLLM",
    "classify_unscored_sentiment",
    "SENTIMENT_PROMPT",
    "VALUE_SCORE_PROMPT",
    "GROWTH_SCORE_PROMPT",
    "QUALITY_SCORE_PROMPT",
    "MOMENTUM_SCORE_PROMPT",
    "SENTIMENT_SCORE_PROMPT",
    "RESEARCH_PROMPTS",
    "PROMPT_PLACEHOLDERS",
    "ResearchScorer",
    "ScoreResult",
    "SentimentLabeler",
    "build_labeler",
]

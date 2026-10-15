"""Prompt templates for local LLM analysis tasks."""

SENTIMENT_PROMPT = """Classify the sentiment of this financial news headline.

Headline: {headline}

Is this news bullish (positive for stock price), bearish (negative for stock price), or neutral?

Respond with ONLY one word: bullish, bearish, or neutral

Sentiment:"""

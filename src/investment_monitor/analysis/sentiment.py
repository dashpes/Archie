"""Pluggable headline sentiment labelers.

One small interface, three implementations: a local Ollama model, Claude Haiku
over the Anthropic API, and a no-op. A label is written once and never
re-labeled, so the LLM output becomes a stored input and everything downstream
stays deterministic given the database. ``None`` means "no label this pass";
the row stays NULL and is retried next time.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from .local_llm import LocalLLM, resolve_installed_model

if TYPE_CHECKING:
    from investment_monitor.config import Settings

LABELS = ("bullish", "bearish", "neutral")

_BATCH_PROMPT = """Classify the sentiment of each financial news headline for the stock it is about.

Reply with ONLY a JSON array of strings, one per headline, in order. Each string must be
exactly one of: "bullish", "bearish", "neutral".

Headlines:
{headlines}
"""


class SentimentLabeler(Protocol):
    name: str

    def label(self, headlines: list[str]) -> list[str | None]: ...


class OllamaLabeler:
    """One prompt per headline against the local model."""

    name = "ollama"

    def __init__(self, llm: LocalLLM) -> None:
        self.llm = llm

    def label(self, headlines: list[str]) -> list[str | None]:
        if not headlines or not self.llm.is_available():
            return [None] * len(headlines)
        out: list[str | None] = []
        for headline in headlines:
            try:
                sentiment = self.llm.sentiment(headline)
            except Exception as exc:  # noqa: BLE001 - one bad headline must not abort the batch
                logger.debug("ollama sentiment failed: {e}", e=exc)
                sentiment = "unknown"
            out.append(sentiment if sentiment in LABELS else None)
        return out


class AnthropicLabeler:
    """One request per ``batch_size`` headlines, answered as a JSON array."""

    name = "anthropic"

    def __init__(self, client, model: str, *, batch_size: int = 50) -> None:
        self.client = client
        self.model = model
        self.batch_size = batch_size

    def label(self, headlines: list[str]) -> list[str | None]:
        out: list[str | None] = []
        for start in range(0, len(headlines), self.batch_size):
            batch = headlines[start : start + self.batch_size]
            out.extend(self._label_batch(batch))
        return out

    def _label_batch(self, batch: list[str]) -> list[str | None]:
        numbered = "\n".join(f"{i + 1}. {h.strip()}" for i, h in enumerate(batch))
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": _BATCH_PROMPT.format(headlines=numbered)}],
            )
        except Exception as exc:  # noqa: BLE001 - never let the API break collection
            logger.warning("anthropic sentiment request failed: {e}", e=exc)
            return [None] * len(batch)
        if getattr(response, "stop_reason", None) == "refusal":
            logger.warning("anthropic sentiment request refused")
            return [None] * len(batch)
        text = "".join(getattr(b, "text", "") for b in response.content)
        return parse_label_array(text, len(batch))


class NoneLabeler:
    name = "none"

    def label(self, headlines: list[str]) -> list[str | None]:
        return [None] * len(headlines)


def parse_label_array(text: str, expected: int) -> list[str | None]:
    """Parse a JSON array of labels; anything malformed or mis-sized yields all None."""
    match = re.search(r"\[.*\]", text, flags=re.S)
    if not match:
        return [None] * expected
    try:
        values = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [None] * expected
    if not isinstance(values, list) or len(values) != expected:
        return [None] * expected
    return [v.lower() if isinstance(v, str) and v.lower() in LABELS else None for v in values]


def build_labeler(settings: Settings) -> SentimentLabeler:
    """Pick the labeler from ``Settings.news_llm``."""
    mode = (settings.news_llm or "none").lower()
    if mode == "ollama":
        model = resolve_installed_model(settings.ollama_model, settings.ollama_host)
        return OllamaLabeler(LocalLLM(model=model, base_url=settings.ollama_host))
    if mode == "anthropic":
        from anthropic import Anthropic

        return AnthropicLabeler(Anthropic(api_key=settings.anthropic_api_key or None), settings.anthropic_model)
    if mode == "none":
        return NoneLabeler()
    raise ValueError(f"NEWS_LLM must be ollama, anthropic or none, got {settings.news_llm!r}")

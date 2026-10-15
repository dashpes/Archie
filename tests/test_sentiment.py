"""Tests for the pluggable sentiment labelers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from investment_monitor.analysis.sentiment import (
    AnthropicLabeler,
    NoneLabeler,
    OllamaLabeler,
    build_labeler,
    parse_label_array,
)

HEADS = ["Record earnings", "SEC probe widens", "Analyst day scheduled"]


# --- parsing ------------------------------------------------------------------------

def test_parse_label_array_accepts_json_with_noise():
    text = 'Sure:\n["Bullish", "bearish", "neutral"]\n'
    assert parse_label_array(text, 3) == ["bullish", "bearish", "neutral"]


@pytest.mark.parametrize("text", ["nope", "[1, 2, 3]", '["bullish"]', '["bullish", "bad", "x"'])
def test_parse_label_array_rejects_malformed_or_missized(text):
    assert parse_label_array(text, 3) == [None, None, None]


def test_parse_label_array_keeps_only_known_labels():
    assert parse_label_array('["bullish", "meh", "neutral"]', 3) == ["bullish", None, "neutral"]


# --- Ollama ------------------------------------------------------------------------

def test_ollama_labeler_maps_unknown_to_none():
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.sentiment.side_effect = ["bullish", "unknown", "neutral"]
    assert OllamaLabeler(llm).label(HEADS) == ["bullish", None, "neutral"]


def test_ollama_labeler_is_all_none_when_model_down():
    llm = MagicMock()
    llm.is_available.return_value = False
    assert OllamaLabeler(llm).label(HEADS) == [None, None, None]
    llm.sentiment.assert_not_called()


# --- Anthropic ----------------------------------------------------------------------

def _client(text: str, stop_reason: str = "end_turn"):
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)],
    )
    return client


def test_anthropic_labeler_sends_one_request_per_batch_at_low_effort():
    client = MagicMock()
    client.messages.create.side_effect = [
        SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(text='["bullish", "bearish"]')]),
        SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(text='["neutral"]')]),
    ]
    labeler = AnthropicLabeler(client, "claude-haiku-5-5", batch_size=2)
    assert labeler.label(HEADS) == ["bullish", "bearish", "neutral"]
    assert client.messages.create.call_count == 2
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_config"] == {"effort": "low"}


def test_anthropic_labeler_parse_failure_leaves_none():
    assert AnthropicLabeler(_client("garbage"), "m").label(HEADS) == [None, None, None]


def test_anthropic_labeler_refusal_leaves_none():
    client = _client('["bullish", "bearish", "neutral"]', stop_reason="refusal")
    assert AnthropicLabeler(client, "m").label(HEADS) == [None, None, None]


def test_anthropic_labeler_api_error_leaves_none():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("429")
    assert AnthropicLabeler(client, "m").label(HEADS) == [None, None, None]


# --- selection ---------------------------------------------------------------------

def test_build_labeler_none_and_invalid():
    assert isinstance(build_labeler(SimpleNamespace(news_llm="none")), NoneLabeler)
    with pytest.raises(ValueError):
        build_labeler(SimpleNamespace(news_llm="gpt"))


def test_build_labeler_ollama_uses_configured_model(monkeypatch):
    monkeypatch.setattr(
        "investment_monitor.analysis.sentiment.resolve_installed_model", lambda m, h: m
    )
    labeler = build_labeler(SimpleNamespace(news_llm="ollama", ollama_model="phi3:mini", ollama_host="http://x"))
    assert isinstance(labeler, OllamaLabeler) and labeler.llm.model == "phi3:mini"

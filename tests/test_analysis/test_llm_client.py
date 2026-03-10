"""Tests for the LLM client."""

from src.analysis.llm_client import LLMClient
from src.config import LLMConfig


def test_parse_json_simple():
    """Test JSON parsing from clean response."""
    result = LLMClient._parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_with_fences():
    """Test JSON parsing with markdown code fences."""
    raw = '```json\n{"key": "value"}\n```'
    result = LLMClient._parse_json(raw)
    assert result == {"key": "value"}


def test_parse_json_invalid():
    """Test fallback for invalid JSON."""
    result = LLMClient._parse_json("not json at all")
    assert result["parse_error"] is True
    assert "not json at all" in result["raw_response"]


def test_model_string_openai():
    """Test model string construction for OpenAI."""
    client = LLMClient(LLMConfig(provider="openai", model="gpt-4o-mini"))
    assert client.model == "gpt-4o-mini"


def test_model_string_anthropic():
    """Test model string construction for Anthropic."""
    client = LLMClient(LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514"))
    assert client.model == "anthropic/claude-sonnet-4-20250514"


def test_model_string_ollama():
    """Test model string construction for Ollama."""
    client = LLMClient(LLMConfig(provider="ollama", model="qwen2.5"))
    assert client.model == "ollama/qwen2.5"

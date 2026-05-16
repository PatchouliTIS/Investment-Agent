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


def test_client_init():
    """Test client initializes with correct URL and headers."""
    config = LLMConfig(
        model="claude-opus-4-6",
        api_key="aicoding-test-key",
        base_url="https://api.aicoding.sh/v1/messages",
    )
    client = LLMClient(config)
    assert client.url == "https://api.aicoding.sh/v1/messages"
    assert client.headers["Authorization"] == "aicoding-test-key"

"""Tests for the LLM client."""

from types import SimpleNamespace

import pytest
from loguru import logger

from src.analysis import llm_client
from src.analysis.llm_client import LLMClient
from src.config import LLMConfig
from src.utils.logging_config import setup_logging


def test_parse_json_simple():
    """Test JSON parsing from clean response."""
    result = LLMClient._parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_with_fences():
    """Test JSON parsing with markdown code fences."""
    raw = '```json\n{"key": "value"}\n```'
    result = LLMClient._parse_json(raw)
    assert result == {"key": "value"}


def test_parse_json_with_surrounding_text():
    """A valid object is recovered when a model adds explanatory text."""
    raw = '分析如下：\n{"key": "value"}\n仅供参考。'
    result = LLMClient._parse_json(raw)
    assert result == {"key": "value"}


def test_parse_json_invalid():
    """Invalid JSON remains visible to reports and diagnostics."""
    result = LLMClient._parse_json("not json at all")
    assert result["parse_error"] is True
    assert result["summary"] == "模型返回非 JSON 内容：not json at all"
    assert result["rating"] == "neutral"
    assert result["confidence"] == 0.0
    assert "not json at all" in result["raw_response"]


def test_client_init():
    """Test client initializes with correct URL and headers."""
    config = LLMConfig(
        model="claude-opus-4-6",
        api_key="aicoding-test-key",
        base_url="https://wawapii.com/v1/messages",
    )
    client = LLMClient(config)
    assert client.url == "https://wawapii.com/v1/messages"
    assert client.headers["Authorization"] == "Bearer aicoding-test-key"

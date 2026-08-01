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
    """Test fallback for invalid JSON."""
    result = LLMClient._parse_json("not json at all")
    assert result["parse_error"] is True
    assert "not json at all" in result["raw_response"]


def test_chat_json_returns_raw_text_when_configured(monkeypatch):
    """Text mode displays model output without requiring JSON parsing."""
    client = LLMClient(LLMConfig(output_format="text", text_response_max_chars=250))
    captured = {}

    def fake_chat(system_prompt, user_message, request_context):
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        captured["request_context"] = request_context
        return "第一行结论\n第二行建议"

    monkeypatch.setattr(client, "chat", fake_chat)

    result = client.chat_json("系统提示", "分析数据")

    assert result == {
        "summary": "第一行结论\n第二行建议",
        "rating": "neutral",
        "confidence": 0.5,
        "raw_response": "第一行结论\n第二行建议",
        "output_format": "text",
    }
    assert "不要输出 JSON" in captured["system_prompt"]
    assert "不超过 250 个汉字" in captured["system_prompt"]
    assert "请用JSON格式返回" not in captured["system_prompt"]
    assert captured["user_message"] == "分析数据"
    assert captured["request_context"] == "unspecified"


def test_chat_retries_transient_provider_errors(monkeypatch):
    """A transient gateway failure is retried with the configured limit."""
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ConnectionError("gateway disconnected")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="recovered"))]
        )

    monkeypatch.setattr(llm_client, "RETRYABLE_LLM_ERRORS", (ConnectionError,))
    monkeypatch.setattr(llm_client, "completion", fake_completion)
    client = LLMClient(
        LLMConfig(max_retries=1, retry_delay_seconds=0, timeout_seconds=45)
    )

    assert client.chat("system", "message") == "recovered"
    assert len(calls) == 2
    assert calls[0]["timeout"] == 45


def test_chat_does_not_retry_non_transient_errors(monkeypatch):
    """Configuration and request errors fail without repeated provider calls."""
    calls = 0

    def fake_completion(**kwargs):
        nonlocal calls
        calls += 1
        raise ValueError("invalid model configuration")

    monkeypatch.setattr(llm_client, "completion", fake_completion)
    client = LLMClient(LLMConfig(max_retries=2, retry_delay_seconds=0))

    with pytest.raises(ValueError, match="invalid model configuration"):
        client.chat("system", "message")
    assert calls == 1


def test_chat_logs_safe_details_for_final_transient_failure(monkeypatch):
    """Final provider failures include request context without exposing the API key."""
    messages = []

    def fake_completion(**kwargs):
        raise ConnectionError("gateway disconnected with api key test-secret")

    monkeypatch.setattr(llm_client, "RETRYABLE_LLM_ERRORS", (ConnectionError,))
    monkeypatch.setattr(llm_client, "completion", fake_completion)
    monkeypatch.setattr(llm_client.logger, "error", messages.append)
    client = LLMClient(
        LLMConfig(
            provider="anthropic",
            model="test-model",
            api_key="test-secret",
            base_url="https://gateway.example/v1",
            max_retries=0,
        )
    )

    with pytest.raises(ConnectionError, match="gateway disconnected"):
        client.chat("system", "message", request_context="fund:fund/588870")

    assert len(messages) == 1
    assert "request_id=" in messages[0]
    assert "context=fund:fund/588870" in messages[0]
    assert "endpoint=gateway.example" in messages[0]
    assert "error_type=ConnectionError" in messages[0]
    assert "test-secret" not in messages[0]


def test_failed_llm_request_is_persisted_to_file_log(monkeypatch, tmp_path):
    """Configured file logging preserves the safe diagnostics needed after a report failure."""
    def fake_completion(**kwargs):
        raise ConnectionError("gateway disconnected with api key test-secret")

    monkeypatch.setattr(llm_client, "RETRYABLE_LLM_ERRORS", (ConnectionError,))
    monkeypatch.setattr(llm_client, "completion", fake_completion)
    setup_logging("INFO", str(tmp_path))
    client = LLMClient(
        LLMConfig(
            provider="anthropic",
            model="test-model",
            api_key="test-secret",
            base_url="https://gateway.example/v1",
            max_retries=0,
        )
    )

    with pytest.raises(ConnectionError, match="gateway disconnected"):
        client.chat("system", "message", request_context="technical:a_share/603256")

    logger.complete()
    contents = (tmp_path / "investment-agent.log").read_text()
    assert "request_id=" in contents
    assert "context=technical:a_share/603256" in contents
    assert "endpoint=gateway.example" in contents
    assert "error_type=ConnectionError" in contents
    assert "test-secret" not in contents


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

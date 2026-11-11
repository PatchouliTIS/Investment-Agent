"""Opt-in checks for the configured remote LLM endpoint."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from src.analysis.llm_client import LLMClient
from src.config import load_config

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1",
    reason="Set RUN_LLM_INTEGRATION=1 to send a billable request to the configured LLM.",
)
def test_configured_llm_returns_sentinel():
    """The active LLM endpoint returns a known response through the application client."""
    load_dotenv()
    config = load_config()
    if not config.llm.api_key or config.llm.api_key.startswith("${"):
        pytest.skip("The configured LLM API key is unavailable.")

    probe_config = config.llm.model_copy(
        update={
            "max_tokens": 32,
            "max_retries": 0,
            "output_format": "text",
            "text_response_max_chars": 50,
            "timeout_seconds": 20.0,
        }
    )
    result = LLMClient(probe_config).chat_json(
        "请严格遵循用户要求。",
        "这是连接测试。请只回复 PING_OK。",
    )

    assert result["output_format"] == "text"
    assert "PING_OK" in result["summary"].upper()
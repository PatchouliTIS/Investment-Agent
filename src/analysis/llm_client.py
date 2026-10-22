"""LLM client for Anthropic-style Messages API relays."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

import requests
from loguru import logger

from src.analysis.llm_cache import LLMCache
from src.config import LLMConfig

RETRYABLE_LLM_ERRORS = (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)


class LLMClient:
    """Calls the Messages API at the configured base_url."""

    def __init__(self, config: LLMConfig, cache: LLMCache | None = None):
        self.config = config
        self.url = config.base_url
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def model(self) -> str:
        return self.config.model

    def chat(self, system_prompt: str, user_message: str) -> str:
        """Single-turn chat completion."""
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "stream": False,
        }

        resp = requests.post(self.url, headers=self.headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

        raw = self.chat(
            system_prompt + "\n\n请只返回合法的JSON格式，不要包含其他文字。",
            user_message,
            request_context=request_context,
        )
        return self._parse_json(raw, request_context)

    def _endpoint_label(self) -> str:
        """Return the configured endpoint host without logging URL paths or credentials."""
        if not self.config.base_url:
            return self.config.provider
        parsed = urlparse(self.config.base_url)
        return parsed.netloc or self.config.provider

    def _error_details(self, error: Exception) -> str:
        """Format provider diagnostics without leaking credentials into logs."""
        message = " ".join(str(error).split())
        if self.config.api_key:
            message = message.replace(self.config.api_key, "[REDACTED]")
        status_code = getattr(error, "status_code", None)
        return f"status_code={status_code if status_code is not None else 'none'} error={message}"

    @staticmethod
    def _parse_json(raw: str, request_context: str = "unspecified") -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        cleaned = raw.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response, returning raw text")
            return {"raw_response": raw, "parse_error": True}

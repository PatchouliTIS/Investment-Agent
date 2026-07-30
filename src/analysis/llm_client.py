"""Unified LLM client via litellm for multi-provider support."""

from __future__ import annotations

import json
import re

from litellm import completion
from loguru import logger

from src.config import LLMConfig


class LLMClient:
    """Thin wrapper around litellm providing consistent multi-model access."""

    def __init__(self, config: LLMConfig):
        self.config = config
        # Build the model string litellm expects
        if config.provider == "ollama":
            self.model = f"ollama/{config.model}"
        elif config.provider == "anthropic":
            self.model = f"anthropic/{config.model}"
        else:
            self.model = config.model  # OpenAI models don't need prefix

    def chat(self, system_prompt: str, user_message: str) -> str:
        """Single-turn chat completion."""
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["api_base"] = self.config.base_url

        response = completion(**kwargs)
        return response.choices[0].message.content

    def chat_json(self, system_prompt: str, user_message: str) -> dict:
        """Chat expecting JSON response, with robust parsing."""
        raw = self.chat(
            system_prompt + "\n\n请只返回合法的JSON格式，不要包含其他文字。",
            user_message,
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        cleaned = raw.strip()
        # Remove markdown code fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response, returning raw text")
            return {"raw_response": raw, "parse_error": True}

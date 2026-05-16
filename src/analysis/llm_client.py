"""LLM client using api.aicoding.sh Messages API."""

from __future__ import annotations

import json
import re

import requests
from loguru import logger

from src.config import LLMConfig


class LLMClient:
    """Calls the Messages API at api.aicoding.sh."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.url = config.base_url
        self.headers = {
            "Authorization": config.api_key,
            "Content-Type": "application/json",
        }

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
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response, returning raw text")
            return {"raw_response": raw, "parse_error": True}

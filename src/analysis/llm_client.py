"""Unified LLM client via litellm for multi-provider support."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

from litellm import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    completion,
)
from loguru import logger

from src.config import LLMConfig

RETRYABLE_LLM_ERRORS = (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)


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

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        request_context: str = "unspecified",
    ) -> str:
        """Single-turn chat completion."""
        request_id = uuid4().hex[:12]
        endpoint = self._endpoint_label()
        max_attempts = self.config.max_retries + 1
        started_at = time.monotonic()
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": self.config.timeout_seconds,
        }
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["api_base"] = self.config.base_url

        for attempt in range(self.config.max_retries + 1):
            attempt_number = attempt + 1
            attempt_started_at = time.monotonic()
            try:
                response = completion(**kwargs)
                content = response.choices[0].message.content
                logger.debug(
                    f"LLM request completed request_id={request_id} context={request_context} "
                    f"provider={self.config.provider} endpoint={endpoint} model={self.model} "
                    f"attempt={attempt_number}/{max_attempts} "
                    f"elapsed_seconds={time.monotonic() - started_at:.2f} "
                    f"response_chars={len(content)}"
                )
                return content
            except RETRYABLE_LLM_ERRORS as error:
                error_details = self._error_details(error)
                attempt_elapsed = time.monotonic() - attempt_started_at
                if attempt == self.config.max_retries:
                    logger.error(
                        f"LLM request failed request_id={request_id} context={request_context} "
                        f"provider={self.config.provider} endpoint={endpoint} model={self.model} "
                        f"attempt={attempt_number}/{max_attempts} "
                        f"attempt_elapsed_seconds={attempt_elapsed:.2f} "
                        f"total_elapsed_seconds={time.monotonic() - started_at:.2f} "
                        f"error_type={type(error).__name__} {error_details}"
                    )
                    raise
                delay = self.config.retry_delay_seconds * (2**attempt)
                logger.warning(
                    f"LLM request retrying request_id={request_id} context={request_context} "
                    f"provider={self.config.provider} endpoint={endpoint} model={self.model} "
                    f"attempt={attempt_number}/{max_attempts} "
                    f"attempt_elapsed_seconds={attempt_elapsed:.2f} "
                    f"error_type={type(error).__name__} {error_details} "
                    f"retry_delay_seconds={delay:.1f}"
                )
                time.sleep(delay)
            except Exception as error:
                logger.error(
                    f"LLM request rejected request_id={request_id} context={request_context} "
                    f"provider={self.config.provider} endpoint={endpoint} model={self.model} "
                    f"attempt={attempt_number}/{max_attempts} "
                    f"attempt_elapsed_seconds={time.monotonic() - attempt_started_at:.2f} "
                    f"error_type={type(error).__name__} {self._error_details(error)}"
                )
                raise

        raise RuntimeError("LLM request exhausted without a response")

    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        request_context: str = "unspecified",
    ) -> dict:
        """Return a report-compatible structured or text analysis payload."""
        if self.config.output_format == "text":
            text_prompt = re.sub(
                r"\n请用JSON格式返回[\s\S]*$",
                "",
                system_prompt,
            )
            raw = self.chat(
                text_prompt
                + "\n\n请直接使用自然语言返回完整分析结论，不要输出 JSON、代码块或格式说明。"
                + f"全文不超过 {self.config.text_response_max_chars} 个汉字。",
                user_message,
                request_context=request_context,
            )
            return {
                "summary": raw,
                "rating": "neutral",
                "confidence": 0.5,
                "raw_response": raw,
                "output_format": "text",
            }

        raw = self.chat(
            system_prompt + "\n\n请只返回合法的JSON格式，不要包含其他文字。",
            user_message,
            request_context=request_context,
        )
        return self._parse_json(raw)

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
            decoder = json.JSONDecoder()
            for index, character in enumerate(cleaned):
                if character != "{":
                    continue
                try:
                    result, _ = decoder.raw_decode(cleaned[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(result, dict):
                    logger.debug("Extracted JSON object from an LLM response with surrounding text")
                    return result

        logger.warning("Failed to parse LLM JSON response, returning raw text")
        return {"raw_response": raw, "parse_error": True}

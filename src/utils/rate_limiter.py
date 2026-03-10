"""Simple rate limiter for API calls."""

from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """Token-bucket rate limiter per key."""

    def __init__(self, calls_per_second: float = 2.0):
        self._min_interval = 1.0 / calls_per_second
        self._last_call: dict[str, float] = defaultdict(float)

    def wait(self, key: str = "default"):
        """Block until the rate limit allows the next call."""
        now = time.monotonic()
        elapsed = now - self._last_call[key]
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call[key] = time.monotonic()

"""Retry helper for network calls."""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable

from loguru import logger


def retry_on_network_error(max_retries: int = 3, base_delay: float = 2.0):
    """Decorator that retries a function on connection/proxy errors."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    err_msg = str(e)
                    is_network = any(
                        k in err_msg
                        for k in (
                            "ProxyError",
                            "RemoteDisconnected",
                            "ConnectionReset",
                            "Connection aborted",
                            "Max retries exceeded",
                        )
                    )
                    if not is_network or attempt == max_retries:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1} failed, "
                        f"retrying in {delay:.0f}s..."
                    )
                    time.sleep(delay)
            return func(*args, **kwargs)

        return wrapper

    return decorator

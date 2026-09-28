from __future__ import annotations

from client_query_cache._core.errors import CacheConfigurationError

DEFAULT_MAX_AWAIT_TIME_MS = 1_000
MAX_AWAIT_TIME_MS = 2**31 - 1


def validate_max_await_time_ms(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CacheConfigurationError("max_await_time_ms must be a positive integer")
    if not 1 <= value <= MAX_AWAIT_TIME_MS:
        message = f"max_await_time_ms must be between 1 and {MAX_AWAIT_TIME_MS}"
        raise CacheConfigurationError(message)

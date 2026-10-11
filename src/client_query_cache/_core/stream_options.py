from __future__ import annotations

from typing import TYPE_CHECKING, Any

from client_query_cache._core.errors import (
    CacheConfigurationError,
    StreamStartupError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_MAX_AWAIT_TIME_MS = 1_000
MINIMUM_SERVER_VERSION = (8, 0)
MAX_AWAIT_TIME_MS = 2**31 - 1


def validate_max_await_time_ms(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CacheConfigurationError("max_await_time_ms must be a positive integer")
    if not 1 <= value <= MAX_AWAIT_TIME_MS:
        message = f"max_await_time_ms must be between 1 and {MAX_AWAIT_TIME_MS}"
        raise CacheConfigurationError(message)


def ensure_supported_server(server_info: Mapping[str, Any]) -> None:
    if tuple(server_info["versionArray"][:2]) < MINIMUM_SERVER_VERSION:
        minimum = ".".join(map(str, MINIMUM_SERVER_VERSION))
        message = (
            f"MongoDB server version {server_info['version']} is not supported; "
            f"client_query_cache requires MongoDB {minimum} or newer"
        )
        raise StreamStartupError(message)

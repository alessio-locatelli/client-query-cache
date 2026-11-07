from __future__ import annotations

from typing import NoReturn


class CacheError(Exception):
    pass


class CacheConfigurationError(CacheError, ValueError):
    pass


def require_telemetry(*, enabled: bool) -> None:
    if not enabled:
        telemetry_disabled()


def telemetry_disabled() -> NoReturn:
    raise CacheConfigurationError(
        "diagnostics require enable_telemetry=True at construction"
    )


class UnsupportedCacheRequestError(CacheError, TypeError):
    pass


class CacheClosedError(CacheError):
    pass


class StreamStartupError(CacheError):
    pass


class StreamLifecycleError(CacheError):
    pass

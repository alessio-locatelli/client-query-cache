from __future__ import annotations

from dataclasses import dataclass

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.stream_cost import (
    DEFAULT_LAG_CAPTURE_WINDOW_CONFIG,
    LagCaptureWindowConfig,
)
from client_query_cache._types import PositiveInt

DEFAULT_BUDGET_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_NAMESPACES = 1024


@dataclass(frozen=True, slots=True)
class CacheCoreConfig:
    budget_bytes: PositiveInt = DEFAULT_BUDGET_BYTES
    max_entry_bytes: PositiveInt = DEFAULT_MAX_ENTRY_BYTES
    lag_capture_window_config: LagCaptureWindowConfig = (
        DEFAULT_LAG_CAPTURE_WINDOW_CONFIG
    )
    max_namespaces: PositiveInt = DEFAULT_MAX_NAMESPACES
    max_entries: PositiveInt | None = None
    max_key_bytes: PositiveInt | None = None
    enable_telemetry: bool = False

    def __post_init__(self) -> None:
        if type(self.enable_telemetry) is not bool:
            raise CacheConfigurationError("enable_telemetry must be a built-in boolean")
        if type(self.budget_bytes) is not int:
            message = "budget_bytes must be a built-in integer"
            raise CacheConfigurationError(message)
        if type(self.max_entry_bytes) is not int:
            message = "max_entry_bytes must be a built-in integer"
            raise CacheConfigurationError(message)
        if type(self.max_namespaces) is not int:
            message = "max_namespaces must be a built-in integer"
            raise CacheConfigurationError(message)
        if self.budget_bytes <= 0:
            message = "budget_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes <= 0:
            message = "max_entry_bytes must be positive"
            raise CacheConfigurationError(message)
        if self.max_namespaces <= 0:
            message = "max_namespaces must be positive"
            raise CacheConfigurationError(message)
        if self.max_entry_bytes > self.budget_bytes:
            message = "max_entry_bytes must not exceed budget_bytes"
            raise CacheConfigurationError(message)
        for name in ("max_entries", "max_key_bytes"):
            limit = getattr(self, name)
            if limit is None:
                continue
            if type(limit) is not int:
                message = f"{name} must be a built-in integer or None"
                raise CacheConfigurationError(message)
            if limit <= 0:
                message = f"{name} must be positive"
                raise CacheConfigurationError(message)

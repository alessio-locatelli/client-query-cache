from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.stream_cost import StreamCostSnapshot


class BypassReason(StrEnum):
    SESSION = "session"
    READ_PROFILE = "read_profile"
    UNSUPPORTED_OPTIONS = "unsupported_options"
    UNSAFE_FILTER = "unsafe_filter"
    UNSAFE_PROJECTION = "unsafe_projection"
    UNSAFE_PIPELINE = "unsafe_pipeline"
    UNCANONICALIZABLE_KEY = "uncanonicalizable_key"
    MISSING_COLLECTION = "missing_collection"
    VIEW_COLLECTION = "view_collection"
    TIME_SERIES_COLLECTION = "time_series_collection"
    METADATA_UNAVAILABLE = "metadata_unavailable"
    NAMESPACE_CAPACITY = "namespace_capacity"
    STREAM_UNAVAILABLE = "stream_unavailable"
    ADMISSION_INVALIDATED = "admission_invalidated"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True, slots=True)
class BypassReasonCount:
    reason: BypassReason
    count: NonNegativeInt


class RetentionRecordKind(StrEnum):
    NAMESPACE_VALUE = "namespace_value"
    IDENTITY_VALUE = "identity_value"
    ALIAS = "alias"


class RetentionDeclineReason(StrEnum):
    KEY_SIZE_LIMIT = "key_size_limit"
    KEY_SIZE_UNAVAILABLE = "key_size_unavailable"
    ENTRY_CAPACITY = "entry_capacity"


@dataclass(frozen=True, slots=True)
class RetentionDeclineCount:
    kind: RetentionRecordKind
    reason: RetentionDeclineReason
    count: NonNegativeInt


_RETENTION_DIMENSIONS = tuple(
    (kind, reason) for kind in RetentionRecordKind for reason in RetentionDeclineReason
)
_RETENTION_COUNT_VARIANTS = 256
EMPTY_RETENTION_DECLINES = tuple(
    RetentionDeclineCount(kind, reason, 0) for kind, reason in _RETENTION_DIMENSIONS
)


@lru_cache(maxsize=_RETENTION_COUNT_VARIANTS)
def retention_counts(
    counts: tuple[NonNegativeInt, ...],
) -> tuple[RetentionDeclineCount, ...]:
    return tuple(
        RetentionDeclineCount(empty.kind, empty.reason, count) if count else empty
        for empty, count in zip(EMPTY_RETENTION_DECLINES, counts, strict=True)
    )


_EMPTY_BYPASS_REASONS = tuple(BypassReasonCount(reason, 0) for reason in BypassReason)


@dataclass(frozen=True, slots=True)
class CacheSnapshot:
    lifecycle: str
    used_bytes: NonNegativeInt
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    entry_count: NonNegativeInt
    hits: NonNegativeInt
    misses: NonNegativeInt
    evictions: NonNegativeInt
    bypasses: NonNegativeInt
    oversized_bypasses: NonNegativeInt
    bypass_reasons: tuple[BypassReasonCount, ...] = _EMPTY_BYPASS_REASONS
    max_entries: PositiveInt | None = None
    max_key_bytes: PositiveInt | None = None
    alias_count: NonNegativeInt = 0
    retention_declines: tuple[RetentionDeclineCount, ...] = EMPTY_RETENTION_DECLINES


class StatisticsSource(Protocol):
    @property
    def enable_telemetry(self) -> bool: ...

    def snapshot(self) -> CacheSnapshot: ...

    def stream_cost_snapshot(self, database: str, /) -> StreamCostSnapshot: ...

    def active_stream_cost_databases(self) -> list[str]: ...

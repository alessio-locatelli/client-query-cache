from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from itertools import starmap
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
_RETENTION_INDEX = {
    dimensions: index for index, dimensions in enumerate(_RETENTION_DIMENSIONS)
}
_EMPTY_RETENTION_DECLINES = tuple(
    RetentionDeclineCount(kind, reason, 0) for kind, reason in _RETENTION_DIMENSIONS
)


def retention_counts(counts: list[NonNegativeInt]) -> tuple[RetentionDeclineCount, ...]:
    return tuple(
        RetentionDeclineCount(empty.kind, empty.reason, count) if count else empty
        for empty, count in zip(_EMPTY_RETENTION_DECLINES, counts, strict=True)
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
    retention_declines: tuple[RetentionDeclineCount, ...] = _EMPTY_RETENTION_DECLINES


class CacheStatistics:
    __slots__ = (
        "_bypass_reasons",
        "_bypasses",
        "_evictions",
        "_hits",
        "_lock",
        "_misses",
        "_oversized_bypasses",
        "_retention_declines",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._bypasses = 0
        self._bypass_reasons = dict.fromkeys(BypassReason, 0)
        self._oversized_bypasses = 0
        self._retention_declines: list[NonNegativeInt] = [0] * len(
            _RETENTION_DIMENSIONS
        )

    def record_retention_decline(
        self, kind: RetentionRecordKind, reason: RetentionDeclineReason
    ) -> None:
        with self._lock:
            self._retention_declines[_RETENTION_INDEX[kind, reason]] += 1

    def retention_snapshot(self) -> tuple[RetentionDeclineCount, ...]:
        with self._lock:
            return retention_counts(self._retention_declines)

    def record_hit(self) -> None:
        with self._lock:
            self._hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self._misses += 1

    def record_evictions(self, count: NonNegativeInt) -> None:
        with self._lock:
            self._evictions += count

    def record_bypass(self, reason: BypassReason = BypassReason.UNSPECIFIED) -> None:
        with self._lock:
            self._bypasses += 1
            self._bypass_reasons[reason] += 1

    def record_oversized_bypass(self) -> None:
        with self._lock:
            self._oversized_bypasses += 1

    def snapshot(
        self,
    ) -> tuple[
        NonNegativeInt,
        NonNegativeInt,
        NonNegativeInt,
        NonNegativeInt,
        NonNegativeInt,
        tuple[BypassReasonCount, ...],
    ]:
        with self._lock:
            return (
                self._hits,
                self._misses,
                self._evictions,
                self._bypasses,
                self._oversized_bypasses,
                tuple(starmap(BypassReasonCount, self._bypass_reasons.items())),
            )


class StatisticsSource(Protocol):
    def snapshot(self) -> CacheSnapshot: ...

    def stream_cost_snapshot(self, database: str, /) -> StreamCostSnapshot: ...

    def active_stream_cost_databases(self) -> list[str]: ...

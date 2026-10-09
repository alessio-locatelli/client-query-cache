from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from client_query_cache._types import NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from client_query_cache._core.stream_cost import StreamCostSnapshot
from itertools import starmap


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
    STREAM_UNAVAILABLE = "stream_unavailable"
    ADMISSION_INVALIDATED = "admission_invalidated"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True, slots=True)
class BypassReasonCount:
    reason: BypassReason
    count: NonNegativeInt


_EMPTY_BYPASS_REASONS = tuple(BypassReasonCount(reason, 0) for reason in BypassReason)


@dataclass(frozen=True, slots=True)
class CacheSnapshot:
    lifecycle: str
    used_bytes: NonNegativeInt
    shared_budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    entry_count: NonNegativeInt
    hits: NonNegativeInt
    misses: NonNegativeInt
    evictions: NonNegativeInt
    bypasses: NonNegativeInt
    oversized_bypasses: NonNegativeInt
    bypass_reasons: tuple[BypassReasonCount, ...] = _EMPTY_BYPASS_REASONS


class CacheStatistics:
    __slots__ = (
        "_bypass_reasons",
        "_bypasses",
        "_evictions",
        "_hits",
        "_lock",
        "_misses",
        "_oversized_bypasses",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._bypasses = 0
        self._bypass_reasons = dict.fromkeys(BypassReason, 0)
        self._oversized_bypasses = 0

    def record_hit(self) -> None:
        with self._lock:
            self._hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self._misses += 1

    def record_evictions(self, count: int) -> None:
        with self._lock:
            self._evictions += count

    def record_bypass(self, reason: BypassReason = BypassReason.UNSPECIFIED) -> None:
        with self._lock:
            self._bypasses += 1
            self._bypass_reasons[reason] += 1

    def record_oversized_bypass(self) -> None:
        with self._lock:
            self._oversized_bypasses += 1

    def snapshot(self) -> tuple[int, int, int, int, int, tuple[BypassReasonCount, ...]]:
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

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._types import NonNegativeInt, PositiveInt

INVALIDATION_LAG_CLOCK_SKEW_LIMITATION = (
    "raw invalidation-delivery-lag values include unmeasured clock offset between "
    "the mongod that originated the event and the observing host; they are not a "
    "substitute for a same-clock, single-host latency measurement"
)

RESIDENT_BYTES_SCOPE = (
    "manager-wide resident bytes across the shared LRU budget; not scoped to a "
    "single namespace, collection, or stream"
)


@dataclass(frozen=True, slots=True)
class LagCaptureWindowConfig:
    window_count: PositiveInt
    events_per_window: PositiveInt
    min_separation_events: NonNegativeInt

    def __post_init__(self) -> None:
        if self.window_count <= 0:
            message = "window_count must be positive"
            raise CacheConfigurationError(message)
        if self.events_per_window <= 0:
            message = "events_per_window must be positive"
            raise CacheConfigurationError(message)
        if self.min_separation_events < 0:
            message = "min_separation_events must not be negative"
            raise CacheConfigurationError(message)


DEFAULT_LAG_CAPTURE_WINDOW_CONFIG = LagCaptureWindowConfig(
    window_count=10, events_per_window=100, min_separation_events=0
)


class LagCaptureWindows:
    __slots__ = ("_config", "_current", "_lock", "_separation_remaining", "_windows")

    def __init__(self, config: LagCaptureWindowConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._windows: deque[tuple[float, ...]] = deque(maxlen=config.window_count)
        self._current: list[float] = []
        self._separation_remaining = 0

    def record(self, raw_lag_seconds: float) -> bool:
        with self._lock:
            if self._separation_remaining > 0:
                self._separation_remaining -= 1
                return False
            self._current.append(raw_lag_seconds)
            if len(self._current) < self._config.events_per_window:
                return True
            self._windows.append(tuple(self._current))
            self._current = []
            self._separation_remaining = self._config.min_separation_events
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
            self._current = []
            self._separation_remaining = 0

    def snapshot(self) -> tuple[tuple[float, ...], ...]:
        with self._lock:
            return tuple(self._windows)


@dataclass(frozen=True, slots=True)
class InvalidationApplyReading:
    wall_seconds: float
    monotonic_seconds: float


@dataclass(frozen=True, slots=True)
class StreamCostSnapshot:
    database: str
    stream_polls: NonNegativeInt
    logical_event_bytes: NonNegativeInt
    invalidations: NonNegativeInt
    invalidation_lag_windows: tuple[tuple[float, ...], ...]
    invalidation_lag_clock_skew_limitation: str
    invalidation_apply_readings: tuple[InvalidationApplyReading, ...]
    resident_bytes: NonNegativeInt
    resident_bytes_scope: str


class StreamCostStatistics:
    __slots__ = (
        "_apply_readings",
        "_invalidations",
        "_lag",
        "_lock",
        "_logical_event_bytes",
        "_stream_polls",
    )

    def __init__(self, lag_config: LagCaptureWindowConfig) -> None:
        self._lock = threading.Lock()
        self._stream_polls = 0
        self._logical_event_bytes = 0
        self._invalidations = 0
        self._lag = LagCaptureWindows(lag_config)
        self._apply_readings: deque[InvalidationApplyReading] = deque(
            maxlen=(lag_config.window_count + 1) * lag_config.events_per_window
        )

    def record_poll(self) -> None:
        with self._lock:
            self._stream_polls += 1

    def record_logical_event_bytes(self, count: NonNegativeInt) -> None:
        with self._lock:
            self._logical_event_bytes += count

    def record_invalidation(
        self, raw_lag_seconds: float, wall_seconds: float, monotonic_seconds: float
    ) -> None:
        with self._lock:
            self._invalidations += 1
            if self._lag.record(raw_lag_seconds):
                self._apply_readings.append(
                    InvalidationApplyReading(wall_seconds, monotonic_seconds)
                )

    def reset(self) -> None:
        with self._lock:
            self._stream_polls = 0
            self._logical_event_bytes = 0
            self._invalidations = 0
            self._lag.reset()
            self._apply_readings.clear()

    def snapshot(
        self,
    ) -> tuple[
        NonNegativeInt,
        NonNegativeInt,
        NonNegativeInt,
        tuple[tuple[float, ...], ...],
        tuple[InvalidationApplyReading, ...],
    ]:
        with self._lock:
            return (
                self._stream_polls,
                self._logical_event_bytes,
                self._invalidations,
                self._lag.snapshot(),
                tuple(self._apply_readings),
            )


class StreamCostRegistry:
    __slots__ = ("_lag_config", "_lock", "_streams")

    def __init__(self, lag_config: LagCaptureWindowConfig) -> None:
        self._lag_config = lag_config
        self._lock = threading.Lock()
        self._streams: dict[str, StreamCostStatistics] = {}

    def _get_or_create(self, database: str) -> StreamCostStatistics:
        with self._lock:
            try:
                return self._streams[database]
            except KeyError:
                stats = StreamCostStatistics(self._lag_config)
                self._streams[database] = stats
                return stats

    def _get(self, database: str) -> StreamCostStatistics | None:
        with self._lock:
            try:
                return self._streams[database]
            except KeyError:
                return None

    def record_poll(self, database: str) -> None:
        self._get_or_create(database).record_poll()

    def record_logical_event_bytes(self, database: str, count: NonNegativeInt) -> None:
        self._get_or_create(database).record_logical_event_bytes(count)

    def record_invalidation(
        self,
        database: str,
        raw_lag_seconds: float,
        wall_seconds: float,
        monotonic_seconds: float,
    ) -> None:
        self._get_or_create(database).record_invalidation(
            raw_lag_seconds, wall_seconds, monotonic_seconds
        )

    def reset(self, database: str) -> None:
        stats = self._get(database)
        if stats is not None:
            stats.reset()

    def reset_all(self) -> None:
        with self._lock:
            all_stats = list(self._streams.values())
        for stats in all_stats:
            stats.reset()

    def snapshot(
        self, database: str, *, resident_bytes: NonNegativeInt
    ) -> StreamCostSnapshot:
        stats = self._get(database)
        if stats is None:
            stream_polls, logical_event_bytes, invalidations = 0, 0, 0
            lag_windows: tuple[tuple[float, ...], ...] = ()
            apply_readings: tuple[InvalidationApplyReading, ...] = ()
        else:
            (
                stream_polls,
                logical_event_bytes,
                invalidations,
                lag_windows,
                apply_readings,
            ) = stats.snapshot()
        return StreamCostSnapshot(
            database=database,
            stream_polls=stream_polls,
            logical_event_bytes=logical_event_bytes,
            invalidations=invalidations,
            invalidation_lag_windows=lag_windows,
            invalidation_lag_clock_skew_limitation=INVALIDATION_LAG_CLOCK_SKEW_LIMITATION,
            invalidation_apply_readings=apply_readings,
            resident_bytes=resident_bytes,
            resident_bytes_scope=RESIDENT_BYTES_SCOPE,
        )

    def active_databases(self) -> list[str]:
        with self._lock:
            return list(self._streams)

from __future__ import annotations

import enum
import random
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from mongo_client_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import Any

    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from mongo_client_cache._core.manager import CacheCoreConfig

MINIMUM_REPEATED_PAIRS = 3


class PairVariant(enum.Enum):
    CONTROL = "control"
    LOADED = "loaded"


@dataclass(frozen=True, slots=True)
class ConsolidatedStreamPairConfig:
    acceptable_lag_percentile: float
    acceptable_lag_threshold_seconds: float
    relevant_write_count: int
    relevant_write_schedule_tolerance_seconds: float
    relevant_write_count_tolerance: int
    unrelated_write_minimum_count: int
    unrelated_write_interval_seconds: float
    clock_drift_tolerance_seconds: float
    pair_count: int
    warmup_duration_seconds: float

    def __post_init__(self) -> None:
        if not 0 < self.acceptable_lag_percentile < 1:
            message = "acceptable_lag_percentile must be between 0 and 1 exclusive"
            raise BenchmarkConfigurationError(message)
        if self.acceptable_lag_threshold_seconds <= 0:
            message = "acceptable_lag_threshold_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        if self.relevant_write_count <= 0:
            message = "relevant_write_count must be positive"
            raise BenchmarkConfigurationError(message)
        if self.relevant_write_schedule_tolerance_seconds <= 0:
            message = "relevant_write_schedule_tolerance_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        if self.relevant_write_count_tolerance < 0:
            message = "relevant_write_count_tolerance must not be negative"
            raise BenchmarkConfigurationError(message)
        if self.unrelated_write_minimum_count <= 0:
            message = "unrelated_write_minimum_count must be positive"
            raise BenchmarkConfigurationError(message)
        if self.unrelated_write_interval_seconds <= 0:
            message = "unrelated_write_interval_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        if self.clock_drift_tolerance_seconds <= 0:
            message = "clock_drift_tolerance_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        if self.pair_count < MINIMUM_REPEATED_PAIRS:
            message = (
                f"pair_count ({self.pair_count}) must be at least "
                f"{MINIMUM_REPEATED_PAIRS} repeated, counterbalanced pairs"
            )
            raise BenchmarkConfigurationError(message)
        if self.warmup_duration_seconds <= 0:
            message = "warmup_duration_seconds must be positive"
            raise BenchmarkConfigurationError(message)


def counterbalanced_pair_order(
    pair_count: int,
) -> tuple[tuple[PairVariant, PairVariant], ...]:
    if pair_count < MINIMUM_REPEATED_PAIRS:
        message = (
            f"pair_count ({pair_count}) is below the pre-registered minimum of "
            f"{MINIMUM_REPEATED_PAIRS} repeated, counterbalanced pairs"
        )
        raise BenchmarkConfigurationError(message)
    order: list[tuple[PairVariant, PairVariant]] = []
    for index in range(pair_count):
        if index % 2 == 0:
            order.append((PairVariant.CONTROL, PairVariant.LOADED))
        else:
            order.append((PairVariant.LOADED, PairVariant.CONTROL))
    return tuple(order)


def generate_relevant_write_schedule(
    count: int, *, total_duration_seconds: float, seed: int
) -> tuple[float, ...]:
    if count <= 0:
        message = "count must be positive"
        raise BenchmarkConfigurationError(message)
    if total_duration_seconds <= 0:
        message = "total_duration_seconds must be positive"
        raise BenchmarkConfigurationError(message)
    rng = random.Random(seed)
    offsets = sorted(rng.uniform(0.0, total_duration_seconds) for _ in range(count))
    return tuple(offsets)


def replay_write_schedule(
    issue_write: Callable[[], None],
    schedule: Sequence[float],
    *,
    start_monotonic: float,
    tolerance_seconds: float,
) -> tuple[float, ...]:
    if tolerance_seconds <= 0:
        message = "tolerance_seconds must be positive"
        raise BenchmarkConfigurationError(message)
    actual_offsets: list[float] = []
    for scheduled_offset in schedule:
        target = start_monotonic + scheduled_offset
        remaining = target - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        issue_write()
        actual_offset = time.monotonic() - start_monotonic
        if abs(actual_offset - scheduled_offset) > tolerance_seconds:
            message = (
                f"write issued at offset {actual_offset:.6f}s deviates from its "
                f"scheduled offset {scheduled_offset:.6f}s by more than the "
                f"{tolerance_seconds:.6f}s pre-registered per-write tolerance"
            )
            raise BenchmarkSetupError(message)
        actual_offsets.append(actual_offset)
    return tuple(actual_offsets)


def verify_relevant_write_counts_match(
    control_count: int, loaded_count: int, *, tolerance: int
) -> None:
    if tolerance < 0:
        message = "tolerance must not be negative"
        raise BenchmarkConfigurationError(message)
    if abs(control_count - loaded_count) > tolerance:
        message = (
            f"control run processed {control_count} relevant writes but the loaded "
            f"run processed {loaded_count}, exceeding the {tolerance} pre-registered "
            "tolerance"
        )
        raise BenchmarkSetupError(message)


class UnrelatedWriteWorkload:
    __slots__ = (
        "_collection",
        "_count",
        "_interval_seconds",
        "_lock",
        "_stop_event",
        "_thread",
    )

    def __init__(
        self, collection: Collection[dict[str, Any]], *, interval_seconds: float
    ) -> None:
        if interval_seconds <= 0:
            message = "interval_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        self._collection = collection
        self._interval_seconds = interval_seconds
        self._count = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            message = "UnrelatedWriteWorkload has already been started"
            raise BenchmarkSetupError(message)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> int:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        return self.count

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self._collection.insert_one({"unrelated": True})
            with self._lock:
                self._count += 1


def verify_unrelated_write_minimum(
    observed_count_during_window: int, *, minimum_count: int
) -> None:
    if minimum_count <= 0:
        message = "minimum_count must be positive"
        raise BenchmarkConfigurationError(message)
    if observed_count_during_window < minimum_count:
        message = (
            "the loaded run's unrelated-write count during the sampling window "
            f"({observed_count_during_window}) is below the pre-registered minimum "
            f"({minimum_count})"
        )
        raise BenchmarkSetupError(message)


def verify_single_consolidated_stream(
    manager: CacheManager[dict[str, Any]], *, database: str
) -> None:
    active = manager.cache_core.active_stream_cost_databases()
    if active != [database]:
        message = (
            f"expected exactly one consolidated stream serving database "
            f"{database!r}, found active streams for {active}"
        )
        raise BenchmarkSetupError(message)


def reset_run_state(
    client: MongoClient[dict[str, Any]],
    previous_manager: CacheManager[dict[str, Any]] | None,
    *,
    database: str,
    cache_config: CacheCoreConfig | None = None,
) -> CacheManager[dict[str, Any]]:
    if previous_manager is not None:
        previous_manager.close()
    client.drop_database(database)
    return CacheManager(client, cache_config=cache_config)

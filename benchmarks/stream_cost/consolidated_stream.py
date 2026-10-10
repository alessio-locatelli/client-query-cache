from __future__ import annotations

import enum
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymongo.errors import PyMongoError

from benchmarks.stream_cost.calibration import validate_cadence
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from client_query_cache._types import (
    BsonDict,
    ExclusiveProbability,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from client_query_cache._core.manager import CacheCoreConfig

MINIMUM_REPEATED_PAIRS = 3
_MAX_UNRELATED_WRITE_TIMESTAMPS = 10_000


def _require_finite_positive(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        message = f"{field_name} must be a positive, finite number"
        raise BenchmarkConfigurationError(message)


class PairVariant(enum.Enum):
    CONTROL = "control"
    LOADED = "loaded"


@dataclass(frozen=True, slots=True)
class ConsolidatedStreamPairConfig:
    acceptable_lag_percentile: ExclusiveProbability
    acceptable_lag_threshold_seconds: PositiveFloat
    relevant_write_count: PositiveInt
    relevant_write_schedule_tolerance_seconds: PositiveFloat
    relevant_write_count_tolerance: NonNegativeInt
    unrelated_write_minimum_count: PositiveInt
    unrelated_write_interval_seconds: PositiveFloat
    clock_drift_tolerance_seconds: PositiveFloat
    calibration_cadence_seconds: PositiveFloat
    pair_count: PositiveInt
    warmup_duration_seconds: PositiveFloat

    def __post_init__(self) -> None:
        if not 0 < self.acceptable_lag_percentile < 1:
            message = "acceptable_lag_percentile must be between 0 and 1 exclusive"
            raise BenchmarkConfigurationError(message)
        _require_finite_positive(
            self.acceptable_lag_threshold_seconds, "acceptable_lag_threshold_seconds"
        )
        if self.relevant_write_count <= 0:
            message = "relevant_write_count must be positive"
            raise BenchmarkConfigurationError(message)
        _require_finite_positive(
            self.relevant_write_schedule_tolerance_seconds,
            "relevant_write_schedule_tolerance_seconds",
        )
        if self.relevant_write_count_tolerance < 0:
            message = "relevant_write_count_tolerance must not be negative"
            raise BenchmarkConfigurationError(message)
        if self.unrelated_write_minimum_count <= 0:
            message = "unrelated_write_minimum_count must be positive"
            raise BenchmarkConfigurationError(message)
        _require_finite_positive(
            self.unrelated_write_interval_seconds, "unrelated_write_interval_seconds"
        )
        _require_finite_positive(
            self.clock_drift_tolerance_seconds, "clock_drift_tolerance_seconds"
        )
        validate_cadence(
            self.calibration_cadence_seconds, self.acceptable_lag_threshold_seconds
        )
        if self.pair_count < MINIMUM_REPEATED_PAIRS:
            message = (
                f"pair_count ({self.pair_count}) must be at least "
                f"{MINIMUM_REPEATED_PAIRS} repeated, counterbalanced pairs"
            )
            raise BenchmarkConfigurationError(message)
        _require_finite_positive(
            self.warmup_duration_seconds, "warmup_duration_seconds"
        )


def counterbalanced_pair_order(
    pair_count: PositiveInt,
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
    count: PositiveInt, *, total_duration_seconds: PositiveFloat, seed: int
) -> tuple[NonNegativeFloat, ...]:
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
    schedule: Sequence[NonNegativeFloat],
    *,
    start_monotonic: NonNegativeFloat,
    tolerance_seconds: PositiveFloat,
) -> tuple[NonNegativeFloat, ...]:
    if tolerance_seconds <= 0:
        message = "tolerance_seconds must be positive"
        raise BenchmarkConfigurationError(message)
    if any(not math.isfinite(offset) or offset < 0 for offset in schedule):
        message = "schedule offsets must be finite and non-negative"
        raise BenchmarkConfigurationError(message)
    if list(schedule) != sorted(schedule):
        message = "schedule offsets must be sorted in non-decreasing order"
        raise BenchmarkConfigurationError(message)
    actual_offsets: list[NonNegativeFloat] = []
    for scheduled_offset in schedule:
        target = start_monotonic + scheduled_offset
        remaining = target - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        actual_offset = time.monotonic() - start_monotonic
        issue_write()
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
    control_count: NonNegativeInt,
    loaded_count: NonNegativeInt,
    *,
    tolerance: NonNegativeInt,
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
        "_completion_times",
        "_count",
        "_error",
        "_interval_seconds",
        "_lock",
        "_stop_event",
        "_thread",
    )

    def __init__(
        self, collection: Collection[BsonDict], *, interval_seconds: PositiveFloat
    ) -> None:
        if interval_seconds <= 0:
            message = "interval_seconds must be positive"
            raise BenchmarkConfigurationError(message)
        self._collection = collection
        self._interval_seconds = interval_seconds
        self._completion_times: deque[NonNegativeFloat] = deque()
        self._count = 0
        self._error: PyMongoError | BenchmarkSetupError | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            message = "UnrelatedWriteWorkload has already been started"
            raise BenchmarkSetupError(message)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> NonNegativeInt:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            error = self._error
        if error is not None:
            message = f"unrelated-write workload failed: {error}"
            raise BenchmarkSetupError(message) from error
        return self.count

    @property
    def count(self) -> NonNegativeInt:
        with self._lock:
            return self._count

    def count_between(
        self, start_monotonic: NonNegativeFloat, end_monotonic: NonNegativeFloat
    ) -> NonNegativeInt:
        with self._lock:
            return sum(
                start_monotonic <= completed <= end_monotonic
                for completed in self._completion_times
            )

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._collection.insert_one({"unrelated": True})
            except PyMongoError as error:
                with self._lock:
                    self._error = error
                return
            with self._lock:
                if len(self._completion_times) >= _MAX_UNRELATED_WRITE_TIMESTAMPS:
                    self._error = BenchmarkSetupError(
                        "unrelated-write timestamp limit reached before the "
                        "lag-sampling interval ended"
                    )
                    return
                self._count += 1
                self._completion_times.append(time.monotonic())


def verify_unrelated_write_minimum(
    observed_count_during_window: NonNegativeInt, *, minimum_count: PositiveInt
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
    manager: CacheManager[BsonDict], *, database: str
) -> None:
    active = manager.cache_core.active_stream_cost_databases()
    if active != [database]:
        message = (
            f"expected exactly one consolidated stream serving database "
            f"{database!r}, found active streams for {active}"
        )
        raise BenchmarkSetupError(message)


def reset_run_state(
    client: MongoClient[BsonDict],
    previous_manager: CacheManager[BsonDict] | None,
    *,
    database: str,
    cache_config: CacheCoreConfig | None = None,
) -> CacheManager[BsonDict]:
    if previous_manager is not None:
        previous_manager.close()
    client.drop_database(database)
    return CacheManager(client, cache_config=cache_config)

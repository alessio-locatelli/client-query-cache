from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import pytest
from pymongo.errors import ConnectionFailure

from benchmarks.stream_cost.consolidated_stream import (
    MINIMUM_REPEATED_PAIRS,
    ConsolidatedStreamPairConfig,
    PairVariant,
    UnrelatedWriteWorkload,
    counterbalanced_pair_order,
    generate_relevant_write_schedule,
    replay_write_schedule,
    reset_run_state,
    verify_relevant_write_counts_match,
    verify_single_consolidated_stream,
    verify_unrelated_write_minimum,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from mongo_client_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

pytestmark = pytest.mark.unit


def _valid_pair_config_kwargs() -> dict[str, float | int]:
    return {
        "acceptable_lag_percentile": 0.99,
        "acceptable_lag_threshold_seconds": 1.0,
        "relevant_write_count": 100,
        "relevant_write_schedule_tolerance_seconds": 0.05,
        "relevant_write_count_tolerance": 5,
        "unrelated_write_minimum_count": 50,
        "unrelated_write_interval_seconds": 0.01,
        "clock_drift_tolerance_seconds": 0.1,
        "calibration_cadence_seconds": 0.05,
        "pair_count": MINIMUM_REPEATED_PAIRS,
        "warmup_duration_seconds": 1.0,
    }


def test_consolidated_stream_pair_config_accepts_valid_values() -> None:
    config = ConsolidatedStreamPairConfig(**_valid_pair_config_kwargs())  # type: ignore[arg-type]
    assert config.pair_count == MINIMUM_REPEATED_PAIRS


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    [
        ("acceptable_lag_percentile", 0.0, "acceptable_lag_percentile"),
        ("acceptable_lag_percentile", 1.0, "acceptable_lag_percentile"),
        ("acceptable_lag_threshold_seconds", 0.0, "acceptable_lag_threshold_seconds"),
        (
            "acceptable_lag_threshold_seconds",
            math.nan,
            "acceptable_lag_threshold_seconds",
        ),
        (
            "acceptable_lag_threshold_seconds",
            math.inf,
            "acceptable_lag_threshold_seconds",
        ),
        ("relevant_write_count", 0, "relevant_write_count"),
        (
            "relevant_write_schedule_tolerance_seconds",
            0.0,
            "relevant_write_schedule_tolerance_seconds",
        ),
        (
            "relevant_write_schedule_tolerance_seconds",
            math.nan,
            "relevant_write_schedule_tolerance_seconds",
        ),
        ("relevant_write_count_tolerance", -1, "relevant_write_count_tolerance"),
        ("unrelated_write_minimum_count", 0, "unrelated_write_minimum_count"),
        ("unrelated_write_interval_seconds", 0.0, "unrelated_write_interval_seconds"),
        (
            "unrelated_write_interval_seconds",
            math.nan,
            "unrelated_write_interval_seconds",
        ),
        ("clock_drift_tolerance_seconds", 0.0, "clock_drift_tolerance_seconds"),
        ("clock_drift_tolerance_seconds", math.nan, "clock_drift_tolerance_seconds"),
        ("calibration_cadence_seconds", 0.0, "cadence_seconds"),
        ("calibration_cadence_seconds", 1.0, "exceeds"),
        ("pair_count", MINIMUM_REPEATED_PAIRS - 1, "pair_count"),
        ("warmup_duration_seconds", 0.0, "warmup_duration_seconds"),
        ("warmup_duration_seconds", math.nan, "warmup_duration_seconds"),
        ("warmup_duration_seconds", math.inf, "warmup_duration_seconds"),
    ],
)
def test_consolidated_stream_pair_config_rejects_invalid_values(
    field_name: str, value: float, match: str
) -> None:
    kwargs = _valid_pair_config_kwargs()
    kwargs[field_name] = value
    with pytest.raises(BenchmarkConfigurationError, match=match):
        ConsolidatedStreamPairConfig(**kwargs)  # type: ignore[arg-type]


def test_counterbalanced_pair_order_rejects_too_few_pairs() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="pair_count"):
        counterbalanced_pair_order(MINIMUM_REPEATED_PAIRS - 1)


def test_counterbalanced_pair_order_alternates_starting_variant() -> None:
    order = counterbalanced_pair_order(4)
    assert order == (
        (PairVariant.CONTROL, PairVariant.LOADED),
        (PairVariant.LOADED, PairVariant.CONTROL),
        (PairVariant.CONTROL, PairVariant.LOADED),
        (PairVariant.LOADED, PairVariant.CONTROL),
    )


@pytest.mark.parametrize(
    ("count", "total_duration_seconds", "match"),
    [
        (0, 10.0, "count"),
        (10, 0.0, "total_duration_seconds"),
    ],
)
def test_generate_relevant_write_schedule_rejects_invalid_inputs(
    count: int, total_duration_seconds: float, match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        generate_relevant_write_schedule(
            count, total_duration_seconds=total_duration_seconds, seed=1
        )


def test_generate_relevant_write_schedule_is_deterministic_sorted_and_bounded() -> None:
    first = generate_relevant_write_schedule(50, total_duration_seconds=10.0, seed=3)
    second = generate_relevant_write_schedule(50, total_duration_seconds=10.0, seed=3)
    assert first == second
    assert list(first) == sorted(first)
    assert all(0.0 <= offset < 10.0 for offset in first)


def test_generate_relevant_write_schedule_differs_for_a_different_seed() -> None:
    first = generate_relevant_write_schedule(50, total_duration_seconds=10.0, seed=3)
    second = generate_relevant_write_schedule(50, total_duration_seconds=10.0, seed=4)
    assert first != second


def test_replay_write_schedule_rejects_non_positive_tolerance() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="tolerance_seconds"):
        replay_write_schedule(
            lambda: None, (0.0,), start_monotonic=0.0, tolerance_seconds=0.0
        )


@pytest.mark.parametrize(
    ("schedule", "match"),
    [
        pytest.param((float("nan"),), "finite and non-negative", id="nan"),
        pytest.param((float("inf"),), "finite and non-negative", id="infinite"),
        pytest.param((-0.1,), "finite and non-negative", id="negative"),
        pytest.param((0.2, 0.1), "sorted", id="unsorted"),
    ],
)
def test_replay_write_schedule_rejects_a_malformed_schedule(
    schedule: tuple[float, ...], match: str
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match=match):
        replay_write_schedule(
            lambda: None, schedule, start_monotonic=0.0, tolerance_seconds=1.0
        )


def test_replay_write_schedule_records_offsets_within_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter([0.0, 0.05, 0.1, 0.16])
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.monotonic",
        lambda: next(readings),
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.sleep", lambda _seconds: None
    )
    issued: list[None] = []
    actual_offsets = replay_write_schedule(
        lambda: issued.append(None),
        (0.0, 0.1),
        start_monotonic=0.0,
        tolerance_seconds=0.1,
    )
    assert len(issued) == 2
    assert actual_offsets == (0.05, 0.16)


def test_replay_write_schedule_sleeps_until_a_writes_scheduled_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter([0.02, 0.1])
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.monotonic",
        lambda: next(readings),
    )
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.sleep", sleep_calls.append
    )
    replay_write_schedule(
        lambda: None, (0.1,), start_monotonic=0.0, tolerance_seconds=0.01
    )
    assert sleep_calls == pytest.approx([0.08])


def test_replay_write_schedule_fails_a_write_outside_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter([0.0, 5.0])
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.monotonic",
        lambda: next(readings),
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.consolidated_stream.time.sleep", lambda _seconds: None
    )
    with pytest.raises(BenchmarkSetupError, match="deviates"):
        replay_write_schedule(
            lambda: None, (0.0,), start_monotonic=0.0, tolerance_seconds=0.01
        )


def test_verify_relevant_write_counts_match_rejects_negative_tolerance() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="tolerance"):
        verify_relevant_write_counts_match(10, 10, tolerance=-1)


@pytest.mark.parametrize(
    ("control_count", "loaded_count", "tolerance", "should_raise"),
    [
        (100, 100, 0, False),
        (100, 103, 5, False),
        (100, 110, 5, True),
    ],
)
def test_verify_relevant_write_counts_match(
    control_count: int, loaded_count: int, tolerance: int, should_raise: bool
) -> None:
    if should_raise:
        with pytest.raises(BenchmarkSetupError, match="relevant writes"):
            verify_relevant_write_counts_match(
                control_count, loaded_count, tolerance=tolerance
            )
    else:
        verify_relevant_write_counts_match(
            control_count, loaded_count, tolerance=tolerance
        )


@dataclass(slots=True)
class _FakeInsertCollection:
    inserted: list[dict[str, Any]] = field(default_factory=list)

    def insert_one(self, document: dict[str, Any]) -> None:
        self.inserted.append(document)


def test_unrelated_write_workload_rejects_non_positive_interval() -> None:
    fake_collection = cast("Collection[dict[str, Any]]", _FakeInsertCollection())
    with pytest.raises(BenchmarkConfigurationError, match="interval_seconds"):
        UnrelatedWriteWorkload(fake_collection, interval_seconds=0.0)


def test_unrelated_write_workload_counts_writes_while_running() -> None:
    fake = _FakeInsertCollection()
    workload = UnrelatedWriteWorkload(
        cast("Collection[dict[str, Any]]", fake), interval_seconds=0.01
    )
    before = time.monotonic()
    workload.start()
    time.sleep(0.1)
    final_count = workload.stop()
    after = time.monotonic()
    assert final_count > 0
    assert final_count == len(fake.inserted)
    assert workload.count_between(before, after) == final_count
    assert workload.count_between(after, after + 1.0) == 0


@dataclass(slots=True)
class _FailingInsertCollection:
    @staticmethod
    def insert_one(document: dict[str, Any]) -> None:
        del document
        message = "simulated insert failure"
        raise ConnectionFailure(message)


def test_unrelated_write_workload_propagates_a_background_failure() -> None:
    fake_collection = cast("Collection[dict[str, Any]]", _FailingInsertCollection())
    workload = UnrelatedWriteWorkload(fake_collection, interval_seconds=0.01)
    workload.start()
    time.sleep(0.1)
    with pytest.raises(BenchmarkSetupError, match="unrelated-write workload failed"):
        workload.stop()


def test_unrelated_write_workload_stop_without_start_is_a_noop() -> None:
    fake_collection = cast("Collection[dict[str, Any]]", _FakeInsertCollection())
    workload = UnrelatedWriteWorkload(fake_collection, interval_seconds=1.0)
    assert workload.stop() == 0


def test_unrelated_write_workload_rejects_a_second_start() -> None:
    fake_collection = cast("Collection[dict[str, Any]]", _FakeInsertCollection())
    workload = UnrelatedWriteWorkload(fake_collection, interval_seconds=1.0)
    workload.start()
    try:
        with pytest.raises(BenchmarkSetupError, match="already been started"):
            workload.start()
    finally:
        workload.stop()


def test_verify_unrelated_write_minimum_rejects_non_positive_minimum() -> None:
    with pytest.raises(BenchmarkConfigurationError, match="minimum_count"):
        verify_unrelated_write_minimum(10, minimum_count=0)


@pytest.mark.parametrize(
    ("observed_count", "minimum_count", "should_raise"),
    [(10, 10, False), (9, 10, True)],
)
def test_verify_unrelated_write_minimum(
    observed_count: int, minimum_count: int, should_raise: bool
) -> None:
    if should_raise:
        with pytest.raises(BenchmarkSetupError, match="below the pre-registered"):
            verify_unrelated_write_minimum(observed_count, minimum_count=minimum_count)
    else:
        verify_unrelated_write_minimum(observed_count, minimum_count=minimum_count)


@dataclass(slots=True)
class _FakeCacheCore:
    active_databases: list[str]

    def active_stream_cost_databases(self) -> list[str]:
        return self.active_databases


@dataclass(slots=True)
class _FakeManagerWithCacheCore:
    cache_core: _FakeCacheCore


@pytest.mark.parametrize(
    "active_databases",
    [[], ["other"], ["db", "other"]],
)
def test_verify_single_consolidated_stream_rejects_anything_but_exactly_one(
    active_databases: list[str],
) -> None:
    fake_manager = _FakeManagerWithCacheCore(_FakeCacheCore(active_databases))
    with pytest.raises(BenchmarkSetupError, match="exactly one consolidated stream"):
        verify_single_consolidated_stream(
            cast("CacheManager[dict[str, Any]]", fake_manager), database="db"
        )


def test_verify_single_consolidated_stream_accepts_a_single_matching_stream() -> None:
    fake_manager = _FakeManagerWithCacheCore(_FakeCacheCore(["db"]))
    verify_single_consolidated_stream(
        cast("CacheManager[dict[str, Any]]", fake_manager), database="db"
    )


class _FakeClosableManager:
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeDropDatabaseClient:
    __slots__ = ("dropped_databases",)

    def __init__(self) -> None:
        self.dropped_databases: list[str] = []

    def drop_database(self, name: str) -> None:
        self.dropped_databases.append(name)


def test_reset_run_state_closes_the_previous_manager_and_drops_the_database() -> None:
    fake_client = _FakeDropDatabaseClient()
    fake_previous_manager = _FakeClosableManager()
    new_manager = reset_run_state(
        cast("MongoClient[dict[str, Any]]", fake_client),
        cast("CacheManager[dict[str, Any]]", fake_previous_manager),
        database="benchmark_db",
    )
    try:
        assert fake_previous_manager.closed is True
        assert fake_client.dropped_databases == ["benchmark_db"]
        assert isinstance(new_manager, CacheManager)
    finally:
        new_manager.close()


def test_reset_run_state_accepts_no_previous_manager() -> None:
    fake_client = _FakeDropDatabaseClient()
    new_manager = reset_run_state(
        cast("MongoClient[dict[str, Any]]", fake_client),
        None,
        database="benchmark_db",
    )
    try:
        assert fake_client.dropped_databases == ["benchmark_db"]
    finally:
        new_manager.close()

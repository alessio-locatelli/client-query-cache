from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self
from unittest.mock import MagicMock

import pytest

from benchmarks.stream_cost import compression_matrix_runner as runner_module
from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec
from benchmarks.stream_cost.compression_matrix_runner import (
    _invalidation_latencies,
    _issue_cache_reads,
    _prime_cache_reads,
    _run_stream_watching_window,
    _seed_window_dataset,
    _write_schedule,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.generators import SMALL_DOCUMENT_PROFILE
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind
from client_query_cache._core.stream_cost import InvalidationApplyReading
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt

pytestmark = pytest.mark.unit


def _window(
    *,
    kind: WorkloadKind = WorkloadKind.BALANCED,
    writes: NonNegativeInt = 3,
    seed: int = 5,
) -> CompressionWindowSpec:
    sampling = (
        OperationCounts(reads=0, writes=0)
        if kind is WorkloadKind.IDLE
        else OperationCounts(reads=1, writes=writes)
    )
    return CompressionWindowSpec(
        kind=kind,
        data_size=SMALL_DOCUMENT_PROFILE,
        document_count=10,
        duration_seconds=5.0,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=sampling,
        seed=seed,
    )


def test_write_schedule_is_empty_when_no_writes_are_sampled() -> None:
    window = _window(kind=WorkloadKind.IDLE, writes=0)
    assert _write_schedule(window) == ()


def test_write_schedule_has_one_offset_per_write_and_is_deterministic() -> None:
    window = _window(writes=4)
    first = _write_schedule(window)
    second = _write_schedule(window)
    assert len(first) == 4
    assert first == second
    assert list(first) == sorted(first)


def test_seed_window_dataset_is_deterministic_and_sized() -> None:
    window = _window()
    first = _seed_window_dataset(window)
    second = _seed_window_dataset(window)
    assert first == second
    assert len(first.documents) == 10


def test_invalidation_latencies_is_empty_without_scheduled_writes() -> None:
    assert _invalidation_latencies((), 0.0, ()) == ()


def _reading(monotonic_seconds: NonNegativeFloat) -> InvalidationApplyReading:
    return InvalidationApplyReading(
        wall_seconds=monotonic_seconds, monotonic_seconds=monotonic_seconds
    )


def test_invalidation_latencies_pairs_offsets_with_the_most_recent_readings() -> None:
    readings = (_reading(100.0), _reading(101.5), _reading(103.0))
    latencies = _invalidation_latencies((0.0, 1.0, 2.0), 100.0, readings)
    assert latencies == pytest.approx((0.0, 0.5, 1.0))


def test_invalidation_latencies_rejects_fewer_readings_than_writes() -> None:
    readings = (_reading(100.0),)
    with pytest.raises(BenchmarkSetupError, match="invalidation-apply readings"):
        _invalidation_latencies((0.0, 1.0), 100.0, readings)


class _RecordingCachedCollection:
    __slots__ = ("finds",)

    def __init__(self) -> None:
        self.finds: list[object] = []

    def find_one(self, query: BsonDict) -> None:
        self.finds.append(query["_id"])


def test_prime_cache_reads_touches_every_distinct_sampled_id_plus_one_repeat() -> None:
    collection: Any = _RecordingCachedCollection()
    dataset = _seed_window_dataset(_window())
    read_ids = (dataset.ids[2], dataset.ids[5], dataset.ids[2], dataset.ids[7])

    _prime_cache_reads(collection, dataset=dataset, read_ids=read_ids, warmup_reads=2)

    assert collection.finds == [
        dataset.ids[2],
        dataset.ids[5],
        dataset.ids[7],
        dataset.ids[2],
    ]


def test_prime_cache_reads_falls_back_to_the_first_dataset_id_when_idle() -> None:
    collection: Any = _RecordingCachedCollection()
    dataset = _seed_window_dataset(_window())

    _prime_cache_reads(collection, dataset=dataset, read_ids=(), warmup_reads=2)

    assert collection.finds == [dataset.ids[0], dataset.ids[0]]


@dataclass(frozen=True, slots=True)
class _FakeSnapshot:
    hits: NonNegativeInt
    misses: NonNegativeInt


class _FakeCacheCore:
    __slots__ = ("_active_databases", "_snapshot_calls")

    def __init__(self, active_databases: list[str]) -> None:
        self._active_databases = active_databases
        self._snapshot_calls = 0

    def snapshot(self) -> _FakeSnapshot:
        self._snapshot_calls += 1
        return _FakeSnapshot(hits=self._snapshot_calls, misses=self._snapshot_calls)

    def active_stream_cost_databases(self) -> list[str]:
        return self._active_databases


class _StaticCacheManager:
    __slots__ = ("cache_core",)

    def __init__(self) -> None:
        self.cache_core = self

    @staticmethod
    def snapshot() -> _FakeSnapshot:
        return _FakeSnapshot(hits=0, misses=0)


def test_issue_cache_reads_rejects_a_primed_read_that_was_not_a_hit() -> None:
    collection: Any = _RecordingCachedCollection()
    manager: Any = _StaticCacheManager()
    with pytest.raises(BenchmarkSetupError, match="was not a hit"):
        _issue_cache_reads(collection, manager, ["missing_id"], latencies=[])


class _FakeCachedCollection:
    __slots__ = ()

    @staticmethod
    def find_one(query: BsonDict) -> None:
        del query


class _FakeRawDatabase:
    __slots__ = ()

    def __getitem__(self, name: str) -> _FakeCachedCollection:
        del name
        return _FakeCachedCollection()


class _FakeCachedDatabase:
    __slots__ = ()

    def __getitem__(self, name: str) -> _FakeCachedCollection:
        del name
        return _FakeCachedCollection()

    @property
    def raw(self) -> _FakeRawDatabase:
        return _FakeRawDatabase()


class _FakeCacheManager:
    __slots__ = ("cache_core",)

    def __init__(self, active_databases: list[str]) -> None:
        self.cache_core = _FakeCacheCore(active_databases)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info

    def __getitem__(self, name: str) -> _FakeCachedDatabase:
        del name
        return _FakeCachedDatabase()


def test_run_stream_watching_window_rejects_an_unhealthy_stream_before_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner_module,
        "CacheManager",
        lambda _client: _FakeCacheManager(["other_database"]),
    )
    window = _window()
    dataset = _seed_window_dataset(window)
    with pytest.raises(BenchmarkSetupError, match="expected exactly one stream"):
        _run_stream_watching_window(
            window,
            dataset,
            client=MagicMock(),
            database_name="expected_database",
            replica_set=MagicMock(),
            proxy=None,
        )

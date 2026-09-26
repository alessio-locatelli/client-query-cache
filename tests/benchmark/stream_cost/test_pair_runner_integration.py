from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from benchmarks.stream_cost import pair_runner
from benchmarks.stream_cost.calibration import TopologyChangeListener
from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    build_dedicated_client,
)
from benchmarks.stream_cost.consolidated_stream import (
    ConsolidatedStreamPairConfig,
    PairVariant,
    counterbalanced_pair_order,
    generate_relevant_write_schedule,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.pair_runner import run_consolidated_stream_pair
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pymongo import MongoClient

    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration

_TOPOLOGY_CONFIG = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compression_enabled=False,
    discovery_enabled=False,
    shared_connections=False,
)


@pytest.fixture
def dedicated_client_and_listener(
    mongodb_uri: MongoDbUri,
) -> Iterator[tuple[MongoClient[dict[str, Any]], TopologyChangeListener]]:
    listener = TopologyChangeListener()
    client = build_dedicated_client(
        mongodb_uri, _TOPOLOGY_CONFIG, event_listeners=[listener]
    )
    yield client, listener
    client.close()


@pytest.fixture
def database(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
) -> Iterator[str]:
    client, _listener = dedicated_client_and_listener
    name = f"test_{uuid.uuid4().hex}"
    yield name
    client.drop_database(name)


@pytest.fixture
def cache_manager_factory(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
    request: pytest.FixtureRequest,
) -> Callable[[CacheCoreConfig | None], CacheManager[dict[str, Any]]]:
    client, _listener = dedicated_client_and_listener

    def create_cache_manager(
        cache_config: CacheCoreConfig | None = None,
    ) -> CacheManager[dict[str, Any]]:
        manager = CacheManager(client, cache_config=cache_config)
        request.addfinalizer(manager.close)
        return manager

    return create_cache_manager


def test_run_consolidated_stream_pair_produces_a_lag_distribution_per_run(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
    database: str,
) -> None:
    client, listener = dedicated_client_and_listener
    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=4,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=2,
        unrelated_write_interval_seconds=0.02,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.1,
        pair_count=3,
        warmup_duration_seconds=0.05,
    )
    schedule = generate_relevant_write_schedule(4, total_duration_seconds=0.3, seed=1)
    order = counterbalanced_pair_order(config.pair_count)[0]
    cache_config = CacheCoreConfig(
        lag_capture_window_config=LagCaptureWindowConfig(
            window_count=2, events_per_window=2, min_separation_events=0
        )
    )

    pair_result = run_consolidated_stream_pair(
        client,
        listener,
        database=database,
        relevant_collection_names=["relevant_a", "relevant_b"],
        unrelated_collection_name="unrelated",
        config=config,
        schedule=schedule,
        order=order,
        cache_config=cache_config,
    )

    assert order == (PairVariant.CONTROL, PairVariant.LOADED)
    assert pair_result.control.relevant_write_count == 4
    assert pair_result.loaded.relevant_write_count == 4
    assert pair_result.control.unrelated_write_count_during_window == 0
    assert pair_result.loaded.unrelated_write_count_during_window >= 2
    assert pair_result.calibration.has_election_change is False
    assert len(pair_result.control.raw_lag_windows) == 2
    assert len(pair_result.loaded.raw_lag_windows) == 2
    assert sum(len(window) for window in pair_result.control.raw_lag_windows) == 4
    assert sum(len(window) for window in pair_result.loaded.raw_lag_windows) == 4


def test_run_consolidated_stream_pair_rejects_a_run_with_too_few_lag_samples(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
    database: str,
) -> None:
    client, listener = dedicated_client_and_listener
    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=1,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=1,
        unrelated_write_interval_seconds=0.5,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.5,
        pair_count=3,
        warmup_duration_seconds=0.01,
    )
    schedule = generate_relevant_write_schedule(1, total_duration_seconds=0.05, seed=1)
    order = counterbalanced_pair_order(config.pair_count)[0]

    with pytest.raises(BenchmarkSetupError, match="invalidation-lag samples"):
        run_consolidated_stream_pair(
            client,
            listener,
            database=database,
            relevant_collection_names=["relevant_a", "relevant_b"],
            unrelated_collection_name="unrelated",
            config=config,
            schedule=schedule,
            order=order,
        )


def test_run_consolidated_stream_pair_rejects_a_run_with_too_few_windows(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
    database: str,
) -> None:
    client, listener = dedicated_client_and_listener
    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=2,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=1,
        unrelated_write_interval_seconds=0.5,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.5,
        pair_count=3,
        warmup_duration_seconds=0.01,
    )
    schedule = generate_relevant_write_schedule(2, total_duration_seconds=0.05, seed=1)
    order = counterbalanced_pair_order(config.pair_count)[0]
    cache_config = CacheCoreConfig(
        lag_capture_window_config=LagCaptureWindowConfig(
            window_count=1, events_per_window=2, min_separation_events=0
        )
    )

    with pytest.raises(BenchmarkSetupError, match="capture window"):
        run_consolidated_stream_pair(
            client,
            listener,
            database=database,
            relevant_collection_names=["relevant_a", "relevant_b"],
            unrelated_collection_name="unrelated",
            config=config,
            schedule=schedule,
            order=order,
            cache_config=cache_config,
        )


def test_execute_run_reports_observed_invalidations_not_the_schedule_length(
    monkeypatch: pytest.MonkeyPatch,
    database: str,
    cache_manager_factory: Callable[
        [CacheCoreConfig | None], CacheManager[dict[str, Any]]
    ],
) -> None:
    cache_config = CacheCoreConfig(
        lag_capture_window_config=LagCaptureWindowConfig(
            window_count=2, events_per_window=1, min_separation_events=0
        )
    )
    manager = cache_manager_factory(cache_config)

    def double_issue_replay(
        issue_write: Callable[[], None], *_args: object, **_kwargs: object
    ) -> tuple[float, ...]:
        issue_write()
        issue_write()
        pair_runner._await_condition(
            lambda: (
                manager.cache_core.stream_cost_snapshot(database).invalidations >= 2
            ),
            timeout_seconds=5.0,
            poll_interval_seconds=0.01,
            timeout_message="the second invalidation was not observed in time",
        )
        return (0.0, 0.01)

    monkeypatch.setattr(pair_runner, "replay_write_schedule", double_issue_replay)

    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=1,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=1,
        unrelated_write_interval_seconds=0.5,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.5,
        pair_count=3,
        warmup_duration_seconds=0.01,
    )

    run_result = pair_runner._execute_run(
        manager,
        database=database,
        relevant_collection_names=["relevant_a", "relevant_b"],
        unrelated_collection_name="unrelated",
        config=config,
        schedule=(0.0,),
        variant=PairVariant.CONTROL,
    )

    assert run_result.relevant_write_count == 2


class _RecordingUnrelatedWriteWorkload:
    __slots__ = ("stopped",)
    instances: ClassVar[list[_RecordingUnrelatedWriteWorkload]] = []

    def __init__(self, _collection: object, *, interval_seconds: float) -> None:
        del interval_seconds
        self.stopped = False
        type(self).instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> int:
        self.stopped = True
        return 0


def test_execute_run_stops_the_unrelated_writer_when_replay_fails(
    monkeypatch: pytest.MonkeyPatch,
    database: str,
    cache_manager_factory: Callable[
        [CacheCoreConfig | None], CacheManager[dict[str, Any]]
    ],
) -> None:
    manager = cache_manager_factory(None)

    _RecordingUnrelatedWriteWorkload.instances.clear()
    monkeypatch.setattr(
        pair_runner, "UnrelatedWriteWorkload", _RecordingUnrelatedWriteWorkload
    )

    def failing_replay(
        issue_write: Callable[[], None], *_args: object, **_kwargs: object
    ) -> None:
        issue_write()
        message = "simulated replay failure"
        raise BenchmarkSetupError(message)

    monkeypatch.setattr(pair_runner, "replay_write_schedule", failing_replay)

    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=1,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=1,
        unrelated_write_interval_seconds=0.5,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.5,
        pair_count=3,
        warmup_duration_seconds=0.01,
    )

    with pytest.raises(BenchmarkSetupError, match="simulated replay failure"):
        pair_runner._execute_run(
            manager,
            database=database,
            relevant_collection_names=["relevant_a", "relevant_b"],
            unrelated_collection_name="unrelated",
            config=config,
            schedule=(0.0,),
            variant=PairVariant.LOADED,
        )

    assert len(_RecordingUnrelatedWriteWorkload.instances) == 1
    assert _RecordingUnrelatedWriteWorkload.instances[0].stopped is True

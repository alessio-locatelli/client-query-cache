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
from mongo_client_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def test_run_consolidated_stream_pair_produces_a_lag_distribution_per_run(
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
) -> None:
    client, listener = dedicated_client_and_listener
    database = f"test_{uuid.uuid4().hex}"
    config = ConsolidatedStreamPairConfig(
        acceptable_lag_percentile=0.5,
        acceptable_lag_threshold_seconds=5.0,
        relevant_write_count=3,
        relevant_write_schedule_tolerance_seconds=1.0,
        relevant_write_count_tolerance=0,
        unrelated_write_minimum_count=2,
        unrelated_write_interval_seconds=0.02,
        clock_drift_tolerance_seconds=1.0,
        calibration_cadence_seconds=0.1,
        pair_count=3,
        warmup_duration_seconds=0.05,
    )
    schedule = generate_relevant_write_schedule(3, total_duration_seconds=0.3, seed=1)
    order = counterbalanced_pair_order(config.pair_count)[0]

    pair_result = run_consolidated_stream_pair(
        client,
        listener,
        database=database,
        relevant_collection_names=["relevant_a", "relevant_b"],
        unrelated_collection_name="unrelated",
        config=config,
        schedule=schedule,
        order=order,
    )

    assert order == (PairVariant.CONTROL, PairVariant.LOADED)
    assert pair_result.control.relevant_write_count == 3
    assert pair_result.loaded.relevant_write_count == 3
    assert pair_result.control.unrelated_write_count_during_window == 0
    assert pair_result.loaded.unrelated_write_count_during_window >= 2
    assert pair_result.calibration.has_election_change is False

    client.drop_database(database)


class _RecordingUnrelatedWriteWorkload:
    __slots__ = ("stopped",)
    instances: ClassVar[list[_RecordingUnrelatedWriteWorkload]] = []

    def __init__(self, _collection: object, *, interval_seconds: float) -> None:
        del interval_seconds
        self.stopped = False
        type(self).instances.append(self)

    def start(self) -> None:
        pass

    @property
    def count(self) -> int:
        return 0

    def stop(self) -> int:
        self.stopped = True
        return 0


def test_execute_run_stops_the_unrelated_writer_when_replay_fails(
    monkeypatch: pytest.MonkeyPatch,
    dedicated_client_and_listener: tuple[
        MongoClient[dict[str, Any]], TopologyChangeListener
    ],
) -> None:
    client, _listener = dedicated_client_and_listener
    database = f"test_{uuid.uuid4().hex}"
    manager = CacheManager(client)

    _RecordingUnrelatedWriteWorkload.instances.clear()
    monkeypatch.setattr(
        pair_runner, "UnrelatedWriteWorkload", _RecordingUnrelatedWriteWorkload
    )

    def failing_replay(*_args: object, **_kwargs: object) -> None:
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

    try:
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
    finally:
        manager.close()
        client.drop_database(database)

    assert len(_RecordingUnrelatedWriteWorkload.instances) == 1
    assert _RecordingUnrelatedWriteWorkload.instances[0].stopped is True

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from benchmarks.stream_cost.await_run import (
    run_bounded_shutdown,
    run_shutdown,
    run_window,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._core.manager import CacheCore

if TYPE_CHECKING:
    from collections.abc import Iterator

    from benchmarks.stream_cost.await_model import (
        AwaitConfiguration,
        AwaitWorkload,
        ExecutionModel,
    )

pytestmark = pytest.mark.integration

# Short instrumentation checks are excluded from the registered decision matrix.
_INSTRUMENTATION_AWAIT_MS = 20


@pytest.fixture(scope="module")
def await_replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=1, memory="512m")) as replica:
        yield replica


@pytest.fixture
def instrumentation_configuration() -> AwaitConfiguration:
    configuration = cast(
        "AwaitConfiguration",
        json.loads(Path("reports/stream-cost/await-v1/config.v1.json").read_bytes()),
    )
    configuration.update(
        {
            "warmup_seconds": 0.05,
            "idle_minimum_seconds": 0.1,
            "active_window_seconds": 0.2,
            "write_offsets_seconds": {
                "paced": [0, 0.02, 0.04],
                "burst": [0, 0.001, 0.002],
            },
            "shutdown_trial_offsets_seconds": [0.005],
            "write_schedule_tolerance_seconds": {"paced": 0.5, "burst": 0.5},
        }
    )
    return configuration


@pytest.mark.parametrize("model", ["sync", "async"])
@pytest.mark.parametrize("workload", ["idle", "paced", "burst"])
async def test_observes_real_workload_resources_and_events(
    await_replica: IsolatedReplicaSet,
    instrumentation_configuration: AwaitConfiguration,
    model: ExecutionModel,
    workload: AwaitWorkload,
) -> None:
    sample = await run_window(
        await_replica,
        instrumentation_configuration,
        block=0,
        candidate=_INSTRUMENTATION_AWAIT_MS,
        model=model,
        workload=workload,
    )
    assert sample.healthy
    assert sample.server_cpu_seconds is not None
    assert sample.server_cpu_seconds > 0
    assert sample.client_cpu_seconds is not None
    assert sample.client_cpu_seconds > 0
    assert sample.bytes_sent is not None
    assert sample.bytes_sent > 0
    assert sample.bytes_received is not None
    assert sample.bytes_received > 0
    assert sample.getmore_completed >= 2
    assert sample.getmore_started + sample.getmore_inflight_at_start == len(
        sample.requested_max_time_ms
    )
    assert set(sample.requested_max_time_ms) == {_INSTRUMENTATION_AWAIT_MS}
    assert sample.command_failures == 0
    if workload == "idle":
        assert sample.getmore_inflight_at_start == 0
        assert sample.invalidations == 0
        assert sample.lag_seconds == ()
    else:
        assert sample.invalidations == len(sample.lag_seconds) == 3
        assert all(value >= 0 for value in sample.lag_seconds)


@pytest.mark.parametrize("model", ["sync", "async"])
async def test_observes_shutdown_during_a_real_getmore(
    await_replica: IsolatedReplicaSet,
    instrumentation_configuration: AwaitConfiguration,
    model: ExecutionModel,
) -> None:
    sample = await run_shutdown(
        await_replica.uri,
        instrumentation_configuration,
        block=0,
        candidate=_INSTRUMENTATION_AWAIT_MS,
        model=model,
    )
    assert sample.shutdown_inflight == (True,)
    assert sample.getmore_inflight_at_start == 1
    assert len(sample.shutdown_seconds) == 1
    assert sample.shutdown_seconds[0] > 0
    assert sample.server_cpu_seconds is None
    assert sample.bytes_received is None


@pytest.mark.parametrize("model", ["sync", "async"])
def test_bounded_shutdown_returns_real_observations(
    await_replica: IsolatedReplicaSet,
    instrumentation_configuration: AwaitConfiguration,
    model: ExecutionModel,
) -> None:
    sample = run_bounded_shutdown(
        await_replica.uri,
        instrumentation_configuration,
        block=0,
        candidate=_INSTRUMENTATION_AWAIT_MS,
        model=model,
    )
    assert sample.shutdown_inflight == (True,)
    assert sample.getmore_inflight_at_start == 1
    assert sample.getmore_completed in {0, 1}


@pytest.mark.parametrize("failure", ["cpu-observer", "stream-health", "write-schedule"])
async def test_rejects_invalid_workload_measurements(
    await_replica: IsolatedReplicaSet,
    instrumentation_configuration: AwaitConfiguration,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    workload: AwaitWorkload = "idle"
    if failure == "cpu-observer":
        monkeypatch.setattr(
            IsolatedReplicaSet,
            "container_cpu_usage_seconds",
            Mock(side_effect=BenchmarkSetupError("CPU observer unavailable")),
        )
        message = "CPU observer unavailable"
    elif failure == "stream-health":
        monkeypatch.setattr(
            CacheCore, "is_database_available", lambda _self, _database: False
        )
        message = "stream health"
    else:
        instrumentation_configuration["write_schedule_tolerance_seconds"]["paced"] = 0
        workload = "paced"
        message = "write schedule"
    with pytest.raises(BenchmarkSetupError, match=message):
        await run_window(
            await_replica,
            instrumentation_configuration,
            block=0,
            candidate=_INSTRUMENTATION_AWAIT_MS,
            model="sync",
            workload=workload,
        )


@pytest.mark.parametrize("failure", ["completed-wait", "late-close"])
async def test_rejects_shutdown_outside_registered_phase(
    await_replica: IsolatedReplicaSet,
    instrumentation_configuration: AwaitConfiguration,
    failure: str,
) -> None:
    if failure == "completed-wait":
        instrumentation_configuration["shutdown_trial_offsets_seconds"] = [0.1]
        message = "in-flight getMore"
    else:
        instrumentation_configuration["shutdown_schedule_tolerance_seconds"] = 0
        message = "shutdown schedule"
    with pytest.raises(BenchmarkSetupError, match=message):
        await run_shutdown(
            await_replica.uri,
            instrumentation_configuration,
            block=0,
            candidate=_INSTRUMENTATION_AWAIT_MS,
            model="sync",
        )

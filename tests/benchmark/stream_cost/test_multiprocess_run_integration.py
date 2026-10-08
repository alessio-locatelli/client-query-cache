from __future__ import annotations

import multiprocessing
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from pymongo.errors import ConnectionFailure
from pymongo.synchronous.collection import Collection

from benchmarks.stream_cost.calibration import PeriodicCalibrationSampler
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import Protocol, planned_cells, run_cell
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from collections.abc import Iterator

from benchmarks.stream_cost.multiprocess_run import Model, PathKind, Payload

pytestmark = pytest.mark.integration
_ORIGINAL_CALIBRATION_STOP = PeriodicCalibrationSampler.stop


def _stop_then_fail(sampler: PeriodicCalibrationSampler) -> None:
    _ORIGINAL_CALIBRATION_STOP(sampler)
    raise BenchmarkSetupError("clock observer failed")


@pytest.fixture(scope="module")
def multiprocess_replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=2, memory="2g")) as replica:
        yield replica


@pytest.fixture
def smoke_protocol() -> Protocol:
    return Protocol.smoke()


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
@pytest.mark.parametrize(
    "path",
    ["native-control", "native", "stream-control", "stream-only"],
    ids=["raw-reads", "cache-reads", "no-stream", "stream-only"],
)
def test_child_owned_clients_and_resource_measurements(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    model: Model,
    path: PathKind,
) -> None:
    cell = replace(
        planned_cells()[0], model=model, path=path, workers=2, workload="active"
    )
    sample = run_cell(multiprocess_replica, cell, smoke_protocol)
    assert sample["healthy"]
    assert sample["actual_streams"] == (2 if path in {"native", "stream-only"} else 0)
    workers = cast("tuple[Payload, ...]", sample["workers_measured"])
    assert len({worker["pid"] for worker in workers}) == 2
    assert all(worker["pid"] != sample["harness_pid"] for worker in workers)
    assert cast("float", sample["server_cpu_seconds"]) > 0
    assert cast("float", sample["harness_cpu_seconds"]) >= 0
    assert all(
        cast("float", worker["worker_cpu_seconds"]) >= 0
        and cast("int", worker["uss_bytes"]) > 0
        for worker in workers
    )
    assert all(
        cast("int", worker["bytes_sent"]) >= 0
        and cast("int", worker["bytes_received"]) >= 0
        for worker in workers
    )
    harness_paths = cast("dict[str, Payload]", sample["harness_paths"])
    writer_commands = cast("dict[str, int]", harness_paths["writer"]["wire_commands"])
    observer_commands = cast(
        "dict[str, int]", harness_paths["observer"]["wire_commands"]
    )
    assert (
        writer_commands["update:requested"] == writer_commands["update:completed"] == 4
    )
    assert observer_commands["hello:requested"] > 0
    assert observer_commands["hello:completed"] > 0
    expected_events = 4 if path in {"native", "stream-only"} else 0
    assert all(worker["invalidations"] == expected_events for worker in workers)
    assert sum(
        len(cast("list[float]", worker["read_offsets_seconds"])) for worker in workers
    ) == (20 if path in {"native", "native-control"} else 0)
    if path == "native":
        assert all(
            cast("Payload", worker["primed"])["entry_count"] == 16 for worker in workers
        )


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
def test_real_capture_retains_every_registered_event_and_gap(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    model: Model,
) -> None:
    protocol = replace(
        smoke_protocol, updates=200, update_interval_seconds=0.01, window_seconds=2.2
    )
    cell = replace(planned_cells()[0], model=model, path="native", workload="active")
    sample = run_cell(multiprocess_replica, cell, protocol)
    worker = cast("tuple[Payload, ...]", sample["workers_measured"])[0]
    assert worker["invalidations"] == 200
    assert (
        tuple(map(len, cast("tuple[tuple[float, ...], ...]", worker["lag_windows"])))
        == (20,) * 6
    )
    assert len(cast("tuple[tuple[int, ...], ...]", worker["capture_ordinals"])) == 6


@pytest.mark.parametrize(
    "failure",
    ["cpu", "writer", "observer"],
    ids=["missing-server-cpu", "failed-writer-command", "failed-clock-observer"],
)
def test_harness_failures_reclaim_children(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure == "cpu":
        monkeypatch.setattr(
            IsolatedReplicaSet,
            "container_cpu_usage_seconds",
            Mock(side_effect=BenchmarkSetupError("server CPU unavailable")),
        )
        message = "server CPU unavailable"
    elif failure == "writer":
        monkeypatch.setattr(
            Collection,
            "update_one",
            Mock(side_effect=ConnectionFailure("writer unavailable")),
        )
        message = "harness MongoDB operation failed"
    else:
        monkeypatch.setattr(PeriodicCalibrationSampler, "stop", _stop_then_fail)
        message = "clock observer failed"
    with pytest.raises(BenchmarkSetupError, match=message):
        run_cell(
            multiprocess_replica,
            replace(planned_cells()[0], workload="active"),
            smoke_protocol,
        )
    assert not multiprocessing.active_children()

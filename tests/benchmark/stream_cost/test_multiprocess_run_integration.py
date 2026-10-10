from __future__ import annotations

import asyncio
import multiprocessing
import time
from dataclasses import replace
from functools import partial, partialmethod
from typing import TYPE_CHECKING, Literal, cast
from unittest.mock import AsyncMock, Mock

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.synchronous.collection import Collection

from benchmarks.stream_cost import multiprocess_run
from benchmarks.stream_cost.calibration import (
    CalibrationSeries,
    PeriodicCalibrationSampler,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import Protocol, planned_cells, run_cell
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import CacheManager
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_health import (
    StreamHealthSnapshot,
    StreamHealthStatus,
)
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.connection import Connection
    from pathlib import Path

    from pymongo.monitoring import CommandStartedEvent

from benchmarks.stream_cost.multiprocess_run import Model, PathKind, Payload

pytestmark = pytest.mark.integration
_ORIGINAL_CALIBRATION_STOP = PeriodicCalibrationSampler.stop
_ORIGINAL_SNAPSHOT = multiprocess_run.WireCommands.snapshot
_ORIGINAL_SYNC_CLOSE = MongoClient.close
_ORIGINAL_ASYNC_CLOSE = AsyncMongoClient.close
_ORIGINAL_WORKER_MAIN = multiprocess_run.worker_main
_ORIGINAL_CONSUME = multiprocess_run.consume_stream
_ORIGINAL_STARTED = multiprocess_run.WireCommands.started
_ORIGINAL_EVENT_TIMES = multiprocess_run.WireCommands.event_wall_seconds
_ORIGINAL_WAIT_UNTIL = multiprocess_run.wait_until


def _stop_then_fail(sampler: PeriodicCalibrationSampler) -> None:
    _ORIGINAL_CALIBRATION_STOP(sampler)
    raise BenchmarkSetupError("clock observer failed")


def _hide_polls(
    listener: multiprocess_run.WireCommands, *, absent: bool
) -> dict[str, NonNegativeInt]:
    commands = _ORIGINAL_SNAPSHOT(listener)
    if absent:
        return {
            key: count for key, count in commands.items() if key != "getMore:completed"
        }
    commands["getMore:completed"] = 0
    return commands


async def _close_then_fail(client: multiprocess_run.Client) -> None:
    if isinstance(client, MongoClient):
        _ORIGINAL_SYNC_CLOSE(client)
    else:
        await _ORIGINAL_ASYNC_CLOSE(client)
    raise ConnectionFailure("cleanup failed after sample")


async def _poll_then_stall(
    stream: multiprocess_run.Stream,
    _observed: list[NonNegativeFloat],
    *,
    gate: asyncio.Event,
) -> None:
    await gate.wait()
    await multiprocess_run.invoke(stream.try_next)
    await asyncio.Event().wait()


def _extra_stream(
    listener: multiprocess_run.WireCommands, event: CommandStartedEvent
) -> None:
    _ORIGINAL_STARTED(listener, event)
    if event.command_name == "aggregate":
        listener.streams += 1


def _faulty_commands(
    listener: multiprocess_run.WireCommands, *, fault: str, uri: str
) -> dict[str, NonNegativeInt]:
    if fault == "document":
        with MongoClient[BsonDict](uri) as client:
            client[multiprocess_run._DATABASE][
                Protocol.load().registration["collections"][0]
            ].delete_one({"_id": 0})
    elif fault == "stream-count":
        listener.streams += 1
    else:
        listener._record("find", "failed")
    return _ORIGINAL_SNAPSHOT(listener)


def _shift_event_time(
    listener: multiprocess_run.WireCommands,
) -> tuple[NonNegativeFloat, ...]:
    stamps = _ORIGINAL_EVENT_TIMES(listener)
    return (stamps[0] + 0.001, *stamps[1:])


async def _alter_stream_observations(
    stream: multiprocess_run.Stream, observed: list[NonNegativeFloat]
) -> None:
    observed.append(time.monotonic())
    await _ORIGINAL_CONSUME(stream, observed)


async def _consume_after_window(
    stream: multiprocess_run.Stream,
    observed: list[NonNegativeFloat],
    *,
    gate: asyncio.Event,
) -> None:
    await gate.wait()
    await _ORIGINAL_CONSUME(stream, observed)


async def _release_after_phase(
    deadline: NonNegativeFloat,
    tolerance: PositiveFloat,
    phase: Literal["start", "read", "end"],
    *,
    gate: asyncio.Event,
    release_phase: Literal["start", "end"],
) -> None:
    await _ORIGINAL_WAIT_UNTIL(deadline, tolerance, phase)
    if phase == release_phase:
        asyncio.get_running_loop().call_later(0.1, gate.set)


def _faulty_worker(
    connection: Connection,
    uri: str,
    cell: multiprocess_run.Cell,
    worker: NonNegativeInt,
    protocol: Protocol,
    *,
    fault: str,
    cleanup_marker: Path,
) -> None:
    with pytest.MonkeyPatch.context() as patches:
        if fault in {"receiver", "slow-failure"}:
            patches.setattr(
                multiprocess_run, "consume_stream", AsyncMock(return_value=None)
            )
        elif fault == "stalled-polls":
            gate = asyncio.Event()
            patches.setattr(
                multiprocess_run, "consume_stream", partial(_poll_then_stall, gate=gate)
            )
            patches.setattr(
                multiprocess_run,
                "wait_until",
                partial(_release_after_phase, gate=gate, release_phase="start"),
            )
        elif fault in {"absent", "zero"}:
            patches.setattr(
                multiprocess_run.WireCommands,
                "snapshot",
                partialmethod(_hide_polls, absent=fault == "absent"),
            )
        elif fault == "streams":
            patches.setattr(multiprocess_run.WireCommands, "started", _extra_stream)
        elif fault == "startup":
            patches.setattr(
                CacheManager,
                "stream_health_snapshot",
                Mock(
                    return_value=StreamHealthSnapshot(
                        multiprocess_run._DATABASE, StreamHealthStatus.STARTUP_FAILED
                    )
                ),
            )
        elif fault == "budget":
            patches.setattr(
                multiprocess_run,
                "CacheCoreConfig",
                partial(
                    CacheCoreConfig,
                    shared_budget_bytes=1,
                    max_entry_bytes=1,
                ),
            )
        elif fault in {"document", "stream-count", "wire"}:
            patches.setattr(
                multiprocess_run.WireCommands,
                "snapshot",
                partialmethod(_faulty_commands, fault=fault, uri=uri),
            )
        elif fault == "lag":
            patches.setattr(
                multiprocess_run.WireCommands, "event_wall_seconds", _shift_event_time
            )
        elif fault == "drain":
            gate = asyncio.Event()
            patches.setattr(
                multiprocess_run,
                "consume_stream",
                partial(_consume_after_window, gate=gate),
            )
            patches.setattr(
                multiprocess_run,
                "wait_until",
                partial(_release_after_phase, gate=gate, release_phase="end"),
            )
        elif fault == "extra-observation":
            patches.setattr(
                multiprocess_run,
                "consume_stream",
                _alter_stream_observations,
            )
        else:
            patches.setattr(MongoClient, "close", _close_then_fail)
            patches.setattr(AsyncMongoClient, "close", _close_then_fail)
        try:
            _ORIGINAL_WORKER_MAIN(connection, uri, cell, worker, protocol)
        finally:
            if fault == "slow-failure":
                time.sleep(0.1)
                cleanup_marker.write_text("closed", encoding="utf-8")


@pytest.fixture
def faulty_worker(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    cleanup_marker = tmp_path / "worker-cleanup.txt"
    monkeypatch.setattr(
        multiprocess_run,
        "worker_main",
        partial(_faulty_worker, fault=request.param, cleanup_marker=cleanup_marker),
    )
    return cleanup_marker


@pytest.mark.parametrize(
    "faulty_worker", ["slow-failure"], indirect=True, ids=["failed-worker-teardown"]
)
def test_failed_worker_finishes_cleanup_before_reclamation(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    faulty_worker: Path,
) -> None:
    with pytest.raises(BenchmarkSetupError, match="stream receiver stopped"):
        run_cell(
            multiprocess_replica,
            replace(planned_cells()[0], path="stream-only", workload="idle"),
            smoke_protocol,
        )
    assert faulty_worker.read_text(encoding="utf-8") == "closed"


@pytest.fixture(scope="module")
def multiprocess_replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=2, memory="2g")) as replica:
        yield replica


@pytest.fixture
def smoke_protocol() -> Protocol:
    # Instrumentation tests tolerate coverage/xdist scheduling jitter.
    return replace(Protocol.smoke(), schedule_tolerance_seconds=0.5)


@pytest.fixture
def capture_protocol(smoke_protocol: Protocol) -> Protocol:
    return replace(
        smoke_protocol,
        updates=200,
        update_interval_seconds=0.01,
        window_seconds=2.2,
        schedule_tolerance_seconds=smoke_protocol.drain_seconds,
    )


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
    assert cast("NonNegativeFloat", sample["server_cpu_seconds"]) > 0
    assert cast("NonNegativeFloat", sample["harness_cpu_seconds"]) >= 0
    assert all(
        cast("NonNegativeFloat", worker["worker_cpu_seconds"]) >= 0
        and cast("NonNegativeInt", worker["uss_bytes"]) > 0
        for worker in workers
    )
    assert all(
        cast("NonNegativeInt", worker["bytes_sent"]) >= 0
        and cast("NonNegativeInt", worker["bytes_received"]) >= 0
        for worker in workers
    )
    harness_paths = cast("dict[str, Payload]", sample["harness_paths"])
    writer_commands = cast(
        "dict[str, NonNegativeInt]", harness_paths["writer"]["wire_commands"]
    )
    observer_commands = cast(
        "dict[str, NonNegativeInt]", harness_paths["observer"]["wire_commands"]
    )
    assert (
        writer_commands["update:requested"] == writer_commands["update:completed"] == 4
    )
    assert observer_commands["hello:requested"] > 0
    assert observer_commands["hello:completed"] > 0
    expected_events = 4 if path in {"native", "stream-only"} else 0
    assert all(worker["invalidations"] == expected_events for worker in workers)
    assert sum(
        len(cast("list[NonNegativeFloat]", worker["read_offsets_seconds"]))
        for worker in workers
    ) == (20 if path in {"native", "native-control"} else 0)
    if path == "native":
        assert all(
            cast("Payload", worker["primed"])["entry_count"] == 16 for worker in workers
        )


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
def test_real_capture_retains_every_registered_event_and_gap(
    multiprocess_replica: IsolatedReplicaSet,
    capture_protocol: Protocol,
    model: Model,
) -> None:
    cell = replace(planned_cells()[0], model=model, path="native", workload="active")
    sample = run_cell(multiprocess_replica, cell, capture_protocol)
    worker = cast("tuple[Payload, ...]", sample["workers_measured"])[0]
    assert worker["invalidations"] == 200
    assert (
        tuple(map(len, cast("tuple[tuple[float, ...], ...]", worker["lag_windows"])))
        == (20,) * 6
    )
    assert (
        len(cast("tuple[tuple[NonNegativeInt, ...], ...]", worker["capture_ordinals"]))
        == 6
    )


@pytest.fixture
def failing_harness(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    smoke_protocol: Protocol,
) -> Protocol:
    if request.param == "cpu":
        monkeypatch.setattr(
            IsolatedReplicaSet,
            "container_cpu_usage_seconds",
            Mock(side_effect=BenchmarkSetupError("server CPU unavailable")),
        )
    elif request.param == "writer":
        monkeypatch.setattr(
            Collection,
            "update_one",
            Mock(side_effect=ConnectionFailure("writer unavailable")),
        )
    elif request.param == "observer":
        monkeypatch.setattr(PeriodicCalibrationSampler, "stop", _stop_then_fail)
    elif request.param == "clock":
        monkeypatch.setattr(
            CalibrationSeries, "exceeds_drift_tolerance", Mock(return_value=True)
        )
    else:
        return replace(smoke_protocol, schedule_tolerance_seconds=1e-9)
    return smoke_protocol


@pytest.mark.parametrize(
    ("failing_harness", "message"),
    [
        pytest.param("cpu", "server CPU unavailable", id="missing-server-cpu"),
        pytest.param(
            "writer", "harness MongoDB operation failed", id="failed-writer-command"
        ),
        pytest.param("observer", "clock observer failed", id="failed-clock-observer"),
        pytest.param("clock", "clock or primary changed", id="clock-drift"),
        pytest.param(
            "schedule", "write schedule exceeded tolerance", id="write-lateness"
        ),
    ],
    indirect=["failing_harness"],
)
def test_harness_failures_reclaim_children(
    multiprocess_replica: IsolatedReplicaSet,
    failing_harness: Protocol,
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        run_cell(
            multiprocess_replica,
            replace(planned_cells()[0], workload="active"),
            failing_harness,
        )
    assert not multiprocessing.active_children()


@pytest.mark.parametrize(
    ("faulty_worker", "path", "message"),
    [
        ("streams", "stream-only", "expected 1 stream, observed 2"),
        ("startup", "native", "native manager stream startup failed"),
        ("budget", "native", "working set was not fully admitted"),
        ("document", "native-control", "scheduled document disappeared"),
        ("stream-count", "stream-only", "stream continuity changed"),
        ("wire", "stream-control", "observed a failed wire command"),
        ("lag", "native", "lag capture separation"),
        ("extra-observation", "stream-only", "incomplete stream-only delivery"),
    ],
    indirect=["faulty_worker"],
    ids=[
        "wrong-stream-count",
        "startup-health",
        "insufficient-budget",
        "deleted-document",
        "stream-count-change",
        "wire-failure",
        "capture-timestamp",
        "extra-observation",
    ],
)
@pytest.mark.usefixtures("faulty_worker")
def test_faulty_instrumentation_rejects_measurements(
    multiprocess_replica: IsolatedReplicaSet,
    capture_protocol: Protocol,
    path: PathKind,
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        run_cell(
            multiprocess_replica,
            replace(planned_cells()[0], path=path, workload="active"),
            capture_protocol,
        )
    assert not multiprocessing.active_children()


@pytest.mark.parametrize(
    "faulty_worker", ["drain"], indirect=True, ids=["delayed-receiver"]
)
@pytest.mark.usefixtures("faulty_worker")
def test_delivery_during_drain_remains_in_sample(
    multiprocess_replica: IsolatedReplicaSet, smoke_protocol: Protocol
) -> None:
    sample = run_cell(
        multiprocess_replica,
        replace(planned_cells()[0], path="stream-only", workload="active"),
        smoke_protocol,
    )
    worker = cast("tuple[Payload, ...]", sample["workers_measured"])[0]
    assert worker["invalidations"] == smoke_protocol.updates


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
@pytest.mark.parametrize("path", ["native", "stream-only"], ids=["cache", "isolated"])
def test_idle_streams_demonstrate_polling(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    model: Model,
    path: PathKind,
) -> None:
    sample = run_cell(
        multiprocess_replica,
        replace(planned_cells()[0], model=model, path=path, workload="idle"),
        smoke_protocol,
    )
    worker = cast("tuple[Payload, ...]", sample["workers_measured"])[0]
    assert (
        cast("dict[str, NonNegativeInt]", worker["wire_commands"])["getMore:completed"]
        > 0
    )
    assert cast("PositiveFloat", worker["idle_poll_max_gap_seconds"]) <= (
        smoke_protocol.registration["max_await_time_ms"] / 1000
        + smoke_protocol.schedule_tolerance_seconds
    )
    assert worker["invalidations"] == 0


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
@pytest.mark.parametrize(
    ("faulty_worker", "path", "message"),
    [
        ("receiver", "stream-only", "stream receiver stopped"),
        ("absent", "stream-only", "idle stream issued no completed getMore"),
        ("zero", "native", "idle stream issued no completed getMore"),
        ("cleanup", "stream-only", "worker exited unsuccessfully"),
    ],
    indirect=["faulty_worker"],
    ids=[
        "completed-receiver",
        "absent-polls",
        "zero-polls",
        "failed-cleanup",
    ],
)
@pytest.mark.usefixtures("faulty_worker")
def test_idle_and_shutdown_failures_cannot_produce_healthy_cells(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    model: Model,
    path: PathKind,
    message: str,
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        run_cell(
            multiprocess_replica,
            replace(planned_cells()[0], model=model, path=path, workload="idle"),
            smoke_protocol,
        )
    assert not multiprocessing.active_children()


@pytest.mark.parametrize("model", ["sync", "async"], ids=["sync", "asyncio"])
@pytest.mark.parametrize("faulty_worker", ["stalled-polls"], indirect=True)
@pytest.mark.usefixtures("faulty_worker")
def test_one_successful_poll_cannot_validate_a_stalled_idle_receiver(
    multiprocess_replica: IsolatedReplicaSet,
    smoke_protocol: Protocol,
    model: Model,
) -> None:
    with pytest.raises(BenchmarkSetupError, match="idle getMore polling gap exceeded"):
        run_cell(
            multiprocess_replica,
            replace(
                planned_cells()[0], model=model, path="stream-only", workload="idle"
            ),
            replace(smoke_protocol, window_seconds=3.5),
        )
    assert not multiprocessing.active_children()

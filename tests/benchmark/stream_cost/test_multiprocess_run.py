from __future__ import annotations

import multiprocessing
import time
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import psutil
import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import (
    Protocol,
    capture_ordinals,
    command_delta,
    cpu_delta,
    partition_reads,
    planned_cells,
    process_reading,
    reads_for_path,
    receive,
    stop_workers,
    validate_capture,
    wait_until,
)
from client_query_cache._core.stream_cost import (
    LagCaptureWindowConfig,
    LagCaptureWindows,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

    from benchmarks.stream_cost.multiprocess_run import PathKind, Workload

pytestmark = pytest.mark.unit


@pytest.fixture
def protocol() -> Protocol:
    return Protocol.load()


@pytest.fixture
def pipe() -> Iterator[tuple[Connection, Connection]]:
    parent, child = multiprocessing.get_context("spawn").Pipe()
    yield parent, child
    parent.close()
    child.close()


def _advance_clock(clock: Mock, lateness: float, delay: float) -> None:
    clock.monotonic.return_value += delay + lateness


@pytest.fixture
def schedule_clock(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Mock:
    clock = Mock()
    clock.monotonic.return_value = request.param[0]
    clock.sleep = AsyncMock(
        side_effect=partial(_advance_clock, clock, request.param[1])
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.multiprocess_run.time.monotonic", clock.monotonic
    )
    monkeypatch.setattr(
        "benchmarks.stream_cost.multiprocess_run.asyncio.sleep", clock.sleep
    )
    return clock


@pytest.mark.parametrize(
    ("schedule_clock", "deadline"),
    [((0.0, 0.001), 60.0), ((0.0, 0.001), 0.3), ((60.01, 0.0), 60.0)],
    indirect=["schedule_clock"],
    ids=["idle-minute", "paced-read", "already-due"],
)
async def test_schedule_preserves_deadline_with_bounded_waits(
    schedule_clock: Mock, deadline: float
) -> None:
    await wait_until(deadline, 0.05, "end")
    assert deadline <= schedule_clock.monotonic.return_value <= deadline + 0.05
    assert all(0 < call.args[0] <= 1 for call in schedule_clock.sleep.await_args_list)


@pytest.mark.parametrize(
    "schedule_clock",
    [(0.0, 0.06), (60.06, 0.0)],
    indirect=True,
    ids=["late-wakeup", "late-arrival"],
)
@pytest.mark.usefixtures("schedule_clock")
async def test_schedule_rejects_lateness_without_relaxing_tolerance() -> None:
    with pytest.raises(
        BenchmarkSetupError, match=r"application end schedule.*0\.060000s"
    ):
        await wait_until(60.0, 0.05, "end")


def _park() -> None:
    multiprocessing.Event().wait(60)


@pytest.fixture
def parked_children(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[BaseProcess, ...]]:
    children = tuple(
        multiprocessing.get_context("spawn").Process(target=_park)
        for _ in range(request.param)
    )
    for child in children:
        child.start()
    yield children
    for child in children:
        if child.is_alive():
            child.terminate()
        child.join(1)
        child.close()


@pytest.mark.parametrize("workers", [1, 8], ids=["one", "eight"])
def test_partitions_fixed_aggregate_schedule(protocol: Protocol, workers: int) -> None:
    partitions = tuple(
        partition_reads(protocol, workers, index) for index in range(workers)
    )
    assert sorted(ordinal for partition in partitions for ordinal in partition) == list(
        range(1800)
    )
    assert len({len(partition) for partition in partitions}) == 1
    assert tuple(
        ordinal * protocol.read_interval_seconds
        for ordinal in sorted(
            ordinal for partition in partitions for ordinal in partition
        )
    ) == pytest.approx(tuple(index / 30 for index in range(1800)))


@pytest.mark.parametrize("workload", ["idle", "active"], ids=["idle", "active"])
@pytest.mark.parametrize(
    "path",
    ["native-control", "native", "stream-control", "stream-only"],
    ids=["raw-reads", "cache-reads", "raw-stream-control", "stream-only"],
)
def test_assigns_application_reads_only_to_native_pair(
    path: PathKind, workload: Workload
) -> None:
    assert reads_for_path(path, workload) == (
        workload == "active" and path in {"native", "native-control"}
    )


def test_counterbalances_complete_cells() -> None:
    cells = planned_cells()
    assert len(cells) == 192
    assert tuple(replace(cell, block=0) for cell in cells[:32]) == tuple(
        replace(cell, block=0) for cell in cells[32:64][::-1]
    )
    assert len(set(cells)) == 192


@pytest.mark.parametrize(
    "event_count", [199, 200, 201], ids=["missing", "complete", "extra"]
)
def test_requires_complete_capture_and_separations(event_count: int) -> None:
    captures = LagCaptureWindows(LagCaptureWindowConfig(6, 20, 16))
    admitted_ordinals = tuple(
        index for index in range(1, event_count + 1) if captures.record(float(index))
    )
    if event_count != 200:
        with pytest.raises(BenchmarkSetupError, match="invalidations"):
            validate_capture(event_count, captures.snapshot(), 200)
    else:
        validate_capture(event_count, captures.snapshot(), 200)
        assert captures.snapshot() == capture_ordinals()
        assert admitted_ordinals == tuple(
            index for window in capture_ordinals() for index in window
        )
        assert sum(len(window) for window in captures.snapshot()) == 120
        assert (
            tuple(
                right[0] - left[-1] - 1
                for left, right in zip(
                    capture_ordinals(),
                    capture_ordinals()[1:],
                    strict=False,
                )
            )
            == (16,) * 5
        )


def test_rejects_incomplete_capture_with_complete_event_count() -> None:
    with pytest.raises(BenchmarkSetupError, match="capture"):
        validate_capture(200, ((0.1,) * 20,) * 5, 200)


@pytest.mark.parametrize(
    "failure",
    ["late", "eof", "startup", "wrong-message"],
    ids=["deadline", "child-exit", "startup-failure", "ordering"],
)
def test_rejects_child_startup_failure(
    pipe: tuple[Connection, Connection], failure: str
) -> None:
    parent, child = pipe
    if failure == "eof":
        child.close()
    elif failure == "startup":
        child.send({"kind": "failure", "error": "manager startup failed"})
    elif failure == "wrong-message":
        child.send({"kind": "sample"})
    with pytest.raises(BenchmarkSetupError):
        receive(parent, time.monotonic() + 0.01, "ready")


@pytest.mark.parametrize("parked_children", [1, 8], indirect=True, ids=["one", "eight"])
def test_bounded_shutdown_terminates_stalled_children(
    parked_children: tuple[BaseProcess, ...],
) -> None:
    started = time.monotonic()
    with pytest.raises(BenchmarkSetupError, match="shutdown exceeded"):
        stop_workers(parked_children, 1)
    assert all(not child.is_alive() for child in parked_children)
    assert time.monotonic() - started < 1.1


def test_separates_required_process_metrics() -> None:
    reading = process_reading()
    assert reading["pid"] == psutil.Process().pid
    assert cast("int", reading["uss_bytes"]) > 0
    assert cast("float", reading["cpu_seconds"]) >= 0


def test_required_private_memory_failure_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        psutil.Process, "memory_full_info", Mock(side_effect=psutil.AccessDenied())
    )
    with pytest.raises(BenchmarkSetupError, match="CPU/USS unavailable"):
        process_reading()


@pytest.mark.parametrize(
    "after", [-1.0, float("nan"), float("inf")], ids=["regression", "nan", "infinite"]
)
def test_rejects_invalid_cpu_delta(after: float) -> None:
    with pytest.raises(BenchmarkSetupError, match="CPU counter"):
        cpu_delta({"cpu_seconds": 0.0}, {"cpu_seconds": after})


def test_command_counts_preserve_inflight_and_failed_outcomes() -> None:
    assert command_delta(
        {"getMore:requested": 2},
        {"getMore:requested": 3, "getMore:completed": 2, "getMore:failed": 1},
    ) == {"getMore:requested": 1, "getMore:completed": 2, "getMore:failed": 1}

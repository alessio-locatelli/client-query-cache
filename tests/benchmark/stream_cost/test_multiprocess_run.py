from __future__ import annotations

import json
import multiprocessing
import runpy
import signal
import time
from contextlib import nullcontext
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import psutil
import pytest
from pymongo.errors import ConnectionFailure

from benchmarks.stream_cost import multiprocess_run
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import (
    Protocol,
    capture_ordinals,
    command_delta,
    cpu_delta,
    idle_poll_max_gap,
    partition_reads,
    planned_cells,
    process_reading,
    reads_for_path,
    receive,
    reclaim_workers,
    stop_workers,
    validate_capture,
    wait_until,
)
from client_query_cache._core.stream_cost import (
    LagCaptureWindowConfig,
    LagCaptureWindows,
)
from client_query_cache._types import NonEmptyStr, PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess
    from pathlib import Path

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


def _ignore_term(connection: Connection) -> None:  # pragma: lax no cover - SIGKILL.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    connection.send(None)
    multiprocessing.Event().wait(60)


@pytest.fixture
def stubborn_child(pipe: tuple[Connection, Connection]) -> Iterator[BaseProcess]:
    parent, child = pipe
    process = multiprocessing.get_context("spawn").Process(
        target=_ignore_term, args=(child,)
    )
    process.start()
    assert parent.poll(5)
    parent.recv()
    yield process
    reclaim_workers((process,), time.monotonic() + 1, graceful=False)
    assert process.exitcode == -signal.SIGKILL
    process.close()


def test_shutdown_kills_a_worker_that_ignores_termination(
    stubborn_child: BaseProcess,
) -> None:
    with pytest.raises(
        BenchmarkSetupError,
        match=r"shutdown exceeded|children remain alive after cleanup deadline",
    ):
        stop_workers((stubborn_child,), 1)


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
    reclaim_workers(children, time.monotonic() + 1, graceful=False)
    for child in children:
        child.close()


@pytest.fixture
def cli_collector(monkeypatch: pytest.MonkeyPatch) -> Mock:
    collector = Mock(return_value={"healthy": True})
    monkeypatch.setattr(multiprocess_run, "run_cell", collector)
    monkeypatch.setattr(
        multiprocess_run, "IsolatedReplicaSet", Mock(return_value=nullcontext(object()))
    )
    return collector


@pytest.mark.parametrize("smoke", [False, True], ids=["baseline", "smoke"])
def test_cli_preserves_protocol_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_collector: Mock, smoke: bool
) -> None:
    output = tmp_path / "new-directory" / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        ["multiprocess_run", "--output", str(output), *(["--smoke"] if smoke else [])],
    )
    multiprocess_run.main()
    report = json.loads(output.read_text())
    assert report["phase"] == ("smoke" if smoke else "baseline")
    assert len(report["revision"]) == 40
    assert len(report["cells"]) == cli_collector.call_count == (8 if smoke else 192)
    assert report["protocol"]["window_seconds"] == (1 if smoke else 60)


def test_cli_records_failed_cell_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_collector: Mock
) -> None:
    output = tmp_path / "failed.json"
    cli_collector.side_effect = BenchmarkSetupError("worker exited unsuccessfully")
    monkeypatch.setattr("sys.argv", ["multiprocess_run", "--output", str(output)])
    with pytest.raises(BenchmarkSetupError, match="worker exited unsuccessfully"):
        multiprocess_run.main()
    assert cli_collector.call_count == 1
    sample = json.loads(output.read_text())["cells"][0]
    assert not sample["healthy"]
    assert sample["failure"] == "worker exited unsuccessfully"


@pytest.fixture
def cli_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["multiprocess_run", "--output", str(output)])
    return output


def test_cli_preserves_existing_evidence(cli_output: Path) -> None:
    cli_output.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(multiprocess_run.__file__), run_name="__main__")
    assert error.value.code == 2
    assert cli_output.read_text(encoding="utf-8") == "existing evidence"


@pytest.mark.usefixtures("cli_output")
def test_cli_requires_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.multiprocess_run.shutil.which",
        Mock(return_value=None),
    )
    with pytest.raises(BenchmarkSetupError, match="git is required"):
        multiprocess_run.main()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (BenchmarkSetupError("startup failed"), "startup failed"),
        (ConnectionFailure("disconnected"), "MongoDB worker failure: disconnected"),
        (TimeoutError(), "worker drain deadline exceeded"),
    ],
    ids=["startup", "database", "deadline"],
)
def test_worker_reports_failure_and_exits_unsuccessfully(
    pipe: tuple[Connection, Connection],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
) -> None:
    parent, child = pipe
    monkeypatch.setattr(
        multiprocess_run, "worker_window", AsyncMock(side_effect=failure)
    )
    with pytest.raises(type(failure)):
        multiprocess_run.worker_main(
            child, "unused", planned_cells()[0], 0, Protocol.smoke()
        )
    assert parent.recv() == {"kind": "failure", "error": message}
    assert child.closed


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


def record_capture(
    event_count: int,
) -> tuple[LagCaptureWindows, tuple[int, ...]]:
    captures = LagCaptureWindows(LagCaptureWindowConfig(6, 20, 16))
    admitted_ordinals = tuple(
        index for index in range(1, event_count + 1) if captures.record(float(index))
    )
    return captures, admitted_ordinals


def test_accepts_complete_capture_with_separations() -> None:
    captures, admitted_ordinals = record_capture(200)
    validate_capture(200, captures.snapshot(), 200)
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


@pytest.mark.parametrize("event_count", [199, 201], ids=["missing", "extra"])
def test_rejects_incomplete_or_extra_invalidations(event_count: int) -> None:
    captures, _admitted_ordinals = record_capture(event_count)
    with pytest.raises(BenchmarkSetupError, match="invalidations"):
        validate_capture(event_count, captures.snapshot(), 200)


def test_rejects_incomplete_capture_with_complete_event_count() -> None:
    with pytest.raises(BenchmarkSetupError, match="capture"):
        validate_capture(200, ((0.1,) * 20,) * 5, 200)


@pytest.mark.parametrize(
    "act_as_child",
    [
        pytest.param(lambda _child: None, id="deadline"),
        pytest.param(lambda child: child.close(), id="child-exit"),
        pytest.param(
            lambda child: child.send(
                {"kind": "failure", "error": "manager startup failed"}
            ),
            id="startup-failure",
        ),
        pytest.param(lambda child: child.send({"kind": "sample"}), id="ordering"),
    ],
)
def test_rejects_child_startup_failure(
    pipe: tuple[Connection, Connection],
    act_as_child: Callable[[Connection], object],
) -> None:
    parent, child = pipe
    act_as_child(child)
    with pytest.raises(BenchmarkSetupError):
        receive(parent, time.monotonic() + 0.01, "ready")


@pytest.mark.parametrize("parked_children", [1, 8], indirect=True, ids=["one", "eight"])
def test_bounded_shutdown_terminates_stalled_children(
    parked_children: tuple[BaseProcess, ...],
) -> None:
    started = time.monotonic()
    shutdown_seconds = 1
    with pytest.raises(BenchmarkSetupError, match="shutdown exceeded"):
        stop_workers(parked_children, shutdown_seconds)
    assert all(not child.is_alive() for child in parked_children)
    assert time.monotonic() - started < shutdown_seconds + 0.1


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


@pytest.mark.parametrize(
    ("completions", "expected"),
    [
        pytest.param(tuple(range(61)), 1.0, id="continuous"),
        pytest.param((-1.0, *range(61), 61.0), 1.0, id="outside-window"),
        pytest.param((0.0, 1.04, *range(2, 61)), 1.04, id="scheduling-slack"),
    ],
)
def test_idle_polling_covers_the_entire_application_window(
    completions: tuple[float, ...], expected: PositiveFloat
) -> None:
    assert idle_poll_max_gap(completions, 0, 60, 1.05) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("completions", "message"),
    [
        pytest.param((1.0,), "polling gap exceeded", id="one-poll-then-stall"),
        pytest.param(tuple(range(10, 61)), "polling gap exceeded", id="initial-gap"),
        pytest.param(
            (*range(30), *range(32, 61)), "polling gap exceeded", id="middle-gap"
        ),
        pytest.param(tuple(range(59)), "polling gap exceeded", id="final-gap"),
        pytest.param((-1.0, 61.0), "no completed getMore", id="only-outside-window"),
    ],
)
def test_idle_polling_rejects_an_uncovered_application_window(
    completions: tuple[float, ...], message: NonEmptyStr
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        idle_poll_max_gap(completions, 0, 60, 1.05)

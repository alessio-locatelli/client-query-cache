from __future__ import annotations

import multiprocessing
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import psutil
import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import fault_recovery, window
from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    fault_recovery_cells,
    smoke_cells,
)
from benchmarks.stream_cost.shared_cache.worker import _query, _verify
from benchmarks.stream_cost.topology import ReplicaSetTopology
from client_query_cache._types import JsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.protocol import Cell
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec
    from benchmarks.stream_cost.topology import IsolatedReplicaSet

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_FAULT_CONFIG = Path("reports/worker-fault-recovery/v1/config.json")


@pytest.fixture
def registration() -> Registration:
    return Registration.load(_CONFIG)


class _SilentControl:
    __slots__ = ("sent",)

    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, request: object) -> None:
        self.sent.append(request)

    # Implements the control-pipe API without using instance state.
    def poll(self, _timeout: float) -> bool:  # noqa: PLR6301
        return False


class _BrokenControl:
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    # Implements a broken control-pipe send operation for cleanup handling.
    def send(self, _request: object) -> None:  # noqa: PLR6301
        raise BrokenPipeError

    def close(self) -> None:
        self.closed = True


class _SuccessfulControl:
    __slots__ = ("response", "sent")

    def __init__(self, response: JsonDict) -> None:
        self.response = response
        self.sent: list[object] = []

    def send(self, request: object) -> None:
        self.sent.append(request)

    # Implements the control-pipe API with a ready response.
    def poll(self, _timeout: float) -> bool:  # noqa: PLR6301
        return True

    def recv(self) -> JsonDict:
        return self.response


class _PipeEnd:
    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _QueuedControl:
    __slots__ = ("available", "received", "sent")

    def __init__(self, response: JsonDict, *, available: bool = True) -> None:
        self.available = available
        self.received = response
        self.sent: list[object] = []

    def send(self, request: object) -> None:
        self.sent.append(request)

    def poll(self, _timeout: float) -> bool:
        return self.available

    def recv(self) -> JsonDict:
        return self.received


class _TimelinePipe:
    __slots__ = ("available", "closed", "received")

    def __init__(self, response: JsonDict) -> None:
        self.available = True
        self.closed = False
        self.received = response

    def poll(self) -> bool:
        return self.available

    def recv(self) -> JsonDict:
        self.available = False
        return self.received

    def close(self) -> None:
        self.closed = True


class _PartialTimelinePipe(_TimelinePipe):
    __slots__ = ()

    def recv(self) -> JsonDict:
        self.available = False
        raise OSError("got end of file during message")


class _ReplaceableProcess:
    __slots__ = ("alive", "args", "joined", "killed", "started", "target")

    def __init__(
        self,
        *,
        alive: bool = False,
        target: object = None,
        args: tuple[object, ...] = (),
    ) -> None:
        self.alive = alive
        self.args = args
        self.joined = False
        self.killed = False
        self.started = False
        self.target = target

    def start(self) -> None:
        self.started = True
        self.alive = True

    def kill(self) -> None:
        self.killed = True
        self.alive = False

    def join(self, _timeout: float) -> None:
        self.joined = True

    def is_alive(self) -> bool:
        return self.alive


class _WorkerContext:
    __slots__ = ("pipes", "processes")

    def __init__(self) -> None:
        self.pipes: list[tuple[_PipeEnd, _PipeEnd]] = []
        self.processes: list[_ReplaceableProcess] = []

    def Pipe(  # noqa: N802 - Mirror multiprocessing context API names.
        self, *, duplex: bool = True
    ) -> tuple[_PipeEnd, _PipeEnd]:
        assert isinstance(duplex, bool)
        pipe = (_PipeEnd(), _PipeEnd())
        self.pipes.append(pipe)
        return pipe

    def Process(  # noqa: N802 - Mirror multiprocessing context API names.
        self, *, target: object, args: tuple[object, ...]
    ) -> _ReplaceableProcess:
        process = _ReplaceableProcess(target=target, args=args)
        self.processes.append(process)
        return process


@dataclass(frozen=True, slots=True)
class _WorkerSpec:
    index: NonNegativeInt = 0
    controls_enabled: bool = True
    timeline_enabled: bool = False
    timeline_generation: NonNegativeInt = 0
    scheduled_ordinals: tuple[NonNegativeInt, ...] | None = None


class _LingeringProcess:
    __slots__ = ("joined",)

    def __init__(self) -> None:
        self.joined = False

    # Implements process-control methods with fixed test responses.
    def is_alive(self) -> bool:  # noqa: PLR6301
        return True

    def join(self, _timeout: float) -> None:
        self.joined = True

    # Implements process-control operations without instance state.
    def terminate(self) -> None:  # noqa: PLR6301
        return None

    # Implements process-control operations without instance state.
    def kill(self) -> None:  # noqa: PLR6301
        return None


@pytest.fixture
def group() -> window.ProcessGroup:
    return window.ProcessGroup(multiprocessing.get_context("spawn"), 0.1)


def test_memory_sampling_reports_a_vanished_process() -> None:
    sampler = window.GroupMemorySampler({"worker-0": 2**22 + 12_345}, 0.01)

    with sampler:
        time.sleep(0.05)

    with pytest.raises(BenchmarkSetupError, match="PSS sampling failed"):
        sampler.summary()


def test_memory_summary_requires_a_sample() -> None:
    sampler = window.GroupMemorySampler({"harness": psutil.Process().pid}, 1.0)

    with pytest.raises(BenchmarkSetupError, match="no group PSS sample"):
        sampler.summary()


def test_find_profiles_schedule_category_reads(registration: Registration) -> None:
    cell = replace(smoke_cells(registration)[0], profile="find16")

    workload = window._workload(registration, cell)

    assert (workload.read, workload.limit) == ("find", 16)
    assert sorted(workload.keys) == list(range(64))


def test_an_unanswered_owner_request_fails_the_window(
    group: window.ProcessGroup,
) -> None:
    group.owner_control = _SilentControl()  # type: ignore[assignment]

    with pytest.raises(BenchmarkSetupError, match="did not answer in time"):
        group.owner_request({"op": "sample"}, time.monotonic() + 0.01)


def test_worker_control_returns_the_matching_response(
    group: window.ProcessGroup,
) -> None:
    control = _SuccessfulControl(
        {"kind": "control", "operation": "sever", "streams": 0}
    )
    group.control_connections = [control]  # type: ignore[list-item]

    response = group.control_worker(0, "sever")

    assert response["operation"] == "sever"
    assert control.sent == [{"op": "sever"}]


def test_worker_control_requires_a_control_pipe(
    group: window.ProcessGroup,
) -> None:
    group.control_connections = [None]

    with pytest.raises(BenchmarkSetupError, match="controls are not enabled"):
        group.control_worker(0, "sever")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param(
            {"kind": "unexpected", "operation": "sever"},
            "unexpected control response",
            id="unexpected-kind",
        ),
        pytest.param(
            {"kind": "control", "operation": "snapshot"},
            "unexpected control response",
            id="unexpected-operation",
        ),
    ],
)
def test_worker_control_rejects_unexpected_responses(
    group: window.ProcessGroup,
    response: JsonDict,
    message: str,
) -> None:
    group.control_connections = [_QueuedControl(response)]  # type: ignore[list-item]

    with pytest.raises(BenchmarkSetupError, match=message):
        group.control_worker(0, "sever")


def test_worker_control_times_out(
    group: window.ProcessGroup,
) -> None:
    group.control_connections = [_SilentControl()]  # type: ignore[list-item]

    with pytest.raises(BenchmarkSetupError, match="did not answer"):
        group.control_worker(0, "sever")


def test_control_workers_require_every_pipe_and_validate_responses(
    group: window.ProcessGroup,
) -> None:
    group.control_connections = cast(
        "list[Connection | None]",
        [None, _SuccessfulControl({"kind": "control"})],
    )
    with pytest.raises(BenchmarkSetupError, match="every worker"):
        group.control_workers("snapshot")

    group.control_connections = cast(
        "list[Connection | None]",
        [_QueuedControl({"kind": "unexpected", "operation": "snapshot"})],
    )
    with pytest.raises(BenchmarkSetupError, match="unexpected control response"):
        group.control_workers("snapshot")

    group.control_connections = [_SilentControl()]  # type: ignore[list-item]
    with pytest.raises(BenchmarkSetupError, match="did not answer"):
        group.control_workers("snapshot")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param({"kind": "failure", "error": "broken"}, "broken", id="failure"),
        pytest.param({"kind": "other"}, "unexpected worker message", id="kind"),
    ],
)
def test_collect_worker_rejects_failure_and_unexpected_messages(
    group: window.ProcessGroup,
    response: JsonDict,
    message: str,
) -> None:
    group.connections = [_QueuedControl(response)]  # type: ignore[list-item]
    group.timeline_connections = []

    with pytest.raises(BenchmarkSetupError, match=message):
        group.collect_worker(0, "sample", time.monotonic() + 1.0)


def test_collect_worker_rejects_an_expired_deadline(
    group: window.ProcessGroup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group.connections = [_SilentControl()]  # type: ignore[list-item]
    group.timeline_connections = []
    monkeypatch.setattr(time, "monotonic", lambda: 2.0)

    with pytest.raises(BenchmarkSetupError, match="deadline exceeded"):
        group.collect_worker(0, "sample", 1.0)


def test_collect_rejects_an_expired_deadline(
    group: window.ProcessGroup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group.connections = [_SilentControl()]  # type: ignore[list-item]
    group.timeline_connections = []
    monkeypatch.setattr(time, "monotonic", lambda: 2.0)

    with pytest.raises(BenchmarkSetupError, match="sample deadline exceeded"):
        group.collect("sample", 1.0)


def test_collect_rejects_an_unexpected_worker_message(
    group: window.ProcessGroup,
) -> None:
    group.connections = [_QueuedControl({"kind": "ready"})]  # type: ignore[list-item]
    group.timeline_connections = []

    with pytest.raises(
        BenchmarkSetupError, match="unexpected worker message at sample"
    ):
        group.collect("sample", time.monotonic() + 1.0)


def test_timeline_drain_rejects_invalid_worker_messages(
    group: window.ProcessGroup,
) -> None:
    group.timeline_connections = [_TimelinePipe({"kind": "not-a-timeline-chunk"})]  # type: ignore[list-item]

    with pytest.raises(BenchmarkSetupError, match="invalid timeline chunk"):
        group.drain_timeline_chunks()


@pytest.mark.parametrize(
    ("alive", "raises"),
    [
        pytest.param(False, False, id="exited-worker"),
        pytest.param(True, True, id="live-worker"),
    ],
)
def test_timeline_drain_handles_partial_eof_only_after_worker_exit(
    alive: bool,
    raises: bool,
    group: window.ProcessGroup,
) -> None:
    group.processes = [_ReplaceableProcess(alive=alive)]  # type: ignore[list-item]
    group.timeline_connections = [_PartialTimelinePipe({})]  # type: ignore[list-item]
    group.timeline_chunks = [[]]

    if raises:
        with pytest.raises(OSError, match="end of file during message"):
            group.drain_timeline_chunks()
    else:
        group.drain_timeline_chunks()


def test_cleanup_preserves_the_window_failure_after_timeline_pipe_eof(
    group: window.ProcessGroup,
) -> None:
    timeline = _PartialTimelinePipe({})
    group.processes = [_ReplaceableProcess()]  # type: ignore[list-item]
    group.timeline_connections = [timeline]  # type: ignore[list-item]
    group.timeline_chunks = [[]]

    with (
        pytest.raises(BenchmarkSetupError, match="write schedule exceeded tolerance"),
        group,
    ):
        raise BenchmarkSetupError("write schedule exceeded tolerance")

    assert timeline.closed


def test_kill_and_replace_reuses_spec_and_closes_old_connections(
    group: window.ProcessGroup,
) -> None:
    context = _WorkerContext()
    group._context = context  # type: ignore[assignment]
    spec = cast("WorkerSpec", _WorkerSpec())
    old_process = _ReplaceableProcess()
    old_process.alive = True
    old_connection = _PipeEnd()
    old_control = _PipeEnd()
    group._specs = [spec]
    group.processes = [old_process]  # type: ignore[list-item]
    group.connections = [old_connection]  # type: ignore[list-item]
    group.control_connections = [old_control]  # type: ignore[list-item]
    group.timeline_connections = [None]
    group.timeline_chunks = [[]]

    group.kill_and_replace(0)

    assert old_process.killed
    assert old_process.joined
    assert old_connection.closed
    assert old_control.closed
    replacement = context.processes[0]
    assert replacement.started
    assert replacement.args[1] == _WorkerSpec(
        controls_enabled=True,
        timeline_enabled=False,
        timeline_generation=1,
    )
    assert cast("object", group.connections[0]) is context.pipes[0][0]
    assert cast("object", group.control_connections[0]) is context.pipes[1][0]
    assert context.pipes[0][1].closed
    assert context.pipes[1][1].closed


def test_kill_timestamp_survives_replacement_spec_setup(
    group: window.ProcessGroup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _WorkerContext()
    group._context = context  # type: ignore[assignment]
    spec = cast("WorkerSpec", _WorkerSpec())
    old_process = _ReplaceableProcess()
    old_process.alive = True
    group._specs = [spec]
    group.processes = [old_process]  # type: ignore[list-item]
    group.connections = [_PipeEnd()]  # type: ignore[list-item]
    group.control_connections = [None]
    group.timeline_connections = [None]
    group.timeline_chunks = [[]]
    clock = [3.9]
    killed_at_values: list[NonNegativeFloat] = []
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.window.time.monotonic",
        lambda: clock[0],
    )

    def record_kill(killed_at: NonNegativeFloat) -> None:
        killed_at_values.append(killed_at)

    def replacement_spec(killed_at: NonNegativeFloat) -> WorkerSpec:
        assert old_process.killed
        clock[0] = 4.1
        offered_ordinals = range(0, 12, 4)
        remaining = tuple(
            ordinal for ordinal in offered_ordinals if ordinal / 2 >= killed_at
        )
        return cast("WorkerSpec", _WorkerSpec(scheduled_ordinals=remaining))

    group.kill_and_replace(
        0,
        spec_factory=replacement_spec,
        before_kill=record_kill,
    )

    assert killed_at_values == [3.9]
    replacement = context.processes[0].args[1]
    assert isinstance(replacement, _WorkerSpec)
    assert replacement.scheduled_ordinals == (8,)


def test_kill_and_replace_rejects_conflicting_or_mismatched_specs(
    group: window.ProcessGroup,
) -> None:
    with pytest.raises(BenchmarkSetupError, match="spec or a spec factory"):
        group.kill_and_replace(
            0,
            cast("WorkerSpec", _WorkerSpec()),
            spec_factory=lambda _killed_at: cast("WorkerSpec", _WorkerSpec()),
        )

    with pytest.raises(BenchmarkSetupError, match="another worker index"):
        group.kill_and_replace(
            0,
            cast("WorkerSpec", _WorkerSpec(index=1)),
        )


def test_kill_and_replace_rejects_a_live_killed_process(
    group: window.ProcessGroup,
) -> None:
    process = _LingeringProcess()
    group.processes = [process]  # type: ignore[list-item]
    group.connections = [_PipeEnd()]  # type: ignore[list-item]
    group.control_connections = [None]
    group.timeline_connections = [None]
    group.timeline_chunks = [[]]

    with pytest.raises(BenchmarkSetupError, match="failed to exit"):
        group.kill_and_replace(0)

    assert process.joined


def test_kill_and_replace_rejects_a_factory_with_another_worker_index(
    group: window.ProcessGroup,
) -> None:
    process = _ReplaceableProcess()
    process.alive = True
    group._context = _WorkerContext()  # type: ignore[assignment]
    group._specs = [cast("WorkerSpec", _WorkerSpec())]
    group.processes = [process]  # type: ignore[list-item]
    group.connections = [_PipeEnd()]  # type: ignore[list-item]
    group.control_connections = [None]
    group.timeline_connections = [None]
    group.timeline_chunks = [[]]

    with pytest.raises(BenchmarkSetupError, match="another worker index"):
        group.kill_and_replace(
            0,
            spec_factory=lambda _killed_at: cast("WorkerSpec", _WorkerSpec(index=1)),
        )


def test_cleanup_tolerates_a_closed_owner_pipe(group: window.ProcessGroup) -> None:
    control = _BrokenControl()
    process = _LingeringProcess()
    group.owner_control = control  # type: ignore[assignment]
    group.owner = process  # type: ignore[assignment]

    with pytest.raises(BenchmarkSetupError, match="children remain alive"):
        group.__exit__()

    assert control.closed
    assert process.joined


def test_stop_tolerates_closed_worker_pipes_and_closes_timeline(
    group: window.ProcessGroup,
) -> None:
    timeline = _TimelinePipe({"kind": "timeline_chunk", "events": [], "snapshot": {}})
    group.control_connections = [_BrokenControl()]  # type: ignore[list-item]
    group.connections = [_BrokenControl()]  # type: ignore[list-item]
    group.timeline_connections = [timeline]  # type: ignore[list-item]
    group.timeline_chunks = [[]]

    group.stop()

    assert timeline.closed
    assert group.timeline_chunks == [
        [{"kind": "timeline_chunk", "events": [], "snapshot": {}}]
    ]


def test_exit_tolerates_closed_worker_control_and_data_pipes(
    group: window.ProcessGroup,
) -> None:
    control = _BrokenControl()
    connection = _BrokenControl()
    group.control_connections = [control]  # type: ignore[list-item]
    group.connections = [connection]  # type: ignore[list-item]
    group.timeline_connections = [None]

    group.__exit__()

    assert control.closed
    assert connection.closed


def test_shared_cache_fault_windows_reject_multi_member_topologies(
    registration: Registration,
) -> None:
    cell = cast("Cell", SimpleNamespace(phase="fault"))
    replica = object.__new__(ReplicaSetTopology)

    with pytest.raises(BenchmarkSetupError, match="single-member replica set"):
        window.run_window(replica, registration, cell)


def test_multi_member_clients_use_replica_set_discovery() -> None:
    replica = object.__new__(ReplicaSetTopology)
    other_replica = cast("IsolatedReplicaSet", object())

    assert window._client_options(replica, {}) == {"directConnection": False}
    assert window._client_options(
        other_replica, {"serverSelectionTimeoutMS": 1000}
    ) == {"serverSelectionTimeoutMS": 1000}


def test_recovery_fault_cells_dispatch_to_the_recovery_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = Registration.load(_FAULT_CONFIG)
    cell = fault_recovery_cells(registration, smoke=True)[0]
    monkeypatch.setattr(
        fault_recovery,
        "run_recovery_fault_window",
        lambda *_args: {"dispatched": True},
    )

    assert window.run_window(
        cast("IsolatedReplicaSet", object()), registration, cell
    ) == {"dispatched": True}


def test_replica_set_server_metrics_sum_all_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replica = object.__new__(ReplicaSetTopology)
    cpu_calls: list[int] = []
    memory_calls: list[int] = []

    def cpu_usage(_self: ReplicaSetTopology, index: int) -> float:
        cpu_calls.append(index)
        return float(index + 1)

    def memory_usage(_self: ReplicaSetTopology, index: int) -> int:
        memory_calls.append(index)
        return index + 100

    monkeypatch.setattr(ReplicaSetTopology, "container_cpu_usage_seconds", cpu_usage)
    monkeypatch.setattr(
        ReplicaSetTopology, "container_memory_usage_bytes", memory_usage
    )

    assert window._server_cpu_usage(replica) == pytest.approx(6.0)
    assert window._server_memory_usage(replica) == 303
    assert cpu_calls == [0, 1, 2]
    assert memory_calls == [0, 1, 2]


@pytest.mark.parametrize(
    ("path", "streams"),
    [
        pytest.param("direct", (1, 0), id="direct-stream"),
        pytest.param("independent", (2, 0), id="uneven-independent-streams"),
    ],
)
def test_ready_checks_reject_unexpected_stream_ownership(
    registration: Registration,
    group: window.ProcessGroup,
    path: str,
    streams: tuple[int, int],
) -> None:
    cell = next(
        cell
        for cell in smoke_cells(registration)
        if cell.path == path and cell.workload == "hot"
    )
    workload = window._workload(registration, cell)
    ready: list[JsonDict] = [
        {"entries": workload.expected_entries, "streams": count} for count in streams
    ]

    with pytest.raises(BenchmarkSetupError, match="stream ownership"):
        window._verify_ready(group, cell, workload, ready, time.monotonic() + 1)


class _ShiftedCalibration:
    __slots__ = ()

    # Implements the calibration API with a fixed changed-clock response.
    def exceeds_drift_tolerance(self, _tolerance: float) -> bool:  # noqa: PLR6301
        return True


def test_active_windows_reject_clock_changes(registration: Registration) -> None:
    cell = next(cell for cell in smoke_cells(registration) if cell.workload == "active")

    with pytest.raises(BenchmarkSetupError, match="clock or primary changed"):
        window._check_clock(registration, cell, _ShiftedCalibration())  # type: ignore[arg-type]


def test_failed_worker_commands_reject_the_window() -> None:
    samples: list[JsonDict] = [{"commands": {"find:completed": 3, "find:failed": 1}}]

    with pytest.raises(BenchmarkSetupError, match="failed wire command"):
        window.reject_failed_commands(samples)


@dataclass(frozen=True, slots=True)
class _Spec:
    read: str
    limit: int


def test_sorted_find_results_must_be_complete() -> None:
    spec = cast("WorkerSpec", _Spec("find", 16))

    query, options = _query(spec, 3)

    assert query == {"attributes.category": 3}
    assert options == {"sort": [("_id", 1)], "limit": 16}
    with pytest.raises(LookupError, match="incomplete result"):
        _verify(spec, [{"payload": "", "revision": 0}])

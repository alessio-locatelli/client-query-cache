from __future__ import annotations

import multiprocessing
import secrets
import shutil
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, cast

import psutil
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from benchmarks.stream_cost.calibration import (
    CalibrationSeries,
    PeriodicCalibrationSampler,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.measurement import scalar_latency_distribution
from benchmarks.stream_cost.multiprocess_run import (
    WireCommands,
    command_delta,
    receive,
    reclaim_workers,
    stop_workers,
)
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.fault_timeline import merge_chunks
from benchmarks.stream_cost.shared_cache.owner import owner_main, proxy_for
from benchmarks.stream_cost.shared_cache.profiling import enabled as profiling_enabled
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    CalibrationTopologyCell,
    RecoveryFaultCell,
    profile_keys,
    write_count,
)
from benchmarks.stream_cost.shared_cache.worker import WorkerSpec, worker_main
from benchmarks.stream_cost.shared_cache.workload import (
    assignment_for,
    key_order,
    measured_keys,
    warm_key,
    worker_keys,
)
from benchmarks.stream_cost.topology import ReplicaSetTopology
from client_query_cache._core.manager import DEFAULT_MAX_NAMESPACES
from client_query_cache._shared.attachment import AttachmentConfig
from client_query_cache._shared.coordinator import OwnerConfig
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.connection import Connection
    from multiprocessing.context import SpawnContext
    from multiprocessing.process import BaseProcess

    from pymongo.synchronous.collection import Collection

    from benchmarks.stream_cost.shared_cache.protocol import (
        Cell,
        PathKind,
        Registration,
    )
    from benchmarks.stream_cost.topology import IsolatedReplicaSet

type Payload = dict[str, object]

_START_LEAD_SECONDS = 1.0
_OWNER_POLL_SECONDS = 0.01
_CONTROL_GRACE_SECONDS = 5.0
_WRITERS = 4
SERVER_MEMORY_SCOPE = "Podman cgroup memory usage, including page cache"
HARNESS_INCLUDES = (
    "writer",
    "clock-observer",
    "PSS-sampler",
    "writer-proxy",
    "observer-proxy",
    "orchestration",
)


class GroupMemorySampler:
    __slots__ = ("_pids", "_seconds", "_stop", "_thread", "error", "samples")

    def __init__(self, pids: dict[str, NonNegativeInt], seconds: PositiveFloat) -> None:
        self._pids = pids
        self._seconds = seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.samples: list[dict[str, NonNegativeInt]] = []
        self.error: str | None = None

    def _run(self) -> None:
        try:
            processes = {name: psutil.Process(pid) for name, pid in self._pids.items()}
            while not self._stop.is_set():
                self.samples.append(
                    {
                        name: process.memory_full_info().pss
                        for name, process in processes.items()
                    }
                )
                self._stop.wait(self._seconds)
        except psutil.Error as error:
            self.error = f"PSS sampling failed: {error}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._stop.set()
        self._thread.join()

    def summary(self) -> Payload:
        if self.error is not None:
            raise BenchmarkSetupError(self.error)
        if not self.samples:
            raise BenchmarkSetupError("no group PSS sample was collected")
        totals = [sum(sample.values()) for sample in self.samples]
        owner = (
            sum(sample["owner"] for sample in self.samples) / len(totals)
            if "owner" in self._pids
            else 0
        )
        return {
            "samples": len(totals),
            "steady_group_pss_bytes": sum(totals) / len(totals),
            "peak_group_pss_bytes": max(totals),
            "steady_owner_pss_bytes": owner,
        }


def _count(record: Payload, *keys: str) -> int:
    value: object = record
    for key in keys:
        value = cast("Payload", value)[key]
    return cast("int", value)


@dataclass(frozen=True, slots=True)
class _Workload:
    keys: tuple[int, ...]
    read: str
    limit: int
    expected_invalidations: NonNegativeInt
    expected_entries: NonNegativeInt
    writes: tuple[tuple[NonNegativeFloat, int], ...]


def _workload(registration: Registration, cell: Cell) -> _Workload:
    profile = registration.profile(cell.profile)
    seed = cast("int", registration.raw["seed"])
    keys = key_order(seed, profile_keys(profile))
    read, limit = (
        ("find", cast("int", profile["limit"]))
        if profile["read"] == "find"
        else ("find_one", 1)
    )
    if cell.workload != "cold":
        keys = keys[: registration.hot_keys]
    updates = write_count(registration, cell) if cell.workload == "active" else 0
    order = key_order(seed + 1, len(keys))
    targets = (
        tuple(keys[index] for index in order)
        if "write_keys" in registration.section("active")
        else order
    )
    return _Workload(
        keys=keys,
        read=read,
        limit=limit,
        expected_invalidations=updates if cell.path != "direct" else 0,
        expected_entries=1 if cell.workload == "cold" else len(keys),
        writes=tuple(
            (
                (ordinal + 0.5) * cell.window_seconds / updates,
                targets[ordinal % len(targets)],
            )
            for ordinal in range(updates)
        ),
    )


def _lag_capture(registration: Registration) -> tuple[int, int, int]:
    capture = cast("Payload", registration.section("active")["lag_capture"])
    return (
        cast("int", capture["windows"]),
        cast("int", capture["events"]),
        cast("int", capture["separation"]),
    )


def owner_config(
    registration: Registration,
    uri: str,
    directory: str,
    capability: bytes,
    path: PathKind,
) -> OwnerConfig:
    return OwnerConfig(
        socket_path=str(Path(directory) / "owner.sock"),
        capability=capability,
        mongodb_uri=uri,
        client_options=registration.section("client_options"),
        databases=(cast("str", registration.raw["database"]),),
        budget_bytes=cast("int", registration.raw["budget_bytes"]),
        max_entry_bytes=cast("int", registration.raw["max_entry_bytes"]),
        max_await_time_ms=cast("int", registration.raw["max_await_time_ms"]),
        limits=registration.limits(),
        lag_capture=_lag_capture(registration),
        shared_index=registration.shared_index() if path == "shared-index" else None,
    )


def attachment_for(config: OwnerConfig) -> AttachmentConfig:
    return AttachmentConfig(
        config.socket_path,
        config.capability,
        config.budget_bytes,
        config.max_entry_bytes,
        config.max_await_time_ms,
        config.limits.rpc_deadline_seconds,
        config.frame_limit,
        max_namespaces=(
            DEFAULT_MAX_NAMESPACES
            if config.shared_index is None
            else config.shared_index.namespaces
        ),
    )


class ProcessGroup:
    __slots__ = (
        "_context",
        "_directory",
        "_owner_config",
        "_specs",
        "connections",
        "control_connections",
        "owner",
        "owner_control",
        "owner_pid",
        "processes",
        "shutdown_seconds",
        "timeline_chunks",
        "timeline_connections",
    )

    def __init__(self, context: SpawnContext, shutdown_seconds: PositiveFloat) -> None:
        self._context = context
        self._directory: str | None = None
        self._owner_config: OwnerConfig | None = None
        self._specs: list[WorkerSpec] = []
        self.shutdown_seconds = shutdown_seconds
        self.processes: list[BaseProcess] = []
        self.connections: list[Connection] = []
        self.control_connections: list[Connection | None] = []
        self.timeline_connections: list[Connection | None] = []
        self.timeline_chunks: list[list[Payload]] = []
        self.owner: BaseProcess | None = None
        self.owner_control: Connection | None = None
        self.owner_pid: NonNegativeInt | None = None

    def start_owner(
        self,
        registration: Registration,
        uri: str,
        deadline: NonNegativeFloat,
        path: PathKind,
    ) -> AttachmentConfig:
        if self._directory is None:
            self._directory = tempfile.mkdtemp(prefix="shared-cache-")
        config = owner_config(
            registration,
            uri,
            self._directory,
            secrets.token_bytes(32)
            if self._owner_config is None
            else self._owner_config.capability,
            path,
        )
        self._owner_config = config
        parent, child = self._context.Pipe()
        self.owner = self._context.Process(target=owner_main, args=(config, child))
        self.owner.start()
        child.close()
        self.owner_control = parent
        self.owner_pid = _count(receive(parent, deadline, "ready"), "pid")
        return attachment_for(config)

    def start_worker(self, spec: WorkerSpec) -> None:
        process, parent, control, timeline = self._launch_worker(spec)
        self._specs.append(spec)
        self.processes.append(process)
        self.connections.append(parent)
        self.control_connections.append(control)
        self.timeline_connections.append(timeline)
        self.timeline_chunks.append([])

    def _launch_worker(
        self, spec: WorkerSpec
    ) -> tuple[BaseProcess, Connection, Connection | None, Connection | None]:
        parent, child = self._context.Pipe()
        control_parent: Connection | None = None
        control_child: Connection | None = None
        timeline_parent: Connection | None = None
        timeline_child: Connection | None = None
        if spec.controls_enabled:
            control_parent, control_child = self._context.Pipe()
        if spec.timeline_enabled:
            timeline_parent, timeline_child = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=worker_main,
            args=(child, spec, control_child, timeline_child),
        )
        process.start()
        child.close()
        if control_child is not None:
            control_child.close()
        if timeline_child is not None:
            timeline_child.close()
        return process, parent, control_parent, timeline_parent

    def drain_timeline_chunks(self, index: NonNegativeInt | None = None) -> None:
        indexes = range(len(self.timeline_connections)) if index is None else (index,)
        for worker_index in indexes:
            timeline = self.timeline_connections[worker_index]
            if timeline is None or timeline.closed:
                continue
            while timeline.poll():
                try:
                    chunk = cast("Payload", timeline.recv())
                except EOFError:
                    break
                except OSError:
                    if not self.processes[worker_index].is_alive():
                        break
                    raise
                if chunk["kind"] != "timeline_chunk":
                    raise BenchmarkSetupError(
                        "worker returned an invalid timeline chunk"
                    )
                self.timeline_chunks[worker_index].append(chunk)

    def received_timeline(self, index: NonNegativeInt) -> list[Payload]:
        self.drain_timeline_chunks(index)
        return self.timeline_chunks[index]

    def control_worker(
        self,
        index: NonNegativeInt,
        operation: Literal["sever", "lose-history", "snapshot", "probe"],
        **fields: object,
    ) -> Payload:
        control = self.control_connections[index]
        if control is None:
            raise BenchmarkSetupError("worker controls are not enabled")
        control.send({"op": operation, **fields})
        if not control.poll(_CONTROL_GRACE_SECONDS):
            raise BenchmarkSetupError("worker control did not answer in time")
        response = cast("Payload", control.recv())
        if response["kind"] != "control" or response["operation"] != operation:
            raise BenchmarkSetupError("worker returned an unexpected control response")
        return response

    def control_workers(
        self,
        operation: Literal["sever", "lose-history", "snapshot", "probe"],
        **fields: object,
    ) -> list[Payload]:
        controls = self.control_connections
        if any(control is None for control in controls):
            raise BenchmarkSetupError(
                "worker controls are not enabled for every worker"
            )
        deadline = time.monotonic() + _CONTROL_GRACE_SECONDS
        for control in controls:
            assert control is not None
            control.send({"op": operation, **fields})
        responses: list[Payload] = []
        for control in controls:
            assert control is not None
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not control.poll(remaining):
                raise BenchmarkSetupError("worker control did not answer in time")
            response = cast("Payload", control.recv())
            if response["kind"] != "control" or response["operation"] != operation:
                raise BenchmarkSetupError(
                    "worker returned an unexpected control response"
                )
            responses.append(response)
        return responses

    def collect_worker(
        self,
        index: NonNegativeInt,
        kind: str,
        deadline: NonNegativeFloat,
        *,
        drain_timelines: bool = True,
    ) -> Payload:
        connection = self.connections[index]
        while True:
            if drain_timelines:
                self.drain_timeline_chunks()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not connection.poll(remaining):
                message = f"worker {kind} deadline exceeded"
                raise BenchmarkSetupError(message)
            response = cast("Payload", connection.recv())
            if response["kind"] == "failure":
                raise BenchmarkSetupError(str(response["error"]))
            if response["kind"] != kind:
                message_text = f"unexpected worker message at {kind}"
                raise BenchmarkSetupError(message_text)
            return response

    def kill_and_replace(
        self,
        index: NonNegativeInt,
        spec: WorkerSpec | None = None,
        *,
        spec_factory: Callable[[NonNegativeFloat], WorkerSpec] | None = None,
        before_kill: Callable[[NonNegativeFloat], None] | None = None,
    ) -> None:
        if spec is not None and spec_factory is not None:
            raise BenchmarkSetupError(
                "replacement worker accepts a spec or a spec factory, not both"
            )
        if spec is not None and spec.index != index:
            raise BenchmarkSetupError("replacement spec has another worker index")
        process = self.processes[index]
        killed_at = time.monotonic()
        if before_kill is not None:
            before_kill(killed_at)
        process.kill()
        process.join(self.shutdown_seconds)
        if process.is_alive():
            raise BenchmarkSetupError("killed worker failed to exit")
        self.drain_timeline_chunks(index)
        self.connections[index].close()
        control = self.control_connections[index]
        if control is not None:
            control.close()
        timeline = self.timeline_connections[index]
        if timeline is not None:
            timeline.close()
        current_spec = self._specs[index]
        replacement_spec = current_spec if spec is None else spec
        if spec_factory is not None:
            replacement_spec = spec_factory(killed_at)
        if replacement_spec.index != index:
            raise BenchmarkSetupError("replacement spec has another worker index")
        self._specs[index] = replace(
            replacement_spec,
            timeline_generation=current_spec.timeline_generation + 1,
        )
        replacement, connection, replacement_control, replacement_timeline = (
            self._launch_worker(self._specs[index])
        )
        self.processes[index] = replacement
        self.connections[index] = connection
        self.control_connections[index] = replacement_control
        self.timeline_connections[index] = replacement_timeline

    def owner_request(self, request: Payload, deadline: NonNegativeFloat) -> Payload:
        control = self.owner_control
        assert control is not None
        control.send(request)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not control.poll(remaining):
            raise BenchmarkSetupError("shared cache owner did not answer in time")
        return cast("Payload", control.recv())

    def collect(self, kind: str, deadline: NonNegativeFloat) -> list[Payload]:
        records: list[Payload] = []
        for connection in self.connections:
            while True:
                self.drain_timeline_chunks()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    message_text = f"worker {kind} deadline exceeded"
                    raise BenchmarkSetupError(message_text)
                wait = min(remaining, _OWNER_POLL_SECONDS)
                if not connection.poll(wait):
                    continue
                message = cast("Payload", connection.recv())
                if message["kind"] == "failure":
                    raise BenchmarkSetupError(str(message["error"]))
                if message["kind"] != kind:
                    message_text = f"unexpected worker message at {kind}"
                    raise BenchmarkSetupError(message_text)
                records.append(message)
                break
        self.drain_timeline_chunks()
        return records

    def stop(self) -> None:
        for control in self.control_connections:
            if control is not None:
                try:
                    control.send({"op": "close"})
                except BrokenPipeError:
                    pass
        for connection in self.connections:
            try:
                connection.send("close")
            except BrokenPipeError:
                pass
        deadline = time.monotonic() + self.shutdown_seconds
        stop_workers(tuple(self.processes), max(0.0, deadline - time.monotonic()))
        self.drain_timeline_chunks()
        for timeline in self.timeline_connections:
            if timeline is not None:
                timeline.close()
        if self.owner_control is not None:
            assert self.owner is not None
            self.owner_control.send("close")
            receive(self.owner_control, deadline, "closed")
            stop_workers((self.owner,), max(0.0, deadline - time.monotonic()))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        for control in self.control_connections:
            if control is not None:
                try:
                    control.send({"op": "close"})
                except BrokenPipeError:
                    pass
        for connection in self.connections:
            try:
                connection.send("close")
            except BrokenPipeError:
                pass
        for connection in self.connections:
            connection.close()
        for control in self.control_connections:
            if control is not None:
                control.close()
        deadline = time.monotonic() + self.shutdown_seconds
        reclaim_workers(tuple(self.processes), deadline, graceful=True)
        self.drain_timeline_chunks()
        for timeline in self.timeline_connections:
            if timeline is not None:
                timeline.close()
        if self.owner is not None:
            assert self.owner_control is not None
            if self.owner.is_alive():
                try:
                    self.owner_control.send("close")
                except OSError:
                    pass
            self.owner_control.close()
            reclaim_workers((self.owner,), deadline, graceful=True)
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)


def _wait_with_timeline(group: ProcessGroup, deadline: NonNegativeFloat) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        group.drain_timeline_chunks()
        time.sleep(min(remaining, _OWNER_POLL_SECONDS))
    group.drain_timeline_chunks()


def _assigned_keys(
    registration: Registration, workload: _Workload, index: NonNegativeInt
) -> tuple[NonNegativeInt, ...]:
    if registration.key_assignment == "shared":
        return worker_keys(cast("int", registration.raw["seed"]), index, workload.keys)
    return workload.keys


def _warm_key(
    registration: Registration,
    cell: Cell,
    workload: _Workload,
    index: NonNegativeInt,
) -> NonNegativeInt:
    workers = range(cell.workers) if cell.path not in BASELINES else (index,)
    assignments = {
        worker: assignment_for(
            cell,
            worker,
            _assigned_keys(registration, workload, worker),
            registration.key_assignment,
            warmup=False,
        )
        for worker in workers
    }
    measured = frozenset().union(*map(measured_keys, assignments.values()))
    return warm_key(assignments[index], measured)


def _spec(
    registration: Registration,
    cell: Cell,
    workload: _Workload,
    uri: str,
    *,
    index: NonNegativeInt,
    attachment: AttachmentConfig | None,
    timeline_enabled: bool = False,
    timeline_cadence_seconds: PositiveFloat = 0.25,
    scheduled_ordinals: tuple[NonNegativeInt, ...] | None = None,
) -> WorkerSpec:
    keys = _assigned_keys(registration, workload, index)
    fault_case = cell.fault_case if isinstance(cell, RecoveryFaultCell) else None
    topology = (
        cell.topology
        if isinstance(cell, (RecoveryFaultCell, CalibrationTopologyCell))
        else "single-member"
    )
    return WorkerSpec(
        cell=cell,
        index=index,
        model="sync" if index < cell.sync_workers() else "async",
        uri=uri,
        database=cast("str", registration.raw["database"]),
        collection=cast("str", registration.raw["collection"]),
        client_options=registration.section("client_options"),
        read=workload.read,  # type: ignore[arg-type]
        limit=workload.limit,
        keys=keys,
        key_assignment=registration.key_assignment,
        warm_key=_warm_key(registration, cell, workload, index)
        if cell.workload == "cold"
        else None,
        budget_bytes=cast("int", registration.raw["budget_bytes"]),
        max_entry_bytes=cast("int", registration.raw["max_entry_bytes"]),
        max_await_time_ms=cast("int", registration.raw["max_await_time_ms"]),
        lag_capture=_lag_capture(registration),
        attachment=attachment,
        outstanding=cast("int", registration.raw["outstanding_per_worker"]),
        drain_seconds=registration.number("drain_seconds"),
        expected_invalidations=(
            workload.expected_invalidations
            if cell.path == "independent" and not isinstance(cell, RecoveryFaultCell)
            else 0
        ),
        controls_enabled=fault_case is not None,
        timeline_enabled=timeline_enabled
        or (cell.phase == "fault" and cell.path in BASELINES),
        timeline_cadence_seconds=timeline_cadence_seconds,
        scheduled_ordinals=scheduled_ordinals,
        topology=topology,
    )


def _verify_ready(
    group: ProcessGroup,
    cell: Cell,
    workload: _Workload,
    ready: list[Payload],
    deadline: NonNegativeFloat,
) -> None:
    if cell.path == "independent" and any(
        sample["entries"] != workload.expected_entries for sample in ready
    ):
        raise BenchmarkSetupError("independent working set was not fully admitted")
    if group.owner_control is not None:
        primed = group.owner_request({"op": "sample"}, deadline)
        if _count(primed, "observation", "cache", "entry_count") < (
            workload.expected_entries
        ):
            raise BenchmarkSetupError("shared working set was not fully admitted")
        if (
            cell.path == "shared-index"
            and workload.read == "find_one"
            and _count(primed, "observation", "shared_index", "published")
            < workload.expected_entries
        ):
            raise BenchmarkSetupError("shared index did not publish the working set")
        group.owner_request({"op": "reset"}, deadline)
    per_worker = 1 if cell.path == "independent" else 0
    if any(_count(sample, "streams") != per_worker for sample in ready):
        raise BenchmarkSetupError("worker stream ownership differs from its path")


def reject_failed_commands(samples: list[Payload]) -> None:
    for sample in samples:
        commands = cast("dict[str, int]", sample["commands"])
        if any(count for key, count in commands.items() if key.endswith(":failed")):
            raise BenchmarkSetupError("observed a failed wire command")


def _pooled(samples: list[Payload], model: str | None) -> Payload:
    return scalar_latency_distribution(
        [
            value
            for sample in samples
            if model is None or sample["model"] == model
            for value in cast("list[float]", sample["latencies"])
        ]
    )


def _owner_record(before: Payload, end: Payload, drained: Payload) -> Payload:
    return {
        "cpu_seconds": cast("float", end["cpu_seconds"])
        - cast("float", before["cpu_seconds"]),
        "drain_cpu_seconds": cast("float", drained["cpu_seconds"])
        - cast("float", end["cpu_seconds"]),
        "wire_sent": _count(drained, "wire_sent") - _count(before, "wire_sent"),
        "wire_received": _count(drained, "wire_received")
        - _count(before, "wire_received"),
        "commands": command_delta(
            cast("dict[str, int]", before["commands"]),
            cast("dict[str, int]", drained["commands"]),
        ),
        "observation": drained["observation"],
        "before": before["observation"],
        "invalidations": drained["invalidations"],
        "lag_windows": drained["lag_windows"],
        "health": drained["health"],
    }


def _drain_owner(
    group: ProcessGroup,
    end: Payload,
    expected: NonNegativeInt,
    deadline: NonNegativeFloat,
) -> Payload:
    drained = end
    while _count(drained, "invalidations") < expected:
        time.sleep(_OWNER_POLL_SECONDS)
        if time.monotonic() > deadline:
            raise BenchmarkSetupError("shared invalidation drain incomplete")
        drained = group.owner_request(
            {"op": "sample"}, deadline + _CONTROL_GRACE_SECONDS
        )
    return drained


def _check_clock(
    registration: Registration, cell: Cell, calibration: CalibrationSeries
) -> None:
    tolerance = registration.number("clock_tolerance_seconds")
    if cell.workload == "active" and (
        calibration.exceeds_drift_tolerance(tolerance)
        or calibration.has_host_clock_step(tolerance_seconds=tolerance)
        or calibration.has_election_change
    ):
        raise BenchmarkSetupError("clock or primary changed during window")


def _timed_write(collection: Collection[BsonDict], target: int) -> float:
    started = time.monotonic()
    collection.update_one({"_id": target}, {"$inc": {"revision": 1}})
    return time.monotonic() - started


def _process_cpu() -> float:
    times = psutil.Process().cpu_times()
    return times.user + times.system


def _server_cpu_usage(replica: IsolatedReplicaSet | ReplicaSetTopology) -> float:
    if isinstance(replica, ReplicaSetTopology):
        return sum(replica.container_cpu_usage_seconds(index) for index in range(3))
    return replica.container_cpu_usage_seconds()


def _server_memory_usage(
    replica: IsolatedReplicaSet | ReplicaSetTopology,
) -> NonNegativeInt:
    if isinstance(replica, ReplicaSetTopology):
        return sum(replica.container_memory_usage_bytes(index) for index in range(3))
    return replica.container_memory_usage_bytes()


def _client_options(
    replica: IsolatedReplicaSet | ReplicaSetTopology, options: dict[str, object]
) -> dict[str, object]:
    if isinstance(replica, ReplicaSetTopology):
        options["directConnection"] = False
    return options


def run_window(
    replica: IsolatedReplicaSet | ReplicaSetTopology,
    registration: Registration,
    cell: Cell,
    *,
    timeline_enabled: bool = False,
    timeline_cadence_seconds: PositiveFloat = 0.25,
) -> Payload:
    if isinstance(cell, RecoveryFaultCell):
        from benchmarks.stream_cost.shared_cache.fault_recovery import (  # noqa: PLC0415 - Recovery faults use the shared worker lifecycle defined here.
            run_recovery_fault_window,
        )

        return run_recovery_fault_window(replica, registration, cell)
    if cell.phase == "fault":
        from benchmarks.stream_cost.shared_cache.faults import run_fault_window  # noqa: PLC0415 - Fault driver reuses window process lifecycle.

        if isinstance(replica, ReplicaSetTopology):
            raise BenchmarkSetupError(
                "shared-cache fault windows require a single-member replica set"
            )
        return run_fault_window(replica, registration, cell)
    database = cast("str", registration.raw["database"])
    collection = cast("str", registration.raw["collection"])
    client_options = _client_options(
        replica, dict(registration.section("client_options"))
    )
    workload = _workload(registration, cell)
    with ExitStack() as resources:
        writer_proxy = (
            None
            if isinstance(replica, ReplicaSetTopology)
            else resources.enter_context(proxy_for(replica.uri))
        )
        observer_proxy = (
            None
            if isinstance(replica, ReplicaSetTopology)
            else resources.enter_context(proxy_for(replica.uri))
        )
        writer_listener = WireCommands((collection,))
        writer_uri = (
            replica.uri
            if writer_proxy is None
            else f"mongodb://127.0.0.1:{writer_proxy.local_port}"
        )
        observer_uri = (
            replica.uri
            if observer_proxy is None
            else f"mongodb://127.0.0.1:{observer_proxy.local_port}"
        )
        writer = resources.enter_context(
            MongoClient[BsonDict](
                writer_uri,
                event_listeners=[writer_listener],
                **client_options,  # type: ignore[arg-type]
            )
        )
        observer = resources.enter_context(
            MongoClient[BsonDict](
                observer_uri,
                **client_options,  # type: ignore[arg-type]
            )
        )
        dataset = seed_catalogue(
            writer,
            database=database,
            collection=collection,
            seed=cast("int", registration.raw["seed"]),
            profile=registration.profile(cell.profile),  # type: ignore[arg-type]
            categories=registration.categories,
        )
        sampler = PeriodicCalibrationSampler(
            lambda: observer.admin.command("hello"),
            cadence_seconds=registration.number("calibration_seconds"),
            rounds=3,
        )
        sampler.start()
        resources.callback(sampler.stop)
        group = resources.enter_context(
            ProcessGroup(
                multiprocessing.get_context("spawn"),
                registration.number("shutdown_seconds"),
            )
        )
        startup_deadline = time.monotonic() + registration.number("startup_seconds")
        attachment = (
            group.start_owner(registration, replica.uri, startup_deadline, cell.path)
            if cell.path not in BASELINES
            else None
        )
        for index in range(cell.workers):
            group.start_worker(
                _spec(
                    registration,
                    cell,
                    workload,
                    replica.uri,
                    index=index,
                    attachment=attachment,
                    timeline_enabled=timeline_enabled,
                    timeline_cadence_seconds=timeline_cadence_seconds,
                )
            )
        ready = group.collect("ready", startup_deadline)
        _verify_ready(group, cell, workload, ready, startup_deadline)
        pids = {f"worker-{sample['index']}": _count(sample, "pid") for sample in ready}
        if group.owner_pid is not None:
            pids["owner"] = group.owner_pid
        start = time.monotonic() + _START_LEAD_SECONDS
        for connection in group.connections:
            connection.send(start)
        window_start = start + cell.warmup_seconds
        window_end = window_start + cell.window_seconds
        _wait_with_timeline(group, window_start - 0.05)
        harness_before = _process_cpu()  # pytriage: TR11 (metric boundary)
        # Sample at the measurement window start.
        server_before = _server_cpu_usage(replica)  # pytriage: TR11
        commands_before = writer_listener.snapshot()  # pytriage: TR11 (metric boundary)
        writer_sent = (  # pytriage: TR11 (metric boundary)
            0 if writer_proxy is None else writer_proxy.bytes_sent
        )
        writer_received = (  # pytriage: TR11 (metric boundary)
            0 if writer_proxy is None else writer_proxy.bytes_received
        )
        owner_before = (
            group.owner_request({"op": "sample"}, window_end)
            if group.owner_control is not None
            else None
        )
        if owner_before is not None and profiling_enabled():
            group.owner_request({"op": "profile-start"}, window_end)
        write_offsets: list[NonNegativeFloat] = []
        write_lateness = 0.0
        pending: list[Future[float]] = []
        with (
            GroupMemorySampler(
                pids, registration.number("memory_sample_seconds")
            ) as memory,
            ThreadPoolExecutor(max_workers=_WRITERS) as writes,
        ):
            for offset, target in workload.writes:
                due = window_start + offset
                _wait_with_timeline(group, due)
                issued = time.monotonic()
                if cell.loop == "open" and issued - due > registration.number(
                    "schedule_tolerance_seconds"
                ):
                    raise BenchmarkSetupError("write schedule exceeded tolerance")
                write_offsets.append(issued - window_start)
                write_lateness = max(write_lateness, issued - due)
                pending.append(
                    writes.submit(_timed_write, writer[database][collection], target)
                )
            _wait_with_timeline(group, window_end)
        try:
            write_seconds = [future.result() for future in pending]
        except PyMongoError as error:
            raise BenchmarkSetupError("harness MongoDB write failed") from error
        if owner_before is not None and profiling_enabled():
            group.owner_request({"op": "profile-stop"}, window_end + 5)
        server_end = _server_cpu_usage(replica)
        server_memory = _server_memory_usage(replica)
        drain_deadline = (
            window_end + registration.number("drain_seconds") + _CONTROL_GRACE_SECONDS
        )
        owner_end = (
            group.owner_request({"op": "sample"}, drain_deadline)
            if group.owner_control is not None
            else None
        )
        samples = group.collect("sample", drain_deadline)
        reject_failed_commands(samples)
        owner_drained = (
            _drain_owner(
                group, owner_end, workload.expected_invalidations, drain_deadline
            )
            if owner_end is not None
            else None
        )
        calibration = CalibrationSeries(sampler.stop())
        _check_clock(registration, cell, calibration)
        timelines: list[Payload] | None = None
        if timeline_enabled:
            timelines = []
            for index in range(cell.workers):
                events, snapshots = merge_chunks(group.received_timeline(index))
                timelines.append(
                    {"index": index, "events": events, "snapshots": snapshots}
                )
        server_drain_cpu_seconds = _server_cpu_usage(replica) - server_end
        harness_cpu_seconds = _process_cpu() - harness_before
        record: Payload = {
            **asdict(cell),
            "healthy": True,
            "dataset": dataset,
            "ready": ready,
            "server_cpu_seconds": server_end - server_before,
            "server_drain_cpu_seconds": server_drain_cpu_seconds,
            "server_memory_bytes": server_memory,
            "server_memory_scope": SERVER_MEMORY_SCOPE,
            "harness_cpu_seconds": harness_cpu_seconds,
            "harness_includes": HARNESS_INCLUDES,
            "writer": {
                "sent": None
                if writer_proxy is None
                else writer_proxy.bytes_sent - writer_sent,
                "received": None
                if writer_proxy is None
                else writer_proxy.bytes_received - writer_received,
                "commands": command_delta(commands_before, writer_listener.snapshot()),
                "offsets": write_offsets,
                "max_lateness_seconds": write_lateness,
                "max_write_seconds": max(write_seconds, default=0.0),
            },
            "memory": memory.summary(),
            "offered": sum(_count(sample, "loop", "offered") for sample in samples),
            "completed": sum(_count(sample, "loop", "completed") for sample in samples),
            "completed_in_window": sum(
                _count(sample, "loop", "completed_in_window") for sample in samples
            ),
            "populations": {
                "request": _pooled(samples, None),
                "sync": _pooled(samples, "sync"),
                "async": _pooled(samples, "async"),
            },
            "workers_measured": [
                {key: value for key, value in sample.items() if key != "latencies"}
                for sample in samples
            ],
            "clock_offset_seconds": calibration.initial.offset_seconds,
            "clock_uncertainty_seconds": calibration.total_uncertainty_seconds,
        }
        if owner_before is not None:
            assert owner_end is not None
            assert owner_drained is not None
            record["owner"] = _owner_record(owner_before, owner_end, owner_drained)
        if timelines is not None:
            record["fault_timeline"] = timelines
        group.stop()
        return record

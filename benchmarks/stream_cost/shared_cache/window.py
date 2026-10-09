from __future__ import annotations

import multiprocessing
import os
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Self, cast

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
from benchmarks.stream_cost.shared_cache.attachment import AttachmentConfig
from benchmarks.stream_cost.shared_cache.coordinator import OwnerConfig
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.owner import owner_main, proxy_for
from benchmarks.stream_cost.shared_cache.worker import WorkerSpec, worker_main
from benchmarks.stream_cost.shared_cache.workload import key_order

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.context import SpawnContext
    from multiprocessing.process import BaseProcess

    from benchmarks.stream_cost.shared_cache.protocol import Cell, Registration
    from benchmarks.stream_cost.topology import IsolatedReplicaSet
    from client_query_cache._types import (
        NonNegativeFloat,
        NonNegativeInt,
        PositiveFloat,
    )

type Payload = dict[str, object]

_START_LEAD_SECONDS = 1.0
_OWNER_POLL_SECONDS = 0.01
_CONTROL_GRACE_SECONDS = 5.0
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
        processes = {name: psutil.Process(pid) for name, pid in self._pids.items()}
        while not self._stop.is_set():
            try:
                self.samples.append(
                    {
                        name: process.memory_full_info().pss
                        for name, process in processes.items()
                    }
                )
            except psutil.Error as error:
                self.error = f"PSS sampling failed: {error}"
                return
            self._stop.wait(self._seconds)

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


def _wait(deadline: NonNegativeFloat) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        time.sleep(min(remaining, 1.0))


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
    if profile["read"] == "find":
        keys = key_order(seed, cast("int", profile["categories"]))
        read, limit = "find", cast("int", profile["limit"])
    else:
        keys = key_order(seed, cast("int", profile["documents"]))
        read, limit = "find_one", 1
    updates = cast("int", registration.section("active")["updates"])
    active = cell.workload == "active"
    targets = key_order(seed + 1, len(keys))
    return _Workload(
        keys=keys,
        read=read,
        limit=limit,
        expected_invalidations=updates if active and cell.path != "direct" else 0,
        expected_entries=1 if cell.workload == "cold" else len(keys),
        writes=tuple(
            ((ordinal + 0.5) * cell.window_seconds / updates, targets[ordinal])
            for ordinal in range(updates)
        )
        if active
        else (),
    )


def _lag_capture(registration: Registration) -> tuple[int, int, int]:
    capture = cast("Payload", registration.section("active")["lag_capture"])
    return (
        cast("int", capture["windows"]),
        cast("int", capture["events"]),
        cast("int", capture["separation"]),
    )


def owner_config(
    registration: Registration, uri: str, directory: str, capability: bytes
) -> OwnerConfig:
    return OwnerConfig(
        socket_path=os.path.join(directory, "owner.sock"),  # noqa: PTH118
        capability=capability,
        mongodb_uri=uri,
        client_options=registration.section("client_options"),
        databases=(cast("str", registration.raw["database"]),),
        budget_bytes=cast("int", registration.raw["budget_bytes"]),
        max_entry_bytes=cast("int", registration.raw["max_entry_bytes"]),
        max_await_time_ms=cast("int", registration.raw["max_await_time_ms"]),
        limits=registration.limits(),
        lag_capture=_lag_capture(registration),
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
    )


class ProcessGroup:
    __slots__ = (
        "_context",
        "_directory",
        "connections",
        "owner",
        "owner_control",
        "owner_pid",
        "processes",
        "shutdown_seconds",
    )

    def __init__(self, context: SpawnContext, shutdown_seconds: PositiveFloat) -> None:
        self._context = context
        self._directory: str | None = None
        self.shutdown_seconds = shutdown_seconds
        self.processes: list[BaseProcess] = []
        self.connections: list[Connection] = []
        self.owner: BaseProcess | None = None
        self.owner_control: Connection | None = None
        self.owner_pid: NonNegativeInt | None = None

    def start_owner(
        self, registration: Registration, uri: str, deadline: NonNegativeFloat
    ) -> AttachmentConfig:
        self._directory = tempfile.mkdtemp(prefix="shared-cache-")
        config = owner_config(
            registration, uri, self._directory, secrets.token_bytes(32)
        )
        parent, child = self._context.Pipe()
        self.owner = self._context.Process(target=owner_main, args=(config, child))
        self.owner.start()
        child.close()
        self.owner_control = parent
        self.owner_pid = _count(receive(parent, deadline, "ready"), "pid")
        return attachment_for(config)

    def start_worker(self, spec: WorkerSpec) -> None:
        parent, child = self._context.Pipe()
        process = self._context.Process(target=worker_main, args=(child, spec))
        process.start()
        child.close()
        self.processes.append(process)
        self.connections.append(parent)

    def owner_request(self, request: Payload, deadline: NonNegativeFloat) -> Payload:
        control = self.owner_control
        assert control is not None
        control.send(request)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not control.poll(remaining):
            raise BenchmarkSetupError("shared cache owner did not answer in time")
        return cast("Payload", control.recv())

    def collect(self, kind: str, deadline: NonNegativeFloat) -> list[Payload]:
        return [receive(connection, deadline, kind) for connection in self.connections]

    def stop(self) -> None:
        deadline = time.monotonic() + self.shutdown_seconds
        for connection in self.connections:
            connection.send("close")
        stop_workers(tuple(self.processes), max(0.0, deadline - time.monotonic()))
        if self.owner_control is not None:
            assert self.owner is not None
            self.owner_control.send("close")
            receive(self.owner_control, deadline, "closed")
            stop_workers((self.owner,), max(0.0, deadline - time.monotonic()))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        deadline = time.monotonic() + self.shutdown_seconds
        for connection in self.connections:
            connection.close()
        reclaim_workers(tuple(self.processes), deadline, graceful=True)
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


def _spec(
    registration: Registration,
    cell: Cell,
    workload: _Workload,
    uri: str,
    *,
    index: NonNegativeInt,
    attachment: AttachmentConfig | None,
) -> WorkerSpec:
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
        keys=workload.keys,
        warm_key=workload.keys[-1 - index],
        budget_bytes=cast("int", registration.raw["budget_bytes"]),
        max_entry_bytes=cast("int", registration.raw["max_entry_bytes"]),
        max_await_time_ms=cast("int", registration.raw["max_await_time_ms"]),
        lag_capture=_lag_capture(registration),
        attachment=attachment,
        outstanding=cast("int", registration.raw["outstanding_per_worker"]),
        drain_seconds=registration.number("drain_seconds"),
        startup_seconds=registration.number("startup_seconds"),
        expected_invalidations=workload.expected_invalidations
        if cell.path == "independent"
        else 0,
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
        group.owner_request({"op": "reset"}, deadline)
    expected_streams = cell.workers if cell.path == "independent" else 0
    if sum(_count(sample, "streams") for sample in ready) != expected_streams:
        raise BenchmarkSetupError("worker stream ownership differs from its path")


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
        if time.monotonic() > deadline:
            raise BenchmarkSetupError("shared invalidation drain incomplete")
        time.sleep(_OWNER_POLL_SECONDS)
        drained = group.owner_request({"op": "sample"}, deadline)
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


def _process_cpu() -> float:
    times = psutil.Process().cpu_times()
    return times.user + times.system


def run_window(
    replica: IsolatedReplicaSet, registration: Registration, cell: Cell
) -> Payload:
    database = cast("str", registration.raw["database"])
    collection = cast("str", registration.raw["collection"])
    client_options = registration.section("client_options")
    workload = _workload(registration, cell)
    with ExitStack() as resources:
        writer_proxy = resources.enter_context(proxy_for(replica.uri))
        observer_proxy = resources.enter_context(proxy_for(replica.uri))
        writer_listener = WireCommands((collection,))
        writer = resources.enter_context(
            MongoClient[dict[str, object]](
                f"mongodb://127.0.0.1:{writer_proxy.local_port}",
                event_listeners=[writer_listener],
                **client_options,  # type: ignore[arg-type]
            )
        )
        observer = resources.enter_context(
            MongoClient[dict[str, object]](
                f"mongodb://127.0.0.1:{observer_proxy.local_port}",
                **client_options,  # type: ignore[arg-type]
            )
        )
        dataset = seed_catalogue(
            writer,
            database=database,
            collection=collection,
            seed=cast("int", registration.raw["seed"]),
            profile=registration.profile(cell.profile),  # type: ignore[arg-type]
            categories=cast("int", registration.profile("find16")["categories"]),
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
            group.start_owner(registration, replica.uri, startup_deadline)
            if cell.path == "shared"
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
        window_end = window_start + cell.window_seconds  # pytriage: TR11 (schedule)
        _wait(window_start - 0.05)
        harness_before = _process_cpu()  # pytriage: TR11 (metric boundary)
        server_before = replica.container_cpu_usage_seconds()  # pytriage: TR11
        commands_before = writer_listener.snapshot()  # pytriage: TR11 (metric boundary)
        writer_sent = writer_proxy.bytes_sent  # pytriage: TR11 (metric boundary)
        writer_received = writer_proxy.bytes_received  # pytriage: TR11
        owner_before = (
            group.owner_request({"op": "sample"}, window_end)
            if group.owner_control is not None
            else None
        )
        write_offsets: list[NonNegativeFloat] = []
        with GroupMemorySampler(
            pids, registration.number("memory_sample_seconds")
        ) as memory:
            for offset, target in workload.writes:
                due = window_start + offset
                _wait(due)
                issued = time.monotonic()
                if issued - due > registration.number("schedule_tolerance_seconds"):
                    raise BenchmarkSetupError("write schedule exceeded tolerance")
                write_offsets.append(issued - window_start)
                try:
                    writer[database][collection].update_one(
                        {"_id": target}, {"$inc": {"revision": 1}}
                    )
                except PyMongoError as error:
                    raise BenchmarkSetupError("harness MongoDB write failed") from error
            _wait(window_end)
        server_end = replica.container_cpu_usage_seconds()
        server_memory = replica.container_memory_usage_bytes()
        drain_deadline = (
            window_end + registration.number("drain_seconds") + _CONTROL_GRACE_SECONDS
        )
        owner_end = (
            group.owner_request({"op": "sample"}, drain_deadline)
            if group.owner_control is not None
            else None
        )
        samples = group.collect("sample", drain_deadline)
        owner_drained = (
            _drain_owner(
                group, owner_end, workload.expected_invalidations, drain_deadline
            )
            if owner_end is not None
            else None
        )
        server_drained = replica.container_cpu_usage_seconds()
        harness_after = _process_cpu()
        calibration = CalibrationSeries(sampler.stop())
        _check_clock(registration, cell, calibration)
        group.stop()
        record: Payload = {
            **asdict(cell),
            "healthy": True,
            "dataset": dataset,
            "ready": ready,
            "server_cpu_seconds": server_end - server_before,
            "server_drain_cpu_seconds": server_drained - server_end,
            "server_memory_bytes": server_memory,
            "server_memory_scope": SERVER_MEMORY_SCOPE,
            "harness_cpu_seconds": harness_after - harness_before,
            "harness_includes": HARNESS_INCLUDES,
            "writer": {
                "sent": writer_proxy.bytes_sent - writer_sent,
                "received": writer_proxy.bytes_received - writer_received,
                "commands": command_delta(commands_before, writer_listener.snapshot()),
                "offsets": write_offsets,
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
        return record

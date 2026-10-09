from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import multiprocessing
import random
import shutil
import subprocess
import threading
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, cast
from urllib.parse import urlsplit

import psutil
from bson import BSON
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.change_stream import AsyncDatabaseChangeStream
from pymongo.errors import PyMongoError
from pymongo.monitoring import CommandListener
from pymongo.synchronous.change_stream import DatabaseChangeStream

from benchmarks.stream_cost.calibration import (
    CalibrationSeries,
    PeriodicCalibrationSampler,
)
from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.measurement import scalar_latency_distribution
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
from client_query_cache._core.stream_events import (
    _wall_time_seconds,
    build_change_stream_pipeline,
)
from client_query_cache._types import (
    MaxAwaitTimeMs,
    NonEmpty,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )

_CONFIG = Path("reports/stream-cost/shared-invalidation-v1/config.json")
_DATABASE = "shared_invalidation_research"
_TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)
type Model = Literal["sync", "async"]
type Workload = Literal["idle", "active"]
type PathKind = Literal["native-control", "native", "stream-control", "stream-only"]
type Client = MongoClient[dict[str, object]] | AsyncMongoClient[dict[str, object]]
type Manager = CacheManager[dict[str, object]] | AsyncCacheManager[dict[str, object]]
type Stream = (
    DatabaseChangeStream[dict[str, object]]
    | AsyncDatabaseChangeStream[dict[str, object]]
)
type Payload = dict[str, object]


class CaptureConfiguration(TypedDict):
    windows: PositiveInt
    events: PositiveInt  # Per window.
    separation: NonNegativeInt


class ClientOptions(TypedDict):
    directConnection: bool
    serverSelectionTimeoutMS: PositiveInt


class RegisteredConfiguration(TypedDict):
    blocks: PositiveInt  # Paired blocks.
    models: NonEmpty[list[Model]]
    worker_counts: NonEmpty[list[PositiveInt]]
    workloads: NonEmpty[list[Workload]]
    paths: NonEmpty[list[PathKind]]
    seed: int
    collections: NonEmpty[list[str]]
    payload_bytes: PositiveInt  # Encoded padding length.
    max_await_time_ms: MaxAwaitTimeMs
    lag_capture: CaptureConfiguration
    calibration_seconds: PositiveFloat  # Sampling interval.
    clock_tolerance_seconds: PositiveFloat  # Drift tolerance.
    client_options: ClientOptions


def load_registration() -> RegisteredConfiguration:
    return cast("RegisteredConfiguration", json.loads(_CONFIG.read_bytes()))


@dataclass(frozen=True, slots=True)
class Protocol:
    window_seconds: PositiveFloat  # Application duration.
    documents: PositiveInt  # Even working-set size.
    reads: PositiveInt  # Aggregate active read count.
    updates: PositiveInt  # Aggregate active write count.
    read_interval_seconds: PositiveFloat  # Pacing interval.
    update_interval_seconds: PositiveFloat  # Pacing interval.
    schedule_tolerance_seconds: PositiveFloat  # Allowed lateness.
    startup_seconds: PositiveFloat  # Group startup deadline.
    drain_seconds: PositiveFloat  # Group drain deadline.
    shutdown_seconds: PositiveFloat  # Group shutdown deadline.
    registration: RegisteredConfiguration = field(default_factory=load_registration)

    @classmethod
    def load(cls) -> Protocol:
        configuration = json.loads(_CONFIG.read_bytes())
        return cls(
            **{
                name: configuration[name]
                for name in cls.__dataclass_fields__
                if name != "registration"
            },
            registration=cast("RegisteredConfiguration", configuration),
        )

    @classmethod
    def smoke(cls) -> Protocol:
        return cls(1.0, 16, 20, 4, 0.04, 0.2, 0.05, 30, 10, 10)


@dataclass(frozen=True, slots=True)
class Cell:
    block: NonNegativeInt  # Zero-based.
    model: Model
    workers: PositiveInt
    workload: Workload
    path: PathKind


def planned_cells() -> tuple[Cell, ...]:
    registration = load_registration()
    cells: list[Cell] = []
    for block in range(registration["blocks"]):
        models = tuple(registration["models"])
        counts = tuple(registration["worker_counts"])
        workloads = tuple(registration["workloads"])
        paths = tuple(registration["paths"])
        if block % 2:
            models, counts, workloads, paths = (
                models[::-1],
                counts[::-1],
                workloads[::-1],
                paths[::-1],
            )
        cells.extend(
            Cell(block, model, workers, workload, path)
            for model in models
            for workers in counts
            for workload in workloads
            for path in paths
        )
    return tuple(cells)


def partition_reads(protocol: Protocol, workers: int, worker: int) -> tuple[int, ...]:
    return tuple(range(worker, protocol.reads, workers))


def reads_for_path(path: PathKind, workload: Workload) -> bool:
    return workload == "active" and path in {"native", "native-control"}


def capture_ordinals() -> tuple[tuple[int, ...], ...]:
    capture = load_registration()["lag_capture"]
    stride = capture["events"] + capture["separation"]
    return tuple(
        tuple(range(1 + stride * index, 1 + stride * index + capture["events"]))
        for index in range(capture["windows"])
    )


def validate_capture(
    invalidations: int, windows: tuple[tuple[float, ...], ...], expected: int
) -> None:
    if invalidations != expected:
        message = f"received {invalidations}/{expected} invalidations"
        raise BenchmarkSetupError(message)
    capture = load_registration()["lag_capture"]
    if (
        expected == capture_ordinals()[-1][-1]
        and tuple(map(len, windows)) != (capture["events"],) * capture["windows"]
    ):
        raise BenchmarkSetupError("incomplete registered lag capture")


class WireCommands(CommandListener):
    def __init__(self, collections: tuple[str, ...]) -> None:
        self._collections = frozenset(collections)
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self.streams = 0
        self._event_wall_seconds: list[float] = []
        self._poll_seconds: list[float] = []

    def _record(self, name: str, outcome: str) -> None:
        with self._lock:
            key = f"{name}:{outcome}"
            try:
                self._counts[key] += 1
            except KeyError:
                self._counts[key] = 1

    def started(self, event: CommandStartedEvent) -> None:
        self._record(event.command_name, "requested")
        if event.command_name == "aggregate" and any(
            "$changeStream" in stage for stage in event.command["pipeline"]
        ):
            with self._lock:
                self.streams += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        self._record(event.command_name, "completed")
        if event.command_name in {"aggregate", "getMore"}:
            cursor = event.reply["cursor"]
            try:
                batch = cursor["nextBatch"]
            except KeyError:
                batch = cursor["firstBatch"]
            with self._lock:
                if event.command_name == "getMore":
                    self._poll_seconds.append(time.monotonic())
                self._event_wall_seconds.extend(
                    _wall_time_seconds(envelope["wallTime"])
                    for envelope in batch
                    if envelope["operationType"] == "update"
                    and envelope["ns"]["db"] == _DATABASE
                    and envelope["ns"]["coll"] in self._collections
                )

    def failed(self, event: CommandFailedEvent) -> None:
        self._record(event.command_name, "failed")

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return self._counts.copy()

    def event_wall_seconds(self) -> tuple[float, ...]:
        with self._lock:
            return tuple(self._event_wall_seconds)

    def poll_completion_seconds(self) -> tuple[float, ...]:
        with self._lock:
            return tuple(self._poll_seconds)


def idle_poll_max_gap(
    completions: tuple[float, ...],
    start: float,  # Monotonic.
    end: PositiveFloat,
    limit: PositiveFloat,  # Maximum polling gap.
) -> PositiveFloat:
    polls = tuple(stamp for stamp in completions if start <= stamp <= end)
    if not polls:
        raise BenchmarkSetupError("idle stream issued no completed getMore")
    boundaries = (start, *polls, end)
    longest = max(later - earlier for earlier, later in pairwise(boundaries))
    if longest > limit:
        message = f"idle getMore polling gap exceeded {limit:.3f}s"
        raise BenchmarkSetupError(message)
    return longest


def command_delta(
    before: Mapping[str, int], after: Mapping[str, int]
) -> dict[str, int]:
    deltas: dict[str, int] = {}
    for key, count in after.items():
        try:
            previous = before[key]
        except KeyError:
            previous = 0
        deltas[key] = count - previous
    return deltas


def process_reading() -> Payload:
    process = psutil.Process()
    try:
        cpu = process.cpu_times()
        private_bytes = process.memory_full_info().uss
    except psutil.Error as error:
        raise BenchmarkSetupError("required process CPU/USS unavailable") from error
    return {
        "pid": process.pid,
        "cpu_seconds": cpu.user + cpu.system,
        "uss_bytes": private_bytes,
    }


def cpu_delta(before: Payload, after: Payload) -> float:
    seconds = cast("float", after["cpu_seconds"]) - cast("float", before["cpu_seconds"])
    if not math.isfinite(seconds) or seconds < 0:
        raise BenchmarkSetupError("process CPU counter is invalid")
    return seconds


def proxy_for_uri(uri: str) -> DirectPathByteProxy:
    address = urlsplit(uri)
    assert address.hostname is not None
    assert address.port is not None
    return DirectPathByteProxy(
        DirectPathProxyConfig(_TOPOLOGY, address.hostname, address.port)
    )


async def invoke[**P, T](
    function: Callable[P, T | Awaitable[T]], *args: P.args, **kwargs: P.kwargs
) -> T:
    value = function(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def wait_until(
    deadline: float, tolerance: float, phase: Literal["start", "read", "end"]
) -> None:
    while (remaining := deadline - time.monotonic()) > 0:  # noqa: ASYNC110 - Bound timer slack, not a polled condition.
        await asyncio.sleep(min(remaining, 1.0))
    lateness = time.monotonic() - deadline
    if lateness > tolerance:
        message = (
            f"application {phase} schedule exceeded tolerance: {lateness:.6f}s late"
        )
        raise BenchmarkSetupError(message)


async def consume_stream(stream: Stream, observed: list[float]) -> None:
    while True:
        if isinstance(stream, DatabaseChangeStream):
            event = await asyncio.to_thread(stream.try_next)
        else:
            event = await stream.try_next()
        if event is not None:
            observed.append(time.monotonic())


async def worker_window(
    connection: Connection, uri: str, cell: Cell, worker: int, protocol: Protocol
) -> None:
    with proxy_for_uri(uri) as proxy:
        proxied = f"mongodb://127.0.0.1:{proxy.local_port}"
        listener = WireCommands(tuple(protocol.registration["collections"]))
        client_type = MongoClient if cell.model == "sync" else AsyncMongoClient
        client: Client = client_type(
            proxied,
            **protocol.registration["client_options"],
            event_listeners=[listener],
        )
        manager: Manager | None = None
        stream: Stream | None = None
        receiver: asyncio.Task[None] | None = None
        observed: list[float] = []  # Stream-only event timestamps.
        try:
            await invoke(client.admin.command, "ping")
            if cell.path == "native":
                cache_config = CacheCoreConfig(
                    lag_capture_window_config=LagCaptureWindowConfig(
                        protocol.registration["lag_capture"]["windows"],
                        protocol.registration["lag_capture"]["events"],
                        protocol.registration["lag_capture"]["separation"],
                    )
                )
                if isinstance(client, MongoClient):
                    manager = CacheManager(
                        client,
                        cache_config=cache_config,
                        max_await_time_ms=protocol.registration["max_await_time_ms"],
                    )
                else:
                    manager = AsyncCacheManager(
                        client,
                        cache_config=cache_config,
                        max_await_time_ms=protocol.registration["max_await_time_ms"],
                    )
            if cell.path == "stream-only":
                if isinstance(client, MongoClient):
                    stream = client[_DATABASE].watch(
                        build_change_stream_pipeline(),
                        show_expanded_events=True,
                        max_await_time_ms=protocol.registration["max_await_time_ms"],
                    )
                else:
                    stream = await client[_DATABASE].watch(
                        build_change_stream_pipeline(),
                        show_expanded_events=True,
                        max_await_time_ms=protocol.registration["max_await_time_ms"],
                    )
                receiver = asyncio.create_task(consume_stream(stream, observed))
            if cell.path in {"native", "native-control"}:
                database = (
                    manager[_DATABASE] if manager is not None else client[_DATABASE]
                )
                for index in range(protocol.documents):
                    await invoke(
                        database[
                            protocol.registration["collections"][
                                index % len(protocol.registration["collections"])
                            ]
                        ].find_one,
                        {"_id": index},
                    )
            expected_streams = int(cell.path in {"native", "stream-only"})
            if listener.streams != expected_streams:
                message = (
                    f"expected {expected_streams} stream, observed {listener.streams}"
                )
                raise BenchmarkSetupError(message)
            primed: Payload = (
                asdict(manager.snapshot())
                if manager is not None
                else {"entry_count": 0, "used_bytes": 0, "shared_budget_bytes": 0}
            )
            if manager is not None:
                if manager.stream_health_snapshot(_DATABASE).status.value != "healthy":
                    raise BenchmarkSetupError("native manager stream startup failed")
                if manager.snapshot().entry_count != protocol.documents:
                    raise BenchmarkSetupError("working set was not fully admitted")
                manager.cache_core.reset_stream_cost_statistics(_DATABASE)
            connection.send(
                {
                    "kind": "ready",
                    "pid": psutil.Process().pid,
                    "streams": listener.streams,
                    "primed": primed,
                }
            )
            start = cast("float", await asyncio.to_thread(connection.recv))
            await wait_until(start, protocol.schedule_tolerance_seconds, "start")
            boundary = process_reading()  # pytriage: TR11 (metric boundary)
            commands_before = listener.snapshot()
            sent, received = proxy.bytes_sent, proxy.bytes_received
            cache_before = manager.snapshot() if manager is not None else None
            latencies: list[float] = []
            offsets: list[float] = []
            if reads_for_path(cell.path, cell.workload):
                database = (
                    manager[_DATABASE] if manager is not None else client[_DATABASE]
                )
                for ordinal in partition_reads(protocol, cell.workers, worker):
                    await wait_until(
                        start + ordinal * protocol.read_interval_seconds,
                        protocol.schedule_tolerance_seconds,
                        "read",
                    )
                    issued = time.monotonic()
                    offsets.append(issued - start)
                    index = ordinal % protocol.documents
                    document = await invoke(
                        database[
                            protocol.registration["collections"][
                                index % len(protocol.registration["collections"])
                            ]
                        ].find_one,
                        {"_id": index},
                    )
                    if document is None:
                        raise BenchmarkSetupError("scheduled document disappeared")
                    latencies.append(time.monotonic() - issued)
            await wait_until(
                start + protocol.window_seconds,
                protocol.schedule_tolerance_seconds,
                "end",
            )
            application_end = process_reading()  # pytriage: TR11 (metric boundary)
            commands_at_end = listener.snapshot()
            connection.send({"kind": "application-end"})
            expected = (
                protocol.updates
                if cell.workload == "active" and expected_streams
                else 0
            )
            async with asyncio.timeout(protocol.drain_seconds):
                while True:
                    if receiver is not None and receiver.done():
                        receiver.result()
                        raise BenchmarkSetupError("stream receiver stopped")
                    count = (
                        manager.stream_cost_snapshot(_DATABASE).invalidations
                        if manager is not None
                        else len(observed)
                    )
                    if count >= expected:
                        break
                    await asyncio.sleep(0.005)
            drained = process_reading()  # pytriage: TR11 (metric boundary)
            cache_after = manager.snapshot() if manager is not None else None
            if manager is not None:
                telemetry = manager.stream_cost_snapshot(_DATABASE)
                windows = telemetry.invalidation_lag_windows
                count = telemetry.invalidations
                validate_capture(count, windows, expected)
                if expected == capture_ordinals()[-1][-1]:
                    captured_times = tuple(
                        reading.wall_seconds - lag
                        for reading, lag in zip(
                            telemetry.invalidation_apply_readings,
                            (lag for window in windows for lag in window),
                            strict=True,
                        )
                    )
                    event_times = listener.event_wall_seconds()
                    if len(event_times) != expected or any(
                        abs(captured - event_times[ordinal - 1]) > 0.000001
                        for captured, ordinal in zip(
                            captured_times,
                            (
                                ordinal
                                for window in capture_ordinals()
                                for ordinal in window
                            ),
                            strict=True,
                        )
                    ):
                        raise BenchmarkSetupError(
                            "lag capture separation does not match delivered events"
                        )
                healthy = (
                    manager.stream_health_snapshot(_DATABASE).status.value == "healthy"
                )
            else:
                windows = ()
                count = len(observed)
                healthy = stream is None or stream.alive
                if count != expected:
                    raise BenchmarkSetupError("incomplete stream-only delivery")
            if not healthy or listener.streams != expected_streams:
                raise BenchmarkSetupError("stream continuity changed during window")
            poll_gap = None
            if expected_streams and cell.workload == "idle":
                application_commands = command_delta(commands_before, commands_at_end)
                try:
                    polls = application_commands["getMore:completed"]
                except KeyError:
                    polls = 0
                if polls <= 0:
                    raise BenchmarkSetupError("idle stream issued no completed getMore")
                poll_gap = idle_poll_max_gap(
                    listener.poll_completion_seconds(),
                    start,
                    start + protocol.window_seconds,
                    protocol.registration["max_await_time_ms"] / 1000
                    + protocol.schedule_tolerance_seconds,
                )
            commands = command_delta(commands_before, listener.snapshot())
            if any(count for key, count in commands.items() if key.endswith(":failed")):
                raise BenchmarkSetupError("observed a failed wire command")
            connection.send(
                {
                    "kind": "sample",
                    "pid": psutil.Process().pid,
                    "streams": expected_streams,
                    "worker_cpu_seconds": cpu_delta(boundary, application_end),
                    "drain_cpu_seconds": cpu_delta(application_end, drained),
                    "uss_bytes": drained["uss_bytes"],
                    "primed": primed,
                    "wire_commands": commands,
                    "idle_poll_max_gap_seconds": poll_gap,
                    "bytes_sent": proxy.bytes_sent - sent,
                    "bytes_received": proxy.bytes_received - received,
                    "read_offsets_seconds": offsets,
                    "read_latency": scalar_latency_distribution(latencies)
                    if latencies
                    else None,
                    "read_outcomes": {
                        "hits": cache_after.hits - cache_before.hits,
                        "misses": cache_after.misses - cache_before.misses,
                        "bypasses": cache_after.bypasses - cache_before.bypasses,
                    }
                    if cache_after is not None and cache_before is not None
                    else {"raw": len(latencies)},
                    "invalidations": count,
                    "lag_windows": windows,
                    "capture_ordinals": capture_ordinals()
                    if count == capture_ordinals()[-1][-1] and manager is not None
                    else (),
                    "populated_bytes_after": cache_after.used_bytes
                    if cache_after is not None
                    else 0,
                }
            )
            await asyncio.to_thread(connection.recv)
        finally:
            if receiver is not None:
                receiver.cancel()
                try:
                    await receiver
                except asyncio.CancelledError:
                    pass
            if stream is not None:
                await invoke(stream.close)
            if manager is not None:
                await invoke(manager.close)
            await invoke(client.close)


def worker_main(
    connection: Connection, uri: str, cell: Cell, worker: int, protocol: Protocol
) -> None:
    try:
        asyncio.run(worker_window(connection, uri, cell, worker, protocol))
    except BenchmarkSetupError as error:
        connection.send({"kind": "failure", "error": str(error)})
        raise
    except PyMongoError as error:
        connection.send(
            {"kind": "failure", "error": f"MongoDB worker failure: {error}"}
        )
        raise
    except TimeoutError:
        connection.send({"kind": "failure", "error": "worker drain deadline exceeded"})
        raise
    finally:
        connection.close()


def receive(connection: Connection, deadline: float, kind: str) -> Payload:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not connection.poll(remaining):
        message_text = f"worker {kind} deadline exceeded"
        raise BenchmarkSetupError(message_text)
    try:
        message = cast("Payload", connection.recv())
    except EOFError as error:
        message_text = f"worker exited before {kind}"
        raise BenchmarkSetupError(message_text) from error
    if message["kind"] == "failure":
        raise BenchmarkSetupError(str(message["error"]))
    if message["kind"] != kind:
        message_text = f"unexpected worker message at {kind}"
        raise BenchmarkSetupError(message_text)
    return message


def reclaim_workers(
    processes: tuple[BaseProcess, ...], deadline: float, *, graceful: bool
) -> bool:
    started = time.monotonic()
    available = max(0.0, deadline - started)
    if graceful:
        grace_deadline = started + 0.8 * available
        for process in processes:
            process.join(max(0.0, grace_deadline - time.monotonic()))
    stalled = tuple(process for process in processes if process.is_alive())
    for process in stalled:
        process.terminate()
    terminate_deadline = started + 0.9 * available
    for process in stalled:
        process.join(max(0.0, terminate_deadline - time.monotonic()))
    for process in stalled:
        if process.is_alive():
            process.kill()
    for process in stalled:
        process.join(max(0.0, deadline - time.monotonic()))
    # SIGKILL reaping can race the shared cleanup deadline.
    if any(process.is_alive() for process in processes):  # pragma: lax no cover
        raise BenchmarkSetupError("children remain alive after cleanup deadline")
    return bool(stalled)


def stop_workers(processes: tuple[BaseProcess, ...], timeout: float) -> None:
    if reclaim_workers(processes, time.monotonic() + timeout, graceful=True):
        raise BenchmarkSetupError(
            "worker shutdown exceeded deadline; children terminated"
        )
    if any(process.exitcode != 0 for process in processes):
        raise BenchmarkSetupError("worker exited unsuccessfully")


def seed_documents(
    client: MongoClient[dict[str, object]], protocol: Protocol
) -> Payload:
    client.drop_database(_DATABASE)
    generator = random.Random(protocol.registration["seed"])
    padding = generator.randbytes(protocol.registration["payload_bytes"]).hex()[
        : protocol.registration["payload_bytes"]
    ]
    encoded_sizes: list[int] = []
    for name in protocol.registration["collections"]:
        documents = tuple(
            {"_id": index, "value": 0, "padding": padding}
            for index in range(protocol.documents)
            if protocol.registration["collections"][
                index % len(protocol.registration["collections"])
            ]
            == name
        )
        client[_DATABASE][name].insert_many(documents)
        encoded_sizes.extend(len(BSON.encode(document)) for document in documents)
    return {
        "documents": protocol.documents,
        "encoded_min_bytes": min(encoded_sizes),
        "encoded_max_bytes": max(encoded_sizes),
        "encoded_total_bytes": sum(encoded_sizes),
    }


def run_cell(replica: IsolatedReplicaSet, cell: Cell, protocol: Protocol) -> Payload:
    context = multiprocessing.get_context("spawn")
    processes: list[BaseProcess] = []
    connections: list[Connection] = []  # One private pipe per spawned child.
    shutdown_deadline: float | None = None
    with ExitStack() as resources:
        writer_proxy = resources.enter_context(proxy_for_uri(replica.uri))
        observer_proxy = resources.enter_context(proxy_for_uri(replica.uri))
        harness_listeners = tuple(
            WireCommands(tuple(protocol.registration["collections"])) for _ in range(2)
        )
        writer = resources.enter_context(
            MongoClient[dict[str, object]](
                f"mongodb://127.0.0.1:{writer_proxy.local_port}",
                **protocol.registration["client_options"],
                event_listeners=[harness_listeners[0]],
            )
        )
        observer = resources.enter_context(
            MongoClient[dict[str, object]](
                f"mongodb://127.0.0.1:{observer_proxy.local_port}",
                **protocol.registration["client_options"],
                event_listeners=[harness_listeners[1]],
            )
        )
        dataset = seed_documents(writer, protocol)
        sampler = PeriodicCalibrationSampler(
            lambda: observer.admin.command("hello"),
            cadence_seconds=protocol.registration["calibration_seconds"],
            rounds=3,
        )
        sampler.start()
        try:
            startup_deadline = time.monotonic() + protocol.startup_seconds
            for worker in range(cell.workers):
                parent, child = context.Pipe()
                process: BaseProcess = context.Process(
                    target=worker_main,
                    args=(child, replica.uri, cell, worker, protocol),
                )
                process.start()
                child.close()
                processes.append(process)
                connections.append(parent)
            ready = tuple(
                receive(connection, startup_deadline, "ready")
                for connection in connections
            )
            before = process_reading()  # pytriage: TR11 (metric boundary)
            server_before = replica.container_cpu_usage_seconds()
            paths_before = tuple(  # pytriage: TR11 (byte boundary)
                (proxy.bytes_sent, proxy.bytes_received)
                for proxy in (writer_proxy, observer_proxy)
            )
            harness_commands_before = tuple(  # pytriage: TR11 (command boundary)
                listener.snapshot() for listener in harness_listeners
            )
            start = time.monotonic()
            for connection in connections:
                connection.send(start)
            write_offsets: list[float] = []
            if cell.workload == "active":
                for ordinal in range(protocol.updates):
                    deadline = start + ordinal * protocol.update_interval_seconds
                    time.sleep(max(0.0, deadline - time.monotonic()))
                    issued = time.monotonic()
                    if issued - deadline > protocol.schedule_tolerance_seconds:
                        raise BenchmarkSetupError("write schedule exceeded tolerance")
                    write_offsets.append(issued - start)
                    index = ordinal % protocol.documents
                    try:
                        writer[_DATABASE][
                            protocol.registration["collections"][
                                index % len(protocol.registration["collections"])
                            ]
                        ].update_one({"_id": index}, {"$set": {"value": ordinal + 1}})
                    except PyMongoError as error:
                        raise BenchmarkSetupError(
                            "harness MongoDB operation failed"
                        ) from error
            time.sleep(max(0.0, start + protocol.window_seconds - time.monotonic()))
            application_end = process_reading()  # pytriage: TR11 (metric boundary)
            server_end = replica.container_cpu_usage_seconds()
            drain_deadline = time.monotonic() + protocol.drain_seconds
            for connection in connections:
                receive(connection, drain_deadline, "application-end")
            samples = tuple(  # pytriage: TR11 (drain boundary)
                receive(connection, drain_deadline, "sample")
                for connection in connections
            )
            drained = process_reading()  # pytriage: TR11 (metric boundary)
            server_drained = replica.container_cpu_usage_seconds()  # pytriage: TR11
            calibration = CalibrationSeries(sampler.stop())
            if (
                calibration.exceeds_drift_tolerance(
                    protocol.registration["clock_tolerance_seconds"]
                )
                or calibration.has_host_clock_step(
                    tolerance_seconds=protocol.registration["clock_tolerance_seconds"]
                )
                or calibration.has_election_change
            ):
                raise BenchmarkSetupError("clock or primary changed during window")
            shutdown_deadline = time.monotonic() + protocol.shutdown_seconds
            for connection in connections:
                connection.send("close")
            stop_workers(
                tuple(processes), max(0.0, shutdown_deadline - time.monotonic())
            )
            return {
                **asdict(cell),
                "database": _DATABASE,
                "collections": protocol.registration["collections"],
                "manager_count": cell.workers if cell.path == "native" else 0,
                "healthy": True,
                "dataset": dataset,
                "application_seconds": protocol.window_seconds,
                "server_cpu_seconds": server_end - server_before,
                "server_drain_cpu_seconds": server_drained - server_end,
                "harness_cpu_seconds": cpu_delta(before, application_end),
                "harness_drain_cpu_seconds": cpu_delta(application_end, drained),
                "harness_pid": before["pid"],
                "harness_uss_bytes": drained["uss_bytes"],
                "harness_includes": (
                    "writer",
                    "clock-observer",
                    "writer-proxy",
                    "observer-proxy",
                    "orchestration",
                ),
                "workers_measured": samples,
                "summed_cache_budget_bytes": sum(
                    cast(
                        "int", cast("Payload", sample["primed"])["shared_budget_bytes"]
                    )
                    for sample in samples
                ),
                "summed_primed_cache_bytes": sum(
                    cast("int", cast("Payload", sample["primed"])["used_bytes"])
                    for sample in samples
                ),
                "summed_worker_uss_bytes": sum(
                    cast("int", sample["uss_bytes"]) for sample in samples
                ),
                "ready": ready,
                "actual_streams": sum(
                    cast("int", sample["streams"]) for sample in samples
                ),
                "write_offsets_seconds": write_offsets,
                "clock_offset_seconds": calibration.initial.offset_seconds,
                "clock_uncertainty_seconds": calibration.total_uncertainty_seconds,
                "clock_samples": len(calibration.points),
                "harness_paths": {
                    name: {
                        "sent": proxy.bytes_sent - sent,
                        "received": proxy.bytes_received - received,
                        "wire_commands": command_delta(
                            commands_before, listener.snapshot()
                        ),
                    }
                    for name, proxy, (sent, received), commands_before, listener in zip(
                        ("writer", "observer"),
                        (writer_proxy, observer_proxy),
                        paths_before,
                        harness_commands_before,
                        harness_listeners,
                        strict=True,
                    )
                },
            }
        finally:
            try:
                sampler.stop()
            finally:
                for connection in connections:
                    connection.close()
                if shutdown_deadline is None:
                    shutdown_deadline = time.monotonic() + protocol.shutdown_seconds
                reclaim_workers(tuple(processes), shutdown_deadline, graceful=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure stream duplication on a disposable replica set."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run shortened instrumentation cells; excluded from baseline inference.",
    )
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve evidence")
    git_path = shutil.which("git")
    if git_path is None:
        raise BenchmarkSetupError("git is required to record the benchmark revision")
    configuration_bytes = _CONFIG.read_bytes()
    configuration = json.loads(configuration_bytes)
    protocol = Protocol.smoke() if arguments.smoke else Protocol.load()
    cells = (
        tuple(
            Cell(0, model, 1, "active", path)
            for model in ("sync", "async")
            for path in ("native-control", "native", "stream-control", "stream-only")
        )
        if arguments.smoke
        else planned_cells()
    )
    report: Payload = {
        "phase": "smoke" if arguments.smoke else "baseline",
        "configuration_sha256": sha256(configuration_bytes).hexdigest(),
        "revision": subprocess.check_output(  # noqa: S603 - fixed git arguments
            [git_path, "rev-parse", "HEAD"], text=True
        ).strip(),
        "protocol": asdict(protocol),
        "cells": [],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with IsolatedReplicaSet(ResourceLimits(**configuration["topology"])) as replica:
        for ordinal, cell in enumerate(cells, 1):
            print(
                f"{ordinal}/{len(cells)} {cell.model} {cell.workers} "
                f"{cell.workload} {cell.path}",
                flush=True,
            )
            try:
                sample = run_cell(replica, cell, protocol)
            except BenchmarkSetupError as error:
                sample = {**asdict(cell), "healthy": False, "failure": str(error)}
            cast("list[Payload]", report["cells"]).append(sample)
            arguments.output.write_text(json.dumps(report, indent=2) + "\n")
            if not sample["healthy"]:
                raise BenchmarkSetupError(str(sample["failure"]))


if __name__ == "__main__":
    main()

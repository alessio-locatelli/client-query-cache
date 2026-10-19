from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from pymongo import AsyncMongoClient, MongoClient, ReadPreference
from pymongo.read_concern import ReadConcern

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import WireCommands, command_delta
from benchmarks.stream_cost.shared_cache.dataset import checksum
from benchmarks.stream_cost.shared_cache.fault_injection import (
    independent_async_supervisor,
    independent_sync_supervisor,
    lose_async_stream_history,
    lose_sync_stream_history,
)
from benchmarks.stream_cost.shared_cache.fault_worker import (
    async_fault_worker,
    sync_fault_worker,
)
from benchmarks.stream_cost.shared_cache.owner import (
    FaultableProxy,
    process_sample,
    proxy_for,
)
from benchmarks.stream_cost.shared_cache.profiling import profiling
from benchmarks.stream_cost.shared_cache.workload import (
    LoopResult,
    assignment_for,
    closed_loop_async,
    closed_loop_sync,
    open_loop_async,
    open_loop_sync,
)
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
from client_query_cache._shared.adapters import (
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AsyncLocalIndex,
    AttachmentConfig,
    LocalIndex,
    SyncEndpoint,
)
from client_query_cache._types import (
    BsonDict,
    MaxAwaitTimeMs,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.protocol import Cell, KeyAssignment
    from benchmarks.stream_cost.shared_cache.workload import Assignment

type Payload = dict[str, object]

_MAJORITY = ReadConcern("majority")
_STARTUP_POLL_SECONDS = 0.05
_FAULT_SAMPLE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    cell: Cell
    index: NonNegativeInt
    model: Literal["sync", "async"]
    uri: str
    database: str
    collection: str
    client_options: dict[str, object]
    read: Literal["find_one", "find"]
    limit: PositiveInt
    keys: tuple[NonNegativeInt, ...]
    key_assignment: KeyAssignment
    warm_key: NonNegativeInt | None
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    max_await_time_ms: MaxAwaitTimeMs
    lag_capture: tuple[PositiveInt, PositiveInt, NonNegativeInt]
    attachment: AttachmentConfig | None
    outstanding: PositiveInt
    drain_seconds: PositiveFloat
    expected_invalidations: NonNegativeInt
    timeline_generation: NonNegativeInt = 0
    controls_enabled: bool = False
    timeline_enabled: bool = False
    timeline_cadence_seconds: PositiveFloat = _FAULT_SAMPLE_SECONDS
    scheduled_ordinals: tuple[NonNegativeInt, ...] | None = None
    topology: Literal["single-member", "three-member"] = "single-member"

    def assignment(self, *, warmup: bool) -> Assignment:
        return assignment_for(
            self.cell,
            self.index,
            self.keys,
            self.key_assignment,
            warmup=warmup,
            scheduled_ordinals=self.scheduled_ordinals if not warmup else None,
        )


def _cache_config(spec: WorkerSpec) -> CacheCoreConfig:
    return CacheCoreConfig(
        shared_budget_bytes=spec.budget_bytes,
        max_entry_bytes=spec.max_entry_bytes,
        lag_capture_window_config=LagCaptureWindowConfig(*spec.lag_capture),
    )


def _query(spec: WorkerSpec, key: NonNegativeInt) -> tuple[BsonDict, dict[str, object]]:
    if spec.read == "find_one":
        return {"_id": key}, {}
    return {"attributes.category": key}, {"sort": [("_id", 1)], "limit": spec.limit}


def _probe_revision(request: Payload, key: NonNegativeInt) -> NonNegativeInt:
    try:
        revisions = cast("dict[NonNegativeInt, NonNegativeInt]", request["revisions"])
    except KeyError:
        return cast("NonNegativeInt", request["revision"])
    return revisions[key]


def _verify(spec: WorkerSpec, outcome: object) -> None:
    if spec.read == "find_one":
        checksum(cast("BsonDict | None", outcome))
        return
    documents = cast("list[BsonDict]", outcome)
    if len(documents) != spec.limit:
        message = "sorted find returned an incomplete result"
        raise LookupError(message)
    for document in documents:
        checksum(document)


@dataclass(slots=True)
class _Outcomes:
    hits: NonNegativeInt = 0
    misses: NonNegativeInt = 0
    bypasses: NonNegativeInt = 0
    reasons: Counter[str] = field(default_factory=Counter)


def _outcomes(manager: object) -> _Outcomes:
    if isinstance(manager, (SharedCacheManager, AsyncSharedCacheManager)):
        observation = manager.observation
        return _Outcomes(
            observation.hits,
            observation.misses,
            sum(observation.bypasses.values()),
            Counter(observation.bypasses),
        )
    if isinstance(manager, (CacheManager, AsyncCacheManager)):
        snapshot = manager.snapshot()
        return _Outcomes(
            snapshot.hits,
            snapshot.misses,
            snapshot.bypasses,
            Counter(
                {
                    **{
                        item.reason.value: item.count
                        for item in snapshot.bypass_reasons
                    },
                    "oversized": snapshot.oversized_bypasses,
                }
            ),
        )
    return _Outcomes()


def _entries(manager: object) -> NonNegativeInt | None:
    if isinstance(manager, (CacheManager, AsyncCacheManager)):
        return manager.snapshot().entry_count
    return None


def _endpoint_counters(manager: object) -> Payload | None:
    if isinstance(manager, (SharedCacheManager, AsyncSharedCacheManager)):
        return asdict(manager.endpoint.counters)
    return None


def _delta(after: Payload | None, before: Payload | None) -> Payload | None:
    if after is None or before is None:
        return None
    return {
        key: cast("int", value) - cast("int", before[key])
        for key, value in after.items()
    }


def _lag(manager: object, spec: WorkerSpec) -> Payload | None:
    if not isinstance(manager, (CacheManager, AsyncCacheManager)):
        return None
    telemetry = manager.stream_cost_snapshot(spec.database)
    return {
        "invalidations": telemetry.invalidations,
        "lag_windows": telemetry.invalidation_lag_windows,
        "health": manager.stream_health_snapshot(spec.database).status.value,
    }


def _timeline_snapshot(
    spec: WorkerSpec,
    manager: object,
    listener: WireCommands,
    start: NonNegativeFloat,
) -> Payload:
    if isinstance(manager, (CacheManager, AsyncCacheManager)):
        snapshot = manager.snapshot()
        telemetry = manager.stream_cost_snapshot(spec.database)
        outcomes = {
            "hits": snapshot.hits,
            "misses": snapshot.misses,
            "bypasses": snapshot.bypasses,
            "bypass_reasons": {
                **{item.reason.value: item.count for item in snapshot.bypass_reasons},
                "oversized": snapshot.oversized_bypasses,
            },
            "entries": snapshot.entry_count,
            "health": manager.stream_health_snapshot(spec.database).status.value,
            "invalidations": telemetry.invalidations,
        }
    else:
        outcomes = {
            "hits": 0,
            "misses": 0,
            "bypasses": 0,
            "bypass_reasons": {},
            "entries": None,
            "health": None,
            "invalidations": 0,
        }
    return {
        "offset": time.monotonic() - start,
        "generation": spec.timeline_generation,
        **outcomes,
        "streams": listener.streams,
        "stream_openings": listener.stream_openings(),
        "command_failures": listener.failures(),
        "stream_operation_times": listener.stream_operation_times(),
        "cpu_seconds": process_sample()["cpu_seconds"],
    }


class _TimelineEmitter:
    __slots__ = (
        "_connection",
        "_events",
        "_listener",
        "_lock",
        "_manager",
        "_spec",
        "_start",
        "_stop",
        "_thread",
    )

    def __init__(
        self,
        connection: Connection,
        spec: WorkerSpec,
        manager: object,
        listener: WireCommands,
        start: NonNegativeFloat,
    ) -> None:
        self._connection = connection
        self._events: list[Payload] = []
        self._listener = listener
        self._lock = threading.Lock()
        self._manager = manager
        self._spec = spec
        self._start = start
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def record(self, event: Payload) -> None:
        with self._lock:
            self._events.append(event)

    def start(self) -> None:
        self._thread.start()

    def _send(self, *, final: bool = False) -> None:
        with self._lock:
            events, self._events = self._events, []
        self._connection.send(
            {
                "kind": "timeline_chunk",
                "index": self._spec.index,
                "events": events,
                "snapshot": _timeline_snapshot(
                    self._spec, self._manager, self._listener, self._start
                ),
                "final": final,
            }
        )

    def _run(self) -> None:
        while not self._stop.wait(self._spec.timeline_cadence_seconds):
            self._send()

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self._send(final=True)


def _worker_client_uri(spec: WorkerSpec, proxy: FaultableProxy | None) -> str:
    if proxy is None:
        return spec.uri
    return f"mongodb://127.0.0.1:{proxy.local_port}"


def _worker_client_options(spec: WorkerSpec) -> dict[str, object]:
    if spec.topology != "three-member":
        return spec.client_options
    options = {
        key: value
        for key, value in spec.client_options.items()
        if key != "directConnection"
    }
    options["directConnection"] = False
    return options


class _Measured:
    __slots__ = ("commands", "cpu", "endpoint", "outcomes", "wire")

    def __init__(
        self,
        manager: object,
        listener: WireCommands,
        proxy: FaultableProxy | None,
    ) -> None:
        self.cpu = cast("float", process_sample()["cpu_seconds"])
        self.commands = listener.snapshot()
        self.endpoint = _endpoint_counters(manager)
        self.outcomes = _outcomes(manager)
        self.wire = (
            (proxy.bytes_sent, proxy.bytes_received)
            if proxy is not None
            else (None, None)
        )


def _sample(
    spec: WorkerSpec,
    manager: object,
    listener: WireCommands,
    proxy: FaultableProxy | None,
    *,
    before: _Measured,
    application_end: _Measured,
    loop: LoopResult,
) -> Payload:
    drained = _Measured(manager, listener, proxy)
    outcomes = drained.outcomes
    commands = command_delta(before.commands, drained.commands)
    return {
        "kind": "sample",
        "index": spec.index,
        "model": spec.model,
        **{
            key: value
            for key, value in process_sample().items()
            if key != "cpu_seconds"
        },
        "cpu_seconds": application_end.cpu - before.cpu,
        "drain_cpu_seconds": drained.cpu - application_end.cpu,
        "wire_sent": (
            drained.wire[0] - before.wire[0]
            if drained.wire[0] is not None and before.wire[0] is not None
            else None
        ),
        "wire_received": (
            drained.wire[1] - before.wire[1]
            if drained.wire[1] is not None and before.wire[1] is not None
            else None
        ),
        "commands": commands,
        "streams": listener.streams,
        "outcomes": {
            "hits": outcomes.hits - before.outcomes.hits,
            "misses": outcomes.misses - before.outcomes.misses,
            "bypasses": outcomes.bypasses - before.outcomes.bypasses,
            "bypass_reasons": dict(outcomes.reasons - before.outcomes.reasons),
        },
        "endpoint": _delta(drained.endpoint, before.endpoint),
        "entries": _entries(manager),
        "lag": _lag(manager, spec),
        "loop": loop.summary(),
        "latencies": loop.latencies,
    }


def _ready(
    spec: WorkerSpec,
    manager: object,
    listener: WireCommands,
    *,
    baseline: Payload,
    primed_at: NonNegativeFloat,
    started: NonNegativeFloat,
) -> Payload:
    primed = process_sample()
    return {
        "kind": "ready",
        "index": spec.index,
        "pid": primed["pid"],
        "baseline_pss_bytes": baseline["pss_bytes"],
        "primed_pss_bytes": primed["pss_bytes"],
        "priming_seconds": primed_at - started,
        "priming_cpu_seconds": cast("float", primed["cpu_seconds"])
        - cast("float", baseline["cpu_seconds"]),
        "priming_misses": _outcomes(manager).misses,
        "streams": listener.streams,
        "entries": _entries(manager),
    }


def _drain_deadline(spec: WorkerSpec) -> NonNegativeFloat:
    return time.monotonic() + spec.drain_seconds


def _invalidations(manager: object, spec: WorkerSpec) -> NonNegativeInt:
    lag = _lag(manager, spec)
    return (
        cast("int", lag["invalidations"])
        if lag is not None
        else spec.expected_invalidations
    )


@dataclass(slots=True)
class _ControlContext:
    spec: WorkerSpec
    manager: object
    proxy: FaultableProxy | None
    listener: WireCommands


def _control_state(operation: str, context: _ControlContext) -> Payload:
    spec = context.spec
    manager = context.manager
    listener = context.listener
    if isinstance(manager, (CacheManager, AsyncCacheManager)):
        health = manager.stream_health_snapshot(spec.database).status.value
        invalidations = manager.stream_cost_snapshot(spec.database).invalidations
    else:
        health = None
        invalidations = 0
    return {
        "kind": "control",
        "operation": operation,
        "streams": listener.streams,
        "entries": _entries(manager),
        "health": health,
        "invalidations": invalidations,
        "command_failures": listener.failures(),
        "stream_operation_times": listener.stream_operation_times(),
    }


def _apply_sync_control(
    operation: str,
    request: Payload,
    context: _ControlContext,
    probe: Callable[[Payload], Payload],
) -> Payload:
    spec = context.spec
    manager = context.manager
    proxy = context.proxy
    action_monotonic: NonNegativeFloat | None = None
    if operation == "sever":
        if proxy is None:
            raise BenchmarkSetupError(
                "proxy severing requires a single-member topology"
            )
        action_monotonic = time.monotonic()
        proxy.sever()
    elif operation == "lose-history":
        if not isinstance(manager, CacheManager):
            raise BenchmarkSetupError(
                "history loss requires an independent cached worker"
            )
        action_monotonic = time.monotonic()
        lose_sync_stream_history(independent_sync_supervisor(manager, spec.database))
    elif operation == "probe":
        return {"kind": "control", "operation": operation, **probe(request)}
    elif operation != "snapshot":
        message = f"unknown worker control operation: {operation}"
        raise BenchmarkSetupError(message)
    response = _control_state(operation, context)
    if action_monotonic is not None:
        response["action_monotonic"] = action_monotonic
    return response


def _serve_sync_controls(
    control: Connection,
    context: _ControlContext,
    probe: Callable[[Payload], Payload],
) -> None:
    try:
        while True:
            request = cast("Payload", control.recv())
            operation = cast("str", request["op"])
            if operation == "close":
                return
            control.send(_apply_sync_control(operation, request, context, probe))
    except EOFError:
        return


async def _serve_async_controls(
    control: Connection,
    context: _ControlContext,
    probe: Callable[[Payload], Awaitable[Payload]],
) -> None:
    spec = context.spec
    manager = context.manager
    proxy = context.proxy
    while True:
        try:
            request = cast("Payload", await asyncio.to_thread(control.recv))
        except EOFError:
            return
        operation = cast("str", request["op"])
        if operation == "close":
            return
        action_monotonic: NonNegativeFloat | None = None
        if operation == "sever":
            if proxy is None:
                raise BenchmarkSetupError(
                    "proxy severing requires a single-member topology"
                )
            action_monotonic = time.monotonic()
            proxy.sever()
        elif operation == "lose-history":
            if not isinstance(manager, AsyncCacheManager):
                raise BenchmarkSetupError(
                    "history loss requires an independent cached worker"
                )
            action_monotonic = time.monotonic()
            await lose_async_stream_history(
                independent_async_supervisor(manager, spec.database)
            )
        elif operation == "probe":
            response = await probe(request)
            await asyncio.to_thread(
                control.send,
                {"kind": "control", "operation": operation, **response},
            )
            continue
        elif operation != "snapshot":
            message = f"unknown worker control operation: {operation}"
            raise BenchmarkSetupError(message)
        response = _control_state(operation, context)
        if action_monotonic is not None:
            response["action_monotonic"] = action_monotonic
        await asyncio.to_thread(control.send, response)


def _shared_sync(
    spec: WorkerSpec, client: MongoClient[BsonDict]
) -> SharedCacheManager[BsonDict]:
    attachment = spec.attachment
    assert attachment is not None
    return SharedCacheManager(
        client,
        SyncEndpoint(attachment),
        LocalIndex.attach(attachment) if spec.cell.path == "shared-index" else None,
    )


async def _shared_async(
    spec: WorkerSpec, client: AsyncMongoClient[BsonDict]
) -> AsyncSharedCacheManager[BsonDict]:
    attachment = spec.attachment
    assert attachment is not None
    return AsyncSharedCacheManager(
        client,
        await AsyncEndpoint.attach(attachment),
        await AsyncLocalIndex.attach(attachment)
        if spec.cell.path == "shared-index"
        else None,
    )


def sync_worker(
    connection: Connection,
    spec: WorkerSpec,
    control_connection: Connection | None = None,
    timeline_connection: Connection | None = None,
) -> None:
    proxy_context = (
        nullcontext(None) if spec.topology == "three-member" else proxy_for(spec.uri)
    )
    with proxy_context as proxy:
        listener = WireCommands((spec.collection,))
        client: MongoClient[BsonDict] = MongoClient(
            _worker_client_uri(spec, proxy),
            event_listeners=[listener],
            **_worker_client_options(spec),  # type: ignore[arg-type]
        )
        manager: CacheManager[BsonDict] | SharedCacheManager[BsonDict] | None = None
        control_thread: threading.Thread | None = None
        try:
            client.admin.command("ping")
            if spec.cell.phase == "fault" and spec.cell.path not in {
                "direct",
                "independent",
            }:
                manager = _shared_sync(spec, client)
                sync_fault_worker(connection, spec, manager)
                return
            baseline = process_sample()
            started = time.monotonic()
            match spec.cell.path:
                case "direct":
                    collection = client[spec.database][spec.collection].with_options(
                        read_preference=ReadPreference.PRIMARY, read_concern=_MAJORITY
                    )
                case "independent":
                    manager = CacheManager(
                        client,
                        cache_config=_cache_config(spec),
                        max_await_time_ms=spec.max_await_time_ms,
                    )
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]
                case _:
                    manager = _shared_sync(spec, client)
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]

            def read(key: NonNegativeInt) -> None:
                query, options = _query(spec, key)
                if spec.read == "find_one":
                    _verify(spec, collection.find_one(query))
                else:
                    _verify(spec, collection.find(query, **options).to_list())

            def probe(request: Payload) -> Payload:
                keys = cast("list[NonNegativeInt]", request["keys"])
                for key in keys:
                    document = collection.find_one({"_id": key})
                    expected = _probe_revision(request, key)
                    if document is None or document["revision"] != expected:
                        return {"probe_ok": False, "stale_key": key}
                    _verify(spec, document)
                return {"probe_ok": True, "probed": len(keys)}

            if isinstance(manager, SharedCacheManager):
                shared = manager[spec.database][spec.collection]
                while shared._cache_ineligibility_reason() is not None:
                    time.sleep(_STARTUP_POLL_SECONDS)
            if spec.warm_key is not None:
                read(spec.warm_key)
            else:
                for key in spec.keys:
                    read(key)
            if isinstance(manager, CacheManager):
                manager.cache_core.reset_stream_cost_statistics(spec.database)
            if spec.controls_enabled:
                assert control_connection is not None
                control_thread = threading.Thread(
                    target=_serve_sync_controls,
                    args=(
                        control_connection,
                        _ControlContext(spec, manager, proxy, listener),
                        probe,
                    ),
                    daemon=True,
                )
                control_thread.start()
            connection.send(
                _ready(
                    spec,
                    manager,
                    listener,
                    baseline=baseline,
                    primed_at=time.monotonic(),
                    started=started,
                )
            )
            start = cast("float", connection.recv())
            window_start = start + spec.cell.warmup_seconds
            if spec.cell.warmup_seconds:
                _run_sync(spec, start, read, warmup=True)
            before = _Measured(manager, listener, proxy)
            timeline = None
            if spec.timeline_enabled:
                assert timeline_connection is not None
                emitter = _TimelineEmitter(
                    timeline_connection, spec, manager, listener, window_start
                )
                emitter.start()
                timeline = emitter.record
            else:
                emitter = None
            try:
                loop = _run_sync(
                    spec, window_start, read, warmup=False, timeline=timeline
                )
            finally:
                if emitter is not None:
                    emitter.close()
            application_end = _Measured(manager, listener, proxy)
            deadline = _drain_deadline(spec)
            while _invalidations(manager, spec) < spec.expected_invalidations:
                if time.monotonic() > deadline:
                    raise BenchmarkSetupError("worker invalidation drain incomplete")
                time.sleep(0.005)
            connection.send(
                _sample(
                    spec,
                    manager,
                    listener,
                    proxy,
                    before=before,
                    application_end=application_end,
                    loop=loop,
                )
            )
            connection.recv()
        finally:
            if control_thread is not None:
                assert control_connection is not None
                try:
                    control_connection.send({"op": "close"})
                except BrokenPipeError:
                    pass
                control_thread.join()
            if manager is not None:
                manager.close()
            client.close()


def _run_sync(
    spec: WorkerSpec,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], object],
    *,
    warmup: bool,
    timeline: Callable[[Payload], None] | None = None,
) -> LoopResult:
    cell = spec.cell
    assignment = spec.assignment(warmup=warmup)
    seconds = cell.warmup_seconds if warmup else cell.window_seconds
    if cell.loop == "closed":
        return closed_loop_sync(assignment, start, seconds, read, cell.concurrency)
    return open_loop_sync(
        assignment,
        start,
        read,
        concurrency=cell.concurrency,
        outstanding_limit=spec.outstanding,
        drain_seconds=spec.drain_seconds,
        record=not warmup,
        timeline=None if warmup else timeline,
    )


async def _run_async(
    spec: WorkerSpec,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], Awaitable[object]],
    *,
    warmup: bool,
    timeline: Callable[[Payload], None] | None = None,
) -> LoopResult:
    cell = spec.cell
    assignment = spec.assignment(warmup=warmup)
    seconds = cell.warmup_seconds if warmup else cell.window_seconds
    if cell.loop == "closed":
        return await closed_loop_async(
            assignment, start, seconds, read, cell.concurrency
        )
    return await open_loop_async(
        assignment,
        start,
        read,
        concurrency=cell.concurrency,
        outstanding_limit=spec.outstanding,
        drain_seconds=spec.drain_seconds,
        record=not warmup,
        timeline=None if warmup else timeline,
    )


async def async_worker(
    connection: Connection,
    spec: WorkerSpec,
    control_connection: Connection | None = None,
    timeline_connection: Connection | None = None,
) -> None:
    proxy_context = (
        nullcontext(None) if spec.topology == "three-member" else proxy_for(spec.uri)
    )
    with proxy_context as proxy:
        listener = WireCommands((spec.collection,))
        client: AsyncMongoClient[BsonDict] = AsyncMongoClient(
            _worker_client_uri(spec, proxy),
            event_listeners=[listener],
            **_worker_client_options(spec),  # type: ignore[arg-type]
        )
        manager: (
            AsyncCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict] | None
        ) = None
        control_task: asyncio.Task[None] | None = None
        try:
            await client.admin.command("ping")
            if spec.cell.phase == "fault" and spec.cell.path not in {
                "direct",
                "independent",
            }:
                manager = await _shared_async(spec, client)
                await async_fault_worker(connection, spec, manager)
                return
            baseline = process_sample()
            started = time.monotonic()
            match spec.cell.path:
                case "direct":
                    collection = client[spec.database][spec.collection].with_options(
                        read_preference=ReadPreference.PRIMARY, read_concern=_MAJORITY
                    )
                case "independent":
                    manager = AsyncCacheManager(
                        client,
                        cache_config=_cache_config(spec),
                        max_await_time_ms=spec.max_await_time_ms,
                    )
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]
                case _:
                    manager = await _shared_async(spec, client)
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]

            async def read(key: NonNegativeInt) -> None:
                query, options = _query(spec, key)
                if spec.read == "find_one":
                    _verify(spec, await collection.find_one(query))
                else:
                    _verify(spec, await collection.find(query, **options).to_list())

            async def probe(request: Payload) -> Payload:
                keys = cast("list[NonNegativeInt]", request["keys"])
                for key in keys:
                    document = await collection.find_one({"_id": key})
                    expected = _probe_revision(request, key)
                    if document is None or document["revision"] != expected:
                        return {"probe_ok": False, "stale_key": key}
                    _verify(spec, document)
                return {"probe_ok": True, "probed": len(keys)}

            if isinstance(manager, AsyncSharedCacheManager):
                shared = manager[spec.database][spec.collection]
                while await shared._cache_ineligibility_reason() is not None:  # noqa: ASYNC110 - The owner offers no readiness notification.
                    await asyncio.sleep(_STARTUP_POLL_SECONDS)
            if spec.warm_key is not None:
                await read(spec.warm_key)
            else:
                for key in spec.keys:
                    await read(key)
            if isinstance(manager, AsyncCacheManager):
                manager.cache_core.reset_stream_cost_statistics(spec.database)
            if spec.controls_enabled:
                assert control_connection is not None
                control_task = asyncio.create_task(
                    _serve_async_controls(
                        control_connection,
                        _ControlContext(spec, manager, proxy, listener),
                        probe,
                    )
                )
            connection.send(
                _ready(
                    spec,
                    manager,
                    listener,
                    baseline=baseline,
                    primed_at=time.monotonic(),
                    started=started,
                )
            )
            start = cast("float", await asyncio.to_thread(connection.recv))
            window_start = start + spec.cell.warmup_seconds
            if spec.cell.warmup_seconds:
                await _run_async(spec, start, read, warmup=True)
            before = _Measured(manager, listener, proxy)
            timeline = None
            if spec.timeline_enabled:
                assert timeline_connection is not None
                emitter = _TimelineEmitter(
                    timeline_connection, spec, manager, listener, window_start
                )
                emitter.start()
                timeline = emitter.record
            else:
                emitter = None
            try:
                with profiling(f"worker-{spec.cell.path}"):
                    loop = await _run_async(
                        spec,
                        window_start,
                        read,
                        warmup=False,
                        timeline=timeline,
                    )
            finally:
                if emitter is not None:
                    emitter.close()
            application_end = _Measured(manager, listener, proxy)
            deadline = _drain_deadline(spec)
            while _invalidations(manager, spec) < spec.expected_invalidations:
                if time.monotonic() > deadline:
                    raise BenchmarkSetupError("worker invalidation drain incomplete")
                await asyncio.sleep(0.005)
            connection.send(
                _sample(
                    spec,
                    manager,
                    listener,
                    proxy,
                    before=before,
                    application_end=application_end,
                    loop=loop,
                )
            )
            await asyncio.to_thread(connection.recv)
        finally:
            if control_task is not None:
                assert control_connection is not None
                try:
                    control_connection.send({"op": "close"})
                except BrokenPipeError:
                    pass
                await control_task
            if manager is not None:
                await manager.close()
            await client.close()


def worker_main(
    connection: Connection,
    spec: WorkerSpec,
    control_connection: Connection | None = None,
    timeline_connection: Connection | None = None,
) -> None:
    try:
        if spec.model == "sync":
            sync_worker(connection, spec, control_connection, timeline_connection)
        else:
            asyncio.run(
                async_worker(connection, spec, control_connection, timeline_connection)
            )
    except BenchmarkSetupError as error:
        connection.send({"kind": "failure", "error": str(error)})
        raise
    except LookupError as error:
        connection.send({"kind": "failure", "error": str(error)})
        raise
    finally:
        if control_connection is not None:
            control_connection.close()
        if timeline_connection is not None:
            timeline_connection.close()
        connection.close()

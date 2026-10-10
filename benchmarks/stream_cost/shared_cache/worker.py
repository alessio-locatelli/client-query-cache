from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, cast

from pymongo import AsyncMongoClient, MongoClient, ReadPreference
from pymongo.read_concern import ReadConcern

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import WireCommands, command_delta
from benchmarks.stream_cost.shared_cache.adapters import (
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from benchmarks.stream_cost.shared_cache.attachment import (
    AsyncEndpoint,
    AttachmentConfig,
    SyncEndpoint,
)
from benchmarks.stream_cost.shared_cache.dataset import checksum
from benchmarks.stream_cost.shared_cache.owner import process_sample, proxy_for
from benchmarks.stream_cost.shared_cache.profiling import profiling
from benchmarks.stream_cost.shared_cache.workload import (
    Assignment,
    LoopResult,
    closed_loop_async,
    closed_loop_sync,
    open_loop_async,
    open_loop_sync,
)
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
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

    from benchmarks.stream_cost.shared_cache.protocol import Cell

type Payload = dict[str, object]

_MAJORITY = ReadConcern("majority")
_STARTUP_POLL_SECONDS = 0.05


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
    warm_key: NonNegativeInt
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    max_await_time_ms: MaxAwaitTimeMs
    lag_capture: tuple[PositiveInt, PositiveInt, NonNegativeInt]
    attachment: AttachmentConfig | None
    outstanding: PositiveInt
    drain_seconds: PositiveFloat
    expected_invalidations: NonNegativeInt

    def assignment(self, *, warmup: bool) -> Assignment:
        cell = self.cell
        seconds = cell.warmup_seconds if warmup else cell.window_seconds
        requests = (
            cell.identities
            if cell.identities is not None
            else round(cell.rate * seconds)
            if cell.rate is not None
            else int(seconds * 1_000_000)
        )
        return Assignment(
            worker=self.index,
            workers=cell.workers,
            rate=cell.rate,
            requests=requests,
            keys=self.keys,
            offset=len(self.keys) // 2 if warmup else 0,
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


def _outcomes(manager: object) -> _Outcomes:
    if isinstance(manager, (SharedCacheManager, AsyncSharedCacheManager)):
        observation = manager.observation
        return _Outcomes(
            observation.hits, observation.misses, sum(observation.bypasses.values())
        )
    if isinstance(manager, (CacheManager, AsyncCacheManager)):
        snapshot = manager.snapshot()
        return _Outcomes(snapshot.hits, snapshot.misses, snapshot.bypasses)
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


class _Measured:
    __slots__ = ("commands", "cpu", "endpoint", "outcomes", "wire")

    def __init__(self, manager: object, listener: WireCommands, proxy: object) -> None:
        self.cpu = cast("float", process_sample()["cpu_seconds"])
        self.commands = listener.snapshot()
        self.endpoint = _endpoint_counters(manager)
        self.outcomes = _outcomes(manager)
        self.wire = (proxy.bytes_sent, proxy.bytes_received)  # type: ignore[attr-defined]


def _sample(
    spec: WorkerSpec,
    manager: object,
    listener: WireCommands,
    proxy: object,
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
        "wire_sent": drained.wire[0] - before.wire[0],
        "wire_received": drained.wire[1] - before.wire[1],
        "commands": commands,
        "streams": listener.streams,
        "outcomes": {
            "hits": outcomes.hits - before.outcomes.hits,
            "misses": outcomes.misses - before.outcomes.misses,
            "bypasses": outcomes.bypasses - before.outcomes.bypasses,
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


def sync_worker(connection: Connection, spec: WorkerSpec) -> None:
    with proxy_for(spec.uri) as proxy:
        listener = WireCommands((spec.collection,))
        client: MongoClient[BsonDict] = MongoClient(
            f"mongodb://127.0.0.1:{proxy.local_port}",
            event_listeners=[listener],
            **spec.client_options,  # type: ignore[arg-type]
        )
        manager: CacheManager[BsonDict] | SharedCacheManager[BsonDict] | None = None
        try:
            client.admin.command("ping")
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
                    assert spec.attachment is not None
                    manager = SharedCacheManager(client, SyncEndpoint(spec.attachment))
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]

            def read(key: NonNegativeInt) -> None:
                query, options = _query(spec, key)
                if spec.read == "find_one":
                    _verify(spec, collection.find_one(query))
                else:
                    _verify(spec, collection.find(query, **options).to_list())

            if isinstance(manager, SharedCacheManager):
                shared = manager[spec.database][spec.collection]
                while shared._cache_ineligibility_reason() is not None:  # noqa: SLF001
                    time.sleep(_STARTUP_POLL_SECONDS)
            if spec.cell.workload == "cold":
                read(spec.warm_key)
            else:
                for key in spec.keys:
                    read(key)
            if isinstance(manager, CacheManager):
                manager.cache_core.reset_stream_cost_statistics(spec.database)
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
            loop = _run_sync(spec, window_start, read, warmup=False)
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
            if manager is not None:
                manager.close()
            client.close()


def _run_sync(
    spec: WorkerSpec,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], object],
    *,
    warmup: bool,
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
    )


async def _run_async(
    spec: WorkerSpec,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], Awaitable[object]],
    *,
    warmup: bool,
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
    )


async def async_worker(connection: Connection, spec: WorkerSpec) -> None:
    with proxy_for(spec.uri) as proxy:
        listener = WireCommands((spec.collection,))
        client: AsyncMongoClient[BsonDict] = AsyncMongoClient(
            f"mongodb://127.0.0.1:{proxy.local_port}",
            event_listeners=[listener],
            **spec.client_options,  # type: ignore[arg-type]
        )
        manager: (
            AsyncCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict] | None
        ) = None
        try:
            await client.admin.command("ping")
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
                    assert spec.attachment is not None
                    manager = AsyncSharedCacheManager(
                        client, await AsyncEndpoint.attach(spec.attachment)
                    )
                    collection = manager[spec.database][spec.collection]  # type: ignore[assignment]

            async def read(key: NonNegativeInt) -> None:
                query, options = _query(spec, key)
                if spec.read == "find_one":
                    _verify(spec, await collection.find_one(query))
                else:
                    _verify(spec, await collection.find(query, **options).to_list())

            if isinstance(manager, AsyncSharedCacheManager):
                shared = manager[spec.database][spec.collection]
                while await shared._cache_ineligibility_reason() is not None:  # noqa: ASYNC110, SLF001 - The owner offers no readiness notification.
                    await asyncio.sleep(_STARTUP_POLL_SECONDS)
            if spec.cell.workload == "cold":
                await read(spec.warm_key)
            else:
                for key in spec.keys:
                    await read(key)
            if isinstance(manager, AsyncCacheManager):
                manager.cache_core.reset_stream_cost_statistics(spec.database)
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
            with profiling(f"worker-{spec.cell.path}"):
                loop = await _run_async(spec, window_start, read, warmup=False)
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
            if manager is not None:
                await manager.close()
            await client.close()


def worker_main(connection: Connection, spec: WorkerSpec) -> None:
    try:
        if spec.model == "sync":
            sync_worker(connection, spec)
        else:
            asyncio.run(async_worker(connection, spec))
    except BenchmarkSetupError as error:
        connection.send({"kind": "failure", "error": str(error)})
        raise
    except LookupError as error:
        connection.send({"kind": "failure", "error": str(error)})
        raise
    finally:
        connection.close()

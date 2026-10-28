"""Measure the installed public shared API against direct and process-local reads."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import ctypes
import json
import math
import multiprocessing
import os
import platform
import resource
import statistics
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import AsyncExitStack, ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from importlib.metadata import version
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import psutil
from pymongo import AsyncMongoClient, MongoClient
from pymongo.read_concern import ReadConcern

from benchmarks.implementation import implementation as identify_implementation
from benchmarks.stream_cost.multiprocess_run import WireCommands, command_delta
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import (
    CacheCoreConfig,
    CacheManager,
    SharedCacheConfig,
    SharedCacheManager,
    SharedCacheServer,
    SharedCacheStatistics,
)
from client_query_cache._core.codec import encode_value
from client_query_cache._shared.attachment import SyncEndpoint
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous import (
    SharedCacheManager as AsyncSharedCacheManager,
)
from research.process_memory.measure import (
    BUDGETS,
    CODE_DOCUMENTS,
    COLD_CODES,
    MAX_ENTRY_BYTES,
    code_filter,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from multiprocessing.synchronize import Barrier

    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.monitoring import CommandSucceededEvent
    from pymongo.synchronous.collection import Collection

    from client_query_cache import CachedCollection
    from client_query_cache.asynchronous import (
        CachedCollection as AsyncCachedCollection,
    )
    from client_query_cache.shared import SharedCacheConnection

_HOT_KEYS = 4096
_DOCUMENT_BYTES = 4096
_WORKERS = 4
_CODE_METHODS = frozenset(("small-entries", "large-keys"))
_READY_TIMEOUT = 300
_START: Barrier
_FINISH: Barrier
_CPU_CLOCK = ctypes.CDLL(None).clock_getcpuclockid
_CPU_CLOCK.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_int))
_CPU_CLOCK.restype = ctypes.c_int


def _process_cpu_clock(pid: PositiveInt) -> int:
    clock = ctypes.c_int()
    status = _CPU_CLOCK(pid, ctypes.byref(clock))
    if status:
        raise OSError(status, os.strerror(status))
    return clock.value


@dataclass(frozen=True, slots=True)
class Observation:
    latencies_us: list[NonNegativeFloat]
    cpu_seconds: NonNegativeFloat
    pss_bytes: NonNegativeInt
    hits: NonNegativeInt
    measured_cpu_seconds: NonNegativeFloat
    streams: NonNegativeInt
    cache_hits: NonNegativeInt = 0
    cache_misses: NonNegativeInt = 0
    cache_bypasses: NonNegativeInt = 0
    endpoint_counts: dict[str, NonNegativeInt] = field(default_factory=dict)
    owner_requests: NonNegativeInt = 0
    origin_commands: dict[str, NonNegativeInt] = field(default_factory=dict)
    checkpoints: list[dict[str, NonNegativeInt]] = field(default_factory=list)
    implementation: dict[str, str] = field(default_factory=dict)
    resources: dict[str, object] = field(default_factory=dict)


class ReadCommands(WireCommands):
    def succeeded(self, event: CommandSucceededEvent) -> None:
        # Reuse command/stream counting without interpreting application cursor
        # documents as change-stream envelopes.
        self._record(event.command_name, "completed")


def _worker_record(observation: Observation) -> dict[str, object]:
    return {
        "completed": len(observation.latencies_us),
        "measured_cpu_seconds": observation.measured_cpu_seconds,
        "cpu_seconds_including_warmup": observation.cpu_seconds,
        "pss_bytes": observation.pss_bytes,
        "cache_hits": observation.cache_hits,
        "cache_misses": observation.cache_misses,
        "cache_bypasses": observation.cache_bypasses,
        "origin_commands": observation.origin_commands,
        "checkpoints": observation.checkpoints,
        "implementation": observation.implementation,
        "resources": observation.resources,
    }


def _install_barriers(start: Barrier, finish: Barrier) -> None:
    global _START, _FINISH
    _START, _FINISH = start, finish


def _collect(
    latencies: list[NonNegativeFloat],
    hits: NonNegativeInt,
    started: NonNegativeFloat,
    measured_cpu_started: NonNegativeFloat,
    streams: NonNegativeInt,
    *,
    cache_hits: NonNegativeInt = 0,
    cache_misses: NonNegativeInt = 0,
    cache_bypasses: NonNegativeInt = 0,
    endpoint_counts: dict[str, NonNegativeInt] | None = None,
    owner_requests: NonNegativeInt = 0,
    origin_commands: dict[str, NonNegativeInt] | None = None,
    checkpoints: list[dict[str, NonNegativeInt]] | None = None,
    implementation: dict[str, str] | None = None,
    manager: object = None,
    validate: bool = False,
) -> Observation:
    cpu_finished = time.process_time()
    _FINISH.wait(30)
    residual_cpu_started = time.process_time()
    residual_started = time.monotonic()
    stable_before = _checkpoint(manager, len(latencies)) if validate else {}
    if validate:
        # Foreground admissions must be complete when reads return. Observe an
        # untimed interval as well, so delayed work cannot escape resource scope.
        time.sleep(0.05)
        assert _checkpoint(manager, len(latencies)) == stable_before
    info = psutil.Process().memory_full_info()
    resources = (
        {
            "rss_bytes": info.rss,
            "uss_bytes": info.uss,
            "peak_rss_bytes_including_warmup": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * 1024,
            "residual_cpu_seconds": time.process_time() - residual_cpu_started,
            "residual_wall_seconds": time.monotonic() - residual_started,
            "stable_checkpoint": stable_before,
        }
        if validate
        else {}
    )
    _FINISH.wait(30)
    return Observation(
        latencies,
        cpu_finished - started,
        info.pss,
        hits,
        cpu_finished - measured_cpu_started,
        streams,
        cache_hits,
        cache_misses,
        cache_bypasses,
        {} if endpoint_counts is None else endpoint_counts,
        owner_requests,
        {} if origin_commands is None else origin_commands,
        [] if checkpoints is None else checkpoints,
        {} if implementation is None else implementation,
        resources,
    )


@dataclass(frozen=True, slots=True)
class Window:
    uri: str
    path: Literal["direct", "independent", "shared"]
    model: Literal["sync", "async"]
    workload: Literal["hot", "cold"]
    worker: NonNegativeInt
    samples: PositiveInt
    connection: SharedCacheConnection | None
    profile_path: Path | None = None
    method: str = "identity"
    hot_keys: PositiveInt = _HOT_KEYS
    result_documents: PositiveInt = 1
    read_rate: NonNegativeFloat = 0
    diagnostics: bool = False
    validate: bool = False
    document_bytes: PositiveInt = _DOCUMENT_BYTES
    rotation: NonNegativeInt = 0


def _checkpoint(
    manager: object, completed: NonNegativeInt
) -> dict[str, NonNegativeInt]:
    if not isinstance(manager, (CacheManager, AsyncCacheManager)):
        return {}
    snapshot = manager.snapshot()
    return {
        "completed": completed,
        "entries": snapshot.entry_count,
        "used_bytes": snapshot.used_bytes,
        "evictions": snapshot.evictions,
        "hits": snapshot.hits,
        "misses": snapshot.misses,
        "bypasses": snapshot.bypasses,
    }


def _implementation(manager: object) -> dict[str, str]:
    core = (
        manager.cache_core
        if isinstance(manager, (CacheManager, AsyncCacheManager))
        else manager
    )
    return identify_implementation(core)


def expected_value(
    window: Window, identity: NonNegativeInt, payloads: tuple[str, ...]
) -> BsonDict | list[BsonDict]:
    if window.method in _CODE_METHODS:
        return {"_id": identity, "code": f"C{identity:07d}", "state": "active"}
    if window.method == "identity":
        ordinal = identity % window.result_documents
        return {
            "_id": identity,
            "group": identity // window.result_documents,
            "ordinal": ordinal,
            "payload": payloads[ordinal],
        }
    if window.method == "find_one":
        ordinal = window.result_documents - 1
        return {
            "_id": identity * window.result_documents + ordinal,
            "group": identity,
            "ordinal": ordinal,
            "payload": payloads[ordinal],
        }
    return [
        {
            "_id": identity * window.result_documents + ordinal,
            "group": identity,
            "ordinal": ordinal,
            "payload": payloads[ordinal],
        }
        for ordinal in range(window.result_documents)
    ]


def _validate_value(
    value: object, window: Window, identity: NonNegativeInt, payloads: tuple[str, ...]
) -> None:
    assert value == expected_value(window, identity, payloads)


def _validate_checkpoint(window: Window, checkpoint: dict[str, NonNegativeInt]) -> None:
    if window.path != "independent":
        return
    if window.method in _CODE_METHODS:
        assert checkpoint["entries"] == COLD_CODES + 1
        assert checkpoint["used_bytes"] == COLD_CODES * 59 + 8
    else:
        assert checkpoint["entries"] == window.hot_keys
    assert checkpoint["bypasses"] == 0


def _validate_observation(
    window: Window,
    before: SharedCacheStatistics,
    after: SharedCacheStatistics,
    origin: dict[str, NonNegativeInt],
    checkpoints: list[dict[str, NonNegativeInt]],
) -> None:
    cached = window.path != "direct"
    assert after.hits - before.hits == (
        window.samples if cached and window.workload == "hot" else 0
    )
    assert after.misses - before.misses == (
        window.samples if cached and window.workload == "cold" else 0
    )
    assert after.bypasses == before.bypasses
    reads = 0
    for command in ("find", "aggregate", "count", "distinct"):
        try:
            reads += origin[f"{command}:requested"]
        except KeyError:
            pass
    assert reads == (
        window.samples
        if window.path == "direct"
        or (window.path == "independent" and window.workload == "cold")
        else 0
    )
    if window.path == "independent" and window.method not in _CODE_METHODS:
        payloads = tuple(
            f"{ordinal}:" + "x" * window.document_bytes
            for ordinal in range(window.result_documents)
        )
        weight = len(encode_value(expected_value(window, 0, payloads)))
        for checkpoint in checkpoints:
            entries = window.hot_keys + (
                checkpoint["completed"] if window.workload == "cold" else 0
            )
            assert checkpoint["entries"] == entries
            assert checkpoint["used_bytes"] == entries * weight
            assert checkpoint["evictions"] == 0
    if window.path == "independent" and window.method in _CODE_METHODS:
        initial = checkpoints[0]
        budget = BUDGETS[window.method]
        for checkpoint in checkpoints:
            completed = checkpoint["completed"]
            if window.workload == "hot":
                entries, used, evictions = COLD_CODES + 1, COLD_CODES * 59 + 8, 0
            elif COLD_CODES * 59 + 8 + completed * 59 <= budget:
                entries, used, evictions = (
                    COLD_CODES + 1 + completed,
                    COLD_CODES * 59 + 8 + completed * 59,
                    0,
                )
            else:
                entries = budget // 59
                used = entries * 59
                evictions = COLD_CODES + 1 + completed - entries
            assert (
                checkpoint["entries"],
                checkpoint["used_bytes"],
                checkpoint["evictions"],
            ) == (entries, used, evictions)
            assert checkpoint["hits"] - initial["hits"] == (
                completed if window.workload == "hot" else 0
            )
            assert checkpoint["misses"] - initial["misses"] == (
                completed if window.workload == "cold" else 0
            )
            assert checkpoint["bypasses"] == 0


def _endpoint_snapshot(window: Window, manager: object) -> dict[str, NonNegativeInt]:
    if window.diagnostics and isinstance(
        manager, (SharedCacheManager, AsyncSharedCacheManager)
    ):
        return asdict(manager.endpoint.counters)
    return {}


@contextmanager
def _profile(window: Window) -> Generator[None]:
    if window.profile_path is None:
        yield
        return
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield
    finally:
        profiler.disable()
        window.profile_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(window.profile_path)


def _identity(window: Window, offset: NonNegativeInt) -> NonNegativeInt:
    return (
        (window.rotation + offset) % window.hot_keys
        if window.workload == "hot"
        else window.hot_keys + window.worker * window.samples + offset
    )


def _read_sync(
    view: CachedCollection[BsonDict] | Collection[BsonDict],
    window: Window,
    identity: NonNegativeInt,
) -> object:
    if window.method == "identity":
        return view.find_one({"_id": identity})
    if window.method in _CODE_METHODS:
        return view.find_one(code_filter(identity, large=window.method == "large-keys"))
    query = {"group": identity}
    if window.method == "find_one":
        return view.find_one(query, sort=[("ordinal", -1)])
    if window.method == "find":
        return (
            view.find(query).sort("ordinal", 1).limit(window.result_documents).to_list()
        )
    if window.method == "aggregate":
        return view.aggregate(
            [
                {"$match": query},
                {"$sort": {"ordinal": 1}},
                {"$limit": window.result_documents},
            ]
        ).to_list()
    if window.method == "count_documents":
        return view.count_documents(query)
    if window.method == "distinct":
        return view.distinct("payload", query)
    return view.estimated_document_count()


async def _read_async(
    view: AsyncCachedCollection[BsonDict] | AsyncCollection[BsonDict],
    window: Window,
    identity: NonNegativeInt,
) -> object:
    if window.method == "identity":
        return await view.find_one({"_id": identity})
    if window.method in _CODE_METHODS:
        return await view.find_one(
            code_filter(identity, large=window.method == "large-keys")
        )
    query = {"group": identity}
    if window.method == "find_one":
        return await view.find_one(query, sort=[("ordinal", -1)])
    if window.method == "find":
        return (
            await view.find(query)
            .sort("ordinal", 1)
            .limit(window.result_documents)
            .to_list()
        )
    if window.method == "aggregate":
        cursor = await view.aggregate(
            [
                {"$match": query},
                {"$sort": {"ordinal": 1}},
                {"$limit": window.result_documents},
            ]
        )
        return await cursor.to_list()
    if window.method == "count_documents":
        return await view.count_documents(query)
    if window.method == "distinct":
        return await view.distinct("payload", query)
    return await view.estimated_document_count()


def _counts(
    manager: CacheManager[BsonDict]
    | AsyncCacheManager[BsonDict]
    | SharedCacheManager[BsonDict]
    | AsyncSharedCacheManager[BsonDict],
) -> SharedCacheStatistics:
    snapshot = (
        manager.snapshot()
        if isinstance(manager, (SharedCacheManager, AsyncSharedCacheManager))
        else manager.cache_core.snapshot()
    )
    return SharedCacheStatistics(snapshot.hits, snapshot.misses, snapshot.bypasses)


def _measure_sync(window: Window) -> Observation:
    cpu_started = time.process_time()
    commands = ReadCommands(()) if window.validate else None
    payloads = (
        tuple(
            f"{ordinal}:" + "x" * window.document_bytes
            for ordinal in range(window.result_documents)
        )
        if window.validate and window.method not in _CODE_METHODS
        else ()
    )
    with ExitStack() as resources:
        client = resources.enter_context(
            MongoClient[BsonDict](
                window.uri, event_listeners=[] if commands is None else [commands]
            )
        )
        raw = client.public_shared_cache.items.with_options(
            read_concern=ReadConcern("majority")
        )
        view: CachedCollection[BsonDict] | Collection[BsonDict]
        if window.path == "shared":
            assert window.connection is not None
            manager = resources.enter_context(
                SharedCacheManager(client, window.connection)
            )
            view = manager.get_cached_collection(raw)
        elif window.path == "independent":
            independent = resources.enter_context(
                CacheManager(
                    client,
                    cache_config=CacheCoreConfig(
                        shared_budget_bytes=BUDGETS[window.method],
                        max_entry_bytes=MAX_ENTRY_BYTES,
                    )
                    if window.method in _CODE_METHODS
                    else None,
                )
            )
            view = independent.get_cached_collection(raw)
        else:
            view = raw
        observed_manager = (
            None
            if window.path == "direct"
            else manager
            if window.path == "shared"
            else independent
        )
        if window.method in _CODE_METHODS and window.path == "independent":
            assert (
                independent.get_cached_collection(
                    client.public_shared_cache.catalogue.with_options(
                        read_concern=ReadConcern("majority")
                    )
                ).find_one({"_id": -1})
                is None
            )
        cold_view: CachedCollection[BsonDict] | Collection[BsonDict]
        cold_views = []
        if window.method == "estimated_document_count" and window.workload == "cold":
            for offset in range(window.samples):
                cold_raw = raw.database[f"count_{window.worker}_{offset}"].with_options(
                    read_concern=ReadConcern("majority")
                )
                if window.path == "shared":
                    cold_view = manager.get_cached_collection(cold_raw)
                elif window.path == "independent":
                    cold_view = independent.get_cached_collection(cold_raw)
                else:
                    cold_view = cold_raw
                cold_view.find_one({"_id": -1})
                cold_views.append(cold_view)
        for identity in range(window.hot_keys):
            value = _read_sync(view, window, identity)
            assert value is not None
            if window.validate:
                _validate_value(value, window, identity, payloads)
        if window.path != "direct":
            warming = manager if window.path == "shared" else independent
            deadline = time.monotonic() + _READY_TIMEOUT
            while True:
                before_warm = _counts(warming)
                for identity in range(window.hot_keys):
                    value = _read_sync(view, window, identity)
                    assert value is not None
                    if window.validate:
                        _validate_value(value, window, identity, payloads)
                after_warm = _counts(warming)
                if (
                    after_warm.hits - before_warm.hits == window.hot_keys
                    and after_warm.misses == before_warm.misses
                    and after_warm.bypasses == before_warm.bypasses
                ):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "cache warmup did not cover the complete resident catalogue"
                    )
                time.sleep(0.02)
        checkpoints = []
        if window.validate:
            checkpoints.append(_checkpoint(observed_manager, 0))
            _validate_checkpoint(window, checkpoints[-1])
        implementation = _implementation(observed_manager) if window.validate else {}
        requests_before = (
            manager.endpoint.counters.requests if window.path == "shared" else 0
        )
        endpoint_before = _endpoint_snapshot(
            window, manager if window.path == "shared" else None
        )
        _START.wait(_READY_TIMEOUT)
        _START.wait(_READY_TIMEOUT)
        # The command delta must enclose the measured reads.
        origin_before = (  # pytriage: TR11 - Capture before the measured reads.
            {} if commands is None else commands.snapshot()
        )
        measured_cpu_started = time.process_time()
        measurement_started = time.monotonic()
        latencies: list[NonNegativeFloat] = []
        before_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
        )
        with _profile(window):
            for offset in range(window.samples):
                if window.read_rate:
                    time.sleep(
                        max(
                            0,
                            measurement_started
                            + offset * _WORKERS / window.read_rate
                            - time.monotonic(),
                        )
                    )
                identity = _identity(window, offset)
                started = time.perf_counter_ns()
                document = _read_sync(
                    cold_views[offset] if cold_views else view,
                    window,
                    identity,
                )
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
                if window.validate:
                    _validate_value(document, window, identity, payloads)
                    if (
                        window.method in _CODE_METHODS
                        and (offset + 1) % 256 == 0
                        and offset + 1 < window.samples
                    ):
                        checkpoints.append(_checkpoint(observed_manager, offset + 1))
        after_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
        )
        origin = (
            {}
            if commands is None
            else command_delta(origin_before, commands.snapshot())
        )
        if window.validate:
            checkpoints.append(_checkpoint(observed_manager, window.samples))
            assert commands is not None
            _validate_observation(
                window, before_counts, after_counts, origin, checkpoints
            )
        hits = 0 if window.path != "shared" else after_counts.hits - before_counts.hits
        return _collect(
            latencies,
            hits,
            cpu_started,
            measured_cpu_started,
            len(independent.active_stream_cost_databases())
            if window.path == "independent"
            else 0,
            cache_hits=after_counts.hits - before_counts.hits,
            cache_misses=after_counts.misses - before_counts.misses,
            cache_bypasses=after_counts.bypasses - before_counts.bypasses,
            endpoint_counts={
                name: count - endpoint_before[name]
                for name, count in _endpoint_snapshot(
                    window, manager if window.path == "shared" else None
                ).items()
            },
            owner_requests=manager.endpoint.counters.requests - requests_before
            if window.path == "shared"
            else 0,
            origin_commands=origin,
            checkpoints=checkpoints,
            implementation=implementation,
            manager=observed_manager,
            validate=window.validate,
        )


async def _measure_async(
    window: Window,
) -> Observation:
    cpu_started = time.process_time()
    commands = ReadCommands(()) if window.validate else None
    payloads = (
        tuple(
            f"{ordinal}:" + "x" * window.document_bytes
            for ordinal in range(window.result_documents)
        )
        if window.validate and window.method not in _CODE_METHODS
        else ()
    )
    async with AsyncExitStack() as resources:
        client = await resources.enter_async_context(
            AsyncMongoClient[BsonDict](
                window.uri, event_listeners=[] if commands is None else [commands]
            )
        )
        raw = client.public_shared_cache.items.with_options(
            read_concern=ReadConcern("majority")
        )
        view: AsyncCachedCollection[BsonDict] | AsyncCollection[BsonDict]
        if window.path == "shared":
            assert window.connection is not None
            manager = await resources.enter_async_context(
                AsyncSharedCacheManager(client, window.connection)
            )
            view = manager.get_cached_collection(raw)
        elif window.path == "independent":
            independent = await resources.enter_async_context(
                AsyncCacheManager(
                    client,
                    cache_config=CacheCoreConfig(
                        shared_budget_bytes=BUDGETS[window.method],
                        max_entry_bytes=MAX_ENTRY_BYTES,
                    )
                    if window.method in _CODE_METHODS
                    else None,
                )
            )
            view = independent.get_cached_collection(raw)
        else:
            view = raw
        observed_manager = (
            None
            if window.path == "direct"
            else manager
            if window.path == "shared"
            else independent
        )
        if window.method in _CODE_METHODS and window.path == "independent":
            assert (
                await independent.get_cached_collection(
                    client.public_shared_cache.catalogue.with_options(
                        read_concern=ReadConcern("majority")
                    )
                ).find_one({"_id": -1})
                is None
            )
        cold_view: AsyncCachedCollection[BsonDict] | AsyncCollection[BsonDict]
        cold_views = []
        if window.method == "estimated_document_count" and window.workload == "cold":
            for offset in range(window.samples):
                cold_raw = raw.database[f"count_{window.worker}_{offset}"].with_options(
                    read_concern=ReadConcern("majority")
                )
                if window.path == "shared":
                    cold_view = manager.get_cached_collection(cold_raw)
                elif window.path == "independent":
                    cold_view = independent.get_cached_collection(cold_raw)
                else:
                    cold_view = cold_raw
                await cold_view.find_one({"_id": -1})
                cold_views.append(cold_view)
        for identity in range(window.hot_keys):
            value = await _read_async(view, window, identity)
            assert value is not None
            if window.validate:
                _validate_value(value, window, identity, payloads)
        if window.path != "direct":
            warming = manager if window.path == "shared" else independent
            deadline = time.monotonic() + _READY_TIMEOUT
            while True:
                before_warm = _counts(warming)
                for identity in range(window.hot_keys):
                    value = await _read_async(view, window, identity)
                    assert value is not None
                    if window.validate:
                        _validate_value(value, window, identity, payloads)
                after_warm = _counts(warming)
                if (
                    after_warm.hits - before_warm.hits == window.hot_keys
                    and after_warm.misses == before_warm.misses
                    and after_warm.bypasses == before_warm.bypasses
                ):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "cache warmup did not cover the complete resident catalogue"
                    )
                await asyncio.sleep(0.02)
        checkpoints = []
        if window.validate:
            checkpoints.append(_checkpoint(observed_manager, 0))
            _validate_checkpoint(window, checkpoints[-1])
        implementation = _implementation(observed_manager) if window.validate else {}
        requests_before = (
            manager.endpoint.counters.requests if window.path == "shared" else 0
        )
        endpoint_before = _endpoint_snapshot(
            window, manager if window.path == "shared" else None
        )
        _START.wait(_READY_TIMEOUT)
        _START.wait(_READY_TIMEOUT)
        # The command delta must enclose the measured reads.
        origin_before = (  # pytriage: TR11 - Capture before the measured reads.
            {} if commands is None else commands.snapshot()
        )
        measured_cpu_started = time.process_time()
        measurement_started = time.monotonic()
        latencies: list[NonNegativeFloat] = []
        before_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
        )
        with _profile(window):
            for offset in range(window.samples):
                if window.read_rate:
                    await asyncio.sleep(
                        max(
                            0,
                            measurement_started
                            + offset * _WORKERS / window.read_rate
                            - time.monotonic(),
                        )
                    )
                identity = _identity(window, offset)
                started = time.perf_counter_ns()
                document = await _read_async(
                    cold_views[offset] if cold_views else view,
                    window,
                    identity,
                )
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
                if window.validate:
                    _validate_value(document, window, identity, payloads)
                    if (
                        window.method in _CODE_METHODS
                        and (offset + 1) % 256 == 0
                        and offset + 1 < window.samples
                    ):
                        checkpoints.append(_checkpoint(observed_manager, offset + 1))
        after_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
        )
        origin = (
            {}
            if commands is None
            else command_delta(origin_before, commands.snapshot())
        )
        if window.validate:
            checkpoints.append(_checkpoint(observed_manager, window.samples))
            assert commands is not None
            _validate_observation(
                window, before_counts, after_counts, origin, checkpoints
            )
        hits = 0 if window.path != "shared" else after_counts.hits - before_counts.hits
        return _collect(
            latencies,
            hits,
            cpu_started,
            measured_cpu_started,
            len(independent.active_stream_cost_databases())
            if window.path == "independent"
            else 0,
            cache_hits=after_counts.hits - before_counts.hits,
            cache_misses=after_counts.misses - before_counts.misses,
            cache_bypasses=after_counts.bypasses - before_counts.bypasses,
            endpoint_counts={
                name: count - endpoint_before[name]
                for name, count in _endpoint_snapshot(
                    window, manager if window.path == "shared" else None
                ).items()
            },
            owner_requests=manager.endpoint.counters.requests - requests_before
            if window.path == "shared"
            else 0,
            origin_commands=origin,
            checkpoints=checkpoints,
            implementation=implementation,
            manager=observed_manager,
            validate=window.validate,
        )


def _worker(window: Window) -> Observation:
    observation = (
        _measure_sync(window)
        if window.model == "sync"
        else asyncio.run(_measure_async(window))
    )
    if window.validate:
        for component in ("library", "extension"):
            assert Path(observation.implementation[component]).is_relative_to(
                sys.prefix
            )
    return observation


def _run_window(
    replica: IsolatedReplicaSet,
    model: Literal["sync", "async"],
    workload: Literal["hot", "cold"],
    path: Literal["direct", "independent", "shared"],
    samples: PositiveInt,
    *,
    profile_directory: Path | None,
    method: str = "identity",
    hot_keys: PositiveInt = _HOT_KEYS,
    result_documents: PositiveInt = 1,
    write_interval: NonNegativeFloat = 0,
    read_rate: NonNegativeFloat = 0,
    diagnostics: bool = False,
    validate: bool = False,
    document_bytes: PositiveInt = _DOCUMENT_BYTES,
    rotation: NonNegativeInt = 0,
) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    start, finish = context.Barrier(_WORKERS + 1), context.Barrier(_WORKERS + 1)
    with ExitStack() as resources:
        server = None
        if path == "shared":
            server = resources.enter_context(
                SharedCacheServer(
                    replica.uri,
                    ("public_shared_cache",),
                    config=SharedCacheConfig(
                        budget_bytes=32 * 1024 * 1024,
                        arena_bytes=40 * 1024 * 1024,
                        slots=16_384,
                    ),
                )
            )
        pool = resources.enter_context(
            ProcessPoolExecutor(
                max_workers=_WORKERS,
                mp_context=context,
                initializer=_install_barriers,
                initargs=(start, finish),
            )
        )
        stop_writer = threading.Event()
        writer = (
            resources.enter_context(MongoClient[BsonDict](replica.uri, timeoutMS=5000))
            if write_interval
            else None
        )
        if writer is not None:
            writer.admin.command("ping")

        def write() -> NonNegativeInt:
            assert writer is not None
            writes = 0
            while not stop_writer.is_set():
                writer.public_shared_cache.items.update_one(
                    {"group": 0}, {"$inc": {"revision": 1}}
                )
                writes += 1
                stop_writer.wait(write_interval)
            return writes

        futures = tuple(
            pool.submit(
                _worker,
                Window(
                    replica.uri,
                    path,
                    model,
                    workload,
                    worker,
                    samples,
                    None if server is None else server.connection,
                    None
                    if profile_directory is None
                    else profile_directory
                    / f"{model}-{workload}-{path}-{worker}.pstats",
                    method,
                    hot_keys,
                    result_documents,
                    read_rate,
                    diagnostics,
                    validate,
                    document_bytes,
                    rotation,
                ),
            )
            for worker in range(_WORKERS)
        )
        start.wait(_READY_TIMEOUT)
        owner = None
        endpoint = None
        owner_before = None
        if server is not None and (diagnostics or validate):
            endpoint = SyncEndpoint(server.connection._attachment)
            resources.callback(endpoint.close)
            owner_before = endpoint.request({"op": "observe"})
            assert owner_before is not None
        owner_cpu_before = 0.0
        owner_clock = None
        if server is not None:
            assert server._process is not None
            owner = psutil.Process(server._process.pid)
            owner_clock = _process_cpu_clock(owner.pid)
            owner_cpu_before = time.clock_gettime(owner_clock)
        # Capture before the measured interval.
        server_cpu_before = replica.container_cpu_usage_seconds()
        started = time.monotonic()
        writer_future = None
        # Include writer startup and stop within its CPU interval.
        writer_cpu_before = time.process_time()
        if write_interval:
            writer_pool = resources.enter_context(ThreadPoolExecutor(max_workers=1))
            writer_future = writer_pool.submit(write)
        supervisor_cpu_started = time.process_time()
        try:
            start.wait(30)
            finish.wait(30)
            supervisor_cpu = time.process_time() - supervisor_cpu_started
        finally:
            stop_writer.set()
            writes = 0 if writer_future is None else writer_future.result(timeout=10)
        writer_cpu = time.process_time() - writer_cpu_before if write_interval else 0
        elapsed = time.monotonic() - started
        server_cpu = replica.container_cpu_usage_seconds() - server_cpu_before
        owner_pss = 0
        owner_cpu = 0.0
        if owner is not None:
            assert owner_clock is not None
            owner_cpu = time.clock_gettime(owner_clock)
            owner_pss = owner.memory_full_info().pss
        owner_streams = 0
        owner_after = None
        if server is not None:
            if endpoint is None:
                endpoint = SyncEndpoint(server.connection._attachment)
                resources.callback(endpoint.close)
            owner_after = endpoint.request({"op": "observe"})
            assert owner_after is not None
            commands = owner_after["upstream_commands"]
            assert isinstance(commands, dict)
            owner_streams = commands["aggregate:requested"]
        finish.wait(30)
        observations = tuple(future.result() for future in futures)
        if validate:
            quantum = time.get_clock_info("process_time").resolution
            assert supervisor_cpu > 100 * quantum
            assert all(
                observation.measured_cpu_seconds > 100 * quantum
                for observation in observations
            )
            if owner_clock is not None:
                assert owner_cpu - owner_cpu_before > 100 * time.clock_getres(
                    owner_clock
                )
        latencies = sorted(
            latency
            for observation in observations
            for latency in observation.latencies_us
        )
        return {
            "method": method,
            "model": model,
            "throughput": _WORKERS * samples / elapsed,
            "server_cpu_seconds": server_cpu,
            "write_interval_seconds": write_interval,
            "writes": writes,
            "writer_cpu_seconds": writer_cpu,
            "target_read_rate": read_rate,
            "result_documents": result_documents,
            "workload": workload,
            "path": path,
            "median_us": statistics.median(latencies),
            "p95_us": latencies[int(len(latencies) * 0.95)],
            "p99_us": latencies[int(len(latencies) * 0.99)],
            "worker_pss_bytes": sum(
                observation.pss_bytes for observation in observations
            ),
            "owner_pss_bytes": owner_pss,
            "cpu_seconds_including_warmup": sum(
                observation.cpu_seconds for observation in observations
            )
            + owner_cpu,
            "supervisor_cpu_seconds": supervisor_cpu,
            "measured_cpu_seconds": supervisor_cpu
            + sum(observation.measured_cpu_seconds for observation in observations)
            + owner_cpu
            - owner_cpu_before,
            "measured_worker_cpu_seconds": sum(
                observation.measured_cpu_seconds for observation in observations
            ),
            "measured_owner_cpu_seconds": owner_cpu - owner_cpu_before,
            "owner_cpu_resolution_seconds": None
            if owner_clock is None
            else time.clock_getres(owner_clock),
            "worker_endpoint_counters": {
                name: sum(
                    observation.endpoint_counts[name] for observation in observations
                )
                for name in observations[0].endpoint_counts
            },
            "owner_requests": sum(
                observation.owner_requests for observation in observations
            ),
            "owner_before": owner_before,
            "owner_after": owner_after if diagnostics or validate else None,
            "shared_hits": sum(observation.hits for observation in observations),
            "cache_hits": sum(observation.cache_hits for observation in observations),
            "cache_misses": sum(
                observation.cache_misses for observation in observations
            ),
            "cache_bypasses": sum(
                observation.cache_bypasses for observation in observations
            ),
            "streams": owner_streams
            + sum(observation.streams for observation in observations),
            "worker_observations": [
                _worker_record(observation) for observation in observations
            ]
            if validate
            else None,
            "process_cpu_clock": vars(time.get_clock_info("process_time")),
            "completed_reads": sum(
                len(observation.latencies_us) for observation in observations
            ),
        }


def _seed(
    client: MongoClient[BsonDict], arguments: argparse.Namespace, workload: str
) -> None:
    client.drop_database("public_shared_cache")
    if arguments.method in _CODE_METHODS:
        client.public_shared_cache.create_collection("catalogue")
        for start in range(0, CODE_DOCUMENTS, 10_000):
            client.public_shared_cache.items.insert_many(
                {"_id": index, "code": f"C{index:07d}", "state": "active"}
                for index in range(start, start + 10_000)
            )
        client.public_shared_cache.items.create_index("code")
        assert (
            len(encode_value({"_id": 0, "code": "C0000000", "state": "active"})) == 59
        )
        assert len(encode_value(None)) == 8
        return
    groups = arguments.hot_keys + (
        _WORKERS * arguments.samples if workload == "cold" else 0
    )
    payloads = tuple(
        f"{ordinal}:" + "x" * arguments.document_bytes
        for ordinal in range(arguments.result_documents)
    )
    client.public_shared_cache.items.insert_many(
        {
            "_id": identity * arguments.result_documents + ordinal,
            "group": identity,
            "ordinal": ordinal,
            "payload": payloads[ordinal],
        }
        for identity in range(groups)
        for ordinal in range(arguments.result_documents)
    )
    client.public_shared_cache.items.create_index([("group", 1), ("ordinal", 1)])
    if arguments.method == "estimated_document_count" and workload == "cold":
        for worker in range(_WORKERS):
            for offset in range(arguments.samples):
                client.public_shared_cache[f"count_{worker}_{offset}"].insert_many(
                    {
                        "_id": ordinal,
                        "payload": "x" * arguments.document_bytes,
                    }
                    for ordinal in range(arguments.result_documents)
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Verify installed artifacts, results, origins and cache trajectories.",
    )
    parser.add_argument("--rotation", type=int, default=0)
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Include worker and owner transport counters for attribution.",
    )
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--method",
        choices=(
            "identity",
            "find_one",
            "find",
            "aggregate",
            "count_documents",
            "estimated_document_count",
            "distinct",
            "small-entries",
            "large-keys",
        ),
        default="identity",
    )
    parser.add_argument("--hot-keys", type=int, default=_HOT_KEYS)
    parser.add_argument("--result-documents", type=int, default=1)
    parser.add_argument("--document-bytes", type=int, default=_DOCUMENT_BYTES)
    parser.add_argument("--write-interval", type=float, default=0)
    parser.add_argument("--read-rate", type=float, default=0)
    parser.add_argument(
        "--models", nargs="+", choices=("sync", "async"), default=("sync", "async")
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        choices=("direct", "independent", "shared"),
        default=("direct", "independent", "shared"),
    )
    parser.add_argument(
        "--workloads", nargs="+", choices=("hot", "cold"), default=("hot", "cold")
    )
    arguments = parser.parse_args()
    if (
        min(
            arguments.samples,
            arguments.repetitions,
            arguments.hot_keys,
            arguments.result_documents,
            arguments.document_bytes,
        )
        <= 0
        or arguments.write_interval < 0
        or arguments.read_rate < 0
        or not math.isfinite(arguments.read_rate)
        or not math.isfinite(arguments.write_interval)
    ):
        parser.error("samples and repetitions must be positive")
    if arguments.rotation < 0:
        parser.error("rotation must not be negative")
    if arguments.method in _CODE_METHODS:
        if (
            arguments.hot_keys != COLD_CODES
            or arguments.result_documents != 1
            or "shared" in arguments.paths
        ):
            parser.error(
                "small-result controls require 64,000 keys, one document "
                "and direct/independent paths"
            )
        if (
            "cold" in arguments.workloads
            and COLD_CODES + _WORKERS * arguments.samples > CODE_DOCUMENTS
        ):
            parser.error(
                "cold code requests must fit within the 100,000-code catalogue"
            )
    if arguments.validate and (
        arguments.method not in {"identity", "find_one", "find", *_CODE_METHODS}
        or arguments.write_interval
    ):
        parser.error(
            "validated cells support identity, find_one, find and small-result "
            "controls without a writer"
        )
    if (
        arguments.method == "estimated_document_count"
        and "cold" in arguments.workloads
        and arguments.samples > 255
    ):
        parser.error(
            "cold estimated counts require samples <= 255 to fit 1,024 namespace slots"
        )
    windows: list[dict[str, object]] = []
    invalid_reason = None
    try:
        with (
            IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica,
            MongoClient[BsonDict](replica.uri) as client,
        ):
            for repetition, model, workload in product(
                range(arguments.repetitions), arguments.models, arguments.workloads
            ):
                paths = tuple(arguments.paths)
                rotation = repetition % len(paths)
                for path in paths[rotation:] + paths[:rotation]:
                    _seed(client, arguments, workload)
                    windows.append(
                        {
                            "repetition": repetition,
                            **_run_window(
                                replica,
                                model,
                                workload,
                                path,
                                arguments.samples,
                                method=arguments.method,
                                hot_keys=arguments.hot_keys,
                                result_documents=arguments.result_documents,
                                write_interval=arguments.write_interval,
                                read_rate=arguments.read_rate,
                                diagnostics=arguments.diagnostics,
                                validate=arguments.validate,
                                document_bytes=arguments.document_bytes,
                                rotation=arguments.rotation,
                                profile_directory=None
                                if arguments.profile_dir is None
                                else arguments.profile_dir / str(repetition),
                            ),
                        }
                    )
    except Exception as error:
        invalid_reason = f"{type(error).__name__}: {error}"
        raise
    finally:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(
                {
                    "package": version("client-query-cache"),
                    "pymongo": version("pymongo"),
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "cpus": os.cpu_count(),
                    "samples_per_worker": arguments.samples,
                    "workers": _WORKERS,
                    "document_bytes": arguments.document_bytes,
                    "hot_keys": arguments.hot_keys,
                    "validated": arguments.validate,
                    "rotation": arguments.rotation,
                    "windows": windows,
                    "invalid_reason": invalid_reason,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()

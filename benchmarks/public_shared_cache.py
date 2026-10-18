"""Measure the installed public shared API against direct and process-local reads."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import math
import multiprocessing
import os
import platform
import statistics
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import AsyncExitStack, ExitStack, contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import psutil
from pymongo import AsyncMongoClient, MongoClient
from pymongo.read_concern import ReadConcern

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import (
    CacheManager,
    SharedCacheConfig,
    SharedCacheManager,
    SharedCacheServer,
    SharedCacheStatistics,
)
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

if TYPE_CHECKING:
    from collections.abc import Generator
    from multiprocessing.synchronize import Barrier

    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.synchronous.collection import Collection

    from client_query_cache import CachedCollection
    from client_query_cache.asynchronous import (
        CachedCollection as AsyncCachedCollection,
    )
    from client_query_cache.shared import SharedCacheConnection

_HOT_KEYS = 4096
_DOCUMENT_BYTES = 4096
_WORKERS = 4
_START: Barrier
_FINISH: Barrier


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
) -> Observation:
    cpu_finished = time.process_time()
    _FINISH.wait(30)
    pss_bytes = psutil.Process().memory_full_info().pss
    _FINISH.wait(30)
    return Observation(
        latencies,
        cpu_finished - started,
        pss_bytes,
        hits,
        cpu_finished - measured_cpu_started,
        streams,
        cache_hits,
        cache_misses,
        cache_bypasses,
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
        offset % window.hot_keys
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
    with ExitStack() as resources:
        client = resources.enter_context(MongoClient[BsonDict](window.uri))
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
            independent = resources.enter_context(CacheManager(client))
            view = independent.get_cached_collection(raw)
        else:
            view = raw
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
            assert _read_sync(view, window, identity) is not None
        if window.path != "direct":
            warming = manager if window.path == "shared" else independent
            deadline = time.monotonic() + 10
            while _counts(warming).hits < window.hot_keys:
                for identity in range(window.hot_keys):
                    assert _read_sync(view, window, identity) is not None
                if time.monotonic() > deadline:
                    raise TimeoutError("cache warmup did not reach hits")
                time.sleep(0.02)
        _START.wait(30)
        _START.wait(30)
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
                started = time.perf_counter_ns()
                document = _read_sync(
                    cold_views[offset] if cold_views else view,
                    window,
                    _identity(window, offset),
                )
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
        after_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
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
        )


async def _measure_async(
    window: Window,
) -> Observation:
    cpu_started = time.process_time()
    async with AsyncExitStack() as resources:
        client = await resources.enter_async_context(
            AsyncMongoClient[BsonDict](window.uri)
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
            independent = await resources.enter_async_context(AsyncCacheManager(client))
            view = independent.get_cached_collection(raw)
        else:
            view = raw
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
            assert await _read_async(view, window, identity) is not None
        if window.path != "direct":
            warming = manager if window.path == "shared" else independent
            deadline = time.monotonic() + 10
            while _counts(warming).hits < window.hot_keys:
                for identity in range(window.hot_keys):
                    assert await _read_async(view, window, identity) is not None
                if time.monotonic() > deadline:
                    raise TimeoutError("cache warmup did not reach hits")
                await asyncio.sleep(0.02)
        _START.wait(30)
        _START.wait(30)
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
                started = time.perf_counter_ns()
                document = await _read_async(
                    cold_views[offset] if cold_views else view,
                    window,
                    _identity(window, offset),
                )
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
        after_counts = (
            SharedCacheStatistics(0, 0, 0)
            if window.path == "direct"
            else _counts(manager if window.path == "shared" else independent)
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
        )


def _worker(window: Window) -> Observation:
    return (
        _measure_sync(window)
        if window.model == "sync"
        else asyncio.run(_measure_async(window))
    )


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
                ),
            )
            for worker in range(_WORKERS)
        )
        start.wait(30)
        owner = None
        owner_cpu_before = 0.0
        if server is not None:
            assert server._process is not None
            owner = psutil.Process(server._process.pid)
            owner_cpu_before = sum(owner.cpu_times()[:2])
        # Capture before the measured interval.
        server_cpu_before = replica.container_cpu_usage_seconds()  # pytriage: TR11
        started = time.monotonic()
        writer_future = None
        # Include writer startup and stop within its CPU interval.
        writer_cpu_before = time.process_time()  # pytriage: TR11
        if write_interval:
            writer_pool = resources.enter_context(ThreadPoolExecutor(max_workers=1))
            writer_future = writer_pool.submit(write)
        try:
            start.wait(30)
            finish.wait(30)
        finally:
            stop_writer.set()
            writes = 0 if writer_future is None else writer_future.result(timeout=10)
        writer_cpu = time.process_time() - writer_cpu_before if write_interval else 0
        elapsed = time.monotonic() - started
        server_cpu = replica.container_cpu_usage_seconds() - server_cpu_before
        owner_pss = 0
        owner_cpu = 0.0
        if owner is not None:
            owner_cpu = sum(owner.cpu_times()[:2])
            owner_pss = owner.memory_full_info().pss
        owner_streams = 0
        if server is not None:
            endpoint = SyncEndpoint(server.connection._attachment)
            try:
                observation = endpoint.request({"op": "observe"})
                assert observation is not None
                commands = observation["upstream_commands"]
                assert isinstance(commands, dict)
                owner_streams = commands["aggregate:requested"]
            finally:
                endpoint.close()
        finish.wait(30)
        observations = tuple(future.result() for future in futures)
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
            "measured_cpu_seconds": sum(
                observation.measured_cpu_seconds for observation in observations
            )
            + owner_cpu
            - owner_cpu_before,
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
        }


def _seed(
    client: MongoClient[BsonDict], arguments: argparse.Namespace, workload: str
) -> None:
    client.drop_database("public_shared_cache")
    client.public_shared_cache.items.insert_many(
        {
            "_id": identity * arguments.result_documents + ordinal,
            "group": identity,
            "ordinal": ordinal,
            "payload": f"{ordinal}:" + "x" * arguments.document_bytes,
        }
        for identity in range(arguments.hot_keys + _WORKERS * arguments.samples)
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
    if (
        arguments.method == "estimated_document_count"
        and "cold" in arguments.workloads
        and arguments.samples > 255
    ):
        parser.error(
            "cold estimated counts require samples <= 255 to fit 1,024 namespace slots"
        )
    windows: list[dict[str, object]] = []
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica,
        MongoClient[BsonDict](replica.uri) as client,
    ):
        for repetition in range(arguments.repetitions):
            for model in arguments.models:
                for workload in arguments.workloads:
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
                                    profile_directory=None
                                    if arguments.profile_dir is None
                                    else arguments.profile_dir / str(repetition),
                                ),
                            }
                        )
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
                "windows": windows,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

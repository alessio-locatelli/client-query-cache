"""Measure the installed public shared API against direct and process-local reads."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import multiprocessing
import os
import platform
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
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


def _install_barriers(start: Barrier, finish: Barrier) -> None:
    global _START, _FINISH
    _START, _FINISH = start, finish


def _collect(
    latencies: list[NonNegativeFloat],
    hits: NonNegativeInt,
    started: NonNegativeFloat,
    measured_cpu_started: NonNegativeFloat,
    streams: NonNegativeInt,
) -> Observation:
    observation = Observation(
        latencies,
        time.process_time() - started,
        psutil.Process().memory_full_info().pss,
        hits,
        time.process_time() - measured_cpu_started,
        streams,
    )
    _FINISH.wait(30)
    _FINISH.wait(30)
    return observation


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
        offset % _HOT_KEYS
        if window.workload == "hot"
        else _HOT_KEYS + window.worker * window.samples + offset
    )


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
        for identity in range(_HOT_KEYS):
            assert view.find_one({"_id": identity}) is not None
        if window.path == "shared":
            deadline = time.monotonic() + 10
            while manager.snapshot().hits < _HOT_KEYS:
                for identity in range(_HOT_KEYS):
                    assert view.find_one({"_id": identity}) is not None
                if time.monotonic() > deadline:
                    raise TimeoutError("shared warmup did not reach local hits")
                time.sleep(0.02)
        _START.wait(30)
        _START.wait(30)
        measured_cpu_started = time.process_time()
        latencies: list[NonNegativeFloat] = []
        before = 0 if window.path != "shared" else manager.snapshot().hits
        with _profile(window):
            for offset in range(window.samples):
                started = time.perf_counter_ns()
                document = view.find_one({"_id": _identity(window, offset)})
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
        hits = 0 if window.path != "shared" else manager.snapshot().hits - before
        return _collect(
            latencies,
            hits,
            cpu_started,
            measured_cpu_started,
            len(independent.active_stream_cost_databases())
            if window.path == "independent"
            else 0,
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
        for identity in range(_HOT_KEYS):
            assert await view.find_one({"_id": identity}) is not None
        if window.path == "shared":
            deadline = time.monotonic() + 10
            while manager.snapshot().hits < _HOT_KEYS:
                for identity in range(_HOT_KEYS):
                    assert await view.find_one({"_id": identity}) is not None
                if time.monotonic() > deadline:
                    raise TimeoutError("shared warmup did not reach local hits")
                await asyncio.sleep(0.02)
        _START.wait(30)
        _START.wait(30)
        measured_cpu_started = time.process_time()
        latencies: list[NonNegativeFloat] = []
        before = 0 if window.path != "shared" else manager.snapshot().hits
        with _profile(window):
            for offset in range(window.samples):
                started = time.perf_counter_ns()
                document = await view.find_one({"_id": _identity(window, offset)})
                latencies.append((time.perf_counter_ns() - started) / 1000)
                assert document is not None
        hits = 0 if window.path != "shared" else manager.snapshot().hits - before
        return _collect(
            latencies,
            hits,
            cpu_started,
            measured_cpu_started,
            len(independent.active_stream_cost_databases())
            if window.path == "independent"
            else 0,
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
        start.wait(30)
        finish.wait(30)
        owner_pss = 0
        owner_cpu = 0.0
        if owner is not None:
            owner_pss = owner.memory_full_info().pss
            owner_cpu = sum(owner.cpu_times()[:2])
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
            "model": model,
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
            "streams": owner_streams
            + sum(observation.streams for observation in observations),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--repetitions", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.samples <= 0 or arguments.repetitions <= 0:
        parser.error("samples and repetitions must be positive")
    windows: list[dict[str, object]] = []
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica,
        MongoClient[BsonDict](replica.uri) as client,
    ):
        for repetition in range(arguments.repetitions):
            for model in ("sync", "async"):
                for workload in ("hot", "cold"):
                    paths: tuple[Literal["direct", "independent", "shared"], ...] = (
                        "direct",
                        "independent",
                        "shared",
                    )
                    rotation = repetition % len(paths)
                    for path in paths[rotation:] + paths[:rotation]:
                        client.drop_database("public_shared_cache")
                        client.public_shared_cache.items.insert_many(
                            {"_id": identity, "payload": "x" * _DOCUMENT_BYTES}
                            for identity in range(
                                _HOT_KEYS + _WORKERS * arguments.samples
                            )
                        )
                        windows.append(
                            {
                                "repetition": repetition,
                                **_run_window(
                                    replica,
                                    model,
                                    workload,
                                    path,
                                    arguments.samples,
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
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpus": os.cpu_count(),
                "samples_per_worker": arguments.samples,
                "workers": _WORKERS,
                "document_bytes": _DOCUMENT_BYTES,
                "windows": windows,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

"""Targeted real-read admission study; raw observations remain outside Git."""

# ruff: noqa: PLC2701, SLF001 - Observe transport counters and inject bounded queue faults.
from __future__ import annotations

import argparse
import json
import multiprocessing
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from pymongo import MongoClient
from pymongo.read_concern import ReadConcern

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import (
    SharedCacheConfig,
    SharedCacheManager,
    SharedCacheServer,
    _shared_index,
)
from client_query_cache._shared import adapters, attachment
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

if TYPE_CHECKING:
    from multiprocessing.synchronize import Barrier

    from client_query_cache.shared import SharedCacheConnection

_BARRIER: Barrier
_WORKERS = 8
_CONCURRENCY = 4
_KEYS = 256


def install(barrier: Barrier) -> None:
    global _BARRIER  # noqa: PLW0603 - Spawn initializer installs one shared barrier.
    _BARRIER = barrier


def worker(
    uri: str, connection: SharedCacheConnection, index: NonNegativeInt, mode: str
) -> list[dict[str, object]]:
    observations = []
    with (
        MongoClient[BsonDict](uri) as client,
        SharedCacheManager(client, connection) as manager,
    ):
        view = manager.get_cached_collection(
            client.admission_study.items.with_options(
                read_concern=ReadConcern("majority")
            )
        )
        deadline = time.monotonic() + 15
        while manager.snapshot().hits == 0:
            assert view.find_one({"_id": -1}) == {"_id": -1}
            if time.monotonic() > deadline:
                raise TimeoutError("stream and warm entry did not become ready")
            time.sleep(0.02)
        # Metadata is ready. Exercise the no-data-socket case explicitly.
        manager.endpoint._drop()
        # Detachment deliberately starts the endpoint reconnect cooldown.
        time.sleep(0.1)

        def connect() -> None:
            if mode == "connected":
                assert manager.endpoint.request({"op": "observe"}) is not None

        ready = threading.Barrier(_CONCURRENCY)

        def prewarm(_index: NonNegativeInt) -> bool:
            ready.wait(15)
            return manager.endpoint.connected

        with ThreadPoolExecutor(
            max_workers=_CONCURRENCY, initializer=connect
        ) as threads:
            connected_threads = sum(threads.map(prewarm, range(_CONCURRENCY)))
            assert connected_threads == (_CONCURRENCY if mode == "connected" else 0)
            for phase in ("cold", "revisit", "recovery"):
                _BARRIER.wait(30)
                _BARRIER.wait(30)
                before = manager.snapshot()
                counters = asdict(manager.endpoint.counters)
                started = time.monotonic()

                def read(offset: NonNegativeInt) -> NonNegativeFloat:
                    identity = index * _KEYS + offset
                    start = time.perf_counter_ns()
                    document = view.find_one({"_id": identity})
                    latency = (time.perf_counter_ns() - start) / 1000
                    assert document is not None
                    assert document["_id"] == identity
                    assert document["revision"] == 0
                    return latency

                latencies = tuple(threads.map(read, range(_KEYS)))
                after = manager.snapshot()
                sent = manager.endpoint.counters.one_way - counters["one_way"]
                dropped = (
                    manager.endpoint.counters.dropped_one_way
                    - counters["dropped_one_way"]
                )
                assert sent + dropped == after.misses - before.misses
                assert (
                    after.hits
                    + after.misses
                    + after.bypasses
                    - before.hits
                    - before.misses
                    - before.bypasses
                    == _KEYS
                )
                observations.append(
                    {
                        "phase": phase,
                        "elapsed_seconds": time.monotonic() - started,
                        "latencies_us": latencies,
                        "hits": after.hits - before.hits,
                        "misses": after.misses - before.misses,
                        "bypasses": after.bypasses - before.bypasses,
                        "endpoint": {
                            name: value - counters[name]
                            for name, value in asdict(manager.endpoint.counters).items()
                        },
                        "connected_threads": connected_threads,
                    }
                )
                _BARRIER.wait(30)
        _BARRIER.wait(30)
        # Parent updates every measured document after all queued admissions drain.
        deadline = time.monotonic() + 10
        while True:
            documents = tuple(
                view.find_one({"_id": index * _KEYS + offset})
                for offset in range(_KEYS)
            )
            if all(
                document is not None and document["revision"] == 1
                for document in documents
            ):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("updated documents remained stale")
            time.sleep(0.02)
        _BARRIER.wait(30)
    return observations


def window(
    replica: IsolatedReplicaSet, mode: str, payload_bytes: PositiveInt
) -> dict[str, object]:
    with MongoClient[BsonDict](replica.uri) as client:
        collection = client.admission_study.items
        collection.drop()
        collection.insert_many(
            [
                {"_id": -1},
                *(
                    {"_id": key, "revision": 0, "payload": "x" * payload_bytes}
                    for key in range(_WORKERS * _KEYS)
                ),
            ]
        )
        server = SharedCacheServer(
            replica.uri,
            ("admission_study",),
            config=SharedCacheConfig(
                budget_bytes=256 * 1024 * 1024, arena_bytes=320 * 1024 * 1024
            ),
        )
        if mode == "reduced":
            server._config = replace(
                server._config,
                limits=replace(
                    server._config.limits, queued_bytes_per_connection=payload_bytes * 2
                ),
            )
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(_WORKERS + 1)
        with (
            server,
            ProcessPoolExecutor(
                max_workers=_WORKERS,
                mp_context=context,
                initializer=install,
                initargs=(barrier,),
            ) as pool,
        ):
            assert server._process is not None
            owner = psutil.Process(server._process.pid)
            futures = tuple(
                pool.submit(worker, replica.uri, server.connection, index, mode)
                for index in range(_WORKERS)
            )
            phases = []
            for phase in ("cold", "revisit", "recovery"):
                barrier.wait(30)
                cpu = sum(owner.cpu_times()[:2])
                suspended = mode == "paused" and phase == "cold"
                if suspended:
                    owner.suspend()
                started = time.monotonic()
                try:
                    barrier.wait(30)
                    barrier.wait(30)
                finally:
                    if suspended:
                        owner.resume()
                phases.append(
                    {
                        "phase": phase,
                        "elapsed_seconds": time.monotonic() - started,
                        "owner_cpu_seconds": sum(owner.cpu_times()[:2]) - cpu,
                    }
                )
                # Explicit settling interval; include deferred owner work separately.
                cpu = sum(owner.cpu_times()[:2])
                time.sleep(0.5)
                phases[-1]["settle_owner_cpu_seconds"] = (
                    sum(owner.cpu_times()[:2]) - cpu
                )
            collection.update_many({"_id": {"$gte": 0}}, {"$set": {"revision": 1}})
            barrier.wait(30)
            barrier.wait(30)
            workers = tuple(future.result(timeout=30) for future in futures)
        for ordinal, summary in enumerate(phases):
            samples = tuple(observations[ordinal] for observations in workers)
            latencies = sorted(
                latency for sample in samples for latency in sample["latencies_us"]
            )
            summary.update(
                {
                    "hits": sum(sample["hits"] for sample in samples),
                    "misses": sum(sample["misses"] for sample in samples),
                    "bypasses": sum(sample["bypasses"] for sample in samples),
                    "endpoint": {
                        name: sum(sample["endpoint"][name] for sample in samples)
                        for name in samples[0]["endpoint"]
                    },
                    "median_us": statistics.median(latencies),
                    "p99_us": latencies[int(len(latencies) * 0.99)],
                    "connected_threads": sum(
                        sample["connected_threads"] for sample in samples
                    ),
                }
            )
        return {
            "mode": mode,
            "payload_bytes": payload_bytes,
            "queue_bytes": server._config.limits.queued_bytes_per_connection,
            "phases": phases,
            "workers": workers,
            "updated_documents_verified": _WORKERS * _KEYS,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.repetitions <= 0:
        parser.error("repetitions must be positive")
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to record the source revision")
    report = {
        "revision": subprocess.check_output(  # noqa: S603 - Fixed Git arguments record local provenance.
            [git, "rev-parse", "HEAD"], text=True
        ).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "logical_cpus": psutil.cpu_count(),
        "source_sha256": {
            name: sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in (
                ("adapters", adapters),
                ("attachment", attachment),
                ("native", _shared_index),
            )
        },
        "harness_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "workers": _WORKERS,
        "concurrency_per_worker": _CONCURRENCY,
        "keys_per_worker": _KEYS,
        "windows": [],
    }
    with (
        arguments.output.open("x") as output,
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as replica,
    ):
        for repetition in range(arguments.repetitions):
            modes = ("default", "connected", "reduced", "paused")
            for payload in (4096, 65536):
                for mode in (
                    modes[repetition % len(modes) :] + modes[: repetition % len(modes)]
                ):
                    report["windows"].append(
                        {"repetition": repetition, **window(replica, mode, payload)}
                    )
                    output.seek(0)
                    json.dump(report, output, indent=2)
                    output.truncate()
                    output.flush()


if __name__ == "__main__":
    main()

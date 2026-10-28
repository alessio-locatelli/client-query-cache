"""Measure readers sharing one manager while an outside client writes."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import resource
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from operator import itemgetter
from pathlib import Path
from threading import Barrier
from typing import TYPE_CHECKING

import psutil
from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from benchmarks.public_shared_cache import (
    ReadCommands,
    _implementation,  # noqa: PLC2701 - Reuse the existing provenance collector.
    _seed,  # noqa: PLC2701 - Reuse the registered workload builder.
)
from benchmarks.stream_cost.multiprocess_run import command_delta
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import CacheCoreConfig, CacheManager
from client_query_cache._core.stream_cost import LagCaptureWindowConfig  # noqa: PLC2701 - Capture every measured invalidation's actual application timestamp.
from client_query_cache._types import (  # noqa: PLC2701 - Use the library constraint aliases in acquisition records.
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

_KEYS = 1024
_PAYLOAD = "0:" + "x" * 4096
_RATE = 4000
_READS = 80_000
_WRITES = 1000
_WRITE_INTERVAL = 0.02


@dataclass(frozen=True, slots=True)
class ReaderObservation:
    manager: PositiveInt
    core: PositiveInt
    client: PositiveInt
    latencies_us: list[NonNegativeFloat]
    intervals: list[tuple[NonNegativeFloat, NonNegativeFloat]]
    lateness_seconds: list[NonNegativeFloat]
    started: NonNegativeFloat
    ended: NonNegativeFloat


def _memory() -> dict[str, NonNegativeInt]:
    info = psutil.Process().memory_full_info()
    return {"rss": info.rss, "uss": info.uss, "pss": info.pss}


def _thread_worker(
    control: Connection, uri: str, threads: PositiveInt, *, native: bool
) -> dict[str, object]:
    commands = ReadCommands(())
    with (
        MongoClient[BsonDict](uri, event_listeners=[commands]) as client,
        CacheManager(
            client,
            cache_config=CacheCoreConfig(
                lag_capture_window_config=LagCaptureWindowConfig(4096, 1, 0)
            ),
        ) as manager,
        ThreadPoolExecutor(max_workers=threads) as pool,
    ):
        provenance = _implementation(manager)
        assert all(
            Path(provenance[field]).is_relative_to(sys.prefix)
            for field in ("library", "extension")
        )
        assert provenance["core"] == (
            "client_query_cache._shared_index.LocalCacheCore"
            if native
            else "client_query_cache._core.manager.CacheCore"
        )
        assert manager._coordinator._cache is manager.cache_core  # noqa: SLF001 - Prove that the stream and all readers use this same core.
        view = manager.get_cached_collection(
            client.public_shared_cache.items.with_options(
                read_concern=ReadConcern("majority")
            )
        )
        deadline = time.monotonic() + 30
        while True:
            before = manager.snapshot()
            for identity in range(_KEYS):
                assert view.find_one({"_id": identity}) == {
                    "_id": identity,
                    "group": identity,
                    "ordinal": 0,
                    "payload": _PAYLOAD,
                }
            after = manager.snapshot()
            if after.hits - before.hits == _KEYS:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("contention catalogue did not become fully resident")
        assert after.entry_count == _KEYS
        manager.cache_core.reset_stream_cost_statistics()
        gate = Barrier(threads + 1)

        def read(share: NonNegativeInt) -> ReaderObservation:
            gate.wait(30)
            latencies = []
            intervals = []
            lateness = []
            first_started = 0.0
            for offered in range(share, _READS, threads):
                due = start_at + offered / _RATE
                time.sleep(max(0, due - time.monotonic()))
                started = time.monotonic()
                if not first_started:
                    first_started = started
                value = view.find_one({"_id": offered % _KEYS})
                ended = time.monotonic()
                intervals.append((started, ended))
                latencies.append((ended - started) * 1e6)
                lateness.append(max(0, started - due))
                assert value is not None
                revision = value.pop("revision", 0)
                assert isinstance(revision, int)
                assert revision >= 0
                identity = offered % _KEYS
                assert value == {
                    "_id": identity,
                    "group": identity,
                    "ordinal": 0,
                    "payload": _PAYLOAD,
                }
            return ReaderObservation(
                id(manager),
                id(manager.cache_core),
                id(client),
                latencies,
                intervals,
                lateness,
                first_started,
                time.monotonic(),
            )

        control.send("ready")
        start_at = control.recv()
        assert isinstance(start_at, float)
        tasks = [pool.submit(read, share) for share in range(threads)]
        before = manager.snapshot()
        # Capture counters and residency before the scheduled read interval.
        origin_before = commands.snapshot()
        # Retain the pre-interval resource reading for comparison after drain.
        memory_before = _memory()
        time.sleep(max(0, start_at - time.monotonic()))
        cpu_started = time.process_time()
        gate.wait(30)
        observations = [task.result(timeout=60) for task in tasks]
        cpu_ended = time.process_time()
        read_ended = time.monotonic()
        after = manager.snapshot()
        origin = command_delta(origin_before, commands.snapshot())
        writes = control.recv()
        assert isinstance(writes, list)
        assert len(writes) == _WRITES
        drain_deadline = read_ended + 30
        while True:
            stream = manager.stream_cost_snapshot("public_shared_cache")
            if stream.invalidations == _WRITES:
                break
            if time.monotonic() >= drain_deadline:
                raise TimeoutError("contention invalidations did not drain within 30s")
            time.sleep(0.01)
        drain_ended = time.monotonic()
        drain_cpu = time.process_time() - cpu_ended
        readings = [asdict(reading) for reading in stream.invalidation_apply_readings]
        assert len(readings) == len(stream.invalidation_lag_windows) == _WRITES
        starts = [observation.started for observation in observations]
        ends = [observation.ended for observation in observations]
        interval_start, interval_end = min(starts), max(ends)
        intervals = sorted(
            interval
            for observation in observations
            for interval in observation.intervals
        )
        position = 0
        active_until = 0.0
        overlap = 0
        for reading in sorted(readings, key=itemgetter("monotonic_seconds")):
            applied_at = reading["monotonic_seconds"]
            while position < len(intervals) and intervals[position][0] <= applied_at:
                active_until = max(active_until, intervals[position][1])
                position += 1
            overlap += applied_at < active_until
        assert overlap > 0
        assert all(
            (observation.manager, observation.core, observation.client)
            == (id(manager), id(manager.cache_core), id(client))
            for observation in observations
        )
        counts = {
            name: getattr(after, name) - getattr(before, name)
            for name in ("hits", "misses", "bypasses")
        }
        assert sum(counts.values()) == _READS
        assert counts["bypasses"] == 0
        assert origin["find:requested"] == counts["misses"]
        assert manager.active_stream_cost_databases() == ["public_shared_cache"]
        latencies = sorted(
            latency
            for observation in observations
            for latency in observation.latencies_us
        )
        assert len(latencies) == _READS
        return {
            "threads": threads,
            "offered_reads": _READS,
            "completed_reads": len(latencies),
            "offered_rate": _RATE,
            "planned_start": start_at,
            "read_started": interval_start,
            "read_ended": interval_end,
            "throughput": _READS / (interval_end - start_at),
            "cpu_seconds": cpu_ended - cpu_started,
            "cpu_clock": vars(time.get_clock_info("process_time")),
            "drain_seconds": drain_ended - read_ended,
            "drain_cpu_seconds": drain_cpu,
            "median_us": statistics.median(latencies),
            "p95_us": latencies[int(len(latencies) * 0.95)],
            "p99_us": latencies[int(len(latencies) * 0.99)],
            "memory_before": memory_before,
            "memory_after": _memory(),
            "peak_rss_bytes_including_warmup": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * 1024,
            "cache_delta": counts,
            "origin_commands": origin,
            "invalidation_overlap": overlap,
            "stream": asdict(stream),
            "writes": writes,
            "readers": [asdict(observation) for observation in observations],
            "implementation": provenance,
        }


def _write_sequence(uri: str, start_at: NonNegativeFloat) -> list[dict[str, object]]:
    with MongoClient[BsonDict](uri, timeoutMS=5000) as client:
        view = client.public_shared_cache.items.with_options(
            write_concern=WriteConcern("majority")
        )
        client.admin.command("ping")
        writes: list[dict[str, object]] = []
        for offered in range(_WRITES):
            due = start_at + offered * _WRITE_INTERVAL
            time.sleep(max(0, due - time.monotonic()))
            started = time.monotonic()
            identity = offered % _KEYS
            write_result = view.update_one({"_id": identity}, {"$inc": {"revision": 1}})
            assert write_result.matched_count == write_result.modified_count == 1
            writes.append(
                {
                    "identity": identity,
                    "due": due,
                    "started": started,
                    "acknowledged": time.monotonic(),
                    "wall_seconds": time.time(),
                }
            )
        return writes


def run_cell(
    replica: IsolatedReplicaSet, threads: PositiveInt, *, native: bool = False
) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    with (
        parent,
        child,
        ProcessPoolExecutor(max_workers=1, mp_context=context) as pool,
    ):
        future = pool.submit(_thread_worker, child, replica.uri, threads, native=native)
        assert parent.poll(60), "contention worker did not become ready"
        assert parent.recv() == "ready"
        start_at = time.monotonic() + 0.25
        parent.send(start_at)
        writes = _write_sequence(replica.uri, start_at)
        parent.send(writes)
        return future.result(timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-native", action="store_true")
    parser.add_argument(
        "--threads", type=int, nargs="+", choices=(1, 4), default=(1, 4)
    )
    arguments = parser.parse_args()
    windows = []
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica,
        MongoClient[BsonDict](replica.uri) as client,
    ):
        for threads in arguments.threads:
            _seed(
                client,
                argparse.Namespace(
                    method="identity",
                    hot_keys=_KEYS,
                    samples=1,
                    result_documents=1,
                    document_bytes=4096,
                ),
                "hot",
            )
            windows.append(run_cell(replica, threads, native=arguments.expect_native))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps({"windows": windows}, indent=2) + "\n")


if __name__ == "__main__":
    main()

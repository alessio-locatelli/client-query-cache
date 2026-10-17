"""Measure collection invalidation and replay narrower invalidation policies."""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import random
import signal
import statistics
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from functools import partial
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import psutil
from pymongo import ReadPreference
from pymongo.monitoring import CommandListener
from pymongo.read_concern import ReadConcern

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.measurement import (
    measure_controlled,
    scalar_latency_distribution,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import CacheManager
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )
    from pymongo.synchronous.collection import Collection

    from client_query_cache.synchronous.collection import CachedCollection

CLASSES = ("feed", "count", "own", "by_id")
MIXES: tuple[Literal["insert", "update"], ...] = ("insert", "update")
POLICIES = (
    "current",
    "id_anchor",
    "insert_partition",
    "field_dependency",
    "all",
    "exact",
)
READS = 4096
WARMUP = 512
DOCUMENTS = 20_000
AUTHORS = 500
HOT_AUTHORS = 32
FEED_LIMIT = 20
TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


@dataclass(frozen=True, slots=True)
class Write:
    mix: Literal["insert", "update"]
    identity: NonNegativeInt
    author: NonNegativeInt
    created: NonNegativeInt


def sequence(
    mix: Literal["insert", "update"], rate: PositiveInt, rep: NonNegativeInt
) -> dict[NonNegativeInt, Write]:
    rng = random.Random(f"{mix}-{rate}-{rep}")
    writes: dict[NonNegativeInt, Write] = {}
    for index in range(rate, READS, rate):
        identity = rng.randrange(DOCUMENTS)
        author = rng.randrange(AUTHORS) if mix == "insert" else identity % AUTHORS
        writes[index] = Write(mix, identity, author, DOCUMENTS + len(writes))
    return writes


def affected(
    write: Write, policy: str, newest: dict[NonNegativeInt, list[NonNegativeInt]]
) -> set[tuple[str, NonNegativeInt]]:
    changed = set()
    for author in range(HOT_AUTHORS):
        for kind in CLASSES:
            same_id = write.mix == "update" and write.identity == author
            if kind == "by_id" or (
                kind == "own" and policy in {"id_anchor", "all", "exact"}
            ):
                invalidate = same_id
            elif kind in {"feed", "count"} and policy == "exact":
                invalidate = write.author == author and (
                    write.mix == "insert"
                    or (kind == "feed" and write.identity in newest[author])
                )
            elif (
                kind in {"feed", "count"}
                and policy in {"insert_partition", "all"}
                and write.mix == "insert"
            ):
                invalidate = write.author == author
            else:
                invalidate = not (
                    kind == "count"
                    and policy in {"field_dependency", "all"}
                    and write.mix == "update"
                )
            if invalidate:
                changed.add((kind, author))
    return changed


def newest_documents() -> dict[NonNegativeInt, list[NonNegativeInt]]:
    return {
        author: list(range(author, DOCUMENTS, AUTHORS))[-FEED_LIMIT:]
        for author in range(HOT_AUTHORS)
    }


def advance_feed(
    write: Write, newest: dict[NonNegativeInt, list[NonNegativeInt]]
) -> None:
    if write.mix == "insert" and write.author < HOT_AUTHORS:
        newest[write.author] = [*newest[write.author][1:], write.created]


def read_key(index: NonNegativeInt) -> tuple[str, NonNegativeInt]:
    return CLASSES[index % len(CLASSES)], (index // len(CLASSES)) % HOT_AUTHORS


def simulate() -> None:
    for mix, rate in product(MIXES, (100, 10)):
        schedules = tuple(sequence(mix, rate, rep) for rep in range(3))
        for policy in POLICIES:
            totals = dict.fromkeys(CLASSES, 0)
            for writes in schedules:
                valid = {read_key(index) for index in range(WARMUP)}
                newest = newest_documents()
                for index in range(READS):
                    if index in writes:
                        write = writes[index]
                        valid.difference_update(affected(write, policy, newest))
                        advance_feed(write, newest)
                    key = read_key(index)
                    totals[key[0]] += key in valid
                    valid.add(key)
            print(
                json.dumps(
                    {
                        "mix": mix,
                        "reads_per_write": rate,
                        "policy": policy,
                        "hit_share": {
                            kind: count / (3 * READS / 4)
                            for kind, count in totals.items()
                        },
                        "overall": sum(totals.values()) / (3 * READS),
                    }
                )
            )


class ReadCommands(CommandListener):
    def __init__(self) -> None:
        self.active: str | None = None
        self.counts = dict.fromkeys(CLASSES, 0)

    def started(self, event: CommandStartedEvent) -> None:
        if (
            self.active is not None
            and event.database_name == "bench"
            and event.command_name in {"find", "aggregate"}
            and event.command[event.command_name] == "target"
        ):
            self.counts[self.active] += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


def seed(collection: Collection[BsonDict]) -> None:
    collection.drop()
    collection.insert_many(
        [
            {
                "_id": index,
                "author_id": index % AUTHORS,
                "created": index,
                "views": 0,
                "body": "x" * 512,
            }
            for index in range(DOCUMENTS)
        ]
    )
    collection.create_index([("author_id", 1), ("created", -1)])


def operations(
    view: Collection[BsonDict] | CachedCollection[BsonDict],
) -> dict[tuple[str, NonNegativeInt], Callable[[], object]]:
    return {
        (kind, author): operation
        for author in range(HOT_AUTHORS)
        for kind, operation in (
            (
                "feed",
                lambda author=author: list(
                    view.find({"author_id": author})
                    .sort("created", -1)
                    .limit(FEED_LIMIT)
                ),
            ),
            (
                "count",
                lambda author=author: view.count_documents({"author_id": author}),
            ),
            (
                "own",
                lambda author=author: view.find_one(
                    {"_id": author, "author_id": author}
                ),
            ),
            ("by_id", lambda author=author: view.find_one({"_id": author})),
        )
    }


def apply_write(collection: Collection[BsonDict], write: Write) -> None:
    if write.mix == "insert":
        collection.insert_one(
            {
                "author_id": write.author,
                "created": write.created,
                "views": 0,
                "body": "x" * 512,
            }
        )
    else:
        collection.update_one({"_id": write.identity}, {"$inc": {"views": 1}})


def await_warm(
    manager: CacheManager[BsonDict], operation: Callable[[], object]
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        before = manager.snapshot().hits
        operation()
        if manager.snapshot().hits > before:
            return
        time.sleep(0.01)
    raise RuntimeError("Cache did not become warm within 30 seconds")


def exposure(
    writes: dict[NonNegativeInt, Write],
    starts: list[NonNegativeFloat],
    returned: list[NonNegativeFloat],
    applied: tuple[NonNegativeFloat, ...],
) -> dict[str, NonNegativeFloat]:
    exposed: set[NonNegativeInt] = set()
    newest = newest_documents()
    for ordinal, write in enumerate(writes.values()):
        changed = affected(write, "exact", newest)
        advance_feed(write, newest)
        for index, started in enumerate(starts):
            if (
                returned[ordinal] < started < applied[ordinal]
                and read_key(index) in changed
            ):
                exposed.add(index)
    return {
        kind: sum(CLASSES[index % 4] == kind for index in exposed) / (READS / 4)
        for kind in CLASSES
    }


def run_cell(
    replica: IsolatedReplicaSet,
    path: str,
    mix: Literal["insert", "update"],
    rate: PositiveInt,
    rep: NonNegativeInt,
) -> dict[str, object]:
    listener = ReadCommands()
    with ExitStack() as stack:
        client = stack.enter_context(
            replica.build_client(TOPOLOGY, event_listeners=(listener,))
        )
        target, sibling = client.bench.target, client.bench.sibling
        seed(target)
        seed(sibling)
        manager = (
            None if path == "direct" else stack.enter_context(CacheManager(client))
        )
        view = (
            target.with_options(
                read_preference=ReadPreference.PRIMARY,
                read_concern=ReadConcern("majority"),
            )
            if manager is None
            else manager["bench"]["target"]
        )
        calls = operations(view)
        if manager is not None:
            await_warm(manager, calls["by_id", 0])
        for index in range(WARMUP):
            calls[read_key(index)]()
        writes = sequence(mix, rate, rep)
        starts = [0.0] * READS
        durations = [0.0] * READS
        returned = [0.0] * len(writes)
        cache_before = manager.snapshot() if manager else None
        stream_before = manager.stream_cost_snapshot("bench") if manager else None
        writer = sibling if path == "ideal" else target

        def measured() -> None:
            ordinal = 0
            for index in range(READS):
                if index in writes:
                    apply_write(writer, writes[index])
                    returned[ordinal] = time.monotonic()
                    ordinal += 1
                kind, author = read_key(index)
                listener.active = kind
                starts[index] = time.monotonic()
                calls[kind, author]()
                durations[index] = time.monotonic() - starts[index]
                listener.active = None

        _, timing = measure_controlled(measured, replica_set=replica)
        summary: dict[str, object] = {
            "path": path,
            "mix": mix,
            "reads_per_write": rate,
            "rep": rep,
            "reads_per_second": READS / timing.wall_seconds,
            "timing": asdict(timing),
            "rss_bytes": psutil.Process().memory_info().rss,
            "latency": {
                kind: scalar_latency_distribution(durations[offset::4])
                for offset, kind in enumerate(CLASSES)
            },
            "hit_share": {
                kind: 1 - count / (READS / 4) for kind, count in listener.counts.items()
            }
            if manager
            else None,
        }
        if manager is not None:
            assert cache_before is not None
            assert stream_before is not None
            deadline = time.monotonic() + 30
            while True:
                stream_after = manager.stream_cost_snapshot("bench")
                if (
                    path != "cache"
                    or stream_after.invalidations - stream_before.invalidations
                    == len(writes)
                ):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Stream did not apply exactly the cell's writes "
                        "within 30 seconds"
                    )
                time.sleep(0.01)
            cache_after = manager.snapshot()
            driver_reads = sum(listener.counts.values())
            if driver_reads != (
                cache_after.misses
                - cache_before.misses
                + cache_after.bypasses
                - cache_before.bypasses
            ):
                raise RuntimeError(
                    "Driver reads do not match cache misses and bypasses"
                )
            summary["cache_delta"] = {
                field: getattr(cache_after, field) - getattr(cache_before, field)
                for field in ("hits", "misses", "bypasses", "used_bytes", "entry_count")
            }
            summary["stream_delta"] = {
                field: getattr(stream_after, field) - getattr(stream_before, field)
                for field in ("invalidations", "logical_event_bytes")
            }
            if path == "cache":
                readings = stream_after.invalidation_apply_readings[
                    len(stream_before.invalidation_apply_readings) :
                ]
                if len(readings) != len(writes):
                    raise RuntimeError("Incomplete invalidation apply timestamps")
                summary["exposed_read_share"] = exposure(
                    writes,
                    starts,
                    returned,
                    tuple(reading.monotonic_seconds for reading in readings),
                )
        return summary


def run(reps: PositiveInt) -> list[dict[str, object]]:
    cells = []
    with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as replica:
        for rep in range(reps):
            for mix in MIXES:
                for rate in (100, 10):
                    for path in (
                        ("direct", "cache", "ideal")
                        if rep % 2 == 0
                        else ("ideal", "cache", "direct")
                    ):
                        cells.append(run_cell(replica, path, mix, rate, rep))
                        print(f"Completed {path} {mix} 1/{rate} rep {rep}", flush=True)
    return cells


def micro() -> dict[str, NonNegativeFloat]:
    medians = {}
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as replica,
        replica.build_client(TOPOLOGY) as client,
    ):
        seed(client.bench.target)
        with CacheManager(client) as manager:
            view = manager["bench"]["target"]
            filters = {
                "by_id": {"_id": 0},
                "own": {"_id": 0, "author_id": 0},
                "generic": {"author_id": 0},
            }
            for kind, query in filters.items():
                await_warm(manager, partial(view.find_one, query))
                batches = []
                for _ in range(5):
                    start = time.perf_counter()
                    for _ in range(20_000):
                        view.find_one(query)
                    batches.append((time.perf_counter() - start) * 1_000_000 / 20_000)
                medians[kind] = statistics.median(batches)
    return medians


def find_cost(reps: PositiveInt) -> dict[str, object]:
    cells = []
    listener = ReadCommands()
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as replica,
        replica.build_client(TOPOLOGY, event_listeners=(listener,)) as client,
        CacheManager(client) as manager,
    ):
        seed(client.bench.target)
        view = manager["bench"]["target"]
        direct = client.bench.target.with_options(
            read_preference=ReadPreference.PRIMARY,
            read_concern=ReadConcern("majority"),
        )
        namespace = view._namespace()  # noqa: SLF001 - Isolate namespace-guard misses without resetting collection metadata.
        core = manager.cache_core
        await_warm(manager, lambda: view.find_one({"_id": 0}))

        def feed(
            author: NonNegativeInt, *, limit: PositiveInt = FEED_LIMIT
        ) -> list[BsonDict]:
            return list(
                view.find({"author_id": author}).sort("created", -1).limit(limit)
            )

        expected = [
            list(
                direct.find({"author_id": author}).sort("created", -1).limit(FEED_LIMIT)
            )
            for author in range(HOT_AUTHORS)
        ]
        for rep in range(reps):
            phases = ("direct", "cold", "exact", "compatible")
            for phase in reversed(phases) if rep % 2 else phases:
                core.clear_namespace(namespace)
                if phase in {"exact", "compatible"}:
                    for author in range(HOT_AUTHORS):
                        feed(author, limit=40 if phase == "compatible" else FEED_LIMIT)
                listener.counts = dict.fromkeys(CLASSES, 0)
                listener.active = "feed"
                before = core.snapshot()
                wall_seconds = cpu_seconds = 0.0
                repetitions = 1024 if phase in {"direct", "cold"} else 4096
                for index in range(repetitions):
                    author = index % HOT_AUTHORS
                    if phase == "cold":
                        core.record_write(namespace, index)
                    cpu_started = time.process_time()
                    wall_started = time.perf_counter()
                    if phase == "direct":
                        documents = list(
                            direct.find({"author_id": author})
                            .sort("created", -1)
                            .limit(FEED_LIMIT)
                        )
                    else:
                        documents = feed(author)
                    wall_seconds += time.perf_counter() - wall_started
                    cpu_seconds += time.process_time() - cpu_started
                    assert documents == expected[author]
                listener.active = None
                after = core.snapshot()
                driver_reads = sum(listener.counts.values())
                assert driver_reads == (
                    repetitions if phase in {"direct", "cold"} else 0
                )
                assert after.misses - before.misses == (
                    repetitions if phase == "cold" else 0
                )
                assert after.hits - before.hits == (
                    repetitions if phase in {"exact", "compatible"} else 0
                )
                cells.append(
                    {
                        "rep": rep,
                        "phase": phase,
                        "repetitions": repetitions,
                        "wall_us": wall_seconds * 1e6 / repetitions,
                        "cpu_us": cpu_seconds * 1e6 / repetitions,
                        "driver_reads": driver_reads,
                    }
                )
        profiler = cProfile.Profile()
        for index in range(128):
            core.record_write(namespace, index)
            with profiler:
                feed(index % HOT_AUTHORS)
        profile_output = io.StringIO()
        pstats.Stats(profiler, stream=profile_output).strip_dirs().sort_stats(
            "cumulative"
        ).print_stats(35)
        return {"cells": cells, "cold_profile": profile_output.getvalue()}


def main() -> None:
    signal.alarm(3600)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("simulate")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--reps", type=int, default=3)
    run_parser.add_argument("--out", type=Path, required=True)
    micro_parser = commands.add_parser("micro")
    micro_parser.add_argument("--out", type=Path, required=True)
    cost_parser = commands.add_parser("find-cost")
    cost_parser.add_argument("--reps", type=int, default=5)
    cost_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "simulate":
        simulate()
    else:
        if args.command in {"run", "find-cost"} and args.reps <= 0:
            parser.error("--reps must be positive")
        summary: object
        if args.command == "find-cost":
            summary = find_cost(args.reps)
        else:
            summary = run(args.reps) if args.command == "run" else micro()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()

"""Measure read retention and costs of the production manager under write churn."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import shutil
import subprocess
import threading
import time
from contextlib import ExitStack
from dataclasses import asdict
from functools import partial
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch
from urllib.parse import urlparse

import bson
import pymongo
from pymongo import ReadPreference
from pymongo.monitoring import CommandListener
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from benchmarks.mongodb_image import MONGODB_IMAGE
from benchmarks.stream_cost.client import build_dedicated_client
from benchmarks.stream_cost.measurement import (
    measure_controlled,
    scalar_latency_distribution,
)
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import CacheCoreConfig, CacheManager
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)
from client_query_cache.synchronous import manager as manager_module
from client_query_cache.synchronous import streams as stream_module
from client_query_cache.synchronous.streams import ChangeStreamCoordinator
from research.invalidation_scope.benchmark import (
    AUTHORS,
    CLASSES,
    DOCUMENTS,
    FEED_LIMIT,
    HOT_AUTHORS,
    TOPOLOGY,
    WARMUP,
    Write,
    await_warm,
    newest_documents,
    read_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )
    from pymongo.synchronous.collection import Collection
    from pymongo.synchronous.database import Database

    from client_query_cache._core.contracts import LocalCacheCore
    from client_query_cache._core.namespace_metadata import NamespaceMetadataCache
    from client_query_cache.synchronous.collection import CachedCollection

PathKind = Literal["direct", "current", "production"]
Policy = Literal["disabled", "insert", "counts", "both"]
ReadKind = Literal["feed", "count", "own", "by_id", "prefix"]
Mix = Literal["insert", "update", "mixed"]
Scenario = Literal["cached", "uncached", "unrelated"]
READ_KINDS: tuple[ReadKind, ...] = ("feed", "count", "own", "by_id")
PATHS: tuple[PathKind, ...] = ("direct", "current")
WRITE_OPERATIONS = frozenset({"insert", "update", "replace", "delete"})
MAJORITY = ReadConcern("majority")
SEED = 257


class ReadCommands(CommandListener):
    def __init__(self) -> None:
        self.active: ReadKind | None = None
        self.counts = dict.fromkeys(READ_KINDS, 0)

    def started(self, event: CommandStartedEvent) -> None:
        if self.active is not None and event.command_name in {"find", "aggregate"}:
            self.counts[self.active] += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


class RoutingObserver:
    __slots__ = ("applied", "condition", "route_cpu_ns")

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.applied: list[NonNegativeFloat] = []
        self.route_cpu_ns = 0

    def install(self, stack: ExitStack) -> None:
        stack.enter_context(
            patch.object(stream_module, "route_change_event", self.route)
        )

    def reset(self) -> None:
        with self.condition:
            self.applied.clear()
            self.route_cpu_ns = 0

    def drain(self, count: NonNegativeInt) -> None:
        with self.condition:
            complete = self.condition.wait_for(lambda: len(self.applied) >= count, 30)
            if not complete or len(self.applied) != count:
                raise RuntimeError("stream did not apply the scheduled writes exactly")

    def route(
        self,
        cache: LocalCacheCore,
        database: str,
        event: Mapping[str, object],
        *,
        metadata_cache: NamespaceMetadataCache[object] | None = None,
    ) -> bool:
        started = time.thread_time_ns()
        reopen = route_change_event(
            cache, database, event, metadata_cache=metadata_cache
        )
        if event["operationType"] in WRITE_OPERATIONS:
            elapsed = time.thread_time_ns() - started
            with self.condition:
                self.route_cpu_ns += elapsed
                self.applied.append(time.monotonic())
                self.condition.notify_all()
        return reopen


def document(identity: NonNegativeInt, author: NonNegativeInt, body: str) -> BsonDict:
    return {
        "_id": identity,
        "author_id": author,
        "created": identity,
        "views": 0,
        "body": body,
    }


def seed(database: Database[BsonDict], size: PositiveInt) -> str:
    padding = size - len(bson.encode(document(0, 0, "")))
    assert padding >= 0
    body = "x" * padding
    for name in ("target", "sibling", "other"):
        collection = database[name]
        collection.drop()
        collection.insert_many(
            [
                document(identity, identity % AUTHORS, body)
                for identity in range(DOCUMENTS)
            ]
        )
        collection.create_index([("author_id", 1), ("created", -1)])
    return body


def restore(
    collection: Collection[BsonDict],
    mix: Mix,
    scheduled: dict[NonNegativeInt, Write],
) -> None:
    if mix in {"insert", "mixed"}:
        collection.delete_many({"_id": {"$gte": DOCUMENTS}})
    if mix in {"update", "mixed"}:
        identities = tuple(
            dict.fromkeys(write.identity for write in scheduled.values())
        )
        collection.update_many({"_id": {"$in": identities}}, {"$set": {"views": 0}})


def feed(
    view: Collection[BsonDict] | CachedCollection[BsonDict],
    query: BsonDict,
    *,
    limit: PositiveInt = FEED_LIMIT,
) -> list[BsonDict]:
    return list(view.find(query).sort("created", -1).limit(limit))


def operations(
    manager: CacheManager[BsonDict] | None, raw: Collection[BsonDict]
) -> dict[tuple[str, NonNegativeInt], Callable[[], object]]:
    calls: dict[tuple[str, NonNegativeInt], Callable[[], object]] = {}
    original = None if manager is None else manager.get_cached_collection(raw)
    for author, kind in product(range(HOT_AUTHORS), READ_KINDS):
        view = raw if original is None else original
        if kind == "feed":
            calls[kind, author] = partial(feed, view, {"author_id": author})
        elif kind == "count":
            calls[kind, author] = partial(view.count_documents, {"author_id": author})
        elif kind == "own":
            calls[kind, author] = partial(
                view.find_one, {"_id": author, "author_id": author}
            )
        else:
            calls[kind, author] = partial(view.find_one, {"_id": author})
    return calls


class Oracle:
    __slots__ = ("body", "counts", "last_changed", "newest", "views")

    def __init__(self, body: str) -> None:
        self.body = body
        self.newest = {
            author: list(reversed(identities))
            for author, identities in newest_documents().items()
        }
        self.counts = dict.fromkeys(range(HOT_AUTHORS), DOCUMENTS // AUTHORS)
        self.views: dict[NonNegativeInt, NonNegativeInt] = {}
        self.last_changed: dict[tuple[str, NonNegativeInt], NonNegativeInt] = {}

    def write(self, write: Write, ordinal: NonNegativeInt) -> None:
        if write.mix == "insert":
            if write.author < HOT_AUTHORS:
                self.counts[write.author] += 1
                self.newest[write.author].insert(0, write.created)
                del self.newest[write.author][FEED_LIMIT:]
                for kind in ("feed", "count"):
                    self.last_changed[kind, write.author] = ordinal
        else:
            try:
                self.views[write.identity] += 1
            except KeyError:
                self.views[write.identity] = 1
            author = write.identity % AUTHORS
            if author < HOT_AUTHORS and write.identity in self.newest[author]:
                self.last_changed["feed", author] = ordinal
            if write.identity < HOT_AUTHORS:
                for kind in ("own", "by_id"):
                    self.last_changed[kind, write.identity] = ordinal

    def expected(self, key: tuple[str, NonNegativeInt]) -> object:
        kind, author = key
        if kind == "count":
            return self.counts[author]
        identities = self.newest[author] if kind == "feed" else (author,)
        documents = []
        for identity in identities:
            value = document(identity, author, self.body)
            try:
                value["views"] = self.views[identity]
            except KeyError:
                pass
            documents.append(value)
        return documents if kind == "feed" else documents[0]


def apply_write(collection: Collection[BsonDict], write: Write, body: str) -> None:
    if write.mix == "insert":
        collection.insert_one(document(write.created, write.author, body))
    else:
        modified = collection.update_one(
            {"_id": write.identity}, {"$inc": {"views": 1}}
        )
        assert modified.modified_count == 1


def writes_for(
    mix: Mix, reads: PositiveInt, reads_per_write: PositiveInt, rep: NonNegativeInt
) -> dict[NonNegativeInt, Write]:
    rng = random.Random(f"{mix}-{reads_per_write}-{rep}")
    scheduled: dict[NonNegativeInt, Write] = {}
    for index in range(reads_per_write, reads, reads_per_write):
        identity = rng.randrange(DOCUMENTS)
        operation = (
            ("insert" if len(scheduled) % 2 == 0 else "update")
            if mix == "mixed"
            else mix
        )
        author = rng.randrange(AUTHORS) if operation == "insert" else identity % AUTHORS
        scheduled[index] = Write(
            operation, identity, author, DOCUMENTS + len(scheduled)
        )
    return scheduled


def configured_manager(
    client: pymongo.MongoClient[BsonDict], policy: Policy
) -> CacheManager[BsonDict]:
    config = CacheCoreConfig(enable_telemetry=True)
    if policy == "disabled":
        return CacheManager(client, cache_config=config)
    # Import only for enabled comparisons so the same runner can measure main.
    from client_query_cache import SelectiveInvalidation  # noqa: PLC0415

    return CacheManager(
        client,
        cache_config=config,
        invalidation={
            ("bench", "target"): SelectiveInvalidation(
                insert_partition_field="author_id"
                if policy in {"insert", "both"}
                else None,
                update_dependencies_for_counts=policy in {"counts", "both"},
            ),
        },
    )


def run_cell(
    replica: IsolatedReplicaSet,
    raw_database: Database[BsonDict],
    body: str,
    *,
    path: PathKind,
    mix: Mix,
    scenario: Scenario,
    rep: NonNegativeInt,
    reads: PositiveInt,
    reads_per_write: PositiveInt,
    control_rate: NonNegativeInt = 0,
    seconds: NonNegativeFloat = 0,
    policy: Policy = "disabled",
) -> BsonDict:
    scheduled = writes_for(mix, reads, reads_per_write, rep)
    if control_rate:
        scheduled = {
            index: Write(
                ("insert" if index % 2 == 0 else "update") if mix == "mixed" else mix,
                index % DOCUMENTS,
                index % AUTHORS,
                DOCUMENTS + index,
            )
            for index in range(round(control_rate * seconds))
        }
    writer_name = "sibling" if scenario == "uncached" else "target"
    address = urlparse(replica.uri)
    assert address.hostname is not None
    assert address.port is not None
    router = RoutingObserver()
    listener = ReadCommands()
    with ExitStack() as stack:
        stack.callback(restore, raw_database[writer_name], mix, scheduled)
        proxies = tuple(
            stack.enter_context(
                DirectPathByteProxy(
                    DirectPathProxyConfig(TOPOLOGY, address.hostname, address.port)
                )
            )
            for _ in range(1 if path == "production" else 2)
        )
        app = stack.enter_context(
            build_dedicated_client(
                f"mongodb://127.0.0.1:{proxies[0].local_port}",
                TOPOLOGY,
                event_listeners=(listener,),
            )
        )
        router.install(stack)
        if path != "production":
            stream_client = stack.enter_context(
                build_dedicated_client(
                    f"mongodb://127.0.0.1:{proxies[1].local_port}",
                    TOPOLOGY,
                )
            )
            stream_client.admin.command("ping")
            stack.enter_context(
                patch.object(
                    manager_module,
                    "ChangeStreamCoordinator",
                    lambda _client, cache, **kwargs: ChangeStreamCoordinator(
                        stream_client, cache, **kwargs
                    ),
                )
            )
        manager = (
            None
            if path == "direct"
            else stack.enter_context(configured_manager(app, policy))
        )
        name = "other" if scenario == "unrelated" else "target"
        raw = app.bench[name].with_options(
            read_preference=ReadPreference.PRIMARY,
            read_concern=MAJORITY,
        )
        writer = app.bench[writer_name].with_options(
            write_concern=WriteConcern("majority")
        )
        calls = operations(manager, raw)
        if manager is not None:
            await_warm(manager, calls["by_id", 0])
            if scenario == "unrelated":
                resident = operations(manager, app.bench.target)
                for index in range(WARMUP):
                    resident[read_key(index)]()
        for index in range(WARMUP):
            calls[read_key(index)]()
        router.reset()
        oracle = Oracle(body)
        stale: list[tuple[NonNegativeInt, NonNegativeFloat, str]] = []
        latencies: dict[str, list[NonNegativeFloat]] = {kind: [] for kind in CLASSES}
        before = None if manager is None else manager.snapshot()
        stream_before = (
            None if manager is None else manager.stream_cost_snapshot("bench")
        )
        wire_before = tuple(
            (proxy.bytes_sent, proxy.bytes_received) for proxy in proxies
        )
        observed_reads = 0

        def read(index: NonNegativeInt) -> None:
            nonlocal observed_reads
            key = read_key(index)
            kind = READ_KINDS[index % len(READ_KINDS)]
            listener.active = kind
            started = time.monotonic()
            value = calls[key]()
            latencies[kind].append(time.monotonic() - started)
            listener.active = None
            observed_reads += 1
            expected = oracle.expected(key)
            if value != expected:
                if (
                    path == "direct"
                    or scenario != "cached"
                    or key not in oracle.last_changed
                ):
                    message = (
                        f"wrong read: path={path} mix={mix} scenario={scenario} "
                        f"index={index} key={key} actual={str(value)[:300]} "
                        f"expected={str(expected)[:300]}"
                    )
                    raise RuntimeError(message)
                stale.append((oracle.last_changed[key], started, kind))

        def exercise() -> None:
            started = time.monotonic()
            ordinal = 0
            if control_rate:
                for index, write in scheduled.items():
                    remaining = started + index / control_rate - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    apply_write(writer, write, body)
                    read(index)
                remaining = started + seconds - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
            else:
                for index in range(reads):
                    if index in scheduled:
                        write = scheduled[index]
                        apply_write(writer, write, body)
                        if scenario == "cached":
                            oracle.write(write, ordinal)
                        ordinal += 1
                    read(index)
            if manager is not None:
                router.drain(len(scheduled))

        _, timing = measure_controlled(exercise, replica_set=replica)
        wire = tuple(
            {
                "sent": proxy.bytes_sent - previous[0],
                "received": proxy.bytes_received - previous[1],
            }
            for proxy, previous in zip(proxies, wire_before, strict=True)
        )
        if manager is not None:
            for write_index, started, _ in stale:
                if router.applied[write_index] <= started:
                    raise RuntimeError(
                        "stale result after its relevant event was applied"
                    )
            after = manager.snapshot()
            assert before is not None
            assert stream_before is not None
            misses = after.misses - before.misses
            bypasses = after.bypasses - before.bypasses
            assert sum(listener.counts.values()) == misses + bypasses
            assert after.hits - before.hits + misses + bypasses == observed_reads
            stream_after = manager.stream_cost_snapshot("bench")
            counters = {
                field: getattr(after, field) - getattr(before, field)
                for field in ("hits", "misses", "bypasses", "used_bytes", "entry_count")
            }
            logical_bytes = (
                stream_after.logical_event_bytes - stream_before.logical_event_bytes
            )
        else:
            assert sum(listener.counts.values()) == observed_reads
            counters = None
            logical_bytes = 0
        return {
            "path": path,
            "mix": mix,
            "scenario": scenario,
            "rep": rep,
            "reads_per_write": reads_per_write,
            "control_rate": control_rate,
            "reads": observed_reads,
            "writes": len(scheduled),
            "timing": asdict(timing),
            "application_wire": wire[0],
            "stream_wire": None if path == "production" else wire[1],
            "policy": policy,
            "applied_events": len(router.applied),
            "logical_bytes": logical_bytes,
            "route_cpu_ns": router.route_cpu_ns,
            "driver_reads": listener.counts,
            "cache_delta": counters,
            "stale_reads": {
                kind: sum(item[2] == kind for item in stale) for kind in CLASSES
            },
            "latency": {
                kind: scalar_latency_distribution(samples)
                for kind, samples in latencies.items()
            },
        }


def micro(
    replica: IsolatedReplicaSet,
    database: Database[BsonDict],
    rep: NonNegativeInt,
    *,
    reads_per_batch: PositiveInt = 4000,
    kinds: tuple[ReadKind, ...] = (*READ_KINDS, "prefix"),
) -> BsonDict:
    listener = ReadCommands()
    with ExitStack() as stack:
        client = stack.enter_context(
            replica.build_client(TOPOLOGY, event_listeners=(listener,))
        )
        manager = stack.enter_context(
            CacheManager(client, cache_config=CacheCoreConfig(enable_telemetry=True))
        )
        calls = operations(manager, client[database.name].target)
        await_warm(manager, calls["by_id", 0])
        for index in range(WARMUP):
            calls[read_key(index)]()
        view = manager.get_cached_collection(client[database.name].target)
        for author in range(HOT_AUTHORS):
            calls["prefix", author] = partial(
                feed, view, {"author_id": author}, limit=5
            )
        listener.counts["prefix"] = 0
        cpu_samples: dict[ReadKind, list[NonNegativeFloat]] = {
            kind: [] for kind in kinds
        }
        wall_samples: dict[ReadKind, list[NonNegativeFloat]] = {
            kind: [] for kind in kinds
        }
        before = manager.snapshot()  # pytriage: TR5, TR11 (before measured batches)
        for batch in range(12):
            for kind in kinds if batch % 2 == 0 else tuple(reversed(kinds)):
                listener.active = kind
                cpu_started = time.thread_time_ns()
                wall_started = time.perf_counter_ns()
                for index in range(reads_per_batch):
                    calls[kind, index % HOT_AUTHORS]()
                wall_samples[kind].append(
                    (time.perf_counter_ns() - wall_started) / reads_per_batch
                )
                cpu_samples[kind].append(
                    (time.thread_time_ns() - cpu_started) / reads_per_batch
                )
        listener.active = None
        assert (
            manager.snapshot().hits - before.hits == len(kinds) * 12 * reads_per_batch
        )
        assert all(listener.counts[kind] == 0 for kind in kinds)
        batches = {
            kind: {
                "cpu_ns_per_hit": cpu_samples[kind],
                "wall_ns_per_hit": wall_samples[kind],
            }
            for kind in kinds
        }

        return {"path": "current", "rep": rep, "size": 2000, "batches": batches}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("pilot", "churn", "controls", "micro"),
        required=True,
    )
    parser.add_argument("--reps", type=int, default=4)
    parser.add_argument("--reads", type=int, default=4096)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--paths", nargs="+", choices=("direct", "current", "production"), default=PATHS
    )
    parser.add_argument(
        "--policy", choices=("disabled", "insert", "counts", "both"), default="disabled"
    )
    parser.add_argument(
        "--policies", nargs="+", choices=("disabled", "insert", "counts", "both")
    )
    parser.add_argument("--sizes", nargs="+", type=int)
    parser.add_argument(
        "--mixes",
        nargs="+",
        choices=("insert", "update", "mixed"),
        default=("insert", "update"),
    )
    parser.add_argument("--ratios", nargs="+", type=int)
    parser.add_argument("--micro-reads", type=int, default=4000)
    parser.add_argument(
        "--micro-kinds",
        nargs="+",
        choices=(*READ_KINDS, "prefix"),
        default=(*READ_KINDS, "prefix"),
    )
    parser.add_argument(
        "--scenarios", nargs="+", choices=("cached", "uncached", "unrelated")
    )
    args = parser.parse_args()
    if (
        args.micro_reads < 1
        or args.reps < 1
        or args.reads < 128
        or args.reads % 4
        or not 1 <= args.seconds <= 60
    ):
        parser.error(
            "positive reps, reads >=128 divisible by four, seconds in [1,60] required"
        )
    if (args.sizes is not None and any(size < 200 for size in args.sizes)) or (
        args.ratios is not None and any(ratio < 1 for ratio in args.ratios)
    ):
        parser.error("sizes must be at least 200 bytes and ratios must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with (
        args.out.open("x") as output,
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="4g")) as replica,
        replica.build_client(TOPOLOGY) as client,
    ):
        cells: list[BsonDict] = []
        if args.suite == "micro":
            seed(client.bench, 2000)
            cells.extend(
                micro(
                    replica,
                    client.bench,
                    rep,
                    reads_per_batch=args.micro_reads,
                    kinds=tuple(args.micro_kinds),
                )
                for rep in range(args.reps)
            )
        sizes = (
            (2000,)
            if args.suite in {"pilot", "controls"}
            else ()
            if args.suite == "micro"
            else (200, 2000, 20000)
        )
        if args.sizes is not None:
            sizes = tuple(args.sizes)
        for rep, size in product(range(args.reps), sizes):
            body = seed(client.bench, size)
            paths = tuple(args.paths) if rep % 2 == 0 else tuple(reversed(args.paths))
            mixes: tuple[Mix, ...] = tuple(args.mixes)
            scenarios: tuple[Scenario, ...] = (
                ("uncached", "unrelated") if args.suite == "controls" else ("cached",)
            )
            if args.scenarios is not None:
                scenarios = tuple(args.scenarios)
            rates: tuple[PositiveInt, ...] = (
                (10, 100) if args.suite == "controls" else (100, 10)
            )
            if args.ratios is not None:
                rates = tuple(args.ratios)
            policies = tuple(args.policies or (args.policy,))
            if rep % 2:
                policies = tuple(reversed(policies))
            for mix, scenario, rate, path, policy in product(
                mixes, scenarios, rates, paths, policies
            ):
                if args.suite == "controls" and path == "direct":
                    continue
                cell = run_cell(
                    replica,
                    client.bench,
                    body,
                    path=path,
                    mix=mix,
                    scenario=scenario,
                    rep=rep,
                    reads=args.reads,
                    reads_per_write=rate,
                    control_rate=rate if args.suite == "controls" else 0,
                    seconds=args.seconds if args.suite == "controls" else 0,
                    policy=policy,
                )
                cells.append({"size": size, **cell})
        git = shutil.which("git")
        assert git is not None
        json.dump(
            {
                "suite": args.suite,
                "python": platform.python_version(),
                "pymongo": pymongo.version,
                "mongodb": client.server_info()["version"],
                "image": MONGODB_IMAGE,
                "revision": subprocess.check_output(  # noqa: S603 - Resolved git executable with fixed arguments, without a shell.
                    (git, "rev-parse", "HEAD"), text=True
                ).strip(),
                "cpus": 2,
                "memory": "4g",
                "reps": args.reps,
                "reads": args.reads,
                "seconds": args.seconds,
                "compression": "none",
                "tls": False,
                "source_sha256": {
                    name: hashlib.sha256(
                        (Path(__file__).parent / name).read_bytes()
                    ).hexdigest()
                    for name in (
                        "end_to_end.py",
                        "stream_projection.py",
                        "benchmark.py",
                    )
                },
                "cells": cells,
            },
            output,
            indent=2,
        )
        output.write("\n")


if __name__ == "__main__":
    main()

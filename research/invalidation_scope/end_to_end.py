"""Measure actual read retention and net costs of experimental invalidation guards."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import shutil
import subprocess
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
from bson.int64 import Int64
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
from client_query_cache import CacheManager
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
)
from client_query_cache.synchronous import manager as manager_module
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
from research.invalidation_scope.guards import GuardRouter, Policy, ReadKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )
    from pymongo.synchronous.collection import Collection
    from pymongo.synchronous.database import Database

    from client_query_cache.synchronous.collection import CachedCollection

PathKind = Literal["direct", "current", "insert", "fields"]
Mix = Literal["insert", "update"]
Scenario = Literal["cached", "uncached", "unrelated"]
READ_KINDS: tuple[ReadKind, ...] = ("feed", "count", "own", "by_id")
PATHS: tuple[PathKind, ...] = ("direct", "current", "insert", "fields")
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
    if mix == "insert":
        collection.delete_many({"_id": {"$gte": DOCUMENTS}})
    else:
        identities = tuple(
            dict.fromkeys(write.identity for write in scheduled.values())
        )
        collection.update_many({"_id": {"$in": identities}}, {"$set": {"views": 0}})


def feed(
    view: Collection[BsonDict] | CachedCollection[BsonDict], query: BsonDict
) -> list[BsonDict]:
    return list(view.find(query).sort("created", -1).limit(FEED_LIMIT))


def operations(
    manager: CacheManager[BsonDict] | None,
    raw: Collection[BsonDict],
    router: GuardRouter,
) -> dict[tuple[str, NonNegativeInt], Callable[[], object]]:
    calls: dict[tuple[str, NonNegativeInt], Callable[[], object]] = {}
    original = None if manager is None else manager.get_cached_collection(raw)
    for author, kind in product(range(HOT_AUTHORS), READ_KINDS):
        view = raw if original is None else router.collection(original, kind, author)
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
        author = rng.randrange(AUTHORS) if mix == "insert" else identity % AUTHORS
        scheduled[index] = Write(mix, identity, author, DOCUMENTS + len(scheduled))
    return scheduled


def qualify(database: Database[BsonDict], policy: Policy, body: str) -> None:
    router = GuardRouter(policy)
    raw = database.target.with_options(
        read_preference=ReadPreference.PRIMARY,
        read_concern=MAJORITY,
        write_concern=WriteConcern("majority"),
    )
    with ExitStack() as stack:
        router.install(stack)
        manager = stack.enter_context(CacheManager(database.client))
        calls = operations(manager, raw, router)
        direct = operations(None, raw, router)
        await_warm(manager, calls["by_id", 0])
        for index in range(WARMUP):
            calls[read_key(index)]()
        router.reset()
        expected_events = 0

        def applied() -> None:
            nonlocal expected_events
            expected_events += 1
            router.drain(expected_events)

        def check() -> None:
            for author, kind in product((0, 1), READ_KINDS):
                assert calls[kind, author]() == direct[kind, author]()

        def retained_count() -> bool:
            before = manager.snapshot().hits  # pytriage: TR5 - Snapshot precedes read.
            assert calls["count", 0]() == direct["count", 0]()
            return manager.snapshot().hits == before + 1

        raw.insert_one(document(DOCUMENTS, 499, body))
        applied()
        assert retained_count() == (policy == "insert")
        check()
        raw.update_one({"_id": 19_500}, {"$inc": {"views": 1}})
        applied()
        assert retained_count() == (policy == "fields")
        check()
        raw.update_one({"_id": 19_500}, {"$set": {"author_id": 1}})
        applied()
        assert not retained_count()
        check()
        unknown_values: tuple[object, ...] = (
            [0, 1],
            None,
            0.0,
            Int64(0),
            True,
            "x" * 65,
        )
        for identity, author in enumerate(unknown_values, DOCUMENTS + 1):
            inserted = document(identity, 0, body)
            inserted["author_id"] = author
            raw.insert_one(inserted)
            applied()
            assert not retained_count()
            check()
        raw.insert_one(
            {"_id": DOCUMENTS + 20, "created": DOCUMENTS + 20, "views": 0, "body": body}
        )
        applied()
        assert not retained_count()
        check()
        base = manager.get_cached_collection(raw)
        assert base.count_documents({"author_id": None}) == raw.count_documents(
            {"author_id": None}
        )
        raw.update_one({"_id": 0}, {"$set": {"author_id": [0, 1, 2, 3]}})
        applied()
        assert not retained_count()
        check()
        raw.update_one(
            {"_id": 0}, [{"$set": {"author_id": {"$slice": ["$author_id", 2]}}}]
        )
        applied()
        assert not retained_count()
        check()
        raw.update_one({"_id": 0}, {"$set": {"author_id.0": 7}})
        applied()
        assert not retained_count()
        check()
        raw.update_one({"_id": 0}, {"$unset": {"author_id": ""}})
        applied()
        assert not retained_count()
        check()
        assert base.count_documents({"author_id": None}) == raw.count_documents(
            {"author_id": None}
        )
        raw.update_one(
            {"_id": 1}, {"$set": {f"changed_{index}": index for index in range(33)}}
        )
        applied()
        assert not retained_count()
        check()
        raw.replace_one({"_id": 1}, document(1, 0, body))
        applied()
        assert not retained_count()
        check()
        raw.delete_one({"_id": 1})
        applied()
        assert not retained_count()
        check()
        physical = next(ns for ns in router.states if ns.collection == "target")
        namespace = (
            router.partitions[physical][0]
            if policy == "insert"
            else router.dependency_namespaces[physical]
            if policy == "fields"
            else physical
        )
        capture = manager.cache_core.capture_namespace_generation(namespace)
        raw.insert_one(document(DOCUMENTS + 50, 0, body))
        applied()
        assert (
            manager.cache_core.admit_namespace(capture, "inflight", 40)
            is AdmissionOutcome.DECLINED_STALE
        )
        capture = manager.cache_core.capture_namespace_generation(namespace)
        raw.insert_one(document(DOCUMENTS + 51, 1, body))
        applied()
        outcome = manager.cache_core.admit_namespace(capture, "unaffected", 40)
        assert outcome is (
            AdmissionOutcome.ADMITTED
            if policy == "insert"
            else AdmissionOutcome.DECLINED_STALE
        )
        capture = manager.cache_core.capture_namespace_generation(namespace)
        raw.insert_one(
            {
                "_id": DOCUMENTS + 52,
                "author_id": [0],
                "created": DOCUMENTS + 52,
                "views": 0,
                "body": body,
            }
        )
        applied()
        assert (
            manager.cache_core.admit_namespace(capture, "fallback", 40)
            is AdmissionOutcome.DECLINED_STALE
        )
        check()


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
) -> BsonDict:
    scheduled = writes_for(mix, reads, reads_per_write, rep)
    if control_rate:
        scheduled = {
            index: Write(mix, index % DOCUMENTS, index % AUTHORS, DOCUMENTS + index)
            for index in range(round(control_rate * seconds))
        }
    writer_name = "sibling" if scenario == "uncached" else "target"
    address = urlparse(replica.uri)
    assert address.hostname is not None
    assert address.port is not None
    router = GuardRouter("current" if path == "direct" else path)
    listener = ReadCommands()
    with ExitStack() as stack:
        stack.callback(restore, raw_database[writer_name], mix, scheduled)
        proxies = tuple(
            stack.enter_context(
                DirectPathByteProxy(
                    DirectPathProxyConfig(TOPOLOGY, address.hostname, address.port)
                )
            )
            for _ in range(2)
        )
        app = stack.enter_context(
            build_dedicated_client(
                f"mongodb://127.0.0.1:{proxies[0].local_port}",
                TOPOLOGY,
                event_listeners=(listener,),
            )
        )
        stream_client = stack.enter_context(
            build_dedicated_client(
                f"mongodb://127.0.0.1:{proxies[1].local_port}",
                TOPOLOGY,
            )
        )
        stream_client.admin.command("ping")
        router.install(stack)
        stack.enter_context(
            patch.object(
                manager_module,
                "ChangeStreamCoordinator",
                lambda _client, cache, **kwargs: ChangeStreamCoordinator(
                    stream_client, cache, **kwargs
                ),
            )
        )
        manager = None if path == "direct" else stack.enter_context(CacheManager(app))
        name = "other" if scenario == "unrelated" else "target"
        raw = app.bench[name].with_options(
            read_preference=ReadPreference.PRIMARY,
            read_concern=MAJORITY,
        )
        writer = app.bench[writer_name].with_options(
            write_concern=WriteConcern("majority")
        )
        calls = operations(manager, raw, router)
        if manager is not None:
            await_warm(manager, calls["by_id", 0])
            if scenario == "unrelated":
                resident = operations(manager, app.bench.target, router)
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
            "stream_wire": wire[1],
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
    policy: Policy,
    rep: NonNegativeInt,
) -> BsonDict:
    listener = ReadCommands()
    router = GuardRouter(policy)
    with ExitStack() as stack:
        client = stack.enter_context(
            replica.build_client(TOPOLOGY, event_listeners=(listener,))
        )
        router.install(stack)
        manager = stack.enter_context(CacheManager(client))
        calls = operations(manager, client[database.name].target, router)
        await_warm(manager, calls["by_id", 0])
        for index in range(WARMUP):
            calls[read_key(index)]()
        batches = {}
        for kind in READ_KINDS:
            cpu_samples = []
            wall_samples = []
            listener.active = kind
            before = manager.snapshot()  # pytriage: TR11 - Snapshot precedes batches.
            for _ in range(3):
                cpu_started = time.thread_time_ns()
                wall_started = time.perf_counter_ns()
                for index in range(4000):
                    calls[kind, index % HOT_AUTHORS]()
                wall_samples.append((time.perf_counter_ns() - wall_started) / 4000)
                cpu_samples.append((time.thread_time_ns() - cpu_started) / 4000)
            listener.active = None
            assert manager.snapshot().hits - before.hits == 12_000
            assert listener.counts[kind] == 0
            batches[kind] = {
                "cpu_ns_per_hit": cpu_samples,
                "wall_ns_per_hit": wall_samples,
            }
        return {"path": policy, "rep": rep, "size": 2000, "batches": batches}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("verify", "pilot", "churn", "controls", "micro"),
        required=True,
    )
    parser.add_argument("--reps", type=int, default=4)
    parser.add_argument("--reads", type=int, default=4096)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument(
        "--focus",
        choices=("insert", "fields"),
        help="Controls only: matching write mix at 100 writes/second.",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.focus and args.suite != "controls":
        parser.error("--focus requires --suite controls")
    if (
        args.reps < 1
        or args.reads < 128
        or args.reads % 4
        or not 1 <= args.seconds <= 60
    ):
        parser.error(
            "positive reps, reads >=128 divisible by four, seconds in [1,60] required"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with (
        args.out.open("x") as output,
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="4g")) as replica,
        replica.build_client(TOPOLOGY) as client,
    ):
        cells: list[BsonDict] = []
        if args.suite == "verify":
            for policy in ("current", "insert", "fields"):
                body = seed(client.bench, 200)
                qualify(client.bench, policy, body)
        if args.suite == "micro":
            seed(client.bench, 2000)
            for rep in range(args.reps):
                policies: tuple[Policy, ...] = ("current", "insert", "fields")
                order = policies if rep % 2 == 0 else tuple(reversed(policies))
                cells.extend(
                    micro(replica, client.bench, policy, rep) for policy in order
                )
        sizes = (
            (2000,)
            if args.suite in {"pilot", "controls"}
            else ()
            if args.suite in {"verify", "micro"}
            else (200, 2000, 20000)
        )
        for rep, size in product(range(args.reps), sizes):
            body = seed(client.bench, size)
            paths = PATHS if rep % 2 == 0 else tuple(reversed(PATHS))
            mixes: tuple[Mix, ...] = ("insert", "update")
            if args.focus:
                paths = tuple(path for path in paths if path in {"current", args.focus})
                mixes = ("insert",) if args.focus == "insert" else ("update",)
            scenarios: tuple[Scenario, ...] = (
                ("uncached", "unrelated") if args.suite == "controls" else ("cached",)
            )
            rates: tuple[PositiveInt, ...] = (
                (10, 100) if args.suite == "controls" else (100, 10)
            )
            if args.focus:
                rates = (100,)
            for mix, scenario, rate, path in product(mixes, scenarios, rates, paths):
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
                )
                cells.append({"size": size, **cell})
        git = shutil.which("git")
        assert git is not None
        json.dump(
            {
                "suite": args.suite,
                "focus": args.focus,
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
                        "guards.py",
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

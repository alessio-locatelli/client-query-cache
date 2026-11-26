"""Measure exact-ID cache refills with ordinary and delayed MongoDB reads."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from contextlib import AsyncExitStack, contextmanager
from dataclasses import dataclass
from statistics import median
from threading import Lock
from time import perf_counter, process_time
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict
from unittest.mock import patch

from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.collection import AsyncCollection

from client_query_cache import CacheManager
from client_query_cache._core.stream_events import (  # noqa: PLC2701 - Synchronize observed writes with the cache stream.
    route_change_event,
)
from client_query_cache._types import (  # noqa: PLC2701 - Use the package's constrained numeric annotations.
    BsonDict,
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.asynchronous import CachedCollection as AsyncCachedCollection
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous import streams as async_streams
from client_query_cache.synchronous import streams as sync_streams
from development.research.collection_adapter.live_error import fixture as replica_set
from tests.cursor_fixtures import ReadCommands
from tests.stream_helpers import StreamBarrier

if TYPE_CHECKING:
    from collections.abc import Generator

    from pymongo.monitoring import CommandStartedEvent, CommandSucceededEvent
    from pymongo.synchronous.collection import Collection

    from client_query_cache import CachedCollection

_WIDTH: PositiveInt = 8
_KEYS = tuple(range(_WIDTH))
_APP_NAME = "exact_id_refill_bursts"
_COLLECTION = "items"
type Model = Literal["sync", "async"]
type Case = Literal[
    "warm", "direct-hot", "cached-hot", "direct-distinct", "cached-distinct"
]
type Policy = Literal["independent", "wait-50ms", "wait-for-leader", "backup-10ms"]
type SyncTarget = Collection[BsonDict] | CachedCollection[BsonDict]
type AsyncTarget = AsyncCollection[BsonDict] | AsyncCachedCollection[BsonDict]
type Target = SyncTarget | AsyncTarget


class DelayProfile(NamedTuple):
    label: NonEmptyStr
    milliseconds: NonNegativeInt
    first_only: bool = False


_ORDINARY = DelayProfile("ordinary", 0)
_SHORT = DelayProfile("all-5ms", 5)
_PROFILES = (
    _ORDINARY,
    _SHORT,
    DelayProfile("all-80ms", 80),
    DelayProfile("first-80ms", 80, first_only=True),
)
# Two seconds models waiting for the leader across the injected delays while
# keeping a stalled experiment bounded.
_WAITS: dict[Policy, PositiveFloat] = {
    "wait-50ms": 0.05,
    "wait-for-leader": 2.0,
    "backup-10ms": 0.01,
}
type Scenario = tuple[DelayProfile, Case, Policy]


class BurstCommands(ReadCommands):
    def __init__(self) -> None:
        super().__init__(_COLLECTION)
        self._lock = Lock()
        self._active: set[int] = set()
        self.peak: NonNegativeInt = 0
        self.wire_micros: list[NonNegativeInt] = []

    def started(self, event: CommandStartedEvent) -> None:
        if event.command_name == "find" and event.command["find"] == _COLLECTION:
            with self._lock:
                super().started(event)
                self._active.add(event.request_id)
                self.peak = max(self.peak, len(self._active))

    def succeeded(self, event: CommandSucceededEvent) -> None:
        if event.command_name == "find":
            with self._lock:
                if event.request_id in self._active:
                    self._active.remove(event.request_id)
                    self.wire_micros.append(event.duration_micros)

    def reset(self) -> None:
        self.commands.clear()
        self.wire_micros.clear()
        self.peak = 0


@dataclass(frozen=True, slots=True)
class Burst:
    latencies: tuple[NonNegativeFloat, ...]
    cpu_seconds: NonNegativeFloat
    reads: NonNegativeInt
    peak_reads: NonNegativeInt
    wire_seconds: tuple[NonNegativeFloat, ...]


class ReadClientOptions(TypedDict):
    appName: str
    directConnection: bool
    minPoolSize: PositiveInt
    maxPoolSize: PositiveInt
    readConcernLevel: Literal["majority"]
    event_listeners: list[BurstCommands]


@contextmanager
def origin_delay(
    control: MongoClient[BsonDict], delay: DelayProfile, commands: BurstCommands
) -> Generator[None]:
    if not delay.milliseconds:
        yield
        return
    before = control.admin.command(
        "configureFailPoint",
        "failCommand",
        mode={"times": 1} if delay.first_only else "alwaysOn",
        data={
            "failCommands": ["find"],
            "appName": _APP_NAME,
            "blockConnection": True,
            "blockTimeMS": delay.milliseconds,
        },
    )["count"]
    try:
        yield
    finally:
        after = control.admin.command("configureFailPoint", "failCommand", mode="off")[
            "count"
        ]
    expected = 1 if delay.first_only else len(commands.commands)
    if after - before != expected:
        message = f"{delay.label} delayed {after - before} finds, expected {expected}"
        raise RuntimeError(message)


async def read_one(target: Target, key: NonNegativeInt) -> BsonDict | None:
    if isinstance(target, (AsyncCollection, AsyncCachedCollection)):
        return await target.find_one({"_id": key})
    return await asyncio.to_thread(target.find_one, {"_id": key})


async def burst(
    target: Target,
    keys: tuple[NonNegativeInt, ...],
    revision: NonNegativeInt,
    commands: BurstCommands,
    *,
    policy: Policy,
) -> Burst:
    async def read(key: NonNegativeInt) -> NonNegativeFloat:
        document = await read_one(target, key)
        elapsed = perf_counter() - arrived  # pytriage: TR11 (end timing)
        if (
            document is None
            or document["_id"] != key
            or document["revision"] != revision
        ):
            message = f"Unexpected result for key {key} at revision {revision}"
            raise RuntimeError(message)
        return elapsed

    cpu_start = process_time()  # pytriage: TR11 (start timing)
    arrived = perf_counter()
    # Model coordination at the harness boundary. Every caller still performs
    # its own library read, reusing an admitted result through ordinary lookup.
    async with asyncio.TaskGroup() as group:
        reads = [group.create_task(read(keys[0]))]
        if policy != "independent":
            done, _ = await asyncio.wait(reads, timeout=_WAITS[policy])
            if not done and policy == "backup-10ms":
                reads.append(group.create_task(read(keys[1])))
                await asyncio.wait(reads, return_when=asyncio.FIRST_COMPLETED)
        reads.extend(group.create_task(read(key)) for key in keys[len(reads) :])
    cpu_seconds = process_time() - cpu_start  # pytriage: TR11 (end timing)
    if len(commands.commands) != len(commands.wire_micros):
        message = "Every started application find must complete"
        raise RuntimeError(message)
    return Burst(
        tuple(task.result() for task in reads),
        cpu_seconds,
        len(commands.commands),
        commands.peak,
        tuple(us / 1_000_000 for us in commands.wire_micros),
    )


async def measure(
    control: MongoClient[BsonDict], model: Model, rounds: PositiveInt, pool: PositiveInt
) -> dict[Scenario, list[Burst]]:
    database = control[f"refill_burst_{model}"]
    database.create_collection("stream_barrier")
    database[_COLLECTION].insert_many(
        {"_id": key, "revision": 0, "payload": "x" * 1024} for key in _KEYS
    )
    address = control.address
    if address is None:
        message = "The benchmark replica set has no primary address"
        raise RuntimeError(message)
    commands = BurstCommands()
    settings = ReadClientOptions(
        appName=_APP_NAME,
        directConnection=True,
        minPoolSize=pool,
        maxPoolSize=pool,
        readConcernLevel="majority",
        event_listeners=[commands],
    )
    stream_barrier = StreamBarrier()
    workload: tuple[Scenario, ...] = (
        (_ORDINARY, "warm", "independent"),
        (_ORDINARY, "direct-distinct", "independent"),
        (_ORDINARY, "cached-distinct", "independent"),
        *((delay, "direct-hot", "independent") for delay in _PROFILES),
        *((delay, "cached-hot", "independent") for delay in _PROFILES),
        *((delay, "cached-hot", policy) for delay in _PROFILES for policy in _WAITS),
    )
    samples: dict[Scenario, list[Burst]] = defaultdict(list)
    async with AsyncExitStack() as resources:
        facade = async_streams if model == "async" else sync_streams
        resources.enter_context(
            patch.object(
                facade, "route_change_event", stream_barrier.observe(route_change_event)
            )
        )
        manager: CacheManager[BsonDict] | AsyncCacheManager[BsonDict]
        if model == "sync":
            client = resources.enter_context(
                MongoClient[BsonDict](*address, **settings)
            )
            manager = resources.enter_context(CacheManager(client))
        else:
            async_client = await resources.enter_async_context(
                AsyncMongoClient[BsonDict](*address, **settings)
            )
            manager = await resources.enter_async_context(
                AsyncCacheManager(async_client)
            )
        cached = manager[database.name][_COLLECTION]
        await read_one(cached, 0)
        # Open enough application sockets for a burst before recording samples.
        commands.reset()
        with origin_delay(control, _SHORT, commands):
            await burst(cached.raw, _KEYS, 0, commands, policy="independent")
        revision = 0
        for _ in range(rounds):
            for delay, case, policy in workload:
                for key in _KEYS:
                    await read_one(cached, key)
                if case != "warm":
                    revision += 1
                    database[_COLLECTION].update_many(
                        {}, {"$set": {"revision": revision}}
                    )
                    await asyncio.to_thread(stream_barrier.wait, database)
                commands.reset()
                target = cached.raw if case.startswith("direct-") else cached
                keys = _KEYS if case.endswith("-distinct") else (0,) * _WIDTH
                with origin_delay(control, delay, commands):
                    sample = await burst(
                        target, keys, revision, commands, policy=policy
                    )
                samples[delay, case, policy].append(sample)
    return samples


def summarize(model: Model, samples: dict[Scenario, list[Burst]]) -> None:
    for (delay, case, policy), bursts in samples.items():
        read_counts = [sample.reads for sample in bursts]
        latencies = sorted(value for sample in bursts for value in sample.latencies)
        wire_times = [value for sample in bursts for value in sample.wire_seconds]
        wire_ms = median(wire_times) * 1000 if wire_times else 0.0
        p95_ms = latencies[(95 * len(latencies) + 99) // 100 - 1] * 1000
        cpu_ms = median(sample.cpu_seconds for sample in bursts) * 1000
        peak = max(sample.peak_reads for sample in bursts)
        print(
            f"{model:5} {delay.label:10} {case:15} {policy:16} "
            f"{median(read_counts):4g} {min(read_counts):2}-{max(read_counts):<2} "
            f"{median(latencies) * 1000:9.3f} {p95_ms:9.3f} {wire_ms:9.3f} "
            f"{cpu_ms:8.3f} {peak:4}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--pool", type=int, default=12)
    args = parser.parse_args()
    if args.rounds < 1 or args.pool < 2:
        parser.error("--rounds must be positive and --pool must be at least 2")
    with replica_set() as control:
        version = control.server_info()["version"]
        print(f"MongoDB {version}, pool {args.pool}, {args.rounds} bursts/case")
        print(
            "model delay      case            policy           finds range"
            "   p50 ms    p95 ms   wire ms   cpu ms peak"
        )
        for model in ("sync", "async"):
            summarize(
                model, asyncio.run(measure(control, model, args.rounds, args.pool))
            )


if __name__ == "__main__":
    main()

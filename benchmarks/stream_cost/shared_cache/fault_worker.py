from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bson

from benchmarks.stream_cost.shared_cache.adapters import _STALE
from benchmarks.stream_cost.shared_cache.safety import local_key
from benchmarks.stream_cost.shared_cache.wire import encode_key
from client_query_cache._core.keys import NamespaceId
from client_query_cache._types import NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from client_query_cache_shared_index import ReaderIndex

    from benchmarks.stream_cost.shared_cache.adapters import (
        AsyncSharedCacheManager,
        SharedCacheManager,
    )
    from benchmarks.stream_cost.shared_cache.worker import Payload, WorkerSpec
    from client_query_cache._types import BsonDict


def selection(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    spec: WorkerSpec,
) -> Payload:
    namespace = next(iter(manager._metadata))  # noqa: SLF001
    return {
        "op": "select-identity",
        "ns": [spec.database, spec.collection],
        "epoch": manager._metadata[namespace].checked_epoch,  # noqa: SLF001
        "identity": encode_key(len(spec.keys)),
        "shape": encode_key(
            manager[spec.database][spec.collection]._find_one_default_shape  # noqa: SLF001
        ),
    }


@dataclass(frozen=True, slots=True)
class LocalSelection:
    reader: ReaderIndex
    database_slot: NonNegativeInt
    slot: NonNegativeInt
    epoch: NonNegativeInt
    shape: bytes
    keys: tuple[bytes, ...]

    @classmethod
    def prepare(
        cls,
        manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
        spec: WorkerSpec,
    ) -> LocalSelection | None:
        namespace = NamespaceId(spec.database, spec.collection)
        local = manager.local
        if local is None or namespace not in manager._slots:  # noqa: SLF001
            return None
        database_slot, slot, _incarnation = manager._slots[namespace]  # noqa: SLF001
        return cls(
            local.reader,
            database_slot,
            slot,
            manager._metadata[namespace].checked_epoch,  # noqa: SLF001
            manager.keys.encode(
                manager[spec.database][spec.collection]._find_one_default_shape  # noqa: SLF001
            ),
            tuple(local_key(key) for key in spec.keys),
        )


@dataclass(slots=True)
class LocalTraffic:
    active: bool = False
    sweeps: NonNegativeInt = 0
    hits: NonNegativeInt = 0
    misses: NonNegativeInt = 0
    last_hit: NonNegativeFloat = 0.0
    selection: LocalSelection | None = None

    def prepare(
        self,
        manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
        spec: WorkerSpec,
    ) -> None:
        self.selection = LocalSelection.prepare(manager, spec)
        assert self.selection is not None

    def step(self) -> None:
        selection = self.selection
        assert selection is not None
        for key in selection.keys:
            if (
                selection.reader.lookup(
                    selection.database_slot,
                    selection.slot,
                    selection.epoch,
                    key,
                    selection.shape,
                )
                is None
            ):
                self.misses += 1
            else:
                self.hits += 1
                self.last_hit = time.monotonic()
        self.sweeps += 1


def local_snapshot(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    spec: WorkerSpec,
) -> Payload:
    local = manager.local
    selection = LocalSelection.prepare(manager, spec)
    return {
        "kind": "probe",
        "index": spec.index,
        "resident_keys": 0
        if selection is None
        else sum(
            selection.reader.lookup(
                selection.database_slot,
                selection.slot,
                selection.epoch,
                key,
                selection.shape,
            )
            is not None
            for key in selection.keys
        ),
        "incarnation": None if local is None else local.incarnation,
        "monotonic": time.monotonic(),
    }


def traffic_command(
    operation: str,
    traffic: LocalTraffic,
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    spec: WorkerSpec,
) -> Payload:
    if operation == "traffic-start":
        traffic.prepare(manager, spec)
        traffic.active = True
        traffic.step()
    else:
        traffic.active = False
    return {
        "kind": "probe",
        "index": spec.index,
        "active": traffic.active,
        "sweeps": traffic.sweeps,
        "hits": traffic.hits,
        "misses": traffic.misses,
        "last_hit": traffic.last_hit,
    }


def probe_keys(spec: WorkerSpec, request: Payload) -> tuple[NonNegativeInt, ...]:
    if request["op"] in {"prime", "detect"}:
        return spec.keys
    if "key" in request:
        key = request["key"]
        assert isinstance(key, int)
        return (key,)
    return spec.keys[:1]


def snapshot(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    spec: WorkerSpec,
    *,
    eligible: bool,
    hits_before: NonNegativeInt,
    bypasses_before: NonNegativeInt,
    reads: NonNegativeInt,
    exhaustive: bool,
    evidence: ReadEvidence,
) -> Payload:
    local = manager.local
    return {
        "kind": "probe",
        "index": spec.index,
        "model": spec.model,
        "eligible": eligible,
        "hit": manager.observation.hits > hits_before,
        "hit_at": evidence.first_hit,
        "last_hit_at": evidence.last_hit,
        "unsafe_hit": evidence.unsafe_hit,
        "all_hits": manager.observation.hits - hits_before == reads,
        "resident_keys": local_snapshot(manager, spec)["resident_keys"]
        if exhaustive
        else None,
        "bypass": sum(manager.observation.bypasses.values()) > bypasses_before,
        "detached": local is not None and local.reader.detached,
        "incarnation": manager.endpoint.incarnation,
        "late_replies": manager.endpoint.counters.late_replies,
        "monotonic": time.monotonic(),
    }


@dataclass(slots=True)
class ReadEvidence:
    first_hit: NonNegativeFloat | None = None
    last_hit: NonNegativeFloat | None = None
    unsafe_hit: bool = False

    def observe(
        self, before: NonNegativeInt, after: NonNegativeInt, *, eligible: bool
    ) -> None:
        if after > before:
            self.last_hit = time.monotonic()
            if self.first_hit is None:
                self.first_hit = self.last_hit
            self.unsafe_hit |= not eligible


def worker_eligible(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    namespace: NamespaceId,
) -> bool:
    try:
        metadata = manager._metadata[namespace]  # noqa: SLF001
    except KeyError:
        return False
    return metadata is not _STALE and metadata.bypass_reason is None


def verify_document(document: BsonDict | None, revision: NonNegativeInt) -> None:
    if document is None or document["revision"] != revision:
        raise LookupError("fault probe returned a missing or stale revision")


def stress_reads(
    connection: Connection,
    spec: WorkerSpec,
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
) -> None:
    namespace = next(iter(manager._slots))  # noqa: SLF001
    database_slot, slot, _incarnation = manager._slots[namespace]  # noqa: SLF001
    epoch = manager._metadata[namespace].checked_epoch  # noqa: SLF001
    local = manager.local
    assert local is not None
    observed: dict[NonNegativeInt, set[bytes]] = {key: set() for key in spec.keys}
    reads = 0
    shape = encode_key("fault-stress")
    keys = tuple((key, local_key(key)) for key in spec.keys)
    connection.send({"kind": "reading"})
    while not connection.poll():
        for key, encoded in keys:
            payload = local.reader.lookup(database_slot, slot, epoch, encoded, shape)
            if payload is not None:
                observed[key].add(payload)
                reads += 1
    connection.recv()
    connection.send({"observed": observed, "reads": reads})


def sync_fault_worker(
    connection: Connection,
    spec: WorkerSpec,
    manager: SharedCacheManager[BsonDict],
) -> None:
    connection.send({"kind": "attached"})
    collection = manager[spec.database][spec.collection]
    namespace = NamespaceId(spec.database, spec.collection)
    traffic = LocalTraffic()
    while True:
        if traffic.active:
            traffic.step()
            if not connection.poll():
                continue
        request = connection.recv()
        if request == "close":
            break
        operation = request["op"]
        if operation in {"traffic-start", "traffic-stop"}:
            connection.send(traffic_command(operation, traffic, manager, spec))
            continue
        if operation == "local-only":
            connection.send(local_snapshot(manager, spec))
            continue
        if operation == "stress":
            stress_reads(connection, spec, manager)
            continue
        if operation == "capture":
            connection.send(manager.endpoint.request(selection(manager, spec)))
            continue
        if operation == "admit":
            manager.endpoint.send(
                {
                    "op": "admit",
                    "handle": request["handle"],
                    "value": bson.encode({"v": {}}),
                }
            )
            connection.send({"kind": "sent"})
            continue
        hits = manager.observation.hits
        bypasses = sum(manager.observation.bypasses.values())
        evidence = ReadEvidence()
        eligible = False
        keys = probe_keys(spec, request)
        for key in keys:
            before = manager.observation.hits
            verify_document(collection.find_one({"_id": key}), request["revision"])
            eligible = worker_eligible(manager, namespace)
            evidence.observe(before, manager.observation.hits, eligible=eligible)
        connection.send(
            snapshot(
                manager,
                spec,
                eligible=eligible,
                hits_before=hits,
                bypasses_before=bypasses,
                reads=len(keys),
                exhaustive=operation in {"prime", "detect"},
                evidence=evidence,
            )
        )


async def async_fault_worker(
    connection: Connection,
    spec: WorkerSpec,
    manager: AsyncSharedCacheManager[BsonDict],
) -> None:
    connection.send({"kind": "attached"})
    collection = manager[spec.database][spec.collection]
    namespace = NamespaceId(spec.database, spec.collection)
    traffic = LocalTraffic()
    while True:
        if traffic.active:
            traffic.step()
            await asyncio.sleep(0)
            if not connection.poll():
                continue
        request = await asyncio.to_thread(connection.recv)
        if request == "close":
            break
        operation = request["op"]
        if operation in {"traffic-start", "traffic-stop"}:
            connection.send(traffic_command(operation, traffic, manager, spec))
            continue
        if operation == "local-only":
            connection.send(local_snapshot(manager, spec))
            continue
        if operation == "stress":
            await asyncio.to_thread(stress_reads, connection, spec, manager)
            continue
        if operation == "cancel":
            before = manager.endpoint.counters.late_replies
            pending = asyncio.create_task(
                manager.endpoint.request(selection(manager, spec))
            )
            await asyncio.sleep(0.05)
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            connection.send({"cancelled": True, "late_replies_before": before})
            continue
        hits = manager.observation.hits
        bypasses = sum(manager.observation.bypasses.values())
        evidence = ReadEvidence()
        eligible = False
        keys = probe_keys(spec, request)
        for key in keys:
            before = manager.observation.hits
            verify_document(
                await collection.find_one({"_id": key}), request["revision"]
            )
            eligible = worker_eligible(manager, namespace)
            evidence.observe(before, manager.observation.hits, eligible=eligible)
        connection.send(
            snapshot(
                manager,
                spec,
                eligible=eligible,
                hits_before=hits,
                bypasses_before=bypasses,
                reads=len(keys),
                exhaustive=operation in {"prime", "detect"},
                evidence=evidence,
            )
        )

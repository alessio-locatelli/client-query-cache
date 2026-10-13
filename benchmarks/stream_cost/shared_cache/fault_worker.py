from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import bson

from benchmarks.stream_cost.shared_cache.safety import local_key, local_read
from benchmarks.stream_cost.shared_cache.wire import encode_key
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

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


def snapshot(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    spec: WorkerSpec,
    *,
    eligible: bool,
    hits_before: NonNegativeInt,
    bypasses_before: NonNegativeInt,
    reads: NonNegativeInt,
) -> Payload:
    local = manager.local
    resident = {
        key
        for key in spec.keys
        if local_read(manager, spec.database, spec.collection, key) is not None
    }
    return {
        "kind": "probe",
        "index": spec.index,
        "model": spec.model,
        "eligible": eligible,
        "hit": manager.observation.hits > hits_before,
        "all_hits": manager.observation.hits - hits_before == reads,
        "resident_keys": len(resident),
        "bypass": sum(manager.observation.bypasses.values()) > bypasses_before,
        "local_hit": spec.keys[0] in resident,
        "detached": local is not None and local.reader.detached,
        "incarnation": manager.endpoint.incarnation,
        "late_replies": manager.endpoint.counters.late_replies,
        "monotonic": time.monotonic(),
    }


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
    while (request := connection.recv()) != "close":
        operation = request["op"]
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
        eligible = collection._cache_ineligibility_reason() is None  # noqa: SLF001
        keys = (
            spec.keys
            if operation == "prime"
            else (request["key"],)
            if "key" in request
            else spec.keys[:1]
        )
        for key in keys:
            verify_document(collection.find_one({"_id": key}), request["revision"])
        connection.send(
            snapshot(
                manager,
                spec,
                eligible=eligible,
                hits_before=hits,
                bypasses_before=bypasses,
                reads=len(keys),
            )
        )


async def async_fault_worker(
    connection: Connection,
    spec: WorkerSpec,
    manager: AsyncSharedCacheManager[BsonDict],
) -> None:
    connection.send({"kind": "attached"})
    collection = manager[spec.database][spec.collection]
    while (request := await asyncio.to_thread(connection.recv)) != "close":
        operation = request["op"]
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
        eligible = await collection._cache_ineligibility_reason() is None  # noqa: SLF001
        keys = (
            spec.keys
            if operation == "prime"
            else (request["key"],)
            if "key" in request
            else spec.keys[:1]
        )
        for key in keys:
            verify_document(
                await collection.find_one({"_id": key}), request["revision"]
            )
        connection.send(
            snapshot(
                manager,
                spec,
                eligible=eligible,
                hits_before=hits,
                bypasses_before=bypasses,
                reads=len(keys),
            )
        )

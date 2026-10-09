from __future__ import annotations

import asyncio
import multiprocessing
import os
import signal
import socket
import struct
import time
from typing import TYPE_CHECKING, Any, cast

import bson
import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from pymongo import AsyncMongoClient, MongoClient

from benchmarks.stream_cost.shared_cache.adapters import (
    METADATA_REFRESH,
    OWNER_UNAVAILABLE,
    PROTOTYPE_SCOPE,
    UNPORTABLE_KEY,
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from benchmarks.stream_cost.shared_cache.attachment import (
    AsyncEndpoint,
    AttachmentConfigurationError,
    InheritedAttachmentError,
    SyncEndpoint,
)
from benchmarks.stream_cost.shared_cache.wire import encode_frame, encode_key
from tests.codec_helpers import Decimal128ToDecimalDecoder
from tests.shared_cache.conftest import (
    COLLECTION,
    DOCUMENTS,
    ready,
    select_identity,
    wait_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.attachment import AttachmentConfig, Message
    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner, Payload

pytestmark = pytest.mark.integration


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as raw:
        yield raw


@pytest.fixture
def sync_manager(
    client: MongoClient[dict[str, Any]], start_owner: Callable[..., Owner]
) -> Iterator[tuple[SharedCacheManager[dict[str, Any]], Owner]]:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    yield manager, owner
    manager.close()


def _reader_main(
    connection: Connection, uri: str, config: AttachmentConfig, database: str, mode: str
) -> None:
    with MongoClient[dict[str, Any]](uri) as raw:
        manager = SharedCacheManager(raw, SyncEndpoint(config))
        collection = manager[database][COLLECTION]
        ready(manager, database)
        if mode == "capture":  # pragma: lax no cover (the test kills this process)
            reply = select_identity(manager.endpoint, manager, database, DOCUMENTS + 10)
            connection.send(reply)
            connection.recv()
            return
        documents = [collection.find_one({"_id": index}) for index in range(DOCUMENTS)]
        connection.send(
            {
                "documents": len([document for document in documents if document]),
                "hits": manager.observation.hits,
                "misses": manager.observation.misses,
            }
        )
        manager.close()


def _spawn_reader(
    owner: Owner, uri: str, database: str, mode: str
) -> tuple[multiprocessing.process.BaseProcess, Connection]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(
        target=_reader_main, args=(child, uri, owner.attachment(), database, mode)
    )
    process.start()
    child.close()
    return process, parent


def test_sync_and_async_workers_reuse_one_admitted_payload_across_processes(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    manager, owner = sync_manager
    ready(manager, seeded_database)
    for index in range(DOCUMENTS):
        manager[seeded_database][COLLECTION].find_one({"_id": index})
    wait_for(lambda: owner.observation()["cache"]["entry_count"] == DOCUMENTS)

    async def read_async() -> tuple[int, int]:
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        async_manager = AsyncSharedCacheManager(async_client, endpoint)
        collection = async_manager[seeded_database][COLLECTION]
        documents = [
            await collection.find_one({"_id": index}) for index in range(DOCUMENTS)
        ]
        await async_manager.close()
        await async_client.close()
        assert all(documents)
        return async_manager.observation.hits, async_manager.observation.misses

    process, connection = _spawn_reader(owner, mongodb_uri, seeded_database, "read")
    child = cast("Payload", connection.recv())
    process.join(10)

    assert asyncio.run(read_async()) == (DOCUMENTS, 0)
    assert child == {"documents": DOCUMENTS, "hits": DOCUMENTS, "misses": 0}
    assert process.exitcode == 0
    assert owner.observation()["cache"]["entry_count"] == DOCUMENTS
    assert owner.request("sample")["commands"]["stream:opened"] == 1


def test_mutating_a_shared_hit_leaves_the_group_entry_unchanged(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner], seeded_database: str
) -> None:
    manager, _owner = sync_manager
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    collection.find_one({"_id": 1})

    first = collection.find_one({"_id": 1})
    assert first is not None
    first["payload"] = "mutated"

    assert collection.find_one({"_id": 1}) == {
        "_id": 1,
        "payload": "value-1",
        "revision": 0,
    }


def test_processed_invalidation_prevents_a_stale_selection(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
    client: MongoClient[dict[str, Any]],
) -> None:
    manager, owner = sync_manager
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    collection.find_one({"_id": 2})
    before = owner.request("sample")["invalidations"]

    client[seeded_database][COLLECTION].update_one(
        {"_id": 2}, {"$inc": {"revision": 1}}
    )
    wait_for(lambda: owner.request("sample")["invalidations"] > before)

    assert cast("dict[str, Any]", collection.find_one({"_id": 2}))["revision"] == 1


def test_owner_restart_fences_old_sessions_and_handles(
    client: MongoClient[dict[str, Any]],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    first = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(first.attachment()))
    ready(manager, seeded_database)
    reply = select_identity(manager.endpoint, manager, seeded_database, 3)
    assert reply is not None
    old_incarnation = manager.endpoint.incarnation

    os.kill(first.pid, signal.SIGKILL)
    first.process.join(10)
    document = manager[seeded_database][COLLECTION].find_one({"_id": 4})
    replacement = start_owner()
    time.sleep(0.2)
    wait_for(
        lambda: (
            select_identity(manager.endpoint, manager, seeded_database, 4) is not None
        )
    )
    manager.endpoint.send(
        {"op": "admit", "handle": reply["handle"], "value": bson.encode({"v": {}})}
    )

    assert document == {"_id": 4, "payload": "value-4", "revision": 0}
    assert manager.observation.bypasses[OWNER_UNAVAILABLE] >= 1
    assert manager.endpoint.incarnation != old_incarnation
    wait_for(lambda: replacement.counters()["rejected_admissions"] == 1)
    assert replacement.observation()["cache"]["entry_count"] == 0
    manager.close()


def test_a_second_live_owner_cannot_take_the_endpoint(
    start_owner: Callable[..., Owner],
) -> None:
    start_owner()

    with pytest.raises(RuntimeError, match="already holds this endpoint"):
        start_owner()


def test_a_paused_owner_times_out_and_the_read_stays_native(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner], seeded_database: str
) -> None:
    manager, owner = sync_manager
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    owner.request("pause-server", seconds=1.0)

    document = collection.find_one({"_id": 5})
    time.sleep(1.0)
    collection.find_one({"_id": 5})
    wait_for(
        lambda: (
            collection.find_one({"_id": 5}) is not None and manager.observation.hits > 0
        )
    )

    assert document == {"_id": 5, "payload": "value-5", "revision": 0}
    assert manager.endpoint.counters.timeouts == 1


def test_a_stalled_watch_disables_selection_and_fences_captures(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner], seeded_database: str
) -> None:
    manager, owner = sync_manager
    ready(manager, seeded_database)
    capture = select_identity(manager.endpoint, manager, seeded_database, 6)
    assert capture is not None

    owner.request("pause-watch")
    wait_for(
        lambda: (
            cast(
                "Payload",
                select_identity(manager.endpoint, manager, seeded_database, 7),
            ).get("reason")
            == "progress-expired"
        )
    )
    manager.endpoint.send(
        {"op": "admit", "handle": capture["handle"], "value": bson.encode({"v": {}})}
    )
    owner.request("resume-watch")
    wait_for(
        lambda: (
            cast(
                "Payload",
                select_identity(manager.endpoint, manager, seeded_database, 7),
            )["r"]
            == "miss"
        )
    )

    counters = owner.counters()
    assert counters["lease_expiries"] >= 1
    assert counters["rejected_admissions"] >= 1
    assert owner.observation()["cache"]["entry_count"] == 0


def _after_stream_reopen(
    manager: SharedCacheManager[dict[str, Any]], owner: Owner, database: str, fault: str
) -> Message:
    collection = manager[database][COLLECTION]
    ready(manager, database)
    collection.find_one({"_id": 8})
    assert owner.observation()["cache"]["entry_count"] == 1
    capture = select_identity(manager.endpoint, manager, database, 9)
    assert capture is not None

    owner.request(fault)
    wait_for(lambda: owner.request("sample")["commands"]["stream:opened"] == 2)
    wait_for(
        lambda: (
            cast("Payload", select_identity(manager.endpoint, manager, database, 10))[
                "r"
            ]
            in {"miss", "refresh"}
        )
    )
    manager.endpoint.send(
        {"op": "admit", "handle": capture["handle"], "value": bson.encode({"v": {}})}
    )
    return capture


def test_a_resumed_stream_keeps_entries_and_captures_valid(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
) -> None:
    manager, owner = sync_manager

    _after_stream_reopen(manager, owner, seeded_database, "sever")

    wait_for(lambda: owner.counters()["admitted"] == 2)
    assert manager[seeded_database][COLLECTION].find_one({"_id": 8}) is not None
    assert owner.counters()["rejected_admissions"] == 0


def test_lost_stream_history_clears_entries_and_fences_captures(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
) -> None:
    manager, owner = sync_manager

    _after_stream_reopen(manager, owner, seeded_database, "lose-history")

    wait_for(lambda: owner.counters()["rejected_admissions"] >= 1)
    assert owner.observation()["cache"]["entry_count"] == 0


def test_a_killed_worker_releases_its_captures(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()
    process, connection = _spawn_reader(owner, mongodb_uri, seeded_database, "capture")
    reply = cast("Payload", connection.recv())
    assert reply["r"] == "miss"
    assert owner.observation()["captures"] == 1

    os.kill(cast("int", process.pid), signal.SIGKILL)
    process.join(10)

    wait_for(lambda: owner.observation()["captures"] == 0)
    assert owner.observation()["connections"] == 0


def test_a_replacement_worker_reuses_group_entries(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()
    first, first_connection = _spawn_reader(owner, mongodb_uri, seeded_database, "read")
    admitted = cast("Payload", first_connection.recv())
    first.join(10)
    replacement, connection = _spawn_reader(owner, mongodb_uri, seeded_database, "read")
    reused = cast("Payload", connection.recv())
    replacement.join(10)

    assert admitted["misses"] == DOCUMENTS
    assert reused == {"documents": DOCUMENTS, "hits": DOCUMENTS, "misses": 0}
    assert owner.request("sample")["commands"]["stream:opened"] == 1


def _raw_connection(config: AttachmentConfig, *, authenticate: bool) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(config.socket_path)
    if authenticate:
        sock.sendall(encode_frame(config.hello()))
        sock.recv(struct.unpack("<I", sock.recv(4))[0])
    return sock


def _closed(sock: socket.socket) -> bool:
    try:
        while sock.recv(65_536):
            pass
    except ConnectionResetError:  # pragma: lax no cover (peer reset timing)
        pass
    return True


def test_a_slow_reader_is_detached_without_blocking_peers(
    client: MongoClient[dict[str, Any]],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(queued_bytes_per_connection=16_384)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)
    slow = _raw_connection(owner.attachment(), authenticate=True)
    slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4_096)
    request = encode_frame({"v": 1, "id": 1, "op": "observe"})
    slow.sendall(request * 64)

    wait_for(lambda: owner.counters()["detached"] == 1)
    manager[seeded_database][COLLECTION].find_one({"_id": 11})
    assert manager[seeded_database][COLLECTION].find_one({"_id": 11}) is not None
    assert manager.observation.hits >= 1
    slow.close()
    manager.close()


@pytest.mark.parametrize(
    ("frames", "authenticate", "counter"),
    [
        pytest.param(
            lambda _database: [struct.pack("<I", 5) + b"\x05\x00\x00\x00\xff"],
            False,
            "protocol_errors",
            id="invalid-bson",
        ),
        pytest.param(
            lambda _database: [struct.pack("<I", 10**8)],
            False,
            "protocol_errors",
            id="oversized",
        ),
        pytest.param(
            lambda _database: [encode_frame({"v": 2, "id": 1, "op": "hello"})],
            False,
            "protocol_errors",
            id="version",
        ),
        pytest.param(
            lambda _database: [encode_frame({"v": 1, "id": 1, "op": "observe"})],
            False,
            "unauthorized",
            id="unauthenticated",
        ),
        pytest.param(
            lambda _database: [encode_frame({"v": 1, "id": 1, "op": "rename"})],
            True,
            "protocol_errors",
            id="unknown-op",
        ),
        pytest.param(
            lambda _database: [
                encode_frame({"v": 1, "id": 1, "op": "select-identity"})
            ],
            True,
            "protocol_errors",
            id="missing-field",
        ),
        pytest.param(
            lambda _database: [
                encode_frame({"v": 1, "id": 1, "op": "metadata", "ns": "db.collection"})
            ],
            True,
            "protocol_errors",
            id="namespace",
        ),
        pytest.param(
            lambda _database: [
                encode_frame(
                    {"v": 1, "id": 1, "op": "admit", "handle": 1, "value": "text"}
                )
            ],
            True,
            "protocol_errors",
            id="admission-value",
        ),
        pytest.param(
            lambda database: [
                encode_frame(
                    {
                        "v": 1,
                        "id": 1,
                        "op": "select-find",
                        "ns": [database, COLLECTION],
                        "epoch": 0,
                        "family": {"t": "nope", "p": 1},
                        "limit": 1,
                    }
                )
            ],
            True,
            "protocol_errors",
            id="canonical-tag",
        ),
    ],
)
def test_malformed_peers_are_rejected_while_others_continue(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
    frames: Callable[[str], list[bytes]],
    authenticate: bool,
    counter: str,
) -> None:
    manager, owner = sync_manager
    ready(manager, seeded_database)
    peer = _raw_connection(owner.attachment(), authenticate=authenticate)

    for frame in frames(seeded_database):
        peer.sendall(frame)

    assert _closed(peer)
    wait_for(lambda: owner.counters()[counter] == 1)
    assert manager[seeded_database][COLLECTION].find_one({"_id": 0}) is not None
    peer.close()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param({"capability": b"wrong"}, "not reachable", id="capability"),
        pytest.param({"budget_bytes": 1}, "configuration-mismatch", id="budget"),
    ],
)
def test_unauthorized_or_conflicting_attachments_fail_visibly(
    start_owner: Callable[..., Owner], change: dict[str, object], message: str
) -> None:
    owner = start_owner()

    with pytest.raises(AttachmentConfigurationError, match=message):
        SyncEndpoint(owner.attachment(**change))


def test_the_connection_limit_rejects_extra_attachments(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner(connections=1)
    endpoint = SyncEndpoint(owner.attachment())

    with pytest.raises(AttachmentConfigurationError, match="not reachable"):
        SyncEndpoint(owner.attachment())
    assert owner.counters()["connections_rejected"] == 1
    endpoint.close()


def test_capture_limits_and_expiry_bound_owner_state(
    client: MongoClient[dict[str, Any]],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(captures=1, capture_seconds=0.3)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)
    wait_for(lambda: owner.observation()["captures"] == 0)

    first = select_identity(manager.endpoint, manager, seeded_database, 12)
    second = select_identity(manager.endpoint, manager, seeded_database, 13)
    wait_for(lambda: owner.counters()["expired_captures"] >= 1)
    manager.endpoint.send(
        {
            "op": "admit",
            "handle": cast("Payload", first)["handle"],
            "value": bson.encode({"v": {}}),
        }
    )
    manager.endpoint.send({"op": "discard", "handle": 99})

    assert cast("Payload", second)["handle"] is None
    wait_for(lambda: owner.counters()["rejected_admissions"] == 1)
    assert owner.counters()["capture_limit_misses"] >= 1
    manager.close()


def test_unauthorized_databases_bypass(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
) -> None:
    manager, _owner = sync_manager

    document = manager["other_database"][COLLECTION].find_one({"_id": 0})

    assert document is None
    assert manager.observation.bypasses["database-not-authorized"] == 1


def test_owner_shutdown_during_activation_leaves_reads_native(
    client: MongoClient[dict[str, Any]],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    collection = manager[seeded_database][COLLECTION]

    first = collection.find_one({"_id": 14})
    owner.stop()
    second = collection.find_one({"_id": 14})

    assert first == second == {"_id": 14, "payload": "value-14", "revision": 0}
    assert owner.process.exitcode == 0
    assert manager.observation.hits == 0
    manager.close()


def test_cancelled_async_selection_releases_its_capture(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[int, int, AsyncEndpoint]:
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        manager = AsyncSharedCacheManager(async_client, endpoint)
        collection = manager[seeded_database][COLLECTION]
        while manager.observation.hits + manager.observation.misses == 0:
            await collection.find_one({"_id": 15})
            await asyncio.sleep(0.02)
        ticks = 0

        async def tick() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(tick())
        owner.request("pause-server", seconds=0.3)
        namespace = next(iter(manager._metadata))
        selection = asyncio.create_task(
            endpoint.request(
                {
                    "op": "select-identity",
                    "ns": [seeded_database, COLLECTION],
                    "epoch": manager._metadata[namespace].checked_epoch,
                    "identity": encode_key(16),
                    "shape": encode_key(collection._find_one_default_shape),
                }
            )
        )
        await asyncio.sleep(0.05)
        selection.cancel()
        await asyncio.sleep(0.6)
        ticker.cancel()
        await manager.close()
        await async_client.close()
        return ticks, endpoint.counters.late_replies, endpoint

    ticks, late, _endpoint = asyncio.run(scenario())

    assert ticks >= 20
    assert late == 1
    wait_for(lambda: owner.observation()["captures"] == 0)


def test_async_reads_fall_back_when_the_owner_disappears(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()

    async def scenario() -> list[dict[str, Any] | None]:
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        manager = AsyncSharedCacheManager(async_client, endpoint)
        collection = manager[seeded_database][COLLECTION]
        while manager.observation.hits + manager.observation.misses == 0:
            await collection.find_one({"_id": 17})
        owner.request("pause-server", seconds=1.0)
        paused = await collection.find_one({"_id": 17})
        await asyncio.sleep(1.0)
        os.kill(owner.pid, signal.SIGKILL)
        owner.process.join(10)
        gone = await collection.find_one({"_id": 18})
        await asyncio.sleep(0.2)
        retried = await collection.find_one({"_id": 18})
        assert endpoint.counters.timeouts == 1
        assert endpoint.counters.failures >= 1
        await manager.close()
        await async_client.close()
        return [paused, gone, retried]

    documents = asyncio.run(scenario())

    assert [cast("dict[str, Any]", document)["_id"] for document in documents] == [
        17,
        18,
        18,
    ]


def test_inherited_attachments_are_rejected_before_use(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
) -> None:
    manager, owner = sync_manager
    endpoint = asyncio.run(AsyncEndpoint.attach(owner.attachment()))
    manager.endpoint._pid = os.getpid() + 1
    endpoint._pid = os.getpid() + 1
    operations: tuple[Callable[[], object], ...] = (
        lambda: manager.endpoint.request({"op": "observe"}),
        lambda: manager.endpoint.send({"op": "discard", "handle": 1}),
        lambda: asyncio.run(endpoint.request({"op": "observe"})),
        lambda: endpoint.send({"op": "discard", "handle": 1}),
    )

    for operation in operations:
        with pytest.raises(InheritedAttachmentError):
            operation()


def test_unportable_and_out_of_scope_reads_execute_natively(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
    client: MongoClient[dict[str, Any]],
) -> None:
    manager, _owner = sync_manager
    ready(manager, seeded_database)
    custom = client[seeded_database].get_collection(
        COLLECTION,
        codec_options=CodecOptions(
            type_registry=TypeRegistry([Decimal128ToDecimalDecoder()])
        ),
    )
    view = manager.get_cached_collection(custom)
    collection = manager[seeded_database][COLLECTION]

    assert view.find_one({"_id": 0}) is not None
    assert collection.find_one({"payload": "value-1"}) is not None
    assert collection.count_documents({}) == DOCUMENTS
    assert collection.estimated_document_count() == DOCUMENTS
    assert len(collection.distinct("_id")) == DOCUMENTS
    assert len(collection.aggregate([{"$match": {}}]).to_list()) == DOCUMENTS
    assert len(collection.find({}, hint=[("_id", 1)]).to_list()) == DOCUMENTS
    assert manager.observation.bypasses[UNPORTABLE_KEY] == 1
    assert manager.observation.bypasses[PROTOTYPE_SCOPE] == 5


def test_collection_metadata_failures_bypass_shared_selection(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner],
    seeded_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _owner = sync_manager
    ready(manager, seeded_database)

    missing = manager[seeded_database]["missing"].find_one({"_id": 0})
    unavailable = manager[seeded_database]["unprobed"]
    monkeypatch.setattr(type(unavailable), "_probe_collection", lambda _view: None)
    probed = unavailable.find_one({"_id": 0})

    assert missing is None
    assert probed is None
    assert manager.observation.bypasses["missing_collection"] == 1
    assert manager.observation.bypasses["metadata_unavailable"] == 1


def test_shared_find_cursors_admit_complete_results_only(
    sync_manager: tuple[SharedCacheManager[dict[str, Any]], Owner], seeded_database: str
) -> None:
    manager, owner = sync_manager
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)

    partial = collection.find({"revision": 0}, sort=[("_id", 1)], limit=8)
    next(partial)
    partial.close()
    wait_for(lambda: owner.observation()["captures"] == 0)
    complete = collection.find({"revision": 0}, sort=[("_id", 1)], limit=8).to_list()
    wait_for(lambda: owner.counters()["admitted"] >= 1)
    hit = collection.find({"revision": 0}, sort=[("_id", 1)], limit=4).to_list()
    clone = collection.find({"revision": 0}, sort=[("_id", 1)], limit=8).clone()

    assert [document["_id"] for document in complete] == list(range(8))
    assert [document["_id"] for document in hit] == list(range(4))
    assert len(clone.to_list()) == 8
    assert manager.observation.hits >= 2


def test_async_find_cursors_and_metadata_refresh(
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
    client: MongoClient[dict[str, Any]],
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[
        list[dict[str, Any]], AsyncSharedCacheManager[dict[str, Any]]
    ]:
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        manager = AsyncSharedCacheManager(
            async_client, await AsyncEndpoint.attach(owner.attachment())
        )
        collection = manager[seeded_database][COLLECTION]
        while manager.observation.hits + manager.observation.misses == 0:
            await collection.find_one({"_id": 19})
        client[seeded_database][COLLECTION].rename("renamed")
        client[seeded_database]["renamed"].rename(COLLECTION)
        await asyncio.sleep(0.5)
        await collection.find_one({"_id": 19})
        await collection.find_one({"_id": 19})
        documents = await collection.find(
            {"revision": 0}, sort=[("_id", 1)], limit=4
        ).to_list()
        await (
            collection.find({"revision": 0}, sort=[("_id", 1)], limit=4)
            .clone()
            .to_list()
        )
        assert await collection.count_documents({}) == DOCUMENTS
        assert await collection.estimated_document_count() == DOCUMENTS
        assert len(await collection.distinct("_id")) == DOCUMENTS
        assert len(await (await collection.aggregate([])).to_list()) == DOCUMENTS
        assert await collection.find_one({"payload": "value-1"}) is not None
        assert collection["sub"].name == f"{COLLECTION}.sub"
        await manager.close()
        await async_client.close()
        return documents, manager

    documents, manager = asyncio.run(scenario())

    assert [document["_id"] for document in documents] == list(range(4))
    assert manager.observation.bypasses[METADATA_REFRESH] >= 1

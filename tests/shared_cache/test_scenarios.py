from __future__ import annotations

import asyncio
import ctypes
import math
import mmap
import multiprocessing
import os
import signal
import socket
import struct
import time
from typing import TYPE_CHECKING, cast

import bson
import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from pymongo import MongoClient

from benchmarks.stream_cost.shared_cache.safety import (
    closed_peer as _closed,
)
from benchmarks.stream_cost.shared_cache.safety import (
    local_key as _local_key,
)
from benchmarks.stream_cost.shared_cache.safety import (
    local_read,
    verify_published_payloads,
)
from benchmarks.stream_cost.shared_cache.safety import (
    raw_connection as _raw_connection,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._shared.adapters import (
    METADATA_REFRESH,
    OWNER_UNAVAILABLE,
    PROTOTYPE_SCOPE,
    UNPORTABLE_KEY,
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AttachmentConfigurationError,
    InheritedAttachmentError,
    LocalIndex,
    SyncEndpoint,
)
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._shared.wire import encode_frame, encode_key
from client_query_cache._types import BsonDict
from tests.codec_helpers import Decimal128ToDecimalDecoder
from tests.shared_cache.conftest import (
    COLLECTION,
    DOCUMENTS,
    LIMITS,
    async_shared_manager,
    ready,
    select_identity,
    wait_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from multiprocessing.connection import Connection

    from client_query_cache._shared.attachment import AttachmentConfig, Message
    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner, Payload

pytestmark = pytest.mark.integration

_PAST_RETRY_SECONDS = 0.15
_SHARED_INDEX = SharedIndexLimits(
    slots=256, arena_bytes=4 * 1024 * 1024, namespaces=4, ring_tokens=1024
)
_SMALL_ARENA = SharedIndexLimits(
    slots=16, arena_bytes=1024, namespaces=1, ring_tokens=64
)
_FEW_SLOTS = SharedIndexLimits(
    slots=8, arena_bytes=1024 * 1024, namespaces=1, ring_tokens=64
)
_DETECTION_BOUND_SECONDS = 0.1
_DETECTION_POLL_SECONDS = 0.001
_EXPIRY_SLACK_SECONDS = 0.1
_CHURN_ROUNDS = 12
_SHAPE_KEY = encode_key("full")
_STRESS_BUDGET = 64 * 1024
_STRESS_MAX_ENTRY = 16 * 1024
_STRESS_READERS = 3
_STRESS_KEYS = 16
_STRESS_ROUNDS = 40
_STRESS_REPEAT = 300
_DENIED = r"Bad file descriptor|Permission denied|Operation not permitted"


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as raw:
        yield raw


@pytest.fixture
def sync_manager(
    client: MongoClient[BsonDict], start_owner: Callable[..., Owner]
) -> Iterator[tuple[SharedCacheManager[BsonDict], Owner]]:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    yield manager, owner
    manager.close()


def _reader_main(
    connection: Connection, uri: str, config: AttachmentConfig, database: str, mode: str
) -> None:
    with MongoClient[BsonDict](uri) as raw:
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    manager, owner = sync_manager
    ready(manager, seeded_database)
    for index in range(DOCUMENTS):
        manager[seeded_database][COLLECTION].find_one({"_id": index})
    wait_for(lambda: owner.observation()["cache"]["entry_count"] == DOCUMENTS)

    async def read_async() -> tuple[int, int]:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            collection = async_manager[seeded_database][COLLECTION]
            documents = [
                await collection.find_one({"_id": index}) for index in range(DOCUMENTS)
            ]
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner], seeded_database: str
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
    client: MongoClient[BsonDict],
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

    assert cast("BsonDict", collection.find_one({"_id": 2}))["revision"] == 1


def test_owner_restart_fences_old_sessions_and_handles(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    first = start_owner()
    manager = open_manager(client, first)
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


def test_a_second_live_owner_cannot_take_the_endpoint(
    start_owner: Callable[..., Owner],
) -> None:
    start_owner()

    with pytest.raises(RuntimeError, match="already holds this endpoint"):
        start_owner()


def test_a_paused_owner_times_out_and_the_read_stays_native(
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner], seeded_database: str
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner], seeded_database: str
) -> None:
    manager, owner = sync_manager
    ready(manager, seeded_database)
    capture = select_identity(manager.endpoint, manager, seeded_database, 6)
    assert capture is not None

    owner.request("pause-watch")
    wait_for(
        lambda: (
            "reason"
            in (
                reply := cast(
                    "Payload",
                    select_identity(manager.endpoint, manager, seeded_database, 7),
                )
            )
            and reply["reason"] == "progress-expired"
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
    manager: SharedCacheManager[BsonDict], owner: Owner, database: str, fault: str
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
) -> None:
    manager, owner = sync_manager

    _after_stream_reopen(manager, owner, seeded_database, "sever")

    wait_for(lambda: owner.counters()["admitted"] == 2)
    assert manager[seeded_database][COLLECTION].find_one({"_id": 8}) is not None
    assert owner.counters()["rejected_admissions"] == 0


def test_lost_stream_history_clears_entries_and_fences_captures(
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
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


def test_a_slow_reader_is_detached_without_blocking_peers(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(queued_bytes_per_connection=16_384)
    manager = open_manager(client, owner)
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
            lambda _database: [encode_frame({"v": 1, "op": "observe"})],
            True,
            "protocol_errors",
            id="missing-id",
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
        *(
            pytest.param(
                lambda database, identity=identity: [
                    encode_frame(
                        {
                            "v": 1,
                            "id": 1,
                            "op": "select-identity",
                            "ns": [database, COLLECTION],
                            "epoch": 0,
                            "identity": encode_key(identity),
                            "shape": encode_key("shape"),
                        }
                    )
                ],
                True,
                "protocol_errors",
                id=name,
            )
            for name, identity in (("null-identity", None), ("nan-identity", math.nan))
        ),
    ],
)
def test_malformed_peers_are_rejected_while_others_continue(
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
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
        pytest.param({"capability": b"wrong"}, "unauthorized", id="capability"),
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
    start_owner: Callable[..., Owner], open_endpoint: Callable[[Owner], SyncEndpoint]
) -> None:
    owner = start_owner(connections=1)
    open_endpoint(owner)

    with pytest.raises(AttachmentConfigurationError, match="not reachable"):
        SyncEndpoint(owner.attachment())
    assert owner.counters()["connections_rejected"] == 1


def test_capture_limits_and_expiry_bound_owner_state(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(captures=1, capture_seconds=0.3)
    manager = open_manager(client, owner)
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


def test_unauthorized_databases_bypass(
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
) -> None:
    manager, _owner = sync_manager

    document = manager["other_database"][COLLECTION].find_one({"_id": 0})

    assert document is None
    assert manager.observation.bypasses["database-not-authorized"] == 1


def test_owner_shutdown_during_activation_leaves_reads_native(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
    collection = manager[seeded_database][COLLECTION]

    first = collection.find_one({"_id": 14})
    owner.stop()
    second = collection.find_one({"_id": 14})

    assert first == second == {"_id": 14, "payload": "value-14", "revision": 0}
    assert owner.process.exitcode == 0
    assert manager.observation.hits == 0


def test_an_owner_exits_cleanly_when_the_harness_hangs_up_after_close(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()

    owner.control.send("close")
    owner.control.close()
    owner.process.join(10)

    assert owner.process.exitcode == 0


def test_cancelled_async_selection_releases_its_capture(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[int, int]:
        async with async_shared_manager(owner, mongodb_uri) as manager:
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
            namespace = NamespaceId(seeded_database, COLLECTION)
            metadata = manager._metadata.find(namespace)
            assert metadata is not None
            selection = asyncio.create_task(
                manager.endpoint.request(
                    {
                        "op": "select-identity",
                        "ns": [seeded_database, COLLECTION],
                        "epoch": metadata.checked_epoch,
                        "identity": encode_key(16),
                        "shape": encode_key(collection._find_one_default_shape),
                    }
                )
            )
            await asyncio.sleep(0.05)
            selection.cancel()
            await asyncio.sleep(0.6)
            ticker.cancel()
        return ticks, manager.endpoint.counters.late_replies

    ticks, late = asyncio.run(scenario())

    assert ticks >= 20
    assert late == 1
    wait_for(lambda: owner.observation()["captures"] == 0)


def test_async_reads_fall_back_when_the_owner_disappears(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()

    async def scenario() -> list[BsonDict | None]:
        async with async_shared_manager(owner, mongodb_uri) as manager:
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
            assert manager.endpoint.counters.timeouts == 1
            assert manager.endpoint.counters.failures >= 1
        return [paused, gone, retried]

    documents = asyncio.run(scenario())

    assert [cast("BsonDict", document)["_id"] for document in documents] == [
        17,
        18,
        18,
    ]


def test_a_replaced_connection_teardown_keeps_current_requests(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[Message | None, int]:
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        replaced = endpoint._writer
        assert replaced is not None
        endpoint._abandon(replaced)
        await asyncio.sleep(_PAST_RETRY_SECONDS)
        assert await endpoint.request({"op": "observe"}) is not None
        owner.request("pause-server", seconds=0.2)
        current = asyncio.create_task(endpoint.request({"op": "observe"}))
        await asyncio.sleep(0.05)
        endpoint._abandon(replaced)
        reply = await current
        await endpoint.close()
        return reply, endpoint.counters.failures

    reply, failures = asyncio.run(scenario())

    assert reply is not None
    assert reply["r"] == "ok"
    assert failures == 0


def test_a_closed_async_endpoint_stays_detached(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[Message | None, int]:
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        await endpoint.close()
        await asyncio.sleep(_PAST_RETRY_SECONDS)
        return await endpoint.request({"op": "observe"}), endpoint.counters.connects

    reply, connects = asyncio.run(scenario())

    assert reply is None
    assert connects == 1


def test_closing_during_a_reconnection_discards_the_new_connection(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[Message | None, AsyncEndpoint]:
        endpoint = await AsyncEndpoint.attach(owner.attachment())
        assert endpoint._writer is not None
        endpoint._abandon(endpoint._writer)
        await asyncio.sleep(_PAST_RETRY_SECONDS)
        owner.request("pause-server", seconds=0.2)
        reconnecting = asyncio.create_task(endpoint.request({"op": "observe"}))
        await asyncio.sleep(0.05)
        await endpoint.close()
        return await reconnecting, endpoint

    reply, endpoint = asyncio.run(scenario())

    assert reply is None
    assert endpoint._writer is None
    assert endpoint.counters.connects == 1


def test_inherited_attachments_are_rejected_before_use(
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, owner = sync_manager
    endpoint = asyncio.run(AsyncEndpoint.attach(owner.attachment()))
    monkeypatch.setattr(manager.endpoint, "_pid", os.getpid() + 1)
    monkeypatch.setattr(endpoint, "_pid", os.getpid() + 1)
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
    client: MongoClient[BsonDict],
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner],
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
    sync_manager: tuple[SharedCacheManager[BsonDict], Owner], seeded_database: str
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
    client: MongoClient[BsonDict],
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[list[BsonDict], AsyncSharedCacheManager[BsonDict]]:
        async with async_shared_manager(owner, mongodb_uri) as manager:
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
        return documents, manager

    documents, manager = asyncio.run(scenario())

    assert [document["_id"] for document in documents] == list(range(4))
    assert manager.observation.bypasses[METADATA_REFRESH] >= 1


def _local_read(
    manager: SharedCacheManager[BsonDict], database: str, key: int
) -> bytes | None:
    return local_read(manager, database, COLLECTION, key)


def _until(predicate: Callable[[], bool], timeout: float = 10.0) -> float:
    started = time.monotonic()
    while not predicate():
        assert time.monotonic() - started < timeout, "condition was not reached in time"
        time.sleep(_DETECTION_POLL_SECONDS)
    return time.monotonic() - started


def _prime(
    manager: SharedCacheManager[BsonDict], owner: Owner, database: str, key: int
) -> bytes:
    admitted = owner.counters()["admitted"]
    manager[database][COLLECTION].find_one({"_id": key})
    wait_for(lambda: owner.counters()["admitted"] > admitted)
    payload = _local_read(manager, database, key)
    assert payload is not None
    return payload


@pytest.fixture
def shared_reads(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    seeded_database: str,
) -> tuple[SharedCacheManager[BsonDict], Owner]:
    owner = start_owner(shared_index=_SHARED_INDEX)
    manager = open_manager(client, owner, local=True)
    ready(manager, seeded_database)
    return manager, owner


def test_a_killed_owner_stops_local_hits_within_the_detection_bound(
    shared_reads: tuple[SharedCacheManager[BsonDict], Owner], seeded_database: str
) -> None:
    manager, owner = shared_reads
    _prime(manager, owner, seeded_database, 1)
    assert manager.local is not None
    reader = manager.local.reader

    os.kill(owner.pid, signal.SIGKILL)
    elapsed = _until(lambda: reader.detached)
    owner.process.join(10)

    assert elapsed <= _DETECTION_BOUND_SECONDS
    assert _local_read(manager, seeded_database, 1) is None
    assert manager[seeded_database][COLLECTION].find_one({"_id": 1}) == {
        "_id": 1,
        "payload": "value-1",
        "revision": 0,
    }


@pytest.mark.parametrize("fault", ["sigstop", "watch-pause"])
def test_a_silent_owner_stops_local_hits_by_the_progress_expiry(
    shared_reads: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
    fault: str,
) -> None:
    manager, owner = shared_reads
    _prime(manager, owner, seeded_database, 1)
    assert manager.local is not None

    if fault == "sigstop":
        os.kill(owner.pid, signal.SIGSTOP)
    else:
        owner.request("pause-watch")
    try:
        elapsed = _until(lambda: _local_read(manager, seeded_database, 1) is None)
    finally:
        if fault == "sigstop":
            os.kill(owner.pid, signal.SIGCONT)
        else:
            owner.request("resume-watch")

    assert elapsed <= LIMITS.progress_expiry_seconds + _EXPIRY_SLACK_SECONDS
    assert not manager.local.reader.detached
    wait_for(lambda: _local_read(manager, seeded_database, 1) is not None)


def test_a_replacement_owner_serves_only_its_own_index(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    first = start_owner(shared_index=_SHARED_INDEX)
    manager = open_manager(client, first, local=True)
    ready(manager, seeded_database)
    _prime(manager, first, seeded_database, 1)
    previous = manager.local
    assert previous is not None

    os.kill(first.pid, signal.SIGKILL)
    first.process.join(10)
    replacement = start_owner(shared_index=_SHARED_INDEX)
    wait_for(
        lambda: (
            manager[seeded_database][COLLECTION].find_one({"_id": 1}) is not None
            and manager.local is not previous
            and manager._slots.find(NamespaceId(seeded_database, COLLECTION))
            is not None
            and _local_read(manager, seeded_database, 1) is not None
        )
    )

    assert previous.reader.detached
    assert manager.local is not None
    assert manager.local.incarnation == replacement.observation()["incarnation"]
    assert manager.local.incarnation != previous.incarnation
    assert replacement.counters()["admitted"] == 1


def _read_forever(  # pragma: no cover (killed before coverage is saved)
    config: AttachmentConfig, database: str, key: int
) -> None:
    local = LocalIndex.attach(config)
    metadata = _shared_metadata(SyncEndpoint(config), database)
    database_slot, slot = cast("list[int]", metadata["slot"])
    epoch = cast("int", metadata["epoch"])
    while True:
        local.reader.lookup(database_slot, slot, epoch, _local_key(key), _SHAPE_KEY)


def _shared_metadata(endpoint: SyncEndpoint, database: str) -> Message:
    request: Message = {"op": "metadata", "ns": [database, COLLECTION]}
    reply = endpoint.request(dict(request))
    while reply is None or reply["r"] != "ok":
        time.sleep(_DETECTION_POLL_SECONDS)
        reply = endpoint.request(dict(request))
    return reply


def test_a_worker_killed_mid_read_never_delays_reclamation(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(shared_index=_SMALL_ARENA)
    manager = open_manager(client, owner, local=True)
    ready(manager, seeded_database)
    _prime(manager, owner, seeded_database, 1)
    context = multiprocessing.get_context("spawn")
    reader = context.Process(
        target=_read_forever, args=(owner.attachment(), seeded_database, 1)
    )
    reader.start()
    wait_for(lambda: owner.observation()["shared_index"]["sessions"] == 2)
    time.sleep(_DETECTION_POLL_SECONDS)

    os.kill(cast("int", reader.pid), signal.SIGKILL)
    reader.join(10)
    for revision in range(1, _CHURN_ROUNDS + 1):
        client[seeded_database][COLLECTION].update_one(
            {"_id": 1}, {"$set": {"revision": revision}}
        )
        wait_for(lambda: _local_read(manager, seeded_database, 1) is None)
        _prime(manager, owner, seeded_database, 1)

    shared = owner.observation()["shared_index"]
    assert shared == {"published": 1, "sessions": 1, "dropped_touches": 0}
    assert manager[seeded_database][COLLECTION].find_one({"_id": 1}) == {
        "_id": 1,
        "payload": "value-1",
        "revision": _CHURN_ROUNDS,
    }


def _stress_reader(
    connection: Connection, config: AttachmentConfig, database: str, keys: int
) -> None:
    endpoint = SyncEndpoint(config)
    local = LocalIndex.attach(config)
    metadata = _shared_metadata(endpoint, database)
    database_slot, slot = cast("list[int]", metadata["slot"])
    epoch = cast("int", metadata["epoch"])
    observed: dict[int, set[bytes]] = {key: set() for key in range(keys)}
    reads = 0
    connection.send("reading")
    while not connection.poll():
        for key in range(keys):
            payload = local.reader.lookup(
                database_slot, slot, epoch, _local_key(key), _SHAPE_KEY
            )
            if payload is not None:
                observed[key].add(payload)
                reads += 1
    connection.send(({key: sorted(values) for key, values in observed.items()}, reads))
    local.close()
    endpoint.close()


def test_concurrent_readers_never_observe_torn_payloads(
    start_owner: Callable[..., Owner],
    open_endpoint: Callable[[Owner], SyncEndpoint],
    seeded_database: str,
) -> None:
    owner = start_owner(
        shared_index=_SHARED_INDEX,
        budget_bytes=_STRESS_BUDGET,
        max_entry_bytes=_STRESS_MAX_ENTRY,
    )
    endpoint = open_endpoint(owner)
    metadata = _shared_metadata(endpoint, seeded_database)
    context = multiprocessing.get_context("spawn")
    readers = []
    for _ in range(_STRESS_READERS):
        parent, child = context.Pipe()
        process = context.Process(
            target=_stress_reader,
            args=(child, owner.attachment(), seeded_database, _STRESS_KEYS),
        )
        process.start()
        child.close()
        assert parent.recv() == "reading"
        readers.append((process, parent))
    published: dict[int, set[bytes]] = {key: set() for key in range(_STRESS_KEYS)}

    for churn in range(_STRESS_ROUNDS):
        for key in range(_STRESS_KEYS):
            reply = endpoint.request(
                {
                    "op": "select-identity",
                    "ns": [seeded_database, COLLECTION],
                    "epoch": metadata["epoch"],
                    "identity": _local_key(key),
                    "shape": _SHAPE_KEY,
                }
            )
            assert reply is not None
            if reply["r"] != "miss":
                continue
            value = f"{key}:{churn}:".encode() * (_STRESS_REPEAT + churn % 7 * 11)
            published[key].add(value)
            endpoint.send({"op": "admit", "handle": reply["handle"], "value": value})
    reports = []
    for process, parent in readers:
        parent.send("stop")
        reports.append(parent.recv())
        process.join(10)

    assert sum(reads for _observed, reads in reports) > 0
    for observed, _reads in reports:
        verify_published_payloads(
            {key: set(values) for key, values in observed.items()}, published
        )


def test_publication_capacity_bounds_shared_state(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner(shared_index=_FEW_SLOTS)
    manager = open_manager(client, owner, local=True)
    ready(manager, seeded_database)
    first = [
        manager[seeded_database][COLLECTION].find_one({"_id": key})
        for key in range(DOCUMENTS)
    ]
    wait_for(lambda: owner.counters()["admitted"] == DOCUMENTS)
    requests = manager.endpoint.counters.requests

    second = [
        manager[seeded_database][COLLECTION].find_one({"_id": key})
        for key in range(DOCUMENTS)
    ]

    published = owner.observation()["shared_index"]["published"]
    assert second == first
    assert published == _FEW_SLOTS.slots * 3 // 4
    assert manager.endpoint.counters.requests == requests + DOCUMENTS - published
    assert manager.observation.hits == DOCUMENTS


@pytest.mark.parametrize("race", ["write", "eviction"])
def test_an_admission_raced_by_a_write_or_eviction_is_never_published(
    shared_reads: tuple[SharedCacheManager[BsonDict], Owner],
    seeded_database: str,
    race: str,
) -> None:
    manager, owner = shared_reads
    owner.request("race-admission", race=race)
    admissions = owner.counters()["admissions"]

    document = manager[seeded_database][COLLECTION].find_one({"_id": 5})
    wait_for(lambda: owner.counters()["admissions"] > admissions)

    assert document == {"_id": 5, "payload": "value-5", "revision": 0}
    assert _local_read(manager, seeded_database, 5) is None


def _received_descriptors(config: AttachmentConfig) -> tuple[socket.socket, list[int]]:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.connect(config.socket_path)
    peer.sendall(encode_frame(config.hello("control")))
    _data, descriptors, _flags, _address = socket.recv_fds(peer, 65_536, 4)
    return peer, descriptors


def _write_directly(descriptor: int) -> None:
    os.write(descriptor, b"x")


def _map_writable(descriptor: int) -> None:
    mmap.mmap(descriptor, os.fstat(descriptor).st_size, mmap.MAP_SHARED)


def _upgrade_mapping(descriptor: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = (
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_long,
    )
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    size = os.fstat(descriptor).st_size
    address = libc.mmap(None, size, mmap.PROT_READ, mmap.MAP_SHARED, descriptor, 0)
    assert address != ctypes.c_void_p(-1).value
    ctypes.set_errno(0)
    libc.mprotect(address, size, mmap.PROT_READ | mmap.PROT_WRITE)
    error = ctypes.get_errno()
    libc.munmap(address, size)
    raise OSError(error, os.strerror(error))


def _reopen_writable(descriptor: int) -> None:
    reopened = os.open(f"/proc/self/fd/{descriptor}", os.O_RDWR)
    try:
        os.write(reopened, b"x")
    finally:
        os.close(reopened)


@pytest.fixture
def index_descriptor(
    shared_reads: tuple[SharedCacheManager[BsonDict], Owner],
) -> Iterator[int]:
    _manager, owner = shared_reads
    peer, descriptors = _received_descriptors(owner.attachment())
    yield descriptors[0]
    for descriptor in descriptors:
        os.close(descriptor)
    peer.close()


@pytest.mark.parametrize(
    "attempt",
    [
        pytest.param(_write_directly, id="write"),
        pytest.param(_map_writable, id="writable-mapping"),
        pytest.param(_upgrade_mapping, id="mprotect"),
        pytest.param(_reopen_writable, id="reopened-descriptor"),
    ],
)
def test_workers_cannot_modify_the_published_index(
    shared_reads: tuple[SharedCacheManager[BsonDict], Owner],
    index_descriptor: int,
    seeded_database: str,
    attempt: Callable[[int], None],
) -> None:
    manager, owner = shared_reads
    payload = _prime(manager, owner, seeded_database, 1)

    with pytest.raises(OSError, match=_DENIED):
        attempt(index_descriptor)

    assert _local_read(manager, seeded_database, 1) == payload

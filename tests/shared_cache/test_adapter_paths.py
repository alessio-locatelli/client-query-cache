from __future__ import annotations

import asyncio
import os
import signal
import threading
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, cast

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from benchmarks.stream_cost.shared_cache import adapters
from benchmarks.stream_cost.shared_cache.adapters import (
    UNPORTABLE_KEY,
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from benchmarks.stream_cost.shared_cache.attachment import (
    AsyncEndpoint,
    AttachmentConfigurationError,
    SyncEndpoint,
)
from benchmarks.stream_cost.shared_cache.wire import encode_key
from client_query_cache._core import canonical
from client_query_cache._types import BsonDict, NonNegativeInt
from tests.codec_helpers import Decimal128ToDecimalDecoder
from tests.cursor_helpers import materialize
from tests.polling import wait_until_async
from tests.shared_cache.conftest import (
    COLLECTION,
    DOCUMENTS,
    async_shared_manager,
    ready,
    select_identity,
    wait_for,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from benchmarks.stream_cost.shared_cache.adapters import (
        AsyncSharedCachedCollection,
        SharedCachedCollection,
    )
    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner

pytestmark = pytest.mark.integration

_INVALID_PROJECTION = {"payload": 1, "revision": 0}
_SORTED = {"sort": [("_id", 1)]}


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as raw:
        yield raw


def _custom_codec() -> CodecOptions[BsonDict]:
    return CodecOptions(type_registry=TypeRegistry([Decimal128ToDecimalDecoder()]))


def test_oversized_find_results_are_not_admitted(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    client[seeded_database]["large"].insert_many(
        {"_id": index, "payload": "x" * 16_384} for index in range(8)
    )
    client[seeded_database]["large"].insert_one(
        {"_id": "big", "payload": "x" * 100_000}
    )
    owner = start_owner(max_entry_bytes=64 * 1024)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)
    cursor = manager[seeded_database]["large"].find({}, **_SORTED, limit=8)

    documents = cursor.to_list()
    cursor.close()

    big = manager[seeded_database]["large"].find_one({"_id": "big"})
    after = manager[seeded_database]["large"].find_one({"_id": 0})

    assert len(documents) == 8
    assert big is not None
    assert after is not None
    assert manager.observation.bypasses["oversized"] == 2
    assert owner.counters()["detached"] == 0
    wait_for(lambda: owner.observation()["captures"] == 0)
    wait_for(lambda: owner.counters()["admitted"] == 1)
    assert owner.observation()["cache"]["entry_count"] == 1
    manager.close()


def test_unportable_and_bypassed_finds_execute_natively(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)
    custom = client[seeded_database].get_collection(
        COLLECTION, codec_options=_custom_codec()
    )

    unportable = manager.get_cached_collection(custom).find({}).to_list()
    subcollection = manager[seeded_database][COLLECTION]["sub"]

    async def asynchronous() -> AsyncSharedCacheManager[BsonDict]:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            view = async_manager.get_cached_collection(
                async_manager.client[seeded_database].get_collection(
                    COLLECTION, codec_options=_custom_codec()
                )
            )
            assert len(await view.find({}).to_list()) == DOCUMENTS
            hinted = async_manager[seeded_database][COLLECTION].find(
                {}, hint=[("_id", 1)]
            )
            assert len(await hinted.to_list()) == DOCUMENTS
            with pytest.raises(ValueError, match="different client"):
                async_manager.get_cached_collection(client[seeded_database][COLLECTION])  # type: ignore[arg-type]
        return async_manager

    async_manager = asyncio.run(asynchronous())

    assert len(unportable) == DOCUMENTS
    assert subcollection.name == f"{COLLECTION}.sub"
    assert manager.observation.bypasses[UNPORTABLE_KEY] == 1
    assert async_manager.observation.bypasses[UNPORTABLE_KEY] == 1
    assert sum(async_manager.observation.bypasses.values()) == 2
    with (
        MongoClient[BsonDict](mongodb_uri) as other,
        pytest.raises(ValueError, match="different client"),
    ):
        manager.get_cached_collection(other[seeded_database][COLLECTION])
    manager.close()


def test_unlimited_find_hits_return_the_complete_result(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)

    collection.find({}, **_SORTED).to_list()
    wait_for(lambda: owner.counters()["admitted"] == 1)
    hit = collection.find({}, **_SORTED).to_list()

    assert len(hit) == DOCUMENTS
    assert manager.observation.hits == 1
    manager.close()


def test_owner_bypasses_reach_find_one_and_find(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    owner.request("pause-watch")

    wait_for(
        lambda: (
            collection.find_one({"_id": 20}) is not None
            and "progress-expired" in manager.observation.bypasses
        )
    )
    documents = collection.find({}, **_SORTED, limit=2).to_list()
    owner.request("resume-watch")

    assert len(documents) == 2
    assert manager.observation.bypasses["progress-expired"] >= 2
    manager.close()


def test_exhausted_captures_leave_reads_native(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner(captures=1)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    held = select_identity(manager.endpoint, manager, seeded_database, 21)

    document = collection.find_one({"_id": 22})
    documents = collection.find({}, **_SORTED, limit=3).to_list()

    async def asynchronous() -> object:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            return await async_manager[seeded_database][COLLECTION].find_one(
                {"_id": 23}
            )

    assert held is not None
    assert held["handle"] is not None
    assert document is not None
    assert len(documents) == 3
    assert asyncio.run(asynchronous()) is not None
    assert owner.counters()["capture_limit_misses"] == 3
    assert owner.counters()["admitted"] == 0
    manager.close()


def test_failed_native_reads_release_their_captures(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner()
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)

    with pytest.raises(OperationFailure):
        manager[seeded_database][COLLECTION].find_one({"_id": 24}, _INVALID_PROJECTION)

    async def asynchronous() -> None:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            with pytest.raises(OperationFailure):
                await async_manager[seeded_database][COLLECTION].find_one(
                    {"_id": 24}, _INVALID_PROJECTION
                )

    asyncio.run(asynchronous())

    wait_for(lambda: owner.observation()["captures"] == 0)
    assert owner.counters()["misses"] == 2
    manager.close()


def test_large_hits_are_reassembled_from_partial_reads(
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    client[seeded_database][COLLECTION].insert_one(
        {"_id": "large", "payload": "x" * 600_000, "revision": 0}
    )
    owner = start_owner(queued_bytes_per_connection=4 * 1024 * 1024)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)

    collection.find_one({"_id": "large"})
    wait_for(lambda: owner.counters()["admitted"] == 1)
    document = collection.find_one({"_id": "large"})

    assert document == {"_id": "large", "payload": "x" * 600_000, "revision": 0}
    assert manager.observation.hits == 1
    manager.close()


def test_sync_endpoints_drop_one_way_messages_without_a_connection(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()
    endpoint = SyncEndpoint(owner.attachment())
    other_thread = threading.Thread(
        target=endpoint.send, args=({"op": "discard", "handle": 1},)
    )

    other_thread.start()
    other_thread.join()
    os.kill(owner.pid, signal.SIGKILL)
    owner.process.join(10)
    endpoint.send({"op": "discard", "handle": 2})
    after_failure = endpoint.request({"op": "observe"})
    endpoint.close()
    after_close = endpoint.request({"op": "observe"})

    assert endpoint.counters.dropped_one_way == 2
    assert after_failure is None
    assert after_close is None


def test_async_endpoints_report_unreachable_or_conflicting_owners(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner()

    async def scenario() -> None:
        with pytest.raises(AttachmentConfigurationError, match="configuration"):
            await AsyncEndpoint.attach(owner.attachment(budget_bytes=1))
        with pytest.raises(AttachmentConfigurationError, match="not reachable"):
            await AsyncEndpoint.attach(
                owner.attachment(socket_path=owner.config.socket_path + ".missing")
            )
        detached = AsyncEndpoint(owner.attachment())
        detached.send({"op": "discard", "handle": 1})
        await detached.close()
        assert detached.counters.dropped_one_way == 1

    asyncio.run(scenario())


def test_async_requests_survive_owner_pauses_and_loss(
    start_owner: Callable[..., Owner], seeded_database: str, mongodb_uri: MongoDbUri
) -> None:
    owner = start_owner()

    async def scenario() -> tuple[object, ...]:
        async with async_shared_manager(owner, mongodb_uri) as manager:
            collection = manager[seeded_database][COLLECTION]
            while await collection._cache_ineligibility_reason() is not None:  # noqa: ASYNC110
                await asyncio.sleep(0.02)
            await collection.find_one({"_id": 25})
            endpoint = manager.endpoint
            shape = encode_key(collection._find_one_default_shape)
            namespace = next(iter(manager._metadata))
            hit_request = {
                "op": "select-identity",
                "ns": [seeded_database, COLLECTION],
                "epoch": manager._metadata[namespace].checked_epoch,
                "identity": encode_key(25),
                "shape": shape,
            }
            owner.request("pause-server", seconds=0.3)
            late_hit = asyncio.create_task(endpoint.request(dict(hit_request)))
            await asyncio.sleep(0.05)
            late_hit.cancel()
            await asyncio.sleep(0.5)
            fresh = AsyncEndpoint(owner.attachment())
            owner.request("pause-server", seconds=1.0)
            connecting = await fresh.request({"op": "observe"})
            await asyncio.sleep(1.0)
            owner.request("pause-server", seconds=0.3)
            in_flight = asyncio.create_task(endpoint.request(dict(hit_request)))
            await asyncio.sleep(0.05)
            os.kill(owner.pid, signal.SIGKILL)
            lost = await in_flight
            retried = await endpoint.request(dict(hit_request))
            counters = endpoint.counters
        await fresh.close()
        return counters.late_replies, connecting, lost, retried, counters.failures

    late, connecting, lost, retried, failures = asyncio.run(scenario())
    owner.process.join(10)

    assert late == 1
    assert connecting is None
    assert lost is None
    assert retried is None
    assert cast("int", failures) >= 1


def test_connections_of_finished_threads_are_released(
    start_owner: Callable[..., Owner],
) -> None:
    owner = start_owner(connections=4)
    endpoint = SyncEndpoint(owner.attachment())

    for _ in range(6):
        worker = threading.Thread(target=endpoint.request, args=({"op": "observe"},))
        worker.start()
        worker.join()

    wait_for(lambda: owner.observation()["connections"] == 1)
    assert endpoint.counters.connects == 7
    assert endpoint.counters.failures == 0
    endpoint.close()


@pytest.fixture(params=("sync", "async"))
async def shared_find_view(
    request: pytest.FixtureRequest,
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[
    tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict],
        Owner,
    ]
]:
    owner = start_owner()
    async with AsyncExitStack() as stack:
        if request.param == "sync":
            manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
            stack.callback(manager.close)
            view: (
                SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict]
            ) = manager[seeded_database][COLLECTION]
        else:
            async_manager = await stack.enter_async_context(
                async_shared_manager(owner, mongodb_uri)
            )
            view = async_manager[seeded_database][COLLECTION]

        async def warm() -> bool:
            before = view._shared.observation.hits
            assert await materialize(view.find({"_id": "warmup"})) == []
            return view._shared.observation.hits > before

        await wait_until_async(warm)
        yield view, owner


@pytest.mark.parametrize("hit_limit", [8, 4], ids=["exact", "compatible"])
async def test_shared_find_reuses_prepared_family(
    shared_find_view: tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict],
        Owner,
    ],
    raw_key_traversals: list[NonNegativeInt],
    monkeypatch: pytest.MonkeyPatch,
    hit_limit: NonNegativeInt,
) -> None:
    view, owner = shared_find_view
    monkeypatch.setattr(adapters, "canonicalize", canonical.canonicalize)
    raw_key_traversals.clear()
    admitted = owner.counters()["admitted"]
    query = {"revision": {"$in": [0, 1, 2]}}
    hits = view._shared.observation.hits
    misses = view._shared.observation.misses

    complete = await materialize(view.find(query, **_SORTED, limit=8))
    wait_for(lambda: owner.counters()["admitted"] == admitted + 1)
    hit = await materialize(view.find(query, **_SORTED, limit=hit_limit))

    assert view._shared.observation.hits == hits + 1
    assert view._shared.observation.misses == misses + 1
    assert [document["_id"] for document in complete] == list(range(8))
    assert [document["_id"] for document in hit] == list(range(hit_limit))
    assert raw_key_traversals == [1, 1]

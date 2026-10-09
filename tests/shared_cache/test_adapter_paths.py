from __future__ import annotations

import asyncio
import os
import signal
import threading
from typing import TYPE_CHECKING, Any, cast

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import OperationFailure

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

    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner

pytestmark = pytest.mark.integration

_INVALID_PROJECTION = {"payload": 1, "revision": 0}
_SORTED = {"sort": [("_id", 1)]}


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as raw:
        yield raw


def _custom_codec() -> CodecOptions[dict[str, Any]]:
    return CodecOptions(type_registry=TypeRegistry([Decimal128ToDecimalDecoder()]))


def test_oversized_find_results_are_not_admitted(
    client: MongoClient[dict[str, Any]],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    client[seeded_database]["large"].insert_many(
        {"_id": index, "payload": "x" * 16_384} for index in range(8)
    )
    owner = start_owner(max_entry_bytes=64 * 1024)
    manager = SharedCacheManager(client, SyncEndpoint(owner.attachment()))
    ready(manager, seeded_database)
    cursor = manager[seeded_database]["large"].find({}, **_SORTED, limit=8)

    documents = cursor.to_list()
    cursor.close()

    assert len(documents) == 8
    assert manager.observation.bypasses["oversized"] == 1
    wait_for(lambda: owner.observation()["captures"] == 0)
    assert owner.observation()["cache"]["entry_count"] == 0
    manager.close()


def test_unportable_and_bypassed_finds_execute_natively(
    client: MongoClient[dict[str, Any]],
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

    async def asynchronous() -> AsyncSharedCacheManager[dict[str, Any]]:
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        async_manager = AsyncSharedCacheManager(
            async_client, await AsyncEndpoint.attach(owner.attachment())
        )
        view = async_manager.get_cached_collection(
            async_client[seeded_database].get_collection(
                COLLECTION, codec_options=_custom_codec()
            )
        )
        assert len(await view.find({}).to_list()) == DOCUMENTS
        hinted = async_manager[seeded_database][COLLECTION].find({}, hint=[("_id", 1)])
        assert len(await hinted.to_list()) == DOCUMENTS
        with pytest.raises(ValueError, match="different client"):
            async_manager.get_cached_collection(client[seeded_database][COLLECTION])  # type: ignore[arg-type]
        await async_manager.close()
        await async_client.close()
        return async_manager

    async_manager = asyncio.run(asynchronous())

    assert len(unportable) == DOCUMENTS
    assert subcollection.name == f"{COLLECTION}.sub"
    assert manager.observation.bypasses[UNPORTABLE_KEY] == 1
    assert async_manager.observation.bypasses[UNPORTABLE_KEY] == 1
    assert sum(async_manager.observation.bypasses.values()) == 2
    with (
        MongoClient[dict[str, Any]](mongodb_uri) as other,
        pytest.raises(ValueError, match="different client"),
    ):
        manager.get_cached_collection(other[seeded_database][COLLECTION])
    manager.close()


def test_unlimited_find_hits_return_the_complete_result(
    client: MongoClient[dict[str, Any]],
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
    client: MongoClient[dict[str, Any]],
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
    client: MongoClient[dict[str, Any]],
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
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        async_manager = AsyncSharedCacheManager(
            async_client, await AsyncEndpoint.attach(owner.attachment())
        )
        read = await async_manager[seeded_database][COLLECTION].find_one({"_id": 23})
        await async_manager.close()
        await async_client.close()
        return read

    assert held is not None
    assert held["handle"] is not None
    assert document is not None
    assert len(documents) == 3
    assert asyncio.run(asynchronous()) is not None
    assert owner.counters()["capture_limit_misses"] == 3
    assert owner.counters()["admitted"] == 0
    manager.close()


def test_failed_native_reads_release_their_captures(
    client: MongoClient[dict[str, Any]],
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
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        async_manager = AsyncSharedCacheManager(
            async_client, await AsyncEndpoint.attach(owner.attachment())
        )
        try:
            with pytest.raises(OperationFailure):
                await async_manager[seeded_database][COLLECTION].find_one(
                    {"_id": 24}, _INVALID_PROJECTION
                )
        finally:
            await async_manager.close()
            await async_client.close()

    asyncio.run(asynchronous())

    wait_for(lambda: owner.observation()["captures"] == 0)
    assert owner.counters()["misses"] == 2
    manager.close()


def test_large_hits_are_reassembled_from_partial_reads(
    client: MongoClient[dict[str, Any]],
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

    assert document is not None
    assert len(document["payload"]) == 600_000
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
        async_client = AsyncMongoClient[dict[str, Any]](mongodb_uri)
        manager = AsyncSharedCacheManager(
            async_client, await AsyncEndpoint.attach(owner.attachment())
        )
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
        await manager.close()
        await async_client.close()
        await fresh.close()
        return counters.late_replies, connecting, lost, retried, counters.failures

    late, connecting, lost, retried, failures = asyncio.run(scenario())
    owner.process.join(10)

    assert late == 1
    assert connecting is None
    assert lost is None
    assert retried is None
    assert cast("int", failures) >= 1

from __future__ import annotations

import asyncio
import errno
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from bson.int64 import Int64
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import OperationFailure
from pymongo.synchronous.collection import Collection

from client_query_cache._core import canonical
from client_query_cache._core.collection_metadata import CollectionProbeResult
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.snapshots import BypassReason
from client_query_cache._shared import adapters, attachment
from client_query_cache._shared.adapters import (
    METADATA_REFRESH,
    OWNER_UNAVAILABLE,
    UNPORTABLE_KEY,
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AsyncLocalIndex,
    AttachmentConfig,
    AttachmentConfigurationError,
    LocalIndex,
    SyncEndpoint,
)
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._shared.wire import (
    LENGTH_BYTES,
    ProtocolError,
    encode_frame,
    encode_key,
    frame_length,
)
from client_query_cache._shared_index import OwnerIndex
from client_query_cache._types import BsonDict, NonNegativeInt
from tests.call_counting import count_current_thread_calls
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
    from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping

    from faker import Faker

    from client_query_cache._shared.adapters import (
        AsyncSharedCachedCollection,
        SharedCachedCollection,
    )
    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner

pytestmark = pytest.mark.integration

_INVALID_PROJECTION = {"payload": 1, "revision": 0}
_SORTED = {"sort": [("_id", 1)]}
_SHARED_INDEX = SharedIndexLimits(
    slots=256, arena_bytes=4 * 1024 * 1024, namespaces=4, ring_tokens=1024
)
_TINY_ARENA = SharedIndexLimits(
    slots=256, arena_bytes=64, namespaces=4, ring_tokens=1024
)
_INCARNATION = 0x5EED
_SPLIT_AT = 3
_SPLIT_PAUSE_SECONDS = 0.05
_LOOP_TURN_SECONDS = 0.01
_FRAME_EXCEEDING_ID_BYTES = 600_000
_CONCURRENT_READS = 8
# Long enough that every concurrent reader reaches reattachment while one attach runs.
_SLOW_ATTACH_SECONDS = 0.3
# Past the adapters' 100 ms reattachment back-off after the owner disappeared.
_PAST_REATTACH_BACKOFF_SECONDS = 0.15
_OTHER = "other"


@pytest.fixture
def client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as raw:
        yield raw


def _custom_codec() -> CodecOptions[BsonDict]:
    return CodecOptions(type_registry=TypeRegistry([Decimal128ToDecimalDecoder()]))


def test_oversized_find_results_are_not_admitted(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
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
    manager = open_manager(client, owner)
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


def test_unportable_and_bypassed_finds_execute_natively(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
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


def test_unlimited_find_hits_return_the_complete_result(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)

    collection.find({}, **_SORTED).to_list()
    wait_for(lambda: owner.counters()["admitted"] == 1)
    hit = collection.find({}, **_SORTED).to_list()

    assert len(hit) == DOCUMENTS
    assert manager.observation.hits == 1


def test_owner_bypasses_reach_find_one_and_find(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
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


def test_exhausted_captures_leave_reads_native(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner(captures=1)
    manager = open_manager(client, owner)
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)
    held = select_identity(manager.endpoint, manager, seeded_database, 21)

    document = collection.find_one({"_id": 22})
    documents = collection.find({}, **_SORTED, limit=3).to_list()
    assert collection.count_documents({}) == DOCUMENTS
    assert len(collection.aggregate([{"$limit": 3}]).to_list()) == 3

    async def asynchronous() -> object:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            view = async_manager[seeded_database][COLLECTION]
            document = await view.find_one({"_id": 23})
            assert await view.count_documents({}) == DOCUMENTS
            cursor = await view.aggregate([{"$limit": 3}])
            assert len(await cursor.to_list()) == 3
            return document

    assert held is not None
    assert held["handle"] is not None
    assert document is not None
    assert len(documents) == 3
    assert asyncio.run(asynchronous()) is not None
    assert owner.counters()["capture_limit_misses"] == 7
    assert owner.counters()["admitted"] == 0


def test_failed_native_reads_release_their_captures(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
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


def test_large_hits_are_reassembled_from_partial_reads(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
) -> None:
    client[seeded_database][COLLECTION].insert_one(
        {"_id": "large", "payload": "x" * 600_000, "revision": 0}
    )
    owner = start_owner(queued_bytes_per_connection=4 * 1024 * 1024)
    manager = open_manager(client, owner)
    collection = manager[seeded_database][COLLECTION]
    ready(manager, seeded_database)

    collection.find_one({"_id": "large"})
    wait_for(lambda: owner.counters()["admitted"] == 1)
    document = collection.find_one({"_id": "large"})

    assert document == {"_id": "large", "payload": "x" * 600_000, "revision": 0}
    assert manager.observation.hits == 1


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
            while await collection._cache_ineligibility_reason() is not None:  # noqa: ASYNC110 - Readiness has no event to await.
                await asyncio.sleep(0.02)
            await collection.find_one({"_id": 25})
            endpoint = manager.endpoint
            shape = encode_key(collection._find_one_default_shape)
            namespace = NamespaceId(seeded_database, COLLECTION)
            metadata = manager._metadata.find(namespace)
            assert metadata is not None
            hit_request = {
                "op": "select-identity",
                "ns": [seeded_database, COLLECTION],
                "epoch": metadata.checked_epoch,
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
    start_owner: Callable[..., Owner], open_endpoint: Callable[[Owner], SyncEndpoint]
) -> None:
    owner = start_owner(connections=4)
    endpoint = open_endpoint(owner)

    for _ in range(6):
        worker = threading.Thread(target=endpoint.request, args=({"op": "observe"},))
        worker.start()
        worker.join()

    wait_for(lambda: owner.observation()["connections"] == 1)
    assert endpoint.counters.connects == 7
    assert endpoint.counters.failures == 0


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


class _SharedReads:
    __slots__ = ("_async_client", "_client", "_database", "_runner", "manager")

    def __init__(self, model: str, owner: Owner, uri: str, database: str) -> None:
        self._database = database
        config = owner.attachment()
        self._client: MongoClient[BsonDict] | None = None
        self._async_client: AsyncMongoClient[BsonDict] | None = None
        self._runner: asyncio.Runner | None = None
        self.manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]
        if model == "sync":
            self._client = MongoClient[BsonDict](uri)
            self.manager = SharedCacheManager(
                self._client, SyncEndpoint(config), LocalIndex.attach(config)
            )
        else:
            self._runner = asyncio.Runner()
            self._async_client = AsyncMongoClient[BsonDict](uri)
            self.manager = AsyncSharedCacheManager(
                self._async_client,
                self._run(AsyncEndpoint.attach(config)),
                self._run(AsyncLocalIndex.attach(config)),
            )
        self.ready()

    def _run[T](self, coroutine: Coroutine[object, object, T]) -> T:
        assert self._runner is not None
        return self._runner.run(coroutine)

    def ready(self) -> None:
        manager = self.manager
        if isinstance(manager, SharedCacheManager):
            ready(manager, self._database)
            return
        collection = manager[self._database][COLLECTION]
        wait_for(lambda: self._run(collection._cache_ineligibility_reason()) is None)

    def find_one(
        self,
        key: object,
        collection: str = COLLECTION,
        *,
        projection: Mapping[str, object] | None = None,
    ) -> BsonDict | None:
        manager = self.manager
        if isinstance(manager, SharedCacheManager):
            return manager[self._database][collection].find_one(
                {"_id": key}, projection
            )
        return self._run(
            manager[self._database][collection].find_one({"_id": key}, projection)
        )

    def find_concurrently(self, key: object, count: int) -> list[BsonDict | None]:
        manager = self.manager
        if isinstance(manager, SharedCacheManager):
            with ThreadPoolExecutor(max_workers=count) as pool:
                return list(pool.map(self.find_one, [key] * count))
        collection = manager[self._database][COLLECTION]

        async def gather() -> list[BsonDict | None]:
            return await asyncio.gather(
                *(collection.find_one({"_id": key}) for _ in range(count))
            )

        return self._run(gather())

    def reattach_from(self, local: object) -> None:
        manager = self.manager
        if isinstance(manager, SharedCacheManager):
            assert isinstance(local, LocalIndex)
            manager._reattach_local(local)
            return
        assert isinstance(local, AsyncLocalIndex)
        self._run(manager._reattach_local(local))

    def disconnect_data(self) -> None:
        endpoint = self.manager.endpoint
        if isinstance(endpoint, SyncEndpoint):
            endpoint._drop()
            return

        async def abandon() -> None:
            writer = endpoint._writer
            assert writer is not None
            endpoint._abandon(writer)
            await writer.wait_closed()

        self._run(abandon())

    def close_endpoint(self) -> None:
        endpoint = self.manager.endpoint
        if isinstance(endpoint, SyncEndpoint):
            endpoint.close()
        else:
            self._run(endpoint.close())

    @property
    def detached(self) -> bool:
        if self._runner is not None:
            self._run(asyncio.sleep(_LOOP_TURN_SECONDS))
        assert self.manager.local is not None
        return self.manager.local.reader.detached

    def close(self) -> None:
        manager = self.manager
        if isinstance(manager, SharedCacheManager):
            manager.close()
            assert self._client is not None
            self._client.close()
            return
        self._run(manager.close())
        assert self._async_client is not None
        self._run(self._async_client.close())
        assert self._runner is not None
        self._runner.close()


@pytest.fixture(params=["sync", "async"])
def open_reads(
    request: pytest.FixtureRequest,
    start_owner: Callable[..., Owner],
    mongodb_uri: MongoDbUri,
    seeded_database: str,
) -> Iterator[Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]]]:
    opened: list[_SharedReads] = []

    def open_reads(limits: SharedIndexLimits) -> tuple[Owner, _SharedReads]:
        owner = start_owner(shared_index=limits)
        reads = _SharedReads(request.param, owner, mongodb_uri, seeded_database)
        opened.append(reads)
        return owner, reads

    yield open_reads
    for reads in opened:
        reads.close()


def _admitted(owner: Owner, count: int) -> None:
    wait_for(lambda: owner.counters()["admitted"] == count)


def test_admitted_identity_hits_are_served_locally(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    owner, reads = open_reads(_SHARED_INDEX)
    first = [reads.find_one(key) for key in range(DOCUMENTS)]
    _admitted(owner, DOCUMENTS)
    requests = reads.manager.endpoint.counters.requests

    second = [reads.find_one(key) for key in range(DOCUMENTS)]

    assert second == first
    assert [document["_id"] for document in first if document] == list(range(DOCUMENTS))
    assert reads.manager.endpoint.counters.requests == requests
    assert reads.manager.observation.hits == DOCUMENTS
    assert reads.manager.observation.misses == DOCUMENTS
    counters = reads.manager.endpoint.counters
    assert (counters.failures, counters.timeouts) == (0, 0)
    assert not reads.detached


@pytest.mark.parametrize("native_queue", [False, True], ids=("socket", "native-queue"))
def test_local_misses_read_through_without_selection_or_capture_handles(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    native_queue: bool,
) -> None:
    owner, reads = open_reads(
        replace(
            _SHARED_INDEX,
            local_miss_admission=True,
            native_admission_queue=native_queue,
        )
    )
    requests = reads.manager.endpoint.counters.requests
    first = [reads.find_one(key) for key in range(DOCUMENTS)]
    _admitted(owner, DOCUMENTS)
    assert reads.manager.endpoint.counters.requests == requests
    assert owner.counters()["misses"] == 0
    assert owner.observation()["captures"] == 0
    assert [reads.find_one(key) for key in range(DOCUMENTS)] == first
    assert reads.manager.observation.hits == DOCUMENTS
    assert reads.manager.observation.misses == DOCUMENTS
    assert reads.manager.endpoint.counters.native_admissions == (
        DOCUMENTS if native_queue else 0
    )


def test_failed_locally_captured_reads_need_no_discard(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    owner, reads = open_reads(replace(_SHARED_INDEX, local_miss_admission=True))
    requests = reads.manager.endpoint.counters.requests
    with pytest.raises(OperationFailure):
        reads.find_one(0, projection=_INVALID_PROJECTION)
    assert reads.manager.endpoint.counters.requests == requests
    assert owner.counters()["admissions"] == 0
    assert owner.observation()["captures"] == 0


@pytest.mark.parametrize("native_queue", [False, True], ids=("socket", "native-queue"))
def test_local_misses_in_new_threads_connect_only_for_socket_admission(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    native_queue: bool,
) -> None:
    owner, reads = open_reads(
        replace(
            _SHARED_INDEX,
            local_miss_admission=True,
            native_admission_queue=native_queue,
        )
    )
    requests = reads.manager.endpoint.counters.requests
    connects = reads.manager.endpoint.counters.connects

    first = reads.find_concurrently(0, 1)
    _admitted(owner, 1)

    assert first == [reads.find_one(0)]
    new_thread = isinstance(reads.manager, SharedCacheManager) and not native_queue
    assert reads.manager.endpoint.counters.requests == requests + new_thread
    assert reads.manager.endpoint.counters.connects == connects + new_thread
    assert reads.manager.observation.hits == 1
    assert reads.manager.endpoint.counters.native_admissions == int(native_queue)


@pytest.mark.parametrize("native_queue", [False, True], ids=("socket", "native-queue"))
def test_local_misses_use_the_control_queue_or_reconnect_after_data_channel_loss(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    native_queue: bool,
) -> None:
    owner, reads = open_reads(
        replace(
            _SHARED_INDEX,
            local_miss_admission=True,
            native_admission_queue=native_queue,
        )
    )
    endpoint = reads.manager.endpoint
    requests = endpoint.counters.requests
    connects = endpoint.counters.connects
    reads.disconnect_data()

    wait_for(
        lambda: (
            reads.find_one(0) is not None
            and (native_queue or endpoint.counters.connects > connects)
        )
    )
    _admitted(owner, 1)

    assert reads.find_one(0) is not None
    assert endpoint.counters.requests == requests + int(not native_queue)
    assert endpoint.counters.connects == connects + int(not native_queue)
    assert endpoint.counters.native_admissions == int(native_queue)
    assert reads.manager.observation.hits == 1
    assert not reads.detached


@pytest.mark.parametrize(
    ("queue_drop", "recovered", "expired"),
    [
        (False, False, False),
        (True, False, False),
        (True, True, False),
        (True, True, True),
    ],
    ids=("other-drop", "queue-full", "queue-recovered", "recovery-expired"),
)
def test_only_active_queue_recovery_makes_disconnected_misses_reconnect(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    queue_drop: bool,
    recovered: bool,
    expired: bool,
) -> None:
    owner, reads = open_reads(
        replace(_SHARED_INDEX, local_miss_admission=True, native_admission_queue=True)
    )
    endpoint = reads.manager.endpoint
    requests = endpoint.counters.requests
    connects = endpoint.counters.connects
    reads.disconnect_data()
    time.sleep(_PAST_REATTACH_BACKOFF_SECONDS)
    endpoint.counters.dropped_one_way = 1
    if queue_drop:
        endpoint.admission_recovery.dropped()
    if recovered:
        assert endpoint.admission_recovery.enqueued(
            endpoint.admission_recovery.generation
        )
    if expired:
        time.sleep(_PAST_REATTACH_BACKOFF_SECONDS)
    # Keep diagnostic values independent of policy state.
    endpoint.counters.native_admission_drops = int(expired)
    endpoint.counters.native_admission_recoveries = int(expired)
    reconnect = recovered and not expired

    wait_for(
        lambda: (
            reads.find_one(0) is not None
            and (not reconnect or endpoint.counters.connects > connects)
        )
    )
    _admitted(owner, 1)

    assert reads.find_one(0) is not None
    assert endpoint.counters.requests == requests + int(reconnect)
    assert endpoint.counters.connects == connects + int(reconnect)
    assert endpoint.counters.native_admissions == int(not reconnect)
    assert reads.manager.observation.hits == 1
    assert not reads.detached

    if reconnect:
        requests = endpoint.counters.requests
        assert reads.find_one(1) is not None
        _admitted(owner, 2)
        assert endpoint.counters.requests == requests
        assert endpoint.counters.native_admissions == 1


@pytest.fixture(params=("sync", "async"))
def capacity_reads(
    request: pytest.FixtureRequest,
    start_owner: Callable[..., Owner],
    open_endpoint: Callable[[Owner], SyncEndpoint],
    mongodb_uri: MongoDbUri,
    seeded_database: str,
) -> Iterator[tuple[Owner, _SharedReads]]:
    owner = start_owner(
        connections=2,
        shared_index=replace(
            _SHARED_INDEX, local_miss_admission=True, native_admission_queue=True
        ),
    )
    reads = _SharedReads(request.param, owner, mongodb_uri, seeded_database)
    reads.disconnect_data()
    wait_for(lambda: owner.observation()["connections"] == 1)
    open_endpoint(owner)
    wait_for(lambda: owner.observation()["connections"] == 2)
    time.sleep(_PAST_REATTACH_BACKOFF_SECONDS)
    yield owner, reads
    reads.close()


@pytest.mark.parametrize(
    "pre_accept_refusal", [False, True], ids=("owner", "pre-accept-eagain")
)
def test_recovery_at_owner_connection_capacity_preserves_native_reads(
    capacity_reads: tuple[Owner, _SharedReads],
    monkeypatch: pytest.MonkeyPatch,
    pre_accept_refusal: bool,
) -> None:
    owner, reads = capacity_reads
    endpoint = reads.manager.endpoint
    if pre_accept_refusal:
        # Simulate EAGAIN from a full listener backlog before owner acceptance.
        refusal = BlockingIOError(errno.EAGAIN, "attachment backlog is full")
        if isinstance(endpoint, SyncEndpoint):
            monkeypatch.setattr(SyncEndpoint, "_handshake", Mock(side_effect=refusal))
        else:
            monkeypatch.setattr(
                asyncio, "open_unix_connection", AsyncMock(side_effect=refusal)
            )
    endpoint.admission_recovery.dropped()
    assert endpoint.admission_recovery.enqueued(endpoint.admission_recovery.generation)
    rejected = owner.counters()["connections_rejected"]
    failures_before = endpoint.counters.failures

    documents = reads.find_concurrently(0, _CONCURRENT_READS)
    assert all(document is not None and document["_id"] == 0 for document in documents)

    observation = owner.observation()
    assert observation["connections"] == 2
    refusals = observation["counters"]["connections_rejected"] - rejected
    failures = endpoint.counters.failures
    assert 1 <= failures - failures_before <= _CONCURRENT_READS
    # A full Unix socket backlog can reject connect() before the owner accepts it.
    assert 0 <= refusals <= failures - failures_before
    if pre_accept_refusal:
        assert refusals == 0
    assert not endpoint.connected
    assert observation["captures"] == 0
    time.sleep(_PAST_REATTACH_BACKOFF_SECONDS)
    assert not endpoint.admission_recovery.active
    admitted = observation["counters"]["admitted"]
    hits = reads.manager.observation.hits
    assert reads.find_one(1) is not None
    _admitted(owner, admitted + 1)
    assert reads.find_one(1) is not None
    assert endpoint.counters.failures == failures
    assert owner.observation()["connections"] == 2
    assert reads.manager.observation.hits == hits + 1
    assert not reads.detached


def test_failed_socket_recovery_admits_during_capacity_refusal_and_cooldown(
    capacity_reads: tuple[Owner, _SharedReads],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reads = capacity_reads
    endpoint = reads.manager.endpoint
    # Hold recovery active and keep the refused socket's retry cooldown in effect.
    clock = Mock(monotonic=Mock(return_value=time.monotonic()))
    monkeypatch.setattr(attachment, "time", clock)
    endpoint.admission_recovery.dropped()
    assert endpoint.admission_recovery.enqueued(endpoint.admission_recovery.generation)
    database_reads = count_current_thread_calls(
        monkeypatch,
        Collection
        if isinstance(reads.manager, SharedCacheManager)
        else AsyncCollection,
        "find_one",
    )
    rejected = owner.counters()["connections_rejected"]
    misses = reads.manager.observation.misses

    for count, key in enumerate((0, 1), start=1):
        assert reads.find_one(key) is not None
        _admitted(owner, count)
        assert endpoint.counters.native_admissions == count
        assert database_reads.count == count
        assert reads.manager.observation.misses == misses + count
        assert reads.find_one(key) is not None
        assert database_reads.count == count
        assert endpoint.counters.failures == 1
        assert endpoint.admission_recovery.active

    observation = owner.observation()
    assert observation["connections"] == 2
    assert observation["counters"]["connections_rejected"] == rejected + 1
    assert observation["captures"] == 0
    assert reads.manager.observation.bypasses == {}
    assert not reads.detached


def test_closed_endpoints_drop_native_admissions(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    _owner, reads = open_reads(
        replace(_SHARED_INDEX, local_miss_admission=True, native_admission_queue=True)
    )
    local = reads.manager.local
    assert local is not None
    assert local.reader.admissions_enabled
    reads.close_endpoint()

    reads.manager.endpoint.send({"op": "discard", "handle": 0}, local.reader)

    assert reads.manager.endpoint.counters.native_admissions == 0
    assert reads.manager.endpoint.counters.dropped_one_way == 1


def test_oversized_local_frames_preserve_the_data_channel(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
    faker: Faker,
) -> None:
    identity = faker.pystr(
        min_chars=_FRAME_EXCEEDING_ID_BYTES, max_chars=_FRAME_EXCEEDING_ID_BYTES
    )
    document: BsonDict = {"_id": identity}
    client[seeded_database][COLLECTION].insert_one(document)
    owner, reads = open_reads(replace(_SHARED_INDEX, local_miss_admission=True))

    assert reads.find_one(identity) == document
    assert reads.find_one(identity) == document

    assert reads.manager.endpoint.counters.dropped_one_way == 2
    assert reads.manager.endpoint.connected
    assert owner.counters()["admissions"] == 0
    assert not reads.detached


def test_oversized_local_reads_need_no_discard(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    owner, reads = open_reads(replace(_SHARED_INDEX, local_miss_admission=True))
    reads.manager.max_entry_bytes = 1
    requests = reads.manager.endpoint.counters.requests
    assert reads.find_one(0) is not None
    assert reads.manager.endpoint.counters.requests == requests
    assert owner.counters()["admissions"] == 0
    assert owner.observation()["captures"] == 0


async def test_cancelling_a_local_miss_retains_no_owner_capture(
    start_owner: Callable[..., Owner],
    mongodb_uri: MongoDbUri,
    seeded_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = start_owner(shared_index=replace(_SHARED_INDEX, local_miss_admission=True))
    async with async_shared_manager(owner, mongodb_uri, local=True) as manager:
        collection = manager[seeded_database][COLLECTION]

        async def eligible() -> bool:
            return await collection._cache_ineligibility_reason() is None

        await wait_until_async(eligible)
        started = asyncio.Event()

        async def native_read(
            _collection: object, *_args: object, **_kwargs: object
        ) -> None:
            started.set()
            await asyncio.Future[None]()

        monkeypatch.setattr(AsyncCollection, "find_one", native_read)
        requests = manager.endpoint.counters.requests  # pytriage: TR11 - Baseline.
        async with asyncio.TaskGroup() as group:
            task = group.create_task(collection.find_one({"_id": 0}))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert manager.endpoint.counters.requests == requests
        assert owner.counters()["admissions"] == 0
        assert owner.observation()["captures"] == 0


def test_unpublished_entries_fall_back_to_owner_hits(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    owner, reads = open_reads(_TINY_ARENA)
    first = reads.find_one(1)
    _admitted(owner, 1)
    requests = reads.manager.endpoint.counters.requests

    second = reads.find_one(1)

    assert second == first
    assert reads.manager.endpoint.counters.requests == requests + 1
    assert reads.manager.observation.hits == 1
    assert owner.observation()["shared_index"]["published"] == 0


def test_namespaces_without_a_slot_bypass_with_bounded_owner_state(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
) -> None:
    client[seeded_database][_OTHER].insert_one({"_id": 1, "payload": "other"})
    owner, reads = open_reads(replace(_SHARED_INDEX, namespaces=1))
    view = reads.manager[seeded_database][_OTHER]
    assert (
        adapters._local_select(view, (b"identity", b"shape")) is adapters.NO_LOCAL_HIT
    )
    first = reads.find_one(1, _OTHER)
    assert owner.counters()["admitted"] == 0
    requests = reads.manager.endpoint.counters.requests

    second = reads.find_one(1, _OTHER)

    assert second == first == {"_id": 1, "payload": "other"}
    assert reads.manager.endpoint.counters.requests == requests
    assert reads.manager.observation.hits == 0
    assert reads.manager.observation.bypasses["namespace_capacity"] == 2
    assert reads.manager._metadata._capacity == 1
    assert reads.manager._slots._capacity == 1
    assert len(reads.manager._metadata) <= 1
    assert len(reads.manager._slots) <= 1
    metadata = reads.manager._metadata.find(NamespaceId(seeded_database, _OTHER))
    assert metadata is not None
    assert metadata.bypass_reason is BypassReason.NAMESPACE_CAPACITY


def test_namespaces_without_a_slot_skip_the_collection_probe(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client[seeded_database][_OTHER].insert_one({"_id": 1, "payload": "other"})
    _owner, reads = open_reads(replace(_SHARED_INDEX, namespaces=1))
    collection = reads.manager[seeded_database][_OTHER]
    if isinstance(reads.manager, SharedCacheManager):
        probe = Mock(wraps=collection._probe_collection)
    else:
        probe = AsyncMock(wraps=collection._probe_collection)
    monkeypatch.setattr(type(collection), "_probe_collection", lambda _self: probe())
    requests = reads.manager.endpoint.counters.requests

    assert reads.find_one(1, _OTHER) == {"_id": 1, "payload": "other"}
    assert reads.find_one(1, _OTHER) == {"_id": 1, "payload": "other"}

    assert probe.call_count == 0
    assert reads.manager.endpoint.counters.requests == requests + 1


@pytest.mark.parametrize(
    ("probe_result", "response_and_expected"),
    [
        pytest.param(
            CollectionProbeResult(None, None),
            (
                (
                    {"r": "probe", "probe_token": 0},
                    {"r": "bypass", "reason": "namespace_capacity"},
                ),
                "namespace_capacity",
            ),
            id="capacity-fills-after-probe",
        ),
        pytest.param(
            None,
            (
                ({"r": "probe", "probe_token": 0}, {"r": "ok"}),
                BypassReason.METADATA_UNAVAILABLE,
            ),
            id="probe-fails",
        ),
    ],
)
def test_shared_metadata_probe_handles_capacity_races_and_probe_failures(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    seeded_database: str,
    monkeypatch: pytest.MonkeyPatch,
    probe_result: CollectionProbeResult | None,
    response_and_expected: tuple[tuple[dict[str, object], ...], BypassReason | str],
) -> None:
    _owner, reads = open_reads(_SHARED_INDEX)
    manager = reads.manager
    namespace = NamespaceId(seeded_database, "capacity-race")
    endpoint_type = type(manager.endpoint)
    owner_replies, expected = response_and_expected
    replies = iter(owner_replies)

    def request(_endpoint: object, _message: object) -> object:
        return next(replies)

    if isinstance(manager, SharedCacheManager):
        monkeypatch.setattr(endpoint_type, "request", request)
        reason = manager._cache_ineligibility_reason(namespace, lambda: probe_result)
    else:
        async_request = AsyncMock(side_effect=lambda _message: next(replies))
        monkeypatch.setattr(
            endpoint_type,
            "request",
            lambda _endpoint, message: async_request(message),
        )
        reason = reads._run(
            manager._cache_ineligibility_reason(
                namespace,
                lambda: asyncio.sleep(0, result=probe_result),
            )
        )

    assert reason == expected
    assert manager._metadata.find(namespace) is None


def test_missing_collection_does_not_consume_a_shared_namespace_slot(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
) -> None:
    client[seeded_database][_OTHER].insert_one({"_id": 1, "payload": "other"})
    owner, reads = open_reads(replace(_SHARED_INDEX, namespaces=2))

    assert reads.find_one(0, "not-created") is None
    first = reads.find_one(1, _OTHER)
    _admitted(owner, 1)
    second = reads.find_one(1, _OTHER)

    assert second == first == {"_id": 1, "payload": "other"}
    assert reads.manager.observation.hits == 1
    assert len(reads.manager._metadata) == 2


def test_view_does_not_consume_a_shared_namespace_slot(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
) -> None:
    view_name = "negative_metadata_view"
    client[seeded_database].command("create", view_name, viewOn=COLLECTION, pipeline=[])
    _, reads = open_reads(replace(_SHARED_INDEX, namespaces=2))
    expected = client[seeded_database][COLLECTION].find_one({"_id": 0})

    assert reads.find_one(0, view_name) == expected
    requests = reads.manager.endpoint.counters.requests
    assert reads.find_one(0, view_name) == expected
    assert reads.manager.endpoint.counters.requests == requests

    metadata = reads.manager._metadata.find(NamespaceId(seeded_database, view_name))
    assert metadata is not None
    assert metadata.bypass_reason is BypassReason.VIEW_COLLECTION
    assert not metadata.epoch_bound
    assert metadata.expires_at is not None

    client[seeded_database][_OTHER].insert_one({"_id": 1, "payload": "other"})
    wait_for(
        lambda: (
            reads.find_one(1, _OTHER) == {"_id": 1, "payload": "other"}
            and reads.manager._metadata.find(NamespaceId(seeded_database, _OTHER))
            is not None
        )
    )
    other_metadata = reads.manager._metadata.find(NamespaceId(seeded_database, _OTHER))
    assert other_metadata is not None
    assert other_metadata.bypass_reason is None


def test_expired_view_metadata_allows_reads_after_collection_replacement(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
) -> None:
    view_name = "replaced_negative_metadata_view"
    client[seeded_database].command("create", view_name, viewOn=COLLECTION, pipeline=[])
    _owner, reads = open_reads(_SHARED_INDEX)
    namespace = NamespaceId(seeded_database, view_name)
    expected_from_view = client[seeded_database][COLLECTION].find_one({"_id": 0})

    assert reads.find_one(0, view_name) == expected_from_view
    metadata = reads.manager._metadata.find(namespace)
    assert metadata is not None
    assert metadata.expires_at is not None

    client[seeded_database].drop_collection(view_name)
    client[seeded_database].create_collection(view_name).insert_one(
        {"_id": "replacement", "payload": "regular collection"}
    )
    reads.manager._metadata.store(namespace, replace(metadata, expires_at=0))

    assert reads.find_one("replacement", view_name) == {
        "_id": "replacement",
        "payload": "regular collection",
    }
    refreshed = reads.manager._metadata.find(namespace)
    assert refreshed is not None
    assert refreshed.bypass_reason is None
    assert refreshed.epoch_bound


def test_a_namespace_reset_makes_local_reads_refresh_metadata(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    client: MongoClient[BsonDict],
    seeded_database: str,
) -> None:
    owner, reads = open_reads(_SHARED_INDEX)
    reads.find_one(1)
    _admitted(owner, 1)
    assert reads.find_one(1) is not None

    client[seeded_database].drop_collection(COLLECTION)
    wait_for(lambda: reads.find_one(1) is None)

    assert reads.manager.observation.bypasses[METADATA_REFRESH] >= 1


def test_owner_exit_detaches_local_reads(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
) -> None:
    owner, reads = open_reads(_SHARED_INDEX)
    document = reads.find_one(1)
    _admitted(owner, 1)

    owner.stop()
    wait_for(lambda: reads.detached)

    assert reads.find_one(1) == document
    assert reads.manager.observation.bypasses[OWNER_UNAVAILABLE] == 1


def _descriptors() -> set[str]:
    return {entry.name for entry in Path("/proc/self/fd").iterdir()}


def _serve_handshake(
    listener: socket.socket, reply: bytes, descriptors: list[int], *, split: bool
) -> None:
    peer, _address = listener.accept()
    with peer:
        header = peer.recv(LENGTH_BYTES)
        hello = b""
        while len(hello) < frame_length(header, 1 << 20):
            hello += peer.recv(65_536)
        if not reply:
            return
        first = reply[:_SPLIT_AT] if split else reply
        socket.send_fds(peer, [first], descriptors)
        if split:
            time.sleep(_SPLIT_PAUSE_SECONDS)
            peer.sendall(reply[_SPLIT_AT:])
        peer.recv(1)


def _attach(model: str, config: AttachmentConfig) -> LocalIndex | AsyncLocalIndex:
    if model == "sync":
        return LocalIndex.attach(config)

    async def attach() -> AsyncLocalIndex:
        local = await AsyncLocalIndex.attach(config)
        await local.close()
        return local

    return asyncio.run(attach())


def _reply(incarnation: int) -> bytes:
    return encode_frame({"v": 1, "id": 0, "r": "ok", "incarnation": Int64(incarnation)})


@pytest.mark.parametrize("model", ["sync", "async"])
@pytest.mark.parametrize(
    ("count", "reply", "split", "rejection"),
    [
        pytest.param(2, _reply(_INCARNATION), True, None, id="split-reply"),
        pytest.param(1, _reply(_INCARNATION), False, ProtocolError, id="missing"),
        pytest.param(3, _reply(_INCARNATION), False, ProtocolError, id="extra"),
        pytest.param(5, _reply(_INCARNATION), False, ProtocolError, id="truncated"),
        pytest.param(
            2, _reply(_INCARNATION) + b"x", False, ProtocolError, id="trailing-bytes"
        ),
        pytest.param(
            2, _reply(_INCARNATION + 1), False, ProtocolError, id="other-incarnation"
        ),
        pytest.param(0, b"", False, ConnectionResetError, id="no-reply"),
    ],
)
def test_handshakes_accept_two_descriptors_from_one_reply(
    owner_endpoint: tuple[socket.socket, AttachmentConfig],
    handshake_descriptors: list[int],
    model: str,
    *,
    count: int,
    reply: bytes,
    split: bool,
    rejection: type[Exception] | None,
) -> None:
    listener, config = owner_endpoint
    sent = handshake_descriptors * 3
    before = _descriptors()  # pytriage: TR5, TR11 (before handshake)
    server = threading.Thread(
        target=_serve_handshake,
        args=(listener, reply, sent[:count]),
        kwargs={"split": split},
    )
    server.start()

    if rejection is None:
        local = _attach(model, config)
        assert local.reader.incarnation == _INCARNATION
        if isinstance(local, LocalIndex):
            local.close()
    else:
        with pytest.raises(rejection):
            _attach(model, config)
    server.join(5)

    assert _descriptors() <= before


@pytest.fixture
def handshake_descriptors() -> Iterator[list[int]]:
    index = OwnerIndex(64, 4096, 1, 1, _INCARNATION, 10**9)
    ring = index.session_ring(4)
    reader = index.reader_descriptor()
    yield [reader, ring.descriptor()]
    os.close(reader)
    ring.close_descriptor()


@pytest.fixture
def owner_endpoint(
    socket_directory: Path,
) -> Iterator[tuple[socket.socket, AttachmentConfig]]:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = socket_directory / "fake-owner.sock"
    listener.bind(str(path))
    listener.listen()
    yield (
        listener,
        AttachmentConfig(str(path), bytes(32), 1024, 1024, 100, 0.5, 1 << 20),
    )
    listener.close()


def test_a_replacement_owner_reattaches_the_local_index(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    start_owner: Callable[..., Owner],
) -> None:
    first, reads = open_reads(_SHARED_INDEX)
    reads.find_one(1)
    _admitted(first, 1)
    previous = reads.manager.local
    assert previous is not None

    os.kill(first.pid, signal.SIGKILL)
    first.process.join(10)
    wait_for(lambda: reads.detached)
    native = reads.find_one(1)
    assert reads.find_one(1) == native
    replacement = start_owner(shared_index=_SHARED_INDEX)
    wait_for(
        lambda: (
            reads.find_one(1) is not None
            and reads.manager.local is not previous
            and replacement.counters()["admitted"] == 1
        )
    )
    requests = reads.manager.endpoint.counters.requests

    local = reads.find_one(1)

    assert native == local == {"_id": 1, "payload": "value-1", "revision": 0}
    assert reads.manager.endpoint.counters.requests == requests
    assert reads.manager.local is not None
    assert reads.manager.local.incarnation == replacement.observation()["incarnation"]


def _slow_attaches(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    attaches: list[float] = []
    sync_attach = LocalIndex.attach
    async_attach = AsyncLocalIndex.attach

    def slow_sync(_cls: type[LocalIndex], config: AttachmentConfig) -> LocalIndex:
        attaches.append(time.monotonic())
        time.sleep(_SLOW_ATTACH_SECONDS)
        return sync_attach(config)

    async def slow_async(
        _cls: type[AsyncLocalIndex], config: AttachmentConfig
    ) -> AsyncLocalIndex:
        attaches.append(time.monotonic())
        await asyncio.sleep(_SLOW_ATTACH_SECONDS)
        return await async_attach(config)

    monkeypatch.setattr(LocalIndex, "attach", classmethod(slow_sync))
    monkeypatch.setattr(AsyncLocalIndex, "attach", classmethod(slow_async))
    return attaches


def test_concurrent_reads_reattach_once_after_owner_replacement(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    start_owner: Callable[..., Owner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, reads = open_reads(_SHARED_INDEX)
    reads.find_one(1)
    _admitted(first, 1)
    os.kill(first.pid, signal.SIGKILL)
    first.process.join(10)
    wait_for(lambda: reads.detached)
    native = reads.find_one(1)
    previous = reads.manager.local
    replacement = start_owner(  # pytriage: TR11 (reads need the owner)
        shared_index=_SHARED_INDEX
    )
    attaches = _slow_attaches(monkeypatch)
    time.sleep(_PAST_REATTACH_BACKOFF_SECONDS)

    concurrently = reads.find_concurrently(1, _CONCURRENT_READS)
    reattached = reads.manager.local
    reads.reattach_from(previous)

    assert concurrently == [native] * _CONCURRENT_READS
    assert len(attaches) == 1
    assert reads.manager.local is reattached
    assert replacement.observation()["shared_index"]["sessions"] == 1
    assert reads.manager.local is not None
    assert reads.manager.local.incarnation == replacement.observation()["incarnation"]


def test_a_read_whose_metadata_is_discarded_by_reattachment_bypasses(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reads = open_reads(_SHARED_INDEX)
    reads.find_one(1)
    _admitted(owner, 1)
    manager = reads.manager
    original = type(manager)._cache_ineligibility_reason

    def discarding(*args: object) -> object:
        reason = original(*args)  # type: ignore[arg-type]
        manager._metadata.clear()
        return reason

    async def discarding_async(*args: object) -> object:
        reason = await original(*args)  # type: ignore[arg-type,misc]
        manager._metadata.clear()
        return reason

    monkeypatch.setattr(
        type(manager),
        "_cache_ineligibility_reason",
        discarding if isinstance(manager, SharedCacheManager) else discarding_async,
    )
    requests = manager.endpoint.counters.requests

    assert reads.find_one(1) == {"_id": 1, "payload": "value-1", "revision": 0}
    assert manager.observation.bypasses == {adapters.METADATA_REFRESH: 1}
    assert manager.endpoint.counters.requests == requests


def test_slots_of_another_incarnation_are_never_read_locally(
    open_reads: Callable[[SharedIndexLimits], tuple[Owner, _SharedReads]],
    seeded_database: str,
) -> None:
    owner, reads = open_reads(_SHARED_INDEX)
    reads.find_one(1)
    _admitted(owner, 1)
    namespace = NamespaceId(seeded_database, COLLECTION)
    assignment = reads.manager._slots.find(namespace)
    assert assignment is not None
    database, slot, incarnation = assignment
    assert isinstance(incarnation, int)
    reads.manager._slots.store(namespace, (database, slot, Int64(incarnation + 1)))
    previous = reads.manager.local  # pytriage: TR5 (before fallback)
    requests = reads.manager.endpoint.counters.requests

    fallback = reads.find_one(1)
    reattached = reads.find_one(1)

    assert fallback == reattached == {"_id": 1, "payload": "value-1", "revision": 0}
    assert reads.manager.endpoint.counters.requests > requests
    assert reads.manager.local is not previous
    refreshed_assignment = reads.manager._slots.find(namespace)
    assert refreshed_assignment is not None
    assert refreshed_assignment[2] == incarnation


def test_scalar_read_recovers_natively_when_control_connection_is_lost(
    open_manager: Callable[..., SharedCacheManager[BsonDict]],
    client: MongoClient[BsonDict],
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> None:
    owner = start_owner()
    manager = open_manager(client, owner)
    ready(manager, seeded_database)
    manager.endpoint.close()
    assert manager[seeded_database][COLLECTION].count_documents({}) == DOCUMENTS

    async def asynchronous() -> None:
        async with async_shared_manager(owner, mongodb_uri) as async_manager:
            view = async_manager[seeded_database][COLLECTION]
            await view._cache_ineligibility_reason()
            await async_manager.endpoint.close()
            assert await view.count_documents({}) == DOCUMENTS

    asyncio.run(asynchronous())

from __future__ import annotations

import asyncio
import multiprocessing
import time
from collections.abc import Awaitable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from pymongo import AsyncMongoClient, MongoClient

from benchmarks.stream_cost.multiprocess_run import reclaim_workers
from client_query_cache._shared.adapters import (
    AsyncSharedCacheManager,
    SharedCachedCollection,
    SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AsyncLocalIndex,
    LocalIndex,
    SyncEndpoint,
)
from client_query_cache._shared.shared_index import SharedIndexLimits
from client_query_cache._types import BsonDict
from tests.codec_helpers import Decimal128ToDecimalDecoder
from tests.cursor_helpers import advance, close_cursor, materialize
from tests.polling import wait_until_async
from tests.shared_cache.conftest import COLLECTION, wait_for

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

    from client_query_cache._shared.adapters import (
        AsyncSharedCachedCollection,
    )
    from client_query_cache._shared.attachment import AttachmentConfig
    from tests.conftest import MongoDbUri
    from tests.shared_cache.conftest import Owner

_INDEX = SharedIndexLimits(
    slots=64, arena_bytes=1024 * 1024, namespaces=1, ring_tokens=256
)
_LIMIT = 8


@asynccontextmanager
async def _attached_view(
    uri: str, attachment: AttachmentConfig, database: str, model: str
) -> AsyncGenerator[
    SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict]
]:
    async with AsyncExitStack() as stack:
        if model == "sync":
            client = stack.enter_context(MongoClient[BsonDict](uri))
            manager = SharedCacheManager(
                client, SyncEndpoint(attachment), LocalIndex.attach(attachment)
            )
            stack.callback(manager.close)
            yield manager[database][COLLECTION]
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[BsonDict](uri)
            )
            async_manager = AsyncSharedCacheManager(
                async_client,
                await AsyncEndpoint.attach(attachment),
                await AsyncLocalIndex.attach(attachment),
            )
            stack.push_async_callback(async_manager.close)
            yield async_manager[database][COLLECTION]


@pytest.fixture
def writer(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture(params=["sync", "async"])
async def sorted_view(
    request: pytest.FixtureRequest,
    start_owner: Callable[..., Owner],
    seeded_database: str,
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[
    tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict], Owner
    ]
]:
    owner = start_owner(shared_index=_INDEX)
    async with _attached_view(
        mongodb_uri, owner.attachment(), seeded_database, request.param
    ) as view:

        async def eligible() -> bool:
            hits = view._shared.observation.hits
            await materialize(view.find({"_id": "metadata-warmup"}))
            return view._shared.observation.hits > hits

        await wait_until_async(eligible)
        yield view, owner


async def _read_sorted(
    connection: Connection,
    uri: str,
    attachment: AttachmentConfig,
    database: str,
    model: str,
) -> None:
    async with _attached_view(uri, attachment, database, model) as view:

        async def eligible() -> bool:
            reason = view._cache_ineligibility_reason()
            if isinstance(reason, Awaitable):
                reason = await reason
            return reason is None

        await wait_until_async(eligible)
        connection.send("ready")
        connection.recv()
        requests = view._shared.endpoint.counters.requests
        documents = await materialize(
            view.find({"revision": 0}).sort("_id", 1).limit(_LIMIT)
        )
        connection.send(
            (
                documents,
                view._shared.observation.hits,
                view._shared.observation.misses,
                view._shared.endpoint.counters.requests - requests,
            )
        )


def _sorted_reader(
    connection: Connection,
    uri: str,
    attachment: AttachmentConfig,
    database: str,
    model: str,
) -> None:
    with connection:
        asyncio.run(_read_sorted(connection, uri, attachment, database, model))


@pytest.fixture
def spawn_sorted_reader(
    mongodb_uri: MongoDbUri,
) -> Iterator[Callable[[Owner, str, str], Connection]]:
    processes: list[BaseProcess] = []
    connections: list[Connection] = []

    def spawn(owner: Owner, database: str, model: str) -> Connection:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=_sorted_reader,
            args=(child, mongodb_uri, owner.attachment(), database, model),
        )
        process.start()
        child.close()
        processes.append(process)
        connections.append(parent)
        assert parent.poll(15)
        assert parent.recv() == "ready"
        return parent

    yield spawn
    reclaim_workers(tuple(processes), time.monotonic() + 10, graceful=True)
    for process in processes:
        assert process.exitcode == 0
    for connection in connections:
        connection.close()


@pytest.mark.integration
@pytest.mark.parametrize("reader_model", ["sync", "async"])
async def test_a_separate_worker_reads_a_published_sorted_result_without_rpc(
    sorted_view: tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict], Owner
    ],
    spawn_sorted_reader: Callable[[Owner, str, str], Connection],
    reader_model: str,
) -> None:
    view, owner = sorted_view
    admitted = owner.counters()["admitted"]
    complete = await materialize(
        view.find({"revision": 0}).sort("_id", 1).limit(_LIMIT)
    )
    wait_for(lambda: owner.counters()["admitted"] > admitted)
    connection = spawn_sorted_reader(owner, view.raw.database.name, reader_model)
    connection.send("read")
    assert connection.poll(15)
    assert connection.recv() == (complete, 1, 0, 0)


@pytest.mark.integration
@pytest.mark.parametrize(
    "query", [{"revision": 0}, {"revision": -1}], ids=["populated", "empty"]
)
async def test_sorted_hits_are_local_isolated_and_invalidated(
    sorted_view: tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict], Owner
    ],
    query: BsonDict,
    writer: MongoClient[BsonDict],
) -> None:
    view, owner = sorted_view
    admitted = owner.counters()["admitted"]
    complete = await materialize(view.find(query).sort("_id", 1).limit(_LIMIT))
    wait_for(lambda: owner.counters()["admitted"] > admitted)
    requests = owner.counters()["requests"]
    hits = view._shared.observation.hits
    hit = await materialize(view.find(query).sort("_id", 1).limit(_LIMIT))
    assert hit == complete
    assert view._shared.observation.hits == hits + 1
    assert owner.counters()["requests"] == requests
    if hit:
        hit[0]["revision"] = 100
        assert (
            await materialize(view.find(query).sort("_id", 1).limit(_LIMIT)) == complete
        )

    before = owner.request("sample")["invalidations"]
    writer[view.raw.database.name][COLLECTION].update_one(
        {"_id": 0}, {"$set": {"revision": -1}}
    )
    wait_for(lambda: owner.request("sample")["invalidations"] > before)
    requests = owner.counters()["requests"]
    refreshed = await materialize(view.find(query).sort("_id", 1).limit(_LIMIT))
    assert owner.counters()["requests"] > requests
    assert refreshed != complete


@pytest.mark.integration
@pytest.mark.parametrize(
    "interruption", ["close", "write"], ids=["partial-close", "admission-race"]
)
async def test_interrupted_sorted_capture_is_never_published(
    sorted_view: tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict], Owner
    ],
    writer: MongoClient[BsonDict],
    interruption: str,
) -> None:
    view, owner = sorted_view
    admitted = owner.counters()["admitted"]
    cursor = view.find({"revision": 0}).sort("_id", 1).limit(_LIMIT)
    await advance(cursor)
    if interruption == "close":
        await close_cursor(cursor)
    else:
        invalidations = owner.request("sample")["invalidations"]
        writer[view.raw.database.name][COLLECTION].update_one(
            {"_id": 0}, {"$inc": {"revision": 1}}
        )
        wait_for(lambda: owner.request("sample")["invalidations"] > invalidations)
        await materialize(cursor)
    wait_for(lambda: owner.observation()["captures"] == 0)
    assert owner.counters()["admitted"] == admitted


@pytest.mark.integration
async def test_unportable_bounded_find_preserves_native_results(
    sorted_view: tuple[
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict], Owner
    ],
) -> None:
    view, owner = sorted_view
    options: CodecOptions[BsonDict] = CodecOptions(
        type_registry=TypeRegistry([Decimal128ToDecimalDecoder()])
    )
    custom_view: (
        SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict]
    )
    if isinstance(view, SharedCachedCollection):
        custom_view = view._shared.get_cached_collection(
            view.raw.with_options(codec_options=options)
        )
    else:
        custom_view = view._shared.get_cached_collection(
            view.raw.with_options(codec_options=options)
        )
    requests = owner.counters()["requests"]
    documents = await materialize(custom_view.find({}).sort("_id", 1).limit(_LIMIT))
    assert [document["_id"] for document in documents] == list(range(_LIMIT))
    assert owner.counters()["requests"] == requests
    assert view._shared.observation.bypasses["unportable-key"] == 1

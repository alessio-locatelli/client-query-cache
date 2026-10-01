from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pymongo
import pytest
from pymongo import AsyncMongoClient

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from client_query_cache.asynchronous import CacheManager
from tests.barrier_helpers import (
    BARRIER_TIMEOUT_SECONDS,
    SPREAD_DOCUMENT_COUNT,
    spread_documents,
)
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from faker import Faker
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache.asynchronous import CachedCollection
    from tests.barrier_helpers import AggregateRecorder, Topology
    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(
    topology: Topology, aggregate_recorder: AggregateRecorder
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](
        topology.uri, w="majority", event_listeners=[aggregate_recorder]
    ) as mongo_client:
        yield mongo_client


@pytest.fixture
async def manager(
    client: AsyncMongoClient[dict[str, Any]],
) -> AsyncIterator[CacheManager[dict[str, Any]]]:
    async with CacheManager(client) as cache_manager:
        yield cache_manager


@pytest.fixture
async def items(
    client: AsyncMongoClient[dict[str, Any]],
    topology: Topology,
    cached_database_name: DatabaseName,
    faker: Faker,
) -> AsyncIterator[AsyncCollection[dict[str, Any]]]:
    database = client[cached_database_name]
    collection = await database.create_collection("items")
    if topology.sharded:
        await client.admin.command("enableSharding", cached_database_name)
        await client.admin.command(
            "shardCollection", collection.full_name, key={"_id": "hashed"}
        )
    await collection.insert_many(
        spread_documents([faker.word() for _ in range(SPREAD_DOCUMENT_COUNT)])
    )
    yield collection
    await client.drop_database(cached_database_name)


@pytest.fixture
async def transaction_collections(
    mongodb_uri: MongoDbUri, cached_database_name: DatabaseName
) -> AsyncIterator[
    tuple[AsyncCollection[dict[str, Any]], AsyncCollection[dict[str, Any]]]
]:
    async with AsyncMongoClient[dict[str, Any]](
        mongodb_uri, w="majority"
    ) as mongo_client:
        database = mongo_client[cached_database_name]
        collections = (
            await database.create_collection("first"),
            await database.create_collection("second"),
        )
        for collection in collections:
            await collection.insert_one({"_id": 1, "value": 0})
        yield collections
        await mongo_client.drop_database(cached_database_name)


async def _warm(
    manager: CacheManager[Any], *reads: Callable[[], Awaitable[object]]
) -> None:
    async def _every_read_hits() -> bool:
        hits_before = manager.cache_core.snapshot().hits
        for read in reads:
            await read()
        return manager.cache_core.snapshot().hits - hits_before == len(reads)

    await wait_until_async(_every_read_hits)


async def _warm_items(
    manager: CacheManager[dict[str, Any]], items: AsyncCollection[dict[str, Any]]
) -> CachedCollection[dict[str, Any]]:
    cached = manager.cached(items)
    await _warm(
        manager,
        lambda: cached.find_one({"_id": 1}),
        lambda: cached.find({"group": "spread"}),
    )
    return cached


async def test_a_barrier_makes_cached_document_and_query_reads_observe_the_write(
    manager: CacheManager[dict[str, Any]],
    items: AsyncCollection[dict[str, Any]],
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    cached = await _warm_items(manager, items)

    async with client.start_session() as session:
        await items.update_many(
            {"group": "spread"}, {"$set": {"value": 1}}, session=session
        )
        boundary = manager.causal_boundary(session)
    await manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    document = await cached.find_one({"_id": 1})
    assert document is not None
    assert document["value"] == 1
    assert {row["value"] for row in await cached.find({"group": "spread"})} == {1}


async def test_a_barrier_completes_after_a_no_op_write_on_an_idle_database(
    manager: CacheManager[dict[str, Any]],
    items: AsyncCollection[dict[str, Any]],
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    await _warm_items(manager, items)

    async with client.start_session() as session:
        no_op_update = await items.update_one(
            {"_id": "missing"}, {"$set": {"value": 1}}, session=session
        )
        boundary = manager.causal_boundary(session)
    await manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    assert no_op_update.matched_count == 0


async def test_a_read_captured_before_the_write_is_not_admitted_after_the_barrier(
    manager: CacheManager[dict[str, Any]],
    items: AsyncCollection[dict[str, Any]],
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    await _warm_items(manager, items)
    namespace = NamespaceId(items.database.name, items.name)
    capture = manager.cache_core.begin_identity_admission(namespace, 2)
    stale_document = await items.find_one({"_id": 2})

    async with client.start_session() as session:
        await items.update_one({"_id": 2}, {"$set": {"value": 2}}, session=session)
        boundary = manager.causal_boundary(session)
    await manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    outcome = manager.cache_core.admit_identity(capture, "full", stale_document)
    assert outcome is AdmissionOutcome.DECLINED_STALE


async def test_ordinary_cached_reads_issue_no_barrier_commands(
    manager: CacheManager[dict[str, Any]],
    items: AsyncCollection[dict[str, Any]],
    aggregate_recorder: AggregateRecorder,
) -> None:
    await _warm_items(manager, items)

    assert not aggregate_recorder.barrier_aggregates()


async def test_a_stream_activated_inside_a_driver_timeout_keeps_running(
    manager: CacheManager[dict[str, Any]],
    items: AsyncCollection[dict[str, Any]],
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    activation_timeout = 0.5
    with pymongo.timeout(activation_timeout):
        await manager.cached(items).find_one({"_id": 3})
    await asyncio.sleep(activation_timeout * 3)

    async with client.start_session() as session:
        await items.update_one({"_id": 3}, {"$set": {"value": 3}}, session=session)
        boundary = manager.causal_boundary(session)
    await manager.wait_for_invalidations(
        items.database.name, boundary, timeout=BARRIER_TIMEOUT_SECONDS
    )

    document = await manager.cached(items).find_one({"_id": 3})
    assert document is not None
    assert document["value"] == 3


async def test_a_barrier_covers_a_committed_transaction_across_collections(
    transaction_collections: tuple[
        AsyncCollection[dict[str, Any]], AsyncCollection[dict[str, Any]]
    ],
) -> None:
    client = transaction_collections[0].database.client
    async with CacheManager(client) as manager:
        cached = [manager.cached(collection) for collection in transaction_collections]
        await _warm(
            manager, *(lambda view=view: view.find_one({"_id": 1}) for view in cached)
        )

        async with client.start_session() as session:
            await session.with_transaction(_update_each(transaction_collections))
            boundary = manager.causal_boundary(session)
        await manager.wait_for_invalidations(
            transaction_collections[0].database.name,
            boundary,
            timeout=BARRIER_TIMEOUT_SECONDS,
        )

        assert [await view.find_one({"_id": 1}) for view in cached] == [
            {"_id": 1, "value": 1},
            {"_id": 1, "value": 1},
        ]


def _update_each(
    collections: tuple[AsyncCollection[dict[str, Any]], ...],
) -> Callable[[AsyncClientSession], Awaitable[None]]:
    async def _update(transaction_session: AsyncClientSession) -> None:
        for collection in collections:
            await collection.update_one(
                {"_id": 1}, {"$set": {"value": 1}}, session=transaction_session
            )

    return _update

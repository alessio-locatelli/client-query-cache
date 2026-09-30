import asyncio
from operator import itemgetter
from typing import TYPE_CHECKING, Any

import pytest
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.database import AsyncDatabase

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.asynchronous.collection import CachedCollection
from client_query_cache.asynchronous.database import CachedDatabase
from client_query_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.asynchronous.collection import AsyncCollection

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    assert not issubclass(CacheManager, AsyncMongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, AsyncDatabase)
    assert isinstance(database.raw, AsyncDatabase)
    assert database.name == "example"
    assert database.raw.client is client


async def test_manager_used_as_a_context_manager_closes_its_own_cache(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    async with CacheManager(client) as manager:
        core = manager.cache_core

    assert core.snapshot().lifecycle == CacheLifecycleState.CLOSED.value


async def test_manager_close_does_not_close_the_caller_owned_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    await CacheManager(client).close()

    assert client._closed is False


async def test_unique_keys_for_rejects_a_probe_racing_a_concurrent_index_change(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    namespace = NamespaceId("example", "widgets")

    async def racing_list_indexes() -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        manager.cache_core.record_index_change(namespace)
        return [{"key": {"email": 1}, "name": "email_1", "unique": True}]

    assert await manager.unique_keys_for(namespace, racing_list_indexes) == ()


@pytest.mark.parametrize(
    "get_raw_collection",
    [
        pytest.param(itemgetter("items"), id="plain"),
        pytest.param(
            lambda database: database["items"].with_options(
                read_preference=ReadPreference.SECONDARY
            ),
            id="with_options",
        ),
        pytest.param(
            lambda database: database.get_collection(
                "items", codec_options=CodecOptions(tz_aware=True)
            ),
            id="get_collection",
        ),
    ],
)
def test_cached_view_retains_the_exact_supplied_collection(
    client: AsyncMongoClient[dict[str, Any]],
    get_raw_collection: Callable[
        [AsyncDatabase[dict[str, Any]]], AsyncCollection[dict[str, Any]]
    ],
) -> None:
    manager = CacheManager(client)
    raw_collection = get_raw_collection(client["example"])

    collection = manager.cached(raw_collection)

    assert isinstance(collection, CachedCollection)
    assert collection.raw is raw_collection
    assert collection.database.raw is raw_collection.database
    assert collection.database.manager is manager


def test_cached_rejects_a_collection_owned_by_another_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    foreign_client = AsyncMongoClient[dict[str, Any]](
        "mongodb://localhost:27017", connect=False
    )

    with pytest.raises(ValueError, match="different client"):
        manager.cached(foreign_client["example"]["items"])


def test_repeated_cached_views_share_the_manager_and_raw_collection(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    first = manager.cached(raw_collection)
    second = manager.cached(raw_collection)

    assert first.raw is second.raw is raw_collection
    assert first.database.manager is second.database.manager is manager

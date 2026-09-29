import asyncio
from typing import Any

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.asynchronous.database import CachedDatabase
from client_query_cache.asynchronous.manager import CacheManager

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

    assert client._closed is False

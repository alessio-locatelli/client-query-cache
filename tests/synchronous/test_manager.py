from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.synchronous.database import Database

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.synchronous.database import CachedDatabase
from client_query_cache.synchronous.manager import CacheManager

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> MongoClient[dict[str, Any]]:
    return MongoClient("mongodb://localhost:27017", connect=False)


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    assert not issubclass(CacheManager, MongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, Database)
    assert isinstance(database.raw, Database)
    assert database.name == "example"
    assert database.raw.client is client


def test_manager_used_as_a_context_manager_closes_its_own_cache(
    client: MongoClient[dict[str, Any]],
) -> None:
    with CacheManager(client) as manager:
        core = manager.cache_core

    assert core.lifecycle_state is CacheLifecycleState.CLOSED


def test_manager_close_does_not_close_the_caller_owned_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    CacheManager(client).close()

    assert client._closed is False


def test_unique_keys_for_rejects_a_probe_racing_a_concurrent_index_change(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    namespace = NamespaceId("example", "widgets")

    def racing_list_indexes() -> list[dict[str, Any]]:
        manager.cache_core.record_index_change(namespace)
        return [{"key": {"email": 1}, "name": "email_1", "unique": True}]

    assert manager.unique_keys_for(namespace, racing_list_indexes) == ()

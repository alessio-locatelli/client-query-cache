from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.synchronous.collection import Collection

from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.database import CachedDatabase
from client_query_cache.synchronous.manager import CacheManager

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> MongoClient[dict[str, Any]]:
    return MongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
def manager(client: MongoClient[dict[str, Any]]) -> CacheManager[dict[str, Any]]:
    return CacheManager(client)


def test_database_retains_access_to_the_caller_owned_raw_database(
    manager: CacheManager[dict[str, Any]], client: MongoClient[dict[str, Any]]
) -> None:
    raw_database = client["example"]

    database = CachedDatabase(manager, raw_database)

    assert database.raw is raw_database
    assert database.manager is manager


def test_database_builds_a_collection_facade_around_its_raw_database(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"]["items"]

    assert isinstance(collection, CachedCollection)
    assert not issubclass(CachedCollection, Collection)
    assert isinstance(collection.raw, Collection)
    assert collection.name == "items"
    assert collection.raw.database.name == "example"

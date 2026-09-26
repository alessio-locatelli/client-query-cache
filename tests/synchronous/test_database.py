from typing import Any

import pytest
from pymongo import MongoClient, ReadPreference
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


def test_database_attribute_access_returns_a_cached_collection_facade(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"].items

    assert isinstance(collection, CachedCollection)
    assert collection.name == "items"


def test_database_get_collection_returns_a_cached_collection_facade(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"].get_collection("items")

    assert isinstance(collection, CachedCollection)
    assert collection.name == "items"


def test_database_with_options_returns_a_cached_database_facade(
    manager: CacheManager[dict[str, Any]],
) -> None:
    database = manager["example"]

    retargeted = database.with_options(read_preference=ReadPreference.SECONDARY)

    assert isinstance(retargeted, CachedDatabase)
    assert retargeted.manager is database.manager
    assert retargeted.raw.read_preference == ReadPreference.SECONDARY


def test_database_builds_a_collection_facade_around_its_raw_database(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"]["items"]

    assert isinstance(collection, CachedCollection)
    assert not issubclass(CachedCollection, Collection)
    assert isinstance(collection.raw, Collection)
    assert collection.name == "items"
    assert collection.raw.database.name == "example"

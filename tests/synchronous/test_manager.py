from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.synchronous.database import Database

from mongo_client_cache.synchronous.database import CachedDatabase
from mongo_client_cache.synchronous.manager import CacheManager

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

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from mongo_client_cache.asynchronous.database import CachedDatabase
from mongo_client_cache.asynchronous.manager import CacheManager

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> AsyncMongoClient:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: AsyncMongoClient,
) -> None:
    assert not issubclass(CacheManager, AsyncMongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: AsyncMongoClient,
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, AsyncDatabase)
    assert isinstance(database.raw, AsyncDatabase)
    assert database.name == "example"
    assert database.raw.client is client

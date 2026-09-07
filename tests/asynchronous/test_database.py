import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from mongo_client_cache.asynchronous.collection import CachedCollection
from mongo_client_cache.asynchronous.database import CachedDatabase
from mongo_client_cache.asynchronous.manager import CacheManager

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> AsyncMongoClient:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
def manager(client: AsyncMongoClient) -> CacheManager:
    return CacheManager(client)


def test_database_retains_access_to_the_caller_owned_raw_database(
    manager: CacheManager, client: AsyncMongoClient
) -> None:
    raw_database = client["example"]

    database = CachedDatabase(manager, raw_database)

    assert database.raw is raw_database
    assert database.manager is manager


def test_database_builds_a_collection_facade_around_its_raw_database(
    manager: CacheManager,
) -> None:
    collection = manager["example"]["items"]

    assert isinstance(collection, CachedCollection)
    assert not issubclass(CachedCollection, AsyncCollection)
    assert isinstance(collection.raw, AsyncCollection)
    assert collection.name == "items"
    assert collection.raw.database.name == "example"

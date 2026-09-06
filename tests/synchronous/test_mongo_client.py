from collections.abc import Iterator

import pymongo
import pytest
from pymongo import MongoClient
from pymongo.synchronous.database import Database

from mongo_client_cache import CachedMongoClient
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.database import CachedDatabase
from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def client_without_cache_config(mongodb_uri: MongoDbUri) -> Iterator[MongoClient]:
    with CachedMongoClient(mongodb_uri, cache_config={}) as client:
        yield client


@pytest.fixture
def client_with_cached_database_without_cached_collections(
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
) -> Iterator[MongoClient]:
    with CachedMongoClient(
        mongodb_uri, cache_config={cached_database_name: {}}
    ) as client:
        yield client


def test_cached_mongo_client_without_cache_config(
    client_without_cache_config: MongoClient,
    cached_database_name: DatabaseName,
) -> None:
    for database, collection in (
        (
            client_without_cache_config[cached_database_name],
            client_without_cache_config[cached_database_name]["test"],
        ),
    ):
        assert isinstance(database, Database)
        assert database.command("ping")["ok"] == 1
        assert isinstance(collection, pymongo.synchronous.collection.Collection)
        assert collection.count_documents({}) == 0


def test_cached_mongo_client_with_cache_config_no_cached_collections(
    client_with_cached_database_without_cached_collections: MongoClient,
    cached_database_name: DatabaseName,
) -> None:
    client = client_with_cached_database_without_cached_collections
    for database, collection in (
        (client[cached_database_name], client[cached_database_name]["test"]),
    ):
        assert isinstance(database, CachedDatabase)
        assert database.command("ping")["ok"] == 1
        assert isinstance(collection, pymongo.synchronous.collection.Collection)
        assert collection.count_documents({}) == 0


def test_cached_mongo_client(
    cached_mongo_client: MongoClient,
    cached_database_name: DatabaseName,
    persistent_collection_name: str,
) -> None:
    database = cached_mongo_client[cached_database_name]
    assert isinstance(database, CachedDatabase)
    assert database.command("ping")["ok"] == 1
    collection = database[persistent_collection_name]
    assert isinstance(collection, CachedCollection)
    assert collection.count_documents({}) == 0

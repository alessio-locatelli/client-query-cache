import os
from collections.abc import Iterator

import pymongo
import pytest
from pymongo import MongoClient
from pymongo.synchronous.database import Database

from mongo_client_cache import CachedMongoClient
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.database import CachedDatabase


@pytest.fixture()
def mongo_host() -> str:
    return f"mongodb+srv://{os.environ['REPLICA_MONGO_NAME']}:{os.environ['REPLICA_MONGO_PASSWORD']}@{os.environ['REPLICA_MONGO_HOST']}/?retryWrites=true&w=majority"


@pytest.fixture()
def client_without_cache_config(mongo_host: str) -> Iterator[MongoClient]:
    with CachedMongoClient(mongo_host, cache_config={}) as client:
        yield client


@pytest.fixture()
def client_with_cached_database_without_cached_collections(
    mongo_host: str,
) -> Iterator[MongoClient]:
    with CachedMongoClient(mongo_host, cache_config={"db_test": []}) as client:
        yield client


def test_cached_mongo_client_without_cache_config(
    client_without_cache_config: MongoClient,
) -> None:
    for database, collection in (
        (client_without_cache_config.db_test, client_without_cache_config.db_test.test),
        (
            client_without_cache_config["db_test"],
            client_without_cache_config["db_test"]["test"],
        ),
    ):
        assert isinstance(database, Database)
        assert database.command("ping")["ok"] == 1
        assert isinstance(collection, pymongo.synchronous.collection.Collection)
        assert collection.count_documents({}) == 0


def test_cached_mongo_client_with_cache_config_no_cached_collections(
    client_with_cached_database_without_cached_collections: MongoClient,
) -> None:
    client = client_with_cached_database_without_cached_collections
    for database, collection in (
        (client.db_test, client.db_test.test),
        (client["db_test"], client["db_test"]["test"]),
    ):
        assert isinstance(database, CachedDatabase)
        assert database.command("ping")["ok"] == 1
        assert isinstance(collection, pymongo.synchronous.collection.Collection)
        assert collection.count_documents({}) == 0


def test_cached_mongo_client(
    cached_mongo_client: MongoClient, persistent_collection_name: str
) -> None:
    assert isinstance(cached_mongo_client.db_one, CachedDatabase)
    assert cached_mongo_client.db_one.command("ping")["ok"] == 1
    collection = cached_mongo_client.db_one[persistent_collection_name]
    assert isinstance(collection, CachedCollection)
    assert collection.count_documents({}) == 0

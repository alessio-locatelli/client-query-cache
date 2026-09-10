from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient

from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> MongoClient[dict[str, Any]]:
    return MongoClient("mongodb://localhost:27017", connect=False)


def test_collection_retains_access_to_the_caller_owned_raw_collection(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    collection = CachedCollection(manager["example"], raw_collection)

    assert collection.raw is raw_collection
    assert collection.database.raw == manager["example"].raw
    assert collection.name == "items"


def test_raw_collection_is_a_fully_functional_pymongo_escape_hatch(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()

    collection.raw.insert_one(document)

    assert collection.raw.find_one({"_id": document["_id"]}) == document
    assert collection.raw.count_documents({}) == 1


def test_composed_facade_and_direct_client_access_can_mix_incrementally(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    migrated_collection = cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    unmigrated_collection = cache_manager.client[cached_database_name][
        persistent_collection_name
    ]
    migrated_document = make_fake_document()
    unmigrated_document = make_fake_document()

    migrated_collection.raw.insert_one(migrated_document)
    unmigrated_collection.insert_one(unmigrated_document)

    assert migrated_collection.raw.find_one({"_id": migrated_document["_id"]})
    assert unmigrated_collection.find_one({"_id": unmigrated_document["_id"]})


def test_manager_never_takes_ownership_of_the_caller_client_lifecycle(
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    client: MongoClient[dict[str, Any]] = MongoClient(mongodb_uri)
    manager = CacheManager(client)
    collection = manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one(make_fake_document())
    del manager, collection

    assert client.admin.command("ping")["ok"] == 1
    client.close()

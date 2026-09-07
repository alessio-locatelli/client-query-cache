from typing import TYPE_CHECKING, Any

import pytest
from pymongo import AsyncMongoClient

from mongo_client_cache.asynchronous.collection import CachedCollection
from mongo_client_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.asynchronous.collection import AsyncCollection

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


def test_collection_retains_access_to_the_caller_owned_raw_collection(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    collection = CachedCollection(manager["example"], raw_collection)

    assert collection.raw is raw_collection
    assert collection.database.raw == manager["example"].raw
    assert collection.name == "items"


async def test_raw_collection_is_a_fully_functional_pymongo_escape_hatch(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()

    await collection.raw.insert_one(document)

    assert await collection.raw.find_one({"_id": document["_id"]}) == document
    assert await collection.raw.count_documents({}) == 1


async def test_composed_facade_and_direct_client_access_can_mix_incrementally(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    migrated_collection = cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    unmigrated_collection: AsyncCollection[dict[str, Any]] = cache_manager.client[
        cached_database_name
    ][persistent_collection_name]
    migrated_document = make_fake_document()
    unmigrated_document = make_fake_document()

    await migrated_collection.raw.insert_one(migrated_document)
    await unmigrated_collection.insert_one(unmigrated_document)

    assert await migrated_collection.raw.find_one({"_id": migrated_document["_id"]})
    assert await unmigrated_collection.find_one({"_id": unmigrated_document["_id"]})


async def test_manager_never_takes_ownership_of_the_caller_client_lifecycle(
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(mongodb_uri)
    manager = CacheManager(client)  # pytriage: TR5
    collection = manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one(make_fake_document())
    del manager, collection

    assert (await client.admin.command("ping"))["ok"] == 1
    await client.close()

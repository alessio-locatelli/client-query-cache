from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest

from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

DOCUMENT_COUNT = 42


@pytest.fixture(autouse=True)
def fill_collection(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
) -> Iterator[None]:
    cached_collection.insert_many(make_fake_document() for _ in range(DOCUMENT_COUNT))
    yield
    cached_collection.delete_many({})


@pytest.fixture
def cached_collection(
    cached_mongo_client: CachedMongoClient,
    cached_database_name: str,
    nonpersistent_collection_name: str,
) -> CachedCollection:
    return cast(
        CachedCollection,
        cached_mongo_client[cached_database_name][nonpersistent_collection_name],
    )


def test_bulk_write() -> None: ...


def test_find_one() -> None: ...


def test_find() -> None: ...


def test_count_documents(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    for _ in range(3):
        assert cached_collection.count_documents({}) == DOCUMENT_COUNT
    cached_collection.insert_one(doc := make_fake_document())
    assert cached_collection.count_documents({}) == DOCUMENT_COUNT + 1
    cached_collection.delete_one({"_id": doc["_id"]})
    assert cached_collection.count_documents({}) == DOCUMENT_COUNT

from collections.abc import Callable, Iterator
from typing import Any, TypedDict, cast

import pytest
from faker import Faker

from mongo_client_cache._types import JsonDict
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

fake = Faker()


@pytest.fixture
def document_count(faker: Faker) -> int:
    return faker.pyint(min_value=0, max_value=42)


@pytest.fixture(autouse=True)
def fill_collection(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
) -> Iterator[None]:
    cached_collection.insert_many(make_fake_document() for _ in range(document_count))
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


def test_find(
    cached_collection: CachedCollection,
    document_count: int,
    faker: Faker,
) -> None:
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.find({}) == document_count


class CountDocumentsKwargs(TypedDict):
    limit: int
    skip: int


@pytest.mark.parametrize(
    "filter,kwargs,expected_count",
    [
        ({}, {}, None),
        ({fake.pystr(): fake.pystr()}, {}, 0),
        # ({}, {"limit": fake.pyint(min_value=1, max_value=100), "skip": fake.pyint(min_value=1, max_value=100)}),  # TODO
        ({}, {"limit": 1, "skip": 1}, 1),
        # ({}, {"limit": 1, "skip": 99999}, 0),  # TODO
    ]
)
def test_count_documents(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
    faker: Faker,
    filter: JsonDict,
    kwargs: CountDocumentsKwargs,
    expected_count: int | None
) -> None:
    if expected_count is None:
        expected_count = document_count
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.count_documents(filter, **kwargs) == expected_count

    cached_collection.insert_one(doc := make_fake_document())
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.count_documents({}) == document_count + 1

    cached_collection.delete_one({"_id": doc["_id"]})
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.count_documents(filter, **kwargs) == expected_count


def test_estimated_document_count(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
    faker: Faker,
) -> None:
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.estimated_document_count() == document_count

    cached_collection.insert_one(doc := make_fake_document())
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.estimated_document_count() == document_count + 1

    cached_collection.delete_one({"_id": doc["_id"]})
    for _ in range(faker.pyint(min_value=1, max_value=10)):
        assert cached_collection.estimated_document_count() == document_count

from collections.abc import Iterator
from typing import Any

import pytest
from faker import Faker

from mongo_client_cache.pymongo.collection import CachedCollection


@pytest.fixture
def document_id(faker: Faker) -> int:
    return faker.pyint()


@pytest.fixture
def example_document(faker: Faker, document_id: int) -> dict[str, Any]:
    document = faker.pydict()
    document["_id"] = document_id
    return document


@pytest.fixture
def fill_collection(
    example_collection: CachedCollection, example_document: dict[str, Any]
) -> Iterator[None]:
    document_id = example_collection.insert_one(example_document).inserted_id
    yield
    example_collection.delete_one(document_id)


def test_collection_find_one(
    example_collection: CachedCollection,
    document_id: int,
    example_document: dict[str, Any],
) -> None:
    cached_document = example_collection.find_one({"_id": document_id})
    assert cached_document == example_document

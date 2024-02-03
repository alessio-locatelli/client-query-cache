from collections.abc import Iterator
from typing import Any

import pytest

from mongo_client_cache.pymongo.collection import CachedCollection


@pytest.fixture
def fill_collection(
    example_collection: CachedCollection, example_document: dict[str, Any]
) -> Iterator[None]:
    document_id = example_collection.insert_one(example_document).inserted_id
    yield
    example_collection.delete_one({"_id": document_id})


@pytest.mark.usefixtures("fill_collection")
def test_collection_find_one(
    example_collection: CachedCollection,
    document_id: int,
    example_document: dict[str, Any],
) -> None:
    cached_document = example_collection.find_one({"_id": document_id})
    assert cached_document == example_document

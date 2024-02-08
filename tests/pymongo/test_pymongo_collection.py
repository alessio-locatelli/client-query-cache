from collections.abc import Iterator
from typing import Any, cast

import pandas as pd
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
    filter = {"_id": document_id}

    # Uncached call.
    cached_document = example_collection.find_one(filter)
    assert cached_document == example_document
    cache_backend = example_collection._Collection__database.client.cache_backend
    queries_df = cast(pd.DataFrame, cache_backend._queries[example_collection.name])
    assert not queries_df.empty
    collection_df = cast(
        pd.DataFrame, cache_backend._collections[example_collection.name]
    )
    assert not collection_df.empty

    # Cached call.
    cached_document = example_collection.find_one(filter)
    assert cached_document == example_document

    # Remove the document from MongoDB to ensure
    # that the document was previously cached.
    example_collection.delete_one(filter)
    cached_document = example_collection.find_one(filter)
    # We still have the document in the memory.
    assert cached_document == example_document


@pytest.mark.usefixtures("fill_collection")
def test_collection_find(
    example_collection: CachedCollection,
    document_id: int,
    example_document: dict[str, Any],
) -> None:
    filter = {"_id": document_id}

    # Uncached call.
    cached_document = next(iter(example_collection.find(filter)))
    assert cached_document == example_document
    return
    cache_backend = example_collection._Collection__database.client.cache_backend
    queries_df = cast(pd.DataFrame, cache_backend._queries[example_collection.name])
    assert not queries_df.empty
    collection_df = cast(
        pd.DataFrame, cache_backend._collections[example_collection.name]
    )
    assert not collection_df.empty

    # Cached call.
    cached_document = example_collection.find_one(filter)
    assert cached_document == example_document

    # Remove the document from MongoDB to ensure
    # that the document was previously cached.
    example_collection.delete_one(filter)
    cached_document = example_collection.find_one(filter)
    # We still have the document in the memory.
    assert cached_document == example_document

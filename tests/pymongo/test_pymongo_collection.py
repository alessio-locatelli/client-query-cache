from collections.abc import Callable, Iterator
from typing import Any, cast

import pandas as pd
import pytest

from mongo_client_cache.cached_pymongo.collection import CachedCollection
from mongo_client_cache.core.local_database import DatabaseCache


@pytest.fixture
def fill_collection(
    example_collection: CachedCollection, example_document: dict[str, Any]
) -> Iterator[None]:
    document_id = example_collection.insert_one(example_document).inserted_id
    yield
    example_collection.delete_one({"_id": document_id})


class TestCachedCollection:
    def test_bulk_write(self) -> None: ...

    @pytest.mark.usefixtures("fill_collection")
    def test_find_one(
        self,
        create_cached_mongo_collection: Callable[[str, str], CachedCollection],
        random_document_id: int,
        example_document: dict[str, Any],
    ) -> None:
        filter = {"_id": random_document_id}
        collection = create_cached_mongo_collection(
            "db_one", "persistent_collection_name"
        )

        # Uncached call.
        cached_document = collection.find_one(filter)
        assert cached_document == example_document
        db = collection.__Collection__database
        cache = cast(DatabaseCache, db.client.client_side_databases[db.name])
        queries_df = cache.cached_queries[collection.name]
        assert not queries_df.empty
        collection_df = cache.local_collections[collection.name]
        assert not collection_df.empty

        # Cached call.
        cached_document = collection.find_one(filter)
        assert cached_document == example_document

        # Remove the document from MongoDB to ensure
        # that the document was previously cached.
        collection.delete_one(filter)
        cached_document = collection.find_one(filter)
        # We still have the document in the memory.
        assert cached_document == example_document

    @pytest.mark.usefixtures("fill_collection")
    def test_find(
        self,
        example_collection: CachedCollection,
        document_id: int,
        example_document: dict[str, Any],
    ) -> None:
        filter = {"_id": document_id}

        # Uncached call.
        uncached_document = next(iter(example_collection.find(filter)))
        assert uncached_document == example_document
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

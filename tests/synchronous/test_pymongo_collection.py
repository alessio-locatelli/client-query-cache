from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from pymongo.errors import DuplicateKeyError

from mongo_client_cache.cache.local_database import DatabaseCache
from mongo_client_cache.synchronous.collection import CachedCollection


@pytest.fixture
def fill_collection(
    create_cached_mongo_collection: Callable[[str, str], CachedCollection],
    example_document: dict[str, Any],
) -> Iterator[None]:
    collection = create_cached_mongo_collection("db_one", "persistent_collection_name")
    try:
        collection.insert_one(example_document)
    except DuplicateKeyError:
        pass
    yield
    collection.delete_one({"_id": example_document["_id"]})


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
        db = collection._Collection__database
        cache = cast(
            DatabaseCache, db._Database__client._client_side_databases[db.name]
        )
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
        create_cached_mongo_collection: Callable[[str, str], CachedCollection],
        random_document_id: int,
        example_document: dict[str, Any],
    ) -> None:
        collection = create_cached_mongo_collection(
            "db_one", "persistent_collection_name"
        )
        filter = {"_id": random_document_id}

        # Uncached call.
        assert collection.count_documents(filter) == 1
        uncached_document = next(iter(collection.find(filter)))
        assert uncached_document

        db = collection._Collection__database
        cache = cast(
            DatabaseCache, db._Database__client._client_side_databases[db.name]
        )
        queries_df = cache.cached_queries[collection.name]
        assert not queries_df.empty
        collection_df = cast(pd.DataFrame, cache.local_collections[collection.name])
        assert not collection_df.empty

        # Cached call.
        cached_document = next(iter(collection.find(filter)))
        assert cached_document == example_document

        # Remove the document from MongoDB to ensure
        # that the document was previously cached.
        collection.delete_one(filter)
        cached_document = next(iter(collection.find(filter)))
        # We still have the document in the memory.
        assert cached_document == example_document

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache.synchronous.manager import CacheManager
    from tests.conftest import CollectionName, DatabaseName

pytestmark = pytest.mark.integration


def test_consumer_keeps_pymongo_typing_beside_its_cached_view(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ]
    cached_collection = cache_manager.cached(collection)
    document = make_fake_document()

    collection.insert_one(document)

    assert cached_collection.find_one({"_id": document["_id"]}) == document
    assert list(cached_collection.raw.find({"_id": document["_id"]})) == [document]
    with pytest.raises(TypeError):
        collection.insert_one(document, upsert=True)  # type: ignore[call-arg]
    with pytest.raises(AttributeError):
        cached_collection.insert_one(document)  # type: ignore[operator]
    collection.drop()
    assert collection.find_one({"_id": document["_id"]}) is None

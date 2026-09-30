from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient, ReadPreference
from pymongo.synchronous.collection import Collection

from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.database import CachedDatabase
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.synchronous.database import Database

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> MongoClient[dict[str, Any]]:
    return MongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
def manager(client: MongoClient[dict[str, Any]]) -> CacheManager[dict[str, Any]]:
    return CacheManager(client)


def test_database_retains_access_to_the_caller_owned_raw_database(
    manager: CacheManager[dict[str, Any]], client: MongoClient[dict[str, Any]]
) -> None:
    raw_database = client["example"]

    database = CachedDatabase(manager, raw_database)

    assert database.raw is raw_database
    assert database.manager is manager


def test_database_attribute_access_returns_a_cached_collection_facade(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"].items

    assert isinstance(collection, CachedCollection)
    assert collection.name == "items"


@pytest.mark.parametrize(
    "name",
    [
        "codec_options",
        "command",
        "create_collection",
        "get_collection",
        "with_options",
        "_private",
    ],
)
def test_database_does_not_expose_undeclared_pymongo_attributes(
    manager: CacheManager[dict[str, Any]], name: str
) -> None:
    database = manager["example"]

    with pytest.raises(AttributeError, match=repr(name)):
        getattr(database, name)


def test_database_index_access_names_a_collection_colliding_with_a_pymongo_method(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"]["create_collection"]

    assert isinstance(collection, CachedCollection)
    assert collection.name == "create_collection"


@pytest.mark.parametrize(
    "get_raw_collection",
    [
        pytest.param(
            lambda database: database.get_collection(
                "items", read_preference=ReadPreference.SECONDARY
            ),
            id="get_collection",
        ),
        pytest.param(
            lambda database: database.with_options(
                read_preference=ReadPreference.SECONDARY
            )["items"],
            id="with_options",
        ),
    ],
)
def test_optioned_raw_database_collection_keeps_its_options_through_the_cached_view(
    manager: CacheManager[dict[str, Any]],
    get_raw_collection: Callable[
        [Database[dict[str, Any]]], Collection[dict[str, Any]]
    ],
) -> None:
    raw_collection = get_raw_collection(manager["example"].raw)

    collection = manager.cached(raw_collection)

    assert collection.raw is raw_collection
    assert collection.name == "items"
    assert collection.raw.read_preference == ReadPreference.SECONDARY


def test_database_builds_a_collection_facade_around_its_raw_database(
    manager: CacheManager[dict[str, Any]],
) -> None:
    collection = manager["example"]["items"]

    assert isinstance(collection, CachedCollection)
    assert not issubclass(CachedCollection, Collection)
    assert isinstance(collection.raw, Collection)
    assert collection.name == "items"
    assert collection.raw.database.name == "example"

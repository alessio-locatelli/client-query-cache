from operator import itemgetter
from typing import TYPE_CHECKING, Any

import pytest
from bson.codec_options import CodecOptions
from pymongo import MongoClient, ReadPreference
from pymongo.synchronous.database import Database

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.synchronous import (
    CacheManager,
    CacheSnapshot,
    StreamCostSnapshot,
    StreamHealthSnapshot,
    StreamHealthStatus,
)
from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.database import CachedDatabase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pymongo.synchronous.collection import Collection

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](
        "mongodb://localhost:27017", connect=False
    ) as instance:
        yield instance


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    assert not issubclass(CacheManager, MongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, Database)
    assert isinstance(database.raw, Database)
    assert database.name == "example"
    assert database.raw.client is client


def test_manager_used_as_a_context_manager_closes_its_own_cache(
    client: MongoClient[dict[str, Any]],
) -> None:
    with CacheManager(client) as manager:
        core = manager.cache_core

    assert core.snapshot().lifecycle == CacheLifecycleState.CLOSED.value


def test_manager_close_does_not_close_the_caller_owned_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    CacheManager(client).close()

    assert client._closed is False


def test_unique_keys_for_rejects_a_probe_racing_a_concurrent_index_change(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    namespace = NamespaceId("example", "widgets")

    def racing_list_indexes() -> list[dict[str, Any]]:
        manager.cache_core.record_index_change(namespace)
        return [{"key": {"email": 1}, "name": "email_1", "unique": True}]

    assert manager._unique_keys_for(namespace, racing_list_indexes) == ()


@pytest.mark.parametrize(
    "get_raw_collection",
    [
        pytest.param(itemgetter("items"), id="plain"),
        pytest.param(
            lambda database: database["items"].with_options(
                read_preference=ReadPreference.SECONDARY
            ),
            id="with_options",
        ),
        pytest.param(
            lambda database: database.get_collection(
                "items", codec_options=CodecOptions(tz_aware=True)
            ),
            id="get_collection",
        ),
    ],
)
def test_cached_view_retains_the_exact_supplied_collection(
    client: MongoClient[dict[str, Any]],
    get_raw_collection: Callable[
        [Database[dict[str, Any]]], Collection[dict[str, Any]]
    ],
) -> None:
    manager = CacheManager(client)
    raw_collection = get_raw_collection(client["example"])

    collection = manager.get_cached_collection(raw_collection)

    assert isinstance(collection, CachedCollection)
    assert collection.raw is raw_collection
    assert collection.database.raw is raw_collection.database
    assert collection.database.manager is manager


def test_cached_rejects_a_collection_owned_by_another_client(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    foreign_client = MongoClient[dict[str, Any]](
        "mongodb://localhost:27017", connect=False
    )

    with pytest.raises(ValueError, match="different client"):
        manager.get_cached_collection(foreign_client["example"]["items"])


def test_repeated_cached_views_share_the_manager_and_raw_collection(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    first = manager.get_cached_collection(raw_collection)
    second = manager.get_cached_collection(raw_collection)

    assert first.raw is second.raw is raw_collection
    assert first.database.manager is second.database.manager is manager


def test_manager_inspection_delegates_without_activation(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    manager.cache_core.record_bypass()
    manager.cache_core.record_stream_poll("example")
    assert isinstance(manager.snapshot(), CacheSnapshot)
    assert isinstance(manager.stream_cost_snapshot("example"), StreamCostSnapshot)
    assert isinstance(manager.stream_health_snapshot("example"), StreamHealthSnapshot)
    assert manager.snapshot() == manager.cache_core.snapshot()
    assert manager.stream_cost_snapshot(
        "example"
    ) == manager.cache_core.stream_cost_snapshot("example")
    assert manager.active_stream_cost_databases() == ["example"]
    assert (
        manager.stream_health_snapshot("example").status
        is StreamHealthStatus.NOT_STARTED
    )
    assert (
        manager.stream_health_snapshot("untouched").status
        is StreamHealthStatus.NOT_STARTED
    )
    manager.close()
    assert manager.snapshot() == manager.cache_core.snapshot()
    assert manager.snapshot().bypasses == 1
    assert manager.snapshot().lifecycle == "closed"
    assert (
        manager.stream_health_snapshot("untouched").status is StreamHealthStatus.CLOSED
    )
    assert manager.stream_cost_snapshot(
        "example"
    ) == manager.cache_core.stream_cost_snapshot("example")
    assert (
        manager.active_stream_cost_databases()
        == manager.cache_core.active_stream_cost_databases()
    )

import math
import time
from operator import itemgetter
from typing import TYPE_CHECKING, Any

import pytest
from bson import Timestamp
from bson.codec_options import CodecOptions
from pymongo import MongoClient, ReadPreference
from pymongo.synchronous.database import Database

from client_query_cache._core.errors import (
    BarrierArgumentError,
    BarrierClosedError,
    BarrierTimeoutError,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.database import CachedDatabase
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pymongo.synchronous.collection import Collection

    from client_query_cache._core.barrier import CausalBoundary

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> MongoClient[dict[str, Any]]:
    return MongoClient("mongodb://localhost:27017", connect=False)


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

    assert manager.unique_keys_for(namespace, racing_list_indexes) == ()


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

    collection = manager.cached(raw_collection)

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
        manager.cached(foreign_client["example"]["items"])


def test_repeated_cached_views_share_the_manager_and_raw_collection(
    client: MongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    first = manager.cached(raw_collection)
    second = manager.cached(raw_collection)

    assert first.raw is second.raw is raw_collection
    assert first.database.manager is second.database.manager is manager


_UNREACHABLE_URI = "mongodb://localhost:1/?serverSelectionTimeoutMS=30000"
_OPERATION_TIME = Timestamp(1_700_000_000, 7)


@pytest.fixture
def manager(client: MongoClient[dict[str, Any]]) -> Iterator[CacheManager[Any]]:
    with CacheManager(client) as cache_manager:
        yield cache_manager


@pytest.fixture
def unreachable_manager() -> Iterator[CacheManager[Any]]:
    with (
        MongoClient[dict[str, Any]](_UNREACHABLE_URI, connect=False) as client,
        CacheManager(client) as cache_manager,
    ):
        yield cache_manager


def _boundary_after_operation(manager: CacheManager[Any]) -> CausalBoundary:
    with manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)
        return manager.causal_boundary(session)


def test_causal_boundary_copies_the_sessions_operation_time(
    manager: CacheManager[Any],
) -> None:
    assert _boundary_after_operation(manager).operation_time == _OPERATION_TIME


def test_causal_boundary_rejects_a_session_without_an_operation(
    manager: CacheManager[Any],
) -> None:
    with (
        manager.client.start_session() as session,
        pytest.raises(BarrierArgumentError, match="not completed any operation"),
    ):
        manager.causal_boundary(session)


def test_causal_boundary_rejects_an_open_transaction(
    manager: CacheManager[Any],
) -> None:
    with manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)
        session.start_transaction()

        with pytest.raises(BarrierArgumentError, match="open transaction"):
            manager.causal_boundary(session)


def test_causal_boundary_rejects_a_session_of_another_client(
    manager: CacheManager[Any], unreachable_manager: CacheManager[Any]
) -> None:
    with unreachable_manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)

        with pytest.raises(BarrierArgumentError, match="different client"):
            manager.causal_boundary(session)


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True, None])
def test_wait_for_invalidations_validates_the_timeout_before_activation(
    manager: CacheManager[Any], timeout: object
) -> None:
    boundary = _boundary_after_operation(manager)

    with pytest.raises(BarrierArgumentError):
        manager.wait_for_invalidations("example", boundary, timeout=timeout)  # type: ignore[arg-type]

    assert not manager._coordinator._supervisors


def test_wait_for_invalidations_rejects_another_managers_boundary(
    manager: CacheManager[Any], client: MongoClient[dict[str, Any]]
) -> None:
    with CacheManager(client) as other_manager:
        boundary = _boundary_after_operation(other_manager)

    with pytest.raises(BarrierArgumentError, match="this manager"):
        manager.wait_for_invalidations("example", boundary, timeout=1)


def test_wait_for_invalidations_after_close_raises_closed(
    manager: CacheManager[Any],
) -> None:
    boundary = _boundary_after_operation(manager)
    manager.close()

    with pytest.raises(BarrierClosedError):
        manager.wait_for_invalidations("example", boundary, timeout=1)


def test_wait_for_invalidations_times_out_during_activation(
    unreachable_manager: CacheManager[Any],
) -> None:
    boundary = _boundary_after_operation(unreachable_manager)
    timeout = 0.3
    started = time.monotonic()

    with pytest.raises(BarrierTimeoutError):
        unreachable_manager.wait_for_invalidations("example", boundary, timeout=timeout)

    assert time.monotonic() - started < timeout + 1
    assert not unreachable_manager._coordinator._supervisors

import asyncio
import math
import time
from operator import itemgetter
from typing import TYPE_CHECKING, Any

import pytest
from bson import Timestamp
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.database import AsyncDatabase

from client_query_cache._core.errors import (
    BarrierArgumentError,
    BarrierClosedError,
    BarrierTimeoutError,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.lifecycle import CacheLifecycleState
from client_query_cache.asynchronous.collection import CachedCollection
from client_query_cache.asynchronous.database import CachedDatabase
from client_query_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from pymongo.asynchronous.collection import AsyncCollection

    from client_query_cache._core.barrier import CausalBoundary

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


def test_manager_does_not_subclass_or_replace_the_caller_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    assert not issubclass(CacheManager, AsyncMongoClient)
    assert CacheManager(client).client is client


def test_manager_builds_a_database_facade_around_the_caller_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    database = CacheManager(client)["example"]

    assert isinstance(database, CachedDatabase)
    assert not issubclass(CachedDatabase, AsyncDatabase)
    assert isinstance(database.raw, AsyncDatabase)
    assert database.name == "example"
    assert database.raw.client is client


async def test_manager_used_as_a_context_manager_closes_its_own_cache(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    async with CacheManager(client) as manager:
        core = manager.cache_core

    assert core.snapshot().lifecycle == CacheLifecycleState.CLOSED.value


async def test_manager_close_does_not_close_the_caller_owned_client(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    await CacheManager(client).close()

    assert client._closed is False


async def test_unique_keys_for_rejects_a_probe_racing_a_concurrent_index_change(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    namespace = NamespaceId("example", "widgets")

    async def racing_list_indexes() -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        manager.cache_core.record_index_change(namespace)
        return [{"key": {"email": 1}, "name": "email_1", "unique": True}]

    assert await manager.unique_keys_for(namespace, racing_list_indexes) == ()


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
    client: AsyncMongoClient[dict[str, Any]],
    get_raw_collection: Callable[
        [AsyncDatabase[dict[str, Any]]], AsyncCollection[dict[str, Any]]
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
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    foreign_client = AsyncMongoClient[dict[str, Any]](
        "mongodb://localhost:27017", connect=False
    )

    with pytest.raises(ValueError, match="different client"):
        manager.cached(foreign_client["example"]["items"])


def test_repeated_cached_views_share_the_manager_and_raw_collection(
    client: AsyncMongoClient[dict[str, Any]],
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
async def manager(
    client: AsyncMongoClient[dict[str, Any]],
) -> AsyncIterator[CacheManager[Any]]:
    async with CacheManager(client) as cache_manager:
        yield cache_manager


@pytest.fixture
async def unreachable_manager() -> AsyncIterator[CacheManager[Any]]:
    async with (
        AsyncMongoClient[dict[str, Any]](_UNREACHABLE_URI, connect=False) as client,
        CacheManager(client) as cache_manager,
    ):
        yield cache_manager


async def _boundary_after_operation(manager: CacheManager[Any]) -> CausalBoundary:
    async with manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)
        return manager.causal_boundary(session)


async def test_causal_boundary_copies_the_sessions_operation_time(
    manager: CacheManager[Any],
) -> None:
    boundary = await _boundary_after_operation(manager)

    assert boundary.operation_time == _OPERATION_TIME


async def test_causal_boundary_rejects_a_session_without_an_operation(
    manager: CacheManager[Any],
) -> None:
    async with manager.client.start_session() as session:
        with pytest.raises(BarrierArgumentError, match="not completed any operation"):
            manager.causal_boundary(session)


async def test_causal_boundary_rejects_an_open_transaction(
    manager: CacheManager[Any],
) -> None:
    async with manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)
        await session.start_transaction()

        with pytest.raises(BarrierArgumentError, match="open transaction"):
            manager.causal_boundary(session)


async def test_causal_boundary_rejects_a_session_of_another_client(
    manager: CacheManager[Any], unreachable_manager: CacheManager[Any]
) -> None:
    async with unreachable_manager.client.start_session() as session:
        session.advance_operation_time(_OPERATION_TIME)

        with pytest.raises(BarrierArgumentError, match="different client"):
            manager.causal_boundary(session)


@pytest.mark.parametrize("invalid_timeout", [0, -1, math.nan, math.inf, True, None])
async def test_wait_for_invalidations_validates_the_timeout_before_activation(
    manager: CacheManager[Any], invalid_timeout: object
) -> None:
    boundary = await _boundary_after_operation(manager)

    with pytest.raises(BarrierArgumentError):
        await manager.wait_for_invalidations(
            "example",
            boundary,
            timeout=invalid_timeout,  # type: ignore[arg-type]
        )

    assert not manager._coordinator._supervisors


async def test_wait_for_invalidations_rejects_another_managers_boundary(
    manager: CacheManager[Any], client: AsyncMongoClient[dict[str, Any]]
) -> None:
    async with CacheManager(client) as other_manager:
        boundary = await _boundary_after_operation(other_manager)

    with pytest.raises(BarrierArgumentError, match="this manager"):
        await manager.wait_for_invalidations("example", boundary, timeout=1)


async def test_wait_for_invalidations_after_close_raises_closed(
    manager: CacheManager[Any],
) -> None:
    boundary = await _boundary_after_operation(manager)
    await manager.close()

    with pytest.raises(BarrierClosedError):
        await manager.wait_for_invalidations("example", boundary, timeout=1)


async def test_wait_for_invalidations_times_out_during_activation(
    unreachable_manager: CacheManager[Any],
) -> None:
    boundary = await _boundary_after_operation(unreachable_manager)
    timeout = 0.3
    started = time.monotonic()

    with pytest.raises(BarrierTimeoutError):
        await unreachable_manager.wait_for_invalidations(
            "example", boundary, timeout=timeout
        )

    assert time.monotonic() - started < timeout + 1
    assert not unreachable_manager._coordinator._supervisors

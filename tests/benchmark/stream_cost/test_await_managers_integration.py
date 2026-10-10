from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from pymongo import AsyncMongoClient, MongoClient

from benchmarks.stream_cost.await_commands import AwaitCommandListener
from benchmarks.stream_cost.await_run import _invoke, _wait_for
from client_query_cache._core.stream_options import DEFAULT_MAX_AWAIT_TIME_MS
from client_query_cache._types import BsonDict, MaxAwaitTimeMs, NonEmptyStr
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from benchmarks.stream_cost.await_model import ExecutionModel
    from benchmarks.stream_cost.await_run import _Manager
    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class ManagedStream:
    manager: _Manager
    listener: AwaitCommandListener
    database: NonEmptyStr  # Unique test database name.
    expected_ms: MaxAwaitTimeMs  # Expected wire option.


@pytest.fixture(params=["sync", "async"], ids=["sync", "async"])
async def managed_streams(
    request: pytest.FixtureRequest,
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[ManagedStream, ...]]:
    model = cast("ExecutionModel", request.param)
    monkeypatch.setenv("CLIENT_QUERY_CACHE_MAX_AWAIT_TIME_MS", "777")
    observed = []
    async with AsyncExitStack() as resources:
        for index, override in enumerate((None, DEFAULT_MAX_AWAIT_TIME_MS + 5000)):
            listener = AwaitCommandListener()
            manager: _Manager
            if model == "sync":
                client = resources.enter_context(
                    MongoClient[BsonDict](mongodb_uri, event_listeners=[listener])
                )
                manager = (
                    CacheManager(client)
                    if override is None
                    else CacheManager(client, max_await_time_ms=override)
                )
            else:
                async_client = await resources.enter_async_context(
                    AsyncMongoClient[BsonDict](mongodb_uri, event_listeners=[listener])
                )
                manager = (
                    AsyncCacheManager(async_client)
                    if override is None
                    else AsyncCacheManager(async_client, max_await_time_ms=override)
                )
            resources.push_async_callback(_invoke, manager.close)
            database = f"{cached_database_name}_{index}"
            resources.push_async_callback(
                _invoke, manager.client.drop_database, database
            )
            seed: BsonDict = {"_id": 0, "value": 0}
            await _invoke(manager.client[database]["measured"].insert_one, seed)
            await _invoke(manager[database]["measured"].find_one, {"_id": 0})
            observed.append(
                ManagedStream(
                    manager,
                    listener,
                    database,
                    DEFAULT_MAX_AWAIT_TIME_MS if override is None else override,
                )
            )
        yield tuple(observed)


async def _exercise_stream(observed: ManagedStream) -> None:
    manager = observed.manager
    database = observed.database
    listener = observed.listener
    await _invoke(
        manager.client[database]["measured"].update_one,
        {"_id": 0},
        {"$set": {"value": 1}},
    )
    await _wait_for(
        lambda: manager.cache_core.stream_cost_snapshot(database).invalidations >= 1,
        10,
        listener,
    )
    supervisor = manager._coordinator._supervisors[database]
    stream = supervisor._stream
    assert stream is not None
    await _invoke(stream.close)
    await _wait_for(
        lambda: supervisor._stream is not stream and supervisor.healthy, 10, listener
    )
    before = manager.cache_core.stream_cost_snapshot(database).invalidations
    await _invoke(
        manager.client[database]["measured"].update_one,
        {"_id": 0},
        {"$set": {"value": 2}},
    )
    await _wait_for(
        lambda: (
            manager.cache_core.stream_cost_snapshot(database).invalidations > before
        ),
        10,
        listener,
    )
    assert await _invoke(manager[database]["measured"].find_one, {"_id": 0}) == {
        "_id": 0,
        "value": 2,
    }
    assert all(
        command.max_time_ms == observed.expected_ms for command in listener.snapshot()
    )
    await _wait_for(
        lambda: any(
            command.completed_seconds is None for command in listener.snapshot()
        ),
        10,
        listener,
    )
    await _invoke(manager.close)
    assert not manager.cache_core.is_database_available(database)


async def test_manager_options_survive_reopen_and_inflight_shutdown(
    managed_streams: tuple[ManagedStream, ...],
) -> None:
    for observed in managed_streams:
        await _exercise_stream(observed)
    assert len({observed.expected_ms for observed in managed_streams}) == 2

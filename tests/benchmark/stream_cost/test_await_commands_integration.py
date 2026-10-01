from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost.await_commands import AwaitCommandListener
from benchmarks.stream_cost.await_run import _wait_for
from client_query_cache._core.manager import CacheCore
from client_query_cache.synchronous.streams import DatabaseStreamSupervisor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration

_INSTRUMENTATION_AWAIT_MS = 20


@dataclass(frozen=True, slots=True)
class ObservedStream:
    listener: AwaitCommandListener
    cache: CacheCore
    database: DatabaseName


@pytest.fixture
def observed_stream(
    mongodb_uri: MongoDbUri, cached_database_name: DatabaseName
) -> Iterator[ObservedStream]:
    listener = AwaitCommandListener()
    cache = CacheCore()
    with ExitStack() as resources:
        client = resources.enter_context(
            MongoClient[dict[str, object]](mongodb_uri, event_listeners=[listener])
        )
        supervisor = DatabaseStreamSupervisor(
            client[cached_database_name],
            cache,
            max_await_time_ms=_INSTRUMENTATION_AWAIT_MS,
        )
        resources.callback(supervisor.stop)
        supervisor.start()
        yield ObservedStream(listener, cache, cached_database_name)


async def test_each_iteration_call_issues_at_most_one_getmore_command(
    observed_stream: ObservedStream,
) -> None:
    await _wait_for(
        lambda: (
            sum(
                command.completed_seconds is not None
                for command in observed_stream.listener.snapshot()
            )
            >= 3
        ),
        10,
        observed_stream.listener,
    )
    completed = tuple(
        command
        for command in observed_stream.listener.snapshot()
        if command.completed_seconds is not None
    )
    assert all(
        command.max_time_ms == _INSTRUMENTATION_AWAIT_MS for command in completed
    )
    assert not any(command.failed for command in completed)
    assert observed_stream.cache.stream_cost_snapshot(
        observed_stream.database
    ).stream_polls >= len(completed)

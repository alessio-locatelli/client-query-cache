from __future__ import annotations

from typing import TYPE_CHECKING, Any

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.stream_cost import (
    LagCaptureWindowConfig,
    StreamCostSnapshot,
)
from client_query_cache._types import NonNegativeFloat, NonNegativeInt
from tests.polling import wait_until, wait_until_async

if TYPE_CHECKING:
    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.synchronous.database import Database

    from client_query_cache._core.manager import CacheCore

SINGLE_EVENT_LAG_WINDOW = LagCaptureWindowConfig(
    window_count=1, events_per_window=1, min_separation_events=0
)
WALL_TIME_BOUND_TOLERANCE_SECONDS = 1.0
_STREAM_BARRIER_COLLECTION_NAME = "stream_barrier"


def assert_lag_matches_write_interval(
    snapshot: StreamCostSnapshot,
    write_started: NonNegativeFloat,
    write_finished: NonNegativeFloat,
) -> None:
    assert snapshot.invalidations == 1
    lag_seconds = snapshot.invalidation_lag_windows[0][0]
    applied_at = snapshot.invalidation_apply_readings[0].wall_seconds
    tolerance = WALL_TIME_BOUND_TOLERANCE_SECONDS
    assert (
        applied_at - write_finished - tolerance
        <= lag_seconds
        <= applied_at - write_started + tolerance
    )


def _generation(cache: CacheCore, namespace: NamespaceId) -> NonNegativeInt:
    return cache.capture_namespace_generation(namespace).generation


def wait_for_stream_barrier(
    cache: CacheCore, database: Database[dict[str, Any]]
) -> None:
    namespace = NamespaceId(database.name, _STREAM_BARRIER_COLLECTION_NAME)
    before = _generation(cache, namespace)
    database[_STREAM_BARRIER_COLLECTION_NAME].insert_one({})
    wait_until(lambda: _generation(cache, namespace) > before)


async def wait_for_stream_barrier_async(
    cache: CacheCore, database: AsyncDatabase[dict[str, Any]]
) -> None:
    namespace = NamespaceId(database.name, _STREAM_BARRIER_COLLECTION_NAME)
    before = _generation(cache, namespace)
    await database[_STREAM_BARRIER_COLLECTION_NAME].insert_one({})
    await wait_until_async(lambda: _generation(cache, namespace) > before)

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from client_query_cache._core.stream_cost import (
    LagCaptureWindowConfig,
    StreamCostSnapshot,
)
from client_query_cache._types import BsonDict, NonNegativeFloat
from tests.polling import wait_until, wait_until_async

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.synchronous.database import Database

    from client_query_cache._core.contracts import LocalCacheCore as CacheCore

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


class StreamBarrier:
    __slots__ = ("_routed",)

    def __init__(self) -> None:
        self._routed: set[object] = set()

    def observe(self, route: Callable[..., bool]) -> Callable[..., bool]:
        def observed(
            cache: CacheCore,
            database: str,
            event: Mapping[str, Any],
            **options: object,
        ) -> bool:
            must_reopen = route(cache, database, event, **options)
            try:
                if event["ns"]["coll"] == _STREAM_BARRIER_COLLECTION_NAME:
                    self._routed.add(event["documentKey"]["_id"])
            except KeyError:
                pass
            return must_reopen

        return observed

    def wait(self, database: Database[BsonDict]) -> None:
        inserted_id = (
            database[_STREAM_BARRIER_COLLECTION_NAME].insert_one({}).inserted_id
        )
        wait_until(lambda: inserted_id in self._routed)

    async def wait_async(self, database: AsyncDatabase[BsonDict]) -> None:
        inserted = await database[_STREAM_BARRIER_COLLECTION_NAME].insert_one({})
        await wait_until_async(lambda: inserted.inserted_id in self._routed)

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from pymongo import MongoClient

from client_query_cache import CacheCoreConfig
from client_query_cache._types import BsonDict, NonNegativeFloat, PositiveFloat
from client_query_cache.synchronous.manager import CacheManager
from development.benchmarks.stream_cost import calibration, compression_matrix_runner

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from tests.conftest import MongoDbUri

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def isolated_calibration_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        calibration,
        "time",
        SimpleNamespace(time=time.time, monotonic=time.monotonic),
    )


@pytest.fixture
def unpaced_compression_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    def issue_writes(
        issue_write: Callable[[], None],
        schedule: Sequence[NonNegativeFloat],
        *,
        start_monotonic: NonNegativeFloat,
        tolerance_seconds: PositiveFloat,
    ) -> tuple[NonNegativeFloat, ...]:
        del tolerance_seconds
        # Keep issue timestamps comparable with real stream invalidation timestamps.
        offsets: list[NonNegativeFloat] = []
        for _ in schedule:
            offsets.append(time.monotonic() - start_monotonic)
            issue_write()
        return tuple(offsets)

    monkeypatch.setattr(
        compression_matrix_runner, "replay_write_schedule", issue_writes
    )


@pytest.fixture
def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture(params=[False], ids=["default"])
def cache_manager(
    request: pytest.FixtureRequest,
    raw_mongo_client: MongoClient[BsonDict],
) -> Iterator[CacheManager[BsonDict]]:
    manager = CacheManager(
        raw_mongo_client, cache_config=CacheCoreConfig(enable_telemetry=request.param)
    )
    yield manager
    manager.close()

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost import calibration
from client_query_cache._types import BsonDict
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

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
def raw_mongo_client(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture
def cache_manager(
    raw_mongo_client: MongoClient[BsonDict],
) -> Iterator[CacheManager[BsonDict]]:
    manager = CacheManager(raw_mongo_client)
    yield manager
    manager.close()

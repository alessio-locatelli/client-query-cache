from __future__ import annotations

import time
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.consolidated_stream import (
    reset_run_state,
    verify_single_consolidated_stream,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from client_query_cache._types import BsonDict, PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo import MongoClient

    from client_query_cache.synchronous.manager import CacheManager
    from tests.conftest import CollectionName, DatabaseName

pytestmark = pytest.mark.integration


def _wait_until(
    predicate: Callable[[], bool], *, timeout: PositiveFloat = 15.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)  # pragma: no cover (timing-dependent retry)
    pytest.fail(  # pragma: no cover (test timeout diagnostic)
        "condition was not met within the timeout"
    )


def test_verify_single_consolidated_stream_rejects_an_inactive_database(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
) -> None:
    with pytest.raises(BenchmarkSetupError, match="exactly one consolidated stream"):
        verify_single_consolidated_stream(cache_manager, database=cached_database_name)


def test_verify_single_consolidated_stream_passes_for_two_cached_collections(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    first = database[persistent_collection_name]
    second = database[nonpersistent_collection_name]
    first.raw.insert_one({"_id": "doc-1", "v": 1})
    second.raw.insert_one({"_id": "doc-1", "v": 1})

    first.find_one({"_id": "doc-1"})
    second.find_one({"_id": "doc-1"})

    _wait_until(
        lambda: (
            cache_manager.cache_core.active_stream_cost_databases()
            == [cached_database_name]
        )
    )
    verify_single_consolidated_stream(cache_manager, database=cached_database_name)


def test_reset_run_state_drops_the_database_and_returns_an_empty_cache(
    raw_mongo_client: MongoClient[BsonDict],
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    collection.raw.insert_one({"_id": "doc-1", "v": 1})
    collection.find_one({"_id": "doc-1"})
    collection.find_one({"_id": "doc-1"})
    assert cache_manager.cache_core.snapshot().entry_count > 0

    with closing(
        reset_run_state(raw_mongo_client, cache_manager, database=cached_database_name)
    ) as new_manager:
        assert new_manager.cache_core.snapshot().entry_count == 0
        assert new_manager.cache_core.active_stream_cost_databases() == []
        remaining_collections = raw_mongo_client[
            cached_database_name
        ].list_collection_names()
        assert persistent_collection_name not in remaining_collections

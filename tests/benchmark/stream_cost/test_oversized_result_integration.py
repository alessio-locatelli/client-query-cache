from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from benchmarks.stream_cost.oversized_result import (
    MINIMUM_ENCODER_REPETITIONS,
    measure_oversized_result_workload,
)
from benchmarks.stream_cost.workload import verify_oversized_primed
from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo import MongoClient

    from tests.conftest import CollectionName, DatabaseName

pytestmark = pytest.mark.integration

_MAX_ENTRY_BYTES = 2_000
_DOCUMENT_COUNT = 50
_PADDING_BYTES = 100


def _oversized_documents() -> list[dict[str, Any]]:
    return [
        {"_id": index, "padding": "x" * _PADDING_BYTES}
        for index in range(_DOCUMENT_COUNT)
    ]


@pytest.fixture
def small_max_entry_cache_manager(
    raw_mongo_client: MongoClient[dict[str, Any]],
) -> Iterator[CacheManager[dict[str, Any]]]:
    manager = CacheManager(
        raw_mongo_client,
        cache_config=CacheCoreConfig(
            shared_budget_bytes=_MAX_ENTRY_BYTES * 4,
            max_entry_bytes=_MAX_ENTRY_BYTES,
        ),
    )
    yield manager
    manager.close()


def test_the_oversized_result_workload_measures_both_costs_from_one_run(
    small_max_entry_cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = small_max_entry_cache_manager[cached_database_name]
    collection = database[persistent_collection_name]
    collection.raw.insert_many(_oversized_documents())

    before = small_max_entry_cache_manager.cache_core.snapshot()
    measurement = measure_oversized_result_workload(
        lambda: collection.find({}),
        max_entry_bytes=_MAX_ENTRY_BYTES,
        codec_options=collection.raw.codec_options,
        repetitions=MINIMUM_ENCODER_REPETITIONS,
        acceptable_savings_threshold_seconds=0.0,
    )
    after = small_max_entry_cache_manager.cache_core.snapshot()

    verify_oversized_primed(before, after, variant_name="oversized-result")
    assert measurement.end_to_end_cost_seconds >= 0
    assert 0 < measurement.savings.prefix_length < _DOCUMENT_COUNT
    assert measurement.savings.prefix_cost_seconds >= 0
    assert measurement.savings.full_cost_seconds >= 0

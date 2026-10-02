from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from pymongo import AsyncMongoClient, MongoClient

from client_query_cache import CacheManager
from client_query_cache._core.keys import NamespaceId
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.otel import register_cache_metrics

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from faker import Faker

pytestmark = pytest.mark.integration


@pytest.fixture(params=[False, True], ids=["sync", "async"])
async def documented_manager(
    request: pytest.FixtureRequest,
) -> AsyncIterator[
    CacheManager[dict[str, object]] | AsyncCacheManager[dict[str, object]]
]:
    if request.param:
        async with (
            AsyncMongoClient[dict[str, object]](connect=False) as client,
            AsyncCacheManager(client) as manager,
        ):
            yield manager
    else:
        with (
            MongoClient[dict[str, object]](connect=False) as sync_client,
            CacheManager(sync_client) as sync_manager,
        ):
            yield sync_manager


def test_documented_otel_usage_snippet_runs_against_a_real_meter_provider(
    faker: Faker,
    documented_manager: CacheManager[dict[str, object]]
    | AsyncCacheManager[dict[str, object]],
) -> None:
    reader = InMemoryMetricReader()

    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("your-application")
    register_cache_metrics(meter, documented_manager)
    documented_manager.cache_core.lookup_identity(
        NamespaceId(faker.word(), faker.word()), faker.uuid4(), faker.word()
    )

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    metrics = [
        metric
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    ]
    misses = next(
        metric for metric in metrics if metric.name == "client_query_cache.cache.misses"
    )
    miss_point = misses.data.data_points[0]
    assert isinstance(miss_point, NumberDataPoint)
    assert miss_point.value == 1

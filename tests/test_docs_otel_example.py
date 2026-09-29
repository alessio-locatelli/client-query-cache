from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache.otel import register_cache_metrics

if TYPE_CHECKING:
    from faker import Faker

pytestmark = pytest.mark.integration


def test_documented_otel_usage_snippet_runs_against_a_real_meter_provider(
    faker: Faker,
) -> None:
    reader = InMemoryMetricReader()

    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("your-application")
    cache_core = CacheCore()
    register_cache_metrics(meter, cache_core)
    cache_core.lookup_identity(
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

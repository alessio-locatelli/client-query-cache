from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from client_query_cache._core.manager import CacheCore
from client_query_cache.otel import register_cache_metrics

pytestmark = pytest.mark.unit


def test_documented_otel_usage_snippet_runs_against_a_real_meter_provider() -> None:
    reader = InMemoryMetricReader()

    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("your-application")
    register_cache_metrics(meter, CacheCore())

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    metric_names = {
        metric.name
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    assert "client_query_cache.cache.hits" in metric_names

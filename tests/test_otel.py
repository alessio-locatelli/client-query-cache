from __future__ import annotations

import dataclasses
import importlib
import sys
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.snapshots import CacheSnapshot
from client_query_cache._core.stream_cost import (
    INVALIDATION_LAG_CLOCK_SKEW_LIMITATION,
    RESIDENT_BYTES_SCOPE,
    StreamCostSnapshot,
)
from client_query_cache.otel import register_cache_metrics

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter
    from opentelemetry.sdk.metrics.export import Metric

pytestmark = pytest.mark.unit

_DB_NAMESPACE_ATTRIBUTE = "db.namespace"


def _make_cache_snapshot(**overrides: object) -> CacheSnapshot:
    defaults: dict[str, object] = {
        "lifecycle": "active",
        "used_bytes": 1_024,
        "shared_budget_bytes": 1_048_576,
        "max_entry_bytes": 65_536,
        "entry_count": 3,
        "hits": 7,
        "misses": 2,
        "evictions": 1,
        "bypasses": 4,
        "oversized_bypasses": 5,
    }
    defaults.update(overrides)
    return CacheSnapshot(**defaults)  # type: ignore[arg-type]


def _make_stream_snapshot(
    database: str, *, lag_windows: tuple[tuple[float, ...], ...] = ()
) -> StreamCostSnapshot:
    return StreamCostSnapshot(
        database=database,
        stream_polls=11,
        logical_event_bytes=2_048,
        invalidations=5,
        invalidation_lag_windows=lag_windows,
        invalidation_lag_clock_skew_limitation=INVALIDATION_LAG_CLOCK_SKEW_LIMITATION,
        invalidation_apply_readings=(),
        resident_bytes=1_024,
        resident_bytes_scope=RESIDENT_BYTES_SCOPE,
    )


@dataclasses.dataclass(slots=True)
class _FakeCacheCore:
    _snapshot: CacheSnapshot
    _stream_snapshots: dict[str, StreamCostSnapshot]

    def snapshot(self) -> CacheSnapshot:
        return self._snapshot

    def active_stream_cost_databases(self) -> list[str]:
        return list(self._stream_snapshots)

    def stream_cost_snapshot(self, database: str) -> StreamCostSnapshot:
        return self._stream_snapshots[database]


def _number_data_points(metric: Metric) -> tuple[NumberDataPoint, ...]:
    points = tuple(metric.data.data_points)
    for point in points:
        assert isinstance(point, NumberDataPoint)
    return points  # type: ignore[return-value]


def _attributes(point: NumberDataPoint) -> dict[str, object]:
    return dict(point.attributes or {})


def _collect_metrics(reader: InMemoryMetricReader) -> dict[str, Metric]:
    metrics_data = reader.get_metrics_data()
    metrics: dict[str, Metric] = {}
    assert metrics_data is not None
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                metrics[metric.name] = metric
    return metrics


def test_base_package_is_importable_without_opentelemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    for name in [
        module_name
        for module_name in sys.modules
        if module_name == "client_query_cache"
        or module_name.startswith("client_query_cache.")
    ]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    module = importlib.import_module("client_query_cache")

    assert module.CacheManager is not None
    assert "client_query_cache.otel" not in sys.modules


def test_otel_module_reports_actionable_error_without_opentelemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", None)
    monkeypatch.delitem(sys.modules, "client_query_cache.otel", raising=False)

    with pytest.raises(ImportError, match="opentelemetry-api"):
        importlib.import_module("client_query_cache.otel")


@pytest.fixture
def reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def meter(reader: InMemoryMetricReader) -> Meter:
    provider = MeterProvider(metric_readers=[reader])
    return provider.get_meter("test")


@pytest.mark.parametrize(
    ("metric_name", "field"),
    [
        ("client_query_cache.cache.hits", "hits"),
        ("client_query_cache.cache.misses", "misses"),
        ("client_query_cache.cache.evictions", "evictions"),
        ("client_query_cache.cache.bypasses", "bypasses"),
        ("client_query_cache.cache.bypasses.oversized", "oversized_bypasses"),
        ("client_query_cache.cache.entries", "entry_count"),
    ],
)
def test_manager_wide_instruments_report_current_snapshot_values(
    meter: Meter, reader: InMemoryMetricReader, metric_name: str, field: str
) -> None:
    snapshot = _make_cache_snapshot()
    cache_core = _FakeCacheCore(snapshot, {})

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    (point,) = _number_data_points(_collect_metrics(reader)[metric_name])
    assert point.value == getattr(snapshot, field)
    assert _DB_NAMESPACE_ATTRIBUTE not in _attributes(point)


def test_resident_bytes_gauge_reports_the_manager_wide_used_bytes(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(_make_cache_snapshot(used_bytes=4_096), {})

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    (point,) = _number_data_points(
        _collect_metrics(reader)["client_query_cache.cache.resident_bytes"]
    )
    assert point.value == 4_096


def test_resident_bytes_gauge_is_not_duplicated_per_database(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {
            "db_one": _make_stream_snapshot("db_one"),
            "db_two": _make_stream_snapshot("db_two"),
        },
    )

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    points = _number_data_points(
        _collect_metrics(reader)["client_query_cache.cache.resident_bytes"]
    )
    assert len(points) == 1


@pytest.mark.parametrize(
    ("metric_name", "field", "unit"),
    [
        ("client_query_cache.stream.polls", "stream_polls", "1"),
        ("client_query_cache.stream.invalidations", "invalidations", "1"),
        (
            "client_query_cache.stream.logical_event_bytes",
            "logical_event_bytes",
            "By",
        ),
    ],
)
def test_per_database_stream_counters_carry_the_db_namespace_attribute(
    meter: Meter,
    reader: InMemoryMetricReader,
    metric_name: str,
    field: str,
    unit: str,
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {
            "db_one": _make_stream_snapshot("db_one"),
            "db_two": _make_stream_snapshot("db_two"),
        },
    )

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]
    metric = _collect_metrics(reader)[metric_name]

    assert metric.unit == unit
    observed_by_database = {
        _attributes(point)[_DB_NAMESPACE_ATTRIBUTE]: point.value
        for point in _number_data_points(metric)
    }
    assert observed_by_database == {
        "db_one": getattr(_make_stream_snapshot("db_one"), field),
        "db_two": getattr(_make_stream_snapshot("db_two"), field),
    }


def test_per_database_stream_counters_emit_nothing_when_no_database_is_active(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(_make_cache_snapshot(), {})

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    try:
        metric = _collect_metrics(reader)["client_query_cache.stream.polls"]
    except KeyError:
        metric = None
    assert metric is None or metric.data.data_points == ()


@pytest.mark.parametrize(
    ("lag_windows", "percentile", "expected"),
    [
        pytest.param(((1.0, 2.0, 3.0, 4.0, 5.0),), 0.5, 3.0, id="median_of_five"),
        pytest.param(((1.0, 2.0, 3.0, 4.0, 5.0),), 1.0, 5.0, id="max_percentile"),
        pytest.param(((1.0, 2.0, 3.0, 4.0, 5.0),), 0.0, 1.0, id="min_percentile"),
        pytest.param(
            ((42.0,),), 1.0, 42.0, id="single_sample_max_percentile_does_not_raise"
        ),
        pytest.param(((42.0,),), 0.5, 42.0, id="single_sample_median_does_not_raise"),
    ],
)
def test_invalidation_lag_gauge_computes_the_nearest_rank_percentile(
    meter: Meter,
    reader: InMemoryMetricReader,
    lag_windows: tuple[tuple[float, ...], ...],
    percentile: float,
    expected: float,
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {"db": _make_stream_snapshot("db", lag_windows=lag_windows)},
    )

    register_cache_metrics(
        meter,
        cache_core,  # type: ignore[arg-type]
        lag_percentiles=(percentile,),
    )

    (point,) = _number_data_points(
        _collect_metrics(reader)["client_query_cache.stream.invalidation_lag"]
    )
    assert point.value == expected
    attributes = _attributes(point)
    assert attributes[_DB_NAMESPACE_ATTRIBUTE] == "db"
    assert attributes["percentile"] == percentile


@pytest.mark.parametrize(
    "invalid_percentile",
    [
        pytest.param(-0.1, id="below_zero"),
        pytest.param(1.1, id="above_one"),
        pytest.param(float("nan"), id="not_a_number"),
        pytest.param(float("inf"), id="positive_infinity"),
    ],
)
def test_register_cache_metrics_rejects_an_invalid_lag_percentile(
    meter: Meter, invalid_percentile: float
) -> None:
    cache_core = _FakeCacheCore(_make_cache_snapshot(), {})

    with pytest.raises(CacheConfigurationError):
        register_cache_metrics(
            meter,
            cache_core,  # type: ignore[arg-type]
            lag_percentiles=(invalid_percentile,),
        )


def test_invalidation_lag_gauge_omits_a_database_with_no_retained_samples(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {"db": _make_stream_snapshot("db", lag_windows=())},
    )

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    try:
        metric = _collect_metrics(reader)["client_query_cache.stream.invalidation_lag"]
    except KeyError:
        metric = None
    assert metric is None or metric.data.data_points == ()


def test_invalidation_lag_gauge_description_carries_the_clock_skew_limitation(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {"db": _make_stream_snapshot("db", lag_windows=((1.0,),))},
    )

    register_cache_metrics(meter, cache_core)  # type: ignore[arg-type]

    description = _collect_metrics(reader)[
        "client_query_cache.stream.invalidation_lag"
    ].description
    assert description is not None
    assert INVALIDATION_LAG_CLOCK_SKEW_LIMITATION in description


def test_collecting_metrics_does_not_mutate_manager_state() -> None:
    core = CacheCore()
    core.record_bypass()
    core.record_stream_poll("db")
    core.record_logical_event_bytes("db", 256)
    core.record_invalidation_applied("db", 0.5, 100.0, 50.0)

    before_cache = core.snapshot()
    before_stream = core.stream_cost_snapshot("db")

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    register_cache_metrics(meter, core)
    for _ in range(3):
        _collect_metrics(reader)

    assert core.snapshot() == before_cache
    assert core.stream_cost_snapshot("db") == before_stream

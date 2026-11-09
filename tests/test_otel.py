from __future__ import annotations

import dataclasses
import importlib
import sys
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from pymongo import AsyncMongoClient, MongoClient

from client_query_cache import BypassReason, CacheCoreConfig, CacheManager
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.manager import CacheCore
from client_query_cache._core.snapshots import CacheSnapshot
from client_query_cache._core.stream_cost import (
    INVALIDATION_LAG_CLOCK_SKEW_LIMITATION,
    RESIDENT_BYTES_SCOPE,
    StreamCostSnapshot,
)
from client_query_cache._shared.adapters import (
    AsyncSharedCacheManager,
    SharedCacheManager,
)
from client_query_cache._shared.attachment import (
    AsyncEndpoint,
    AttachmentConfig,
    SyncEndpoint,
)
from client_query_cache._shared.diagnostics import SharedBypassReason
from client_query_cache._shared_index import LocalCacheCore, SharedOwnerCore
from client_query_cache._types import BsonDict, Probability
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.otel import register_cache_metrics

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from faker import Faker
    from opentelemetry.sdk.metrics.export import Metric

    from client_query_cache._core.snapshots import StatisticsSource

pytestmark = pytest.mark.unit

_DB_NAMESPACE_ATTRIBUTE = "db.namespace"


def _make_cache_snapshot(**overrides: object) -> CacheSnapshot:
    defaults: dict[str, object] = {
        "lifecycle": "active",
        "used_bytes": 1_024,
        "budget_bytes": 1_048_576,
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
    enable_telemetry: bool = True

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

    register_cache_metrics(meter, cache_core)

    (point,) = _number_data_points(_collect_metrics(reader)[metric_name])
    assert point.value == getattr(snapshot, field)
    assert _DB_NAMESPACE_ATTRIBUTE not in _attributes(point)


def test_resident_bytes_gauge_reports_the_manager_wide_used_bytes(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(_make_cache_snapshot(used_bytes=4_096), {})

    register_cache_metrics(meter, cache_core)

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

    register_cache_metrics(meter, cache_core)

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

    register_cache_metrics(meter, cache_core)
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

    register_cache_metrics(meter, cache_core)

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
    percentile: Probability,
    expected: float,
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {"db": _make_stream_snapshot("db", lag_windows=lag_windows)},
    )

    register_cache_metrics(
        meter,
        cache_core,
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
            cache_core,
            lag_percentiles=(invalid_percentile,),
        )


def test_invalidation_lag_gauge_omits_a_database_with_no_retained_samples(
    meter: Meter, reader: InMemoryMetricReader
) -> None:
    cache_core = _FakeCacheCore(
        _make_cache_snapshot(),
        {"db": _make_stream_snapshot("db", lag_windows=())},
    )

    register_cache_metrics(meter, cache_core)

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

    register_cache_metrics(meter, cache_core)

    description = _collect_metrics(reader)[
        "client_query_cache.stream.invalidation_lag"
    ].description
    assert description is not None
    assert INVALIDATION_LAG_CLOCK_SKEW_LIMITATION in description


def test_collecting_metrics_does_not_mutate_manager_state() -> None:
    core = CacheCore(CacheCoreConfig(enable_telemetry=True))
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


@pytest.mark.parametrize("keyword", [False, True], ids=["positional", "keyword"])
def test_bypass_reason_metric_has_only_the_fixed_reason_dimension(
    meter: Meter, reader: InMemoryMetricReader, keyword: bool
) -> None:
    core = CacheCore(CacheCoreConfig(enable_telemetry=True))
    for reason in BypassReason:
        core.record_bypass(reason)
    core.record_bypass(BypassReason.MISSING_COLLECTION)
    before = core.snapshot()
    if keyword:
        register_cache_metrics(meter, cache_core=core)
    else:
        register_cache_metrics(meter, core)
    points = _number_data_points(
        _collect_metrics(reader)["client_query_cache.cache.bypasses.by_reason"]
    )
    assert len(points) == len(BypassReason)
    assert {tuple(_attributes(point)) for point in points} == {("cache.bypass.reason",)}
    assert {
        _attributes(point)["cache.bypass.reason"]: point.value for point in points
    } == {record.reason.value: record.count for record in before.bypass_reasons}
    assert sum(point.value for point in points) == before.bypasses
    assert core.snapshot() == before


@pytest.fixture
def retention_core() -> Iterator[CacheCore]:
    core = CacheCore(
        CacheCoreConfig(max_entries=1, max_key_bytes=1024, enable_telemetry=True)
    )
    yield core
    core.close()


def test_retention_declines_do_not_increment_bypass_instruments(
    meter: Meter, reader: InMemoryMetricReader, retention_core: CacheCore
) -> None:
    namespace = NamespaceId("telemetry", "retention")
    capture = retention_core.begin_identity_admission(namespace, "document")
    assert (
        retention_core.admit_identity(
            capture, "full", 1, alias=canonical_alias_key("email", "x" * 4096, None)
        )
        is AdmissionOutcome.ADMITTED
    )
    assert (
        sum(record.count for record in retention_core.snapshot().retention_declines)
        == 1
    )
    register_cache_metrics(meter, retention_core)
    metrics = _collect_metrics(reader)
    for name in (
        "client_query_cache.cache.bypasses",
        "client_query_cache.cache.bypasses.oversized",
    ):
        (point,) = _number_data_points(metrics[name])
        assert point.value == 0
    assert not any("retention" in name for name in metrics)


@pytest.fixture(params=["sync", "async"])
async def shared_manager(
    request: pytest.FixtureRequest, tmp_path: Path, faker: Faker
) -> AsyncIterator[SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]]:
    config = AttachmentConfig(
        enable_telemetry=True,
        socket_path=str(tmp_path / "absent.sock"),
        capability=faker.binary(length=32),
        budget_bytes=1,
        max_entry_bytes=1,
        max_await_time_ms=100,
        rpc_deadline_seconds=0.05,
        frame_limit=65_537,
    )
    if request.param == "sync":
        with MongoClient[BsonDict](connect=False) as client:
            manager = SharedCacheManager(
                client, SyncEndpoint(config, require_owner=False)
            )
            yield manager
            manager.close()
    else:
        async with AsyncMongoClient[BsonDict](connect=False) as async_client:
            async_manager = AsyncSharedCacheManager(
                async_client, await AsyncEndpoint.attach(config, require_owner=False)
            )
            yield async_manager
            await async_manager.close()


def test_shared_managers_export_worker_counters_without_contacting_the_owner(
    meter: Meter,
    reader: InMemoryMetricReader,
    shared_manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
) -> None:
    observation = shared_manager.observation
    observation.hits = 3
    observation.misses = 2
    observation.record_bypass(SharedBypassReason.OWNER_UNAVAILABLE)
    observation.record_bypass(SharedBypassReason.OWNER_UNAVAILABLE)
    observation.record_bypass(SharedBypassReason.SESSION)
    observation.record_oversized_bypass()
    attempts = shared_manager.endpoint.counters.failures
    snapshot = shared_manager.snapshot()

    register_cache_metrics(meter, shared_manager)
    _collect_metrics(reader)
    metrics = _collect_metrics(reader)

    assert set(metrics) == {
        "client_query_cache.cache.hits",
        "client_query_cache.cache.misses",
        "client_query_cache.cache.bypasses",
        "client_query_cache.cache.bypasses.oversized",
        "client_query_cache.cache.bypasses.by_reason",
    }
    for name, expected in [
        ("hits", snapshot.hits),
        ("misses", snapshot.misses),
        ("bypasses", snapshot.bypasses),
        ("bypasses.oversized", snapshot.oversized_bypasses),
    ]:
        (point,) = _number_data_points(metrics[f"client_query_cache.cache.{name}"])
        assert point.value == expected
    points = _number_data_points(metrics["client_query_cache.cache.bypasses.by_reason"])
    assert {
        _attributes(point)["cache.bypass.reason"]: point.value for point in points
    } == {record.reason.value: record.count for record in snapshot.bypass_reasons}
    assert len(points) == len(SharedBypassReason)
    assert shared_manager.endpoint.counters.failures == attempts


type Source = (
    StatisticsSource | SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]
)


@pytest.fixture(
    params=["python", "native", "owner", "sync", "async", "shared-sync", "shared-async"]
)
async def disabled_source(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Source]:
    async with AsyncExitStack() as stack:
        if request.param in {"python", "native", "owner"}:
            if request.param == "python":
                core: CacheCore | LocalCacheCore = CacheCore()
            elif request.param == "native":
                core = LocalCacheCore()
            else:
                core = SharedOwnerCore(CacheCoreConfig(), None, ["db"], 1, 30.0)
            stack.callback(core.close)
            yield core
            return
        if request.param in {"sync", "shared-sync"}:
            client = stack.enter_context(MongoClient[BsonDict](connect=False))
            if request.param == "sync":
                yield stack.enter_context(CacheManager(client))
                return
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[BsonDict](connect=False)
            )
            if request.param == "async":
                yield await stack.enter_async_context(AsyncCacheManager(async_client))
                return
        attachment = AttachmentConfig(
            socket_path=str(tmp_path / "absent.sock"),
            capability=b"test-capability",
            budget_bytes=1024,
            max_entry_bytes=512,
            max_await_time_ms=100,
            rpc_deadline_seconds=0.01,
            frame_limit=65536,
        )
        forbidden_request = Mock(
            side_effect=AssertionError("disabled diagnostics contacted the owner")
        )
        monkeypatch.setattr(SyncEndpoint, "request", forbidden_request)
        monkeypatch.setattr(AsyncEndpoint, "request", forbidden_request)
        if request.param == "shared-sync":
            manager = SharedCacheManager(
                client, SyncEndpoint(attachment, require_owner=False)
            )
            stack.callback(manager.close)
            yield manager
        else:
            async_manager = AsyncSharedCacheManager(
                async_client,
                await AsyncEndpoint.attach(attachment, require_owner=False),
            )
            stack.push_async_callback(async_manager.close)
            yield async_manager


def test_disabled_registration_creates_no_instruments(disabled_source: Source) -> None:
    meter = Mock(spec=Meter)
    with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
        register_cache_metrics(meter, disabled_source)
    assert meter.mock_calls == []


@pytest.mark.parametrize(
    "disabled_source", ["shared-sync", "shared-async"], indirect=True
)
def test_disabled_shared_advanced_recording_preserves_the_core_interface(
    disabled_source: Source,
) -> None:
    assert isinstance(disabled_source, (SharedCacheManager, AsyncSharedCacheManager))
    core = disabled_source.cache_core
    assert core.max_entries is None
    assert core.enable_telemetry is False
    core.record_bypass(SharedBypassReason.SESSION)
    core.record_oversized_bypass()
    assert disabled_source._observation is None
    with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
        core.snapshot()


@pytest.fixture(params=[False, True], ids=["open", "closed"])
async def inspected_shared_source(
    disabled_source: Source, request: pytest.FixtureRequest
) -> SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict]:
    assert isinstance(disabled_source, (SharedCacheManager, AsyncSharedCacheManager))
    if request.param:
        if isinstance(disabled_source, AsyncSharedCacheManager):
            await disabled_source.close()
        else:
            disabled_source.close()
    return disabled_source


@pytest.mark.parametrize(
    "disabled_source", ["shared-sync", "shared-async"], indirect=True
)
async def test_shared_diagnostics_reject_locally(
    inspected_shared_source: SharedCacheManager[BsonDict]
    | AsyncSharedCacheManager[BsonDict],
) -> None:
    with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
        inspected_shared_source.snapshot()
    if isinstance(inspected_shared_source, AsyncSharedCacheManager):
        with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
            await inspected_shared_source.owner_snapshot()
    else:
        with pytest.raises(CacheConfigurationError, match="enable_telemetry=True"):
            inspected_shared_source.owner_snapshot()

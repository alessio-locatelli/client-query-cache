from __future__ import annotations

import math
from typing import TYPE_CHECKING

try:
    from opentelemetry.metrics import Observation
except ImportError as error:
    _message = (
        "OpenTelemetry metrics support requires the 'opentelemetry-api' package; "
        "install it with the 'client-query-cache[otel]' extra"
    )
    raise ImportError(_message) from error

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.stream_cost import (
    INVALIDATION_LAG_CLOCK_SKEW_LIMITATION,
    RESIDENT_BYTES_SCOPE,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from opentelemetry.metrics import CallbackOptions, Meter

    from client_query_cache._core.snapshots import StatisticsSource

__all__ = ["register_cache_metrics"]

_DB_NAMESPACE_ATTRIBUTE = "db.namespace"

_CACHE_COUNTER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("client_query_cache.cache.hits", "hits", "Cumulative cache hits."),
    ("client_query_cache.cache.misses", "misses", "Cumulative cache misses."),
    (
        "client_query_cache.cache.evictions",
        "evictions",
        "Cumulative least-recently-used cache evictions.",
    ),
    (
        "client_query_cache.cache.bypasses",
        "bypasses",
        "Cumulative ordinary cache bypass recording events.",
    ),
    (
        "client_query_cache.cache.bypasses.oversized",
        "oversized_bypasses",
        "Cumulative cache bypasses caused by a result exceeding the max entry size.",
    ),
)

_STREAM_COUNTER_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    (
        "client_query_cache.stream.polls",
        "stream_polls",
        "1",
        "Cumulative manager calls to change-stream iteration, per database.",
    ),
    (
        "client_query_cache.stream.invalidations",
        "invalidations",
        "1",
        "Cumulative invalidations applied, per database.",
    ),
    (
        "client_query_cache.stream.logical_event_bytes",
        "logical_event_bytes",
        "By",
        "Cumulative logical projected-event bytes observed, per database.",
    ),
)

_LAG_GAUGE_DESCRIPTION = (
    "Simple order-statistic quantile, tagged by the 'percentile' attribute, of "
    "currently retained invalidation-delivery-lag samples; not a confidence-interval "
    f"estimate. {INVALIDATION_LAG_CLOCK_SKEW_LIMITATION}"
)


def _percentile(sorted_samples: tuple[float, ...], percentile: float) -> float:
    index = round(percentile * (len(sorted_samples) - 1))
    return sorted_samples[index]


def _make_cache_counter_callback(
    cache_core: StatisticsSource, field: str
) -> Callable[[CallbackOptions], Iterable[Observation]]:
    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(getattr(cache_core.snapshot(), field))

    return callback


def _make_bypass_reason_callback(
    cache_core: StatisticsSource,
) -> Callable[[CallbackOptions], Iterable[Observation]]:
    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        for record in cache_core.snapshot().bypass_reasons:
            yield Observation(
                record.count, {"cache.bypass.reason": record.reason.value}
            )

    return callback


def _register_cache_counters(meter: Meter, cache_core: StatisticsSource) -> None:
    for name, field, description in _CACHE_COUNTER_FIELDS:
        meter.create_observable_counter(
            name,
            callbacks=[_make_cache_counter_callback(cache_core, field)],
            unit="1",
            description=description,
        )


def _register_cache_gauges(meter: Meter, cache_core: StatisticsSource) -> None:
    def entries_callback(_options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(cache_core.snapshot().entry_count)

    def resident_bytes_callback(_options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(cache_core.snapshot().used_bytes)

    meter.create_observable_gauge(
        "client_query_cache.cache.entries",
        callbacks=[entries_callback],
        unit="1",
        description="Current resident cache entry count.",
    )
    meter.create_observable_gauge(
        "client_query_cache.cache.resident_bytes",
        callbacks=[resident_bytes_callback],
        unit="By",
        description=RESIDENT_BYTES_SCOPE,
    )


def _make_stream_counter_callback(
    cache_core: StatisticsSource, field: str
) -> Callable[[CallbackOptions], Iterable[Observation]]:
    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        for database in cache_core.active_stream_cost_databases():
            snapshot = cache_core.stream_cost_snapshot(database)
            yield Observation(
                getattr(snapshot, field), {_DB_NAMESPACE_ATTRIBUTE: database}
            )

    return callback


def _register_stream_counters(meter: Meter, cache_core: StatisticsSource) -> None:
    for name, field, unit, description in _STREAM_COUNTER_FIELDS:
        meter.create_observable_counter(
            name,
            callbacks=[_make_stream_counter_callback(cache_core, field)],
            unit=unit,
            description=description,
        )


def _make_lag_percentile_callback(
    cache_core: StatisticsSource, lag_percentiles: tuple[float, ...]
) -> Callable[[CallbackOptions], Iterable[Observation]]:
    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        for database in cache_core.active_stream_cost_databases():
            snapshot = cache_core.stream_cost_snapshot(database)
            samples = tuple(
                sorted(
                    value
                    for window in snapshot.invalidation_lag_windows
                    for value in window
                )
            )
            if not samples:
                continue
            for percentile in lag_percentiles:
                yield Observation(
                    _percentile(samples, percentile),
                    {
                        _DB_NAMESPACE_ATTRIBUTE: database,
                        "percentile": percentile,
                    },
                )

    return callback


def _register_lag_gauges(
    meter: Meter, cache_core: StatisticsSource, lag_percentiles: tuple[float, ...]
) -> None:
    meter.create_observable_gauge(
        "client_query_cache.stream.invalidation_lag",
        callbacks=[_make_lag_percentile_callback(cache_core, lag_percentiles)],
        unit="s",
        description=_LAG_GAUGE_DESCRIPTION,
    )


def _validate_lag_percentiles(lag_percentiles: tuple[float, ...]) -> None:
    for percentile in lag_percentiles:
        if not math.isfinite(percentile) or not 0.0 <= percentile <= 1.0:
            message = (
                f"lag_percentiles values must be finite numbers in [0.0, 1.0]; "
                f"got {percentile!r}"
            )
            raise CacheConfigurationError(message)


def register_cache_metrics(
    meter: Meter,
    cache_core: StatisticsSource,
    *,
    lag_percentiles: tuple[float, ...] = (0.5, 0.95, 1.0),
) -> None:
    _validate_lag_percentiles(lag_percentiles)
    _register_cache_counters(meter, cache_core)
    meter.create_observable_counter(
        "client_query_cache.cache.bypasses.by_reason",
        callbacks=[_make_bypass_reason_callback(cache_core)],
        unit="1",
        description=(
            "Cumulative ordinary cache bypass recording events by fixed reason."
        ),
    )
    _register_cache_gauges(meter, cache_core)
    _register_stream_counters(meter, cache_core)
    _register_lag_gauges(meter, cache_core, lag_percentiles)

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from annotated_types import Interval

from benchmarks.stream_cost.errors import BenchmarkSetupError
from client_query_cache._types import (
    NonNegativeFloat,
    NonNegativeInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from benchmarks.stream_cost.proxy import DirectPathByteProxy
    from benchmarks.stream_cost.topology import IsolatedReplicaSet
    from client_query_cache.synchronous.manager import CacheManager


@dataclass(frozen=True, slots=True)
class OperationLatency:
    operation: str
    outcome: str
    seconds: NonNegativeFloat


@dataclass(frozen=True, slots=True)
class ControlledMeasurement:
    wall_seconds: NonNegativeFloat
    process_cpu_seconds: NonNegativeFloat
    container_cpu_seconds: NonNegativeFloat
    direct_path_bytes_sent: NonNegativeInt | None
    direct_path_bytes_received: NonNegativeInt | None


@dataclass(frozen=True, slots=True)
class ChangeStreamCostComparison:
    raw: ControlledMeasurement
    cache: ControlledMeasurement


def _percentile(
    sorted_values: Sequence[NonNegativeFloat],
    fraction: Annotated[float, Interval(gt=0, le=1)],
) -> NonNegativeFloat:
    return sorted_values[math.ceil(fraction * len(sorted_values)) - 1]


def _timed[T](
    operation: Callable[[], T],
) -> tuple[T, NonNegativeFloat, NonNegativeFloat]:
    process_cpu_before = time.process_time()
    wall_before = time.monotonic()
    value = operation()  # pytriage: TR5 (keep the operation inside the timed interval)
    wall_seconds = time.monotonic() - wall_before
    process_cpu_seconds = time.process_time() - process_cpu_before
    return value, wall_seconds, process_cpu_seconds


def _require_valid_deltas(*deltas: float) -> None:
    if not all(math.isfinite(number) and number >= 0 for number in deltas):
        raise BenchmarkSetupError(
            "controlled run produced an invalid timing or CPU delta"
        )


def measure_controlled[T](
    operation: Callable[[], T],
    *,
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None = None,
) -> tuple[T, ControlledMeasurement]:
    container_cpu_before = replica_set.container_cpu_usage_seconds()
    proxy_sent_before = proxy.bytes_sent if proxy is not None else None
    proxy_received_before = proxy.bytes_received if proxy is not None else None
    value, wall_seconds, process_cpu_seconds = _timed(operation)
    container_cpu_seconds = (
        replica_set.container_cpu_usage_seconds() - container_cpu_before
    )
    _require_valid_deltas(wall_seconds, process_cpu_seconds, container_cpu_seconds)
    return value, ControlledMeasurement(
        wall_seconds=wall_seconds,
        process_cpu_seconds=process_cpu_seconds,
        container_cpu_seconds=container_cpu_seconds,
        direct_path_bytes_sent=(
            proxy.bytes_sent - proxy_sent_before
            if proxy is not None and proxy_sent_before is not None
            else None
        ),
        direct_path_bytes_received=(
            proxy.bytes_received - proxy_received_before
            if proxy is not None and proxy_received_before is not None
            else None
        ),
    )


def latency_distribution(samples: Sequence[OperationLatency]) -> dict[str, object]:
    if not samples:
        return {"operation_count": 0, "no_latency_samples": True, "by_outcome": []}
    groups: dict[tuple[str, str], list[NonNegativeFloat]] = {}
    for sample in samples:
        groups.setdefault((sample.operation, sample.outcome), []).append(sample.seconds)
    distributions: list[dict[str, object]] = []
    for (operation, outcome), values in sorted(groups.items()):
        values.sort()

        distributions.append(
            {
                "operation": operation,
                "outcome": outcome,
                "sample_count": len(values),
                "p50_seconds": _percentile(values, 0.5),
                "p95_seconds": _percentile(values, 0.95),
                "p99_seconds": _percentile(values, 0.99),
            }
        )
    return {
        "operation_count": len(samples),
        "no_latency_samples": False,
        "by_outcome": distributions,
    }


def scalar_latency_distribution(
    samples: Sequence[NonNegativeFloat],
) -> dict[str, object]:
    if not samples:
        return {"sample_count": 0, "no_latency_samples": True}
    values = sorted(samples)
    return {
        "sample_count": len(values),
        "no_latency_samples": False,
        "p50_seconds": _percentile(values, 0.5),
        "p95_seconds": _percentile(values, 0.95),
        "p99_seconds": _percentile(values, 0.99),
    }


def snapshot_logical_metrics(
    manager: CacheManager[dict[str, object]],
) -> dict[str, object]:
    cache = manager.cache_core.snapshot()
    streams: list[dict[str, object]] = []
    for database in manager.cache_core.active_stream_cost_databases():
        stream = manager.cache_core.stream_cost_snapshot(database)
        lag_limitation = stream.invalidation_lag_clock_skew_limitation
        streams.append(
            {
                "database": stream.database,
                "stream_polls": stream.stream_polls,
                "logical_event_bytes": stream.logical_event_bytes,
                "invalidations": stream.invalidations,
                "invalidation_lag_windows": [
                    list(window) for window in stream.invalidation_lag_windows
                ],
                "invalidation_lag_clock_skew_limitation": lag_limitation,
                "resident_bytes": stream.resident_bytes,
                "resident_bytes_scope": stream.resident_bytes_scope,
            }
        )
    return {
        "cache": {
            "hits": cache.hits,
            "misses": cache.misses,
            "evictions": cache.evictions,
            "bypasses": cache.bypasses,
            "oversized_bypasses": cache.oversized_bypasses,
            "used_bytes": cache.used_bytes,
            "shared_budget_bytes": cache.shared_budget_bytes,
            "entry_count": cache.entry_count,
        },
        "streams": streams,
    }

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import BenchmarkSetupError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from benchmarks.stream_cost.proxy import DirectPathByteProxy
    from benchmarks.stream_cost.topology import IsolatedReplicaSet
    from client_query_cache.synchronous.manager import CacheManager


@dataclass(frozen=True, slots=True)
class OperationLatency:
    operation: str
    outcome: str
    seconds: float


@dataclass(frozen=True, slots=True)
class ControlledMeasurement:
    wall_seconds: float
    process_cpu_seconds: float
    container_cpu_seconds: float
    direct_path_bytes_sent: int | None
    direct_path_bytes_received: int | None


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    return sorted_values[math.ceil(fraction * len(sorted_values)) - 1]


def measure_controlled[T](
    operation: Callable[[], T],
    *,
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None = None,
) -> tuple[T, ControlledMeasurement]:
    container_cpu_before = replica_set.container_cpu_usage_seconds()
    proxy_sent_before = proxy.bytes_sent if proxy is not None else None
    proxy_received_before = proxy.bytes_received if proxy is not None else None
    process_cpu_before = time.process_time()
    wall_before = time.monotonic()
    value = operation()  # pytriage: TR5 (keep the operation inside the timed interval)
    wall_seconds = time.monotonic() - wall_before
    process_cpu_seconds = time.process_time() - process_cpu_before
    container_cpu_seconds = (
        replica_set.container_cpu_usage_seconds() - container_cpu_before
    )
    if not all(
        math.isfinite(number) and number >= 0
        for number in (wall_seconds, process_cpu_seconds, container_cpu_seconds)
    ):
        raise BenchmarkSetupError(
            "controlled run produced an invalid timing or CPU delta"
        )
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
    groups: dict[tuple[str, str], list[float]] = {}
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

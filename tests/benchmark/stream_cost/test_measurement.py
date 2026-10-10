from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.measurement import (
    OperationLatency,
    latency_distribution,
    measure_controlled,
    scalar_latency_distribution,
)
from benchmarks.stream_cost.workload import STANDARD_WORKLOAD_VARIANTS, run_paired_reads
from client_query_cache._types import JsonDict

pytestmark = pytest.mark.unit


def test_controlled_measurement_requires_container_cpu_before_sampling() -> None:
    replica_set = Mock(
        container_cpu_usage_seconds=Mock(
            side_effect=BenchmarkSetupError("container CPU unavailable")
        )
    )
    operation = Mock()

    with pytest.raises(BenchmarkSetupError, match="container CPU unavailable"):
        measure_controlled(operation, replica_set=replica_set)

    operation.assert_not_called()


def test_controlled_measurement_requires_container_cpu_after_sampling() -> None:
    replica_set = Mock(
        container_cpu_usage_seconds=Mock(
            side_effect=[0.0, BenchmarkSetupError("container CPU unavailable")]
        )
    )

    with pytest.raises(BenchmarkSetupError, match="container CPU unavailable"):
        measure_controlled(lambda: None, replica_set=replica_set)


def test_controlled_measurement_rejects_invalid_cpu_delta() -> None:
    replica_set = Mock(container_cpu_usage_seconds=Mock(side_effect=[2.0, 1.0]))

    with pytest.raises(BenchmarkSetupError, match="invalid timing or CPU delta"):
        measure_controlled(lambda: None, replica_set=replica_set)


def test_latency_distribution_preserves_outcome_groups() -> None:
    distribution = latency_distribution(
        (
            OperationLatency("read", "hit", 0.1),
            OperationLatency("read", "hit", 0.2),
            OperationLatency("read", "miss", 0.5),
        )
    )

    assert distribution["operation_count"] == 3
    assert cast("list[JsonDict]", distribution["by_outcome"])[0] == {
        "operation": "read",
        "outcome": "hit",
        "sample_count": 2,
        "p50_seconds": 0.1,
        "p95_seconds": 0.2,
        "p99_seconds": 0.2,
    }


def test_scalar_latency_distribution_marks_an_idle_window_with_no_samples() -> None:
    distribution = scalar_latency_distribution(())
    assert distribution == {"sample_count": 0, "no_latency_samples": True}


def test_scalar_latency_distribution_computes_percentiles() -> None:
    distribution = scalar_latency_distribution((0.1, 0.2, 0.5))
    assert distribution == {
        "sample_count": 3,
        "no_latency_samples": False,
        "p50_seconds": 0.2,
        "p95_seconds": 0.5,
        "p99_seconds": 0.5,
    }


def test_read_latency_labels_an_uncached_bypass() -> None:
    snapshot = SimpleNamespace(hits=0, misses=0)
    cache_core = Mock(snapshot=Mock(side_effect=[snapshot, snapshot]))
    cache_collection = Mock(
        database=Mock(manager=Mock(cache_core=cache_core)),
        find_one=Mock(return_value={"_id": 1}),
    )
    raw_collection = Mock(find_one=Mock(return_value={"_id": 1}))

    outcome = run_paired_reads(
        raw_collection, cache_collection, STANDARD_WORKLOAD_VARIANTS[0], (1,)
    )

    assert outcome.cache_latencies[0].outcome == "bypass"

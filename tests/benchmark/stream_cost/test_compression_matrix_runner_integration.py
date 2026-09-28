from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

from benchmarks.stream_cost import compression_matrix_runner as runner_module
from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec, WirePath
from benchmarks.stream_cost.compression_matrix_runner import (
    run_compression_mode_block,
    run_compression_window,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.generators import SMALL_DOCUMENT_PROFILE
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo import MongoClient

pytestmark = pytest.mark.integration

_IDLE_WINDOW = CompressionWindowSpec(
    kind=WorkloadKind.IDLE,
    data_size=SMALL_DOCUMENT_PROFILE,
    document_count=5,
    duration_seconds=0.5,
    warmup=OperationCounts(reads=2, writes=0),
    sampling=OperationCounts(reads=0, writes=0),
    seed=0,
)
_ACTIVE_WINDOW = CompressionWindowSpec(
    kind=WorkloadKind.BALANCED,
    data_size=SMALL_DOCUMENT_PROFILE,
    document_count=10,
    duration_seconds=2.0,
    warmup=OperationCounts(reads=2, writes=0),
    sampling=OperationCounts(reads=3, writes=3),
    seed=1,
)
_TEST_WINDOWS = (_IDLE_WINDOW, _ACTIVE_WINDOW)


@pytest.fixture(scope="module")
def compression_replica_set() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")) as replica_set:
        yield replica_set


@pytest.fixture(scope="module")
def compression_proxy(
    compression_replica_set: IsolatedReplicaSet,
) -> Iterator[DirectPathByteProxy]:
    parsed = urlparse(compression_replica_set.uri)
    config = DirectPathProxyConfig(
        client_topology=BenchmarkClientTopologyConfig(
            tls_enabled=False,
            compressor=WireCompressor.NONE,
            discovery_enabled=False,
            shared_connections=False,
        ),
        upstream_host=parsed.hostname or "127.0.0.1",
        upstream_port=parsed.port or 27017,
    )
    with DirectPathByteProxy(config) as proxy:
        yield proxy


@pytest.fixture
def admin_client(
    compression_replica_set: IsolatedReplicaSet,
) -> Iterator[MongoClient[dict[str, Any]]]:
    topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=WireCompressor.NONE,
        discovery_enabled=False,
        shared_connections=False,
    )
    with build_dedicated_client(compression_replica_set.uri, topology) as client:
        yield client


def _client_for_mode(
    proxy: DirectPathByteProxy, mode: WireCompressor
) -> MongoClient[dict[str, Any]]:
    uri = f"mongodb://127.0.0.1:{proxy.local_port}/?directConnection=true"
    topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=mode,
        discovery_enabled=False,
        shared_connections=False,
    )
    return build_dedicated_client(uri, topology)


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    "mode",
    [
        WireCompressor.NONE,
        WireCompressor.SNAPPY,
        WireCompressor.ZLIB,
        WireCompressor.ZSTD,
    ],
)
def test_run_compression_mode_block_produces_finite_values(
    compression_replica_set: IsolatedReplicaSet,
    compression_proxy: DirectPathByteProxy,
    admin_client: MongoClient[dict[str, Any]],
    mode: WireCompressor,
) -> None:
    with _client_for_mode(compression_proxy, mode) as client:
        negotiation, block_results = run_compression_mode_block(
            _TEST_WINDOWS,
            mode=mode,
            path_order=(WirePath.NO_STREAM, WirePath.STREAM_WATCHING),
            block_index=0,
            client=client,
            admin_client=admin_client,
            replica_set=compression_replica_set,
            proxy=compression_proxy,
            database_prefix=f"compression_block_{mode.value}",
        )

    assert negotiation.compressor is mode
    assert len(block_results) == len(_TEST_WINDOWS) * 2
    for result in block_results:
        measurement = result.measurement
        assert math.isfinite(measurement.wall_seconds)
        assert math.isfinite(measurement.process_cpu_seconds)
        assert math.isfinite(measurement.container_cpu_seconds)
        assert measurement.direct_path_bytes_sent is not None
        assert measurement.direct_path_bytes_received is not None
        assert measurement.direct_path_bytes_sent >= 0
        assert measurement.direct_path_bytes_received >= 0
        for latency in (*result.read_latencies, *result.write_latencies):
            assert math.isfinite(latency.seconds)
            assert latency.seconds >= 0
        for latency_seconds in result.invalidation_latencies_seconds:
            assert math.isfinite(latency_seconds)

        if result.window.kind is WorkloadKind.IDLE:
            assert result.reads_issued == 0
            assert result.writes_issued == 0
            assert result.invalidation_latencies_seconds == ()
        else:
            assert result.reads_issued == result.window.sampling.reads
            assert result.writes_issued == result.window.sampling.writes
            if result.path is WirePath.STREAM_WATCHING:
                assert len(result.invalidation_latencies_seconds) == (
                    result.window.sampling.writes
                )
            else:
                assert result.invalidation_latencies_seconds == ()


def test_run_compression_window_rejects_missed_write_schedule_tolerance(
    compression_replica_set: IsolatedReplicaSet,
    compression_proxy: DirectPathByteProxy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module, "_SCHEDULE_TOLERANCE_SECONDS", 1e-9)
    with (
        _client_for_mode(compression_proxy, WireCompressor.NONE) as client,
        pytest.raises(BenchmarkSetupError, match="deviates from its scheduled"),
    ):
        run_compression_window(
            _ACTIVE_WINDOW,
            mode=WireCompressor.NONE,
            path=WirePath.NO_STREAM,
            block_index=0,
            client=client,
            replica_set=compression_replica_set,
            proxy=compression_proxy,
            database_name="compression_missed_tolerance",
        )


def test_run_compression_window_rejects_missing_invalidation_events(
    compression_replica_set: IsolatedReplicaSet,
    compression_proxy: DirectPathByteProxy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.workload._STREAM_SETTLE_TIMEOUT_SECONDS", 1e-9
    )
    with (
        _client_for_mode(compression_proxy, WireCompressor.NONE) as client,
        pytest.raises(BenchmarkSetupError, match="did not settle"),
    ):
        run_compression_window(
            _ACTIVE_WINDOW,
            mode=WireCompressor.NONE,
            path=WirePath.STREAM_WATCHING,
            block_index=0,
            client=client,
            replica_set=compression_replica_set,
            proxy=compression_proxy,
            database_name="compression_missing_events",
        )

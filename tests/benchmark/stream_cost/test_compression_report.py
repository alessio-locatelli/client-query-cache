from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.compression_matrix import (
    CompressionWindowSpec,
    WirePath,
    counterbalanced_mode_order,
    counterbalanced_path_order,
)
from benchmarks.stream_cost.compression_matrix_runner import CompressionWindowResult
from benchmarks.stream_cost.compression_report import (
    CompressionBlockPlan,
    build_compression_report,
    validate_compression_report,
)
from benchmarks.stream_cost.compressor_preflight import CompressorPreflightResult
from benchmarks.stream_cost.config import (
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
)
from benchmarks.stream_cost.errors import ReportValidationError
from benchmarks.stream_cost.generators import SMALL_DOCUMENT_PROFILE
from benchmarks.stream_cost.measurement import ControlledMeasurement, OperationLatency
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind
from client_query_cache._types import JsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

_IDLE_WINDOW = CompressionWindowSpec(
    kind=WorkloadKind.IDLE,
    data_size=SMALL_DOCUMENT_PROFILE,
    document_count=5,
    duration_seconds=1.0,
    warmup=OperationCounts(reads=2, writes=0),
    sampling=OperationCounts(reads=0, writes=0),
    seed=0,
)
_ACTIVE_WINDOW = CompressionWindowSpec(
    kind=WorkloadKind.BALANCED,
    data_size=SMALL_DOCUMENT_PROFILE,
    document_count=5,
    duration_seconds=1.0,
    warmup=OperationCounts(reads=2, writes=0),
    sampling=OperationCounts(reads=2, writes=2),
    seed=1,
)
_WINDOWS = (_IDLE_WINDOW, _ACTIVE_WINDOW)


def _measurement() -> ControlledMeasurement:
    return ControlledMeasurement(
        wall_seconds=1.0,
        process_cpu_seconds=0.5,
        container_cpu_seconds=0.25,
        direct_path_bytes_sent=1_000,
        direct_path_bytes_received=2_000,
    )


def _result(
    *,
    block_index: NonNegativeInt,
    mode: WireCompressor,
    path: WirePath,
    window: CompressionWindowSpec,
    reads: NonNegativeInt,
    writes: NonNegativeInt,
    invalidations: tuple[NonNegativeFloat, ...] = (),
) -> CompressionWindowResult:
    outcome = "raw" if path is WirePath.NO_STREAM else "hit"
    return CompressionWindowResult(
        window=window,
        mode=mode,
        path=path,
        block_index=block_index,
        measurement=_measurement(),
        read_latencies=tuple(
            OperationLatency("read", outcome, 0.01) for _ in range(reads)
        ),
        write_latencies=tuple(
            OperationLatency("write", "shared_write", 0.02) for _ in range(writes)
        ),
        invalidation_latencies_seconds=invalidations,
        reads_issued=reads,
        writes_issued=writes,
    )


def _full_report() -> JsonDict:
    blocks = [
        CompressionBlockPlan(
            block_index=index,
            mode_order=counterbalanced_mode_order(index),
            path_order=counterbalanced_path_order(index),
        )
        for index in range(4)
    ]
    negotiations: dict[
        tuple[NonNegativeInt, WireCompressor], CompressorPreflightResult
    ] = {}
    window_results: list[CompressionWindowResult] = []
    for block in blocks:
        for mode in block.mode_order:
            counter_deltas = (
                {mode.value: 500} if mode is not WireCompressor.NONE else {}
            )
            negotiations[block.block_index, mode] = CompressorPreflightResult(
                compressor=mode, counter_deltas=counter_deltas
            )
            for window in _WINDOWS:
                for path in block.path_order:
                    if window.kind is WorkloadKind.IDLE:
                        window_result = _result(
                            block_index=block.block_index,
                            mode=mode,
                            path=path,
                            window=window,
                            reads=0,
                            writes=0,
                        )
                    else:
                        invalidations = (
                            (0.01, 0.02) if path is WirePath.STREAM_WATCHING else ()
                        )
                        window_result = _result(
                            block_index=block.block_index,
                            mode=mode,
                            path=path,
                            window=window,
                            reads=2,
                            writes=2,
                            invalidations=invalidations,
                        )
                    window_results.append(window_result)

    identity = BenchmarkIdentity(
        revision="abc1234",
        library_version="0.1.0",
        python_version="3.14.6",
        pymongo_version="4.18.1",
    )
    environment = BenchmarkEnvironment(
        mongodb_version="8.0.4",
        topology="isolated single-member replica set",
        member_count=1,
        resource_limits={"cpus": "1", "memory": "1g"},
    )
    limitations = (
        Limitation("container-cpu", "CPU is measured for the isolated container."),
    )
    return build_compression_report(
        identity=identity,
        environment=environment,
        windows=_WINDOWS,
        blocks=blocks,
        negotiations=negotiations,
        window_results=window_results,
        limitations=limitations,
    )


def _first_sample(
    samples: list[object], predicate: Callable[[JsonDict], bool]
) -> JsonDict:
    for sample in samples:
        assert isinstance(sample, dict)
        if predicate(sample):
            return sample
    pytest.fail("no matching sample")  # pragma: no cover - always matches


def test_a_complete_four_mode_matrix_report_is_accepted() -> None:
    validate_compression_report(_full_report())


def test_report_rejects_a_missing_sample() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    samples.pop()
    with pytest.raises(ReportValidationError, match="missing sample"):
        validate_compression_report(report)


def test_report_rejects_fewer_writes_than_scheduled() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    sample = _first_sample(samples, lambda item: item["writes_issued"] == 2)
    sample["writes_issued"] = 1
    with pytest.raises(ReportValidationError, match="expected"):
        validate_compression_report(report)


def test_report_rejects_idle_samples_with_latency_data() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    idle_sample = _first_sample(samples, lambda item: item["window_kind"] == "idle")
    idle_sample["read_latency"] = {
        "operation_count": 1,
        "no_latency_samples": False,
        "by_outcome": [
            {
                "operation": "read",
                "outcome": "raw",
                "sample_count": 1,
                "p50_seconds": 0.01,
                "p95_seconds": 0.01,
                "p99_seconds": 0.01,
            }
        ],
    }
    with pytest.raises(ReportValidationError, match="idle"):
        validate_compression_report(report)


def test_report_rejects_a_missing_negotiation() -> None:
    report = copy.deepcopy(_full_report())
    negotiations = report["negotiations"]
    assert isinstance(negotiations, list)
    assert negotiations
    negotiations.pop()
    with pytest.raises(ReportValidationError, match="negotiation"):
        validate_compression_report(report)


def test_report_rejects_a_duplicate_sample() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    samples.append(copy.deepcopy(samples[0]))
    with pytest.raises(ReportValidationError, match="duplicate sample"):
        validate_compression_report(report)


def test_report_rejects_fewer_reads_than_scheduled() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    sample = _first_sample(samples, lambda item: item["reads_issued"] == 2)
    sample["reads_issued"] = 1
    with pytest.raises(ReportValidationError, match="expected"):
        validate_compression_report(report)


def test_report_rejects_a_sample_referencing_an_undeclared_window() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    first_sample = samples[0]
    assert isinstance(first_sample, dict)
    first_sample["window"] = "unknown_window"
    with pytest.raises(ReportValidationError, match="undeclared window"):
        validate_compression_report(report)


def test_report_rejects_a_no_stream_sample_with_invalidation_latency_data() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    sample = _first_sample(
        samples,
        lambda item: item["path"] == "no_stream" and item["window_kind"] != "idle",
    )
    sample["invalidation_latency"] = {
        "sample_count": 1,
        "no_latency_samples": False,
        "p50_seconds": 0.01,
        "p95_seconds": 0.01,
        "p99_seconds": 0.01,
    }
    with pytest.raises(ReportValidationError, match="invalidation_latency"):
        validate_compression_report(report)


def test_report_rejects_a_duplicate_stream_minus_control_entry() -> None:
    report = copy.deepcopy(_full_report())
    stream_minus_control = report["stream_minus_control"]
    assert isinstance(stream_minus_control, list)
    assert stream_minus_control
    stream_minus_control.append(copy.deepcopy(stream_minus_control[0]))
    with pytest.raises(ReportValidationError, match="duplicate stream-minus-control"):
        validate_compression_report(report)


def test_report_rejects_a_missing_stream_minus_control_entry() -> None:
    report = copy.deepcopy(_full_report())
    stream_minus_control = report["stream_minus_control"]
    assert isinstance(stream_minus_control, list)
    assert stream_minus_control
    stream_minus_control.pop()
    with pytest.raises(ReportValidationError, match="missing stream-minus-control"):
        validate_compression_report(report)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="non_finite_number"),
        pytest.param({1}, id="non_serializable_type"),
    ],
)
def test_report_rejects_a_report_containing_a_non_json_serializable_value(
    value: object,
) -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    first_sample = samples[0]
    assert isinstance(first_sample, dict)
    first_sample["wall_seconds"] = value
    with pytest.raises(ReportValidationError, match="not JSON-serializable"):
        validate_compression_report(report)


def test_report_rejects_a_stream_watching_sample_missing_invalidation_latency() -> None:
    report = copy.deepcopy(_full_report())
    samples = report["samples"]
    assert isinstance(samples, list)
    assert samples
    sample = _first_sample(
        samples,
        lambda item: (
            item["path"] == "stream_watching" and item["window_kind"] != "idle"
        ),
    )
    sample["invalidation_latency"] = {
        "sample_count": 0,
        "no_latency_samples": True,
    }
    with pytest.raises(ReportValidationError, match="invalidation_latency"):
        validate_compression_report(report)

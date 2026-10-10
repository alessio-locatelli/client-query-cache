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


@pytest.fixture
def report() -> JsonDict:
    return _full_report()


def _entries(report: JsonDict, section: str) -> list[object]:
    entries = report[section]
    assert isinstance(entries, list)
    return entries


def _first_sample(report: JsonDict, predicate: Callable[[JsonDict], bool]) -> JsonDict:
    for sample in _entries(report, "samples"):
        assert isinstance(sample, dict)
        if predicate(sample):
            return sample
    pytest.fail("no matching sample")  # pragma: no cover - always matches


def test_a_complete_four_mode_matrix_report_is_accepted(report: JsonDict) -> None:
    validate_compression_report(report)


@pytest.mark.parametrize(
    ("section", "match"),
    [
        pytest.param("samples", "missing sample", id="sample"),
        pytest.param("negotiations", "negotiation", id="negotiation"),
        pytest.param(
            "stream_minus_control",
            "missing stream-minus-control",
            id="stream_minus_control",
        ),
    ],
)
def test_report_rejects_a_missing_entry(
    report: JsonDict, section: str, match: str
) -> None:
    _entries(report, section).pop()
    with pytest.raises(ReportValidationError, match=match):
        validate_compression_report(report)


@pytest.mark.parametrize(
    ("section", "match"),
    [
        pytest.param("samples", "duplicate sample", id="sample"),
        pytest.param(
            "stream_minus_control",
            "duplicate stream-minus-control",
            id="stream_minus_control",
        ),
    ],
)
def test_report_rejects_a_duplicate_entry(
    report: JsonDict, section: str, match: str
) -> None:
    entries = _entries(report, section)
    entries.append(copy.deepcopy(entries[0]))
    with pytest.raises(ReportValidationError, match=match):
        validate_compression_report(report)


@pytest.mark.parametrize("field", ["writes_issued", "reads_issued"])
def test_report_rejects_fewer_operations_than_scheduled(
    report: JsonDict, field: str
) -> None:
    sample = _first_sample(report, lambda item: item[field] == 2)
    sample[field] = 1
    with pytest.raises(ReportValidationError, match="expected"):
        validate_compression_report(report)


def test_report_rejects_idle_samples_with_latency_data(report: JsonDict) -> None:
    idle_sample = _first_sample(report, lambda item: item["window_kind"] == "idle")
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


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        pytest.param(
            "window", "unknown_window", "undeclared window", id="undeclared_window"
        ),
        pytest.param(
            "wall_seconds",
            float("nan"),
            "not JSON-serializable",
            id="non_finite_number",
        ),
        pytest.param(
            "wall_seconds", {1}, "not JSON-serializable", id="non_serializable_type"
        ),
    ],
)
def test_report_rejects_an_invalid_first_sample_value(
    report: JsonDict, field: str, value: object, match: str
) -> None:
    first_sample = _entries(report, "samples")[0]
    assert isinstance(first_sample, dict)
    first_sample[field] = value
    with pytest.raises(ReportValidationError, match=match):
        validate_compression_report(report)


@pytest.mark.parametrize(
    ("path", "invalidation_latency"),
    [
        pytest.param(
            "no_stream",
            {
                "sample_count": 1,
                "no_latency_samples": False,
                "p50_seconds": 0.01,
                "p95_seconds": 0.01,
                "p99_seconds": 0.01,
            },
            id="no_stream_with_data",
        ),
        pytest.param(
            "stream_watching",
            {"sample_count": 0, "no_latency_samples": True},
            id="stream_watching_without_data",
        ),
    ],
)
def test_report_rejects_inconsistent_invalidation_latency(
    report: JsonDict, path: str, invalidation_latency: JsonDict
) -> None:
    sample = _first_sample(
        report, lambda item: item["path"] == path and item["window_kind"] != "idle"
    )
    sample["invalidation_latency"] = invalidation_latency
    with pytest.raises(ReportValidationError, match="invalidation_latency"):
        validate_compression_report(report)

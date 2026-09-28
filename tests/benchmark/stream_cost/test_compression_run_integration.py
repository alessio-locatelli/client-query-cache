from __future__ import annotations

import pytest

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.compression_decision import evaluate_compression_decision
from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec
from benchmarks.stream_cost.compression_run import run_compression_matrix
from benchmarks.stream_cost.generators import SMALL_DOCUMENT_PROFILE
from benchmarks.stream_cost.topology import ResourceLimits
from benchmarks.stream_cost.workload import OperationCounts, WorkloadKind

pytestmark = pytest.mark.integration

_FAST_WINDOWS = (
    CompressionWindowSpec(
        kind=WorkloadKind.IDLE,
        data_size=SMALL_DOCUMENT_PROFILE,
        document_count=5,
        duration_seconds=0.5,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=OperationCounts(reads=0, writes=0),
        seed=0,
    ),
    CompressionWindowSpec(
        kind=WorkloadKind.BALANCED,
        data_size=SMALL_DOCUMENT_PROFILE,
        document_count=10,
        duration_seconds=1.0,
        warmup=OperationCounts(reads=2, writes=0),
        sampling=OperationCounts(reads=2, writes=2),
        seed=1,
    ),
)


@pytest.mark.timeout(300)
def test_run_compression_matrix_produces_a_valid_report_and_decision() -> None:
    report = run_compression_matrix(
        windows=_FAST_WINDOWS,
        block_count=4,
        limits=ResourceLimits(cpus=1.0, memory="1g"),
    )

    blocks = report["blocks"]
    samples = report["samples"]
    assert isinstance(blocks, list)
    assert isinstance(samples, list)
    assert report["schema_version"] == "1"
    assert len(blocks) == 4
    assert {sample["mode"] for sample in samples} == {
        mode.value for mode in WireCompressor
    }
    assert len(samples) == 4 * 4 * len(_FAST_WINDOWS) * 2

    decision = evaluate_compression_decision(report)
    assert decision.recommended_mode in WireCompressor
    assert len(decision.evidence) == 3

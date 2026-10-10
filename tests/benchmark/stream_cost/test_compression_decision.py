from __future__ import annotations

import pytest

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.compression_decision import evaluate_compression_decision
from client_query_cache._types import JsonDict, NonNegativeFloat, NonNegativeInt

pytestmark = pytest.mark.unit

_BLOCK_COUNT = 3
_IDLE_NONE_CPU = 0.1
_ACTIVE_NONE_CPU = 1.0
_ACTIVE_NONE_ADDED_CPU = 0.5
_ACTIVE_NONE_P95 = 0.01
_ACTIVE_NONE_SENT = 1_000
_ACTIVE_NONE_RECEIVED = 1_000
_WINDOWS = [
    {"name": "idle", "kind": "idle"},
    {"name": "active", "kind": "balanced"},
]


def _sample(
    *,
    block_index: NonNegativeInt,
    mode: str,
    window: str,
    cpu: NonNegativeFloat,
    p95: NonNegativeFloat | None = None,
    sent: NonNegativeInt | None = None,
    received: NonNegativeInt | None = None,
) -> JsonDict:
    sample: JsonDict = {
        "block_index": block_index,
        "mode": mode,
        "window": window,
        "path": "stream_watching",
        "container_cpu_seconds": cpu,
    }
    if p95 is not None:
        sample["invalidation_latency"] = {"p95_seconds": p95}
    if sent is not None and received is not None:
        sample["direct_path_bytes"] = {"sent": sent, "received": received}
    return sample


def _build_report(
    *,
    cpu_overhead_fraction: float,
    latency_overhead_fraction: float,
    byte_reduction_fraction: float,
    idle_deltas: list[float],
) -> JsonDict:
    samples: list[JsonDict] = []
    stream_minus_control: list[JsonDict] = []
    for block_index in range(_BLOCK_COUNT):
        samples.extend(
            (
                _sample(
                    block_index=block_index,
                    mode="none",
                    window="idle",
                    cpu=_IDLE_NONE_CPU,
                ),
                _sample(
                    block_index=block_index,
                    mode="zstd",
                    window="idle",
                    cpu=_IDLE_NONE_CPU + idle_deltas[block_index],
                ),
                _sample(
                    block_index=block_index,
                    mode="none",
                    window="active",
                    cpu=_ACTIVE_NONE_CPU,
                    p95=_ACTIVE_NONE_P95,
                    sent=_ACTIVE_NONE_SENT,
                    received=_ACTIVE_NONE_RECEIVED,
                ),
                _sample(
                    block_index=block_index,
                    mode="zstd",
                    window="active",
                    cpu=_ACTIVE_NONE_CPU * (1 + cpu_overhead_fraction),
                    p95=_ACTIVE_NONE_P95 * (1 + latency_overhead_fraction),
                    sent=round(_ACTIVE_NONE_SENT * (1 - byte_reduction_fraction)),
                    received=round(
                        _ACTIVE_NONE_RECEIVED * (1 - byte_reduction_fraction)
                    ),
                ),
            )
        )
        stream_minus_control.extend(
            (
                {
                    "block_index": block_index,
                    "mode": "none",
                    "window": "active",
                    "container_cpu_seconds_delta": _ACTIVE_NONE_ADDED_CPU,
                },
                {
                    "block_index": block_index,
                    "mode": "zstd",
                    "window": "active",
                    "container_cpu_seconds_delta": (
                        _ACTIVE_NONE_ADDED_CPU * (1 + cpu_overhead_fraction)
                    ),
                },
            )
        )
    return {
        "windows": _WINDOWS,
        "blocks": [{"block_index": index} for index in range(_BLOCK_COUNT)],
        "samples": samples,
        "stream_minus_control": stream_minus_control,
    }


@pytest.mark.parametrize(
    (
        "cpu_overhead_fraction",
        "latency_overhead_fraction",
        "byte_reduction_fraction",
        "idle_deltas",
        "expect_recommended",
        "expect_inconclusive",
    ),
    [
        pytest.param(
            0.0, 0.0, 0.15, [0.0, 0.0, 0.0], WireCompressor.ZSTD, False, id="qualifying"
        ),
        pytest.param(
            0.20,
            0.0,
            0.15,
            [0.0, 0.0, 0.0],
            WireCompressor.NONE,
            True,
            id="cpu_regression",
        ),
        pytest.param(
            0.0,
            0.20,
            0.15,
            [0.0, 0.0, 0.0],
            WireCompressor.NONE,
            True,
            id="latency_regression",
        ),
        pytest.param(
            0.0,
            0.0,
            0.05,
            [0.0, 0.0, 0.0],
            WireCompressor.NONE,
            True,
            id="insufficient_byte_savings",
        ),
        pytest.param(
            0.0,
            0.0,
            0.15,
            [0.01, -0.01, 0.01],
            WireCompressor.NONE,
            True,
            id="noisy_idle_data",
        ),
    ],
)
def test_evaluate_compression_decision(
    *,
    cpu_overhead_fraction: float,
    latency_overhead_fraction: float,
    byte_reduction_fraction: float,
    idle_deltas: list[float],
    expect_recommended: WireCompressor,
    expect_inconclusive: bool,
) -> None:
    report = _build_report(
        cpu_overhead_fraction=cpu_overhead_fraction,
        latency_overhead_fraction=latency_overhead_fraction,
        byte_reduction_fraction=byte_reduction_fraction,
        idle_deltas=idle_deltas,
    )
    decision = evaluate_compression_decision(report)
    assert decision.recommended_mode is expect_recommended
    assert decision.inconclusive is expect_inconclusive
    (zstd_evidence,) = (
        item for item in decision.evidence if item.mode is WireCompressor.ZSTD
    )
    assert zstd_evidence.qualifies == (not expect_inconclusive)

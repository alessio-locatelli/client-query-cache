from __future__ import annotations

import pytest

from benchmarks.stream_cost.guard_decision import BLOCK_PAIRS, Decision, evaluate_case
from client_query_cache._types import NonNegativeFloat

BASE_BLOCK_SECONDS = 0.025
# Small timing variation stays safely below the material-slowdown boundary.
ORDINARY_NOISE_HEAD_BLOCKS = (
    0.0249,
    0.025,
    0.0251,
    0.025,
    0.0248,
    0.0252,
    0.025,
    0.0249,
    0.0251,
    0.025,
    0.0248,
    0.0252,
    0.025,
    0.0249,
    0.0251,
)
# Ratios span both sides of the 30% boundary; the spread makes this inconclusive.
NOISY_HEAD_BLOCKS = (
    0.021,
    0.022,
    0.023,
    0.03,
    0.035,
    0.04,
    0.045,
    0.021,
    0.022,
    0.023,
    0.03,
    0.035,
    0.04,
    0.045,
    0.03,
)


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        ((0.04,) * BLOCK_PAIRS, Decision.REGRESSION),
        ((0.021,) * BLOCK_PAIRS, Decision.WITHIN_BOUNDARY),
        (ORDINARY_NOISE_HEAD_BLOCKS, Decision.WITHIN_BOUNDARY),
        (NOISY_HEAD_BLOCKS, Decision.INCONCLUSIVE),
    ],
)
def test_paired_decision(
    head: tuple[NonNegativeFloat, ...], expected: Decision
) -> None:
    decision = evaluate_case((BASE_BLOCK_SECONDS,) * BLOCK_PAIRS, head)
    assert decision.decision is expected
    assert decision.base_median_seconds == BASE_BLOCK_SECONDS
    assert decision.head_median_seconds > 0
    assert decision.lower_ratio <= decision.median_ratio <= decision.upper_ratio
    assert decision.reason


@pytest.mark.parametrize(
    "base",
    [(), (0.0,) * BLOCK_PAIRS, (float("nan"),) * BLOCK_PAIRS],
)
def test_invalid_baseline_is_a_measurement_error(base: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match=r"paired blocks|invalid"):
        evaluate_case(base, (0.04,) * BLOCK_PAIRS)

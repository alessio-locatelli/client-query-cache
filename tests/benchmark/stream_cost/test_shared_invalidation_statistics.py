from __future__ import annotations

import math
from collections import Counter
from functools import partial
from itertools import product
from statistics import fmean

import pytest

from benchmarks.stream_cost.await_statistics import (
    exact_basic_bootstrap,
    exact_block_bootstrap,
    exact_block_draws,
)

pytestmark = pytest.mark.unit


def _block_mean(values: tuple[float, ...], indices: tuple[int, ...]) -> float:
    return fmean(values[index] for index in indices)


@pytest.mark.parametrize("blocks", [3, 6], ids=["small", "registered"])
def test_exact_weights_match_ordered_draws(blocks: int) -> None:
    enumerated = tuple(exact_block_draws(blocks))
    reference = Counter(
        tuple(sorted(indices)) for indices in product(range(blocks), repeat=blocks)
    )
    assert dict(enumerated) == reference
    assert sum(weight for _, weight in enumerated) == blocks**blocks
    if blocks == 6:
        assert len(enumerated) == 462


@pytest.mark.parametrize(
    "shift", [-10.0, 0.0, 10.0], ids=["negative", "crosses-zero", "positive"]
)
def test_signed_basic_bounds_use_centered_nearest_rank_draws(shift: float) -> None:
    values = tuple(value + shift for value in (-0.06, -0.03, 0.01, 0.02, 0.04, 0.09))
    statistic = partial(_block_mean, values)
    bootstrap = exact_basic_bootstrap(statistic, block_count=6)
    observed = fmean(values)
    ordered = sorted(
        statistic(indices) - observed for indices in product(range(6), repeat=6)
    )
    alpha = 0.05 / 4
    assert bootstrap.estimate == pytest.approx(observed)
    assert bootstrap.lower_bound(alpha) == pytest.approx(
        observed - ordered[math.ceil((1 - alpha) * len(ordered)) - 1]
    )
    assert bootstrap.upper_bound(alpha) == pytest.approx(
        observed - ordered[math.ceil(alpha * len(ordered)) - 1]
    )


def test_preserves_positive_log_statistic_bound() -> None:
    values = (0.8, 0.85, 0.9, 0.95, 1.0, 1.05)
    statistic = partial(_block_mean, values)
    bootstrap = exact_block_bootstrap(statistic, block_count=6, limit=1.05)
    observed = fmean(values)
    centered = sorted(
        math.log(statistic(indices)) - math.log(observed)
        for indices in product(range(6), repeat=6)
    )
    alpha = 0.05
    quantile = centered[math.ceil(alpha * len(centered)) - 1]
    assert bootstrap.upper_bound(alpha) == pytest.approx(observed * math.exp(-quantile))
    threshold = math.log(observed) - math.log(1.05)
    assert bootstrap.p_value == pytest.approx(
        (1 + sum(value <= threshold for value in centered)) / (1 + 6**6)
    )

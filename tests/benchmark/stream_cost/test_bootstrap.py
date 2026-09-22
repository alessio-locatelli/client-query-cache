from __future__ import annotations

import pytest

from benchmarks.stream_cost.bootstrap import (
    ConfidenceInterval,
    absolute_threshold_decisive,
    block_bootstrap_percentile_ci,
    bonferroni_confidence_level,
    bonferroni_delta_interval,
    delta_threshold_decisive,
    expand_with_uncertainty,
    minimum_sample_count,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("percentile", "expected"),
    [
        (0.5, 2),
        (0.9, 10),
        (0.99, 100),
    ],
)
def test_minimum_sample_count(percentile: float, expected: int) -> None:
    assert minimum_sample_count(percentile) == expected


@pytest.mark.parametrize("percentile", [0.0, 1.0, -0.1, 1.1])
def test_minimum_sample_count_rejects_out_of_range_percentile(
    percentile: float,
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="between 0 and 1"):
        minimum_sample_count(percentile)


def test_confidence_interval_rejects_inverted_bounds() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="lower bound must not exceed"
    ):
        ConfidenceInterval(lower=1.0, upper=0.0, point_estimate=0.5)


def test_block_bootstrap_rejects_empty_windows() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="at least one capture window"
    ):
        block_bootstrap_percentile_ci(
            (), percentile=0.5, confidence_level=0.95, resample_count=10, seed=1
        )


def test_block_bootstrap_rejects_non_positive_resample_count() -> None:
    with pytest.raises(
        BenchmarkConfigurationError, match="resample_count must be positive"
    ):
        block_bootstrap_percentile_ci(
            ((1.0, 2.0),),
            percentile=0.5,
            confidence_level=0.95,
            resample_count=0,
            seed=1,
        )


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.5, 1.5])
def test_block_bootstrap_rejects_out_of_range_confidence(
    confidence_level: float,
) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="confidence_level"):
        block_bootstrap_percentile_ci(
            ((1.0, 2.0),),
            percentile=0.5,
            confidence_level=confidence_level,
            resample_count=10,
            seed=1,
        )


def test_block_bootstrap_rejects_below_sample_count_floor() -> None:
    windows = ((1.0,), (2.0,))
    with pytest.raises(BenchmarkConfigurationError, match="required for"):
        block_bootstrap_percentile_ci(
            windows, percentile=0.99, confidence_level=0.95, resample_count=10, seed=1
        )


def test_block_bootstrap_point_estimate_matches_full_sample_percentile() -> None:
    windows = tuple((float(value),) for value in range(1, 101))
    ci = block_bootstrap_percentile_ci(
        windows, percentile=0.5, confidence_level=0.95, resample_count=200, seed=7
    )
    assert ci.point_estimate == pytest.approx(50.0)
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_block_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    windows = tuple((float(value),) for value in range(1, 101))
    first = block_bootstrap_percentile_ci(
        windows, percentile=0.9, confidence_level=0.95, resample_count=200, seed=42
    )
    second = block_bootstrap_percentile_ci(
        windows, percentile=0.9, confidence_level=0.95, resample_count=200, seed=42
    )
    assert first == second


def test_block_bootstrap_draws_whole_windows_not_individual_values() -> None:
    low_window = (0.0,) * 50
    high_window = (100.0,) * 50
    windows = (low_window, high_window)
    ci = block_bootstrap_percentile_ci(
        windows, percentile=0.5, confidence_level=0.95, resample_count=500, seed=3
    )
    assert ci.lower in {0.0, 100.0}
    assert ci.upper in {0.0, 100.0}


def test_expand_with_uncertainty() -> None:
    interval = ConfidenceInterval(lower=1.0, upper=2.0, point_estimate=1.5)
    expanded = expand_with_uncertainty(interval, 0.5)
    assert expanded.lower == pytest.approx(0.5)
    assert expanded.upper == pytest.approx(2.5)
    assert expanded.point_estimate == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("lower", "upper", "uncertainty", "threshold", "expected"),
    [
        (0.0, 1.0, 0.0, 1.0, True),
        (0.0, 1.0, 0.0, 0.99, False),
        (1.1, 2.0, 0.0, 1.0, False),
        (0.0, 0.9, 0.1, 1.0, True),
        (0.0, 0.95, 0.1, 1.0, False),
    ],
)
def test_absolute_threshold_decisive(
    lower: float, upper: float, uncertainty: float, threshold: float, expected: bool
) -> None:
    interval = ConfidenceInterval(lower=lower, upper=upper, point_estimate=lower)
    assert (
        absolute_threshold_decisive(
            interval, threshold, total_uncertainty_seconds=uncertainty
        )
        is expected
    )


@pytest.mark.parametrize(
    ("lower", "upper", "threshold", "expected"),
    [
        (0.0, 1.0, 1.0, True),
        (0.0, 1.0, 0.99, False),
        (1.1, 2.0, 1.0, False),
    ],
)
def test_delta_threshold_decisive(
    lower: float, upper: float, threshold: float, expected: bool
) -> None:
    interval = ConfidenceInterval(lower=lower, upper=upper, point_estimate=lower)
    assert delta_threshold_decisive(interval, threshold) is expected


@pytest.mark.parametrize(
    ("target_confidence", "expected"),
    [
        (0.95, 0.975),
        (0.90, 0.95),
    ],
)
def test_bonferroni_confidence_level(target_confidence: float, expected: float) -> None:
    assert bonferroni_confidence_level(target_confidence) == pytest.approx(expected)


def test_bonferroni_delta_interval_centers_on_the_supplied_delta() -> None:
    control_windows = tuple((float(value),) for value in range(1, 101))
    loaded_windows = tuple((float(value) + 10,) for value in range(1, 101))
    interval = bonferroni_delta_interval(
        control_windows,
        loaded_windows,
        percentile=0.5,
        confidence_level=0.95,
        resample_count=200,
        seed=11,
        delta_seconds=12.34,
    )
    assert interval.point_estimate == pytest.approx(12.34)
    assert interval.lower <= interval.point_estimate <= interval.upper

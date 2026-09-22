from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import BenchmarkConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence


_FLOATING_POINT_GUARD_DECIMALS = 9


def minimum_sample_count(percentile: float) -> int:
    if not 0 < percentile < 1:
        message = "percentile must be between 0 and 1 exclusive"
        raise BenchmarkConfigurationError(message)
    exact_count = round(1 / (1 - percentile), _FLOATING_POINT_GUARD_DECIMALS)
    return math.ceil(exact_count)


def _percentile_index(count: int, percentile: float) -> int:
    exact_rank = round(percentile * count, _FLOATING_POINT_GUARD_DECIMALS)
    return min(max(math.floor(exact_rank), 0), count - 1)


def _percentile(values: Sequence[float], percentile: float) -> float:
    sorted_values = sorted(values)
    return sorted_values[_percentile_index(len(sorted_values), percentile)]


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float
    point_estimate: float

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            message = "lower bound must not exceed upper bound"
            raise BenchmarkConfigurationError(message)


def block_bootstrap_percentile_ci(
    windows: Sequence[Sequence[float]],
    *,
    percentile: float,
    confidence_level: float,
    resample_count: int,
    seed: int,
) -> ConfidenceInterval:
    if len(windows) < 2:
        message = (
            "at least two capture windows are required for a valid block bootstrap"
        )
        raise BenchmarkConfigurationError(message)
    window_sizes = {len(window) for window in windows}
    if window_sizes == {0}:
        message = "capture windows must not be empty"
        raise BenchmarkConfigurationError(message)
    if len(window_sizes) > 1:
        message = f"capture windows must all be the same size, got sizes {window_sizes}"
        raise BenchmarkConfigurationError(message)
    if resample_count < 2:
        message = "resample_count must be at least 2 for a meaningful bootstrap"
        raise BenchmarkConfigurationError(message)
    if not 0 < confidence_level < 1:
        message = "confidence_level must be between 0 and 1 exclusive"
        raise BenchmarkConfigurationError(message)
    all_values = [value for window in windows for value in window]
    floor = minimum_sample_count(percentile)
    if len(all_values) < floor:
        message = (
            f"{len(all_values)} retained samples is below the {floor} required for "
            f"the {percentile:.2%} percentile to be defined"
        )
        raise BenchmarkConfigurationError(message)
    point_estimate = _percentile(all_values, percentile)
    rng = random.Random(seed)
    window_count = len(windows)
    resampled_percentiles = []
    for _ in range(resample_count):
        resample_values: list[float] = []
        for _ in range(window_count):
            resample_values.extend(windows[rng.randrange(window_count)])
        resampled_percentiles.append(_percentile(resample_values, percentile))
    resampled_percentiles.sort()
    alpha = 1 - confidence_level
    lower_index = _percentile_index(len(resampled_percentiles), alpha / 2)
    upper_index = _percentile_index(len(resampled_percentiles), 1 - alpha / 2)
    return ConfidenceInterval(
        lower=resampled_percentiles[lower_index],
        upper=resampled_percentiles[upper_index],
        point_estimate=point_estimate,
    )


def expand_with_uncertainty(
    interval: ConfidenceInterval, total_uncertainty_seconds: float
) -> ConfidenceInterval:
    return ConfidenceInterval(
        lower=interval.lower - total_uncertainty_seconds,
        upper=interval.upper + total_uncertainty_seconds,
        point_estimate=interval.point_estimate,
    )


def absolute_threshold_decisive(
    interval: ConfidenceInterval,
    threshold_seconds: float,
    *,
    total_uncertainty_seconds: float,
) -> bool:
    expanded = expand_with_uncertainty(interval, total_uncertainty_seconds)
    return expanded.upper <= threshold_seconds


def delta_threshold_decisive(
    delta_interval: ConfidenceInterval, threshold_seconds: float
) -> bool:
    return delta_interval.upper <= threshold_seconds


def bonferroni_confidence_level(target_confidence_level: float) -> float:
    if not 0 < target_confidence_level < 1:
        message = "target_confidence_level must be between 0 and 1 exclusive"
        raise BenchmarkConfigurationError(message)
    alpha = 1 - target_confidence_level
    return 1 - alpha / 2


def bonferroni_delta_interval(
    control_windows: Sequence[Sequence[float]],
    loaded_windows: Sequence[Sequence[float]],
    *,
    percentile: float,
    confidence_level: float,
    resample_count: int,
    seed: int,
    delta_seconds: float,
) -> ConfidenceInterval:
    adjusted_confidence = bonferroni_confidence_level(confidence_level)
    control_ci = block_bootstrap_percentile_ci(
        control_windows,
        percentile=percentile,
        confidence_level=adjusted_confidence,
        resample_count=resample_count,
        seed=seed,
    )
    loaded_ci = block_bootstrap_percentile_ci(
        loaded_windows,
        percentile=percentile,
        confidence_level=adjusted_confidence,
        resample_count=resample_count,
        seed=seed + 1,
    )
    half_width = (control_ci.upper - control_ci.lower) / 2 + (
        loaded_ci.upper - loaded_ci.lower
    ) / 2
    return ConfidenceInterval(
        lower=delta_seconds - half_width,
        upper=delta_seconds + half_width,
        point_estimate=delta_seconds,
    )

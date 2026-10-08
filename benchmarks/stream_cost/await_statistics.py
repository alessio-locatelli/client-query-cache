from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import accumulate, combinations_with_replacement
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class WeightedStatistic:
    value: float  # The statistic may be zero or negative.
    weight: int  # Positive multinomial multiplicity.


@dataclass(frozen=True, slots=True)
class BootstrapTest:
    estimate: float  # Positive observed statistic.
    p_value: float  # Probability in [0, 1].
    centered_samples: tuple[WeightedStatistic, ...]

    def upper_bound(self, alpha: float) -> float:  # Tail probability in (0, 1).
        return self.estimate * math.exp(
            -weighted_quantile(self.centered_samples, alpha)
        )


def weighted_quantile(
    samples: Sequence[WeightedStatistic], probability: float
) -> float:  # Probability lies in (0, 1).
    threshold = math.ceil(probability * sum(sample.weight for sample in samples))
    return next(
        sample.value
        for sample, cumulative in zip(
            samples,
            accumulate(sample.weight for sample in samples),
            strict=True,
        )
        if cumulative >= threshold
    )


def exact_block_draws(
    block_count: int,
) -> Iterator[tuple[tuple[int, ...], int]]:  # Positive block count and weights.
    for indices in combinations_with_replacement(range(block_count), block_count):
        multiplicities = Counter(indices)
        weight = math.factorial(block_count) // math.prod(
            math.factorial(count) for count in multiplicities.values()
        )
        yield indices, weight


@dataclass(frozen=True, slots=True)
class BasicBootstrap:
    estimate: float  # Signed observed statistic, including zero.
    centered_samples: tuple[WeightedStatistic, ...]

    def lower_bound(self, alpha: float) -> float:  # Tail probability in (0, 1).
        return self.estimate - weighted_quantile(self.centered_samples, 1 - alpha)

    def upper_bound(self, alpha: float) -> float:  # Tail probability in (0, 1).
        return self.estimate - weighted_quantile(self.centered_samples, alpha)


def exact_basic_bootstrap(
    statistic: Callable[[tuple[int, ...]], float], *, block_count: int
) -> BasicBootstrap:  # Positive block count.
    observed = statistic(tuple(range(block_count)))
    samples = tuple(
        WeightedStatistic(statistic(indices) - observed, weight)
        for indices, weight in exact_block_draws(block_count)
    )
    return BasicBootstrap(
        observed, tuple(sorted(samples, key=lambda sample: sample.value))
    )


def exact_block_bootstrap(
    statistic: Callable[[tuple[int, ...]], float],
    *,
    block_count: int,  # Positive block count.
    limit: float,  # Positive registered upper limit.
) -> BootstrapTest:
    observed = statistic(tuple(range(block_count)))
    log_observed = math.log(observed)
    weighted_samples: list[WeightedStatistic] = []  # Empty until the first resample.
    null_threshold = log_observed - math.log(limit)
    lower_tail = 0
    for indices, weight in exact_block_draws(block_count):
        centered = math.log(statistic(indices)) - log_observed
        weighted_samples.append(WeightedStatistic(centered, weight))
        if centered <= null_threshold:
            lower_tail += weight
    return BootstrapTest(
        observed,
        (1 + lower_tail) / (1 + block_count**block_count),
        tuple(sorted(weighted_samples, key=lambda sample: sample.value)),
    )


def holm_adjusted(p_values: Sequence[float]) -> tuple[float, ...]:
    adjusted = [1.0] * len(p_values)
    previous = 0.0
    for rank, index in enumerate(
        sorted(range(len(p_values)), key=p_values.__getitem__)
    ):
        previous = max(previous, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = previous
    return tuple(adjusted)


def nearest_rank_p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]

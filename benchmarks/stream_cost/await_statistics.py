from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import accumulate, combinations_with_replacement
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@dataclass(frozen=True, slots=True)
class WeightedStatistic:
    value: float  # The centered log statistic may be zero or negative.
    weight: int  # Positive multinomial multiplicity.


@dataclass(frozen=True, slots=True)
class BootstrapTest:
    estimate: float  # Positive observed statistic.
    p_value: float  # Probability in [0, 1].
    centered_samples: tuple[WeightedStatistic, ...]

    def upper_bound(self, alpha: float) -> float:  # Tail probability in (0, 1).
        threshold = math.ceil(
            alpha * sum(sample.weight for sample in self.centered_samples)
        )
        quantile = next(
            sample.value
            for sample, cumulative in zip(
                self.centered_samples,
                accumulate(sample.weight for sample in self.centered_samples),
                strict=True,
            )
            if cumulative >= threshold
        )
        return self.estimate * math.exp(-quantile)


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
    for indices in combinations_with_replacement(range(block_count), block_count):
        multiplicities = Counter(indices)
        weight = math.factorial(block_count) // math.prod(
            math.factorial(count) for count in multiplicities.values()
        )
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

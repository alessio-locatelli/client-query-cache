from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.await_statistics import (
    exact_block_bootstrap,
    holm_adjusted,
    nearest_rank_p95,
)
from client_query_cache._types import (
    ExclusiveProbability,
    MaxAwaitTimeMs,
    NonEmptyStr,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    Probability,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from benchmarks.stream_cost.await_model import (
        AwaitConfiguration,
        AwaitMetric,
        AwaitWindow,
        Comparison,
    )
    from benchmarks.stream_cost.await_statistics import BootstrapTest, WeightedStatistic


class UnresolvedComparisonError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComparisonEvidence:
    comparison: Comparison
    estimate: PositiveFloat | None  # Absent when unresolved.
    nominal_upper: PositiveFloat | None  # Absent when unresolved.
    holm_step_upper: PositiveFloat | None  # Absent when unresolved.
    p_value: Probability
    adjusted_p_value: Probability
    passes: bool
    unresolved: bool
    holm_rank: PositiveInt  # One-based rank in the complete comparison family.
    holm_step_alpha: ExclusiveProbability  # Per-step tail probability.
    bootstrap_distribution: tuple[WeightedStatistic, ...]


@dataclass(frozen=True, slots=True)
class AwaitDecision:
    selected_ms: MaxAwaitTimeMs
    eligible_ms: tuple[MaxAwaitTimeMs, ...]
    inconclusive: bool
    rationale: NonEmptyStr
    comparisons: tuple[ComparisonEvidence, ...]


def _metric(samples: Sequence[AwaitWindow], metric: AwaitMetric) -> float:
    if metric == "lag_p95_seconds":
        return nearest_rank_p95(
            [value for sample in samples for value in sample.lag_seconds]
        )
    if metric == "shutdown_p95_seconds":
        return nearest_rank_p95(
            [value for sample in samples for value in sample.shutdown_seconds]
        )
    if metric == "server_cpu_seconds":
        return sum(cast("float", sample.server_cpu_seconds) for sample in samples)
    if metric == "client_cpu_seconds":
        return sum(cast("float", sample.client_cpu_seconds) for sample in samples)
    elapsed = sum(sample.elapsed_seconds for sample in samples)
    if metric == "server_cpu_rate":
        return (
            sum(cast("float", sample.server_cpu_seconds) for sample in samples)
            / elapsed
        )
    if metric == "client_cpu_rate":
        return (
            sum(cast("float", sample.client_cpu_seconds) for sample in samples)
            / elapsed
        )
    return (
        sum(
            cast("NonNegativeInt", sample.bytes_sent)
            + cast("NonNegativeInt", sample.bytes_received)
            for sample in samples
        )
        / elapsed
    )


def _comparison_test(
    samples: Sequence[AwaitWindow],
    comparison: Comparison,
    configuration: AwaitConfiguration,
) -> BootstrapTest:
    candidate = {
        sample.block: sample
        for sample in samples
        if sample.candidate_ms == comparison["candidate"]
        and sample.model == comparison["model"]
        and sample.workload == comparison["workload"]
    }
    reference = {
        sample.block: sample
        for sample in samples
        if sample.candidate_ms == comparison["reference"]
        and sample.model == comparison["model"]
        and sample.workload == comparison["workload"]
    }
    block_count = len(configuration["block_orders"])
    if len(candidate) != block_count or (
        comparison["reference"] is not None and len(reference) != block_count
    ):
        raise UnresolvedComparisonError("missing or failed paired blocks")
    metric = comparison["metric"]
    resolution = configuration["uncertainty"]["resolution"][metric]

    def statistic(indices: tuple[NonNegativeInt, ...]) -> float:
        numerator = _metric(tuple(candidate[index] for index in indices), metric)
        if numerator <= 0:
            raise UnresolvedComparisonError("nonpositive candidate statistic")
        if comparison["reference"] is None:
            return numerator
        denominator = _metric(tuple(reference[index] for index in indices), metric)
        if denominator <= resolution:
            raise UnresolvedComparisonError("baseline denominator is below resolution")
        return numerator / denominator

    return exact_block_bootstrap(
        statistic, block_count=block_count, limit=comparison["limit"]
    )


def evaluate_await_decision(
    samples: Sequence[AwaitWindow], configuration: AwaitConfiguration
) -> AwaitDecision:
    tests: list[BootstrapTest | None] = []
    for comparison in configuration["comparisons"]:
        try:
            tests.append(_comparison_test(samples, comparison, configuration))
        except UnresolvedComparisonError:
            tests.append(None)
    p_values = tuple(test.p_value if test is not None else 1.0 for test in tests)
    adjusted = holm_adjusted(p_values)
    ranks = {
        index: rank
        for rank, index in enumerate(
            sorted(range(len(tests)), key=p_values.__getitem__)
        )
    }
    evidence: list[ComparisonEvidence] = []
    alpha = 1 - configuration["uncertainty"]["confidence_level"]
    for index, (comparison, test) in enumerate(
        zip(configuration["comparisons"], tests, strict=True)
    ):
        bound = (
            test.upper_bound(alpha / (len(tests) - ranks[index]))
            if test is not None
            else None
        )
        evidence.append(
            ComparisonEvidence(
                comparison,
                test.estimate if test is not None else None,
                test.upper_bound(alpha) if test is not None else None,
                bound,
                p_values[index],
                adjusted[index],
                bound is not None
                and adjusted[index] <= alpha
                and bound <= comparison["limit"],
                test is None,
                ranks[index] + 1,
                alpha / (len(tests) - ranks[index]),
                test.centered_samples if test is not None else (),
            )
        )
    eligible = []
    for candidate in configuration["candidates_ms"][1:]:
        outcomes = tuple(
            item
            for item in evidence
            if item.comparison["candidate"] == candidate
            and item.comparison["reference"] in {None, 1000}
        )
        safe = all(
            item.passes
            for item in outcomes
            if item.comparison["workload"] != "idle"
            or item.comparison["metric"] == "client_cpu_rate"
        )
        saves = all(
            any(
                item.passes
                for item in outcomes
                if item.comparison["model"] == model
                and item.comparison["workload"] == "idle"
                and item.comparison["metric"] in {"server_cpu_rate", "byte_rate"}
            )
            for model in configuration["models"]
        )
        expected_windows = (
            len(configuration["block_orders"]) * len(configuration["models"]) * 4
        )
        complete = (
            sum(sample.candidate_ms == candidate for sample in samples)
            == expected_windows
        )
        baseline_complete = (
            sum(sample.candidate_ms == 1000 for sample in samples) == expected_windows
        )
        if complete and baseline_complete and safe and saves:
            eligible.append(candidate)
    if not eligible:
        return AwaitDecision(
            selected_ms=1000,
            eligible_ms=(),
            inconclusive=True,
            rationale="No larger candidate met every registered gate in both models.",
            comparisons=tuple(evidence),
        )
    if len(eligible) == 1:
        return AwaitDecision(
            selected_ms=eligible[0],
            eligible_ms=tuple(eligible),
            inconclusive=False,
            rationale="One larger candidate met every registered gate in both models.",
            comparisons=tuple(evidence),
        )
    for metric in ("server_cpu_rate", "byte_rate"):
        if any(
            item.estimate is None
            for item in evidence
            if item.comparison["candidate"] in eligible
            and item.comparison["reference"] == 1000
            and item.comparison["metric"] == metric
        ):
            continue
        best = min(eligible, key=partial(_resource_order, evidence, metric))
        if all(
            item.passes
            for item in evidence
            if item.comparison["candidate"] == best
            and item.comparison["reference"] in eligible
            and item.comparison["metric"] == metric
        ):
            return AwaitDecision(
                selected_ms=best,
                eligible_ms=tuple(eligible),
                inconclusive=False,
                rationale=(
                    f"The lowest worse-path {metric} beat every other eligible "
                    "candidate decisively in both models."
                ),
                comparisons=tuple(evidence),
            )
    return AwaitDecision(
        selected_ms=min(eligible),
        eligible_ms=tuple(eligible),
        inconclusive=False,
        rationale=(
            "Pairwise resource comparisons did not establish one winner; "
            "selected the shorter eligible wait."
        ),
        comparisons=tuple(evidence),
    )


def _resource_order(
    evidence: Sequence[ComparisonEvidence], metric: str, candidate: MaxAwaitTimeMs
) -> tuple[float, MaxAwaitTimeMs]:
    estimates = tuple(
        item.estimate
        for item in evidence
        if item.comparison["candidate"] == candidate
        and item.comparison["reference"] == 1000
        and item.comparison["metric"] == metric
        and item.comparison["workload"] == "idle"
    )
    return max(cast("float", value) for value in estimates), candidate

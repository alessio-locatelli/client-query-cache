from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from functools import partial
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict, cast

from annotated_types import Len

from benchmarks.stream_cost.await_statistics import (
    WeightedStatistic,
    exact_basic_bootstrap,
    exact_block_draws,
    weighted_quantile,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import _CONFIG, Protocol, validate_capture
from client_query_cache._types import (
    ExclusiveProbability,
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from benchmarks.stream_cost.multiprocess_run import Model, Payload, Workload


type Outcome = Literal["opportunity", "below-threshold", "inconclusive"]


class Opportunity(TypedDict):
    model: Model
    workload: Workload
    outcome: Outcome
    complete: bool
    block_rates: tuple[float, ...]
    estimate: float | None  # CPU rate; None means unavailable.
    lower: float | None  # None means unavailable.
    upper: float | None  # None means unavailable.
    failure: NonEmptyStr | None  # Explanation for unavailable evidence.


class BaselineDecision(TypedDict):
    outcome: Literal["proceed", "below-threshold", "inconclusive"]
    comparisons: tuple[Opportunity, ...]
    alpha: ExclusiveProbability  # Per-alternative tail probability.
    threshold: PositiveFloat  # CPU-rate investment threshold.
    active_minus_idle: Annotated[dict[str, float | None], Len(2, 2)]


class NativeLag(TypedDict):
    model: Model
    block: NonNegativeInt  # Zero-based.
    workers: PositiveInt  # Group size.
    worker: NonNegativeInt  # Zero-based.
    p95_seconds: float  # Clock-corrected lag.
    lower_seconds: float  # Expanded endpoint.
    upper_seconds: float  # Expanded endpoint.


def _capture_p95(
    windows: tuple[tuple[float, ...], ...], indices: tuple[NonNegativeInt, ...]
) -> float:
    ordered = sorted(value for index in indices for value in windows[index])
    return ordered[math.floor(0.95 * len(ordered))]


def describe_native_lag(report: Mapping[str, object]) -> tuple[NativeLag, ...]:
    expected_events = Protocol.load().updates
    intervals: list[NativeLag] = []
    for sample in cast("list[Payload]", report["cells"]):
        if (
            sample["path"] != "native"
            or sample["workload"] != "active"
            or not sample["healthy"]
        ):
            continue
        for worker, metrics in enumerate(
            cast("Sequence[Payload]", sample["workers_measured"])
        ):
            windows = tuple(
                tuple(window)
                for window in cast("Sequence[Sequence[float]]", metrics["lag_windows"])
            )
            validate_capture(
                cast("NonNegativeInt", metrics["invalidations"]),
                windows,
                expected_events,
            )
            corrected = tuple(
                tuple(
                    value + cast("float", sample["clock_offset_seconds"])
                    for value in window
                )
                for window in windows
            )
            statistic = partial(_capture_p95, corrected)
            percentiles = tuple(
                sorted(
                    (
                        WeightedStatistic(statistic(indices), weight)
                        for indices, weight in exact_block_draws(len(corrected))
                    ),
                    key=lambda sample: sample.value,
                )
            )
            uncertainty = cast("NonNegativeFloat", sample["clock_uncertainty_seconds"])
            intervals.append(
                {
                    "model": cast("Model", sample["model"]),
                    "block": cast("NonNegativeInt", sample["block"]),
                    "workers": cast("PositiveInt", sample["workers"]),
                    "worker": worker,
                    "p95_seconds": statistic(tuple(range(len(corrected)))),
                    "lower_seconds": weighted_quantile(percentiles, 0.025)
                    - uncertainty,
                    "upper_seconds": weighted_quantile(percentiles, 0.975)
                    + uncertainty,
                }
            )
    return tuple(intervals)


def _mean_rates(
    values: tuple[float, ...], indices: tuple[NonNegativeInt, ...]
) -> float:
    return fmean(values[index] for index in indices)


def _sample_rate(
    sample: Payload, workload: Workload, seconds: PositiveFloat
) -> NonNegativeFloat:
    if not sample["healthy"]:
        raise BenchmarkSetupError("failed required stream-only/control cell")
    fields = (
        ("server_cpu_seconds", "server_drain_cpu_seconds")
        if workload == "active"
        else ("server_cpu_seconds",)
    )
    cpu = 0.0
    for field in fields:
        value = sample[field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise BenchmarkSetupError("required MongoDB CPU metric is unavailable")
        cpu += value
    if sample["application_seconds"] != seconds:
        raise BenchmarkSetupError("cell does not match registered application duration")
    return cpu / seconds


def _block_rate(
    samples: tuple[Payload, ...],
    model: Model,
    workload: Workload,
    block: NonNegativeInt,
    seconds: PositiveFloat,
) -> float:
    rates: dict[tuple[PositiveInt, str], float] = {}
    for workers in (1, 8):
        for path in ("stream-only", "stream-control"):
            matched = tuple(
                sample
                for sample in samples
                if (
                    sample["block"],
                    sample["model"],
                    sample["workload"],
                    sample["workers"],
                    sample["path"],
                )
                == (block, model, workload, workers, path)
            )
            if len(matched) != 1:
                raise BenchmarkSetupError("missing or duplicated matched cell")
            rates[workers, path] = _sample_rate(matched[0], workload, seconds)
    return (rates[8, "stream-only"] - rates[8, "stream-control"]) - (
        rates[1, "stream-only"] - rates[1, "stream-control"]
    )


def _incomplete(model: Model, workload: Workload, reason: str) -> Opportunity:
    return {
        "model": model,
        "workload": workload,
        "outcome": "inconclusive",
        "complete": False,
        "block_rates": (),
        "estimate": None,
        "lower": None,
        "upper": None,
        "failure": reason,
    }


def _comparison(
    samples: tuple[Payload, ...],
    model: Model,
    workload: Workload,
    *,
    blocks: PositiveInt,
    seconds: PositiveFloat,
    alpha: ExclusiveProbability,
    threshold: PositiveFloat,
) -> Opportunity:
    try:
        block_rates = tuple(
            _block_rate(samples, model, workload, block, seconds)
            for block in range(blocks)
        )
    except BenchmarkSetupError as error:
        return _incomplete(model, workload, str(error))
    except KeyError:
        return _incomplete(
            model, workload, "required cell identity or metric is missing"
        )
    inference = exact_basic_bootstrap(
        partial(_mean_rates, block_rates), block_count=blocks
    )
    lower = inference.lower_bound(alpha)
    upper = inference.upper_bound(alpha)
    outcome: Outcome = (
        "opportunity"
        if lower > threshold
        else "below-threshold"
        if upper <= threshold
        else "inconclusive"
    )
    return {
        "model": model,
        "workload": workload,
        "outcome": outcome,
        "complete": True,
        "block_rates": block_rates,
        "estimate": inference.estimate,
        "lower": lower,
        "upper": upper,
        "failure": None,
    }


def evaluate_baseline(report: Mapping[str, object]) -> BaselineDecision:
    configuration_bytes = _CONFIG.read_bytes()
    configuration = json.loads(configuration_bytes)
    if (
        report["phase"] != "baseline"
        or report["configuration_sha256"] != sha256(configuration_bytes).hexdigest()
        or report["protocol"] != asdict(Protocol.load())
    ):
        raise BenchmarkSetupError(
            "report does not match the registered baseline protocol"
        )
    gate = configuration["baseline_gate"]
    alpha = gate["family_alpha"] / gate["alternatives"]
    samples = tuple(cast("list[Payload]", report["cells"]))
    comparisons = tuple(
        _comparison(
            samples,
            model,
            workload,
            blocks=configuration["blocks"],
            seconds=configuration["window_seconds"],
            alpha=alpha,
            threshold=gate["cpu_rate"],
        )
        for model in configuration["models"]
        for workload in configuration["workloads"]
    )
    outcome: Literal["proceed", "below-threshold", "inconclusive"] = (
        "proceed"
        if any(comparison["outcome"] == "opportunity" for comparison in comparisons)
        else "below-threshold"
        if all(comparison["outcome"] == "below-threshold" for comparison in comparisons)
        else "inconclusive"
    )
    diagnostics: dict[str, float | None] = {}
    for model in configuration["models"]:
        active = next(
            comparison["estimate"]
            for comparison in comparisons
            if comparison["model"] == model and comparison["workload"] == "active"
        )
        idle = next(
            comparison["estimate"]
            for comparison in comparisons
            if comparison["model"] == model and comparison["workload"] == "idle"
        )
        diagnostics[model] = None if active is None or idle is None else active - idle
    return {
        "outcome": outcome,
        "comparisons": comparisons,
        "alpha": alpha,
        "threshold": gate["cpu_rate"],
        "active_minus_idle": diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the shared-invalidation gate and describe native lag."
    )
    parser.add_argument("report", type=Path)
    report = json.loads(parser.parse_args().report.read_bytes())
    print(
        json.dumps(
            {
                **evaluate_baseline(report),
                "native_lag_context": describe_native_lag(report),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

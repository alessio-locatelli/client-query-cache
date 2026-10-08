from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from functools import partial
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Literal, TypedDict, cast

from benchmarks.stream_cost.await_statistics import exact_basic_bootstrap
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import _CONFIG, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from benchmarks.stream_cost.multiprocess_run import Model, Payload, Workload


type Outcome = Literal["opportunity", "below-threshold", "inconclusive"]


class Opportunity(TypedDict):
    model: Model
    workload: Workload
    outcome: Outcome
    complete: bool
    block_rates: tuple[float, ...]  # Can be empty when evidence is incomplete.
    estimate: float | None  # Signed CPU rate; None means unavailable.
    lower: float | None  # Signed lower bound; None means unavailable.
    upper: float | None  # Signed upper bound; None means unavailable.
    failure: str | None  # Nonempty explanation for unavailable evidence.


class BaselineDecision(TypedDict):
    outcome: Literal["proceed", "below-threshold", "inconclusive"]
    comparisons: tuple[Opportunity, ...]
    alpha: float  # Positive per-alternative tail probability.
    threshold: float  # Positive CPU-rate investment threshold.
    active_minus_idle: dict[str, float | None]  # Two signed diagnostic rates.


def _mean_rates(values: tuple[float, ...], indices: tuple[int, ...]) -> float:
    return fmean(values[index] for index in indices)


def _sample_rate(sample: Payload, workload: Workload, seconds: float) -> float:
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
    block: int,
    seconds: float,
) -> float:
    rates: dict[tuple[int, str], float] = {}  # Four matched cells per complete block.
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
    blocks: int,
    seconds: float,
    alpha: float,
    threshold: float,
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
    diagnostics: dict[str, float | None] = {}  # Populated for both execution models.
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
        description="Evaluate the registered shared-invalidation investment gate."
    )
    parser.add_argument("report", type=Path)
    print(
        json.dumps(
            evaluate_baseline(json.loads(parser.parse_args().report.read_bytes())),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

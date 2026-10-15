"""Evaluate the frozen empirical protocol validation without candidate promotion."""

from __future__ import annotations

import argparse
import itertools
import json
import operator
import statistics
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from scipy.stats import t

from benchmarks.stream_cost.shared_cache.analysis import (
    InferenceSettings,
    block_statistics,
    compare,
    paired_blocks,
)
from benchmarks.stream_cost.shared_cache.protocol import Registration
from client_query_cache._types import JsonDict, NonEmptyStr, PositiveInt
from research.shared_cache_runtime.qualification import (
    health_failures,
    qualification_decision,
    require_complete,
)
from scripts.analyze_shared_cache_runtime import stable_bounds, weights, wilson

if TYPE_CHECKING:
    from numpy.typing import NDArray

type Array = NDArray[np.float64]
CONFIG = Path("reports/shared-worker-cache/v8/config.json")


def interval(
    candidate: Array, reference: Array, *, relative: bool
) -> tuple[float, float]:
    low, high = float("inf"), float("-inf")
    selections = (
        tuple(range(len(candidate))),
        *(
            tuple(index for index in range(len(candidate)) if index != omitted)
            for omitted in range(len(candidate))
        ),
    )
    for selected, seed in itertools.product(selections, (278, 279)):
        indices = np.array(selected)
        sampling = weights(len(selected), seed)
        changed = sampling @ candidate[indices]
        control = sampling @ reference[indices]
        difference = changed / control - 1 if relative else changed - control
        lower, upper = np.quantile(difference, (0.025, 0.975), method="lower")
        low, high = min(low, float(lower)), max(high, float(upper))
    return low, high


def measurements(cell: JsonDict) -> dict[str, float]:
    metrics = block_statistics(cell)
    metrics["wire_per_request"] = metrics["wire_bytes"] / cast(
        "PositiveInt", cell["completed"]
    )
    populations = cast("dict[str, JsonDict]", cell["populations"])
    names = ("sync", "async") if cell["model"] == "mixed" else ("request",)
    for name in names:
        metrics["p95_" + name] = cast("float", populations[name]["p95_seconds"])
        metrics["p99_" + name] = cast("float", populations[name]["p99_seconds"])
    return metrics


def evaluate(
    qualification: JsonDict, validation: JsonDict, config: Path = CONFIG
) -> JsonDict:
    registration = Registration.load(config)
    require_complete(qualification, "qualification", registration)
    require_complete(validation, "validation", registration)
    all_cells = cast("list[JsonDict]", qualification["cells"]) + cast(
        "list[JsonDict]", validation["cells"]
    )
    failures = health_failures(all_cells, registration)
    cells = cast("list[JsonDict]", validation["cells"])
    statistics = {id(cell): measurements(cell) for cell in cells if cell["healthy"]}
    equivalence: list[JsonDict] = []
    for condition, path in itertools.product(
        ("short20.1", "short27.6"), registration.paths
    ):
        selected = {
            label: sorted(
                (
                    cell
                    for cell in cells
                    if cell["condition"] == label
                    and cell["path"] == path
                    and cell["model"] == "mixed"
                ),
                key=lambda cell: cast("int", cell["block"]),
            )
            for label in ("reference", condition)
        }
        if any(not cell["healthy"] for group in selected.values() for cell in group):
            continue
        metrics = (
            "p95_sync",
            "p95_async",
            "p99_sync",
            "p99_async",
            "cpu_per_request",
            "wire_per_request",
            "steady_pss",
        )
        if path != "direct":
            metrics = (*metrics, "lag_p95")
        for metric in metrics:
            changed = np.array(
                [statistics[id(cell)][metric] for cell in selected[condition]]
            )
            control = np.array(
                [statistics[id(cell)][metric] for cell in selected["reference"]]
            )
            relative = metric in {"cpu_per_request", "wire_per_request", "steady_pss"}
            tolerance = (
                0.05
                if relative or metric == "lag_p95"
                else 0.0001
                if metric.startswith("p95")
                else 0.00025
            )
            lower, upper = interval(changed, control, relative=relative)
            equivalence.append(
                {
                    "condition": condition,
                    "path": path,
                    "metric": metric,
                    "lower": lower,
                    "upper": upper,
                    "margin": tolerance,
                    "equivalent": lower >= -tolerance and upper <= tolerance,
                }
            )
    point_checks: JsonDict = {}
    for condition in ("reference", "short27.6"):
        first = [
            cell
            for cell in cells
            if cell["condition"] == condition and cell["block"] == 0
        ]
        if all(cell["healthy"] for cell in first):
            checks = compare(
                paired_blocks(first, lambda cell: statistics[id(cell)]),
                InferenceSettings.load(registration, 1, inference=False),
            )
            point_checks[condition] = [asdict(check) for check in checks]
    return {
        "failures": failures,
        "equivalence": equivalence,
        "diagnostic_point_checks": point_checks,
    }


def historical_lags(
    path: Path, capture_counts: tuple[PositiveInt, ...] = (1, 2, 3, 6)
) -> list[JsonDict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    cells = report["cells"]
    rows: list[JsonDict] = []
    for model, workers in (
        ("sync", 4),
        ("sync", 8),
        ("async", 4),
        ("async", 8),
        ("mixed", 8),
    ):
        for captures in capture_counts:
            path_values = {}
            for candidate in ("independent", "shared-index"):
                selected = sorted(
                    (
                        cell
                        for cell in cells
                        if cell["model"] == model
                        and cell["workers"] == workers
                        and cell["path"] == candidate
                    ),
                    key=operator.itemgetter("block"),
                )
                values = []
                for cell in selected:
                    windows = (
                        cell["owner"]["lag_windows"][:captures]
                        if candidate == "shared-index"
                        else [
                            window
                            for worker in cell["workers_measured"]
                            for window in worker["lag"]["lag_windows"][:captures]
                        ]
                    )
                    lags = (
                        np.array([lag for window in windows for lag in window])
                        + cell["clock_offset_seconds"]
                    )
                    values.append(np.quantile(lags, 0.95, method="higher"))
                path_values[candidate] = np.array(values)
            delta = path_values["shared-index"] - path_values["independent"]
            uncertainty = max(
                cell["clock_uncertainty_seconds"]
                for cell in cells
                if cell["model"] == model and cell["workers"] == workers
            )
            generator = np.random.default_rng(278 + workers + captures)
            for kind, observations, threshold in (
                ("delta", delta, 0.05),
                ("absolute", path_values["shared-index"], 0.5),
            ):
                noise = generator.choice(
                    observations - observations.mean(), size=(2000, 12)
                )
                _primary, _smallest, largest = stable_bounds(noise)
                largest += uncertainty
                passed = largest + 0.8 * threshold <= threshold
                error = largest + threshold <= threshold
                rows.append(
                    {
                        "model": model,
                        "workers": workers,
                        "captures": captures,
                        "criterion": kind,
                        "assumption": "iid block sensitivity only",
                        "observed_sd_seconds": float(observations.std(ddof=1)),
                        "lag_one_block_correlation": float(
                            np.corrcoef(observations[:-1], observations[1:])[0, 1]
                        ),
                        "clock_expansion_seconds": uncertainty,
                        "power_lower": wilson(int(passed.sum()), 2000)[0],
                        "boundary_error_upper": wilson(int(error.sum()), 2000)[1],
                    }
                )
    return rows


def temporal_slices(report: JsonDict) -> list[JsonDict]:
    differences: dict[tuple[NonEmptyStr, PositiveInt, NonEmptyStr], list[float]] = (
        defaultdict(list)
    )
    for cell in cast("list[JsonDict]", report["cells"]):
        start = next(
            boundary["start"]
            for boundary in cell["timing"]
            if boundary["name"] == "measurement-scheduled"
        )
        times = (
            np.concatenate([worker["completion_times"] for worker in cell["traces"]])
            - start
        )
        latencies = np.concatenate([worker["latencies"] for worker in cell["traces"]])
        settled = np.quantile(
            latencies[(times >= 10) & (times < 30)], (0.95, 0.99), method="higher"
        )
        for duration in (3, 5, 10, 15):
            prefix = np.quantile(
                latencies[(times >= 1) & (times < 1 + duration)],
                (0.95, 0.99),
                method="higher",
            )
            for percentile, difference in zip(
                ("p95", "p99"), prefix - settled, strict=True
            ):
                differences[cell["path"], duration, percentile].append(
                    float(difference)
                )
    critical = t.ppf(0.975, 5)
    rows: list[JsonDict] = []
    for (path, duration, percentile), values in differences.items():
        margin = critical * statistics.stdev(values) / len(values) ** 0.5
        mean = statistics.mean(values)
        rows.append(
            {
                "path": path,
                "duration_seconds": duration,
                "percentile": percentile,
                "lower_seconds": mean - margin,
                "upper_seconds": mean + margin,
                "assumption": "six paired discovery blocks; Student t interval",
            }
        )
    return rows


def runtime_forecast(
    reference: Path, qualification: JsonDict, validation: JsonDict, discovery: JsonDict
) -> JsonDict:
    residuals = defaultdict(list)
    keys = ("profile", "model", "workers", "path")
    for report in (qualification, validation, discovery):
        for cell in report["cells"]:
            priming = max(worker["priming_seconds"] for worker in cell["ready"])
            residuals[tuple(cell[key] for key in keys)].append(
                cell["wall_seconds"]
                - cell["window_seconds"]
                - cell["warmup_seconds"]
                - priming
            )
    overhead = {key: statistics.median(values) for key, values in residuals.items()}
    rows: list[JsonDict] = []
    fallbacks: set[tuple[tuple[object, ...], tuple[object, ...]]] = set()
    for phase in (
        "screening",
        "confirmation",
        "capacity",
        "active",
        "cold",
        "sensitivity",
    ):
        historical = json.loads(
            (reference / f"v8-{phase}.json").read_text(encoding="utf-8")
        )
        estimates = []
        for cell in historical["cells"]:
            key = tuple(cell[field] for field in keys)
            if key in overhead:
                selected = key
            else:
                selected = min(
                    (
                        other
                        for other in overhead
                        if other[1] == key[1] and other[3] == key[3]
                    ),
                    key=lambda other: (other[0] != key[0], abs(other[2] - key[2])),
                )
                fallbacks.add((key, selected))
            priming = max(worker["priming_seconds"] for worker in cell["ready"])
            estimates.append(
                cell["window_seconds"]
                + cell["warmup_seconds"]
                + priming
                + overhead[selected]
            )
        rows.append(
            {
                "phase": phase,
                "windows": len(estimates),
                "estimated_seconds": sum(estimates),
            }
        )
    return {
        "candidate_phases": rows,
        "qualification_seconds": qualification["wall_seconds"],
        "performance_total_seconds": qualification["wall_seconds"]
        + sum(row["estimated_seconds"] for row in rows),
        "fallbacks": sorted(fallbacks),
        "scope": "forecast only; excludes fault, smoke and analysis commands",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--historical-active", type=Path)
    parser.add_argument("--discovery", type=Path)
    parser.add_argument("--runtime-reference", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if all(
        value is None
        for value in (
            arguments.qualification,
            arguments.historical_active,
            arguments.discovery,
        )
    ):
        parser.error("provide --qualification, --historical-active or --discovery")
    if arguments.validation is not None and arguments.qualification is None:
        parser.error("--validation requires --qualification")
    if arguments.runtime_reference is not None and any(
        value is None
        for value in (
            arguments.qualification,
            arguments.validation,
            arguments.discovery,
        )
    ):
        parser.error(
            "--runtime-reference requires --qualification, --validation and --discovery"
        )
    report: JsonDict = {}
    qualification = (
        json.loads(arguments.qualification.read_text(encoding="utf-8"))
        if arguments.qualification is not None
        else None
    )
    validation = (
        json.loads(arguments.validation.read_text(encoding="utf-8"))
        if arguments.validation is not None
        else None
    )
    discovery = (
        json.loads(arguments.discovery.read_text(encoding="utf-8"))
        if arguments.discovery is not None
        else None
    )
    if discovery is not None:
        report["discovery_slices"] = temporal_slices(discovery)
    if arguments.historical_active is not None:
        report["historical_lags"] = historical_lags(arguments.historical_active)
    if arguments.qualification is not None and arguments.validation is not None:
        report["fresh_validation"] = evaluate(
            qualification,
            validation,
            arguments.config,
        )
    elif arguments.qualification is not None:
        registration = Registration.load(arguments.config)
        decision = qualification_decision(qualification, registration)
        report["qualification"] = decision
    if arguments.runtime_reference is not None:
        report["runtime_forecast"] = runtime_forecast(
            arguments.runtime_reference, qualification, validation, discovery
        )
    with arguments.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    if (
        arguments.qualification is not None
        and arguments.validation is None
        and not decision["automated_checks_passed"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

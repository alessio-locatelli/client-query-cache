"""Evaluate the frozen empirical protocol validation without candidate promotion."""

from __future__ import annotations

import argparse
import itertools
import json
import operator
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np

from benchmarks.stream_cost.shared_cache.analysis import (
    InferenceSettings,
    block_statistics,
    compare,
    paired_blocks,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    validation_failure,
)
from client_query_cache._types import JsonDict, PositiveInt
from research.shared_cache_runtime.experiment import design_cells, planned_rows
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


def require_complete(report: JsonDict, design_name: str) -> None:
    design = json.loads(
        Path(f"reports/shared-worker-cache/runtime/{design_name}.json").read_text(
            encoding="utf-8"
        )
    )
    expected = planned_rows(design_cells(Registration.load(CONFIG), design))
    if report["planned"] != expected:
        raise ValueError("recorded schedule differs from the frozen design")
    keys = tuple(expected[0])
    actual = cast("list[JsonDict]", report["cells"])
    if Counter(tuple(row[key] for key in keys) for row in actual) != Counter(
        tuple(row[key] for key in keys) for row in expected
    ):
        raise ValueError("validation has missing, duplicate or unexpected windows")


def evaluate(qualification: JsonDict, validation: JsonDict) -> JsonDict:
    require_complete(qualification, "qualification")
    require_complete(validation, "validation")
    registration = Registration.load(CONFIG)
    all_cells = cast("list[JsonDict]", qualification["cells"]) + cast(
        "list[JsonDict]", validation["cells"]
    )
    failures = [
        {
            "condition": cell["condition"],
            "model": cell["model"],
            "path": cell["path"],
            "reason": cell["failure"],
        }
        if not cell["healthy"]
        else {
            "condition": cell["condition"],
            "model": cell["model"],
            "path": cell["path"],
            "reason": reason,
        }
        for cell in all_cells
        if not cell["healthy"]
        or (reason := validation_failure(cell, registration)) is not None
    ]
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


def historical_lags(path: Path) -> list[JsonDict]:
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
        for captures in (1, 2, 3, 6):
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--historical-active", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report: JsonDict = {"historical_lags": historical_lags(arguments.historical_active)}
    if arguments.qualification is not None and arguments.validation is not None:
        report["fresh_validation"] = evaluate(
            json.loads(arguments.qualification.read_text(encoding="utf-8")),
            json.loads(arguments.validation.read_text(encoding="utf-8")),
        )
    with arguments.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()

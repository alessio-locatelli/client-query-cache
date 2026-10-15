# /// script
# requires-python = ">=3.14"
# dependencies = ["numpy==2.3.4", "scipy==1.16.3", "annotated-types==0.7.0"]
# ///
"""Exploratory accounting and known-effect simulation for issue #278."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import platform
import time
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import numpy as np
import scipy
from annotated_types import Ge, Gt, MinLen
from scipy.special import ndtri

if TYPE_CHECKING:
    from numpy.typing import NDArray

type PositiveInt = Annotated[int, Gt(0)]
type NonNegativeInt = Annotated[int, Ge(0)]
type NonEmptyStr = Annotated[str, MinLen(1)]
type Record = dict[NonEmptyStr, object]
type Array = NDArray[np.float64]

SEED = 278
STUDIES = 2_000
DRAWS = 2_000
SAMPLES = (1_000, 2_500, 5_000, 10_000, 30_000, 60_000)
BLOCKS = (3, 6, 12, 24)
PERCENTILES = (0.95, 0.99)
EFFECTS_MS = (0.8, 0.95, 1.0, 1.05)
PHASES = (
    "calibration",
    "screening",
    "confirmation",
    "capacity",
    "active",
    "cold",
    "sensitivity",
)


def records(report: Record, key: NonEmptyStr) -> list[Record]:
    return cast("list[Record]", report[key])


def number(record: Record, key: NonEmptyStr) -> float:
    return cast("float", record[key])


def section(record: Record, key: NonEmptyStr) -> Record:
    return cast("Record", record[key])


def load_reports(directory: Path) -> tuple[Record, Record]:
    reports: Record = {}
    provenance: Record = {}
    for version, phase in itertools.product((7, 8), PHASES):
        name = f"v{version}-{phase}"
        path = directory / f"{name}.json"
        content = path.read_bytes()
        report = json.loads(content)
        reports[name] = report
        provenance[name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "environment": report["environment"],
        }
    return reports, provenance


def accounting(reports: Record) -> list[Record]:
    rows: list[Record] = []
    for name, report in reports.items():
        cells = records(cast("Record", report), "cells")
        assert all(cell["healthy"] for cell in cells)
        measurement = sum(number(cell, "window_seconds") for cell in cells)
        warmup = sum(number(cell, "warmup_seconds") for cell in cells)
        priming = sum(
            max(number(worker, "priming_seconds") for worker in records(cell, "ready"))
            for cell in cells
        )
        rows.append(
            {
                "report": name,
                "windows": len(cells),
                "measurement_seconds": measurement,
                "warmup_seconds": warmup,
                "priming_lower_seconds": priming,
                "start_lead_seconds": len(cells),
                "known_lower_seconds": measurement + warmup + priming + len(cells),
            }
        )
    return rows


def runtime_options(runtime: list[Record]) -> list[Record]:
    current = {
        str(row["report"]).removeprefix("v8-"): row
        for row in runtime
        if str(row["report"]).startswith("v8-")
    }
    rows: list[Record] = []
    for blocks, hot, active, sensitivity in itertools.product(
        BLOCKS, (3, 10, 15, 30), (15, 30, 60), (3, 10, 15, 32)
    ):
        total = 0.0
        measurement = 0.0
        for phase, row in current.items():
            factor = blocks / 12 if phase in {"confirmation", "active", "cold"} else 1
            try:
                duration = {
                    "screening": hot,
                    "confirmation": hot,
                    "active": active,
                    "sensitivity": sensitivity,
                }[phase]
            except KeyError:
                measured = number(row, "measurement_seconds")
            else:
                measured = number(row, "windows") * duration
            measurement += measured * factor
            total += (
                measured
                + number(row, "warmup_seconds")
                + number(row, "priming_lower_seconds")
                + number(row, "start_lead_seconds")
            ) * factor
        rows.append(
            {
                "blocks": blocks,
                "hot_seconds": hot,
                "active_seconds": active,
                "sensitivity_seconds": sensitivity,
                "measurement_seconds": measurement,
                "known_lower_seconds": total,
                "smallest_read_population": min(
                    1006 * hot, 1006 * active / 2, 319 * sensitivity
                ),
                "balanced": blocks % 6 == 0,
                "preserves_write_workload": active == 60,
            }
        )
    return rows


@cache
def weights(blocks: PositiveInt, seed: int) -> Array:
    return (
        np.random.default_rng(seed)
        .multinomial(blocks, np.full(blocks, 1 / blocks), size=DRAWS)
        .astype(np.float64)
        / blocks
    )


def upper_bounds(pairs: Array) -> Array:
    draws = pairs @ weights(pairs.shape[1], SEED).T
    # Match analysis.bootstrap's floor-indexed upper end of a 95% interval.
    return np.quantile(draws, 0.975, axis=1, method="lower")


def stable_bounds(pairs: Array) -> tuple[Array, Array, Array]:
    primary = upper_bounds(pairs)
    second = np.quantile(
        pairs @ weights(pairs.shape[1], SEED + 1).T,
        0.975,
        axis=1,
        method="lower",
    )
    largest = np.maximum(primary, second)
    smallest = np.minimum(primary, second)
    for omitted in range(pairs.shape[1]):
        kept = np.delete(pairs, omitted, axis=1)
        bound = upper_bounds(kept)
        largest = np.maximum(largest, bound)
        smallest = np.minimum(smallest, bound)
    return primary, smallest, largest


def retrospective(reports: Record) -> list[Record]:
    rows: list[Record] = []
    subsets = np.array(
        tuple(
            tuple(order + cycle * 6 for order, cycle in enumerate(cycles))
            for cycles in itertools.product((0, 1), repeat=6)
        )
    )
    for version, model, workers, percentile in itertools.product(
        (7, 8), ("sync", "async"), (4, 8), (95, 99)
    ):
        cells = records(section(reports, f"v{version}-cold"), "cells")
        paths = {}
        for path in ("direct", "shared-index"):
            selected = sorted(
                (
                    cell
                    for cell in cells
                    if cell["model"] == model
                    and cell["workers"] == workers
                    and cell["path"] == path
                ),
                key=lambda cell: number(cell, "block"),
            )
            assert len(selected) == 12
            paths[path] = np.array(
                [
                    number(
                        section(section(cell, "populations"), "request"),
                        f"p{percentile}_seconds",
                    )
                    * 1_000
                    for cell in selected
                ]
            )
        pairs = paths["shared-index"] - paths["direct"]
        primary, smallest, largest = stable_bounds(pairs[None, :])
        six_primary, six_min, six_max = stable_bounds(pairs[subsets])
        point = float(pairs.mean())
        rows.append(
            {
                "version": version,
                "model": model,
                "workers": workers,
                "percentile": percentile,
                "point_ms": point,
                "sd_ms": float(pairs.std(ddof=1)),
                "early_late_ms": float(pairs[6:].mean() - pairs[:6].mean()),
                "lag_one_correlation": float(np.corrcoef(pairs[:-1], pairs[1:])[0, 1]),
                "upper_ms": float(primary[0]),
                "stable_pass": bool(largest[0] <= 1),
                "unstable": bool(smallest[0] <= 1 < largest[0]),
                "six_width_median_ms": float(
                    np.median(six_primary - pairs[subsets].mean(axis=1))
                ),
                "twelve_width_ms": float(primary[0] - point),
                "six_pass_fraction": float(np.mean(six_max <= 1)),
                "six_unstable_fraction": float(np.mean((six_min <= 1) & (six_max > 1))),
            }
        )
    return rows


def wilson(successes: NonNegativeInt, total: PositiveInt) -> tuple[float, float]:
    # One-sided 95% endpoints, reported together for Monte Carlo uncertainty.
    z = 1.6448536269514722
    probability = successes / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(probability * (1 - probability) / total + z * z / (4 * total**2))
        / denominator
    )
    return center - half, center + half


def quantile_noise(
    generator: np.random.Generator,
    samples: PositiveInt,
    blocks: PositiveInt,
    percentile: Annotated[float, Gt(0)],
) -> Array:
    rank = min(math.floor(percentile * samples) + 1, samples)
    uniforms = generator.beta(rank, samples + 1 - rank, size=(2, STUDIES, blocks))
    quantiles = np.exp(0.4 * ndtri(uniforms))
    # Identical path distributions have exactly zero expected paired difference.
    return quantiles[0] - quantiles[1]


def simulations() -> list[Record]:
    rows: list[Record] = []
    for blocks, samples, percentile in itertools.product(BLOCKS, SAMPLES, PERCENTILES):
        generator = np.random.default_rng(
            SEED + blocks + samples + round(percentile * 100)
        )
        ordinary = generator.normal(0, 0.15, size=(STUDIES, blocks))
        independent = quantile_noise(generator, samples, blocks, percentile) + ordinary
        clustered = (
            quantile_noise(generator, samples // 10, blocks, percentile) + ordinary
        )
        models = {"independent": independent, "clustered10": clustered}
        if samples == 10_000:
            models["asymmetric"] = (
                independent + generator.exponential(0.15, size=ordinary.shape) - 0.15
            )
            dependent = ordinary.copy()
            for block in range(1, blocks):
                dependent[:, block] = (
                    0.6 * dependent[:, block - 1] + 0.8 * ordinary[:, block]
                )
            models["ar1"] = independent - ordinary + dependent
            models["drift"] = independent + np.linspace(-0.15, 0.15, blocks)
        for model, pairs in models.items():
            primary, smallest, largest = stable_bounds(pairs)
            width = float(np.median(primary - pairs.mean(axis=1)))
            for effect in EFFECTS_MS:
                passed = largest + effect <= 1
                unstable = (smallest + effect <= 1) & ~passed
                low, high = wilson(int(passed.sum()), STUDIES)
                rows.append(
                    {
                        "blocks": blocks,
                        "samples": samples,
                        "percentile": percentile,
                        "model": model,
                        "effect_ms": effect,
                        "acceptance": float(passed.mean()),
                        "acceptance_mc_lower": low,
                        "acceptance_mc_upper": high,
                        "unstable": float(unstable.mean()),
                        "median_width_ms": width,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--reports", type=Path)
    mode.add_argument("--simulate-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    started = time.monotonic()
    if arguments.simulate_only:
        provenance: Record = {}
        runtime: list[Record] = []
        historical: list[Record] = []
        costs: list[Record] = []
    else:
        reports, provenance = load_reports(arguments.reports)
        runtime = accounting(reports)
        historical = retrospective(reports)
        costs = runtime_options(runtime)
    simulated = simulations()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        json.dump(
            {
                "label": "exploratory; excluded from acceptance",
                "program_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "python": platform.python_version(),
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "inputs": provenance,
                "seed": SEED,
                "studies": STUDIES,
                "draws": DRAWS,
                "runtime": runtime,
                "runtime_options": costs,
                "historical": historical,
                "simulations": simulated,
                "elapsed_seconds": time.monotonic() - started,
            },
            output,
            indent=2,
        )
        output.write("\n")


if __name__ == "__main__":
    main()

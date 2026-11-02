from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from client_query_cache._types import NonNegativeInt, PositiveInt

BOOTSTRAP_RESAMPLES = 2000
STARTUP_RUNS = 15
CONFIDENCE_TAIL = 0.025
ROOT = Path(__file__).resolve().parents[2]
TASKSET = "/usr/bin/taskset"
SETARCH = "/usr/bin/setarch"


@dataclass(frozen=True, slots=True)
class Run:
    label: str
    round_index: NonNegativeInt
    medians: dict[str, float]
    max_rss_kib: NonNegativeInt = 0
    extension_bytes: NonNegativeInt = 0


def child_environment(overlay: Path) -> dict[str, str]:
    environment = {
        "PYTHONPATH": f"{overlay}:{ROOT}",
        "PYTHONHASHSEED": "0",
        "PATH": "/usr/bin:/bin",
    }
    try:
        environment["LLVM_PROFILE_FILE"] = os.environ["LLVM_PROFILE_FILE"]
    except KeyError:
        pass
    return environment


def run_child(
    python: Path,
    overlay: Path,
    cpu: NonNegativeInt,
    output: Path,
    workloads: list[str],
) -> dict[str, object]:
    command = [
        SETARCH,
        "--addr-no-randomize",
        TASKSET,
        "-c",
        str(cpu),
        str(python),
        "-m",
        "research.native_build_profile.measure",
        "--output",
        str(output),
    ]
    if workloads:
        command += ["--workloads", *workloads]
    subprocess.run(  # noqa: S603 - Fixed argument list built from trusted paths.
        command,
        check=True,
        cwd=ROOT,
        env=child_environment(overlay),
        stdout=subprocess.DEVNULL,
    )
    report: dict[str, object] = json.loads(output.read_text(encoding="utf-8"))
    expected = overlay / "client_query_cache" / "_shared_index.abi3.so"
    if report["extension"] != str(expected):
        message = f"imported {report['extension']}, expected {expected}"
        raise SystemExit(message)
    return report


def startup_milliseconds(python: Path, overlay: Path, cpu: NonNegativeInt) -> float:
    samples: list[float] = []
    for _ in range(STARTUP_RUNS):
        started = time.perf_counter()
        subprocess.run(  # noqa: S603 - Fixed argument list built from trusted paths.
            [
                TASKSET,
                "-c",
                str(cpu),
                str(python),
                "-c",
                "import client_query_cache._shared_index",
            ],
            check=True,
            cwd=ROOT,
            env=child_environment(overlay),
        )
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def improvement_percent(baseline: float, candidate: float) -> float:
    return (baseline - candidate) / baseline * 100


def interval(samples: list[float], generator: random.Random) -> tuple[float, float]:
    means = sorted(
        statistics.median(generator.choices(samples, k=len(samples)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return (
        means[int(CONFIDENCE_TAIL * BOOTSTRAP_RESAMPLES)],
        means[int((1 - CONFIDENCE_TAIL) * BOOTSTRAP_RESAMPLES) - 1],
    )


def geometric_improvement(percentages: list[float]) -> float:
    mean_log_ratio = statistics.fmean(math.log1p(-value / 100) for value in percentages)
    return (1 - math.exp(mean_log_ratio)) * 100


def summarize(
    runs: list[Run], baseline: str, labels: list[str], seed: PositiveInt
) -> dict[str, object]:
    generator = random.Random(seed)
    by_round: dict[tuple[str, int], Run] = {(r.label, r.round_index): r for r in runs}
    rounds = sorted({run.round_index for run in runs})
    workloads = sorted(runs[0].medians)
    summary: dict[str, object] = {}
    for label in labels:
        per_workload: dict[str, dict[str, float]] = {}
        for workload in workloads:
            paired = [
                improvement_percent(
                    by_round[baseline, index].medians[workload],
                    by_round[label, index].medians[workload],
                )
                for index in rounds
            ]
            low, high = interval(paired, generator)
            per_workload[workload] = {
                "improvement_percent": statistics.median(paired),
                "low": low,
                "high": high,
            }
        geomeans = [
            geometric_improvement(
                [
                    improvement_percent(
                        by_round[baseline, index].medians[workload],
                        by_round[label, index].medians[workload],
                    )
                    for workload in workloads
                ]
            )
            for index in rounds
        ]
        low, high = interval(geomeans, generator)
        label_runs = [run for run in runs if run.label == label]
        baseline_runs = [run for run in runs if run.label == baseline]
        summary[label] = {
            "workloads": per_workload,
            "geomean": {
                "improvement_percent": statistics.median(geomeans),
                "low": low,
                "high": high,
            },
            "max_rss_change_percent": -improvement_percent(
                statistics.median(r.max_rss_kib for r in baseline_runs),
                statistics.median(r.max_rss_kib for r in label_runs),
            )
            if baseline_runs[0].max_rss_kib
            else 0.0,
            "extension_bytes": label_runs[0].extension_bytes,
        }
    return summary


def markdown(summary: dict[str, object], labels: list[str]) -> str:
    first = summary[labels[0]]
    assert isinstance(first, dict)
    workloads = sorted(first["workloads"])
    lines = [
        "| Workload | " + " | ".join(labels) + " |",
        "| --- | " + " | ".join("---:" for _ in labels) + " |",
    ]
    for workload in [*workloads, "geomean"]:
        cells = []
        for label in labels:
            entry = summary[label]
            assert isinstance(entry, dict)
            cell = (
                entry["geomean"]
                if workload == "geomean"
                else entry["workloads"][workload]
            )
            cells.append(
                f"{cell['improvement_percent']:+.1f} "
                f"[{cell['low']:+.1f}, {cell['high']:+.1f}]"
            )
        lines.append(f"| {workload} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alternate native builds in pinned subprocesses and compare them"
    )
    parser.add_argument("--overlay-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--workloads", nargs="*", default=[])
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    labels = [arguments.baseline, *arguments.labels]
    scratch = arguments.output.parent / f"{arguments.output.stem}-runs"
    scratch.mkdir(parents=True, exist_ok=True)
    generator = random.Random(arguments.seed)
    runs: list[Run] = []
    for round_index in range(arguments.rounds):
        order = labels.copy()
        generator.shuffle(order)
        for label in order:
            report = run_child(
                arguments.python,
                arguments.overlay_root / label,
                arguments.cpu,
                scratch / f"{label}-{round_index}.json",
                arguments.workloads,
            )
            timings = report["results"]
            assert isinstance(timings, dict)
            runs.append(
                Run(
                    label,
                    round_index,
                    {name: entry["median_ns"] for name, entry in timings.items()},
                    int(report["max_rss_kib"]),  # type: ignore[call-overload]
                    int(report["extension_bytes"]),  # type: ignore[call-overload]
                )
            )
        print(f"round {round_index} done: {order}", file=sys.stderr, flush=True)
    summary = summarize(runs, arguments.baseline, arguments.labels, arguments.seed)
    if arguments.startup:
        for label in labels:
            milliseconds = startup_milliseconds(
                arguments.python, arguments.overlay_root / label, arguments.cpu
            )
            entry = summary.get(label)
            if isinstance(entry, dict):
                entry["startup_ms"] = milliseconds
            else:
                summary[label] = {"startup_ms": milliseconds}
    arguments.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(markdown(summary, arguments.labels))


if __name__ == "__main__":
    main()

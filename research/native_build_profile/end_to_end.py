from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from itertools import product
from pathlib import Path

from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from research.native_build_profile.compare import (
    ROOT,
    TASKSET,
    Run,
    child_environment,
    markdown,
    summarize,
)

TOPOLOGY_LIMITS = ResourceLimits(cpus=2.0, memory="1g")


def run_case(python: Path, overlay: Path, cpu: int, uri: str, cell: str) -> float:
    case, profile = cell.split("/")
    completed = subprocess.run(  # noqa: S603 - Fixed argument list built from trusted paths.
        [
            TASKSET,
            "-c",
            str(cpu),
            str(python),
            "-m",
            "benchmarks.stream_cost.guard_workload",
            "--uri",
            uri,
            "--case",
            case,
            "--profile",
            profile,
        ],
        check=True,
        cwd=ROOT,
        env=child_environment(overlay),
        capture_output=True,
        text=True,
    )
    return float(json.loads(completed.stdout)["elapsed_seconds"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alternate native builds on the pull-request guard workload"
    )
    parser.add_argument("--overlay-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    labels = [arguments.baseline, *arguments.labels]
    cells = [
        f"{case}/{profile.name}" for case, profile in product(CASE_NAMES, PROFILES)
    ]
    generator = random.Random(arguments.seed)
    runs: list[Run] = []
    with IsolatedReplicaSet(TOPOLOGY_LIMITS) as replica_set:
        for round_index in range(arguments.rounds):
            order = labels.copy()
            generator.shuffle(order)
            for label in order:
                medians = {
                    cell: min(
                        run_case(
                            arguments.python,
                            arguments.overlay_root / label,
                            arguments.cpu,
                            replica_set.uri,
                            cell,
                        )
                        for _ in range(arguments.repeats)
                    )
                    for cell in cells
                }
                runs.append(Run(label, round_index, medians))
            print(f"round {round_index} done: {order}", file=sys.stderr, flush=True)
    summary = summarize(runs, arguments.baseline, arguments.labels, arguments.seed)
    arguments.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(markdown(summary, arguments.labels))


if __name__ == "__main__":
    main()

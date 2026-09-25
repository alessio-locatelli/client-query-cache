from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_report import (
    build_guard_report,
    measure_and_evaluate_case,
    measurement_error_report,
    report_to_json,
    report_to_summary,
)
from benchmarks.stream_cost.guard_runner import prepare_environment
from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from benchmarks.stream_cost.guard_report import GuardReport

_TOPOLOGY_LIMITS = ResourceLimits(cpus=2.0, memory="1g")


def run_guard(
    repo_root: Path,
    base_revision: str,
    head_revision: str,
    *,
    base_worktree: Path,
    head_worktree: Path,
) -> GuardReport:
    try:
        base_environment = prepare_environment(
            repo_root, base_revision, worktree_dir=base_worktree
        )
        head_environment = prepare_environment(
            repo_root,
            head_revision,
            worktree_dir=head_worktree,
            workload_source_root=base_environment.repo_root,
        )
    except BenchmarkSetupError as error:
        cases = tuple(
            measurement_error_report(case, profile.name, str(error))
            for case, profile in product(CASE_NAMES, PROFILES)
        )
        return build_guard_report(base_revision, head_revision, cases)
    with IsolatedReplicaSet(_TOPOLOGY_LIMITS) as replica_set:
        cases = tuple(
            measure_and_evaluate_case(
                base_environment, head_environment, replica_set.uri, case, profile.name
            )
            for case, profile in product(CASE_NAMES, PROFILES)
        )
    return build_guard_report(
        base_environment.revision, head_environment.revision, cases
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paired PR performance guard")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--head-revision", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = run_guard(
        arguments.repo_root,
        arguments.base_revision,
        arguments.head_revision,
        base_worktree=arguments.work_dir / "base",
        head_worktree=arguments.work_dir / "head",
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report_to_json(report), indent=2, sort_keys=True) + "\n"
    )
    print(report_to_summary(report))
    if not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()

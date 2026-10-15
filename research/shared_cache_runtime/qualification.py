"""Check baseline qualification evidence independently of numerical analysis."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from functools import cache
from pathlib import Path
from typing import cast

from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    validation_failure,
)
from client_query_cache._types import JsonDict, NonEmptyStr
from research.shared_cache_runtime.design import (
    PROGRAM,
    RESEARCH_PATHS,
    design_cells,
    planned_rows,
)

ENVIRONMENT = Path("reports/shared-worker-cache/v9/environment.json")


@cache
def committed_program_digest(revision: NonEmptyStr) -> NonEmptyStr:
    git = shutil.which("git")
    if git is None:
        raise ValueError(
            "git is required to verify the recorded research implementation"
        )
    committed = subprocess.check_output(  # noqa: S603 - Resolve git and pass the fixed research path without a shell.
        [git, "show", "--end-of-options", f"{revision}:{PROGRAM.as_posix()}"],
    )
    return hashlib.sha256(committed).hexdigest()


def require_complete(
    report: JsonDict, design_name: NonEmptyStr, registration: Registration
) -> None:
    if "wall_seconds" not in report:
        raise ValueError("qualification report did not finish container shutdown")
    environment = cast("JsonDict", report["environment"])
    if (
        environment["dirty_tree"]
        or environment["configuration_sha256"] != registration.digest
    ):
        raise ValueError(
            "qualification requires clean source and the registered configuration"
        )
    if report["program_sha256"] != committed_program_digest(
        cast("NonEmptyStr", environment["revision"])
    ):
        raise ValueError(
            "recorded research implementation differs from its Git revision"
        )
    if registration.raw["registration"] == 9:
        if "research_source_paths" not in report or report[
            "research_source_paths"
        ] != list(RESEARCH_PATHS):
            raise ValueError(
                "qualification did not record the required research source scope"
            )
        required_environment = json.loads(ENVIRONMENT.read_text(encoding="utf-8"))
        mismatches = [
            field
            for field, expected_value in required_environment.items()
            if environment[field] != expected_value
        ]
        if mismatches:
            raise ValueError("registered environment differs: " + ", ".join(mismatches))
    design = json.loads(
        Path(f"reports/shared-worker-cache/runtime/{design_name}.json").read_text(
            encoding="utf-8"
        )
    )
    expected = planned_rows(design_cells(registration, design))
    if report["planned"] != expected:
        raise ValueError("recorded schedule differs from the frozen design")
    keys = tuple(expected[0])
    actual = cast("list[JsonDict]", report["cells"])
    if Counter(tuple(row[key] for key in keys) for row in actual) != Counter(
        tuple(row[key] for key in keys) for row in expected
    ):
        raise ValueError("validation has missing, duplicate or unexpected windows")


def health_failures(
    cells: list[JsonDict], registration: Registration
) -> list[JsonDict]:
    return [
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
        for cell in cells
        if not cell["healthy"]
        or (reason := validation_failure(cell, registration)) is not None
    ]


def qualification_decision(report: JsonDict, registration: Registration) -> JsonDict:
    require_complete(report, "qualification", registration)
    failures = health_failures(cast("list[JsonDict]", report["cells"]), registration)
    return {
        "automated_checks_passed": not failures,
        "status": "failed" if failures else "pending-manual-review",
        "manual_review_required": [
            "baseline source compatibility",
            "physical host identity",
        ],
        "failures": failures,
    }

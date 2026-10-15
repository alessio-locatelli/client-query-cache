from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.shared_cache import run
from benchmarks.stream_cost.shared_cache.protocol import Registration
from client_query_cache._types import JsonDict, NonEmptyStr
from research.shared_cache_runtime import experiment, qualification

if TYPE_CHECKING:
    from faker import Faker

pytestmark = pytest.mark.unit

_ENVIRONMENT = json.loads(qualification.ENVIRONMENT.read_text(encoding="utf-8"))
_ENVIRONMENT_FIELDS = tuple(
    (field, child) if isinstance(value, dict) else (field,)
    for field, value in _ENVIRONMENT.items()
    for child in (tuple(value) if isinstance(value, dict) else (None,))
)


@pytest.fixture(scope="module")
def registration() -> Registration:
    return Registration.load(Path("reports/shared-worker-cache/v9/config.json"))


@pytest.fixture(scope="module")
def completed_report(registration: Registration) -> JsonDict:
    git = shutil.which("git")
    assert git is not None
    revision = subprocess.check_output([git, "rev-parse", "HEAD"], text=True).strip()  # noqa: S603 - Resolved git executable with fixed arguments and no shell.
    producer = subprocess.check_output(  # noqa: S603 - Read the committed research producer without a shell.
        [git, "show", f"{revision}:{experiment.PROGRAM}"]
    )
    design = json.loads(
        Path("reports/shared-worker-cache/runtime/qualification.json").read_text(
            encoding="utf-8"
        )
    )
    selected = experiment.design_cells(registration, design)
    planned = experiment.planned_rows(selected)
    cells = []
    for row, (_label, _registration, cell) in zip(planned, selected, strict=True):
        assert cell.rate is not None
        completed = math.ceil(cell.rate * cell.window_seconds)
        per_worker, remainder = divmod(completed, cell.workers)
        cells.append(
            {
                **row,
                "healthy": True,
                "offered": completed,
                "completed": completed,
                "completed_in_window": completed,
                "workers_measured": [
                    {
                        "loop": {"errors": 0, "overflow": 0, "outstanding_at_end": 0},
                        "outcomes": {
                            "misses": per_worker + (index < remainder),
                            "hits": 0,
                            "bypasses": 0,
                        },
                    }
                    for index in range(cell.workers)
                ],
                "populations": {
                    name: {
                        "sample_count": completed // (2 if cell.model == "mixed" else 1)
                    }
                    for name in ("request", "sync", "async")
                },
            }
        )
    return {
        "environment": {
            **_ENVIRONMENT,
            "revision": revision,
            "dirty_tree": False,
            "configuration_sha256": registration.digest,
            "available_memory_bytes": _ENVIRONMENT["total_memory_bytes"],
        },
        "program_sha256": hashlib.sha256(producer).hexdigest(),
        "research_source_paths": list(experiment.RESEARCH_PATHS),
        "planned": planned,
        "cells": cells,
        "wall_seconds": 2083.39,
    }


@pytest.fixture
def report(completed_report: JsonDict) -> JsonDict:
    return copy.deepcopy(completed_report)


def test_success_keeps_manual_compatibility_pending(
    report: JsonDict, registration: Registration
) -> None:
    environment = report["environment"]
    assert isinstance(environment, dict)
    available = environment["available_memory_bytes"]
    assert isinstance(available, int)
    environment["available_memory_bytes"] = available // 2

    decision = qualification.qualification_decision(report, registration)

    assert decision["automated_checks_passed"]
    assert decision["status"] == "pending-manual-review"
    assert decision["manual_review_required"] == [
        "baseline source compatibility",
        "physical host identity",
    ]
    assert not decision["failures"]
    assert "qualified" not in decision


def test_historical_investigation_keeps_its_recorded_environment(
    report: JsonDict,
) -> None:
    registration = Registration.load(Path("reports/shared-worker-cache/v8/config.json"))
    environment = report["environment"]
    planned = report["planned"]
    cells = report["cells"]
    assert isinstance(environment, dict)
    assert isinstance(planned, list)
    assert isinstance(cells, list)
    environment["configuration_sha256"] = registration.digest
    report.pop("research_source_paths")
    for row in (*planned, *cells):
        assert isinstance(row, dict)
        row["configuration_sha256"] = registration.digest

    assert qualification.qualification_decision(report, registration)[
        "automated_checks_passed"
    ]


@pytest.mark.parametrize(
    "field_path",
    _ENVIRONMENT_FIELDS,
    ids=[".".join(path) for path in _ENVIRONMENT_FIELDS],
)
def test_rejects_incompatible_registered_environment(
    report: JsonDict,
    registration: Registration,
    field_path: tuple[NonEmptyStr, ...],
    faker: Faker,
) -> None:
    changed = report["environment"]
    for field in field_path[:-1]:
        assert isinstance(changed, dict)
        changed = changed[field]
    assert isinstance(changed, dict)
    changed[field_path[-1]] = faker.sentence()

    with pytest.raises(
        ValueError, match="registered environment differs: " + field_path[0]
    ):
        qualification.qualification_decision(report, registration)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unfinished", "did not finish container shutdown"),
        ("dirty", "requires clean source"),
        ("configuration", "registered configuration"),
        ("producer", "implementation differs from its Git revision"),
        ("scope", "required research source scope"),
        ("legacy-scope", "required research source scope"),
        ("schedule", "schedule differs"),
        ("missing", "missing, duplicate or unexpected windows"),
        ("duplicate", "missing, duplicate or unexpected windows"),
    ],
    ids=[
        "unfinished",
        "dirty",
        "configuration",
        "producer",
        "scope",
        "legacy-scope",
        "schedule",
        "missing",
        "duplicate",
    ],
)
def test_rejects_invalid_evidence(
    report: JsonDict,
    registration: Registration,
    mutation: NonEmptyStr,
    message: NonEmptyStr,
    faker: Faker,
) -> None:
    environment = report["environment"]
    cells = report["cells"]
    assert isinstance(environment, dict)
    assert isinstance(cells, list)
    if mutation == "unfinished":
        report.pop("wall_seconds")
    elif mutation == "dirty":
        environment["dirty_tree"] = True
    elif mutation == "configuration":
        environment["configuration_sha256"] = faker.sha256()
    elif mutation == "producer":
        report["program_sha256"] = faker.sha256()
    elif mutation == "scope":
        report["research_source_paths"] = []
    elif mutation == "legacy-scope":
        report.pop("research_source_paths")
    elif mutation == "schedule":
        report["planned"] = []
    elif mutation == "missing":
        cells.pop()
    else:
        cells.append(copy.deepcopy(cells[0]))

    with pytest.raises(ValueError, match=message):
        qualification.qualification_decision(report, registration)


@pytest.mark.parametrize("setup_failure", [True, False], ids=["setup", "traffic"])
def test_records_qualification_failure(
    report: JsonDict, registration: Registration, setup_failure: bool, faker: Faker
) -> None:
    cells = report["cells"]
    assert isinstance(cells, list)
    cell = cells[0]
    assert isinstance(cell, dict)
    if setup_failure:
        cell["healthy"] = False
        cell["failure"] = faker.sentence()
    else:
        cell["completed_in_window"] = 0

    decision = qualification.qualification_decision(report, registration)

    assert not decision["automated_checks_passed"]
    assert decision["status"] == "failed"
    failures = decision["failures"]
    assert isinstance(failures, list)
    assert len(failures) == 1


def test_provenance_check_requires_git(
    monkeypatch: pytest.MonkeyPatch, faker: Faker
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ValueError, match="git is required"):
        qualification.committed_program_digest(faker.sha1())


@pytest.fixture
def source_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)  # noqa: S603 - Initialize only the disposable test repository.
    for name in ("experiment.py", "analysis.py"):
        path = tmp_path / "research/shared_cache_runtime" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# committed producer or analyzer\n", encoding="utf-8")
    subprocess.run([git, "-C", str(tmp_path), "add", "."], check=True)  # noqa: S603 - Stage only the disposable test files.
    subprocess.run(  # noqa: S603 - Commit the disposable fixture with explicit test identity and no hooks.
        [
            git,
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Qualification test",
            "-c",
            "user.email=qualification@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "Fixture",
        ],
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run, "native_extension", dict)
    return tmp_path


@pytest.mark.parametrize(
    "relative_path",
    [
        "research/shared_cache_runtime/experiment.py",
        "research/shared_cache_runtime/analysis.py",
        "scripts/analyze_shared_cache_runtime.py",
    ],
    ids=["producer", "analyzer", "numerical-helper"],
)
def test_research_tool_changes_mark_source_dirty(
    source_repository: Path, registration: Registration, relative_path: NonEmptyStr
) -> None:
    path = source_repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# uncommitted implementation\n", encoding="utf-8")

    metadata = run.environment(
        registration, extra_source_paths=experiment.RESEARCH_PATHS
    )

    assert metadata["dirty_tree"]

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost import guard_runner
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_runner import (
    RevisionEnvironment,
    measure_paired_case,
    prepare_environment,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

pytestmark = pytest.mark.unit

_SOURCE_FILE_NAMES = ("errors.py", "generators.py", "guard_workload.py")


def _write_workload_sources(root: Path, *, content: str) -> None:
    target_dir = root / "benchmarks" / "stream_cost"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in _SOURCE_FILE_NAMES:
        (target_dir / name).write_text(content)


def _write_python_executable(worktree_dir: Path) -> Path:
    python_executable = worktree_dir / ".venv" / "bin" / "python"
    python_executable.parent.mkdir(parents=True, exist_ok=True)
    python_executable.write_text("")
    return python_executable


def _environment(
    tmp_path: Path,
    *,
    revision: str,
    python_version: str,
    workload_digest: str,
) -> RevisionEnvironment:
    return RevisionEnvironment(
        revision=revision,
        repo_root=tmp_path / revision,
        python_executable=tmp_path / revision / "python",
        python_version=python_version,
        workload_digest=workload_digest,
    )


def _revision_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    worktree_dir: Path,
    revision: str,
    fault: str,
    selected_python: str,
) -> str:
    if command[:2] == ["git", "rev-parse"]:
        if command[-1] == "HEAD":
            assert cwd == worktree_dir
            if fault == "checkout_mismatch":
                return "wrong-revision\n"
        return revision + "\n"
    if command[:3] == ["git", "worktree", "add"]:
        if fault == "worktree_add_failure":
            raise subprocess.CalledProcessError(1, command, stderr="add failed")
        return ""
    if Path(command[0]).name == "uv":
        if fault == "uv_sync_failure":
            raise subprocess.CalledProcessError(1, command, stderr="sync failed")
        expected_command = ["/usr/bin/uv", "sync", "--locked", "--all-groups"]
        expected_command.extend(("--python", selected_python))
        assert command == expected_command
        return ""
    return "3.14.6\n"


@pytest.fixture
def revision_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Path, str, str, str], None]:
    def install(
        worktree_dir: Path, revision: str, fault: str, selected_python: str
    ) -> None:
        monkeypatch.setattr(
            guard_runner,
            "_run",
            partial(
                _revision_command,
                worktree_dir=worktree_dir,
                revision=revision,
                fault=fault,
                selected_python=selected_python,
            ),
        )
        monkeypatch.setattr(
            shutil,
            "which",
            lambda _name: None if fault == "missing_uv" else "/usr/bin/uv",
        )

    return install


def test_run_returns_the_subprocess_stdout() -> None:
    output = guard_runner._run([sys.executable, "-c", "print('hello')"])

    assert output == "hello\n"


@pytest.mark.parametrize(
    "selected_python",
    ["3.14.6", "3.14.7"],
    ids=["unchanged-interpreter", "proposed-interpreter"],
)
def test_prepare_environment_succeeds(
    tmp_path: Path,
    revision_commands: Callable[[Path, str, str, str], None],
    selected_python: str,
) -> None:
    repo_root = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(repo_root, content="original")
    _write_python_executable(worktree_dir)
    _write_workload_sources(worktree_dir, content="original")

    revision_commands(worktree_dir, "abc123", "", selected_python)

    environment = prepare_environment(
        repo_root, "main", worktree_dir=worktree_dir, python_version=selected_python
    )

    assert environment.revision == "abc123"
    assert environment.python_version == "3.14.6"
    assert environment.python_executable == worktree_dir / ".venv" / "bin" / "python"


def test_prepare_environment_copies_base_workload_source(
    tmp_path: Path, revision_commands: Callable[[Path, str, str, str], None]
) -> None:
    base_root = tmp_path / "base"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(base_root, content="base-definition")
    _write_python_executable(worktree_dir)
    _write_workload_sources(worktree_dir, content="head-definition")

    revision_commands(worktree_dir, "def456", "", "3.14.6")

    environment = prepare_environment(
        base_root,
        "main",
        worktree_dir=worktree_dir,
        workload_source_root=base_root,
        python_version="3.14.6",
    )

    copied = (
        worktree_dir / "benchmarks" / "stream_cost" / "guard_workload.py"
    ).read_text()
    assert copied == "base-definition"
    assert environment.workload_digest == guard_runner._workload_digest(base_root)


@pytest.mark.parametrize(
    ("fault", "match"),
    [
        ("checkout_mismatch", "checked out"),
        ("worktree_add_failure", "could not add a worktree"),
        ("missing_uv", "uv is required"),
        ("uv_sync_failure", "could not sync locked dependencies"),
        ("missing_workload_definition", "does not exist on this revision"),
        ("missing_interpreter", "no interpreter was created"),
    ],
    ids=[
        "checkout-mismatch",
        "worktree-failure",
        "missing-uv",
        "sync-failure",
        "missing-workload",
        "missing-interpreter",
    ],
)
def test_prepare_environment_reports_setup_faults(
    tmp_path: Path,
    revision_commands: Callable[[Path, str, str, str], None],
    *,
    fault: str,
    match: str,
) -> None:
    repo_root = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(repo_root, content="original")
    if fault != "missing_interpreter":
        _write_python_executable(worktree_dir)
    if fault != "missing_workload_definition":
        _write_workload_sources(worktree_dir, content="original")

    revision_commands(worktree_dir, "abc123", fault, "3.14.7")

    with pytest.raises(BenchmarkSetupError, match=match):
        prepare_environment(
            repo_root, "main", worktree_dir=worktree_dir, python_version="3.14.7"
        )


@pytest.mark.parametrize(
    ("head_python_version", "head_workload_digest", "match"),
    [
        ("3.13.0", "digest", "different Python versions"),
        ("3.14.6", "head-digest", "same guard workload definition"),
    ],
    ids=["interpreter-mismatch", "workload-mismatch"],
)
def test_measure_paired_case_detects_environment_mismatch(
    tmp_path: Path, head_python_version: str, head_workload_digest: str, match: str
) -> None:
    base = _environment(
        tmp_path, revision="base", python_version="3.14.6", workload_digest="digest"
    )
    head = _environment(
        tmp_path,
        revision="head",
        python_version=head_python_version,
        workload_digest=head_workload_digest,
    )
    with pytest.raises(BenchmarkSetupError, match=match):
        measure_paired_case(base, head, "mongodb://unused", "sync_hit", "small")


def test_measure_paired_case_reports_outcome_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _environment(
        tmp_path, revision="base", python_version="3.14.6", workload_digest="digest"
    )
    head = _environment(
        tmp_path, revision="head", python_version="3.14.6", workload_digest="digest"
    )

    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        del cwd
        raise subprocess.CalledProcessError(1, command, stderr="wrong data")

    monkeypatch.setattr(guard_runner, "_run", fake_run)

    with pytest.raises(BenchmarkSetupError, match="wrong data"):
        measure_paired_case(base, head, "mongodb://unused", "sync_hit", "small")


def test_measure_paired_case_alternates_and_attributes_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _environment(
        tmp_path, revision="base", python_version="3.14.6", workload_digest="digest"
    )
    head = _environment(
        tmp_path, revision="head", python_version="3.14.6", workload_digest="digest"
    )
    elapsed_seconds_by_python = {
        str(base.python_executable): 0.01,
        str(head.python_executable): 0.02,
    }
    observed_order: list[str] = []

    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        del cwd
        python_executable = command[0]
        observed_order.append(python_executable)
        return f'{{"elapsed_seconds": {elapsed_seconds_by_python[python_executable]}}}'

    monkeypatch.setattr(guard_runner, "_run", fake_run)

    measurement = measure_paired_case(
        base, head, "mongodb://unused", "sync_hit", "small", block_pairs=4
    )

    assert measurement.base_seconds == (0.01, 0.01, 0.01, 0.01)
    assert measurement.head_seconds == (0.02, 0.02, 0.02, 0.02)
    assert observed_order == [
        str(base.python_executable),
        str(head.python_executable),
        str(head.python_executable),
        str(base.python_executable),
        str(base.python_executable),
        str(head.python_executable),
        str(head.python_executable),
        str(base.python_executable),
    ]


@pytest.mark.parametrize(
    "available", [True, False], ids=["head-selection", "missing-selection"]
)
def test_revision_python_version_reads_requested_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, available: bool
) -> None:
    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        assert command == ["git", "show", "proposed:.python-version"]
        assert cwd == tmp_path
        if not available:
            raise subprocess.CalledProcessError(1, command, stderr="missing selection")
        return "3.14.7\n"

    monkeypatch.setattr(guard_runner, "_run", fake_run)
    if available:
        assert guard_runner.revision_python_version(tmp_path, "proposed") == "3.14.7"
    else:
        with pytest.raises(
            BenchmarkSetupError,
            match=r"could not read Python selection.*missing selection",
        ):
            guard_runner.revision_python_version(tmp_path, "proposed")

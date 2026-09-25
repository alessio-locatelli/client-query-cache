from __future__ import annotations

import shutil
import subprocess
import sys
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
    from collections.abc import Sequence

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


def test_run_returns_the_subprocess_stdout() -> None:
    output = guard_runner._run([sys.executable, "-c", "print('hello')"])

    assert output == "hello\n"


def test_prepare_environment_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(repo_root, content="original")
    _write_python_executable(worktree_dir)
    _write_workload_sources(worktree_dir, content="original")

    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        if command[:2] == ["git", "rev-parse"] and command[-1] == "HEAD":
            assert cwd == worktree_dir
            return "abc123\n"
        if command[:2] == ["git", "rev-parse"]:
            return "abc123\n"
        if command[:3] == ["git", "worktree", "add"]:
            return ""
        if Path(command[0]).name == "uv":
            return ""
        if "-c" in command:
            return "3.14.6\n"
        message = f"unexpected command {command}"  # pragma: no cover
        raise AssertionError(message)  # pragma: no cover

    monkeypatch.setattr(guard_runner, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")

    environment = prepare_environment(repo_root, "main", worktree_dir=worktree_dir)

    assert environment.revision == "abc123"
    assert environment.python_version == "3.14.6"
    assert environment.python_executable == worktree_dir / ".venv" / "bin" / "python"


def test_prepare_environment_copies_base_workload_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_root = tmp_path / "base"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(base_root, content="base-definition")
    _write_python_executable(worktree_dir)
    _write_workload_sources(worktree_dir, content="head-definition")

    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        del cwd
        if command[:2] == ["git", "rev-parse"]:
            return "def456\n"
        if command[:3] == ["git", "worktree", "add"]:
            return ""
        if Path(command[0]).name == "uv":
            return ""
        if "-c" in command:
            return "3.14.6\n"
        message = f"unexpected command {command}"  # pragma: no cover
        raise AssertionError(message)  # pragma: no cover

    monkeypatch.setattr(guard_runner, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")

    environment = prepare_environment(
        base_root,
        "main",
        worktree_dir=worktree_dir,
        workload_source_root=base_root,
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
)
def test_prepare_environment_reports_setup_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fault: str, match: str
) -> None:
    repo_root = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    _write_workload_sources(repo_root, content="original")
    if fault != "missing_interpreter":
        _write_python_executable(worktree_dir)
    if fault != "missing_workload_definition":
        _write_workload_sources(worktree_dir, content="original")

    def fake_run(command: Sequence[str], *, cwd: Path | None = None) -> str:
        del cwd
        if command[:3] == ["git", "worktree", "add"]:
            if fault == "worktree_add_failure":
                raise subprocess.CalledProcessError(1, command, stderr="add failed")
            return ""
        if command[:2] == ["git", "rev-parse"] and command[-1] == "HEAD":
            return "wrong-revision\n" if fault == "checkout_mismatch" else "abc123\n"
        if command[:2] == ["git", "rev-parse"]:
            return "abc123\n"
        if Path(command[0]).name == "uv":
            if fault == "uv_sync_failure":
                raise subprocess.CalledProcessError(1, command, stderr="sync failed")
            return ""
        if "-c" in command:
            return "3.14.6\n"
        message = f"unexpected command {command}"  # pragma: no cover
        raise AssertionError(message)  # pragma: no cover

    monkeypatch.setattr(guard_runner, "_run", fake_run)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda _name: None if fault == "missing_uv" else "/usr/bin/uv",
    )

    with pytest.raises(BenchmarkSetupError, match=match):
        prepare_environment(repo_root, "main", worktree_dir=worktree_dir)


@pytest.mark.parametrize(
    ("head_python_version", "head_workload_digest", "match"),
    [
        ("3.13.0", "digest", "different Python versions"),
        ("3.14.6", "head-digest", "same guard workload definition"),
    ],
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

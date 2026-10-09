from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_decision import BLOCK_PAIRS
from client_query_cache._types import PositiveInt

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_WORKLOAD_SOURCE_FILES = ("errors.py", "generators.py", "guard_workload.py")


def _run(command: Sequence[str], *, cwd: Path | None = None) -> str:
    # Python 3.14: https://docs.python.org/3.14/library/subprocess.html
    # check=True: The default is false. We override it because failed commands must
    # abort assembly or benchmark preparation.
    completed_process = subprocess.run(  # noqa: S603 - fixed argument lists built from trusted values
        list(command), cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed_process.stdout


def _resolve_revision(repo_root: Path, revision: str) -> str:
    return _run(["git", "rev-parse", revision], cwd=repo_root).strip()


def revision_python_version(repo_root: Path, revision: str) -> str:
    try:
        return _run(
            ["git", "show", f"{revision}:.python-version"], cwd=repo_root
        ).strip()
    except subprocess.CalledProcessError as error:
        message = (
            f"could not read Python selection for revision {revision}: {error.stderr}"
        )
        raise BenchmarkSetupError(message) from None


def _workload_digest(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for name in _WORKLOAD_SOURCE_FILES:
        path = repo_root / "benchmarks" / "stream_cost" / name
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            message = f"{path} does not exist on this revision"
            raise BenchmarkSetupError(message) from None
        digest.update(name.encode())
        digest.update(content)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RevisionEnvironment:
    revision: str
    repo_root: Path
    python_executable: Path
    python_version: str
    workload_digest: str


def prepare_environment(
    repo_root: Path,
    revision: str,
    *,
    worktree_dir: Path,
    workload_source_root: Path | None = None,
    python_version: str,
) -> RevisionEnvironment:
    resolved = _resolve_revision(repo_root, revision)
    try:
        _run(
            # Git 2.55.0: https://git-scm.com/docs/git-worktree
            # --detach: The default is attaching to a matching branch if one resolves,
            # otherwise detaching. We override it because benchmark worktrees must
            # remain detached even if a branch name matches this object ID.
            ["git", "worktree", "add", "--detach", str(worktree_dir), resolved],
            cwd=repo_root,
        )
    except subprocess.CalledProcessError as error:
        message = f"could not add a worktree for revision {resolved}: {error.stderr}"
        raise BenchmarkSetupError(message) from None
    checked_out = _resolve_revision(worktree_dir, "HEAD")
    if checked_out != resolved:
        message = (
            f"worktree {worktree_dir} checked out {checked_out}, not the "
            f"requested revision {resolved}"
        )
        raise BenchmarkSetupError(message)
    if workload_source_root is not None:
        target_dir = worktree_dir / "benchmarks" / "stream_cost"
        for name in _WORKLOAD_SOURCE_FILES:
            shutil.copyfile(
                workload_source_root / "benchmarks" / "stream_cost" / name,
                target_dir / name,
            )
    uv_path = shutil.which("uv")
    if uv_path is None:
        message = "uv is required to install a revision's locked dependencies"
        raise BenchmarkSetupError(message)
    try:
        command = [
            uv_path,
            "sync",
            # uv 0.12.9 locally / 0.12.19 in CI: https://docs.astral.sh/uv/reference/cli/
            # --locked: The default is inherited UV_LOCKED, otherwise unlocked
            # resolution. We override it because this standalone command must validate
            # the committed lockfile.
            # --all-groups: The default is project default groups (dev). We override it
            # because revision validation needs documentation tools too.
            "--locked",
            "--all-groups",
            "--python",
            python_version,
        ]
        _run(command, cwd=worktree_dir)
    except subprocess.CalledProcessError as error:
        message = (
            f"could not sync locked dependencies for revision {resolved}: "
            f"{error.stderr}"
        )
        raise BenchmarkSetupError(message) from None
    python_executable = worktree_dir / ".venv" / "bin" / "python"
    if not python_executable.exists():
        message = f"no interpreter was created for revision {resolved}"
        raise BenchmarkSetupError(message)
    python_version = _run(
        [
            str(python_executable),
            "-c",
            "import platform; print(platform.python_version())",
        ]
    ).strip()
    return RevisionEnvironment(
        revision=resolved,
        repo_root=worktree_dir,
        python_executable=python_executable,
        python_version=python_version,
        workload_digest=_workload_digest(worktree_dir),
    )


def _run_case_subprocess(
    environment: RevisionEnvironment, uri: str, case: str, profile: str
) -> float:
    try:
        output = _run(
            [
                str(environment.python_executable),
                "-m",
                "benchmarks.stream_cost.guard_workload",
                "--uri",
                uri,
                "--case",
                case,
                "--profile",
                profile,
            ],
            cwd=environment.repo_root,
        )
    except subprocess.CalledProcessError as error:
        message = (
            f"revision {environment.revision} could not measure case "
            f"{case!r}/{profile!r}: {error.stderr.strip()}"
        )
        raise BenchmarkSetupError(message) from None
    return float(json.loads(output)["elapsed_seconds"])


@dataclass(frozen=True, slots=True)
class PairedCaseMeasurement:
    case: str
    profile: str
    base_seconds: tuple[float, ...]
    head_seconds: tuple[float, ...]


def measure_paired_case(
    base_environment: RevisionEnvironment,
    head_environment: RevisionEnvironment,
    uri: str,
    case: str,
    profile: str,
    *,
    block_pairs: PositiveInt = BLOCK_PAIRS,
) -> PairedCaseMeasurement:
    if base_environment.python_version != head_environment.python_version:
        message = (
            "base and head environments use different Python versions: "
            f"{base_environment.python_version} vs {head_environment.python_version}"
        )
        raise BenchmarkSetupError(message)
    if base_environment.workload_digest != head_environment.workload_digest:
        message = (
            "base and head environments do not run the same guard workload definition"
        )
        raise BenchmarkSetupError(message)
    base_seconds: list[float] = []
    head_seconds: list[float] = []
    for index in range(block_pairs):
        base_first = index % 2 == 0
        first_environment, second_environment = (
            (base_environment, head_environment)
            if base_first
            else (head_environment, base_environment)
        )
        first_seconds = _run_case_subprocess(first_environment, uri, case, profile)
        second_seconds = _run_case_subprocess(second_environment, uri, case, profile)
        if base_first:
            base_seconds.append(first_seconds)
            head_seconds.append(second_seconds)
        else:
            head_seconds.append(first_seconds)
            base_seconds.append(second_seconds)
    return PairedCaseMeasurement(
        case=case,
        profile=profile,
        base_seconds=tuple(base_seconds),
        head_seconds=tuple(head_seconds),
    )

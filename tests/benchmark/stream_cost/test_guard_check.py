from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from benchmarks.stream_cost import guard_check
from benchmarks.stream_cost.guard_decision import Decision
from benchmarks.stream_cost.guard_report import CaseReport, build_guard_report
from benchmarks.stream_cost.guard_runner import RevisionEnvironment
from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _environment(tmp_path: Path, revision: str) -> RevisionEnvironment:
    return RevisionEnvironment(
        revision=revision,
        repo_root=tmp_path / revision,
        python_executable=tmp_path / revision / "python",
        python_version="3.14.6",
        workload_digest="digest",
    )


def _case_report(case: str, profile: str) -> CaseReport:
    return CaseReport(
        case=case,
        profile=profile,
        decision=Decision.WITHIN_BOUNDARY,
        reason="upper stability bound stays within the 30% boundary",
        base_seconds=(0.02,) * 7,
        head_seconds=(0.021,) * 7,
        base_median_seconds=0.02,
        head_median_seconds=0.021,
        median_ratio=1.05,
        lower_ratio=1.0,
        upper_ratio=1.1,
    )


def test_run_guard_measures_every_case_and_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_environment = _environment(tmp_path, "abc123")
    head_environment = _environment(tmp_path, "def456")
    prepared = {base_environment.revision: base_environment, "head": head_environment}
    replica_set = MagicMock()
    replica_set.__enter__ = MagicMock(return_value=MagicMock(uri="mongodb://unused"))
    replica_set.__exit__ = MagicMock(return_value=False)
    observed_cases: list[tuple[str, str]] = []

    def fake_prepare_environment(
        _repo_root: Path,
        revision: str,
        *,
        worktree_dir: Path,
        workload_source_root: Path | None = None,
    ) -> RevisionEnvironment:
        del worktree_dir, workload_source_root
        return prepared["abc123"] if revision == "abc123" else prepared["head"]

    def fake_measure_and_evaluate_case(
        _base: RevisionEnvironment,
        _head: RevisionEnvironment,
        _uri: str,
        case: str,
        profile: str,
    ) -> CaseReport:
        observed_cases.append((case, profile))
        return _case_report(case, profile)

    monkeypatch.setattr(guard_check, "prepare_environment", fake_prepare_environment)
    monkeypatch.setattr(guard_check, "IsolatedReplicaSet", lambda _limits: replica_set)
    monkeypatch.setattr(
        guard_check, "measure_and_evaluate_case", fake_measure_and_evaluate_case
    )

    report = guard_check.run_guard(
        tmp_path,
        "abc123",
        "head",
        base_worktree=tmp_path / "base-worktree",
        head_worktree=tmp_path / "head-worktree",
    )

    assert report.base_revision == "abc123"
    assert report.head_revision == "def456"
    assert report.passed is True
    assert sorted(observed_cases) == sorted(
        (case, profile.name) for case in CASE_NAMES for profile in PROFILES
    )


@pytest.mark.parametrize(("passed", "expects_exit"), [(True, False), (False, True)])
def test_main_writes_report_and_exits_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    passed: bool,
    expects_exit: bool,
) -> None:
    output = tmp_path / "nested" / "guard-report.json"
    decision = Decision.WITHIN_BOUNDARY if passed else Decision.REGRESSION
    report = build_guard_report(
        "abc123",
        "def456",
        (
            CaseReport(
                case="sync_hit",
                profile="small",
                decision=decision,
                reason="reason",
                base_seconds=(0.02,) * 7,
                head_seconds=(0.021,) * 7,
                base_median_seconds=0.02,
                head_median_seconds=0.021,
                median_ratio=1.05,
                lower_ratio=1.0,
                upper_ratio=1.1,
            ),
        ),
    )
    monkeypatch.setattr(guard_check, "run_guard", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guard_check",
            "--repo-root",
            str(tmp_path),
            "--base-revision",
            "abc123",
            "--head-revision",
            "def456",
            "--work-dir",
            str(tmp_path / "work"),
            "--output",
            str(output),
        ],
    )

    if expects_exit:
        with pytest.raises(SystemExit) as exit_info:
            guard_check.main()
        assert exit_info.value.code == 1
    else:
        guard_check.main()

    written = json.loads(output.read_text())
    assert written["passed"] is passed
    assert "abc123" in capsys.readouterr().out

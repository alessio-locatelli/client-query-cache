from __future__ import annotations

import io
import sys

import pytest

from benchmarks.stream_cost import guard_scope
from benchmarks.stream_cost.guard_scope import changed_files_require_guard

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (("src/mongo_client_cache/synchronous/manager.py",), True),
        (("benchmarks/stream_cost/guard_workload.py",), True),
        (("pyproject.toml",), True),
        (("uv.lock",), True),
        ((".github/workflows/pr-performance-guard.yml",), True),
        (("docs/stream-cost-benchmarks.md", "README.md"), False),
        ((), False),
    ],
)
def test_changed_files_require_guard(paths: tuple[str, ...], *, expected: bool) -> None:
    assert changed_files_require_guard(paths) is expected


def test_main_prints_true_for_relevant_changes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("src/module.py\n\n"))

    guard_scope.main()

    assert capsys.readouterr().out == "true\n"


def test_main_prints_false_for_unrelated_changes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("README.md\n"))

    guard_scope.main()

    assert capsys.readouterr().out == "false\n"

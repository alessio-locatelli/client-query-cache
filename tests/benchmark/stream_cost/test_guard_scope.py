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
        (("src/client_query_cache/synchronous/manager.py",), True),
        (("benchmarks/stream_cost/guard_workload.py",), True),
        (("pyproject.toml",), True),
        (("uv.lock",), True),
        ((".github/workflows/test.yml",), True),
        (("docs/stream-cost-benchmarks.md", "README.md"), False),
        ((), False),
    ],
)
def test_changed_files_require_guard(paths: tuple[str, ...], *, expected: bool) -> None:
    assert changed_files_require_guard(paths) is expected


@pytest.mark.parametrize(
    ("stdin_text", "expected_stdout"),
    [
        ("src/module.py\n\n", "true\n"),
        ("README.md\n", "false\n"),
    ],
)
def test_main_prints_the_guard_requirement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin_text: str,
    expected_stdout: str,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

    guard_scope.main()

    assert capsys.readouterr().out == expected_stdout

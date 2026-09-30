from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("changed_paths", "expected_stdout"),
    [
        (("src/client_query_cache/core.py",), "python=true\nformat=false\n"),
        (("README.md",), "python=false\nformat=true\n"),
        ((".prettierrc",), "python=false\nformat=true\n"),
        (("notes.txt",), "python=false\nformat=false\n"),
        (("justfile",), "python=true\nformat=false\n"),
        ((".github/workflows/test.yml",), "python=true\nformat=true\n"),
        (("README.md", "src/client_query_cache/core.py"), "python=true\nformat=true\n"),
    ],
    ids=[
        "python",
        "documentation",
        "prettier-config",
        "unrelated",
        "justfile",
        "workflow",
        "mixed",
    ],
)
def test_ci_scope_selects_validation_tiers(
    changed_paths: tuple[str, ...], expected_stdout: str
) -> None:
    completed = subprocess.run(
        (sys.executable, "-m", "scripts.ci_scope"),
        input=b"\0".join(path.encode() for path in changed_paths) + b"\0",
        capture_output=True,
        check=True,
    )

    assert completed.stdout.decode() == expected_stdout

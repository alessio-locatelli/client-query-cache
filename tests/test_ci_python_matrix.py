from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def matrix_checkout(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.14.6"\n'
    )
    (tmp_path / ".python-version").write_text(request.param, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("matrix_checkout", "expected_versions"),
    [
        pytest.param("3.14.6", ("3.14.6",), id="exact-minimum"),
        pytest.param("3.14.7", ("3.14.6", "3.14.7"), id="later-patch"),
        pytest.param("3.15.0", ("3.14.6", "3.15.0"), id="next-release"),
        pytest.param("3.16.0", ("3.14.6", "3.15", "3.16.0"), id="intermediate-release"),
    ],
    indirect=("matrix_checkout",),
)
def test_python_matrix_retains_exact_minimum(
    matrix_checkout: Path, expected_versions: tuple[str, ...]
) -> None:
    completed = subprocess.run(
        (sys.executable, "-m", "scripts.ci_python_matrix"),
        cwd=matrix_checkout,
        env=os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        check=True,
        text=True,
    )
    assert (
        tuple(json.loads(completed.stdout.removeprefix("versions=")))
        == expected_versions
    )

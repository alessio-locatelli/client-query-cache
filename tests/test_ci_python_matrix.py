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
    minimum, classifiers, selected = request.param
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nrequires-python = ">={minimum}"\n'
        f"classifiers = {json.dumps(classifiers)}\n",
        encoding="utf-8",
    )
    (tmp_path / ".python-version").write_text(selected, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("matrix_checkout", "expected_versions"),
    [
        pytest.param(
            ("3.14", ("Programming Language :: Python :: 3.14",), "3.14.0"),
            ("3.14.0",),
            id="exact-minimum",
        ),
        pytest.param(
            ("3.14", ("Programming Language :: Python :: 3.15",), "3.14.0"),
            ("3.14.0", "3.15"),
            id="exact-minimum-with-next-release",
        ),
        pytest.param(
            (
                "3.14",
                (
                    "Programming Language :: Python :: 3.14",
                    "Programming Language :: Python :: 3.15",
                ),
                "3.14.6",
            ),
            ("3.14.0", "3.15", "3.14.6"),
            id="classified-next-release",
        ),
        pytest.param(
            ("3.14", ("Programming Language :: Python :: 3.15",), "3.15.0"),
            ("3.14.0", "3.15.0"),
            id="development-next-release",
        ),
        pytest.param(
            ("3.14", ("Programming Language :: Python :: 3.15",), "3.16.0"),
            ("3.14.0", "3.15", "3.16.0"),
            id="development-beyond-classifiers",
        ),
        pytest.param(
            (
                "3.14",
                (
                    "Programming Language :: Python :: 3.16",
                    "Programming Language :: Python :: 3.14",
                ),
                "3.14.6",
            ),
            ("3.14.0", "3.15", "3.16", "3.14.6"),
            id="highest-classifier-with-intermediate-release",
        ),
        pytest.param(
            ("3.14.6", (), "3.14.6"),
            ("3.14.6",),
            id="explicit-exact-minimum",
        ),
        pytest.param(
            ("3.14.6", (), "3.14.7"),
            ("3.14.6", "3.14.7"),
            id="explicit-minimum-later-patch",
        ),
        pytest.param(
            ("3.14.6", (), "3.15.0"),
            ("3.14.6", "3.15.0"),
            id="explicit-minimum-next-release",
        ),
        pytest.param(
            ("3.14.6", (), "3.16.0"),
            ("3.14.6", "3.15", "3.16.0"),
            id="explicit-minimum-intermediate-release",
        ),
        pytest.param(
            (
                "3.14",
                (
                    "Programming Language :: Python",
                    "Programming Language :: Python :: 3",
                ),
                "3.14.6",
            ),
            ("3.14.0", "3.14.6"),
            id="general-classifiers",
        ),
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

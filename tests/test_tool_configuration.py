from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TypedDict

import pytest

pytestmark = pytest.mark.unit


class ToolProbe(TypedDict):
    completed: subprocess.CompletedProcess[str]
    diagnostic: str | None


@pytest.fixture
def tool_probe(tmp_path: Path, request: pytest.FixtureRequest) -> ToolProbe:
    tool, source, diagnostic = request.param
    source_path = tmp_path / "probe.py"
    source_path.write_text(source)
    project = Path(__file__).resolve().parents[1]
    arguments = (
        ("--config-file", str(project / "mypy.ini"))
        if tool == "mypy"
        else (
            "--settings",
            str(project / "pyproject.toml"),
            "--pythonpath",
            str(tmp_path),
        )
    )
    completed = subprocess.run(  # noqa: S603 - Fixed tool names and fixture inputs.
        (sys.executable, "-m", tool, *arguments, str(source_path)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,  # Required by Ruff; failing probes must return their diagnostics.
    )
    return {"completed": completed, "diagnostic": diagnostic}


@pytest.mark.parametrize(
    "tool_probe",
    [
        pytest.param(
            ("mypy", "def consume(value: str) -> str:\n    return value\n", None),
            id="mypy-valid",
        ),
        pytest.param(
            ("mypy", "def consume(value):\n    return value\n", "[no-untyped-def]"),
            id="mypy-untyped-definition",
        ),
        pytest.param(
            (
                "mypy",
                "def consume(value: str):\n    return value\n",
                "[no-untyped-def]",
            ),
            id="mypy-incomplete-definition",
        ),
        pytest.param(
            ("mypy", "values: dict = {}\n", "[type-arg]"), id="mypy-bare-generic"
        ),
        pytest.param(
            ("mypy", 'value: str = "typed"  # type: ignore\n', "[unused-ignore]"),
            id="mypy-unused-ignore",
        ),
        pytest.param(
            (
                "mypy",
                'from typing import cast\nvalue: str = "typed"\ncast(str, value)\n',
                "[redundant-cast]",
            ),
            id="mypy-redundant-cast",
        ),
        pytest.param(
            (
                "mypy",
                "def consume(value):\n    label: str = 1\n    return label\n",
                "[assignment]",
            ),
            id="mypy-untyped-body",
        ),
        pytest.param(
            (
                "mypy",
                "def consume(value: str = None) -> str:\n    return value\n",
                "[assignment]",
            ),
            id="mypy-implicit-optional",
        ),
        pytest.param(
            ("slotscheck", "class Parent:\n    __slots__ = ()\n", None),
            id="slots-valid",
        ),
        pytest.param(
            (
                "slotscheck",
                "import unavailable_configuration_probe_module\n",
                "Failed to import 'probe'",
            ),
            id="slots-import-failure",
        ),
        pytest.param(
            (
                "slotscheck",
                "class Parent:\n    pass\n\nclass Child(Parent):\n    __slots__ = ()\n",
                "defines slots but superclass does not",
            ),
            id="slots-superclass",
        ),
    ],
    indirect=True,
)
def test_tool_configuration_preserves_validation(tool_probe: ToolProbe) -> None:
    completed = tool_probe["completed"]
    diagnostic = tool_probe["diagnostic"]
    if diagnostic is None:
        assert completed.returncode == 0, completed.stdout + completed.stderr
    else:
        assert completed.returncode != 0
        assert diagnostic in completed.stdout + completed.stderr

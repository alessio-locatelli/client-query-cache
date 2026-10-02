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

    selected = dict(line.split("=") for line in completed.stdout.decode().splitlines())
    assert (
        f"python={selected['python']}\nformat={selected['format']}\n" == expected_stdout
    )


@pytest.mark.parametrize(
    ("changed_path", "python", "container", "benchmark", "formatting", "pins"),
    [
        ("Containerfile", False, True, False, False, True),
        (".python-version", True, True, True, False, True),
        ("tests/conftest.py", True, False, True, False, True),
        ("benchmarks/stream_cost/topology.py", True, False, True, False, True),
        (".github/actions/setup-toolchain/action.yml", True, False, True, True, True),
        (".github/workflows/test.yml", True, True, True, True, True),
        (".github/workflows/publish.yml", True, False, True, True, True),
        (".github/workflows/release-verification.yml", True, False, True, True, True),
        (".github/workflows/stream-cost-benchmark.yml", True, False, True, True, True),
        ("scripts/check_dev_container.sh", False, True, False, False, False),
        ("renovate.json5", False, False, False, True, True),
        ("docs/architecture.md", False, False, False, True, False),
    ],
    ids=[
        "container",
        "python",
        "test-mongodb",
        "benchmark-mongodb",
        "shared-tools",
        "pr-tools",
        "publish-tools",
        "release-tools",
        "benchmark-tools",
        "container-check",
        "renovate",
        "documentation",
    ],
)
def test_managed_inputs_select_consumers(
    changed_path: str,
    *,
    python: bool,
    container: bool,
    benchmark: bool,
    formatting: bool,
    pins: bool,
) -> None:
    completed = subprocess.run(
        (sys.executable, "-m", "scripts.ci_scope"),
        input=changed_path.encode() + b"\0",
        capture_output=True,
        check=True,
    )
    selected = dict(line.split("=") for line in completed.stdout.decode().splitlines())
    assert selected == {
        "pins": str(pins).lower(),
        "python": str(python).lower(),
        "container": str(container).lower(),
        "benchmark": str(benchmark).lower(),
        "format": str(formatting).lower(),
    }

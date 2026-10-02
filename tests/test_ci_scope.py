from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("changed_paths", "python", "formatting", "container", "benchmark"),
    [
        pytest.param(
            ("src/client_query_cache/core.py",),
            True,
            False,
            False,
            False,
            id="python-source",
        ),
        pytest.param(("README.md",), False, True, False, False, id="documentation"),
        pytest.param((".prettierrc",), False, True, False, False, id="prettier-config"),
        pytest.param(("notes.txt",), False, False, False, False, id="unrelated"),
        pytest.param(("justfile",), True, False, False, False, id="justfile"),
        pytest.param(
            (".github/workflows/test.yml",), True, True, False, False, id="pr-workflow"
        ),
        pytest.param(
            ("README.md", "src/client_query_cache/core.py", "Containerfile"),
            True,
            True,
            True,
            False,
            id="mixed",
        ),
        pytest.param(("Containerfile",), False, False, True, False, id="container"),
        pytest.param(
            (".python-version",), True, False, True, True, id="python-version"
        ),
        pytest.param(
            ("tests/conftest.py",),
            True,
            False,
            False,
            True,
            id="shared-pytest-fixtures",
        ),
        pytest.param(
            ("benchmarks/stream_cost/topology.py",),
            True,
            False,
            False,
            True,
            id="benchmark-mongodb",
        ),
        pytest.param(
            (".github/actions/setup-toolchain/action.yml",),
            True,
            True,
            False,
            True,
            id="shared-tools",
        ),
        pytest.param(
            (".github/workflows/publish.yml",),
            False,
            True,
            False,
            False,
            id="publish-tools",
        ),
        pytest.param(
            (".github/workflows/release-verification.yml",),
            False,
            True,
            False,
            False,
            id="release-tools",
        ),
        pytest.param(
            (".github/workflows/stream-cost-benchmark.yml",),
            False,
            True,
            False,
            False,
            id="benchmark-tools",
        ),
        pytest.param(
            ("benchmarks/stream_cost/guard_report.py",),
            True,
            False,
            False,
            False,
            id="benchmark-report",
        ),
        pytest.param(
            ("tests/benchmark/stream_cost/test_topology_integration.py",),
            True,
            False,
            False,
            True,
            id="startup-test",
        ),
        pytest.param(
            ("scripts/check_dev_container.sh",),
            False,
            False,
            True,
            False,
            id="container-check",
        ),
        pytest.param(("renovate.json5",), False, True, False, False, id="renovate"),
    ],
)
def test_ci_scope_selects_validation_tiers(
    changed_paths: tuple[str, ...],
    *,
    python: bool,
    formatting: bool,
    container: bool,
    benchmark: bool,
) -> None:
    completed = subprocess.run(
        (sys.executable, "-m", "scripts.ci_scope"),
        input=b"\0".join(path.encode() for path in changed_paths) + b"\0",
        capture_output=True,
        check=True,
    )

    selected = dict(line.split("=") for line in completed.stdout.decode().splitlines())
    assert selected == {
        "python": str(python).lower(),
        "format": str(formatting).lower(),
        "container": str(container).lower(),
        "benchmark": str(benchmark).lower(),
    }

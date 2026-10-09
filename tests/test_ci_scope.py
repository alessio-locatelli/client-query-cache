from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    (
        "changed_paths",
        "python",
        "formatting",
        "container",
        "benchmark",
        "documentation",
    ),
    [
        pytest.param(
            ("src/client_query_cache/core.py",),
            True,
            False,
            False,
            False,
            False,
            id="python-source",
        ),
        pytest.param(("README.md",), False, True, False, False, False, id="readme"),
        pytest.param(
            (".prettierrc",), False, True, False, False, False, id="prettier-config"
        ),
        pytest.param(("notes.txt",), False, False, False, False, False, id="unrelated"),
        pytest.param(("justfile",), True, False, False, False, True, id="justfile"),
        pytest.param(
            ("tox.ini",), True, False, False, False, False, id="minimum-driver-config"
        ),
        pytest.param(
            (".coveragerc",), True, False, False, False, False, id="coverage-config"
        ),
        pytest.param(
            (".github/workflows/test.yml",),
            True,
            True,
            False,
            False,
            True,
            id="pr-workflow",
        ),
        pytest.param(
            ("README.md", "src/client_query_cache/core.py", "Containerfile"),
            True,
            True,
            True,
            False,
            False,
            id="mixed",
        ),
        pytest.param(
            ("Containerfile",), False, False, True, False, False, id="container"
        ),
        pytest.param(
            (".python-version",), True, False, True, True, True, id="python-version"
        ),
        pytest.param(
            (".node-version",), False, True, True, False, False, id="node-version"
        ),
        pytest.param(
            ("tests/conftest.py",),
            True,
            False,
            False,
            True,
            False,
            id="shared-pytest-fixtures",
        ),
        pytest.param(
            ("benchmarks/stream_cost/topology.py",),
            True,
            False,
            False,
            True,
            False,
            id="benchmark-mongodb",
        ),
        pytest.param(
            (".github/actions/setup-toolchain/action.yml",),
            True,
            True,
            False,
            True,
            True,
            id="shared-tools",
        ),
        pytest.param(
            (".github/workflows/publish.yml",),
            False,
            True,
            False,
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
            False,
            id="release-tools",
        ),
        pytest.param(
            (".github/workflows/stream-cost-benchmark.yml",),
            False,
            True,
            False,
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
            False,
            id="benchmark-report",
        ),
        pytest.param(
            ("tests/benchmark/stream_cost/test_topology_integration.py",),
            True,
            False,
            False,
            True,
            False,
            id="startup-test",
        ),
        pytest.param(
            ("scripts/check_dev_container.sh",),
            False,
            False,
            True,
            False,
            False,
            id="container-check",
        ),
        pytest.param(
            ("renovate.json5",), False, True, False, False, False, id="renovate"
        ),
        pytest.param(
            ("docs/user/reference/api.md",), False, True, False, False, True, id="guide"
        ),
        pytest.param(
            ("docs/user/assets/figure.svg",),
            False,
            False,
            False,
            False,
            True,
            id="asset",
        ),
        pytest.param(
            ("examples/README.md",),
            False,
            True,
            False,
            False,
            True,
            id="examples-readme",
        ),
        pytest.param(
            ("zensical.toml",), False, False, False, False, True, id="site-config"
        ),
        pytest.param(
            ("pyproject.toml",), True, False, False, True, True, id="dependencies"
        ),
        pytest.param(("uv.lock",), True, False, False, True, True, id="lockfile"),
        pytest.param(
            ("docker-compose.yaml",), True, True, False, True, False, id="compose-image"
        ),
        pytest.param(
            ("scripts/build_versioned_docs.py",),
            True,
            False,
            False,
            False,
            True,
            id="edition-builder",
        ),
        pytest.param(
            ("scripts/ci_scope.py",),
            True,
            False,
            False,
            False,
            False,
            id="scope-script",
        ),
        pytest.param(
            (".github/workflows/docs.yml",),
            False,
            True,
            False,
            False,
            True,
            id="docs-workflow",
        ),
        *[
            pytest.param((path,), False, True, False, False, False, id=path)
            for path in (
                "docs/development/index.md",
                "docs/development/architecture.md",
                "docs/development/performance-regression-guard.md",
                "docs/development/pypi-publishing-setup.md",
                "docs/development/ci-validation-caches.md",
                "docs/development/executable-version-updates.md",
                "docs/development/research/causal-invalidation-barrier.md",
                "docs/development/decisions/defer-causal-invalidation-barrier.md",
            )
        ],
        *[
            pytest.param((path,), False, True, False, False, True, id=path)
            for path in (
                "docs/user/getting-started/asyncio.md",
                "docs/user/usage/consistency.md",
                "docs/user/benchmarks/stream-cost.md",
                "docs/user/examples/index.md",
                "docs/user/operations/monitoring.md",
            )
        ],
        *[
            pytest.param((path,), True, False, False, False, True, id=path)
            for path in (
                "examples/requests_cache_example.py",
                "examples/celery_example.py",
                "examples/py_abac_example.py",
            )
        ],
        pytest.param(
            ("docs/development/architecture.md", "docs/user/reference/api.md"),
            False,
            True,
            False,
            False,
            True,
            id="mixed-documentation",
        ),
        pytest.param(
            ("docs/development/index.md", "examples/celery_example.py"),
            True,
            True,
            False,
            False,
            True,
            id="development-and-example",
        ),
        pytest.param((), False, False, False, False, False, id="empty"),
    ],
)
def test_ci_scope_selects_validation_tiers(
    changed_paths: tuple[str, ...],
    *,
    python: bool,
    formatting: bool,
    container: bool,
    benchmark: bool,
    documentation: bool,
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
        "documentation": str(documentation).lower(),
    }

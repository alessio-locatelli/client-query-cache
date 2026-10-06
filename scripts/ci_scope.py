"""Select pull request checks from changed repository paths."""

from __future__ import annotations

import sys


def main() -> None:
    paths = [
        path.decode("utf-8", "surrogateescape")
        for path in sys.stdin.buffer.read().split(b"\0")
        if path
    ]
    python = any(
        path.endswith(".py")
        or path
        in {
            "pytest.ini",
            "docker-compose.yaml",
            ".coveragerc",
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            "justfile",
            ".github/workflows/test.yml",
            "scripts/ci_scope.py",
        }
        or path.startswith(".github/actions/setup-toolchain/")
        for path in paths
    )
    documentation = any(
        path.startswith(("docs/user/", ".github/actions/setup-toolchain/"))
        or path == "examples/README.md"
        or (path.startswith("examples/") and path.endswith(".py"))
        or path
        in {
            "zensical.toml",
            "stable-docs.toml",
            "scripts/build_versioned_docs.py",
            ".github/workflows/test.yml",
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            "justfile",
            ".github/workflows/docs.yml",
        }
        for path in paths
    )
    formatting = any(
        path.endswith((".json", ".json5", ".jsonc", ".md", ".yaml", ".yml"))
        or path in {".node-version", ".prettierignore", ".prettierrc"}
        for path in paths
    )
    container = any(
        path
        in {
            "Containerfile",
            ".node-version",
            ".python-version",
            "scripts/check_dev_container.sh",
        }
        for path in paths
    )
    benchmark = any(
        path
        in {
            "tests/conftest.py",
            "docker-compose.yaml",
            ".python-version",
            "pyproject.toml",
            "uv.lock",
            "benchmarks/stream_cost/topology.py",
            "tests/benchmark/stream_cost/test_topology_integration.py",
        }
        or path.startswith(".github/actions/setup-toolchain/")
        for path in paths
    )
    print(f"documentation={str(documentation).lower()}")
    print(f"container={str(container).lower()}")
    print(f"benchmark={str(benchmark).lower()}")
    print(f"python={str(python).lower()}")
    print(f"format={str(formatting).lower()}")


if __name__ == "__main__":
    main()

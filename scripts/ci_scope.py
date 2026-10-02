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
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            "justfile",
            ".github/workflows/test.yml",
            ".github/workflows/publish.yml",
            ".github/workflows/release-verification.yml",
            ".github/workflows/stream-cost-benchmark.yml",
            "scripts/ci_scope.py",
        }
        or path.startswith(".github/actions/setup-toolchain/")
        for path in paths
    )
    pins = any(
        path
        in {
            "renovate.json5",
            "scripts/check_executable_pins.cjs",
            "Containerfile",
            ".python-version",
            "tests/conftest.py",
            "benchmarks/stream_cost/topology.py",
            ".github/workflows/test.yml",
            ".github/workflows/publish.yml",
            ".github/workflows/release-verification.yml",
            ".github/workflows/stream-cost-benchmark.yml",
        }
        or path.startswith(".github/actions/setup-toolchain/")
        for path in paths
    )
    formatting = any(
        path.endswith((".json", ".json5", ".jsonc", ".md", ".yaml", ".yml"))
        or path in {".prettierignore", ".prettierrc"}
        for path in paths
    )
    container = any(
        path
        in {
            "Containerfile",
            ".python-version",
            "scripts/check_dev_container.sh",
            ".github/workflows/test.yml",
        }
        for path in paths
    )
    benchmark = any(
        path
        in {
            "tests/conftest.py",
            ".python-version",
            "pyproject.toml",
            "uv.lock",
            ".github/workflows/test.yml",
            ".github/workflows/publish.yml",
            ".github/workflows/release-verification.yml",
            ".github/workflows/stream-cost-benchmark.yml",
        }
        or path.startswith(
            ("benchmarks/stream_cost/", ".github/actions/setup-toolchain/")
        )
        for path in paths
    )
    print(f"pins={str(pins).lower()}")
    print(f"container={str(container).lower()}")
    print(f"benchmark={str(benchmark).lower()}")
    print(f"python={str(python).lower()}")
    print(f"format={str(formatting).lower()}")


if __name__ == "__main__":
    main()

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
            "justfile",
            ".github/workflows/test.yml",
            "scripts/ci_scope.py",
        }
        or path.startswith(".github/actions/setup-toolchain/")
        for path in paths
    )
    formatting = any(
        path.endswith((".json", ".jsonc", ".md", ".yaml", ".yml"))
        or path in {".prettierignore", ".prettierrc"}
        for path in paths
    )
    print(f"python={str(python).lower()}")
    print(f"format={str(formatting).lower()}")


if __name__ == "__main__":
    main()

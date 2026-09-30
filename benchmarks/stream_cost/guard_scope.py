from __future__ import annotations

import fnmatch
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_RELEVANT_PATTERNS = (
    "*.py",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/test.yml",
)


def changed_files_require_guard(paths: Sequence[str]) -> bool:
    return any(
        fnmatch.fnmatch(path, pattern)
        for path in paths
        for pattern in _RELEVANT_PATTERNS
    )


def main() -> None:
    paths = [line for line in sys.stdin.read().splitlines() if line]
    print("true" if changed_files_require_guard(paths) else "false")


if __name__ == "__main__":
    main()

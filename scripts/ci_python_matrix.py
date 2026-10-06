"""Select exact minimum/development Python and intermediate compatibility lines."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


def main() -> None:
    minimum = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["requires-python"].removeprefix(">=")
    selected = Path(".python-version").read_text(encoding="utf-8").strip()
    first_major, first_minor, *_ = map(int, minimum.split("."))
    last_major, last_minor, *_ = map(int, selected.split("."))
    assert first_major == last_major, (
        "A Python language-major transition needs a compatibility decision"
    )
    versions = (
        minimum,
        *(f"{first_major}.{minor}" for minor in range(first_minor + 1, last_minor)),
        selected,
    )
    print(f"versions={json.dumps(tuple(dict.fromkeys(versions)))}")


if __name__ == "__main__":
    main()

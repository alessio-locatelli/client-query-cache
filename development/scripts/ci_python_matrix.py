"""Select exact minimum/development Python and classified compatibility lines."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def main() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    minimum = project["requires-python"].removeprefix(">=")
    if minimum.count(".") == 1:
        minimum = f"{minimum}.0"
    selected = Path(".python-version").read_text(encoding="utf-8").strip()
    first_major, first_minor, *_ = map(int, minimum.split("."))
    selected_major, selected_minor, *_ = map(int, selected.split("."))
    last_major, last_minor = max(
        (
            (selected_major, selected_minor),
            *(
                tuple(map(int, match.groups()))
                for classifier in project["classifiers"]
                if (
                    match := re.fullmatch(
                        r"Programming Language :: Python :: (\d+)\.(\d+)", classifier
                    )
                )
            ),
        )
    )
    assert first_major == selected_major == last_major, (
        "A Python language-major transition needs a compatibility decision"
    )
    versions = (
        minimum,
        *(
            f"{first_major}.{minor}"
            for minor in range(first_minor + 1, last_minor + 1)
            if minor != selected_minor
        ),
        selected,
    )
    print(f"versions={json.dumps(tuple(dict.fromkeys(versions)))}")


if __name__ == "__main__":
    main()

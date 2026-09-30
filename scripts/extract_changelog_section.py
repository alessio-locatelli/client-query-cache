import re
import sys
from pathlib import Path


def extract_section(changelog: str, version: str) -> str:
    heading = re.search(rf"^## \[{re.escape(version)}\].*$", changelog, re.MULTILINE)
    if heading is None:
        message = f"No CHANGELOG.md section found for version {version}"
        raise SystemExit(message)
    body_start = heading.end()
    next_heading = re.search(r"^## ", changelog[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(changelog)
    return changelog[body_start:body_end].strip("\n")


if __name__ == "__main__":
    print(
        extract_section(Path("CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[1])
    )

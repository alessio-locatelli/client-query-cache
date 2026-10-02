"""Reject missing local targets in the generated documentation HTML."""

from __future__ import annotations

import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class AssetTargets(HTMLParser):
    def __init__(self, page: Path, site: Path, prefix: str) -> None:
        super().__init__()
        self.page = page
        self.site = site.resolve()
        self.prefix = prefix
        self.missing: set[Path] = set()

    def handle_starttag(
        self,
        _tag: str,
        attrs: list[tuple[str, str | None]],  # Can be empty.
    ) -> None:
        for name, value in attrs:
            if name not in {"src", "href"} or not value:
                continue
            target = urlsplit(value)
            if target.scheme or target.netloc or not target.path:
                continue
            target_path = unquote(target.path)
            if target_path.startswith("/"):
                if not target_path.startswith(self.prefix):
                    self.missing.add(Path(target_path))
                    continue
                resolved = self.site / target_path.removeprefix(self.prefix).lstrip("/")
            else:
                resolved = self.page.parent / target_path
            if resolved.is_dir():
                resolved /= "index.html"
            resolved = resolved.resolve()
            if not resolved.is_relative_to(self.site) or not resolved.is_file():
                self.missing.add(resolved)


def main() -> None:
    with Path("zensical.toml").open("rb") as config:
        project = tomllib.load(config)["project"]
    site = Path(project["site_dir"])
    prefix = urlsplit(project["site_url"]).path
    missing = False
    pages = tuple(site.rglob("*.html"))
    if not pages:
        sys.exit(f"Documentation output contains no HTML pages: {site}")
    for page in pages:
        parser = AssetTargets(page, site, prefix)
        parser.feed(page.read_text())
        for target in sorted(parser.missing):
            print(f"{page}: missing local target {target}", file=sys.stderr)
            missing = True
    sys.exit(int(missing))


if __name__ == "__main__":
    main()

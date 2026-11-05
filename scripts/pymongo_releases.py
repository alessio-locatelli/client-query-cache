from __future__ import annotations

import json
import sys
from importlib.metadata import requires, version
from typing import TYPE_CHECKING, Any

from packaging.requirements import Requirement
from packaging.version import Version

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from packaging.specifiers import SpecifierSet


def select_releases(
    releases: Mapping[str, Sequence[Mapping[str, Any]]],
    specifier: SpecifierSet,
    excluded: Collection[Version],
) -> list[Version]:
    selected = []
    for name, files in releases.items():
        release = Version(name)
        if (
            release.is_prerelease
            or release in excluded
            or release not in specifier
            or not files
            or all(file["yanked"] for file in files)
        ):
            continue
        selected.append(release)
    return sorted(selected)


def main() -> None:
    try:
        listing = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit("The PyPI release listing is not valid JSON.")
    try:
        releases = listing["releases"]
    except KeyError:
        sys.exit("The PyPI release listing has no 'releases' key.")
    requirement = next(
        (
            item
            for item in map(Requirement, requires("client-query-cache") or ())
            if item.name == "pymongo"
        ),
        None,
    )
    if requirement is None:
        sys.exit("client-query-cache does not declare a pymongo requirement.")
    minimum = Version(
        next(item.version for item in requirement.specifier if item.operator == ">=")
    )
    if minimum not in map(Version, releases):
        sys.exit(f"The PyPI release listing lacks the declared minimum {minimum}.")
    for release in select_releases(
        releases, requirement.specifier, {minimum, Version(version("pymongo"))}
    ):
        print(release)


if __name__ == "__main__":
    main()

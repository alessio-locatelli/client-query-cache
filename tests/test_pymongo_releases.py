from __future__ import annotations

import subprocess
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from client_query_cache._types import NonEmptyStr
from scripts.pymongo_releases import select_releases

pytestmark = pytest.mark.unit

_FILES = [{"yanked": False}]

_RELEASE_NAMES = st.builds(
    "{}.{}.{}{}".format,
    st.integers(min_value=3, max_value=5),
    st.integers(min_value=0, max_value=20),
    st.integers(min_value=0, max_value=20),
    st.sampled_from(["", "a1", "b1", "rc1", ".dev0"]),
)
_LISTED_FILES = st.lists(st.fixed_dictionaries({"yanked": st.booleans()}), max_size=2)
_SPECIFIER = SpecifierSet(">=4.2.0,!=4.7.3,<5")


@pytest.mark.parametrize(
    ("releases", "specifier", "excluded", "expected"),
    [
        pytest.param(
            {"4.10.0": _FILES, "4.2.0": _FILES, "4.3.0": _FILES},
            ">=4.1",
            set[str](),
            ["4.2.0", "4.3.0", "4.10.0"],
            id="ascending-pep440-order",
        ),
        pytest.param(
            {"4.1.0": _FILES, "4.2.0": _FILES, "4.3.0": _FILES},
            ">=4.1",
            {"4.1.0", "4.3.0"},
            ["4.2.0"],
            id="minimum-and-locked-excluded",
        ),
        pytest.param(
            {"4.1.0": _FILES, "4.3.0": _FILES},
            ">=4.1",
            {"4.1.0", "4.3.0"},
            [],
            id="only-minimum-and-locked-in-range",
        ),
        pytest.param(
            {
                "4.2.0": _FILES,
                "4.3.0rc1": _FILES,
                "4.3.0b1": _FILES,
                "4.3.0a1": _FILES,
                "4.3.0.dev0": _FILES,
            },
            ">=4.1",
            set[str](),
            ["4.2.0"],
            id="pre-releases-skipped",
        ),
        pytest.param(
            {"4.2.0": _FILES, "4.3.0": [{"yanked": True}]},
            ">=4.1",
            set[str](),
            ["4.2.0"],
            id="yanked-skipped",
        ),
        pytest.param(
            {"4.2.0": _FILES, "4.3.0": []},
            ">=4.1",
            set[str](),
            ["4.2.0"],
            id="without-files-skipped",
        ),
        pytest.param(
            {"4.2.0": _FILES, "4.3.0": _FILES},
            ">=4.1,!=4.2.0",
            set[str](),
            ["4.3.0"],
            id="not-equal-clause-removes-release",
        ),
        pytest.param(
            {"4.0.0": _FILES, "4.2.0": _FILES, "5.0.0": _FILES},
            ">=4.1,<5",
            set[str](),
            ["4.2.0"],
            id="outside-range-skipped",
        ),
    ],
)
def test_select_releases(
    releases: dict[str, list[dict[str, bool]]],
    specifier: NonEmptyStr,
    excluded: set[str],
    expected: list[str],
) -> None:
    selected = select_releases(
        releases, SpecifierSet(specifier), {Version(name) for name in excluded}
    )
    assert [str(release) for release in selected] == expected


@given(
    releases=st.dictionaries(_RELEASE_NAMES, _LISTED_FILES),
    excluded=st.sets(_RELEASE_NAMES.map(Version)),
)
def test_selected_releases_are_ascending_and_eligible(
    releases: dict[str, list[dict[str, bool]]], excluded: set[Version]
) -> None:
    selected = select_releases(releases, _SPECIFIER, excluded)
    assert selected == sorted(set(selected))
    for release in selected:
        assert not release.is_prerelease
        assert release not in excluded
        assert release in _SPECIFIER
        assert not all(file["yanked"] for file in releases[str(release)])


@pytest.mark.parametrize(
    ("stdin", "message"),
    [
        pytest.param(b"{", "not valid JSON", id="invalid-json"),
        pytest.param(b"{}", "no 'releases' key", id="missing-releases"),
        pytest.param(
            b'{"releases": {}}', "lacks the declared minimum", id="empty-listing"
        ),
    ],
)
def test_unusable_listing_fails_with_message(
    stdin: bytes, message: NonEmptyStr
) -> None:
    completed = subprocess.run(
        (sys.executable, "-m", "scripts.pymongo_releases"),
        input=stdin,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert message in completed.stderr.decode()

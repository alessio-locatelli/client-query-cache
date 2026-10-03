from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from scripts.build_versioned_docs import (
    Sources,
    Text,
    assemble,
    git,
    resolve,
    run,
    select_sources,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def commit(repo: Path) -> Text:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Fixture snapshot")
    return resolve(repo, "HEAD")


def record_backport(repo: Path, source: Text, tag: Text = "v0.2.0") -> None:
    (repo / "stable-docs.toml").write_text(
        f'[backports."{tag}"]\nsource = "{source}"\n'
    )


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    run(repo, "git", "init", "-q")
    for key, value in (
        ("commit.gpgsign", "false"),
        ("user.name", "Docs fixture"),
        ("user.email", "docs@example.invalid"),
    ):
        git(repo, "config", "--local", key, value)
    (repo / "src/client_query_cache").mkdir(parents=True)
    (repo / "src/client_query_cache/__init__.py").write_text('VERSION = "released"\n')
    (repo / "examples").mkdir()
    (repo / "examples/example.py").write_text('print("released")\n')
    (repo / "examples/README.md").write_text("# Released examples\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.2.0"\n'
    )
    (repo / "docs/user").mkdir(parents=True)
    (repo / "docs/user/index.md").write_text("# Released guide\n")
    (repo / "docs/user/guide.md").write_text("# Guide\n")
    (repo / "zensical.toml").write_text("""[project]
site_name = "Fixture"
site_url = "https://example.invalid/library/"
repo_url = "https://github.com/alessio-locatelli/client-query-cache"
docs_dir = "docs/user"
site_dir = "site"
strict = true
[project.theme]
font = false
[project.validation]
invalid_links = true
invalid_link_anchors = true
[project.markdown_extensions.pymdownx.snippets]
base_path = ["."]
check_paths = true
restrict_base_path = true
[project.plugins.redirects.redirect_maps]
""")
    commit(repo)
    git(repo, "tag", "--no-sign", "v0.2.0")
    (repo / "docs/user/index.md").write_text("# Corrected guide\n")
    record_backport(repo, commit(repo))
    return repo


@pytest.fixture
def selection_sources(release_repo: Path, request: pytest.FixtureRequest) -> Sources:
    correction = resolve(release_repo, "HEAD")
    if request.param == "release":
        (release_repo / "stable-docs.toml").write_text("[backports]\n")
    elif request.param == "different-tag":
        record_backport(release_repo, correction, "v0.1.0")
    (release_repo / "src/client_query_cache/__init__.py").write_text(
        'VERSION = "development"\n'
    )
    return Sources(
        release=resolve(release_repo, "refs/tags/v0.2.0"),
        stable=correction
        if request.param == "backport"
        else resolve(release_repo, "refs/tags/v0.2.0"),
        development=commit(release_repo),
        version="0.2.0",
    )


@pytest.mark.parametrize(
    "selection_sources", ["release", "backport", "different-tag"], indirect=True
)
def test_selects_exact_release_and_independent_development(
    release_repo: Path, selection_sources: Sources
) -> None:
    assert select_sources(release_repo, "v0.2.0", "HEAD") == selection_sources


@pytest.fixture
def incompatible_backport(release_repo: Path, request: pytest.FixtureRequest) -> None:
    path, replacement = request.param
    (release_repo / path).write_text(replacement)
    record_backport(release_repo, commit(release_repo))


@pytest.mark.parametrize(
    "incompatible_backport",
    [
        pytest.param(
            ("src/client_query_cache/__init__.py", 'VERSION = "unreleased"\n'),
            id="runtime",
        ),
        pytest.param(
            ("examples/example.py", 'print("unreleased")\n'), id="executable-example"
        ),
        pytest.param(
            ("pyproject.toml", '[project]\nname = "changed"\nversion = "0.2.0"\n'),
            id="project-metadata",
        ),
    ],
    indirect=True,
)
@pytest.mark.usefixtures("incompatible_backport")
def test_rejects_incompatible_backport(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="differs from the released"):
        select_sources(release_repo, "v0.2.0", "HEAD")


@pytest.fixture
def mutable_backport(release_repo: Path, request: pytest.FixtureRequest) -> None:
    record_backport(release_repo, request.param)


@pytest.mark.parametrize("mutable_backport", ["HEAD", "main", "v0.2.0"], indirect=True)
@pytest.mark.usefixtures("mutable_backport")
def test_rejects_mutable_backport_provenance(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="immutable commit SHA"):
        select_sources(release_repo, "v0.2.0", "HEAD")


@pytest.mark.parametrize("tag", ["HEAD", "main", "v0.2.0rc1"])
def test_requires_exact_stable_release_tag(release_repo: Path, tag: Text) -> None:
    with pytest.raises(ValueError, match=r"exact vX\.Y\.Z"):
        select_sources(release_repo, tag, "HEAD")


@pytest.fixture
def mismatched_release(release_repo: Path) -> None:
    git(release_repo, "tag", "--no-sign", "v0.3.0")


@pytest.mark.usefixtures("mismatched_release")
def test_rejects_release_version_mismatch(release_repo: Path) -> None:
    with pytest.raises(ValueError, match="tag and package version disagree"):
        select_sources(release_repo, "v0.3.0", "HEAD")


@pytest.fixture
def previous_artifact(release_repo: Path) -> Path:
    output = release_repo / "site"
    output.mkdir()
    (output / "previous.txt").write_text("Previous complete artifact\n")
    return output


@pytest.fixture
def failed_edition(
    release_repo: Path, request: pytest.FixtureRequest
) -> type[Exception]:
    if request.param == "heading":
        (release_repo / "docs/user/index.md").write_text(
            "# Invalid guide\n\n[Missing heading](#absent)\n"
        )
    else:
        git(release_repo, "rm", "-q", "docs/user/index.md")
    commit(release_repo)
    return subprocess.CalledProcessError if request.param == "heading" else ValueError


@pytest.mark.parametrize("failed_edition", ["heading", "layout"], indirect=True)
def test_failed_edition_preserves_previous_artifact(
    release_repo: Path, previous_artifact: Path, failed_edition: type[Exception]
) -> None:
    sources = select_sources(release_repo, "v0.2.0", "HEAD")
    with pytest.raises(failed_edition):
        assemble(release_repo, sources, previous_artifact)
    assert tuple(previous_artifact.iterdir()) == (previous_artifact / "previous.txt",)
    assert (
        previous_artifact / "previous.txt"
    ).read_text() == "Previous complete artifact\n"


@pytest.fixture
def development_only_edition(release_repo: Path) -> None:
    (release_repo / "docs/user/index.md").write_text("# DevelopmentOnlyToken\n")
    (release_repo / "docs/user/preview.md").write_text("# UnreleasedPageToken\n")
    with (release_repo / "zensical.toml").open("a") as configuration:
        configuration.write('[project.extra.version]\nprovider = "mike"\n')
    commit(release_repo)


@pytest.mark.usefixtures("development_only_edition")
@pytest.mark.parametrize(
    "artifact_name", ["site", "fresh-site"], ids=["replace-artifact", "first-build"]
)
def test_assembles_independent_snapshots_with_development_only_page(
    release_repo: Path, previous_artifact: Path, artifact_name: Text
) -> None:
    output = (
        previous_artifact if artifact_name == "site" else release_repo / artifact_name
    )
    sources = select_sources(release_repo, "v0.2.0", "HEAD")
    assemble(release_repo, sources, output)
    assert "Corrected guide" in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" not in (output / "stable/index.html").read_text()
    assert "DevelopmentOnlyToken" in (output / "dev/index.html").read_text()
    assert not (output / "stable/preview/index.html").exists()
    assert "UnreleasedPageToken" in (output / "dev/preview/index.html").read_text()
    assert "stable" in (output / "preview/index.html").read_text()
    assert "stable/guide" in (output / "guide/index.html").read_text()
    assert not (output / "previous.txt").exists()


@pytest.fixture
def linked_artifact(release_repo: Path) -> Path:
    target = release_repo / "existing-artifact"
    target.mkdir()
    output = release_repo / "site"
    output.symlink_to(target, target_is_directory=True)
    return output


def test_rejects_linked_artifact_without_changing_it(
    release_repo: Path, linked_artifact: Path
) -> None:
    with pytest.raises(ValueError, match="symbolic link"):
        assemble(
            release_repo,
            select_sources(release_repo, "v0.2.0", "HEAD"),
            linked_artifact,
        )
    assert linked_artifact.is_symlink()
    assert tuple(linked_artifact.iterdir()) == ()
